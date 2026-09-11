from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from uuid import uuid4

from .reporting import summarize_trades
from .storage import connect, tx, utcnow
from .strategy_registry import canonical_json
from .strategy_storage import migrate_strategy_db

MONITOR_CONTROL_ACTIVE = "ACTIVE"
MONITOR_CONTROL_SUSPENDED = "SUSPENDED"
MONITOR_ACTIONS = {"ACKNOWLEDGE", "MANUAL_SUSPEND", "RESUME"}


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _regime_key(row: dict[str, Any]) -> str:
    regime = row.get("regime") or {}
    if not isinstance(regime, dict):
        return "UNKNOWN"
    return str(
        regime.get("market_regime")
        or regime.get("volatility_regime")
        or regime.get("regime")
        or "UNKNOWN"
    )


def _profile(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(x) for x in trades]
    days = {str(x.get("trading_date")) for x in rows if x.get("trading_date")}
    slippage = [_f(x.get("slippage_points")) for x in rows]
    regimes: dict[str, int] = defaultdict(int)
    for row in rows:
        regimes[_regime_key(row)] += 1
    total = sum(regimes.values())
    distribution = {
        key: value / total for key, value in sorted(regimes.items())
    } if total else {}
    return {
        "trades": len(rows),
        "trading_days": len(days),
        "signal_frequency": len(rows) / len(days) if days else 0.0,
        "avg_slippage_points": sum(slippage) / len(slippage) if slippage else 0.0,
        "regime_counts": dict(sorted(regimes.items())),
        "regime_distribution": distribution,
    }


def _ratio(current: Any, baseline: Any) -> float | None:
    base = _f(baseline)
    if base <= 0:
        return None
    return _f(current) / base


def _regime_tvd(current: dict[str, float], baseline: dict[str, float]) -> float:
    keys = set(current) | set(baseline)
    return 0.5 * sum(abs(_f(current.get(k)) - _f(baseline.get(k))) for k in keys)


def compute_monitor_drift(
    current_summary: dict[str, Any],
    current_profile: dict[str, Any],
    baseline_summary: dict[str, Any],
    baseline_profile: dict[str, Any],
) -> dict[str, Any]:
    cur_slip = _f(current_profile.get("avg_slippage_points"))
    base_slip = _f(baseline_profile.get("avg_slippage_points"))
    cur_dd = _f(current_summary.get("max_drawdown_r"))
    base_dd = _f(baseline_summary.get("max_drawdown_r"))
    return {
        "expectancy_ratio": _ratio(
            current_summary.get("net_expectancy_r"), baseline_summary.get("net_expectancy_r")
        ),
        "profit_factor_ratio": _ratio(
            current_summary.get("profit_factor"), baseline_summary.get("profit_factor")
        ),
        "drawdown_multiple": (cur_dd / base_dd) if base_dd > 0 else None,
        "signal_frequency_ratio": _ratio(
            current_profile.get("signal_frequency"), baseline_profile.get("signal_frequency")
        ),
        "slippage_multiple": (cur_slip / base_slip) if base_slip > 0 else None,
        "slippage_delta_points": cur_slip - base_slip,
        "regime_tvd": _regime_tvd(
            current_profile.get("regime_distribution") or {},
            baseline_profile.get("regime_distribution") or {},
        ),
    }


def classify_monitor_state(
    current: dict[str, Any],
    baseline: dict[str, Any],
    policy: dict[str, Any] | None = None,
    drift: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    policy = dict(policy or {})
    drift = dict(drift or {})
    min_trades = int(policy.get("min_trades", 20))
    watch_expectancy_ratio = float(policy.get("watch_expectancy_ratio", 0.65))
    degraded_expectancy_ratio = float(policy.get("degraded_expectancy_ratio", 0.25))
    watch_pf_ratio = float(policy.get("watch_pf_ratio", 0.80))
    suspend_dd_multiple = float(policy.get("suspend_dd_multiple", 1.50))
    watch_signal_low = float(policy.get("watch_signal_frequency_ratio_low", 0.60))
    watch_signal_high = float(policy.get("watch_signal_frequency_ratio_high", 1.60))
    degraded_signal_low = float(policy.get("degraded_signal_frequency_ratio_low", 0.30))
    degraded_signal_high = float(policy.get("degraded_signal_frequency_ratio_high", 2.50))
    watch_slippage_multiple = float(policy.get("watch_slippage_multiple", 1.50))
    degraded_slippage_multiple = float(policy.get("degraded_slippage_multiple", 2.00))
    watch_slippage_delta = float(policy.get("watch_slippage_delta_points", 0.50))
    degraded_slippage_delta = float(policy.get("degraded_slippage_delta_points", 1.00))
    watch_regime_tvd = float(policy.get("watch_regime_tvd", 0.30))
    degraded_regime_tvd = float(policy.get("degraded_regime_tvd", 0.60))
    reasons: list[str] = []

    trades = int(current.get("trades") or 0)
    cur_ev = _f(current.get("net_expectancy_r"))
    base_ev = _f(baseline.get("net_expectancy_r"))
    cur_pf = current.get("profit_factor")
    base_pf = baseline.get("profit_factor")
    cur_dd = _f(current.get("max_drawdown_r"))
    base_dd = _f(baseline.get("max_drawdown_r"))

    if base_dd > 0 and cur_dd > base_dd * suspend_dd_multiple:
        return "SUSPEND", ["DRAWDOWN_BREACH"]

    severe: list[str] = []
    if cur_ev < 0:
        severe.append("NEGATIVE_ROLLING_EXPECTANCY")
        if cur_pf is not None and float(cur_pf) < 1.0:
            severe.append("PF_BELOW_ONE")
    elif base_ev > 0 and cur_ev < base_ev * degraded_expectancy_ratio:
        severe.append("EXPECTANCY_COLLAPSE")

    freq_ratio = drift.get("signal_frequency_ratio")
    if freq_ratio is not None and (
        float(freq_ratio) < degraded_signal_low or float(freq_ratio) > degraded_signal_high
    ):
        severe.append("SIGNAL_FREQUENCY_DRIFT")

    slip_multiple = drift.get("slippage_multiple")
    slip_delta = _f(drift.get("slippage_delta_points"))
    if (
        (slip_multiple is not None and float(slip_multiple) >= degraded_slippage_multiple)
        or slip_delta >= degraded_slippage_delta
    ):
        severe.append("SLIPPAGE_DRIFT")

    regime_tvd = _f(drift.get("regime_tvd"))
    if regime_tvd >= degraded_regime_tvd:
        severe.append("REGIME_MIX_DRIFT")

    if severe:
        return "DEGRADED", list(dict.fromkeys(severe))

    if trades < min_trades:
        reasons.append("INSUFFICIENT_RECENT_TRADES")
    if base_ev > 0 and cur_ev < base_ev * watch_expectancy_ratio:
        reasons.append("EXPECTANCY_DECAY")
    if (
        cur_pf is not None
        and base_pf is not None
        and float(base_pf) > 0
        and float(cur_pf) < float(base_pf) * watch_pf_ratio
    ):
        reasons.append("PF_DECAY")
    if freq_ratio is not None and (
        float(freq_ratio) < watch_signal_low or float(freq_ratio) > watch_signal_high
    ):
        reasons.append("SIGNAL_FREQUENCY_DRIFT")
    if (
        (slip_multiple is not None and float(slip_multiple) >= watch_slippage_multiple)
        or slip_delta >= watch_slippage_delta
    ):
        reasons.append("SLIPPAGE_DRIFT")
    if regime_tvd >= watch_regime_tvd:
        reasons.append("REGIME_MIX_DRIFT")

    reasons = list(dict.fromkeys(reasons))
    return ("WATCH", reasons) if reasons else ("NORMAL", [])


def build_monitor_snapshot(
    trades: Iterable[dict[str, Any]],
    baseline_summary: dict[str, Any],
    *,
    strategy_key: str,
    as_of_date: str,
    window_days: int = 60,
    policy: dict[str, Any] | None = None,
    baseline_trades: Iterable[dict[str, Any]] | None = None,
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
    current_profile = _profile(recent)
    baseline_profile = _profile(baseline_trades or [])
    drift = compute_monitor_drift(summary, current_profile, baseline_summary, baseline_profile)
    state, reasons = classify_monitor_state(summary, baseline_summary, policy, drift)

    return {
        "strategy_key": strategy_key,
        "as_of_date": end.isoformat(),
        "window_days": int(window_days),
        "trades": len(recent),
        "expectancy_r": summary.get("net_expectancy_r"),
        "profit_factor": summary.get("profit_factor"),
        "max_drawdown_r": summary.get("max_drawdown_r"),
        "win_rate": summary.get("win_rate"),
        "avg_slippage_points": current_profile.get("avg_slippage_points"),
        "signal_frequency": current_profile.get("signal_frequency"),
        "state": state,
        "regime": current_profile.get("regime_counts") or {},
        "details": {
            "reasons": reasons,
            "window_start": start.isoformat(),
            "baseline": baseline_summary,
            "current": summary,
            "baseline_profile": baseline_profile,
            "current_profile": current_profile,
            "drift": drift,
            "policy": policy or {},
        },
    }


def _migrate_monitor_governance(event_db) -> None:
    migrate_strategy_db(event_db)
    with tx(event_db) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategy_monitor_controls(
              strategy_key TEXT PRIMARY KEY,
              lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE',
              updated_at TEXT NOT NULL,
              last_action_id TEXT,
              details_json TEXT NOT NULL DEFAULT '{}',
              CHECK(lifecycle_state IN ('ACTIVE','SUSPENDED'))
            );
            CREATE TABLE IF NOT EXISTS strategy_monitor_actions(
              action_id TEXT PRIMARY KEY,
              strategy_key TEXT NOT NULL,
              created_at TEXT NOT NULL,
              action TEXT NOT NULL,
              reason TEXT NOT NULL,
              previous_state TEXT NOT NULL,
              next_state TEXT NOT NULL,
              details_json TEXT NOT NULL DEFAULT '{}',
              CHECK(action IN ('ACKNOWLEDGE','MANUAL_SUSPEND','RESUME')),
              CHECK(previous_state IN ('ACTIVE','SUSPENDED')),
              CHECK(next_state IN ('ACTIVE','SUSPENDED'))
            );
            CREATE INDEX IF NOT EXISTS ix_strategy_monitor_actions_strategy
              ON strategy_monitor_actions(strategy_key,created_at);
            """
        )


def get_monitor_control(event_db, strategy_key: str) -> dict[str, Any]:
    _migrate_monitor_governance(event_db)
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT * FROM strategy_monitor_controls WHERE strategy_key=?", (strategy_key,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        return {
            "strategy_key": strategy_key,
            "lifecycle_state": MONITOR_CONTROL_ACTIVE,
            "updated_at": None,
            "last_action_id": None,
            "details": {},
        }
    out = dict(row)
    try:
        out["details"] = __import__("json").loads(out.get("details_json") or "{}")
    except Exception:
        out["details"] = {}
    return out


def persist_monitor_snapshot(event_db, snapshot: dict[str, Any]) -> dict[str, Any]:
    _migrate_monitor_governance(event_db)
    snapshot = dict(snapshot)
    details = dict(snapshot.get("details") or {})
    reasons = list(details.get("reasons") or [])
    computed_state = str(snapshot.get("state") or "WATCH").upper()

    with tx(event_db) as c:
        row = c.execute(
            "SELECT * FROM strategy_monitor_controls WHERE strategy_key=?",
            (snapshot["strategy_key"],),
        ).fetchone()
        lifecycle = row["lifecycle_state"] if row else MONITOR_CONTROL_ACTIVE
        effective_state = computed_state

        if lifecycle == MONITOR_CONTROL_SUSPENDED:
            effective_state = "SUSPEND"
            if "SUSPEND_LATCHED_BY_LIFECYCLE_CONTROL" not in reasons:
                reasons.append("SUSPEND_LATCHED_BY_LIFECYCLE_CONTROL")
        elif computed_state == "SUSPEND":
            lifecycle = MONITOR_CONTROL_SUSPENDED
            c.execute(
                """INSERT INTO strategy_monitor_controls(
                     strategy_key,lifecycle_state,updated_at,last_action_id,details_json
                   ) VALUES(?,?,?,?,?)
                   ON CONFLICT(strategy_key) DO UPDATE SET
                     lifecycle_state=excluded.lifecycle_state,
                     updated_at=excluded.updated_at,
                     details_json=excluded.details_json""",
                (
                    snapshot["strategy_key"],
                    MONITOR_CONTROL_SUSPENDED,
                    utcnow(),
                    None,
                    canonical_json({
                        "source": "AUTO_MONITOR",
                        "as_of_date": snapshot["as_of_date"],
                        "reasons": reasons,
                    }),
                ),
            )
        elif not row:
            c.execute(
                "INSERT INTO strategy_monitor_controls VALUES(?,?,?,?,?)",
                (
                    snapshot["strategy_key"],
                    MONITOR_CONTROL_ACTIVE,
                    utcnow(),
                    None,
                    canonical_json({"source": "MONITOR_INIT"}),
                ),
            )

        details["reasons"] = reasons
        details["computed_state"] = computed_state
        details["effective_state"] = effective_state
        details["lifecycle_state"] = lifecycle
        snapshot["state"] = effective_state
        snapshot["details"] = details

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
    return snapshot


def record_monitor_action(
    event_db,
    strategy_key: str,
    action: str,
    reason: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _migrate_monitor_governance(event_db)
    action = str(action or "").strip().upper()
    reason = str(reason or "").strip()
    if action not in MONITOR_ACTIONS:
        raise ValueError(f"unsupported monitor action: {action}")
    if len(reason) < 3:
        raise ValueError("monitor action requires a human review reason")

    action_id = "monitor-action-" + uuid4().hex[:20]
    created_at = utcnow()
    with tx(event_db) as c:
        row = c.execute(
            "SELECT lifecycle_state FROM strategy_monitor_controls WHERE strategy_key=?",
            (strategy_key,),
        ).fetchone()
        previous = row["lifecycle_state"] if row else MONITOR_CONTROL_ACTIVE
        if action == "RESUME":
            if previous != MONITOR_CONTROL_SUSPENDED:
                raise ValueError("RESUME requires a currently SUSPENDED strategy")
            next_state = MONITOR_CONTROL_ACTIVE
        elif action == "MANUAL_SUSPEND":
            next_state = MONITOR_CONTROL_SUSPENDED
        else:
            next_state = previous

        c.execute(
            """INSERT INTO strategy_monitor_actions(
                 action_id,strategy_key,created_at,action,reason,previous_state,next_state,details_json
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                action_id,
                strategy_key,
                created_at,
                action,
                reason,
                previous,
                next_state,
                canonical_json(details or {}),
            ),
        )
        c.execute(
            """INSERT INTO strategy_monitor_controls(
                 strategy_key,lifecycle_state,updated_at,last_action_id,details_json
               ) VALUES(?,?,?,?,?)
               ON CONFLICT(strategy_key) DO UPDATE SET
                 lifecycle_state=excluded.lifecycle_state,
                 updated_at=excluded.updated_at,
                 last_action_id=excluded.last_action_id,
                 details_json=excluded.details_json""",
            (
                strategy_key,
                next_state,
                created_at,
                action_id,
                canonical_json({"action": action, "reason": reason, **(details or {})}),
            ),
        )

    return {
        "action_id": action_id,
        "strategy_key": strategy_key,
        "created_at": created_at,
        "action": action,
        "reason": reason,
        "previous_state": previous,
        "next_state": next_state,
        "details": details or {},
    }


def list_monitor_actions(event_db, strategy_key: str, limit: int = 100) -> list[dict[str, Any]]:
    _migrate_monitor_governance(event_db)
    c = connect(event_db)
    try:
        rows = [dict(r) for r in c.execute(
            """SELECT * FROM strategy_monitor_actions
               WHERE strategy_key=? ORDER BY created_at DESC LIMIT ?""",
            (strategy_key, min(max(int(limit), 1), 1000)),
        ).fetchall()]
    finally:
        c.close()
    for row in rows:
        try:
            row["details"] = __import__("json").loads(row.get("details_json") or "{}")
        except Exception:
            row["details"] = {}
    return rows
