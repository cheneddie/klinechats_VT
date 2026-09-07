from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .monitor import build_monitor_snapshot
from .production_deployment import (
    create_deployment_from_gate,
    deployment_status,
    list_deployment_actions,
    list_deployment_monitor_snapshots,
    list_deployments,
    persist_deployment_monitor_snapshot,
    record_deployment_action,
    verify_backtest_matches_deployment,
)
from .strategy_api import _load_backtest


class DeploymentCreateRequest(BaseModel):
    deployment_id: str | None = None
    notes: str | None = None


class DeploymentMonitorRequest(BaseModel):
    backtest_run_id: str
    baseline_backtest_run_id: str
    as_of_date: str
    window_days: int = Field(60, ge=5, le=730)
    policy: dict[str, Any] = Field(default_factory=dict)


class DeploymentActionRequest(BaseModel):
    action: str
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


def install_production_deployment_api(app, *, event_db: str | Path):
    event_db = Path(event_db)

    @app.post("/api/v5/strategy-lab/production-gates/{production_gate_id}/deployments")
    def deployment_create(production_gate_id: str, req: DeploymentCreateRequest):
        return create_deployment_from_gate(
            event_db,
            production_gate_id,
            deployment_id=req.deployment_id,
            notes=req.notes,
        )

    @app.get("/api/v5/strategy-lab/deployments")
    def deployment_list(limit: int = 200):
        return {"items": list_deployments(event_db, limit)}

    @app.get("/api/v5/strategy-lab/deployments/{deployment_id}")
    def deployment_get(deployment_id: str):
        return deployment_status(event_db, deployment_id)

    @app.post("/api/v5/strategy-lab/deployments/{deployment_id}/monitor-health")
    def deployment_monitor(deployment_id: str, req: DeploymentMonitorRequest):
        current_check = verify_backtest_matches_deployment(event_db, deployment_id, req.backtest_run_id)
        baseline_check = verify_backtest_matches_deployment(event_db, deployment_id, req.baseline_backtest_run_id)
        if not current_check["passed"]:
            raise ValueError(f"current monitoring backtest does not match deployment identity: {current_check['failed']}")
        if not baseline_check["passed"]:
            raise ValueError(f"baseline monitoring backtest does not match deployment identity: {baseline_check['failed']}")

        current = _load_backtest(event_db, req.backtest_run_id)
        baseline = _load_backtest(event_db, req.baseline_backtest_run_id)
        status = deployment_status(event_db, deployment_id)
        snapshot = build_monitor_snapshot(
            current["trades"],
            baseline["summary"],
            strategy_key=status["strategy_key"],
            as_of_date=req.as_of_date,
            window_days=req.window_days,
            policy=req.policy,
            baseline_trades=baseline["trades"],
        )
        snapshot = persist_deployment_monitor_snapshot(
            event_db,
            deployment_id,
            snapshot,
            source_backtest_run_id=req.backtest_run_id,
            baseline_backtest_run_id=req.baseline_backtest_run_id,
        )
        return {
            "snapshot": snapshot,
            "deployment": deployment_status(event_db, deployment_id),
            "identity_checks": {
                "current": current_check,
                "baseline": baseline_check,
            },
        }

    @app.get("/api/v5/strategy-lab/deployments/{deployment_id}/monitor-health")
    def deployment_monitor_list(deployment_id: str, limit: int = 200):
        return {
            "deployment": deployment_status(event_db, deployment_id),
            "items": list_deployment_monitor_snapshots(event_db, deployment_id, limit),
        }

    @app.get("/api/v5/strategy-lab/deployments/{deployment_id}/actions")
    def deployment_action_list(deployment_id: str, limit: int = 100):
        return {"items": list_deployment_actions(event_db, deployment_id, limit)}

    @app.post("/api/v5/strategy-lab/deployments/{deployment_id}/actions")
    def deployment_action(deployment_id: str, req: DeploymentActionRequest):
        action = record_deployment_action(
            event_db,
            deployment_id,
            req.action,
            req.reason,
            details=req.details,
        )
        return {
            "action": action,
            "deployment": deployment_status(event_db, deployment_id),
        }

    return app


__all__ = ["install_production_deployment_api"]
