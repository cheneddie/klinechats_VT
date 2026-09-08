from __future__ import annotations

import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from server.v5.data_intake import IntakePolicy, inspect_mtx_parquet


def _write_fixture(path: Path, *, reversed_time: bool = False, invalid_tick: bool = False) -> None:
    times = [
        "2025-01-02T08:45:00.100",
        "2025-01-02T08:45:00.200",
        "2025-01-02T08:45:01.000",
        "2025-01-02T08:45:02.000",
        "2025-01-03T08:45:00.000",
        "2025-01-03T08:45:01.000",
        "2025-01-03T08:45:02.000",
        "2025-01-03T08:45:03.000",
    ]
    if reversed_time:
        times[5], times[6] = times[6], times[5]
    prices = [20000.0, 20001.0, 20002.0, 20003.0, 20010.0, 20011.0, 20012.0, 20013.0]
    volumes = [5.0, 3.0, 4.0, 2.0, 8.0, 7.0, 6.0, 5.0]
    if invalid_tick:
        prices[1] = -1.0
        volumes[6] = -2.0
    table = pa.table({
        "datetime": pa.array(times, type=pa.timestamp("ms")),
        "product": ["MTX"] * 8,
        "expiry": ["202501", "202501", "202501", "202501/202502", "202502", "202502", "202502", "202502"],
        "price": prices,
        "volume": volumes,
        "side": ["B", "S", "B", "S", "B", "S", "B", "S"],
    })
    pq.write_table(table, path, row_group_size=4)


def test_real_mtx_intake_passes_structural_source_and_preserves_physical_order_metrics():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "MTX_2025.parquet"
        _write_fixture(path)
        report = inspect_mtx_parquet(path)
        again = inspect_mtx_parquet(path)

        assert report["status"] == "PASS", report
        assert report["failed_checks"] == []
        assert report["parquet"]["rows"] == 8
        assert report["parquet"]["row_groups"] == 2
        assert report["scan"]["rows_scanned"] == 8
        assert report["scan"]["physical_timestamp_reversals"] == 0
        assert report["scan"]["same_second"]["groups_with_multiple_rows"] == 1
        assert report["scan"]["same_second"]["max_group_rows"] == 2
        assert report["mtx"]["outright_rows"] == 7
        assert report["mtx"]["other_expiry_rows"] == 1
        assert report["mtx"]["expected_year_share"] == 1.0
        assert report["contract_days"]["days"] == 2
        assert report["contract_days"]["dominant_rolls"] == 1
        assert report["report_hash"] == again["report_hash"]


def test_real_mtx_intake_rejects_synthetic_source_name_by_default():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "MTX_2025_SYNTHETIC.parquet"
        _write_fixture(path)
        report = inspect_mtx_parquet(path)

        assert report["status"] == "FAIL"
        assert "NOT_SYNTHETIC_SOURCE" in report["failed_checks"]

        qa_only = inspect_mtx_parquet(path, policy=IntakePolicy(reject_synthetic=False))
        assert qa_only["status"] == "PASS", qa_only


def test_real_mtx_intake_rejects_physical_timestamp_reversal_without_sorting_it_away():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "MTX_2025.parquet"
        _write_fixture(path, reversed_time=True)
        report = inspect_mtx_parquet(path)

        assert report["status"] == "FAIL"
        assert report["scan"]["physical_timestamp_reversals"] >= 1
        assert "PHYSICAL_TIME_ORDER" in report["failed_checks"]


def test_real_mtx_intake_rejects_invalid_outright_price_and_volume():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "MTX_2025.parquet"
        _write_fixture(path, invalid_tick=True)
        report = inspect_mtx_parquet(path)

        assert report["status"] == "FAIL"
        assert report["mtx"]["invalid_price_rows"] == 1
        assert report["mtx"]["invalid_volume_rows"] == 1
        assert "MTX_OUTRIGHT_PRICE_VALID" in report["failed_checks"]
        assert "MTX_OUTRIGHT_VOLUME_VALID" in report["failed_checks"]
