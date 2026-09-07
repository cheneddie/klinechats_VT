from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.execution import ExecutionModel
from server.v5.strategy_registry import content_hash


def test_js_zero_numbers_match_python_execution_defaults():
    python_default = ExecutionModel().to_dict()
    js_payload = ExecutionModel.from_dict({
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

    assert js_payload == python_default
    assert isinstance(js_payload["entry_slippage_points"], float)
    assert isinstance(js_payload["exit_slippage_points"], float)
    assert isinstance(js_payload["commission_points_per_side"], float)
    assert isinstance(js_payload["latency_ms"], int)
    assert content_hash(js_payload) == content_hash(python_default)


def test_form_numeric_strings_canonicalize_before_execution_hashing():
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

    assert from_form == typed
    assert content_hash(from_form) == content_hash(typed)


def test_direct_python_integer_construction_serializes_canonically():
    direct = ExecutionModel(
        entry_slippage_points=0,
        exit_slippage_points=0,
        commission_points_per_side=0,
        latency_ms=0,
    ).to_dict()
    default = ExecutionModel().to_dict()

    assert direct == default
    assert content_hash(direct) == content_hash(default)
