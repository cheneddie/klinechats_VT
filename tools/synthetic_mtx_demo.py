from __future__ import annotations

"""Generate a deterministic synthetic MTX Parquet and run Strategy Lab end to end.

THIS IS SYNTHETIC DATA. It is deliberately shaped to exercise physical replay,
execution, immutable backtest persistence and optimization. It must never be used
as market-edge evidence or mixed with real MTX research campaigns.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from server.v4_replay_final import read_tick_path
from server.v5.backtest import run_backtest
from server.v5.execution import ExecutionModel
from server.v5.optimizer import run_optimization
from server.v5.storage import create_research_run, freeze_run, tx, verify_run_digest
from server.v5.strategy_registry import load_strategy


RUN_ID = "synthetic-mtx-discovery-v1"
BACKTEST_ID = "bt-synthetic-mtx-mr-v1"
CONTRACT = "202509"
SOURCE_FILE = "MTX_2025_SYNTHETIC.parquet"
DAY = "2025-09-01"
MR_CHAIN = [
    "AUC_ATTEMPT",
    "MR_REJECTION",
    "MR_CLEAR_RECLAIM",
    "MR_RECLAIM_LEG",
    "MR_LVN",
    "MR_PULLBACK",
    "MR_ENTRY",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_prices(times: pd.DatetimeIndex) -> np.ndarray:
    # Calm baseline around 20,000 with deterministic micro-variation.
    x = np.arange(len(times), dtype=float)
    prices = 20000.0 + np.sin(x / 17.0) * 0.5 + np.sin(x / 53.0) * 0.25
    prices = np.round(prices * 2.0) / 2.0

    def setp(ts: str, value: float):
        idx = times.get_loc(pd.Timestamp(ts))
        prices[idx] = float(value)

    # Trade 1: long, target hit quickly.
    for ts, p in [
        (f"{DAY} 09:00:10", 20000.0),
        (f"{DAY} 09:00:11", 20001.0),
        (f"{DAY} 09:00:12", 20003.0),
        (f"{DAY} 09:00:13", 20005.0),
    ]:
        setp(ts, p)

    # Trade 2: short, stop hit quickly.
    for ts, p in [
        (f"{DAY} 09:05:10", 20010.0),
        (f"{DAY} 09:05:11", 20012.0),
        (f"{DAY} 09:05:12", 20015.0),
        (f"{DAY} 09:05:13", 20016.5),
    ]:
        setp(ts, p)

    # Trade 3: long, stays inside stop/target until the 300 second time stop.
    start = times.get_loc(pd.Timestamp(f"{DAY} 09:10:10"))
    end = times.get_loc(pd.Timestamp(f"{DAY} 09:15:10"))
    for i in range(start, end + 1):
        prices[i] = 20021.0 + ((i - start) % 5) * 0.5
    prices[start] = 20020.0
    prices[end] = 20022.0

    # Trade 4: short, target hit quickly after the time-stop example.
    for ts, p in [
        (f"{DAY} 09:16:10", 20030.0),
        (f"{DAY} 09:16:11", 20029.0),
        (f"{DAY} 09:16:12", 20027.0),
        (f"{DAY} 09:16:13", 20025.0),
    ]:
        setp(ts, p)

    return prices


def generate_parquet(data_root: Path) -> tuple[Path, pd.DataFrame]:
    data_root.mkdir(parents=True, exist_ok=True)
    path = data_root / SOURCE_FILE
    times = pd.date_range(f"{DAY} 08:45:00", f"{DAY} 09:20:00", freq="1s")
    prices = _build_prices(times)
    direction = np.sign(np.diff(prices, prepend=prices[0]))
    side = np.where(direction >= 0, 1, -1).astype(np.int8)
    volume = (1 + (np.arange(len(times)) % 7)).astype(np.int32)
    frame = pd.DataFrame(
        {
            "datetime": times,
            "product": pd.Series(["MTX"] * len(times), dtype="string"),
            "expiry": pd.Series([CONTRACT] * len(times), dtype="string"),
            "price": prices.astype(float),
            "volume": volume,
            "side": side,
        }
    )
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table, path, compression="zstd", row_group_size=500)
    return path, frame


def _entry_seq(frame: pd.DataFrame, when: str) -> int:
    match = frame.index[frame["datetime"].eq(pd.Timestamp(when))]
    if len(match) != 1:
        raise RuntimeError(f"synthetic entry timestamp not unique: {when}")
    return int(match[0])


def seed_research_run(event_db: Path, frame: pd.DataFrame) -> list[dict]:
    if event_db.exists():
        event_db.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(event_db) + suffix)
        if p.exists():
            p.unlink()

    create_research_run(
        event_db,
        RUN_ID,
        "DISCOVERY",
        [2025],
        scanner_version="SYNTHETIC_FIXTURE_V1",
        strategy_version="MR_BROAD_V3",
        notes="SYNTHETIC DATA ONLY - physical replay/backtest integration fixture",
    )

    specs = [
        {
            "event_id": "SYN-MR-001",
            "direction": "long",
            "time": f"{DAY} 09:00:10",
            "entry": 20000.0,
            "stop": 19994.0,
            "target": 20004.5,
            "regime": "SYNTHETIC_TARGET_LONG",
        },
        {
            "event_id": "SYN-MR-002",
            "direction": "short",
            "time": f"{DAY} 09:05:10",
            "entry": 20010.0,
            "stop": 20016.0,
            "target": 20005.5,
            "regime": "SYNTHETIC_STOP_SHORT",
        },
        {
            "event_id": "SYN-MR-003",
            "direction": "long",
            "time": f"{DAY} 09:10:10",
            "entry": 20020.0,
            "stop": 20014.0,
            "target": 20024.5,
            "regime": "SYNTHETIC_TIME_LONG",
        },
        {
            "event_id": "SYN-MR-004",
            "direction": "short",
            "time": f"{DAY} 09:16:10",
            "entry": 20030.0,
            "stop": 20036.0,
            "target": 20025.5,
            "regime": "SYNTHETIC_TARGET_SHORT",
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
                    RUN_ID,
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
                        RUN_ID,
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

    digest = freeze_run(event_db, RUN_ID)
    verified = verify_run_digest(event_db, RUN_ID)
    if not verified.get("valid"):
        raise RuntimeError(f"synthetic frozen research digest invalid: {verified}")
    if digest != verified.get("digest"):
        raise RuntimeError("synthetic frozen digest mismatch")
    return specs


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

    # Prove the production replay reader reconstructed physical _seq from the file.
    probe_event = {
        "source_file": SOURCE_FILE,
        "trading_date": DAY,
        "contract": CONTRACT,
    }
    probe = read_tick_path(data_root, probe_event, 0, 0)
    if len(probe) != len(frame):
        raise RuntimeError(f"physical replay row mismatch: parquet={len(frame)} replay={len(probe)}")
    if int(probe["_seq"].iloc[0]) != 0 or int(probe["_seq"].iloc[-1]) != len(frame) - 1:
        raise RuntimeError("physical replay did not preserve source row order")

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
    trades = bt["trades"]
    if len(trades) != 4:
        raise RuntimeError(f"expected 4 synthetic trades, got {len(trades)}; skipped={bt.get('skipped')}")
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

    summary = {
        "synthetic": True,
        "warning": "SYNTHETIC DATA - NOT MARKET EDGE EVIDENCE",
        "source_file": SOURCE_FILE,
        "source_sha256": _sha256(parquet_path),
        "rows": len(frame),
        "row_groups": pq.ParquetFile(parquet_path).num_row_groups,
        "schema": [str(x) for x in pq.ParquetFile(parquet_path).schema_arrow.names],
        "research_run_id": RUN_ID,
        "research_digest": bt["research_run"].get("frozen_digest"),
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
            "strictly_increasing": bool((probe["_seq"].diff().fillna(1) > 0).all()),
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
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--event-db", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--code-commit", default=None)
    args = ap.parse_args()
    summary = run_demo(Path(args.data_root), Path(args.event_db), Path(args.out_dir), args.code_commit)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
