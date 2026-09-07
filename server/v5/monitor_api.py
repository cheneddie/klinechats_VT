from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .monitor import (
    build_monitor_snapshot,
    get_monitor_control,
    list_monitor_actions,
    persist_monitor_snapshot,
    record_monitor_action,
)
from .storage import connect
from .strategy_api import _load_backtest
from .strategy_storage import migrate_strategy_db


class MonitorHealthRequest(BaseModel):
    strategy_key: str
    backtest_run_id: str
    baseline_backtest_run_id: str
    as_of_date: str
    window_days: int = Field(60, ge=5, le=730)
    policy: dict[str, Any] = Field(default_factory=dict)


class MonitorActionRequest(BaseModel):
    strategy_key: str
    action: str
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


def _json(value, default=None):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except Exception:
        return default


def _decode_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["regime"] = _json(out.get("regime_json"), {}) or {}
    out["details"] = _json(out.get("details_json"), {}) or {}
    return out


def install_monitor_api(app, *, event_db: str | Path):
    event_db = Path(event_db)
    migrate_strategy_db(event_db)

    @app.post("/api/v5/strategy-lab/monitor-health")
    def monitor_health(req: MonitorHealthRequest):
        current = _load_backtest(event_db, req.backtest_run_id)
        baseline = _load_backtest(event_db, req.baseline_backtest_run_id)
        if current["run"].get("strategy_key") != req.strategy_key:
            raise ValueError("current backtest strategy_key mismatch")
        if baseline["run"].get("strategy_key") != req.strategy_key:
            raise ValueError("baseline backtest strategy_key mismatch")
        snapshot = build_monitor_snapshot(
            current["trades"],
            baseline["summary"],
            strategy_key=req.strategy_key,
            as_of_date=req.as_of_date,
            window_days=req.window_days,
            policy=req.policy,
            baseline_trades=baseline["trades"],
        )
        snapshot = persist_monitor_snapshot(event_db, snapshot)
        return {
            "snapshot": snapshot,
            "control": get_monitor_control(event_db, req.strategy_key),
        }

    @app.get("/api/v5/strategy-lab/monitor-health")
    def monitor_health_list(strategy_key: str | None = None, limit: int = 200):
        c = connect(event_db)
        try:
            if strategy_key:
                rows = [dict(r) for r in c.execute(
                    """SELECT * FROM strategy_monitor_snapshots
                       WHERE strategy_key=? ORDER BY as_of_date DESC,window_days DESC LIMIT ?""",
                    (strategy_key, min(max(int(limit), 1), 2000)),
                ).fetchall()]
            else:
                rows = [dict(r) for r in c.execute(
                    """SELECT * FROM strategy_monitor_snapshots
                       ORDER BY as_of_date DESC,window_days DESC LIMIT ?""",
                    (min(max(int(limit), 1), 2000),),
                ).fetchall()]
        finally:
            c.close()
        items = [_decode_snapshot(r) for r in rows]
        keys = sorted({x["strategy_key"] for x in items})
        if strategy_key and strategy_key not in keys:
            keys.append(strategy_key)
        controls = {key: get_monitor_control(event_db, key) for key in keys}
        return {"items": items, "controls": controls}

    @app.get("/api/v5/strategy-lab/monitor-health/control")
    def monitor_health_control(strategy_key: str):
        return get_monitor_control(event_db, strategy_key)

    @app.get("/api/v5/strategy-lab/monitor-health/actions")
    def monitor_health_actions(strategy_key: str, limit: int = 100):
        return {"items": list_monitor_actions(event_db, strategy_key, limit)}

    @app.post("/api/v5/strategy-lab/monitor-health/actions")
    def monitor_health_action(req: MonitorActionRequest):
        action = record_monitor_action(
            event_db,
            req.strategy_key,
            req.action,
            req.reason,
            details=req.details,
        )
        return {
            "action": action,
            "control": get_monitor_control(event_db, req.strategy_key),
        }

    return app
