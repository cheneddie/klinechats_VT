from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from server.causal_engine import ScanConfig
from server.coverage_guard import COVERAGE_POLICY_VERSION, evaluate_profile_coverage
from server.progress_scanner import scan_files_progress


def build_fixture(root: Path, days=None):
    days = days or ["2025-03-17", "2025-03-18"]
    rows = []
    for day_i, day in enumerate(days):
        base = 100.0 + day_i
        for i in range(80):
            rows.append({
                "datetime": pd.Timestamp(f"{day} 09:00:00") + pd.Timedelta(seconds=i),
                "product": "MTX",
                "expiry": "202503",
                "price": base + ((i % 12) - 6),
                "volume": 1 + (i % 5),
                "side": 0 if i == 0 else (1 if i % 2 else -1),
            })
    pd.DataFrame(rows).to_parquet(root / "MTX_2025.parquet", index=False, row_group_size=37)


def test_progress_reports_all_expensive_passes():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build_fixture(root)
        db = root / "events.sqlite3"
        reports = []
        cfg = ScanConfig(contract_mode="strict", roll_blackout_days=0)
        scan_files_progress(root, db, [2025], cfg, reports.append)
        phases = {x.get("phase") for x in reports}
        assert "prepare" in phases
        assert "catalog" in phases
        assert "contract_map" in phases
        assert "scan_rows" in phases
        assert "scan_day" in phases
        assert reports[-1]["phase"] == "done"
        assert reports[-1]["percent"] == 1.0
        assert reports[-1]["work_rows_processed"] == reports[-1]["work_rows_total"]
        assert any((x.get("file_rows_processed") or 0) > 0 for x in reports if x.get("phase") == "catalog")
        assert any((x.get("trading_days_found") or 0) >= 2 for x in reports if x.get("phase") == "contract_map")

        con = sqlite3.connect(db)
        try:
            rows = con.execute(
                "SELECT trading_date,policy_version,status,profile_chain_reset "
                "FROM source_coverage_audit ORDER BY trading_date"
            ).fetchall()
        finally:
            con.close()
        assert rows == [
            ("2025-03-17", COVERAGE_POLICY_VERSION, "FIRST_OBSERVED_DAY", 0),
            ("2025-03-18", COVERAGE_POLICY_VERSION, "PASS", 0),
        ]


def test_coverage_guard_keeps_normal_weekend_and_breaks_long_gap():
    weekend = evaluate_profile_coverage("2025-03-14", "2025-03-17")
    assert weekend["gap_calendar_days"] == 3
    assert weekend["status"] == "PASS"
    assert weekend["profile_chain_reset"] is False

    gap = evaluate_profile_coverage("2025-03-17", "2025-03-21")
    assert gap["gap_calendar_days"] == 4
    assert gap["status"] == "PROFILE_CHAIN_RESET"
    assert gap["reason"] == "CALENDAR_GAP_EXCEEDS_FROZEN_LIMIT"
    assert gap["profile_chain_reset"] is True


def test_scanner_persists_and_reports_profile_chain_reset():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build_fixture(root, ["2025-03-14", "2025-03-17", "2025-03-21"])
        db = root / "events.sqlite3"
        reports = []
        scan_files_progress(
            root,
            db,
            [2025],
            ScanConfig(contract_mode="strict", roll_blackout_days=0),
            reports.append,
        )

        con = sqlite3.connect(db)
        try:
            rows = con.execute(
                "SELECT trading_date,gap_calendar_days,status,reason,profile_chain_reset "
                "FROM source_coverage_audit ORDER BY trading_date"
            ).fetchall()
        finally:
            con.close()

        assert rows[1] == (
            "2025-03-17", 3, "PASS", "CONTIGUOUS_OR_NORMAL_WEEKEND_GAP", 0
        )
        assert rows[2] == (
            "2025-03-21", 4, "PROFILE_CHAIN_RESET", "CALENDAR_GAP_EXCEEDS_FROZEN_LIMIT", 1
        )
        assert any(
            x.get("phase") == "scan_day"
            and x.get("current_day") == "2025-03-21"
            and x.get("coverage_status") == "PROFILE_CHAIN_RESET"
            and x.get("coverage_breaks") == 1
            for x in reports
        )


if __name__ == "__main__":
    test_progress_reports_all_expensive_passes()
    test_coverage_guard_keeps_normal_weekend_and_breaks_long_gap()
    test_scanner_persists_and_reports_profile_chain_reset()
    print("scan progress tests: PASS")
