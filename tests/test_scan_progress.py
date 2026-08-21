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
from server.coverage_guard import (
    COVERAGE_POLICY_VERSION,
    audit_observed_sessions,
    evaluate_profile_coverage,
)
from server.progress_scanner import scan_files_progress


def build_fixture(root: Path, days=None):
    days = days or ["2025-03-17", "2025-03-18"]
    rows = []
    for day_i, day in enumerate(days):
        base = 100.0 + day_i
        # Preserve the production contract rule inside the fixture too: after
        # March 2025's third-Wednesday expiry, only the next monthly contract is
        # a legal causal front-month candidate.
        expiry = "202503" if day <= "2025-03-19" else "202504"
        for i in range(80):
            rows.append({
                "datetime": pd.Timestamp(f"{day} 09:00:00") + pd.Timedelta(seconds=i),
                "product": "MTX",
                "expiry": expiry,
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


def test_exchange_calendar_guard_distinguishes_holidays_from_missing_sessions():
    weekend = evaluate_profile_coverage("2025-03-14", "2025-03-17")
    assert weekend["status"] == "PASS"
    assert weekend["missing_expected_sessions"] == []

    # A long official Lunar New Year closure must not be mistaken for a source
    # hole merely because the calendar-day distance is greater than three.
    cny = evaluate_profile_coverage("2025-01-22", "2025-02-03")
    assert cny["gap_calendar_days"] == 12
    assert cny["status"] == "PASS"
    assert cny["missing_expected_sessions"] == []

    # Extraordinary TAIFEX typhoon closures are also legitimate non-sessions.
    gaemi = evaluate_profile_coverage("2024-07-23", "2024-07-26")
    assert gaemi["status"] == "PASS"
    assert gaemi["missing_expected_sessions"] == []

    # The uploaded 2024 source's real anomaly: 12/27 was an expected trading
    # session but has no regular-session rows, so 12/30 may not inherit 12/26 PV.
    real_gap = evaluate_profile_coverage("2024-12-26", "2024-12-30")
    assert real_gap["status"] == "PROFILE_CHAIN_RESET"
    assert real_gap["missing_expected_sessions"] == ["2024-12-27"]
    assert real_gap["reason"] == "EXPECTED_TAIFEX_SESSION_MISSING|2024-12-27"


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
            "2025-03-17", 3, "PASS", "EXCHANGE_CALENDAR_CONTIGUOUS", 0
        )
        assert rows[2] == (
            "2025-03-21", 4, "PROFILE_CHAIN_RESET",
            "EXPECTED_TAIFEX_SESSION_MISSING|2025-03-18,2025-03-19,2025-03-20", 1
        )
        assert any(
            x.get("phase") == "scan_day"
            and x.get("current_day") == "2025-03-21"
            and x.get("coverage_status") == "PROFILE_CHAIN_RESET"
            and x.get("coverage_breaks") == 1
            for x in reports
        )


def test_file_level_calendar_audit_marks_partial_year_not_interior_gap():
    from server.coverage_guard import official_trading_sessions

    sessions = official_trading_sessions(2025)
    observed = sessions[:-7]
    audit = audit_observed_sessions(observed, 2025)
    assert audit["expected_days"] == 243
    assert audit["observed_days"] == 236
    assert audit["status"] == "PARTIAL_YEAR"
    assert audit["interior_missing_days"] == []
    assert audit["tail_missing_days"] == sessions[-7:]


if __name__ == "__main__":
    test_progress_reports_all_expensive_passes()
    test_exchange_calendar_guard_distinguishes_holidays_from_missing_sessions()
    test_scanner_persists_and_reports_profile_chain_reset()
    test_file_level_calendar_audit_marks_partial_year_not_interior_gap()
    print("scan progress tests: PASS")
