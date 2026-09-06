from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from .reporting import summarize_trades
from .storage import tx
from .strategy_registry import canonical_json
from .strategy_storage import migrate_strategy_db


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def classify_monitor_state(
    current: dict[str, Any],
    baseline: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    policy = dict(policy or {})
    min_trades = int(policy.get("min_trades", 20))
    watch_expectancy_ratio = float(policy.get("watch_expectancy_ratio", 0.65))
    degraded_expectancy_ratio = float(policy.get("degraded_expectancy_ratio", 0.25))
    watch_pf_ratio = float(policy.get("watch_pf_ratio", 0.80))
    suspend_dd_multiple = float(policy.get("suspend_dd_multiple", 1.50))
    reasons = []

    trades = int(current.get("trades") or 0)
    if trades < min_trades:
        return "WATCH", ["INSUFFICIENT_RECENT_TRADES"]

    cur_ev = float(current.get("net_expectancy_r") or 0.0)
    base_ev = float(baseline.get("net_expectancy_r") or 0.0)
    cur_pf = current.get("profit_factor")
    base_pf = baseline.get("profit_factor")
    cur_dd = float(current.get("max_drawdown_r") or 0.0)
    base_dd = float(baseline.get("max_drawdown_r") or 0.0)

    if base_dd > 0 and cur_dd > base_dd * suspend_dd_multiple:
        reasons.append("DRAWDOWN_BREACH")
        return "SUSPEND", reasons
    if cur_ev < 0:
        reasons.append("NEGATIVE_ROLLING_EXPECTANCY")
        if cur_pf is not None and float(cur_pf) < 1.0:
            reasons.append("PF_BELOW_ONE")
        return "DEGRADED", reasons
    if base_ev > 0 and cur_ev < base_ev * degraded_expectancy_ratio:
        reasons.append("EXPECTANCY_COLLAPSE")
        return "DEGRADED", reasons
    if base_ev > 0 and cur_ev < base_ev * watch_expectancy_ratio:
        reasons.append("EXPECTANCY_DECAY")
    if (
        cur_pf is not None
        and base_pf is not None
        and float(base_pf) > 0
        and float(cur_pf) < float(base_pf) * watch_pf_ratio
    ):
        reasons.append("PF_DECAY")
    return ("WATCH", reasons) if reasons else ("NORMAL", [])


def build_monitor_snapshot(
    trades: Iterable[dict[str, Any]],
    baseline_summary: dict[str, Any],
    *,
    strategy_key: str,
    as_of_date: str,
    window_days: int = 60,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    end = _as_date(as_of_date)
    if end is None:
        raise ValueError("invalid as_of_date")
    start = end - timedelta(days=max(1, int(window_days)) - 1)
    recent = []
    for row in trades:
        d = _as_date(row.get("trading_date"))
        if d is not None and start <= d <= end:
            recent.append(dict(row))
    summary = summarize_trades(recent, bootstrap_reps=1000)["metrics"]
    state, reasons = classify_monitor_state(summary, baseline_summary, policy)
    slippage = [float(x.get("slippage_points") or 0.0) for x in recent]
    unique_days = {str(x.get("trading_date")) for x in recent if x.get("trading_date")}
    signal_frequency = len(recent) / len(unique_days) if unique_days else 0.0
    regimes = defaultdict(int)
    for row in recent:
        regime = row.get("regime") or {}
        if isinstance(regime, dict):
            key = regime.get("market_regime") or regime.get("volatility_regime") or "UNKNOWN"
            regimes[str(key)] += 1
    return {
        "strategy_key": strategy_key,
        "as_of_date": end.isoformat(),
        "window_days": int(window_days),
        "trades": len(recent),
        "expectancy_r": summary.get("net_expectancy_r"),
        "profit_factor": summary.get("profit_factor"),
        "max_drawdown_r": summary.get("max_drawdown_r"),
        "win_rate": summary.get("win_rate"),
        "avg_slippage_points": sum(slippage) / len(slippage) if slippage else 0.0,
        "signal_frequency": signal_frequency,
        "state": state,
        "regime": dict(regimes),
        "details": {
            "reasons": reasons,
            "window_start": start.isoformat(),
            "baseline": baseline_summary,
            "current": summary,
            "policy": policy or {},
        },
    }


def persist_monitor_snapshot(event_db, snapshot: dict[str, Any]) -> None:
    migrate_strategy_db(event_db)
    with tx(event_db) as c:
        c.execute(
            """INSERT OR REPLACE INTO strategy_monitor_snapshots(
              strategy_key,as_of_date,window_days,trades,expectancy_r,profit_factor,
              max_drawdown_r,win_rate,avg_slippage_points,signal_frequency,state,
              regime_json,details_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snapshot["strategy_key"],
                snapshot["as_of_date"],
                snapshot["window_days"],
                snapshot["trades"],
                snapshot.get("expectancy_r"),
                snapshot.get("profit_factor"),
                snapshot.get("max_drawdown_r"),
                snapshot.get("win_rate"),
                snapshot.get("avg_slippage_points"),
                snapshot.get("signal_frequency"),
                snapshot["state"],
                canonical_json(snapshot.get("regime") or {}),
                canonical_json(snapshot.get("details") or {}),
            ),
        )
