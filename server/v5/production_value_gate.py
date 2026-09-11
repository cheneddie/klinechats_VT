from __future__ import annotations

from pathlib import Path
from typing import Any

from .production_gate import (
    _persist_gate_context,
    _persist_gate_failure,
    production_gate as _strict_production_gate,
    verify_candidate_execution_identity,
    verify_candidate_provenance,
)
from .production_value import (
    audit_candidate_production_value,
    record_production_value_audit,
)
from .real_mtx_provenance import verify_candidate_real_mtx_provenance
from .strategy_registry import StrategyDefinition, content_hash


def _attach_real_mtx_provenance(value_audit: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    audit = dict(value_audit)
    audit["real_mtx_provenance"] = provenance
    checks = list(audit.get("checks") or [])
    check = {
        "name": "REAL_MTX_INTAKE_PROVENANCE",
        "passed": bool(provenance.get("passed")),
        "actual": provenance.get("policy") if provenance.get("applicable") else "NOT_APPLICABLE",
        "threshold": "PASS when any Real MTX campaign is declared",
        "details": provenance,
    }
    checks.append(check)
    audit["checks"] = checks
    if provenance.get("applicable") and not provenance.get("passed"):
        audit["passed"] = False
    audit["failed_checks"] = [x["name"] for x in checks if not x.get("passed")]
    audit.pop("audit_hash", None)
    audit["audit_hash"] = content_hash(audit)
    return audit


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
    """Public Production Gate with immutable trading-value and Real-MTX source evidence.

    The strict gate owns frozen campaign/run provenance, exact D/V/H execution identity,
    parity/paper evidence and append-only gate persistence. This wrapper additionally
    freezes the economic-value layer and, when a candidate declares a Real MTX
    campaign, the REAL_MTX_INTAKE_V1 source-evidence chain.
    """
    value_audit = audit_candidate_production_value(
        event_db,
        candidate_id,
        policy=policy,
    )
    real_mtx_provenance = verify_candidate_real_mtx_provenance(event_db, candidate_id)
    value_audit = _attach_real_mtx_provenance(value_audit, real_mtx_provenance)

    if not value_audit["passed"]:
        provenance = verify_candidate_provenance(event_db, candidate_id)
        execution_identity = verify_candidate_execution_identity(event_db, candidate_id, strategy)
        checklist = [
            {
                "name": item["name"],
                "passed": bool(item.get("passed")),
                "details": {
                    "actual": item.get("actual"),
                    "threshold": item.get("threshold"),
                    "details": item.get("details"),
                },
            }
            for item in value_audit.get("checks", [])
        ]
        checklist.extend(
            {
                "name": f"{item['role']}_PROVENANCE",
                "passed": bool(item.get("passed")),
                "details": item,
            }
            for item in provenance.get("roles", [])
        )
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
                "production_value": value_audit,
                "real_mtx_provenance": real_mtx_provenance,
                "provenance": provenance,
                "execution_identity": execution_identity,
                "policy": dict(policy or {}),
                "notes": notes,
            },
        )
        result = _persist_gate_context(
            event_db,
            result,
            provenance,
            execution_identity,
        )
    else:
        result = _strict_production_gate(
            event_db,
            candidate_id,
            strategy,
            policy=policy,
            parity_evidence_id=parity_evidence_id,
            paper_evidence_id=paper_evidence_id,
            notes=notes,
        )

    frozen_audit = record_production_value_audit(
        event_db,
        result["production_gate_id"],
        candidate_id,
        value_audit,
    )
    result["production_value"] = frozen_audit
    result["real_mtx_provenance"] = real_mtx_provenance
    return result


__all__ = ["production_gate"]
