"""M5 Development 3 continuous Balance measurements.

No threshold or signal classification is defined here. The engine consumes the
frozen M4 event store and Dev2 physical windows and measures path efficiency,
two-sided activity, time balance, retests and trigger-level crossings.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Iterable

import numpy as np
import pandas as pd

from .outcomes import FROZEN_HORIZONS, validate_probe_events, validate_probe_outcomes
from .physical_outcomes import compute_physical_tick_outcomes

BALANCE_SCHEMA_VERSION = "POC_M5_BALANCE_MEASUREMENT_V1"
BALANCE_REFERENCE_SCHEMA_VERSION = "POC_M5_BALANCE_REFERENCE_V1"
BALANCE_REQUIRED_EVENT_COLUMNS = ("rolling_high",)
BALANCE_COUNT_METRICS = ("one_second_close_count", "raw_tick_high_retest_count", "high_retest_count", "raw_tick_range_cross_count", "range_cross_count")

BALANCE_METRICS = (
    "raw_tick_total_path_points",
    "raw_tick_path_efficiency",
    "one_second_total_path_points",
    "one_second_path_efficiency",
    "one_second_close_count",
    "net_move_points",
    "net_move_atr",
    "up_excursion_atr",
    "down_excursion_atr",
    "future_range_atr",
    "two_sided_min_excursion_atr",
    "two_sided_total_excursion_atr",
    "time_above_trigger_seconds",
    "time_below_trigger_seconds",
    "time_at_trigger_seconds",
    "time_above_trigger_fraction",
    "time_below_trigger_fraction",
    "time_at_trigger_fraction",
    "raw_tick_high_retest_count",
    "high_retest_count",
    "raw_tick_range_cross_count",
    "range_cross_count",
)


def _canonical_reference_payload(event_id, trigger_price, rolling_high) -> bytes:
    return json.dumps(
        [str(event_id), float(trigger_price), float(rolling_high)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def build_balance_reference_manifest(events: pd.DataFrame) -> dict:
    """Freeze Dev3 reference levels without reopening the Dev1 event fingerprint."""
    validate_probe_events(events)
    missing = set(BALANCE_REQUIRED_EVENT_COLUMNS).difference(events.columns)
    if missing:
        raise ValueError(f"balance events missing columns: {sorted(missing)}")
    rolling_high = pd.to_numeric(events["rolling_high"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(rolling_high).all():
        raise ValueError("rolling_high must be finite for every Dev3 event")
    h = sha256()
    h.update((BALANCE_REFERENCE_SCHEMA_VERSION + "\n").encode("utf-8"))
    for eid, trigger, high in events[["event_id", "trigger_price", "rolling_high"]].itertuples(index=False, name=None):
        h.update(_canonical_reference_payload(eid, trigger, high))
        h.update(b"\n")
    return {
        "schema_version": BALANCE_REFERENCE_SCHEMA_VERSION,
        "event_count": int(len(events)),
        "hash_columns": ["event_id", "trigger_price", "rolling_high"],
        "balance_reference_hash": h.hexdigest(),
        "high_retest_reference_source": "M4.rolling_high",
        "range_cross_reference_source": "M4.trigger_price",
    }


def _count_crossings(values: np.ndarray, level: float) -> int:
    signs = np.sign(values - level)
    nonzero = signs[signs != 0]
    return int(np.sum(nonzero[1:] != nonzero[:-1])) if len(nonzero) >= 2 else 0


def _count_high_retests(values_with_trigger: np.ndarray, rolling_high: float) -> int:
    at_or_above = values_with_trigger >= rolling_high
    return int(np.sum((~at_or_above[:-1]) & at_or_above[1:]))


def _measure_balance_path(
    *,
    trigger_time,
    trigger_price: float,
    atr: float,
    rolling_high: float,
    future_time_ns: np.ndarray,
    future_price: np.ndarray,
    deadline_time,
) -> dict:
    """Pure continuous path measurement for one already-frozen future window."""
    fp = np.asarray(future_price, dtype=float)
    ft = np.asarray(future_time_ns, dtype=np.int64)
    result = {name: np.nan for name in BALANCE_METRICS}
    if len(fp) == 0:
        return result

    trigger_price = float(trigger_price)
    atr = float(atr)
    rolling_high = float(rolling_high)
    trigger_ns = np.datetime64(pd.Timestamp(trigger_time), "ns").astype(np.int64)
    deadline_ns = np.datetime64(pd.Timestamp(deadline_time), "ns").astype(np.int64)

    raw_path = np.r_[trigger_price, fp]
    raw_total = float(np.abs(np.diff(raw_path)).sum())
    net_move = float(fp[-1] - trigger_price)
    hi = float(fp.max())
    lo = float(fp.min())
    up = max(hi - trigger_price, 0.0) / atr
    down = max(trigger_price - lo, 0.0) / atr

    result.update(
        raw_tick_total_path_points=raw_total,
        raw_tick_path_efficiency=(abs(net_move) / raw_total if raw_total > 0 else np.nan),
        net_move_points=net_move,
        net_move_atr=net_move / atr,
        up_excursion_atr=up,
        down_excursion_atr=down,
        future_range_atr=(hi - lo) / atr,
        two_sided_min_excursion_atr=min(up, down),
        two_sided_total_excursion_atr=up + down,
    )

    # 1-second path: last physical future tick observed in each wall-clock second.
    seconds = ft // 1_000_000_000
    second_last = np.r_[seconds[1:] != seconds[:-1], True]
    second_close = fp[second_last]
    result["one_second_close_count"] = int(len(second_close))
    one_second_path = np.r_[trigger_price, second_close]
    one_second_total = float(np.abs(np.diff(one_second_path)).sum())
    one_second_net = float(second_close[-1] - trigger_price)
    result["one_second_total_path_points"] = one_second_total
    result["one_second_path_efficiency"] = (
        abs(one_second_net) / one_second_total if one_second_total > 0 else np.nan
    )

    # Time-weighted state. The state is trigger price until the first future tick,
    # then last observed physical price until the next tick/deadline.
    state_price = np.r_[trigger_price, fp]
    state_time = np.r_[trigger_ns, ft]
    state_end = np.r_[state_time[1:], deadline_ns]
    duration = np.maximum(state_end - state_time, 0).astype(float) / 1e9
    above = float(duration[state_price > trigger_price].sum())
    below = float(duration[state_price < trigger_price].sum())
    equal = float(duration[state_price == trigger_price].sum())
    effective = max(0.0, (deadline_ns - trigger_ns) / 1e9)
    result["time_above_trigger_seconds"] = above
    result["time_below_trigger_seconds"] = below
    result["time_at_trigger_seconds"] = equal
    if effective > 0:
        result["time_above_trigger_fraction"] = above / effective
        result["time_below_trigger_fraction"] = below / effective
        result["time_at_trigger_fraction"] = equal / effective

    # Raw counts are retained as a microstructure-sensitivity channel.
    result["raw_tick_high_retest_count"] = _count_high_retests(raw_path, rolling_high)
    result["raw_tick_range_cross_count"] = _count_crossings(fp, trigger_price)

    # Canonical counts use the 1-second close path to avoid treating same-second
    # transaction churn as repeated market retests/crossings.
    one_second_with_trigger = np.r_[trigger_price, second_close]
    result["high_retest_count"] = _count_high_retests(one_second_with_trigger, rolling_high)
    result["range_cross_count"] = _count_crossings(second_close, trigger_price)
    return result


def compute_balance_outcomes(
    events: pd.DataFrame,
    ticks: pd.DataFrame,
    *,
    contract: str,
    session: str,
    horizons: Iterable[str] = FROZEN_HORIZONS,
) -> pd.DataFrame:
    """Attach continuous Balance measurements to Dev2 physical outcome rows."""
    manifest = build_balance_reference_manifest(events)
    hs = tuple(horizons)
    physical = compute_physical_tick_outcomes(
        events, ticks, contract=str(contract), session=session, horizons=hs
    ).reset_index(drop=True)

    seq = pd.to_numeric(ticks["_seq"], errors="raise").to_numpy(dtype=np.int64)
    time_ns = pd.to_datetime(ticks["datetime"], errors="raise", format="mixed").to_numpy(dtype="datetime64[ns]").astype(np.int64)
    price = pd.to_numeric(ticks["price"], errors="raise").to_numpy(dtype=float)

    n = len(events)
    block: dict[str, object] = {
        "balance_schema_version": np.full(n, BALANCE_SCHEMA_VERSION, dtype=object),
        "balance_reference_schema_version": np.full(n, BALANCE_REFERENCE_SCHEMA_VERSION, dtype=object),
        "balance_reference_manifest_hash": np.full(n, manifest["balance_reference_hash"], dtype=object),
        "high_retest_reference_level": pd.to_numeric(events["rolling_high"], errors="raise").to_numpy(dtype=float),
        "high_retest_reference_source": np.full(n, "M4.rolling_high", dtype=object),
        "range_cross_reference_level": pd.to_numeric(events["trigger_price"], errors="raise").to_numpy(dtype=float),
        "range_cross_reference_source": np.full(n, "M4.trigger_price", dtype=object),
    }
    for h in hs:
        p = "h_" + h
        for metric in BALANCE_METRICS:
            block[f"{p}_{metric}"] = np.full(n, np.nan, dtype=float)

    event_rows = events.reset_index(drop=True)
    for i, event in event_rows.iterrows():
        for h in hs:
            p = "h_" + h
            count = int(physical.at[i, f"{p}_future_tick_count"])
            if count == 0:
                continue
            start_seq = int(physical.at[i, f"{p}_window_start_seq"])
            end_seq = int(physical.at[i, f"{p}_window_end_seq"])
            left = int(np.searchsorted(seq, start_seq, side="left"))
            right = int(np.searchsorted(seq, end_seq, side="right"))
            if right - left != count or left >= len(seq) or seq[left] != start_seq or seq[right - 1] != end_seq:
                raise AssertionError(f"Dev3 window coordinate mismatch for event={event.event_id}, horizon={h}")
            measured = _measure_balance_path(
                trigger_time=event.trigger_time,
                trigger_price=float(event.trigger_price),
                atr=float(event.atr),
                rolling_high=float(event.rolling_high),
                future_time_ns=time_ns[left:right],
                future_price=price[left:right],
                deadline_time=physical.at[i, f"{p}_deadline_time"],
            )
            for metric, value in measured.items():
                block[f"{p}_{metric}"][i] = value

    out = pd.concat([physical, pd.DataFrame(block)], axis=1)
    for h in hs:
        p = "h_" + h
        for metric in BALANCE_COUNT_METRICS:
            col = f"{p}_{metric}"
            out[col] = pd.array([None if pd.isna(v) else int(v) for v in out[col]], dtype="Int64")
    integrity = validate_probe_outcomes(events, out)
    if not integrity.all_pass:
        raise AssertionError("Dev3 Balance outcomes violated M4→M5 event contract")
    return out


__all__ = [
    "BALANCE_SCHEMA_VERSION",
    "BALANCE_REFERENCE_SCHEMA_VERSION",
    "BALANCE_METRICS",
    "BALANCE_COUNT_METRICS",
    "build_balance_reference_manifest",
    "compute_balance_outcomes",
]
