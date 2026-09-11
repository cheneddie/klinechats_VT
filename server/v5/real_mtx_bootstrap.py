from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .campaigns import (
    ALLOWED_ROLES,
    REAL_MTX_INTAKE_POLICY,
    _verify_real_mtx_dataset_record,
    get_campaign,
)
from .data_intake import inspect_mtx_parquet
from .storage import connect, migrate_event_db, tx, utcnow


REQUIRED_REAL_CAMPAIGN_ROLES = frozenset(ALLOWED_ROLES)


def _normalize_specs(datasets: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    dataset_ids: set[str] = set()
    roles: list[str] = []
    for raw in datasets:
        item = dict(raw or {})
        dataset_id = str(item.get("dataset_id") or "").strip()
        role = str(item.get("role") or "").strip().upper()
        source_file = str(item.get("source_file") or "").strip()
        try:
            year = int(item.get("year"))
        except Exception as exc:
            raise ValueError(f"invalid dataset year for {dataset_id or source_file or '<unknown>'}") from exc
        if not dataset_id:
            raise ValueError("dataset_id is required")
        if dataset_id in dataset_ids:
            raise ValueError(f"duplicate dataset_id: {dataset_id}")
        if role not in ALLOWED_ROLES:
            raise ValueError(f"unsupported campaign dataset role: {role}")
        if not source_file:
            raise ValueError(f"source_file is required for {dataset_id}")
        dataset_ids.add(dataset_id)
        roles.append(role)
        specs.append({
            "dataset_id": dataset_id,
            "role": role,
            "year": year,
            "source_file": source_file,
            "metadata": dict(item.get("metadata") or {}),
        })

    role_set = set(roles)
    if role_set != REQUIRED_REAL_CAMPAIGN_ROLES or len(roles) != len(REQUIRED_REAL_CAMPAIGN_ROLES):
        raise ValueError(
            "atomic Real MTX campaign requires exactly one dataset for each role: "
            "DISCOVERY, VALIDATION, FINAL_HOLDOUT"
        )
    return specs


def preflight_real_mtx_campaign(
    data_root: str | Path,
    datasets: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inspect every Real MTX source before any campaign database mutation.

    The returned records are ready for one atomic campaign transaction. A failed
    source raises before research_campaigns/campaign_datasets are touched.
    """
    root = Path(data_root)
    specs = _normalize_specs(datasets)
    prepared: list[dict[str, Any]] = []
    failures: list[str] = []

    for spec in specs:
        source_path = root / spec["source_file"]
        try:
            report = inspect_mtx_parquet(source_path, expected_year=spec["year"])
        except Exception as exc:
            failures.append(
                f"{spec['role']}:{spec['source_file']}:INTAKE_EXCEPTION:{type(exc).__name__}:{exc}"
            )
            continue
        if report.get("status") != "PASS":
            codes = ",".join(report.get("failed_checks") or []) or "UNKNOWN_INTAKE_FAILURE"
            failures.append(f"{spec['role']}:{spec['source_file']}:{codes}")
            continue

        metadata = dict(spec["metadata"])
        metadata.update({
            "source_class": "REAL_MTX",
            "dataset_evidence_policy": REAL_MTX_INTAKE_POLICY,
            "real_mtx_intake": report,
        })
        record = {
            "dataset_id": spec["dataset_id"],
            "role": spec["role"],
            "year": spec["year"],
            "source_file": spec["source_file"],
            "sha256": str(report["sha256"]).lower(),
            "start_time": (report.get("scan") or {}).get("start"),
            "end_time": (report.get("scan") or {}).get("end"),
            "metadata": metadata,
        }
        reasons = _verify_real_mtx_dataset_record(record)
        if reasons:
            failures.append(
                f"{spec['role']}:{spec['source_file']}:" + ",".join(reasons)
            )
            continue
        prepared.append(record)

    if failures:
        raise RuntimeError("Real MTX campaign preflight failed: " + "; ".join(failures))
    if len(prepared) != len(REQUIRED_REAL_CAMPAIGN_ROLES):
        raise RuntimeError("Real MTX campaign preflight did not produce all D/V/H datasets")
    return prepared


def bootstrap_real_mtx_campaign(
    event_db: str | Path,
    data_root: str | Path,
    campaign_id: str,
    name: str,
    datasets: Iterable[dict[str, Any]],
    *,
    description: str = "",
    governance: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Preflight all D/V/H sources, then create + register + freeze atomically.

    No research campaign row is written unless every physical Parquet source first
    passes REAL_MTX_INTAKE_V1. The final database mutation is a single transaction,
    so an insert/freeze error cannot leave a half-built campaign.
    """
    migrate_event_db(event_db)
    campaign_id = str(campaign_id or "").strip()
    name = str(name or "").strip()
    if not campaign_id:
        raise ValueError("campaign_id is required")
    if not name:
        raise ValueError("campaign name is required")

    c = connect(event_db)
    try:
        if c.execute(
            "SELECT 1 FROM research_campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone():
            raise ValueError(f"campaign already exists: {campaign_id}")
    finally:
        c.close()

    # Expensive physical scans happen before the campaign write transaction.
    prepared = preflight_real_mtx_campaign(data_root, datasets)

    governed = dict(governance or {})
    governed.setdefault("roles", sorted(ALLOWED_ROLES))
    governed["dataset_evidence_policy"] = REAL_MTX_INTAKE_POLICY
    governed["source_class"] = "REAL_MTX"
    now = utcnow()

    with tx(event_db) as c:
        # Re-check inside the transaction to close the race between preflight/read and write.
        if c.execute(
            "SELECT 1 FROM research_campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone():
            raise ValueError(f"campaign already exists: {campaign_id}")
        c.execute(
            """INSERT INTO research_campaigns(
              campaign_id,name,description,created_at,status,frozen,frozen_at,governance_json,notes
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                campaign_id,
                name,
                description,
                now,
                "OPEN",
                0,
                None,
                json.dumps(governed, ensure_ascii=False, sort_keys=True),
                notes,
            ),
        )
        for record in prepared:
            c.execute(
                """INSERT INTO campaign_datasets(
                  campaign_id,dataset_id,role,year,source_file,sha256,start_time,end_time,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    campaign_id,
                    record["dataset_id"],
                    record["role"],
                    int(record["year"]),
                    record["source_file"],
                    record["sha256"],
                    record["start_time"],
                    record["end_time"],
                    json.dumps(record["metadata"], ensure_ascii=False, sort_keys=True),
                ),
            )
        c.execute(
            "UPDATE research_campaigns SET frozen=1,status='FROZEN',frozen_at=? WHERE campaign_id=?",
            (utcnow(), campaign_id),
        )

    campaign = get_campaign(event_db, campaign_id)
    if not bool(campaign.get("frozen")) or campaign.get("status") != "FROZEN":
        raise RuntimeError(f"atomic Real MTX campaign failed to freeze: {campaign_id}")
    if len(campaign.get("datasets") or []) != len(REQUIRED_REAL_CAMPAIGN_ROLES):
        raise RuntimeError(f"atomic Real MTX campaign dataset count mismatch: {campaign_id}")
    return campaign


__all__ = [
    "REQUIRED_REAL_CAMPAIGN_ROLES",
    "preflight_real_mtx_campaign",
    "bootstrap_real_mtx_campaign",
]
