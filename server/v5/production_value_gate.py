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
from .strategy_registry import StrategyDefinition


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
    """Public Production Gate with immutable trading-value evidence.

    The existing strict gate owns provenance, exact D/V/H execution identity,
    parity/paper evidence and append-only gate persistence. This wrapper adds the
    missing economic-value layer before a candidate may receive a production PASS:

    * every D/V/H BASE ledger must have 100% frozen event-time ATR coverage;
    * average realized NET points / event-time ATR must be >= the frozen floor
      (default 10%);
    * D/V/H BASE ledgers are pooled for month/year profit concentration;
    * month/year concentration limits must be explicitly supplied in gate policy.

    A failed value audit creates an append-only FAIL gate. A passing value audit is
    persisted as an append-only companion record keyed to the strict gate decision.
    """
    value_audit = audit_candidate_production_value(
        event_db,
        candidate_id,
        policy=policy,
    )

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
    return result


__all__ = ["production_gate"]
