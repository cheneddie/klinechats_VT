from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.execution import ExecutionModel, simulate_physical_trade
from server.v5.portfolio import PortfolioPolicy, arbitrate_trades
from server.v5.strategy_registry import content_hash


def _trade(
    trade_id: str,
    *,
    entry_time: str,
    exit_time: str,
    entry_seq: int,
    exit_seq: int,
    source: str = "MTX.parquet",
    contract: str = "202509",
):
    return {
        "trade_id": trade_id,
        "event_id": f"E-{trade_id}",
        "trading_date": "2025-09-01",
        "signal_seq": entry_seq,
        "signal_time": entry_time,
        "entry_seq": entry_seq,
        "entry_time": entry_time,
        "exit_seq": exit_seq,
        "exit_time": exit_time,
        "gross_points": 2.0,
        "net_points": 1.5,
        "payload": {"source_file": source, "contract": contract},
    }


def test_independent_event_preserves_overlapping_trades():
    trades = [
        _trade("A", entry_time="2025-09-01T09:00:00", exit_time="2025-09-01T09:05:00", entry_seq=10, exit_seq=50),
        _trade("B", entry_time="2025-09-01T09:01:00", exit_time="2025-09-01T09:02:00", entry_seq=20, exit_seq=30),
    ]
    accepted, skipped = arbitrate_trades(trades, PortfolioPolicy())
    assert [x["trade_id"] for x in accepted] == ["A", "B"]
    assert skipped == []
    assert all(x["quantity"] == pytest.approx(1.0) for x in accepted)
    assert accepted[0]["position_id"] == "pos:A"
    assert accepted[0]["payload"]["position_id"] == "pos:A"
    assert accepted[0]["payload"]["position_net_points"] == pytest.approx(1.5)


def test_single_position_skips_trade_while_position_open():
    policy = PortfolioPolicy(mode="SINGLE_POSITION", overlap_policy="SKIP_WHILE_OPEN")
    trades = [
        _trade("A", entry_time="2025-09-01T09:00:00", exit_time="2025-09-01T09:05:00", entry_seq=10, exit_seq=50),
        _trade("B", entry_time="2025-09-01T09:01:00", exit_time="2025-09-01T09:02:00", entry_seq=20, exit_seq=30),
        _trade("C", entry_time="2025-09-01T09:06:00", exit_time="2025-09-01T09:07:00", entry_seq=60, exit_seq=70),
    ]
    accepted, skipped = arbitrate_trades(trades, policy)
    assert [x["trade_id"] for x in accepted] == ["A", "C"]
    assert len(skipped) == 1
    assert skipped[0]["trade_id"] == "B"
    assert skipped[0]["reason"] == "PORTFOLIO_OVERLAP"
    assert skipped[0]["details"]["blocked_by_trade_id"] == "A"


def test_same_timestamp_uses_physical_seq_within_same_stream():
    policy = PortfolioPolicy(mode="SINGLE_POSITION", overlap_policy="SKIP_WHILE_OPEN")
    trades = [
        _trade("A", entry_time="2025-09-01T09:00:00", exit_time="2025-09-01T09:05:00", entry_seq=10, exit_seq=50),
        _trade("B", entry_time="2025-09-01T09:05:00", exit_time="2025-09-01T09:06:00", entry_seq=51, exit_seq=60),
    ]
    accepted, skipped = arbitrate_trades(trades, policy)
    assert [x["trade_id"] for x in accepted] == ["A", "B"]
    assert skipped == []


def test_same_timestamp_cross_stream_is_conservatively_skipped():
    policy = PortfolioPolicy(mode="SINGLE_POSITION", overlap_policy="SKIP_WHILE_OPEN")
    trades = [
        _trade("A", entry_time="2025-09-01T09:00:00", exit_time="2025-09-01T09:05:00", entry_seq=10, exit_seq=50, source="A.parquet"),
        _trade("B", entry_time="2025-09-01T09:05:00", exit_time="2025-09-01T09:06:00", entry_seq=100, exit_seq=120, source="B.parquet"),
    ]
    accepted, skipped = arbitrate_trades(trades, policy)
    assert [x["trade_id"] for x in accepted] == ["A"]
    assert skipped[0]["details"]["ordering_basis"] == "SAME_TIME_CROSS_STREAM"


def test_reentry_cooldown_blocks_too_early_reentry():
    policy = PortfolioPolicy(
        mode="SINGLE_POSITION",
        overlap_policy="SKIP_WHILE_OPEN",
        reentry_cooldown_seconds=120,
        fixed_quantity=2.0,
    )
    trades = [
        _trade("A", entry_time="2025-09-01T09:00:00", exit_time="2025-09-01T09:05:00", entry_seq=10, exit_seq=50),
        _trade("B", entry_time="2025-09-01T09:06:00", exit_time="2025-09-01T09:07:00", entry_seq=60, exit_seq=70),
        _trade("C", entry_time="2025-09-01T09:08:00", exit_time="2025-09-01T09:09:00", entry_seq=80, exit_seq=90),
    ]
    accepted, skipped = arbitrate_trades(trades, policy)
    assert [x["trade_id"] for x in accepted] == ["A", "C"]
    assert skipped[0]["reason"] == "PORTFOLIO_REENTRY_COOLDOWN"
    assert all(x["quantity"] == pytest.approx(2.0) for x in accepted)
    assert accepted[0]["payload"]["position_net_points"] == pytest.approx(3.0)


def test_forced_flat_is_first_physical_row_at_or_after_clock():
    path = pd.DataFrame({
        "_seq": [10, 11, 12, 13],
        "dt": pd.to_datetime([
            "2025-09-01T13:39:58",
            "2025-09-01T13:39:59",
            "2025-09-01T13:40:00",
            "2025-09-01T13:40:01",
        ]),
        "price": [100.0, 100.5, 101.0, 110.0],
    })
    out = simulate_physical_trade(
        path,
        direction="long",
        signal_seq=10,
        signal_price=100.0,
        stop_price=90.0,
        target_price=120.0,
        time_stop_seconds=None,
        force_flat_time="13:40:00",
    )
    assert out["exit_reason"] == "FORCED_FLAT"
    assert out["exit_seq"] == 12
    assert out["exit_price"] == pytest.approx(101.0)


def test_policy_validation_is_explicit():
    with pytest.raises(ValueError, match="requires overlap_policy"):
        PortfolioPolicy(mode="SINGLE_POSITION").validate()
    with pytest.raises(ValueError, match="force_flat_time"):
        PortfolioPolicy(force_flat_time="25:99").validate()


def test_json_numeric_types_canonicalize_to_stable_policy_hash():
    python_default = PortfolioPolicy().to_dict()
    js_round_trip = PortfolioPolicy.from_dict({
        "mode": "independent_event",
        "overlap_policy": "allow",
        "max_open_positions": 1,
        "reentry_cooldown_seconds": 0,
        "fixed_quantity": 1,
        "force_flat_time": "",
    }).to_dict()
    assert js_round_trip == python_default
    assert isinstance(js_round_trip["max_open_positions"], int)
    assert isinstance(js_round_trip["reentry_cooldown_seconds"], int)
    assert isinstance(js_round_trip["fixed_quantity"], float)
    assert js_round_trip["force_flat_time"] is None
    assert content_hash(js_round_trip) == content_hash(python_default)


def test_numeric_strings_canonicalize_before_policy_hashing():
    typed = PortfolioPolicy(
        mode="SINGLE_POSITION",
        overlap_policy="SKIP_WHILE_OPEN",
        max_open_positions=1,
        reentry_cooldown_seconds=60,
        fixed_quantity=2.0,
        force_flat_time="13:40:00",
    ).to_dict()
    from_json_form = PortfolioPolicy.from_dict({
        "mode": "single_position",
        "overlap_policy": "skip_while_open",
        "max_open_positions": "1",
        "reentry_cooldown_seconds": "60",
        "fixed_quantity": "2",
        "force_flat_time": "13:40:00",
    }).to_dict()
    assert from_json_form == typed
    assert content_hash(from_json_form) == content_hash(typed)


def test_execution_model_js_numbers_match_python_default_identity():
    python_default = ExecutionModel().to_dict()
    js_round_trip = ExecutionModel.from_dict({
        "execution_model_id": "PHYSICAL_MARKET",
        "version": "V1",
        "fill_timing": "signal",
        "entry_slippage_points": 0,
        "exit_slippage_points": 0,
        "commission_points_per_side": 0,
        "latency_ms": 0,
        "price_column": "price",
        "seq_column": "_seq",
        "time_column": "dt",
    }).to_dict()
    assert js_round_trip == python_default
    assert isinstance(js_round_trip["entry_slippage_points"], float)
    assert isinstance(js_round_trip["exit_slippage_points"], float)
    assert isinstance(js_round_trip["commission_points_per_side"], float)
    assert isinstance(js_round_trip["latency_ms"], int)
    assert content_hash(js_round_trip) == content_hash(python_default)


def test_execution_model_form_strings_and_direct_integers_hash_canonically():
    typed = ExecutionModel(
        execution_model_id="CUSTOM",
        version="V2",
        fill_timing="NEXT_TICK",
        entry_slippage_points=0.25,
        exit_slippage_points=0.50,
        commission_points_per_side=0.10,
        latency_ms=250,
    ).to_dict()
    from_form = ExecutionModel.from_dict({
        "execution_model_id": "CUSTOM",
        "version": "V2",
        "fill_timing": "next_tick",
        "entry_slippage_points": "0.25",
        "exit_slippage_points": "0.50",
        "commission_points_per_side": "0.10",
        "latency_ms": "250",
    }).to_dict()
    direct_zero = ExecutionModel(
        entry_slippage_points=0,
        exit_slippage_points=0,
        commission_points_per_side=0,
        latency_ms=0,
    ).to_dict()
    assert from_form == typed
    assert content_hash(from_form) == content_hash(typed)
    assert direct_zero == ExecutionModel().to_dict()
    assert content_hash(direct_zero) == content_hash(ExecutionModel().to_dict())
