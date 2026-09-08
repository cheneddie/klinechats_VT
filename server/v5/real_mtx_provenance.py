from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .campaigns import REAL_MTX_INTAKE_POLICY, _verify_real_mtx_dataset_record
from .storage import connect
from .strategy_storage import migrate_strategy_db

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


def verify_candidate_real_mtx_provenance(
    event_db: str | Path,
    candidate_id: str,
) -> dict[str, Any]:
    """Verify the Real-MTX intake evidence carried by a D/V/H candidate.

    Backward-compatible synthetic/legacy campaigns are reported as non-applicable.
    If any evaluated role declares REAL_MTX_INTAKE_V1, all D/V/H roles must use that
    same evidence policy and every campaign dataset must retain a valid intake report.
    """
    migrate_strategy_db(event_db)
    c = connect(event_db)
    try:
        candidate = c.execute(
            "SELECT 1 FROM strategy_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        if not candidate:
            raise KeyError(f"candidate not found: {candidate_id}")
        evaluations = {
            str(r["role"]): dict(r)
            for r in c.execute(
                "SELECT * FROM candidate_evaluations WHERE candidate_id=?",
                (candidate_id,),
            ).fetchall()
        }
        roles: list[dict[str, Any]] = []
        any_real = False
        for role in ROLES:
            evaluation = evaluations.get(role)
            if not evaluation:
                roles.append({
                    "role": role,
                    "passed": False,
                    "real_mtx": False,
                    "reasons": ["MISSING_CANDIDATE_EVALUATION"],
                })
                continue
            run = c.execute(
                "SELECT campaign_id FROM research_runs WHERE research_run_id=?",
                (evaluation["research_run_id"],),
            ).fetchone()
            campaign_id = run["campaign_id"] if run else None
            campaign = c.execute(
                "SELECT governance_json,frozen FROM research_campaigns WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone() if campaign_id else None
            governance = _json(campaign["governance_json"], {}) if campaign else {}
            evidence_policy = str((governance or {}).get("dataset_evidence_policy") or "")
            source_class = str((governance or {}).get("source_class") or "")
            is_real = evidence_policy == REAL_MTX_INTAKE_POLICY or source_class == "REAL_MTX"
            any_real = any_real or is_real
            reasons: list[str] = []
            datasets: list[dict[str, Any]] = []
            if is_real:
                if evidence_policy != REAL_MTX_INTAKE_POLICY:
                    reasons.append("REAL_MTX_POLICY_MISSING")
                if source_class != "REAL_MTX":
                    reasons.append("REAL_MTX_SOURCE_CLASS_MISSING")
                if not campaign or not bool(campaign["frozen"]):
                    reasons.append("REAL_MTX_CAMPAIGN_NOT_FROZEN")
                raw_datasets = [
                    dict(r)
                    for r in c.execute(
                        "SELECT * FROM campaign_datasets WHERE campaign_id=? AND role=? ORDER BY dataset_id",
                        (campaign_id, role),
                    ).fetchall()
                ]
                if not raw_datasets:
                    reasons.append("REAL_MTX_ROLE_HAS_NO_DATASET")
                for raw in raw_datasets:
                    dataset = dict(raw)
                    dataset["metadata"] = _json(dataset.pop("metadata_json", None), {}) or {}
                    ds_reasons = _verify_real_mtx_dataset_record(dataset)
                    if ds_reasons:
                        reasons.extend(f"{dataset['dataset_id']}:{x}" for x in ds_reasons)
                    intake = (dataset.get("metadata") or {}).get("real_mtx_intake") or {}
                    datasets.append({
                        "dataset_id": dataset.get("dataset_id"),
                        "year": dataset.get("year"),
                        "source_file": dataset.get("source_file"),
                        "sha256": dataset.get("sha256"),
                        "intake_report_hash": intake.get("report_hash"),
                        "intake_status": intake.get("status"),
                        "passed": not ds_reasons,
                        "reasons": ds_reasons,
                    })
            roles.append({
                "role": role,
                "research_run_id": evaluation.get("research_run_id"),
                "campaign_id": campaign_id,
                "evidence_policy": evidence_policy or None,
                "source_class": source_class or None,
                "real_mtx": is_real,
                "datasets": datasets,
                "passed": not reasons,
                "reasons": reasons,
            })
    finally:
        c.close()

    if not any_real:
        return {
            "candidate_id": candidate_id,
            "applicable": False,
            "passed": True,
            "policy": REAL_MTX_INTAKE_POLICY,
            "reason": "NO_REAL_MTX_CAMPAIGN_DECLARED",
            "roles": roles,
        }

    for item in roles:
        if not item.get("real_mtx"):
            item.setdefault("reasons", []).append("MIXED_REAL_AND_LEGACY_CAMPAIGN")
            item["passed"] = False

    return {
        "candidate_id": candidate_id,
        "applicable": True,
        "passed": len(roles) == len(ROLES) and all(x.get("passed") and x.get("real_mtx") for x in roles),
        "policy": REAL_MTX_INTAKE_POLICY,
        "roles": roles,
    }


def require_candidate_real_mtx_provenance(
    event_db: str | Path,
    candidate_id: str,
) -> dict[str, Any]:
    result = verify_candidate_real_mtx_provenance(event_db, candidate_id)
    if result.get("applicable") and not result.get("passed"):
        failed = []
        for role in result.get("roles", []):
            failed.extend(f"{role['role']}:{x}" for x in role.get("reasons", []))
        raise RuntimeError("real MTX provenance verification failed: " + ";".join(failed))
    return result


__all__ = ["verify_candidate_real_mtx_provenance", "require_candidate_real_mtx_provenance"]
