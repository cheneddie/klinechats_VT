from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from .candidate import production_gate as _candidate_production_gate
from .storage import connect, tx, utcnow, verify_run_digest
from .strategy_registry import StrategyDefinition
from .strategy_storage import migrate_strategy_db

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ROLES = ("DISCOVERY", "VALIDATION", "FINAL_HOLDOUT")


def verify_candidate_provenance(event_db: str | Path, candidate_id: str) -> dict[str, Any]:
    """Verify that every candidate evaluation is tied to a frozen campaign dataset.

    Production evidence must be reproducible back to an immutable research campaign,
    frozen research run and exact SHA-256-pinned dataset. Diagnostic/legacy runs may
    still exist, but they cannot cross this production boundary.
    """
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

    # Digest verification opens its own connection; keep it outside the read handle.
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


def _persist_provenance_failure(
    event_db: str | Path,
    candidate_id: str,
    provenance: dict[str, Any],
    *,
    notes: str | None = None,
) -> dict[str, Any]:
    gate_id = "pgate-" + uuid.uuid4().hex[:16]
    checklist = [
        {
            "name": f"{item['role']}_PROVENANCE",
            "passed": bool(item.get("passed")),
            "details": item,
        }
        for item in provenance.get("roles", [])
    ]
    details = {
        "research_pass": False,
        "failed_checks": [x["name"] for x in checklist if not x["passed"]],
        "provenance": provenance,
        "notes": notes,
    }
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
    if not provenance["passed"]:
        return _persist_provenance_failure(event_db, candidate_id, provenance, notes=notes)
    result = _candidate_production_gate(
        event_db,
        candidate_id,
        strategy,
        policy=policy,
        parity_evidence_id=parity_evidence_id,
        paper_evidence_id=paper_evidence_id,
        notes=notes,
    )
    # The low-level candidate gate already persists the immutable decision. Add the
    # verified provenance to the returned decision without mutating that row.
    result["provenance"] = provenance
    return result


__all__ = ["production_gate", "verify_candidate_provenance"]
