from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .data_intake import inspect_mtx_parquet
from .storage import connect, migrate_event_db, tx, utcnow

ALLOWED_ROLES = {"DISCOVERY", "VALIDATION", "FINAL_HOLDOUT"}
REAL_MTX_INTAKE_POLICY = "REAL_MTX_INTAKE_V1"


def _canonical_intake_hash(report):
    clean = dict(report or {})
    clean.pop("generated_at", None)
    clean.pop("report_hash", None)
    clean.pop("path", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _verify_real_mtx_dataset_record(dataset):
    metadata = dataset.get("metadata") or {}
    intake = metadata.get("real_mtx_intake") or {}
    reasons = []
    if metadata.get("source_class") != "REAL_MTX":
        reasons.append("SOURCE_CLASS_NOT_REAL_MTX")
    if metadata.get("dataset_evidence_policy") != REAL_MTX_INTAKE_POLICY:
        reasons.append("DATASET_EVIDENCE_POLICY_MISMATCH")
    if intake.get("status") != "PASS":
        reasons.append("INTAKE_NOT_PASS")
    if intake.get("synthetic_name") is True:
        reasons.append("SYNTHETIC_SOURCE_FORBIDDEN")
    if intake.get("failed_checks"):
        reasons.append("INTAKE_HAS_FAILED_CHECKS")
    if str(intake.get("sha256") or "").lower() != str(dataset.get("sha256") or "").lower():
        reasons.append("INTAKE_SHA256_MISMATCH")
    if intake.get("file") != dataset.get("source_file"):
        reasons.append("INTAKE_SOURCE_FILE_MISMATCH")
    if intake.get("expected_year") is not None and int(intake.get("expected_year")) != int(dataset.get("year")):
        reasons.append("INTAKE_YEAR_MISMATCH")
    expected_hash = _canonical_intake_hash(intake) if intake else ""
    if not intake.get("report_hash") or intake.get("report_hash") != expected_hash:
        reasons.append("INTAKE_REPORT_HASH_INVALID")
    return reasons


def create_campaign(path, campaign_id, name, *, description="", governance=None, notes=""):
    migrate_event_db(path)
    governance = governance or {"roles": sorted(ALLOWED_ROLES)}
    with tx(path) as c:
        if c.execute("SELECT 1 FROM research_campaigns WHERE campaign_id=?", (campaign_id,)).fetchone():
            raise ValueError(f"campaign already exists: {campaign_id}")
        c.execute(
            """INSERT INTO research_campaigns(
              campaign_id,name,description,created_at,status,frozen,frozen_at,governance_json,notes
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (campaign_id, name, description, utcnow(), "OPEN", 0, None,
             json.dumps(governance, ensure_ascii=False, sort_keys=True), notes),
        )
    return get_campaign(path, campaign_id)


def create_real_mtx_campaign(path, campaign_id, name, *, description="", governance=None, notes=""):
    governed = dict(governance or {})
    governed.setdefault("roles", sorted(ALLOWED_ROLES))
    governed["dataset_evidence_policy"] = REAL_MTX_INTAKE_POLICY
    governed["source_class"] = "REAL_MTX"
    return create_campaign(
        path, campaign_id, name, description=description, governance=governed, notes=notes
    )


def register_campaign_dataset(
    path,
    campaign_id,
    dataset_id,
    role,
    year,
    source_file,
    sha256,
    *,
    start_time=None,
    end_time=None,
    metadata=None,
):
    migrate_event_db(path)
    role = str(role).upper()
    if role not in ALLOWED_ROLES:
        raise ValueError(f"unsupported campaign dataset role: {role}")
    digest = str(sha256 or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("dataset sha256 must be a 64-character hexadecimal digest")
    with tx(path) as c:
        campaign = c.execute(
            "SELECT frozen FROM research_campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if not campaign:
            raise KeyError(campaign_id)
        if bool(campaign["frozen"]):
            raise RuntimeError(f"research campaign is frozen: {campaign_id}")
        c.execute(
            """INSERT INTO campaign_datasets(
              campaign_id,dataset_id,role,year,source_file,sha256,start_time,end_time,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (campaign_id, dataset_id, role, int(year), source_file, digest, start_time, end_time,
             json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)),
        )
    return get_campaign(path, campaign_id)


def register_real_mtx_dataset(
    event_db,
    data_root,
    campaign_id,
    dataset_id,
    role,
    year,
    source_file,
    *,
    metadata=None,
):
    campaign = get_campaign(event_db, campaign_id)
    if (campaign.get("governance") or {}).get("dataset_evidence_policy") != REAL_MTX_INTAKE_POLICY:
        raise RuntimeError(
            f"campaign {campaign_id} is not governed by {REAL_MTX_INTAKE_POLICY}"
        )
    source_path = Path(data_root) / str(source_file)
    report = inspect_mtx_parquet(source_path, expected_year=int(year))
    if report.get("status") != "PASS":
        failed = ",".join(report.get("failed_checks") or [])
        raise RuntimeError(f"real MTX intake failed for {source_file}: {failed}")
    payload = dict(metadata or {})
    payload.update({
        "source_class": "REAL_MTX",
        "dataset_evidence_policy": REAL_MTX_INTAKE_POLICY,
        "real_mtx_intake": report,
    })
    return register_campaign_dataset(
        event_db,
        campaign_id,
        dataset_id,
        role,
        int(year),
        str(source_file),
        report["sha256"],
        start_time=(report.get("scan") or {}).get("start"),
        end_time=(report.get("scan") or {}).get("end"),
        metadata=payload,
    )


def freeze_campaign(path, campaign_id):
    migrate_event_db(path)
    campaign = get_campaign(path, campaign_id)
    governance = campaign.get("governance") or {}
    if governance.get("dataset_evidence_policy") == REAL_MTX_INTAKE_POLICY:
        evidence_failures = []
        for dataset in campaign.get("datasets") or []:
            reasons = _verify_real_mtx_dataset_record(dataset)
            if reasons:
                evidence_failures.append(f"{dataset.get('dataset_id')}:{','.join(reasons)}")
        if not campaign.get("datasets"):
            evidence_failures.append("NO_DATASETS")
        if evidence_failures:
            raise RuntimeError(
                "real MTX campaign cannot freeze without valid intake evidence: "
                + "; ".join(evidence_failures)
            )

    with tx(path) as c:
        row = c.execute(
            "SELECT frozen FROM research_campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if not row:
            raise KeyError(campaign_id)
        already_frozen = bool(row["frozen"])
        count = c.execute(
            "SELECT COUNT(*) n FROM campaign_datasets WHERE campaign_id=?", (campaign_id,)
        ).fetchone()["n"]
        if not count:
            raise RuntimeError("cannot freeze campaign without registered datasets")
        if not already_frozen:
            c.execute(
                "UPDATE research_campaigns SET frozen=1,status='FROZEN',frozen_at=? WHERE campaign_id=?",
                (utcnow(), campaign_id),
            )
    return get_campaign(path, campaign_id)


def get_campaign(path, campaign_id):
    migrate_event_db(path)
    c = connect(path)
    try:
        row = c.execute(
            "SELECT * FROM research_campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if not row:
            raise KeyError(campaign_id)
        item = dict(row)
        item["governance"] = json.loads(item.pop("governance_json") or "{}")
        item["datasets"] = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM campaign_datasets WHERE campaign_id=? ORDER BY role,year,dataset_id",
                (campaign_id,),
            ).fetchall()
        ]
        for dataset in item["datasets"]:
            dataset["metadata"] = json.loads(dataset.pop("metadata_json") or "{}")
        return item
    finally:
        c.close()


def list_campaigns(path):
    migrate_event_db(path)
    c = connect(path)
    try:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM research_campaigns ORDER BY created_at DESC,campaign_id"
            ).fetchall()
        ]
    finally:
        c.close()


def validate_campaign_governance(path, campaign_id, role, years):
    role = str(role).upper()
    if role not in ALLOWED_ROLES:
        raise ValueError(f"unsupported research role: {role}")
    requested = {int(y) for y in years}
    campaign = get_campaign(path, campaign_id)
    registered = {
        int(x["year"]) for x in campaign["datasets"] if x["role"] == role and x.get("year") is not None
    }
    if not registered:
        raise ValueError(f"campaign {campaign_id} has no dataset registered for role {role}")
    if requested != registered:
        raise ValueError(
            f"campaign {campaign_id} {role} must use exactly {sorted(registered)}, got {sorted(requested)}"
        )
    return role


def pin_run_datasets(path, research_run_id, campaign_id, role, years):
    validate_campaign_governance(path, campaign_id, role, years)
    campaign = get_campaign(path, campaign_id)
    chosen = [x for x in campaign["datasets"] if x["role"] == str(role).upper()]
    with tx(path) as c:
        for x in chosen:
            c.execute(
                """INSERT INTO research_run_datasets(
                  research_run_id,dataset_id,role,year,source_file,sha256,metadata_json
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    research_run_id, x["dataset_id"], x["role"], x.get("year"),
                    x["source_file"], x["sha256"],
                    json.dumps(x.get("metadata") or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
    return chosen


__all__ = [
    "ALLOWED_ROLES",
    "REAL_MTX_INTAKE_POLICY",
    "create_campaign",
    "create_real_mtx_campaign",
    "register_campaign_dataset",
    "register_real_mtx_dataset",
    "freeze_campaign",
    "get_campaign",
    "list_campaigns",
    "validate_campaign_governance",
    "pin_run_datasets",
]
