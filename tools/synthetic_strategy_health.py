from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.monitor import (
    build_monitor_snapshot,
    get_monitor_control,
    persist_monitor_snapshot,
    record_monitor_action,
)
from server.v5.reporting import summarize_trades

WARNING = "SYNTHETIC STRATEGY HEALTH DATA - NOT MARKET EDGE EVIDENCE"
STRATEGY_KEY = "MR_BROAD@V3"


def trades(
    start: date,
    *,
    days: int,
    per_day: int,
    r_pattern: list[float],
    slippage: float,
    regimes: list[str],
):
    out = []
    n = 0
    for d in range(days):
        trading_date = (start + timedelta(days=d)).isoformat()
        for i in range(per_day):
            r = float(r_pattern[n % len(r_pattern)])
            regime = regimes[n % len(regimes)]
            out.append(
                {
                    "trade_id": f"SYN-H-{start.isoformat()}-{d}-{i}",
                    "trading_date": trading_date,
                    "month": trading_date[:7],
                    "net_r": r,
                    "gross_r": r + 0.02,
                    "net_points": r * 10,
                    "gross_points": (r + 0.02) * 10,
                    "mfe_r": max(r, 0.0) + 0.25,
                    "mae_r": abs(min(r, 0.0)) + 0.05,
                    "mfe_points": (max(r, 0.0) + 0.25) * 10,
                    "mae_points": (abs(min(r, 0.0)) + 0.05) * 10,
                    "capture_ratio": 0.55 if r > 0 else 0.0,
                    "commission_points": 0.10,
                    "slippage_points": slippage,
                    "regime": {"market_regime": regime},
                }
            )
            n += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event-db", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    db = Path(args.event_db)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    baseline = trades(
        date(2026, 1, 1),
        days=20,
        per_day=2,
        r_pattern=[0.55, -0.20, 0.40, -0.10],
        slippage=0.20,
        regimes=["RANGE", "TREND"],
    )
    baseline_summary = summarize_trades(baseline, bootstrap_reps=200)["metrics"]
    policy = {
        "min_trades": 10,
        "watch_expectancy_ratio": 0.65,
        "degraded_expectancy_ratio": 0.25,
        "suspend_dd_multiple": 1.50,
        "watch_signal_frequency_ratio_low": 0.60,
        "degraded_signal_frequency_ratio_low": 0.30,
        "watch_slippage_multiple": 1.50,
        "degraded_slippage_multiple": 2.00,
        "watch_regime_tvd": 0.30,
        "degraded_regime_tvd": 0.60,
    }

    degraded_trades = trades(
        date(2026, 4, 1),
        days=10,
        per_day=1,
        r_pattern=[-0.25, 0.05, -0.20, -0.10],
        slippage=0.80,
        regimes=["HIGH_VOL"],
    )
    degraded = build_monitor_snapshot(
        degraded_trades,
        baseline_summary,
        strategy_key=STRATEGY_KEY,
        as_of_date="2026-04-10",
        window_days=30,
        policy=policy,
        baseline_trades=baseline,
    )
    degraded = persist_monitor_snapshot(db, degraded)
    assert degraded["state"] == "DEGRADED", degraded

    suspend_trades = trades(
        date(2026, 4, 11),
        days=10,
        per_day=2,
        r_pattern=[-0.65, -0.55, -0.45, 0.10],
        slippage=0.90,
        regimes=["HIGH_VOL", "TREND"],
    )
    suspended = build_monitor_snapshot(
        suspend_trades,
        baseline_summary,
        strategy_key=STRATEGY_KEY,
        as_of_date="2026-04-20",
        window_days=30,
        policy=policy,
        baseline_trades=baseline,
    )
    suspended = persist_monitor_snapshot(db, suspended)
    assert suspended["state"] == "SUSPEND", suspended
    assert suspended["details"]["computed_state"] == "SUSPEND", suspended

    record_monitor_action(
        db,
        STRATEGY_KEY,
        "ACKNOWLEDGE",
        "synthetic operator acknowledged the suspension",
        details={"synthetic": True},
    )

    recovery_trades = trades(
        date(2026, 4, 21),
        days=10,
        per_day=2,
        r_pattern=[0.55, -0.20, 0.40, -0.10],
        slippage=0.20,
        regimes=["RANGE", "TREND"],
    )
    recovery = build_monitor_snapshot(
        recovery_trades,
        baseline_summary,
        strategy_key=STRATEGY_KEY,
        as_of_date="2026-04-30",
        window_days=30,
        policy=policy,
        baseline_trades=baseline,
    )
    recovery = persist_monitor_snapshot(db, recovery)
    assert recovery["details"]["computed_state"] == "NORMAL", recovery
    assert recovery["state"] == "SUSPEND", recovery
    assert "SUSPEND_LATCHED_BY_LIFECYCLE_CONTROL" in recovery["details"]["reasons"], recovery

    control = get_monitor_control(db, STRATEGY_KEY)
    assert control["lifecycle_state"] == "SUSPENDED", control

    result = {
        "synthetic": True,
        "warning": WARNING,
        "strategy_key": STRATEGY_KEY,
        "baseline": {
            "trades": baseline_summary["trades"],
            "expectancy_r": baseline_summary["net_expectancy_r"],
            "profit_factor": baseline_summary["profit_factor"],
            "max_drawdown_r": baseline_summary["max_drawdown_r"],
        },
        "degraded": degraded,
        "suspended": suspended,
        "latched_recovery": recovery,
        "control": control,
        "assertion": "A later NORMAL rolling window cannot auto-resume a strategy after SUSPEND; explicit human RESUME is required.",
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
