from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from .candidate import production_gate as _candidate_production_gate
from .storage import connect, tx, utcnow, verify_run_digest
from .strategy_registry import StrategyDefinition, content_hash
from .strategy_storage import migrate_strategy_db, verify_backtest_digest

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ROLES = ("DISCOVERY", "VALIDATION", "FINAL_HOLDOUT")


def _json(value: Any, default=None):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _migrate_gate_contexts(event_db: str | Path) -> None:
    migrate_strategy_db(event_db)
    with tx(event_db) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS production_gate_contexts(
              production_gate_id TEXT PRIMARY KEY,
              candidate_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              context_hash TEXT NOT NULL,
              provenance_json TEXT NOT NULL,
              execution_identity_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_production_gate_context_candidate
              ON production_gate_contexts(candidate_id,created_at);
            DROP TRIGGER IF EXISTS protect_production_gate_contexts_update;
            CREATE TRIGGER protect_production_gate_contexts_update
              BEFORE UPDATE ON production_gate_contexts
              BEGIN SELECT RAISE(ABORT,'production gate context is append-only'); END;
            DROP TRIGGER IF EXISTS protect_production_gate_contexts_delete;
            CREATE TRIGGER protect_production_gate_contexts_delete
              BEFORE DELETE ON production_gate_contexts
              BEGIN SELECT RAISE(ABORT,'production gate context is append-only'); END;
            """
        )


def verify_candidate_provenance(event_db: str | Path, candidate_id: str) -> dict[str, Any]:
    """Verify every candidate evaluation against a frozen SHA-256-pinned campaign."""
    migrate_strategy_db(event_db)
    c = connect(event_db)
    try:
        candidate = c.execute(
            "SELECT * FROM strategy_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        if not candidate:
            raise KeyError(f"candidate not found: {candidate_id}")
        evaluations = {
            r["role"]: dict(r)
            for r in c.execute(
                "SELECT * FROM candidate_evaluations WHERE candidate_id=?",
                (candidate_id,),
            ).fetchall()
        }
        checks: list[dict[str, Any]] = []
        for role in ROLES:
            evaluation = evaluations.get(role)
            if not evaluation:
                checks.append({
                    "role": role,
                    "passed": False,
                    "reason": "MISSING_CANDIDATE_EVALUATION",
                })
                continue
            run_id = evaluation["research_run_id"]
            run = c.execute(
                "SELECT * FROM research_runs WHERE research_run_id=?", (run_id,)
            ).fetchone()
            if not run:
                checks.append({
                    "role": role,
                    "research_run_id": run_id,
                    "passed": False,
                    "reason": "MISSING_RESEARCH_RUN",
                })
                continue
            run = dict(run)
            campaign_id = run.get("campaign_id")
            campaign = c.execute(
                "SELECT * FROM research_campaigns WHERE campaign_id=?", (campaign_id,)
            ).fetchone() if campaign_id else None
            pinned = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM research_run_datasets WHERE research_run_id=? ORDER BY dataset_id",
                    (run_id,),
                ).fetchall()
            ]
            campaign_rows = {
                r["dataset_id"]: dict(r)
                for r in c.execute(
                    "SELECT * FROM campaign_datasets WHERE campaign_id=?", (campaign_id,)
                ).fetchall()
            } if campaign_id else {}

            reasons = []
            if str(run.get("role")) != role:
                reasons.append("RUN_ROLE_MISMATCH")
            if not bool(run.get("frozen")):
                reasons.append("RUN_NOT_FROZEN")
            if not campaign_id:
                reasons.append("MISSING_CAMPAIGN_ID")
            elif not campaign:
                reasons.append("MISSING_CAMPAIGN")
            elif not bool(campaign["frozen"]):
                reasons.append("CAMPAIGN_NOT_FROZEN")
            if not pinned:
                reasons.append("NO_PINNED_DATASETS")
            for dataset in pinned:
                digest = str(dataset.get("sha256") or "").lower()
                if not SHA256_RE.fullmatch(digest):
                    reasons.append(f"INVALID_DATASET_SHA256:{dataset.get('dataset_id')}")
                    continue
                source = campaign_rows.get(dataset.get("dataset_id"))
                if not source:
                    reasons.append(f"DATASET_NOT_IN_CAMPAIGN:{dataset.get('dataset_id')}")
                    continue
                for field in ("role", "year", "source_file", "sha256"):
                    if source.get(field) != dataset.get(field):
                        reasons.append(f"PIN_MISMATCH:{dataset.get('dataset_id')}:{field}")
            checks.append({
                "role": role,
                "research_run_id": run_id,
                "campaign_id": campaign_id,
                "datasets": [
                    {
                        "dataset_id": x.get("dataset_id"),
                        "source_file": x.get("source_file"),
                        "sha256": x.get("sha256"),
                    }
                    for x in pinned
                ],
                "passed": not reasons,
                "reasons": reasons,
            })
    finally:
        c.close()

    for item in checks:
        if not item.get("research_run_id"):
            continue
        try:
            integrity = verify_run_digest(event_db, item["research_run_id"])
            item["run_digest_valid"] = bool(integrity.get("valid"))
            item["run_digest"] = integrity.get("digest")
            if not item["run_digest_valid"]:
                item.setdefault("reasons", []).append("RESEARCH_DIGEST_INVALID")
                item["passed"] = False
        except Exception as exc:
            item["run_digest_valid"] = False
            item.setdefault("reasons", []).append(f"RESEARCH_DIGEST_ERROR:{exc}")
            item["passed"] = False

    return {
        "candidate_id": candidate_id,
        "passed": len(checks) == len(ROLES) and all(x.get("passed") for x in checks),
        "roles": checks,
        "policy": "FROZEN_CAMPAIGN + FROZEN_RUN_DIGEST + EXACT_DATASET_SHA256_PIN",
    }


def verify_candidate_execution_identity(
    event_db: str | Path,
    candidate_id: str,
    strategy: StrategyDefinition,
) -> dict[str, Any]:
    """Pin the exact realizable BASE execution identity across D/V/H.

    Stress scenarios are intentionally different. The BASE execution assumptions must
    be identical across Discovery, Validation and Final Holdout before a candidate is
    production-deployable.
    """
    migrate_strategy_db(event_db)
    c = connect(event_db)
    try:
        candidate_row = c.execute(
            "SELECT * FROM strategy_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        if not candidate_row:
            raise KeyError(f"candidate not found: {candidate_id}")
        candidate = dict(candidate_row)
        evidence = _json(candidate.get("evidence_json"), {}) or {}
        expected_portfolio_hash = str(evidence.get("portfolio_policy_hash") or "")
        evaluations = {
            r["role"]: dict(r)
            for r in c.execute(
                "SELECT * FROM candidate_evaluations WHERE candidate_id=?", (candidate_id,)
            ).fetchall()
        }
        roles: list[dict[str, Any]] = []
        for role in ROLES:
            evaluation = evaluations.get(role)
            if not evaluation:
                roles.append({"role": role, "passed": False, "reasons": ["MISSING_EVALUATION"]})
                continue
            backtest_run_id = evaluation.get("backtest_run_id")
            bt_row = c.execute(
                "SELECT * FROM backtest_runs WHERE backtest_run_id=?", (backtest_run_id,)
            ).fetchone()
            if not bt_row:
                roles.append({
                    "role": role,
                    "backtest_run_id": backtest_run_id,
                    "passed": False,
                    "reasons": ["MISSING_BASE_BACKTEST"],
                })
                continue
            bt = dict(bt_row)
            audit = c.execute(
                """SELECT slice_value,payload_json FROM backtest_metrics
                   WHERE backtest_run_id=? AND metric_key='portfolio_policy_audit'
                   LIMIT 1""",
                (backtest_run_id,),
            ).fetchone()
            portfolio_hash = str(audit["slice_value"] if audit else "")
            reasons: list[str] = []
            if bt.get("strategy_key") != candidate.get("strategy_key"):
                reasons.append("STRATEGY_KEY_MISMATCH")
            if bt.get("strategy_hash") != strategy.definition_hash:
                reasons.append("STRATEGY_HASH_MISMATCH")
            if bt.get("parameters_hash") != candidate.get("parameters_hash"):
                reasons.append("PARAMETERS_HASH_MISMATCH")
            if not bool(bt.get("frozen")):
                reasons.append("BASE_BACKTEST_NOT_FROZEN")
            if not str(bt.get("execution_hash") or ""):
                reasons.append("MISSING_EXECUTION_HASH")
            if not expected_portfolio_hash:
                reasons.append("MISSING_CANDIDATE_PORTFOLIO_HASH")
            elif portfolio_hash != expected_portfolio_hash:
                reasons.append("PORTFOLIO_POLICY_HASH_MISMATCH")
            roles.append({
                "role": role,
                "backtest_run_id": backtest_run_id,
                "research_run_id": evaluation.get("research_run_id"),
                "strategy_hash": bt.get("strategy_hash"),
                "parameters_hash": bt.get("parameters_hash"),
                "execution_hash": bt.get("execution_hash"),
                "execution_model_id": bt.get("execution_model_id"),
                "execution_model_version": bt.get("execution_model_version"),
                "portfolio_policy_hash": portfolio_hash,
                "code_commit": bt.get("code_commit"),
                "data_digest": bt.get("data_digest"),
                "passed": not reasons,
                "reasons": reasons,
            })
    finally:
        c.close()

    for item in roles:
        bt = item.get("backtest_run_id")
        if not bt:
            continue
        try:
            integrity = verify_backtest_digest(event_db, bt)
            item["backtest_digest_valid"] = bool(integrity.get("valid"))
            item["backtest_digest"] = integrity.get("digest")
            if not item["backtest_digest_valid"]:
                item.setdefault("reasons", []).append("BASE_BACKTEST_DIGEST_INVALID")
                item["passed"] = False
        except Exception as exc:
            item["backtest_digest_valid"] = False
            item.setdefault("reasons", []).append(f"BASE_BACKTEST_DIGEST_ERROR:{exc}")
            item["passed"] = False

    complete = [x for x in roles if x.get("execution_hash")]
    execution_hashes = {str(x.get("execution_hash")) for x in complete}
    execution_ids = {
        (str(x.get("execution_model_id")), str(x.get("execution_model_version")))
        for x in complete
    }
    portfolio_hashes = {str(x.get("portfolio_policy_hash")) for x in complete}
    strategy_hashes = {str(x.get("strategy_hash")) for x in complete}
    parameter_hashes = {str(x.get("parameters_hash")) for x in complete}
    commits = [str(x.get("code_commit")) for x in complete if x.get("code_commit")]
    commit_values = set(commits)
    warnings: list[str] = []
    global_reasons: list[str] = []
    if len(complete) != len(ROLES):
        global_reasons.append("INCOMPLETE_BASE_EXECUTION_IDENTITY")
    if len(execution_hashes) != 1:
        global_reasons.append("BASE_EXECUTION_HASH_MISMATCH")
    if len(execution_ids) != 1:
        global_reasons.append("BASE_EXECUTION_MODEL_MISMATCH")
    if len(portfolio_hashes) != 1:
        global_reasons.append("BASE_PORTFOLIO_POLICY_HASH_MISMATCH")
    if len(strategy_hashes) != 1 or strategy.definition_hash not in strategy_hashes:
        global_reasons.append("BASE_STRATEGY_HASH_MISMATCH")
    if len(parameter_hashes) != 1:
        global_reasons.append("BASE_PARAMETERS_HASH_MISMATCH")
    if commit_values and len(commit_values) != 1:
        global_reasons.append("BASE_CODE_COMMIT_MISMATCH")
    if commits and len(commits) != len(complete):
        global_reasons.append("BASE_CODE_COMMIT_PARTIALLY_PINNED")
    if not commits:
        warnings.append("BASE_CODE_COMMIT_UNPINNED")

    reference = complete[-1] if complete else {}
    passed = (
        len(roles) == len(ROLES)
        and all(x.get("passed") for x in roles)
        and not global_reasons
    )
    return {
        "candidate_id": candidate_id,
        "passed": passed,
        "strategy_key": candidate.get("strategy_key"),
        "strategy_hash": strategy.definition_hash,
        "parameters_hash": candidate.get("parameters_hash"),
        "portfolio_policy_hash": expected_portfolio_hash or None,
        "execution_hash": reference.get("execution_hash"),
        "execution_model_id": reference.get("execution_model_id"),
        "execution_model_version": reference.get("execution_model_version"),
        "code_commit": reference.get("code_commit"),
        "roles": roles,
        "reasons": global_reasons,
        "warnings": warnings,
        "policy": "D/V/H BASE MUST SHARE STRATEGY + PARAMETERS + EXECUTION + PORTFOLIO IDENTITY",
    }


def _persist_gate_failure(
    event_db: str | Path,
    candidate_id: str,
    *,
    checklist: list[dict[str, Any]],
    details: dict[str, Any],
) -> dict[str, Any]:
    gate_id = "pgate-" + uuid.uuid4().hex[:16]
    details = dict(details)
    details.setdefault("research_pass", False)
    details["failed_checks"] = [x["name"] for x in checklist if not x["passed"]]
    with tx(event_db) as c:
        c.execute(
            "INSERT INTO production_gates VALUES(?,?,?,?,?,?)",
            (
                gate_id,
                candidate_id,
                utcnow(),
                "FAIL",
                json.dumps(checklist, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
    return {
        "production_gate_id": gate_id,
        "candidate_id": candidate_id,
        "status": "FAIL",
        "checklist": checklist,
        "details": details,
    }


def _persist_gate_context(
    event_db: str | Path,
    result: dict[str, Any],
    provenance: dict[str, Any],
    execution_identity: dict[str, Any],
) -> dict[str, Any]:
    _migrate_gate_contexts(event_db)
    context = {
        "candidate_id": result["candidate_id"],
        "production_gate_id": result["production_gate_id"],
        "gate_status": result["status"],
        "provenance": provenance,
        "execution_identity": execution_identity,
    }
    context_hash = content_hash(context)
    with tx(event_db) as c:
        c.execute(
            """INSERT INTO production_gate_contexts(
                 production_gate_id,candidate_id,created_at,context_hash,provenance_json,execution_identity_json
               ) VALUES(?,?,?,?,?,?)""",
            (
                result["production_gate_id"],
                result["candidate_id"],
                utcnow(),
                context_hash,
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                json.dumps(execution_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
    result["provenance"] = provenance
    result["execution_identity"] = execution_identity
    result["gate_context_hash"] = context_hash
    return result


def get_production_gate_context(event_db: str | Path, production_gate_id: str) -> dict[str, Any]:
    _migrate_gate_contexts(event_db)
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT * FROM production_gate_contexts WHERE production_gate_id=?",
            (production_gate_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(f"production gate context not found: {production_gate_id}")
    out = dict(row)
    out["provenance"] = _json(out.get("provenance_json"), {}) or {}
    out["execution_identity"] = _json(out.get("execution_identity_json"), {}) or {}
    expected = content_hash({
        "candidate_id": out["candidate_id"],
        "production_gate_id": out["production_gate_id"],
        "gate_status": _gate_status(event_db, out["production_gate_id"]),
        "provenance": out["provenance"],
        "execution_identity": out["execution_identity"],
    })
    out["context_hash_valid"] = expected == out.get("context_hash")
    return out


def _gate_status(event_db: str | Path, production_gate_id: str) -> str:
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT status FROM production_gates WHERE production_gate_id=?",
            (production_gate_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(production_gate_id)
    return str(row["status"])


def production_gate(
    event_db: str | Path,
    candidate_id: str,
    strategy: StrategyDefinition,
    *,
    policy: dict[str, Any] | None = None,
    parity_evidence_id: str | None = None,
    paper_evidence_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    provenance = verify_candidate_provenance(event_db, candidate_id)
    execution_identity = verify_candidate_execution_identity(event_db, candidate_id, strategy)

    if not provenance["passed"] or not execution_identity["passed"]:
        checklist = [
            {
                "name": f"{item['role']}_PROVENANCE",
                "passed": bool(item.get("passed")),
                "details": item,
            }
            for item in provenance.get("roles", [])
        ]
        checklist.append({
            "name": "EXACT_BASE_EXECUTION_IDENTITY",
            "passed": bool(execution_identity.get("passed")),
            "details": execution_identity,
        })
        result = _persist_gate_failure(
            event_db,
            candidate_id,
            checklist=checklist,
            details={
                "research_pass": False,
                "provenance": provenance,
                "execution_identity": execution_identity,
                "notes": notes,
            },
        )
        return _persist_gate_context(event_db, result, provenance, execution_identity)

    result = _candidate_production_gate(
        event_db,
        candidate_id,
        strategy,
        policy=policy,
        parity_evidence_id=parity_evidence_id,
        paper_evidence_id=paper_evidence_id,
        notes=notes,
    )
    return _persist_gate_context(event_db, result, provenance, execution_identity)


__all__ = [
    "production_gate",
    "verify_candidate_provenance",
    "verify_candidate_execution_identity",
    "get_production_gate_context",
]
