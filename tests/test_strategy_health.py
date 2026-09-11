from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.monitor import (
    build_monitor_snapshot,
    get_monitor_control,
    list_monitor_actions,
    persist_monitor_snapshot,
    record_monitor_action,
)
from server.v5.reporting import summarize_trades


def _trades(
    start: date,
    *,
    days: int,
    per_day: int,
    net_r: float,
    slippage: float,
    regime: str,
):
    rows = []
    for d in range(days):
        trading_date = (start + timedelta(days=d)).isoformat()
        for i in range(per_day):
            rows.append(
                {
                    "trade_id": f"T-{d}-{i}",
                    "trading_date": trading_date,
                    "month": trading_date[:7],
                    "net_r": net_r,
                    "gross_r": net_r,
                    "net_points": net_r * 10,
                    "gross_points": net_r * 10,
                    "mfe_r": max(net_r, 0.0) + 0.2,
                    "mae_r": abs(min(net_r, 0.0)),
                    "mfe_points": max(net_r, 0.0) * 10 + 2,
                    "mae_points": abs(min(net_r, 0.0)) * 10,
                    "capture_ratio": 0.5,
                    "commission_points": 0.1,
                    "slippage_points": slippage,
                    "regime": {"market_regime": regime},
                }
            )
    return rows


def _snapshot(strategy_key: str, as_of_date: str, state: str):
    return {
        "strategy_key": strategy_key,
        "as_of_date": as_of_date,
        "window_days": 30,
        "trades": 30,
        "expectancy_r": 0.2,
        "profit_factor": 1.2,
        "max_drawdown_r": 1.0,
        "win_rate": 0.55,
        "avg_slippage_points": 0.2,
        "signal_frequency": 2.0,
        "state": state,
        "regime": {"RANGE": 30},
        "details": {"reasons": []},
    }


def test_strategy_health_detects_multiple_drift_dimensions():
    baseline = _trades(
        date(2026, 1, 1), days=10, per_day=2, net_r=0.4, slippage=0.2, regime="RANGE"
    )
    current = _trades(
        date(2026, 2, 1), days=10, per_day=1, net_r=-0.25, slippage=0.8, regime="TREND"
    )
    baseline_summary = summarize_trades(baseline, bootstrap_reps=200)["metrics"]
    snapshot = build_monitor_snapshot(
        current,
        baseline_summary,
        strategy_key="MR_BROAD@V3",
        as_of_date="2026-02-10",
        window_days=30,
        baseline_trades=baseline,
        policy={"min_trades": 5},
    )

    drift = snapshot["details"]["drift"]
    reasons = set(snapshot["details"]["reasons"])
    assert snapshot["state"] == "DEGRADED"
    assert drift["signal_frequency_ratio"] == 0.5
    assert drift["slippage_multiple"] == 4.0
    assert drift["regime_tvd"] == 1.0
    assert "NEGATIVE_ROLLING_EXPECTANCY" in reasons
    assert "SLIPPAGE_DRIFT" in reasons
    assert "REGIME_MIX_DRIFT" in reasons


def test_suspend_is_latched_until_explicit_human_resume():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        key = "MR_BROAD@V3"

        suspended = persist_monitor_snapshot(db, _snapshot(key, "2026-03-01", "SUSPEND"))
        assert suspended["state"] == "SUSPEND"
        assert get_monitor_control(db, key)["lifecycle_state"] == "SUSPENDED"

        recovery_without_review = persist_monitor_snapshot(
            db, _snapshot(key, "2026-03-02", "NORMAL")
        )
        assert recovery_without_review["state"] == "SUSPEND"
        assert recovery_without_review["details"]["computed_state"] == "NORMAL"
        assert "SUSPEND_LATCHED_BY_LIFECYCLE_CONTROL" in recovery_without_review["details"]["reasons"]

        action = record_monitor_action(
            db,
            key,
            "RESUME",
            "human reviewed execution and live evidence",
            details={"reviewer": "synthetic-test"},
        )
        assert action["previous_state"] == "SUSPENDED"
        assert action["next_state"] == "ACTIVE"
        assert get_monitor_control(db, key)["lifecycle_state"] == "ACTIVE"

        recovery_after_review = persist_monitor_snapshot(
            db, _snapshot(key, "2026-03-03", "NORMAL")
        )
        assert recovery_after_review["state"] == "NORMAL"
        actions = list_monitor_actions(db, key)
        assert actions[0]["action"] == "RESUME"
        assert actions[0]["reason"] == "human reviewed execution and live evidence"
