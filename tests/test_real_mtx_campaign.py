from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.v5.campaigns import (
    REAL_MTX_INTAKE_POLICY,
    create_real_mtx_campaign,
    freeze_campaign,
    get_campaign,
    register_campaign_dataset,
    register_real_mtx_dataset,
)
from server.v5.storage import tx


def _write_real_fixture(path: Path) -> None:
    table = pa.table({
        "datetime": pa.array([
            datetime.fromisoformat("2025-01-02T08:45:00.100"),
            datetime.fromisoformat("2025-01-02T08:45:00.200"),
            datetime.fromisoformat("2025-01-02T08:45:01.000"),
            datetime.fromisoformat("2025-01-02T08:45:02.000"),
            datetime.fromisoformat("2025-01-03T08:45:00.000"),
            datetime.fromisoformat("2025-01-03T08:45:01.000"),
            datetime.fromisoformat("2025-01-03T08:45:02.000"),
            datetime.fromisoformat("2025-01-03T08:45:03.000"),
        ], type=pa.timestamp("ms")),
        "product": ["MTX"] * 8,
        "expiry": ["202501", "202501", "202501", "202501", "202502", "202502", "202502", "202502"],
        "price": [20000.0, 20001.0, 20002.0, 20003.0, 20010.0, 20011.0, 20012.0, 20013.0],
        "volume": [5.0, 3.0, 4.0, 2.0, 8.0, 7.0, 6.0, 5.0],
        "side": ["B", "S", "B", "S", "B", "S", "B", "S"],
    })
    pq.write_table(table, path, row_group_size=4)


def test_real_campaign_registers_from_passing_intake_and_freezes():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "events.sqlite3"
        source = root / "MTX_2025.parquet"
        _write_real_fixture(source)

        create_real_mtx_campaign(db, "real-campaign", "Real MTX research")
        registered = register_real_mtx_dataset(
            db,
            root,
            "real-campaign",
            "mtx-2025",
            "DISCOVERY",
            2025,
            source.name,
        )
        dataset = registered["datasets"][0]
        intake = dataset["metadata"]["real_mtx_intake"]
        assert registered["governance"]["dataset_evidence_policy"] == REAL_MTX_INTAKE_POLICY
        assert dataset["metadata"]["source_class"] == "REAL_MTX"
        assert dataset["sha256"] == intake["sha256"]
        assert intake["status"] == "PASS"
        assert intake["synthetic_name"] is False
        assert intake["failed_checks"] == []

        frozen = freeze_campaign(db, "real-campaign")
        assert frozen["frozen"] == 1
        assert frozen["status"] == "FROZEN"


def test_real_campaign_cannot_freeze_low_level_dataset_without_intake_evidence():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        create_real_mtx_campaign(db, "real-campaign", "Real MTX research")
        register_campaign_dataset(
            db,
            "real-campaign",
            "manual-dataset",
            "DISCOVERY",
            2025,
            "MTX_2025.parquet",
            "a" * 64,
            metadata={},
        )

        with pytest.raises(RuntimeError, match="valid intake evidence") as exc:
            freeze_campaign(db, "real-campaign")
        assert "INTAKE_NOT_PASS" in str(exc.value)
        assert "INTAKE_REPORT_HASH_INVALID" in str(exc.value)


def test_real_campaign_rejects_tampered_intake_report_hash_before_freeze():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "events.sqlite3"
        source = root / "MTX_2025.parquet"
        _write_real_fixture(source)
        create_real_mtx_campaign(db, "real-campaign", "Real MTX research")
        register_real_mtx_dataset(
            db,
            root,
            "real-campaign",
            "mtx-2025",
            "DISCOVERY",
            2025,
            source.name,
        )
        campaign = get_campaign(db, "real-campaign")
        metadata = campaign["datasets"][0]["metadata"]
        metadata["real_mtx_intake"]["report_hash"] = "0" * 64
        with tx(db) as c:
            c.execute(
                "UPDATE campaign_datasets SET metadata_json=? WHERE campaign_id=? AND dataset_id=?",
                (json.dumps(metadata, ensure_ascii=False, sort_keys=True), "real-campaign", "mtx-2025"),
            )

        with pytest.raises(RuntimeError, match="INTAKE_REPORT_HASH_INVALID"):
            freeze_campaign(db, "real-campaign")


def test_real_campaign_rejects_synthetic_source_during_registration():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "events.sqlite3"
        source = root / "MTX_2025_SYNTHETIC.parquet"
        _write_real_fixture(source)
        create_real_mtx_campaign(db, "real-campaign", "Real MTX research")

        with pytest.raises(RuntimeError, match="NOT_SYNTHETIC_SOURCE"):
            register_real_mtx_dataset(
                db,
                root,
                "real-campaign",
                "mtx-2025",
                "DISCOVERY",
                2025,
                source.name,
            )
