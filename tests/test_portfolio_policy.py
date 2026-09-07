from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.portfolio import PortfolioPolicy, arbitrate_trades


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


def test_policy_validation_is_explicit():
    with pytest.raises(ValueError, match="requires overlap_policy"):
        PortfolioPolicy(mode="SINGLE_POSITION").validate()
    with pytest.raises(ValueError, match="force_flat_time"):
        PortfolioPolicy(force_flat_time="25:99").validate()
