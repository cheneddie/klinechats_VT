from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.compare_api import compare_contexts


def _ctx(*, dataset="d1", execution="e1", portfolio="p1", cost=None, code="abc"):
    return {
        "campaign_id": "c1",
        "dataset_digest": dataset,
        "contract_policy_version": "CP1",
        "mode": "PHYSICAL_TICK",
        "execution_hash": execution,
        "cost_profile": cost or {
            "fill_timing": "SIGNAL",
            "entry_slippage_points": 0.25,
            "exit_slippage_points": 0.25,
            "commission_points_per_side": 0.1,
            "latency_ms": 0,
        },
        "portfolio_policy_hash": portfolio,
        "code_commit": code,
    }


def test_same_data_and_execution_is_comparable_even_when_strategy_parameters_differ_elsewhere():
    out = compare_contexts([_ctx(), _ctx()])
    assert out["status"] == "COMPARABLE"
    assert out["failed"] == []
    assert all(x["passed"] for x in out["checks"])


def test_portfolio_policy_mismatch_blocks_interpretation():
    out = compare_contexts([_ctx(portfolio="p1"), _ctx(portfolio="p2", execution="e2")])
    assert out["status"] == "BLOCKED"
    assert "PORTFOLIO_POLICY_HASH" in out["failed"]
    assert "EXECUTION_HASH" in out["failed"]


def test_dataset_or_cost_mismatch_blocks_interpretation():
    changed_cost = {
        "fill_timing": "SIGNAL",
        "entry_slippage_points": 1.0,
        "exit_slippage_points": 0.25,
        "commission_points_per_side": 0.1,
        "latency_ms": 0,
    }
    out = compare_contexts([_ctx(), _ctx(dataset="d2", execution="e2", cost=changed_cost)])
    assert out["status"] == "BLOCKED"
    assert "DATASET_DIGEST" in out["failed"]
    assert "COST_SLIPPAGE_LATENCY" in out["failed"]
