from __future__ import annotations

import pandas as pd
import pytest

from server.poc_absorption.bars import (
    BAR_RESOLUTIONS,
    build_bars,
    build_developing_poc,
    volume_profile_levels,
)


def frame(rows):
    return pd.DataFrame(rows, columns=["_seq", "datetime", "price", "volume"])


def test_all_required_resolutions_exist():
    assert BAR_RESOLUTIONS == {"15s": 15, "30s": 30, "1m": 60, "3m": 180, "5m": 300, "15m": 900}


def test_physical_order_controls_open_close_with_same_second_ticks():
    df = frame(
        [
            (100, "2026-08-03 08:45:00", 100.0, 2),
            (101, "2026-08-03 08:45:00", 103.0, 2),
            (102, "2026-08-03 08:45:00", 99.0, 2),
            (103, "2026-08-03 08:45:01", 101.0, 2),
        ]
    )
    bar = build_bars(df, "15s", "day")[0]
    assert (bar.open, bar.high, bar.low, bar.close) == (100.0, 103.0, 99.0, 101.0)
    assert (bar.bar_start_seq, bar.bar_end_seq) == (100, 103)


def test_session_anchor_not_generic_resample_origin():
    df = frame(
        [
            (1, "2026-08-03 08:45:00", 100.0, 2),
            (2, "2026-08-03 08:47:59", 101.0, 2),
            (3, "2026-08-03 08:48:00", 102.0, 2),
        ]
    )
    bars = build_bars(df, "3m", "day")
    assert [b.bar_start.strftime("%H:%M:%S") for b in bars] == ["08:45:00", "08:48:00"]


def test_poc_tie_breaks_nearest_vwap_then_prior_poc_then_lower():
    p = volume_profile_levels(
        {100.0: 10.0, 102.0: 10.0},
        total_volume=20.0,
        vwap=101.0,
        low=100.0,
        high=102.0,
        prior_poc=102.0,
    )
    assert p.poc == 102.0
    p2 = volume_profile_levels(
        {100.0: 10.0, 102.0: 10.0},
        total_volume=20.0,
        vwap=101.0,
        low=100.0,
        high=102.0,
        prior_poc=None,
    )
    assert p2.poc == 100.0


def test_developing_poc_tick_snapshots_never_see_future_ticks():
    df = frame(
        [
            (10, "2026-08-03 08:45:00", 100.0, 2),
            (11, "2026-08-03 08:45:00", 101.0, 8),
            (12, "2026-08-03 08:45:01", 100.0, 20),
        ]
    )
    full = build_developing_poc(df, "1m", "day", snapshot_mode="tick")
    prefix = build_developing_poc(df.iloc[:2], "1m", "day", snapshot_mode="tick")
    assert full[1] == prefix[-1]
    assert full[1].developing_poc == 101.0
    assert full[2].developing_poc == 100.0


def test_second_snapshot_uses_last_physical_tick_of_second():
    df = frame(
        [
            (10, "2026-08-03 08:45:00", 100.0, 2),
            (11, "2026-08-03 08:45:00", 101.0, 8),
            (12, "2026-08-03 08:45:01", 100.0, 20),
        ]
    )
    snaps = build_developing_poc(df, "1m", "day", snapshot_mode="second")
    assert [s.decision_seq for s in snaps] == [11, 12]
    assert snaps[0].decision_price == 101.0


def test_unsorted_seq_is_rejected_instead_of_silently_sorted():
    df = frame(
        [
            (2, "2026-08-03 08:45:00", 100.0, 2),
            (1, "2026-08-03 08:45:00", 101.0, 2),
        ]
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        build_bars(df, "15s", "day")


def test_atr_uses_completed_bars_only_and_starts_after_n_bars():
    df = frame(
        [
            (1, "2026-08-03 08:45:00", 100.0, 2),
            (2, "2026-08-03 08:45:14", 102.0, 2),
            (3, "2026-08-03 08:45:15", 103.0, 2),
            (4, "2026-08-03 08:45:29", 104.0, 2),
        ]
    )
    bars = build_bars(df, "15s", "day", atr_period=2)
    assert bars[0].atr_n is None
    assert bars[1].atr_n == pytest.approx(2.0)


def test_night_session_anchor_is_stable_across_midnight():
    df = frame(
        [
            (1, "2026-07-08 23:59:58", 100.0, 2),
            (2, "2026-07-08 23:59:59", 101.0, 2),
            (3, "2026-07-09 00:00:00", 102.0, 2),
            (4, "2026-07-09 00:00:01", 103.0, 2),
        ]
    )
    bars = build_bars(df, "15s", "night")
    assert [b.bar_start.strftime("%Y-%m-%d %H:%M:%S") for b in bars] == [
        "2026-07-08 23:59:45",
        "2026-07-09 00:00:00",
    ]
    assert bars[0].bar_end_seq == 2
    assert bars[1].bar_start_seq == 3
