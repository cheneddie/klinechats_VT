from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.backtest import RescanRequired, evaluate_backtest, persist_backtest
from server.v5.execution import ExecutionModel, simulate_physical_trade
from server.v5.monitor import build_monitor_snapshot, classify_monitor_state
from server.v5.optimizer import run_optimization
from server.v5.reporting import build_full_report
from server.v5.storage import create_research_run, freeze_run, tx
from server.v5.strategy_registry import load_strategy, normalize_strategy
from server.v5.strategy_storage import verify_backtest_digest


MR_CHAIN = [
    "AUC_ATTEMPT",
    "MR_REJECTION",
    "MR_CLEAR_RECLAIM",
    "MR_RECLAIM_LEG",
    "MR_LVN",
    "MR_PULLBACK",
    "MR_ENTRY",
]


def _strategy():
    return normalize_strategy({
        "name": "TEST_MR_V1",
        "family": "MR",
        "node_chain": MR_CHAIN,
        "stop": {"type": "lvn_buffer", "points": 6},
        "target": {"type": "r_multiple", "r": 1.0},
        "time_stop_seconds": 300,
        "parameter_schema": [
            {"path": "stop.points", "kind": "float", "default": 6.0, "scope": "execution", "requires_rescan": False, "minimum": 1, "maximum": 20},
            {"path": "target.r", "kind": "float", "default": 1.0, "scope": "execution", "requires_rescan": False, "minimum": 0.25, "maximum": 5},
            {"path": "time_stop_seconds", "kind": "int", "default": 300, "scope": "execution", "requires_rescan": False, "minimum": 1, "maximum": 3600},
            {"path": "lvn.depth", "kind": "float", "default": 0.55, "scope": "detector", "requires_rescan": True, "minimum": 0, "maximum": 1},
        ],
        "lvn": {"depth": 0.55},
    })


def _seed_frozen_run(db: Path, run_id: str = "r", role: str = "DISCOVERY"):
    create_research_run(db, run_id, role, [2025], scanner_version="V4.1", strategy_version="TEST_MR_V1")
    day = "2025-01-02"
    payload = {"lvn": 100.0}
    with tx(db) as c:
        c.execute(
            """INSERT INTO events(
              research_run_id,event_id,source_file,year,trading_date,contract,strategy,direction,result,difficulty,
              attempt_start_seq,attempt_start_time,entry_seq,entry_time,entry_price,stop,target,features_json,nodes_json,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, "E1", "fake.parquet", 2025, day, "202501", "MR", "long", "ENTRY", 2,
             1, f"{day}T09:00:00", 10, f"{day}T09:00:10", 100.0, 94.0, 106.0,
             json.dumps({"market_regime": "RANGE"}), "{}", json.dumps(payload)),
        )
        for i, node_id in enumerate(MR_CHAIN):
            c.execute(
                """INSERT INTO event_nodes(
                  research_run_id,event_id,node_id,evaluation_state,answer,
                  decision_seq,decision_time,decision_price,anchor_seq,anchor_time,anchor_price,
                  resolution_seq,resolution_time,resolution_price,parent_node_id,reason_code,metrics_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, "E1", node_id, "EVALUATED", 1,
                 2 + i, f"{day}T09:00:{2+i:02d}", 100.0,
                 2 + i, f"{day}T09:00:{2+i:02d}", 100.0,
                 2 + i, f"{day}T09:00:{2+i:02d}", 100.0,
                 MR_CHAIN[i - 1] if i else "CTX_VALUE", "PASS", "{}"),
            )
    freeze_run(db, run_id)


def _path():
    return pd.DataFrame({
        "_seq": [10, 11, 12, 13, 14],
        "dt": pd.to_datetime([
            "2025-01-02T09:00:10",
            "2025-01-02T09:00:11",
            "2025-01-02T09:00:12",
            "2025-01-02T09:00:13",
            "2025-01-02T09:00:14",
        ]),
        "price": [100.0, 101.0, 103.0, 106.0, 105.0],
    })


def test_legacy_strategy_registry_marks_rescan_boundary():
    root = Path(__file__).resolve().parents[1]
    mr = load_strategy(root / "config/strategies/MR_BROAD_V3.json")
    specs = mr.parameter_map()
    assert mr.family == "MR"
    assert specs["target.r"].requires_rescan is False
    assert specs["stop.points"].requires_rescan is False
    assert specs["lvn.depth"].requires_rescan is True
    assert mr.rescan_parameters({"target.r": 1.25}) == []
    assert mr.rescan_parameters({"lvn.depth": 0.60}) == ["lvn.depth"]


def test_execution_preserves_physical_seq_and_costs():
    model = ExecutionModel(entry_slippage_points=0.5, exit_slippage_points=0.5, commission_points_per_side=0.1)
    out = simulate_physical_trade(
        _path(), direction="long", signal_seq=10, signal_price=100.0,
        stop_price=94.0, target_price=106.0, model=model, time_stop_seconds=300,
    )
    assert out["entry_seq"] == 10
    assert out["exit_seq"] == 13
    assert out["exit_reason"] == "TARGET"
    assert out["entry_price"] == pytest.approx(100.5)
    assert out["exit_price"] == pytest.approx(105.5)
    assert out["net_points"] == pytest.approx(4.8)


def test_execution_rejects_nonphysical_order():
    bad = _path().iloc[[0, 2, 1, 3, 4]].reset_index(drop=True)
    with pytest.raises(ValueError, match="strictly increasing"):
        simulate_physical_trade(
            bad, direction="long", signal_seq=10, signal_price=100,
            stop_price=94, target_price=106,
        )


def test_reporting_expectancy_pf_drawdown_and_cluster_inference():
    trades = []
    for i, r in enumerate([1.0, -1.0, 2.0, -0.5]):
        trades.append({
            "trading_date": f"2025-01-0{1 + i // 2}",
            "year": 2025,
            "month": "2025-01",
            "direction": "long" if i % 2 == 0 else "short",
            "strategy_family": "MR",
            "exit_reason": "TARGET" if r > 0 else "STOP",
            "post_trade_reason": "TARGET_HIT" if r > 0 else "VALID_LOSS",
            "net_r": r, "gross_r": r, "net_points": r * 6, "gross_points": r * 6,
            "mfe_r": max(0, r), "mae_r": max(0, -r), "mfe_points": max(0, r * 6),
            "mae_points": max(0, -r * 6), "capture_ratio": 1 if r > 0 else 0,
            "commission_points": 0, "slippage_points": 0,
        })
    report = build_full_report(trades, bootstrap_reps=500)
    s = report["summary"]
    assert s["trades"] == 4
    assert s["net_expectancy_r"] == pytest.approx(0.375)
    assert s["expectancy_formula_r"] == pytest.approx(0.375)
    assert s["profit_factor"] == pytest.approx(2.0)
    assert s["bootstrap_unit"] == "TRADING_DAY"
    assert s["cluster_count"] == 2


def test_backtest_trade_ledger_is_frozen_and_digest_verifies():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        _seed_frozen_run(db)
        evaluated = evaluate_backtest(
            db, td, "r", _strategy(), path_loader=lambda event, start: _path(), bootstrap_reps=300,
        )
        assert len(evaluated["trades"]) == 1
        assert evaluated["trades"][0]["post_trade_reason"] == "TARGET_HIT"
        persisted = persist_backtest(db, evaluated, backtest_run_id="bt1", code_commit="abc")
        assert persisted["frozen"] is True
        verified = verify_backtest_digest(db, "bt1")
        assert verified["valid"] is True
        with pytest.raises(sqlite3.IntegrityError, match="frozen backtest run is immutable"):
            with tx(db) as c:
                c.execute("UPDATE backtest_trades SET net_r=99 WHERE backtest_run_id='bt1'")


def test_rescan_parameters_are_hard_blocked_from_snapshot_reuse():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        _seed_frozen_run(db)
        with pytest.raises(RescanRequired):
            evaluate_backtest(
                db, td, "r", _strategy(), overrides={"lvn.depth": 0.6},
                path_loader=lambda event, start: _path(), bootstrap_reps=300,
            )


def test_optimizer_never_tunes_holdout_and_returns_plateau():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        _seed_frozen_run(db)
        out = run_optimization(
            db, td, "r", _strategy(),
            {"target.r": [0.5, 1.0]},
            objective={"min_trades": 1, "min_profit_factor": 0, "max_drawdown_r": 99},
            max_trials=10, bootstrap_reps=300,
            execution_model=ExecutionModel(),
        )
        assert out["hypotheses_tested"] == 2
        assert out["governance"]["holdout_used_for_tuning"] is False
        assert out["plateau"] is not None

        holdout = Path(td) / "holdout.sqlite3"
        _seed_frozen_run(holdout, "h", role="FINAL_HOLDOUT")
        with pytest.raises(RuntimeError, match="sealed"):
            run_optimization(
                holdout, td, "h", _strategy(), {"target.r": [0.5, 1.0]},
                objective={"min_trades": 1}, bootstrap_reps=300,
            )


def test_monitor_distinguishes_normal_decay_and_suspend():
    baseline = {"net_expectancy_r": 0.5, "profit_factor": 1.8, "max_drawdown_r": 4.0}
    state, reasons = classify_monitor_state(
        {"trades": 40, "net_expectancy_r": -0.1, "profit_factor": 0.8, "max_drawdown_r": 3.0},
        baseline,
    )
    assert state == "DEGRADED"
    assert "NEGATIVE_ROLLING_EXPECTANCY" in reasons

    trades = [{
        "trading_date": "2025-03-01", "net_r": 1.0, "gross_r": 1.0,
        "net_points": 6, "gross_points": 6, "mfe_r": 1.2, "mae_r": 0.2,
        "mfe_points": 7.2, "mae_points": 1.2, "capture_ratio": .8,
        "commission_points": 0, "slippage_points": 0, "regime": {"market_regime": "RANGE"},
    } for _ in range(25)]
    snap = build_monitor_snapshot(
        trades, baseline, strategy_key="TEST_MR@V1", as_of_date="2025-03-01", window_days=60,
    )
    assert snap["trades"] == 25
    assert snap["state"] in {"NORMAL", "WATCH"}
