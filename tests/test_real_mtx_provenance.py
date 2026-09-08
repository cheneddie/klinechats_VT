from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from server.v5.campaigns import (
    create_campaign,
    create_real_mtx_campaign,
    freeze_campaign,
    register_campaign_dataset,
    register_real_mtx_dataset,
)
from server.v5.production_value_gate import _attach_real_mtx_provenance
from server.v5.real_mtx_provenance import verify_candidate_real_mtx_provenance
from server.v5.storage import migrate_event_db, tx
from server.v5.strategy_registry import content_hash
from server.v5.strategy_storage import migrate_strategy_db

ROLES = (
    ("DISCOVERY", "d", 2023),
    ("VALIDATION", "v", 2024),
    ("FINAL_HOLDOUT", "h", 2025),
)


def _write_fixture(path: Path, year: int) -> None:
    table = pa.table({
        "datetime": pa.array([
            datetime.fromisoformat(f"{year}-01-02T08:45:00.100"),
            datetime.fromisoformat(f"{year}-01-02T08:45:00.200"),
            datetime.fromisoformat(f"{year}-01-02T08:45:01.000"),
        ], type=pa.timestamp("ms")),
        "product": ["MTX"] * 3,
        "expiry": [f"{year}01"] * 3,
        "price": [20000.0, 20001.0, 20002.0],
        "volume": [2.0, 3.0, 4.0],
        "side": ["B", "S", "B"],
    })
    pq.write_table(table, path, row_group_size=2)


def _seed_candidate_rows(db: Path, campaign_by_role: dict[str, str]) -> None:
    migrate_event_db(db)
    migrate_strategy_db(db)
    with tx(db) as c:
        c.execute(
            """INSERT INTO strategy_candidates(
                 candidate_id,strategy_key,source_optimization_run_id,parameters_json,
                 parameters_hash,discovery_run_id,validation_run_id,holdout_run_id,
                 status,frozen_at,evidence_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "cand-real", "MR_BROAD@V3", None, "{}", "p" * 64,
                "d", "v", "h", "FROZEN_CANDIDATE", "2026-01-01T00:00:00Z", "{}",
            ),
        )
        for role, run_id, year in ROLES:
            c.execute(
                """INSERT INTO research_runs(
                     research_run_id,created_at,role,years_json,frozen,campaign_id
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    run_id, "2026-01-01T00:00:00Z", role, f"[{year}]", 1,
                    campaign_by_role[role],
                ),
            )
            c.execute(
                """INSERT INTO candidate_evaluations(
                     evaluation_id,candidate_id,role,research_run_id,backtest_run_id,
                     parameters_hash,created_at,result_json
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    f"eval-{run_id}", "cand-real", role, run_id, f"bt-{run_id}",
                    "p" * 64, "2026-01-01T00:00:00Z", "{}",
                ),
            )


def _seed_real_campaign(db: Path, root: Path, campaign_id: str = "real-all") -> None:
    create_real_mtx_campaign(db, campaign_id, "Real D/V/H")
    for role, _, year in ROLES:
        source = root / f"MTX_{year}.parquet"
        _write_fixture(source, year)
        register_real_mtx_dataset(
            db, root, campaign_id, f"mtx-{year}", role, year, source.name
        )
    freeze_campaign(db, campaign_id)


def test_candidate_real_mtx_provenance_passes_when_all_roles_are_intake_governed():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "events.sqlite3"
        _seed_real_campaign(db, root)
        _seed_candidate_rows(db, {role: "real-all" for role, _, _ in ROLES})

        result = verify_candidate_real_mtx_provenance(db, "cand-real")
        assert result["applicable"] is True
        assert result["passed"] is True, result
        assert all(x["real_mtx"] and x["passed"] for x in result["roles"])
        assert all(x["datasets"][0]["intake_status"] == "PASS" for x in result["roles"])


def test_candidate_real_mtx_provenance_rejects_mixed_real_and_legacy_roles():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "events.sqlite3"
        _seed_real_campaign(db, root)
        create_campaign(db, "legacy-v", "Legacy validation fixture")
        register_campaign_dataset(
            db, "legacy-v", "legacy-2024", "VALIDATION", 2024,
            "MTX_2024_LEGACY.parquet", "a" * 64,
        )
        freeze_campaign(db, "legacy-v")
        _seed_candidate_rows(db, {
            "DISCOVERY": "real-all",
            "VALIDATION": "legacy-v",
            "FINAL_HOLDOUT": "real-all",
        })

        result = verify_candidate_real_mtx_provenance(db, "cand-real")
        assert result["applicable"] is True
        assert result["passed"] is False
        validation = next(x for x in result["roles"] if x["role"] == "VALIDATION")
        assert "MIXED_REAL_AND_LEGACY_CAMPAIGN" in validation["reasons"]


def test_production_value_audit_freezes_real_mtx_provenance_check():
    base = {
        "candidate_id": "cand-real",
        "passed": True,
        "policy": {},
        "policy_hash": "x",
        "roles": {},
        "month_concentration": {},
        "year_concentration": {},
        "checks": [],
        "failed_checks": [],
        "methodology": {},
    }
    base["audit_hash"] = content_hash(base)
    provenance = {
        "candidate_id": "cand-real",
        "applicable": True,
        "passed": False,
        "policy": "REAL_MTX_INTAKE_V1",
        "roles": [{
            "role": "VALIDATION",
            "real_mtx": False,
            "passed": False,
            "reasons": ["MIXED_REAL_AND_LEGACY_CAMPAIGN"],
        }],
    }
    audit = _attach_real_mtx_provenance(base, provenance)

    assert audit["passed"] is False
    assert "REAL_MTX_INTAKE_PROVENANCE" in audit["failed_checks"]
    check = next(x for x in audit["checks"] if x["name"] == "REAL_MTX_INTAKE_PROVENANCE")
    assert check["passed"] is False
    assert audit["real_mtx_provenance"]["policy"] == "REAL_MTX_INTAKE_V1"
    assert audit["audit_hash"] == content_hash({k: v for k, v in audit.items() if k != "audit_hash"})
