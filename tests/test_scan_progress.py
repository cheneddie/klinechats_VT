from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from server.causal_engine import ScanConfig
from server.progress_scanner import scan_files_progress


def build_fixture(root: Path):
    rows = []
    for day_i, day in enumerate(["2025-03-17", "2025-03-18"]):
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


if __name__ == "__main__":
    test_progress_reports_all_expensive_passes()
    print("scan progress tests: PASS")
