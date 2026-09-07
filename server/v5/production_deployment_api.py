from __future__ import annotations

from datetime import date, timedelta
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
from .production_gate import get_production_gate_context
from .production_observations import (
    execution_observation_digest,
    execution_observation_summary,
    execution_observations_as_trades,
    list_execution_observation_batches,
    list_execution_observations,
    record_execution_observation_batch,
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


class ExecutionObservationItem(BaseModel):
    source_execution_id: str
    source_signal_id: str
    observed_at: str
    trading_date: str | None = None
    direction: str
    entry_time: str
    exit_time: str
    expected_entry_price: float
    entry_price: float
    expected_exit_price: float
    exit_price: float
    risk_points: float = Field(gt=0)
    quantity: float = Field(1.0, gt=0)
    commission_points: float = Field(0.0, ge=0)
    fees_points: float = Field(0.0, ge=0)
    regime: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class ExecutionObservationBatchRequest(BaseModel):
    source_type: str
    producer: str
    deployment_identity_hash: str
    artifact_sha256: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    observations: list[ExecutionObservationItem] = Field(min_length=1, max_length=5000)


class DeploymentObservationMonitorRequest(BaseModel):
    source_type: str = "LIVE"
    as_of_date: str
    window_days: int = Field(60, ge=5, le=730)
    policy: dict[str, Any] = Field(default_factory=dict)


class DeploymentActionRequest(BaseModel):
    action: str
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


def _final_holdout_baseline(event_db: Path, deployment_id: str) -> tuple[str, dict[str, Any]]:
    status = deployment_status(event_db, deployment_id)
    context = get_production_gate_context(event_db, status["production_gate_id"])
    identity = context.get("execution_identity") or {}
    roles = identity.get("roles") or []
    final = next((x for x in roles if str(x.get("role")) == "FINAL_HOLDOUT"), None)
    if not final or not final.get("backtest_run_id"):
        raise RuntimeError("deployment gate context is missing FINAL_HOLDOUT BASE backtest")
    backtest_run_id = str(final["backtest_run_id"])
    check = verify_backtest_matches_deployment(event_db, deployment_id, backtest_run_id)
    if not check["passed"]:
        raise RuntimeError(f"FINAL_HOLDOUT baseline does not match deployment identity: {check['failed']}")
    return backtest_run_id, check


def _window_rows(rows: list[dict[str, Any]], as_of_date: str, window_days: int) -> list[dict[str, Any]]:
    try:
        end = date.fromisoformat(str(as_of_date)[:10])
    except Exception as exc:
        raise ValueError("as_of_date must be YYYY-MM-DD") from exc
    start = end - timedelta(days=max(1, int(window_days)) - 1)
    out = []
    for row in rows:
        try:
            trading_date = date.fromisoformat(str(row.get("trading_date"))[:10])
        except Exception:
            continue
        if start <= trading_date <= end:
            out.append(row)
    return out


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

    @app.post("/api/v5/strategy-lab/deployments/{deployment_id}/execution-observations")
    def deployment_execution_observations_create(deployment_id: str, req: ExecutionObservationBatchRequest):
        batch = record_execution_observation_batch(
            event_db,
            deployment_id,
            source_type=req.source_type,
            producer=req.producer,
            deployment_identity_hash=req.deployment_identity_hash,
            artifact_sha256=req.artifact_sha256,
            details=req.details,
            observations=[x.model_dump() for x in req.observations],
        )
        return {
            "batch": batch,
            "summary": execution_observation_summary(event_db, deployment_id),
            "deployment": deployment_status(event_db, deployment_id),
        }

    @app.get("/api/v5/strategy-lab/deployments/{deployment_id}/execution-observations")
    def deployment_execution_observations_list(
        deployment_id: str,
        source_type: str | None = None,
        limit: int = 1000,
    ):
        return {
            "summary": execution_observation_summary(event_db, deployment_id),
            "items": list_execution_observations(
                event_db,
                deployment_id,
                source_type=source_type,
                limit=limit,
            ),
        }

    @app.get("/api/v5/strategy-lab/deployments/{deployment_id}/execution-observation-batches")
    def deployment_execution_observation_batches_list(
        deployment_id: str,
        source_type: str | None = None,
        limit: int = 200,
    ):
        return {
            "items": list_execution_observation_batches(
                event_db,
                deployment_id,
                source_type=source_type,
                limit=limit,
            )
        }

    @app.post("/api/v5/strategy-lab/deployments/{deployment_id}/monitor-health")
    def deployment_monitor_backtest_preview(deployment_id: str, req: DeploymentMonitorRequest):
        """Research-only preview. Backtests cannot mutate production lifecycle state."""
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
        snapshot["details"] = {
            **(snapshot.get("details") or {}),
            "evidence_kind": "BACKTEST_PREVIEW",
            "authoritative": False,
            "source_backtest_run_id": req.backtest_run_id,
            "baseline_backtest_run_id": req.baseline_backtest_run_id,
        }
        return {
            "snapshot": snapshot,
            "deployment": status,
            "authoritative": False,
            "identity_checks": {
                "current": current_check,
                "baseline": baseline_check,
            },
        }

    @app.post("/api/v5/strategy-lab/deployments/{deployment_id}/monitor-health-observations")
    def deployment_monitor_observations(deployment_id: str, req: DeploymentObservationMonitorRequest):
        source = str(req.source_type or "").strip().upper()
        if source not in {"LIVE", "PAPER"}:
            raise ValueError("source_type must be LIVE or PAPER")

        baseline_backtest_run_id, baseline_check = _final_holdout_baseline(event_db, deployment_id)
        baseline = _load_backtest(event_db, baseline_backtest_run_id)
        status = deployment_status(event_db, deployment_id)
        rows = list_execution_observations(
            event_db,
            deployment_id,
            source_type=source,
            limit=50000,
        )
        trades = execution_observations_as_trades(
            event_db,
            deployment_id,
            source_type=source,
        )
        window_rows = _window_rows(rows, req.as_of_date, req.window_days)
        snapshot = build_monitor_snapshot(
            trades,
            baseline["summary"],
            strategy_key=status["strategy_key"],
            as_of_date=req.as_of_date,
            window_days=req.window_days,
            policy=req.policy,
            baseline_trades=baseline["trades"],
        )
        authoritative = source == "LIVE"
        snapshot["details"] = {
            **(snapshot.get("details") or {}),
            "evidence_kind": "EXECUTION_OBSERVATIONS",
            "source_type": source,
            "authoritative": authoritative,
            "observation_count": len(window_rows),
            "observation_digest": execution_observation_digest(window_rows),
            "baseline_backtest_run_id": baseline_backtest_run_id,
            "baseline_identity_check": baseline_check,
        }
        if authoritative:
            snapshot = persist_deployment_monitor_snapshot(
                event_db,
                deployment_id,
                snapshot,
                baseline_backtest_run_id=baseline_backtest_run_id,
            )
        return {
            "snapshot": snapshot,
            "deployment": deployment_status(event_db, deployment_id),
            "authoritative": authoritative,
            "source_type": source,
            "baseline_backtest_run_id": baseline_backtest_run_id,
            "baseline_identity_check": baseline_check,
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
