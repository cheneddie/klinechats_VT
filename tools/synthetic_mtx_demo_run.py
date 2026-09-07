from __future__ import annotations

"""Run the synthetic MTX fixture through the persisted Strategy Lab pipeline.

SYNTHETIC DATA ONLY. This validates integration and physical execution plumbing;
it is never market-edge evidence.
"""

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

from tools.synthetic_mtx_demo import (
    BACKTEST_ID,
    CONTRACT,
    DAY,
    RUN_ID,
    SOURCE_FILE,
    _sha256,
    generate_parquet,
    seed_research_run,
)
from server.v4_replay_final import read_tick_path
from server.v5.backtest import run_backtest
from server.v5.execution import ExecutionModel
from server.v5.optimizer import run_optimization
from server.v5.storage import connect, verify_run_digest
from server.v5.strategy_registry import load_strategy


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
        objective={"min_trades": 1, "min_profit_factor": 0.0, "max_drawdown_r": 99.0},
        max_trials=3,
        seed=23,
        bootstrap_reps=300,
        optimization_run_id="opt-synthetic-mtx-mr-v1",
        notes="SYNTHETIC DATA ONLY - optimization smoke test",
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
