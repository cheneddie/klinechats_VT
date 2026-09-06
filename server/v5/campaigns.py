from __future__ import annotations

import json
from pathlib import Path

from .storage import connect, migrate_event_db, tx, utcnow

ALLOWED_ROLES = {"DISCOVERY", "VALIDATION", "FINAL_HOLDOUT"}


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


def freeze_campaign(path, campaign_id):
    migrate_event_db(path)
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
