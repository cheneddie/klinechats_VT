from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.v5.campaigns import REAL_MTX_INTAKE_POLICY, get_campaign
from server.v5.real_mtx_bootstrap import (
    bootstrap_real_mtx_campaign,
    preflight_real_mtx_campaign,
)
from tools.bootstrap_real_mtx_campaign import main as bootstrap_cli_main


def _write_fixture(path: Path, year: int, *, invalid_price: bool = False) -> None:
    prices = [20000.0, 20001.0, 20002.0, 20003.0, 20010.0, 20011.0]
    if invalid_price:
        prices[2] = -1.0
    expiry = f"{year}01"
    table = pa.table({
        "datetime": pa.array([
            datetime.fromisoformat(f"{year}-01-02T08:45:00.100"),
            datetime.fromisoformat(f"{year}-01-02T08:45:00.200"),
            datetime.fromisoformat(f"{year}-01-02T08:45:01.000"),
            datetime.fromisoformat(f"{year}-01-03T08:45:00.000"),
            datetime.fromisoformat(f"{year}-01-03T08:45:01.000"),
            datetime.fromisoformat(f"{year}-01-03T08:45:02.000"),
        ], type=pa.timestamp("ms")),
        "product": ["MTX"] * 6,
        "expiry": [expiry] * 6,
        "price": prices,
        "volume": [5.0, 3.0, 4.0, 8.0, 7.0, 6.0],
        "side": ["B", "S", "B", "S", "B", "S"],
    })
    pq.write_table(table, path, row_group_size=3)


def _specs() -> list[dict]:
    return [
        {"dataset_id": "mtx-2025-discovery", "role": "DISCOVERY", "year": 2025, "source_file": "MTX_2025.parquet"},
        {"dataset_id": "mtx-2024-validation", "role": "VALIDATION", "year": 2024, "source_file": "MTX_2024.parquet"},
        {"dataset_id": "mtx-2026-final-holdout", "role": "FINAL_HOLDOUT", "year": 2026, "source_file": "MTX_2026.parquet"},
    ]


def _write_all(root: Path, *, bad_holdout: bool = False) -> None:
    _write_fixture(root / "MTX_2025.parquet", 2025)
    _write_fixture(root / "MTX_2024.parquet", 2024)
    _write_fixture(root / "MTX_2026.parquet", 2026, invalid_price=bad_holdout)


def test_atomic_bootstrap_preflights_all_roles_then_freezes_one_complete_campaign():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "events.sqlite3"
        _write_all(root)

        campaign = bootstrap_real_mtx_campaign(
            db,
            root,
            "real-dvh-v1",
            "Real MTX D/V/H",
            _specs(),
        )

        assert campaign["status"] == "FROZEN"
        assert campaign["frozen"] == 1
        assert campaign["governance"]["dataset_evidence_policy"] == REAL_MTX_INTAKE_POLICY
        assert {d["role"] for d in campaign["datasets"]} == {"DISCOVERY", "VALIDATION", "FINAL_HOLDOUT"}
        assert len(campaign["datasets"]) == 3
        for dataset in campaign["datasets"]:
            intake = dataset["metadata"]["real_mtx_intake"]
            assert dataset["metadata"]["source_class"] == "REAL_MTX"
            assert intake["status"] == "PASS"
            assert intake["failed_checks"] == []
            assert intake["synthetic_name"] is False
            assert dataset["sha256"] == intake["sha256"]
            assert len(dataset["sha256"]) == 64


def test_atomic_bootstrap_leaves_no_campaign_when_third_source_fails_preflight():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "events.sqlite3"
        _write_all(root, bad_holdout=True)

        with pytest.raises(RuntimeError, match="FINAL_HOLDOUT:MTX_2026.parquet") as exc:
            bootstrap_real_mtx_campaign(
                db,
                root,
                "real-dvh-v1",
                "Real MTX D/V/H",
                _specs(),
            )
        assert "MTX_OUTRIGHT_PRICE_VALID" in str(exc.value)
        with pytest.raises(KeyError):
            get_campaign(db, "real-dvh-v1")


def test_atomic_bootstrap_rejects_missing_or_duplicate_role_before_source_scan():
    malformed = [
        {"dataset_id": "a", "role": "DISCOVERY", "year": 2025, "source_file": "missing-a.parquet"},
        {"dataset_id": "b", "role": "VALIDATION", "year": 2024, "source_file": "missing-b.parquet"},
        {"dataset_id": "c", "role": "VALIDATION", "year": 2026, "source_file": "missing-c.parquet"},
    ]
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ValueError, match="exactly one dataset for each role"):
            preflight_real_mtx_campaign(Path(td), malformed)


def test_bootstrap_cli_writes_auditable_summary_and_freezes_campaign():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "events.sqlite3"
        out = root / "bootstrap-summary.json"
        _write_all(root)

        rc = bootstrap_cli_main([
            "--event-db", str(db),
            "--data-root", str(root),
            "--campaign-id", "real-dvh-cli-v1",
            "--out", str(out),
        ])
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["status"] == "PASS"
        assert payload["frozen"] is True
        assert payload["dataset_evidence_policy"] == REAL_MTX_INTAKE_POLICY
        assert len(payload["datasets"]) == 3
        assert {x["role"] for x in payload["datasets"]} == {"DISCOVERY", "VALIDATION", "FINAL_HOLDOUT"}
        assert all(len(x["sha256"]) == 64 for x in payload["datasets"])
        assert all(len(x["intake_report_hash"]) == 64 for x in payload["datasets"])


def test_bootstrap_cli_failure_reports_contract_and_does_not_leave_partial_campaign():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "events.sqlite3"
        out = root / "bootstrap-failure.json"
        _write_all(root, bad_holdout=True)

        rc = bootstrap_cli_main([
            "--event-db", str(db),
            "--data-root", str(root),
            "--campaign-id", "real-dvh-cli-fail",
            "--out", str(out),
        ])
        assert rc == 2
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["status"] == "FAIL"
        assert payload["database_mutation_contract"] == "NO_CAMPAIGN_WRITE_BEFORE_ALL_DVH_PREFLIGHT_PASS"
        assert "MTX_OUTRIGHT_PRICE_VALID" in payload["error"]
        with pytest.raises(KeyError):
            get_campaign(db, "real-dvh-cli-fail")
