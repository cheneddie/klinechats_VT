from __future__ import annotations

"""Run the synthetic MTX fixture through the persisted Strategy Lab pipeline.

SYNTHETIC DATA ONLY. This validates integration and physical execution plumbing;
it is never market-edge evidence.
"""

import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from tools.synthetic_mtx_demo import (
    BACKTEST_ID,
    CONTRACT,
    DAY,
    MR_CHAIN,
    RUN_ID,
    SOURCE_FILE,
    _entry_seq,
    _sha256,
    generate_parquet,
    seed_research_run,
)
from server.v4_replay_final import read_tick_path
from server.v5.backtest import run_backtest
from server.v5.execution import ExecutionModel
from server.v5.optimizer import run_optimization
from server.v5.portfolio import PortfolioPolicy
from server.v5.storage import connect, create_research_run, freeze_run, tx, verify_run_digest
from server.v5.strategy_registry import load_strategy

OVERLAP_RUN_ID = "synthetic-mtx-portfolio-overlap-v1"
OVERLAP_INDEPENDENT_BT = "bt-synthetic-mtx-overlap-independent-v1"
OVERLAP_SINGLE_BT = "bt-synthetic-mtx-overlap-single-v1"


def _seed_overlap_run(event_db: Path, frame: pd.DataFrame) -> None:
    create_research_run(
        event_db,
        OVERLAP_RUN_ID,
        "DISCOVERY",
        [2025],
        scanner_version="SYNTHETIC_PORTFOLIO_V1",
        strategy_version="MR_BROAD_V3",
        notes="SYNTHETIC DATA ONLY - overlapping causal events for portfolio arbitration QA",
    )
    specs = [
        {
            "event_id": "SYN-PF-A",
            "direction": "long",
            "time": f"{DAY} 09:10:10",
            "entry": 20020.0,
            "stop": 19990.0,
            "target": 20040.0,
            "regime": "SYNTHETIC_PORTFOLIO_PRIMARY",
        },
        {
            "event_id": "SYN-PF-B",
            "direction": "long",
            "time": f"{DAY} 09:11:10",
            "entry": 20021.0,
            "stop": 19990.0,
            "target": 20040.0,
            "regime": "SYNTHETIC_PORTFOLIO_OVERLAP",
        },
    ]
    with tx(event_db) as c:
        for spec in specs:
            seq = _entry_seq(frame, spec["time"])
            dt = pd.Timestamp(spec["time"])
            payload = {"lvn": spec["entry"], "synthetic": True, "fixture": spec["regime"]}
            c.execute(
                """INSERT INTO events(
                  research_run_id,event_id,source_file,year,trading_date,contract,strategy,direction,result,difficulty,
                  attempt_start_seq,attempt_start_time,entry_seq,entry_time,entry_price,stop,target,
                  features_json,nodes_json,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    OVERLAP_RUN_ID,
                    spec["event_id"],
                    SOURCE_FILE,
                    2025,
                    DAY,
                    CONTRACT,
                    "MR",
                    spec["direction"],
                    "ENTRY",
                    2,
                    max(0, seq - 15),
                    (dt - pd.Timedelta(seconds=15)).isoformat(),
                    seq,
                    dt.isoformat(),
                    spec["entry"],
                    spec["stop"],
                    spec["target"],
                    json.dumps({"market_regime": spec["regime"], "synthetic": True}, sort_keys=True),
                    "{}",
                    json.dumps(payload, sort_keys=True),
                ),
            )
            first_decision = max(0, seq - len(MR_CHAIN))
            for i, node_id in enumerate(MR_CHAIN):
                decision_seq = first_decision + i
                decision_time = frame.iloc[decision_seq]["datetime"]
                decision_price = float(frame.iloc[decision_seq]["price"])
                c.execute(
                    """INSERT INTO event_nodes(
                      research_run_id,event_id,node_id,evaluation_state,answer,
                      decision_seq,decision_time,decision_price,anchor_seq,anchor_time,anchor_price,
                      resolution_seq,resolution_time,resolution_price,parent_node_id,reason_code,metrics_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        OVERLAP_RUN_ID,
                        spec["event_id"],
                        node_id,
                        "EVALUATED",
                        1,
                        decision_seq,
                        pd.Timestamp(decision_time).isoformat(),
                        decision_price,
                        decision_seq,
                        pd.Timestamp(decision_time).isoformat(),
                        decision_price,
                        decision_seq,
                        pd.Timestamp(decision_time).isoformat(),
                        decision_price,
                        MR_CHAIN[i - 1] if i else "CTX_VALUE",
                        "SYNTHETIC_PASS",
                        json.dumps({"synthetic": True}, sort_keys=True),
                    ),
                )
    freeze_run(event_db, OVERLAP_RUN_ID)
    verified = verify_run_digest(event_db, OVERLAP_RUN_ID)
    if not verified.get("valid"):
        raise RuntimeError(f"synthetic overlap research digest invalid: {verified}")


def _portfolio_overlap_proof(
    event_db: Path,
    data_root: Path,
    frame: pd.DataFrame,
    strategy,
    execution: ExecutionModel,
    code_commit: str | None,
) -> dict:
    _seed_overlap_run(event_db, frame)
    independent_policy = PortfolioPolicy()
    single_policy = PortfolioPolicy(mode="SINGLE_POSITION", overlap_policy="SKIP_WHILE_OPEN")

    independent = run_backtest(
        event_db,
        data_root,
        OVERLAP_RUN_ID,
        strategy,
        execution_model=execution,
        portfolio_policy=independent_policy,
        bootstrap_reps=300,
        backtest_run_id=OVERLAP_INDEPENDENT_BT,
        code_commit=code_commit,
        notes="SYNTHETIC DATA ONLY - overlapping signals with independent-event policy",
    )
    single = run_backtest(
        event_db,
        data_root,
        OVERLAP_RUN_ID,
        strategy,
        execution_model=execution,
        portfolio_policy=single_policy,
        bootstrap_reps=300,
        backtest_run_id=OVERLAP_SINGLE_BT,
        code_commit=code_commit,
        notes="SYNTHETIC DATA ONLY - overlapping signals with single-position policy",
    )

    independent_n = int(independent.get("trades") or 0)
    single_n = int(single.get("trades") or 0)
    skips = list((single.get("report") or {}).get("portfolio_skips") or [])
    if independent_n != 2:
        raise RuntimeError(f"independent portfolio proof expected 2 trades, got {independent_n}")
    if single_n != 1:
        raise RuntimeError(f"single-position portfolio proof expected 1 trade, got {single_n}")
    if len(skips) != 1 or skips[0].get("reason") != "PORTFOLIO_OVERLAP":
        raise RuntimeError(f"single-position overlap audit mismatch: {skips}")
    if skips[0].get("trade_id") != "SYN-PF-B:1570":
        raise RuntimeError(f"unexpected skipped overlap trade: {skips[0]}")

    verified = verify_run_digest(event_db, OVERLAP_RUN_ID)
    if not verified.get("valid"):
        raise RuntimeError(f"overlap research digest invalid after backtests: {verified}")

    return {
        "research_run_id": OVERLAP_RUN_ID,
        "research_digest": verified.get("digest"),
        "independent": {
            "backtest_run_id": independent.get("backtest_run_id"),
            "trades": independent_n,
            "portfolio_policy": independent.get("portfolio_policy"),
            "portfolio_policy_hash": independent.get("portfolio_policy_hash"),
        },
        "single_position": {
            "backtest_run_id": single.get("backtest_run_id"),
            "trades": single_n,
            "portfolio_policy": single.get("portfolio_policy"),
            "portfolio_policy_hash": single.get("portfolio_policy_hash"),
            "portfolio_skips": skips,
        },
        "assertion": "INDEPENDENT_EVENT executes both overlapping causal signals; SINGLE_POSITION executes the first and audits the second as PORTFOLIO_OVERLAP",
    }


def run_demo(data_root: Path, event_db: Path, out_dir: Path, code_commit: str | None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path, frame = generate_parquet(data_root)
    specs = seed_research_run(event_db, frame)

    strategy_path = Path(__file__).resolve().parents[1] / "config" / "strategies" / "MR_BROAD_V3.json"
    strategy = load_strategy(strategy_path)
    execution = ExecutionModel(
        execution_model_id="SYNTHETIC_PHYSICAL",
        version="V1",
        fill_timing="SIGNAL",
        entry_slippage_points=0.25,
        exit_slippage_points=0.25,
        commission_points_per_side=0.10,
        latency_ms=0,
    )

    # Exercise the production physical reader. `_seq` must be reconstructed from
    # Parquet physical row order rather than being supplied by the fixture.
    probe_event = {"source_file": SOURCE_FILE, "trading_date": DAY, "contract": CONTRACT}
    probe = read_tick_path(data_root, probe_event, 0, 0)
    if len(probe) != len(frame):
        raise RuntimeError(f"physical replay row mismatch: parquet={len(frame)} replay={len(probe)}")
    if int(probe["_seq"].iloc[0]) != 0 or int(probe["_seq"].iloc[-1]) != len(frame) - 1:
        raise RuntimeError("physical replay did not preserve source row order")
    if not bool((probe["_seq"].diff().fillna(1) > 0).all()):
        raise RuntimeError("physical replay _seq is not strictly increasing")

    bt = run_backtest(
        event_db,
        data_root,
        RUN_ID,
        strategy,
        execution_model=execution,
        bootstrap_reps=400,
        backtest_run_id=BACKTEST_ID,
        code_commit=code_commit,
        notes="SYNTHETIC DATA ONLY - end-to-end physical parquet demo",
    )

    # `run_backtest` intentionally returns a compact immutable-run summary where
    # `trades` is a count. Read the persisted immutable ledger for row-level QA.
    c = connect(event_db)
    try:
        trades = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM backtest_trades WHERE backtest_run_id=? ORDER BY trading_date,entry_seq,trade_id",
                (BACKTEST_ID,),
            ).fetchall()
        ]
    finally:
        c.close()

    if int(bt.get("trades") or 0) != len(trades):
        raise RuntimeError(f"backtest count/ledger mismatch: summary={bt.get('trades')} ledger={len(trades)}")
    if len(trades) != 4:
        raise RuntimeError(f"expected 4 synthetic trades, got {len(trades)}")
    expected = ["TARGET", "STOP", "TIME", "TARGET"]
    actual = [str(x["exit_reason"]) for x in trades]
    if actual != expected:
        raise RuntimeError(f"synthetic exit contract mismatch: expected={expected} actual={actual}")

    opt = run_optimization(
        event_db,
        data_root,
        RUN_ID,
        strategy,
        {"target.r": [0.50, 0.75, 1.00]},
        execution_model=execution,
        portfolio_policy=PortfolioPolicy(),
        objective={"min_trades": 1, "min_profit_factor": 0.0, "max_drawdown_r": 99.0},
        max_trials=3,
        seed=23,
        bootstrap_reps=300,
        optimization_run_id="opt-synthetic-mtx-mr-v1",
        notes="SYNTHETIC DATA ONLY - optimization smoke test",
    )

    portfolio_proof = _portfolio_overlap_proof(
        event_db, data_root, frame, strategy, execution, code_commit
    )

    run_verify = verify_run_digest(event_db, RUN_ID)
    if not run_verify.get("valid"):
        raise RuntimeError(f"frozen research digest invalid after backtest/optimization: {run_verify}")

    summary = {
        "synthetic": True,
        "warning": "SYNTHETIC DATA - NOT MARKET EDGE EVIDENCE",
        "source_file": SOURCE_FILE,
        "source_sha256": _sha256(parquet_path),
        "rows": len(frame),
        "row_groups": pq.ParquetFile(parquet_path).num_row_groups,
        "schema": list(pq.ParquetFile(parquet_path).schema_arrow.names),
        "research_run_id": RUN_ID,
        "research_digest": run_verify.get("digest"),
        "backtest_run_id": bt["backtest_run_id"],
        "backtest_digest": bt.get("digest"),
        "strategy_key": strategy.strategy_key,
        "events_seeded": len(specs),
        "trades": len(trades),
        "exit_reasons": actual,
        "report_summary": bt["report"]["summary"],
        "optimization_run_id": opt["optimization_run_id"],
        "optimization_hypotheses": opt["hypotheses_tested"],
        "optimization_plateau": opt.get("plateau"),
        "optimization_portfolio_policy_hash": opt.get("portfolio_policy_hash"),
        "portfolio_overlap_proof": portfolio_proof,
        "physical_seq": {
            "first": int(probe["_seq"].iloc[0]),
            "last": int(probe["_seq"].iloc[-1]),
            "strictly_increasing": True,
        },
    }

    (out_dir / "synthetic-demo-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (out_dir / "synthetic-trades.json").write_text(
        json.dumps(trades, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (out_dir / "synthetic-optimization.json").write_text(
        json.dumps(opt, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (out_dir / "synthetic-portfolio-overlap.json").write_text(
        json.dumps(portfolio_proof, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--event-db", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--code-commit", default=None)
    args = ap.parse_args()
    run_demo(Path(args.data_root), Path(args.event_db), Path(args.out_dir), args.code_commit)


if __name__ == "__main__":
    main()
