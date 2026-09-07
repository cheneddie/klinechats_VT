from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .production_gate import get_production_gate_context
from .storage import connect, tx, utcnow
from .strategy_registry import content_hash
from .strategy_storage import migrate_strategy_db

DEPLOYMENT_ACTIVE = "ACTIVE"
DEPLOYMENT_SUSPENDED = "SUSPENDED"
DEPLOYMENT_ACTIONS = {"ACKNOWLEDGE", "MANUAL_SUSPEND", "RESUME"}


def _json(value: Any, default=None):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _migrate(event_db: str | Path) -> None:
    migrate_strategy_db(event_db)
    with tx(event_db) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS production_deployments(
              deployment_id TEXT PRIMARY KEY,
              production_gate_id TEXT NOT NULL UNIQUE,
              candidate_id TEXT NOT NULL,
              strategy_key TEXT NOT NULL,
              strategy_hash TEXT NOT NULL,
              parameters_hash TEXT NOT NULL,
              execution_hash TEXT NOT NULL,
              execution_model_id TEXT NOT NULL,
              execution_model_version TEXT NOT NULL,
              portfolio_policy_hash TEXT NOT NULL,
              code_commit TEXT,
              created_at TEXT NOT NULL,
              identity_hash TEXT NOT NULL,
              identity_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_production_deployments_candidate
              ON production_deployments(candidate_id,created_at);

            CREATE TABLE IF NOT EXISTS production_deployment_controls(
              deployment_id TEXT PRIMARY KEY,
              lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE',
              updated_at TEXT NOT NULL,
              last_action_id TEXT,
              details_json TEXT NOT NULL DEFAULT '{}',
              CHECK(lifecycle_state IN ('ACTIVE','SUSPENDED'))
            );

            CREATE TABLE IF NOT EXISTS production_deployment_actions(
              action_id TEXT PRIMARY KEY,
              deployment_id TEXT NOT NULL,
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
            CREATE INDEX IF NOT EXISTS ix_production_deployment_actions
              ON production_deployment_actions(deployment_id,created_at);

            CREATE TABLE IF NOT EXISTS production_deployment_monitor_snapshots(
              snapshot_id TEXT PRIMARY KEY,
              deployment_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              as_of_date TEXT NOT NULL,
              window_days INTEGER NOT NULL,
              trades INTEGER NOT NULL,
              expectancy_r REAL,
              profit_factor REAL,
              max_drawdown_r REAL,
              win_rate REAL,
              avg_slippage_points REAL,
              signal_frequency REAL,
              state TEXT NOT NULL,
              regime_json TEXT NOT NULL DEFAULT '{}',
              details_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS ix_production_deployment_monitor
              ON production_deployment_monitor_snapshots(deployment_id,as_of_date,created_at);

            DROP TRIGGER IF EXISTS protect_production_deployments_update;
            CREATE TRIGGER protect_production_deployments_update
              BEFORE UPDATE ON production_deployments
              BEGIN SELECT RAISE(ABORT,'production deployment identity is immutable'); END;
            DROP TRIGGER IF EXISTS protect_production_deployments_delete;
            CREATE TRIGGER protect_production_deployments_delete
              BEFORE DELETE ON production_deployments
              BEGIN SELECT RAISE(ABORT,'production deployment identity is immutable'); END;
            DROP TRIGGER IF EXISTS protect_production_deployment_actions_update;
            CREATE TRIGGER protect_production_deployment_actions_update
              BEFORE UPDATE ON production_deployment_actions
              BEGIN SELECT RAISE(ABORT,'production deployment action is append-only'); END;
            DROP TRIGGER IF EXISTS protect_production_deployment_actions_delete;
            CREATE TRIGGER protect_production_deployment_actions_delete
              BEFORE DELETE ON production_deployment_actions
              BEGIN SELECT RAISE(ABORT,'production deployment action is append-only'); END;
            DROP TRIGGER IF EXISTS protect_production_deployment_monitor_update;
            CREATE TRIGGER protect_production_deployment_monitor_update
              BEFORE UPDATE ON production_deployment_monitor_snapshots
              BEGIN SELECT RAISE(ABORT,'production deployment monitor snapshot is append-only'); END;
            DROP TRIGGER IF EXISTS protect_production_deployment_monitor_delete;
            CREATE TRIGGER protect_production_deployment_monitor_delete
              BEFORE DELETE ON production_deployment_monitor_snapshots
              BEGIN SELECT RAISE(ABORT,'production deployment monitor snapshot is append-only'); END;
            """
        )


def _decode_deployment(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["identity"] = _json(out.get("identity_json"), {}) or {}
    return out


def _decode_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["regime"] = _json(out.get("regime_json"), {}) or {}
    out["details"] = _json(out.get("details_json"), {}) or {}
    return out


def get_deployment_control(event_db: str | Path, deployment_id: str) -> dict[str, Any]:
    _migrate(event_db)
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT * FROM production_deployment_controls WHERE deployment_id=?",
            (deployment_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(f"deployment control not found: {deployment_id}")
    out = dict(row)
    out["details"] = _json(out.get("details_json"), {}) or {}
    return out


def create_deployment_from_gate(
    event_db: str | Path,
    production_gate_id: str,
    *,
    deployment_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    _migrate(event_db)
    context = get_production_gate_context(event_db, production_gate_id)
    if not context.get("context_hash_valid"):
        raise RuntimeError("production gate context hash verification failed")
    identity = dict(context.get("execution_identity") or {})
    if not identity.get("passed"):
        raise RuntimeError("production gate execution identity is not deployable")

    c = connect(event_db)
    try:
        gate = c.execute(
            "SELECT * FROM production_gates WHERE production_gate_id=?",
            (production_gate_id,),
        ).fetchone()
    finally:
        c.close()
    if not gate:
        raise KeyError(production_gate_id)
    gate = dict(gate)
    if str(gate.get("status")) != "PASS":
        raise RuntimeError("production deployment requires a PASS production gate")
    if gate.get("candidate_id") != context.get("candidate_id"):
        raise RuntimeError("production gate context candidate mismatch")

    required = (
        "strategy_key",
        "strategy_hash",
        "parameters_hash",
        "execution_hash",
        "execution_model_id",
        "execution_model_version",
        "portfolio_policy_hash",
    )
    missing = [k for k in required if not identity.get(k)]
    if missing:
        raise RuntimeError(f"deployment identity is incomplete: {','.join(missing)}")

    deployment_id = deployment_id or ("deploy-" + uuid.uuid4().hex[:16])
    canonical_identity = {
        "deployment_id": deployment_id,
        "production_gate_id": production_gate_id,
        "gate_context_hash": context.get("context_hash"),
        "candidate_id": context["candidate_id"],
        "strategy_key": identity["strategy_key"],
        "strategy_hash": identity["strategy_hash"],
        "parameters_hash": identity["parameters_hash"],
        "execution_hash": identity["execution_hash"],
        "execution_model_id": identity["execution_model_id"],
        "execution_model_version": identity["execution_model_version"],
        "portfolio_policy_hash": identity["portfolio_policy_hash"],
        "code_commit": identity.get("code_commit"),
    }
    identity_hash = content_hash(canonical_identity)
    created_at = utcnow()
    with tx(event_db) as c:
        if c.execute(
            "SELECT 1 FROM production_deployments WHERE production_gate_id=?",
            (production_gate_id,),
        ).fetchone():
            raise ValueError("production gate already has an immutable deployment identity")
        c.execute(
            """INSERT INTO production_deployments(
                 deployment_id,production_gate_id,candidate_id,strategy_key,strategy_hash,
                 parameters_hash,execution_hash,execution_model_id,execution_model_version,
                 portfolio_policy_hash,code_commit,created_at,identity_hash,identity_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                deployment_id,
                production_gate_id,
                context["candidate_id"],
                identity["strategy_key"],
                identity["strategy_hash"],
                identity["parameters_hash"],
                identity["execution_hash"],
                identity["execution_model_id"],
                identity["execution_model_version"],
                identity["portfolio_policy_hash"],
                identity.get("code_commit"),
                created_at,
                identity_hash,
                json.dumps(canonical_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
        c.execute(
            "INSERT INTO production_deployment_controls VALUES(?,?,?,?,?)",
            (
                deployment_id,
                DEPLOYMENT_ACTIVE,
                created_at,
                None,
                json.dumps(
                    {"source": "PRODUCTION_GATE", "production_gate_id": production_gate_id, "notes": notes},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
    return deployment_status(event_db, deployment_id)


def get_deployment(event_db: str | Path, deployment_id: str) -> dict[str, Any]:
    _migrate(event_db)
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT * FROM production_deployments WHERE deployment_id=?",
            (deployment_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(f"deployment not found: {deployment_id}")
    return _decode_deployment(dict(row))


def list_deployments(event_db: str | Path, limit: int = 200) -> list[dict[str, Any]]:
    _migrate(event_db)
    c = connect(event_db)
    try:
        rows = [
            _decode_deployment(dict(r))
            for r in c.execute(
                "SELECT * FROM production_deployments ORDER BY created_at DESC LIMIT ?",
                (min(max(int(limit), 1), 2000),),
            ).fetchall()
        ]
    finally:
        c.close()
    return [deployment_status(event_db, x["deployment_id"]) for x in rows]


def verify_deployment_identity(event_db: str | Path, deployment_id: str) -> dict[str, Any]:
    deployment = get_deployment(event_db, deployment_id)
    identity = dict(deployment.get("identity") or {})
    expected = content_hash(identity)
    fields = {
        "deployment_id": deployment["deployment_id"],
        "production_gate_id": deployment["production_gate_id"],
        "candidate_id": deployment["candidate_id"],
        "strategy_key": deployment["strategy_key"],
        "strategy_hash": deployment["strategy_hash"],
        "parameters_hash": deployment["parameters_hash"],
        "execution_hash": deployment["execution_hash"],
        "execution_model_id": deployment["execution_model_id"],
        "execution_model_version": deployment["execution_model_version"],
        "portfolio_policy_hash": deployment["portfolio_policy_hash"],
        "code_commit": deployment.get("code_commit"),
    }
    mismatches = [k for k, v in fields.items() if identity.get(k) != v]
    return {
        "deployment_id": deployment_id,
        "valid": not mismatches and expected == deployment.get("identity_hash"),
        "identity_hash": deployment.get("identity_hash"),
        "computed_identity_hash": expected,
        "mismatches": mismatches,
    }


def verify_backtest_matches_deployment(
    event_db: str | Path,
    deployment_id: str,
    backtest_run_id: str,
) -> dict[str, Any]:
    deployment = get_deployment(event_db, deployment_id)
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT * FROM backtest_runs WHERE backtest_run_id=?",
            (backtest_run_id,),
        ).fetchone()
        audit = c.execute(
            """SELECT slice_value,payload_json FROM backtest_metrics
               WHERE backtest_run_id=? AND metric_key='portfolio_policy_audit'
               LIMIT 1""",
            (backtest_run_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(backtest_run_id)
    bt = dict(row)
    portfolio_hash = str(audit["slice_value"] if audit else "")
    checks = {
        "STRATEGY_KEY": bt.get("strategy_key") == deployment.get("strategy_key"),
        "STRATEGY_HASH": bt.get("strategy_hash") == deployment.get("strategy_hash"),
        "PARAMETERS_HASH": bt.get("parameters_hash") == deployment.get("parameters_hash"),
        "EXECUTION_HASH": bt.get("execution_hash") == deployment.get("execution_hash"),
        "EXECUTION_MODEL_ID": bt.get("execution_model_id") == deployment.get("execution_model_id"),
        "EXECUTION_MODEL_VERSION": bt.get("execution_model_version") == deployment.get("execution_model_version"),
        "PORTFOLIO_POLICY_HASH": portfolio_hash == deployment.get("portfolio_policy_hash"),
    }
    if deployment.get("code_commit"):
        checks["CODE_COMMIT"] = bt.get("code_commit") == deployment.get("code_commit")
    failed = [k for k, passed in checks.items() if not passed]
    return {
        "deployment_id": deployment_id,
        "backtest_run_id": backtest_run_id,
        "passed": not failed,
        "checks": checks,
        "failed": failed,
        "actual": {
            "strategy_key": bt.get("strategy_key"),
            "strategy_hash": bt.get("strategy_hash"),
            "parameters_hash": bt.get("parameters_hash"),
            "execution_hash": bt.get("execution_hash"),
            "execution_model_id": bt.get("execution_model_id"),
            "execution_model_version": bt.get("execution_model_version"),
            "portfolio_policy_hash": portfolio_hash,
            "code_commit": bt.get("code_commit"),
        },
    }


def persist_deployment_monitor_snapshot(
    event_db: str | Path,
    deployment_id: str,
    snapshot: dict[str, Any],
    *,
    source_backtest_run_id: str | None = None,
    baseline_backtest_run_id: str | None = None,
) -> dict[str, Any]:
    _migrate(event_db)
    deployment = get_deployment(event_db, deployment_id)
    if snapshot.get("strategy_key") != deployment.get("strategy_key"):
        raise ValueError("monitor snapshot strategy_key does not match deployment")

    snapshot = dict(snapshot)
    details = dict(snapshot.get("details") or {})
    reasons = list(details.get("reasons") or [])
    computed_state = str(snapshot.get("state") or "WATCH").upper()
    created_at = utcnow()
    snapshot_id = "deploy-health-" + uuid.uuid4().hex[:20]

    with tx(event_db) as c:
        control = c.execute(
            "SELECT * FROM production_deployment_controls WHERE deployment_id=?",
            (deployment_id,),
        ).fetchone()
        if not control:
            raise KeyError(f"deployment control not found: {deployment_id}")
        lifecycle = str(control["lifecycle_state"])
        effective_state = computed_state
        if lifecycle == DEPLOYMENT_SUSPENDED:
            effective_state = "SUSPEND"
            if "SUSPEND_LATCHED_BY_DEPLOYMENT_CONTROL" not in reasons:
                reasons.append("SUSPEND_LATCHED_BY_DEPLOYMENT_CONTROL")
        elif computed_state == "SUSPEND":
            lifecycle = DEPLOYMENT_SUSPENDED
            c.execute(
                """UPDATE production_deployment_controls SET
                     lifecycle_state=?,updated_at=?,details_json=? WHERE deployment_id=?""",
                (
                    DEPLOYMENT_SUSPENDED,
                    created_at,
                    json.dumps(
                        {"source": "AUTO_MONITOR", "as_of_date": snapshot.get("as_of_date"), "reasons": reasons},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    deployment_id,
                ),
            )

        details.update({
            "deployment_id": deployment_id,
            "source_backtest_run_id": source_backtest_run_id,
            "baseline_backtest_run_id": baseline_backtest_run_id,
            "computed_state": computed_state,
            "effective_state": effective_state,
            "lifecycle_state": lifecycle,
            "reasons": reasons,
        })
        snapshot["state"] = effective_state
        snapshot["details"] = details
        c.execute(
            """INSERT INTO production_deployment_monitor_snapshots(
                 snapshot_id,deployment_id,created_at,as_of_date,window_days,trades,
                 expectancy_r,profit_factor,max_drawdown_r,win_rate,avg_slippage_points,
                 signal_frequency,state,regime_json,details_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snapshot_id,
                deployment_id,
                created_at,
                snapshot["as_of_date"],
                snapshot["window_days"],
                snapshot["trades"],
                snapshot.get("expectancy_r"),
                snapshot.get("profit_factor"),
                snapshot.get("max_drawdown_r"),
                snapshot.get("win_rate"),
                snapshot.get("avg_slippage_points"),
                snapshot.get("signal_frequency"),
                effective_state,
                json.dumps(snapshot.get("regime") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
    snapshot["snapshot_id"] = snapshot_id
    snapshot["deployment_id"] = deployment_id
    snapshot["production_eligible"] = lifecycle == DEPLOYMENT_ACTIVE and effective_state != "SUSPEND"
    return snapshot


def list_deployment_monitor_snapshots(
    event_db: str | Path,
    deployment_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    _migrate(event_db)
    c = connect(event_db)
    try:
        rows = [
            _decode_snapshot(dict(r))
            for r in c.execute(
                """SELECT * FROM production_deployment_monitor_snapshots
                   WHERE deployment_id=? ORDER BY as_of_date DESC,created_at DESC LIMIT ?""",
                (deployment_id, min(max(int(limit), 1), 2000)),
            ).fetchall()
        ]
    finally:
        c.close()
    return rows


def record_deployment_action(
    event_db: str | Path,
    deployment_id: str,
    action: str,
    reason: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _migrate(event_db)
    action = str(action or "").strip().upper()
    reason = str(reason or "").strip()
    if action not in DEPLOYMENT_ACTIONS:
        raise ValueError(f"unsupported deployment action: {action}")
    if len(reason) < 3:
        raise ValueError("deployment action requires a human review reason")

    action_id = "deploy-action-" + uuid.uuid4().hex[:20]
    created_at = utcnow()
    with tx(event_db) as c:
        control = c.execute(
            "SELECT lifecycle_state FROM production_deployment_controls WHERE deployment_id=?",
            (deployment_id,),
        ).fetchone()
        if not control:
            raise KeyError(deployment_id)
        previous = str(control["lifecycle_state"])
        if action == "RESUME":
            if previous != DEPLOYMENT_SUSPENDED:
                raise ValueError("RESUME requires a currently SUSPENDED deployment")
            latest = c.execute(
                """SELECT details_json FROM production_deployment_monitor_snapshots
                   WHERE deployment_id=? ORDER BY as_of_date DESC,created_at DESC LIMIT 1""",
                (deployment_id,),
            ).fetchone()
            if not latest:
                raise ValueError("RESUME requires a deployment health snapshot")
            latest_details = _json(latest["details_json"], {}) or {}
            if str(latest_details.get("computed_state") or "") != "NORMAL":
                raise ValueError("RESUME requires latest computed deployment health state NORMAL")
            next_state = DEPLOYMENT_ACTIVE
        elif action == "MANUAL_SUSPEND":
            next_state = DEPLOYMENT_SUSPENDED
        else:
            next_state = previous

        payload = {"action": action, "reason": reason, **(details or {})}
        c.execute(
            """INSERT INTO production_deployment_actions(
                 action_id,deployment_id,created_at,action,reason,previous_state,next_state,details_json
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                action_id,
                deployment_id,
                created_at,
                action,
                reason,
                previous,
                next_state,
                json.dumps(details or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
        c.execute(
            """UPDATE production_deployment_controls SET
                 lifecycle_state=?,updated_at=?,last_action_id=?,details_json=? WHERE deployment_id=?""",
            (
                next_state,
                created_at,
                action_id,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                deployment_id,
            ),
        )
    return {
        "action_id": action_id,
        "deployment_id": deployment_id,
        "created_at": created_at,
        "action": action,
        "reason": reason,
        "previous_state": previous,
        "next_state": next_state,
        "details": details or {},
    }


def list_deployment_actions(
    event_db: str | Path,
    deployment_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _migrate(event_db)
    c = connect(event_db)
    try:
        rows = [dict(r) for r in c.execute(
            """SELECT * FROM production_deployment_actions
               WHERE deployment_id=? ORDER BY created_at DESC LIMIT ?""",
            (deployment_id, min(max(int(limit), 1), 1000)),
        ).fetchall()]
    finally:
        c.close()
    for row in rows:
        row["details"] = _json(row.get("details_json"), {}) or {}
    return rows


def deployment_status(event_db: str | Path, deployment_id: str) -> dict[str, Any]:
    deployment = get_deployment(event_db, deployment_id)
    control = get_deployment_control(event_db, deployment_id)
    identity = verify_deployment_identity(event_db, deployment_id)
    snapshots = list_deployment_monitor_snapshots(event_db, deployment_id, 1)
    latest = snapshots[0] if snapshots else None
    c = connect(event_db)
    try:
        gate = c.execute(
            "SELECT status FROM production_gates WHERE production_gate_id=?",
            (deployment["production_gate_id"],),
        ).fetchone()
    finally:
        c.close()
    gate_pass = bool(gate and str(gate["status"]) == "PASS")
    production_eligible = (
        gate_pass
        and bool(identity.get("valid"))
        and control.get("lifecycle_state") == DEPLOYMENT_ACTIVE
        and (not latest or latest.get("state") != "SUSPEND")
    )
    return {
        **deployment,
        "control": control,
        "latest_health": latest,
        "identity_verification": identity,
        "production_gate_pass": gate_pass,
        "production_eligible": production_eligible,
    }


__all__ = [
    "create_deployment_from_gate",
    "get_deployment",
    "list_deployments",
    "deployment_status",
    "verify_deployment_identity",
    "verify_backtest_matches_deployment",
    "persist_deployment_monitor_snapshot",
    "list_deployment_monitor_snapshots",
    "record_deployment_action",
    "list_deployment_actions",
    "get_deployment_control",
]
