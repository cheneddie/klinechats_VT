"""M5 Development 4 frozen-reference structure-break / reversal outcomes.

Reference placement is causal and separated from future-path measurement. Future
ordering is physical `_seq` only; this module defines outcomes, not a trade signal.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .balance_outcomes import compute_balance_outcomes
from .outcomes import FROZEN_HORIZONS, validate_probe_events, validate_probe_outcomes

REVERSAL_SCHEMA_VERSION = "POC_M5_REVERSAL_MEASUREMENT_V1"
REVERSAL_REFERENCE_SCHEMA_VERSION = "POC_M5_REVERSAL_REFERENCE_V1"
MICRO_SWING_ALGORITHM_VERSION = "STRICT_CONFIRMED_PIVOT_LOW_R2_WITHIN_LAST24_V1"
PIVOT_RADIUS = 2
PIVOT_SEARCH_LOOKBACK_BARS = 24
REFERENCE_NAMES = ("channel_midline", "micro_swing_low", "channel_low")
REFERENCE_PARAMETERS = {
    "pivot_radius": 2,
    "pivot_search_lookback_bars": 24,
    "pivot_rule": "candidate low strictly below all 2 left + 2 right completed-bar lows; entire 5-bar pivot window lies inside latest 24 completed bars including trigger",
    "break_rule": "first physical future tick with price strictly below frozen reference",
    "new_high_rule": "first physical future tick with price strictly above frozen channel high",
    "no_fallback": True,
    "no_observation_policy": "all Dev4 outcome fields NA when future_tick_count=0",
    "simultaneous_break_policy": "record every reference sharing the first physical break seq in canonical reference order",
    "continuity_semantics": "same contract + same session + no DATA_GAP continuity partition; completed-bar lookback may span consecutive trading days like M3/M4",
}
REFERENCE_HASH_COLUMNS = (
    "event_id", "trigger_price", "channel_high_reference_level",
    "channel_midline_reference_level", "channel_low_reference_level",
    "channel_midline_break_eligible", "channel_low_break_eligible",
    "micro_swing_reference_available", "micro_swing_break_eligible",
    "micro_swing_low_reference_level", "micro_swing_bar_start_seq",
    "micro_swing_bar_end_seq", "micro_swing_bar_start_time",
)
BOOL_METRICS = (
    "made_new_high", "break_channel_midline", "break_micro_swing_low",
    "break_channel_low", "any_structure_break", "new_high_before_first_break",
)
SEQ_METRICS = (
    "new_high_seq", "channel_midline_break_seq", "micro_swing_low_break_seq",
    "channel_low_break_seq", "first_structure_break_seq", "pre_break_peak_seq",
)
TIME_METRICS = (
    "new_high_time", "channel_midline_break_time", "micro_swing_low_break_time",
    "channel_low_break_time", "first_structure_break_time", "pre_break_peak_time",
)
FLOAT_METRICS = (
    "new_high_price", "time_to_new_high_seconds",
    "channel_midline_break_price", "time_to_channel_midline_break_seconds",
    "micro_swing_low_break_price", "time_to_micro_swing_low_break_seconds",
    "channel_low_break_price", "time_to_channel_low_break_seconds",
    "first_structure_break_price", "time_to_first_break_seconds",
    "pre_break_peak_price", "time_to_peak_after_trigger_seconds",
    "time_peak_to_structure_break_seconds",
    "adverse_extension_before_reversal_points", "adverse_extension_before_reversal_atr",
    "forward_slope_1s_step", "forward_slope_atr_1s_step", "forward_r2_1s",
)
OBJECT_METRICS = ("first_structure_break_references",)
REVERSAL_METRICS = BOOL_METRICS + SEQ_METRICS + TIME_METRICS + FLOAT_METRICS + OBJECT_METRICS


def _canon(v):
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, np.datetime64):
        return pd.Timestamp(v).isoformat()
    if isinstance(v, np.generic):
        v = v.item()
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v if isinstance(v, (bool, int, float, str)) else str(v)


def _validate_bars(frame: pd.DataFrame, timeframe: str, session: str) -> pd.DataFrame:
    req = {"bar_start_seq", "bar_end_seq", "bar_start", "low"}
    miss = req - set(frame.columns)
    if miss:
        raise ValueError(f"reversal reference bars missing columns: {sorted(miss)}")
    out = frame.reset_index(drop=True)
    start = pd.to_numeric(out.bar_start_seq, errors="raise").to_numpy(np.int64)
    end = pd.to_numeric(out.bar_end_seq, errors="raise").to_numpy(np.int64)
    if len(start) > 1 and np.any(np.diff(start) <= 0):
        raise ValueError("reversal reference bars must remain in strict physical order")
    if np.any(end < start):
        raise ValueError("reversal reference bar_end_seq precedes bar_start_seq")
    if len(end) > 1 and (np.any(np.diff(end) <= 0) or np.any(end[:-1] >= start[1:])):
        raise ValueError("reversal reference completed bars overlap or end seq is not strictly increasing")
    bt = pd.to_datetime(out.bar_start, errors="coerce", format="mixed")
    if bt.isna().any():
        raise ValueError("reversal reference bars contain invalid bar_start")
    ns = bt.to_numpy(dtype="datetime64[ns]").astype(np.int64)
    if len(ns) > 1 and np.any(np.diff(ns) < 0):
        raise ValueError("reversal reference bar_start moved backward")
    if "timeframe" in out and set(out.timeframe.astype(str).unique()) != {str(timeframe)}:
        raise ValueError("reversal reference timeframe drift")
    if "session" in out and set(out.session.astype(str).unique()) != {str(session)}:
        raise ValueError("reversal reference session drift")
    if pd.to_numeric(out.low, errors="coerce").isna().any():
        raise ValueError("reversal reference bars contain invalid low")
    return out


def _latest_pivot(bars: pd.DataFrame, i: int, radius: int, lookback: int):
    if radius < 1 or lookback < 2 * radius + 1:
        raise ValueError("invalid micro-swing reference parameters")
    lows = pd.to_numeric(bars.low, errors="raise").to_numpy(float)
    ws = max(0, i - lookback + 1)
    first = max(radius, ws + radius)
    last = i - radius
    for j in range(last, first - 1, -1):
        nbr = np.r_[lows[j-radius:j], lows[j+1:j+radius+1]]
        if len(nbr) == 2 * radius and np.isfinite(nbr).all() and np.isfinite(lows[j]) and lows[j] < nbr.min():
            return j
    return None


def build_reversal_reference_store(
    events: pd.DataFrame,
    bars_by_timeframe: Mapping[str, pd.DataFrame],
    *, pivot_radius: int = PIVOT_RADIUS,
    pivot_search_lookback_bars: int = PIVOT_SEARCH_LOOKBACK_BARS,
) -> pd.DataFrame:
    validate_probe_events(events)
    if events.session.astype(str).nunique() != 1:
        raise ValueError("reversal reference construction requires one session partition")
    miss = {"rolling_high", "rolling_low"} - set(events.columns)
    if miss:
        raise ValueError(f"reversal events missing columns: {sorted(miss)}")
    cache = {}
    rows = []
    for ev in events.itertuples(index=False):
        tf, sess = str(ev.timeframe), str(ev.session)
        if tf not in cache:
            if tf not in bars_by_timeframe:
                raise ValueError(f"missing completed bars for timeframe {tf!r}")
            cache[tf] = _validate_bars(bars_by_timeframe[tf], tf, sess)
        bars = cache[tf]
        end = pd.to_numeric(bars.bar_end_seq, errors="raise").to_numpy(np.int64)
        loc = np.flatnonzero(end == int(ev.trigger_seq))
        if len(loc) != 1:
            raise ValueError(f"event {ev.event_id}: trigger bar lookup returned {len(loc)} rows")
        i = int(loc[0])
        if int(bars.iloc[i].bar_start_seq) != int(ev.bar_start_seq):
            raise ValueError(f"event {ev.event_id}: trigger bar_start_seq mismatch")
        pivot = _latest_pivot(bars, i, pivot_radius, pivot_search_lookback_bars)
        high, low, trigger = float(ev.rolling_high), float(ev.rolling_low), float(ev.trigger_price)
        if not np.isfinite(high) or not np.isfinite(low) or high < low:
            raise ValueError(f"event {ev.event_id}: invalid frozen M4 channel")
        mid = (high + low) / 2.0
        available = pivot is not None
        micro = np.nan; bs = be = None; bt = pd.NaT
        if available:
            pr = bars.iloc[pivot]
            micro = float(pr.low); bs = int(pr.bar_start_seq); be = int(pr.bar_end_seq); bt = pd.Timestamp(pr.bar_start)
        rows.append({
            "reversal_reference_schema_version": REVERSAL_REFERENCE_SCHEMA_VERSION,
            "micro_swing_algorithm_version": MICRO_SWING_ALGORITHM_VERSION,
            "event_id": str(ev.event_id), "trigger_price": trigger,
            "channel_high_reference_level": high,
            "channel_midline_reference_level": mid,
            "channel_low_reference_level": low,
            "channel_midline_break_eligible": bool(trigger >= mid),
            "channel_low_break_eligible": bool(trigger >= low),
            "micro_swing_reference_available": bool(available),
            "micro_swing_break_eligible": bool(available and trigger >= micro),
            "micro_swing_low_reference_level": micro,
            "micro_swing_bar_start_seq": bs, "micro_swing_bar_end_seq": be,
            "micro_swing_bar_start_time": bt,
        })
    store = pd.DataFrame(rows)
    manifest = build_reversal_reference_manifest(events, store)
    store.insert(2, "reversal_reference_manifest_hash", manifest["reversal_reference_manifest_hash"])
    return store


def _align(events: pd.DataFrame, references: pd.DataFrame) -> pd.DataFrame:
    validate_probe_events(events)
    req = {"reversal_reference_schema_version", "micro_swing_algorithm_version", *REFERENCE_HASH_COLUMNS}
    miss = req - set(references.columns)
    if miss:
        raise ValueError(f"reversal reference store missing columns: {sorted(miss)}")
    if references.event_id.isna().any() or not references.event_id.is_unique:
        raise ValueError("reversal reference event_id must be non-null and unique")
    ids = events.event_id.astype(str).tolist()
    if set(ids) != set(references.event_id.astype(str)):
        raise ValueError("reversal reference event_id set mismatch")
    ref = references.set_index("event_id", drop=False).loc[ids].reset_index(drop=True)
    if set(ref.reversal_reference_schema_version.astype(str).unique()) != {REVERSAL_REFERENCE_SCHEMA_VERSION}:
        raise ValueError("reversal reference schema drift")
    if set(ref.micro_swing_algorithm_version.astype(str).unique()) != {MICRO_SWING_ALGORITHM_VERSION}:
        raise ValueError("micro-swing algorithm drift")
    trigger = pd.to_numeric(events.trigger_price).to_numpy(float)
    rh = pd.to_numeric(events.rolling_high).to_numpy(float)
    rl = pd.to_numeric(events.rolling_low).to_numpy(float)
    for col, exp in {
        "trigger_price": trigger,
        "channel_high_reference_level": rh,
        "channel_midline_reference_level": (rh + rl) / 2.0,
        "channel_low_reference_level": rl,
    }.items():
        got = pd.to_numeric(ref[col], errors="raise").to_numpy(float)
        if not np.array_equal(got, exp, equal_nan=True):
            raise ValueError(f"reversal reference {col} drift from frozen event source")
    if not np.array_equal(ref.channel_midline_break_eligible.astype(bool), trigger >= (rh + rl)/2.0):
        raise ValueError("channel_midline_break_eligible drift")
    if not np.array_equal(ref.channel_low_break_eligible.astype(bool), trigger >= rl):
        raise ValueError("channel_low_break_eligible drift")
    avail = ref.micro_swing_reference_available.astype(bool).to_numpy()
    micro = pd.to_numeric(ref.micro_swing_low_reference_level, errors="coerce").to_numpy(float)
    elig = ref.micro_swing_break_eligible.astype(bool).to_numpy()
    if not np.array_equal(elig, avail & np.isfinite(micro) & (trigger >= micro)):
        raise ValueError("micro_swing_break_eligible drift")
    if np.any((~avail) & np.isfinite(micro)):
        raise ValueError("unavailable micro-swing reference must not have a level")
    ms = pd.to_numeric(ref.micro_swing_bar_start_seq, errors="coerce").to_numpy(float)
    me = pd.to_numeric(ref.micro_swing_bar_end_seq, errors="coerce").to_numpy(float)
    mt = pd.to_datetime(ref.micro_swing_bar_start_time, errors="coerce", format="mixed")
    ts = pd.to_numeric(events.trigger_seq).to_numpy(np.int64)
    tt = pd.to_datetime(events.trigger_time, errors="raise", format="mixed")
    if np.any(avail & (~np.isfinite(ms) | ~np.isfinite(me))):
        raise ValueError("available micro-swing reference requires source seq coordinates")
    if np.any(avail & (ms > me)) or np.any(avail & (me > ts)):
        raise ValueError("micro-swing source coordinates are not causal at trigger_seq")
    if bool((avail & mt.isna().to_numpy()).any()) or bool((avail & (mt > tt).to_numpy()).any()):
        raise ValueError("micro-swing source time is not causal at trigger_time")
    if np.any((~avail) & (np.isfinite(ms) | np.isfinite(me))) or bool(((~avail) & mt.notna().to_numpy()).any()):
        raise ValueError("unavailable micro-swing reference must not have source coordinates")
    return ref


def build_reversal_reference_manifest(events: pd.DataFrame, references: pd.DataFrame) -> dict:
    ref = _align(events, references)
    h = sha256()
    h.update((REVERSAL_REFERENCE_SCHEMA_VERSION + "\n").encode())
    h.update((MICRO_SWING_ALGORITHM_VERSION + "\n").encode())
    h.update((json.dumps(REFERENCE_PARAMETERS, sort_keys=True, separators=(",", ":")) + "\n").encode())
    h.update(("|".join(REFERENCE_HASH_COLUMNS) + "\n").encode())
    for row in ref.loc[:, REFERENCE_HASH_COLUMNS].itertuples(index=False, name=None):
        h.update(json.dumps([_canon(v) for v in row], ensure_ascii=False, separators=(",", ":")).encode()); h.update(b"\n")
    avail = ref.micro_swing_reference_available.astype(bool)
    elig = ref.micro_swing_break_eligible.astype(bool)
    return {
        "schema_version": REVERSAL_REFERENCE_SCHEMA_VERSION,
        "algorithm_version": MICRO_SWING_ALGORITHM_VERSION,
        "parameters": REFERENCE_PARAMETERS,
        "event_count": int(len(ref)),
        "channel_midline_break_eligible": int(ref.channel_midline_break_eligible.astype(bool).sum()),
        "channel_low_break_eligible": int(ref.channel_low_break_eligible.astype(bool).sum()),
        "micro_swing_reference_available": int(avail.sum()),
        "micro_swing_reference_missing": int((~avail).sum()),
        "micro_swing_break_eligible": int(elig.sum()),
        "micro_swing_already_broken_at_trigger": int((avail & ~elig).sum()),
        "hash_columns": list(REFERENCE_HASH_COLUMNS),
        "reversal_reference_manifest_hash": h.hexdigest(),
    }


def validate_reversal_reference_store(events: pd.DataFrame, references: pd.DataFrame) -> dict:
    manifest = build_reversal_reference_manifest(events, references)
    if "reversal_reference_manifest_hash" in references:
        obs = set(references.reversal_reference_manifest_hash.dropna().astype(str).unique())
        if obs != {manifest["reversal_reference_manifest_hash"]}:
            raise ValueError("reversal reference manifest hash drift")
    return manifest


def _empty():
    out = {m: None for m in BOOL_METRICS + SEQ_METRICS + OBJECT_METRICS}
    out.update({m: pd.NaT for m in TIME_METRICS})
    out.update({m: np.nan for m in FLOAT_METRICS})
    return out


def _ols(values):
    y = np.asarray(values, float)
    if len(y) < 2 or not np.isfinite(y).all():
        return np.nan, np.nan
    x = np.arange(len(y), dtype=float); xc = x-x.mean(); yc = y-y.mean(); ssx = float(xc@xc)
    if ssx == 0:
        return np.nan, np.nan
    slope = float((xc@yc)/ssx); fit = y.mean()+slope*xc; sst = float(yc@yc); ssr = float(((y-fit)**2).sum())
    return slope, (1.0 if sst == 0 and ssr == 0 else (np.nan if sst == 0 else 1.0-ssr/sst))


def _measure(ev, ref, seq, ns, price):
    if len(price) == 0:
        return _empty()
    out = _empty(); trigger_time = pd.Timestamp(ev.trigger_time); tp = float(ev.trigger_price); atr = float(ev.atr)
    sec = ns // 1_000_000_000; last = np.r_[sec[1:] != sec[:-1], True]; closes = price[last]
    slope, r2 = _ols(closes); out["forward_slope_1s_step"] = slope; out["forward_slope_atr_1s_step"] = slope/atr if np.isfinite(slope) else np.nan; out["forward_r2_1s"] = r2
    nh = np.flatnonzero(price > float(ref.channel_high_reference_level)); new_high = None
    if len(nh):
        k = int(nh[0]); new_high = (int(seq[k]), pd.Timestamp(ns[k], unit="ns"), float(price[k]))
        out.update(made_new_high=True, new_high_seq=new_high[0], new_high_time=new_high[1], new_high_price=new_high[2], time_to_new_high_seconds=float((new_high[1]-trigger_time).total_seconds()))
    else:
        out["made_new_high"] = False
    breaks = []
    for name, level, eligible in (
        ("channel_midline", ref.channel_midline_reference_level, bool(ref.channel_midline_break_eligible)),
        ("micro_swing_low", ref.micro_swing_low_reference_level, bool(ref.micro_swing_break_eligible)),
        ("channel_low", ref.channel_low_reference_level, bool(ref.channel_low_break_eligible)),
    ):
        if not eligible or pd.isna(level):
            continue
        hit = np.flatnonzero(price < float(level))
        if not len(hit):
            out[f"break_{name}"] = False; continue
        k = int(hit[0]); bs = int(seq[k]); bt = pd.Timestamp(ns[k], unit="ns"); bp = float(price[k])
        breaks.append((name, bs, bt, bp)); out[f"break_{name}"] = True
        out[f"{name}_break_seq"] = bs; out[f"{name}_break_time"] = bt; out[f"{name}_break_price"] = bp; out[f"time_to_{name}_break_seconds"] = float((bt-trigger_time).total_seconds())
    if not breaks:
        out["any_structure_break"] = False
        return out
    out["any_structure_break"] = True
    first_seq = min(x[1] for x in breaks); same = [x for x in breaks if x[1] == first_seq]
    bs, bt, bp = first_seq, same[0][2], same[0][3]
    out["first_structure_break_references"] = "|".join(x[0] for x in same)
    out["first_structure_break_seq"] = bs; out["first_structure_break_time"] = bt; out["first_structure_break_price"] = bp; out["time_to_first_break_seconds"] = float((bt-trigger_time).total_seconds())
    before = seq < bs
    if before.any() and float(price[before].max()) > tp:
        p = price[before]; mx = float(p.max()); k = int(np.flatnonzero(p == mx)[0]); ps = int(seq[before][k]); pt = pd.Timestamp(ns[before][k], unit="ns")
    else:
        mx, ps, pt = tp, int(ev.trigger_seq), trigger_time
    adverse = max(mx-tp, 0.0)
    out["pre_break_peak_seq"] = ps; out["pre_break_peak_time"] = pt; out["pre_break_peak_price"] = mx
    out["time_to_peak_after_trigger_seconds"] = float((pt-trigger_time).total_seconds()); out["time_peak_to_structure_break_seconds"] = float((bt-pt).total_seconds())
    out["adverse_extension_before_reversal_points"] = adverse; out["adverse_extension_before_reversal_atr"] = adverse/atr
    out["new_high_before_first_break"] = bool(new_high is not None and new_high[0] < bs)
    return out


def compute_reversal_outcomes(events, ticks, references, *, contract: str, session: str, horizons: Iterable[str] = FROZEN_HORIZONS):
    validate_probe_events(events); manifest = validate_reversal_reference_store(events, references); ref = _align(events, references)
    hs = tuple(horizons)
    if len(set(hs)) != len(hs) or any(h not in FROZEN_HORIZONS for h in hs):
        raise ValueError("invalid/duplicate horizons")
    base = compute_balance_outcomes(events, ticks, contract=str(contract), session=session, horizons=hs).reset_index(drop=True)
    seq = pd.to_numeric(ticks._seq, errors="raise").to_numpy(np.int64)
    ns = pd.to_datetime(ticks.datetime, errors="raise", format="mixed").to_numpy(dtype="datetime64[ns]").astype(np.int64)
    price = pd.to_numeric(ticks.price, errors="raise").to_numpy(float)
    n = len(events); nat = np.datetime64("NaT", "ns")
    block = {
        "reversal_schema_version": np.full(n, REVERSAL_SCHEMA_VERSION, object),
        "reversal_reference_schema_version": np.full(n, REVERSAL_REFERENCE_SCHEMA_VERSION, object),
        "reversal_reference_manifest_hash": np.full(n, manifest["reversal_reference_manifest_hash"], object),
        "micro_swing_algorithm_version": np.full(n, MICRO_SWING_ALGORITHM_VERSION, object),
    }
    for c in ("channel_high_reference_level", "channel_midline_reference_level", "channel_low_reference_level", "micro_swing_low_reference_level"):
        block[c] = pd.to_numeric(ref[c], errors="coerce").to_numpy(float)
    for c in ("channel_midline_break_eligible", "channel_low_break_eligible", "micro_swing_reference_available", "micro_swing_break_eligible"):
        block[c] = ref[c].astype(bool).to_numpy()
    for c in ("micro_swing_bar_start_seq", "micro_swing_bar_end_seq"):
        block[c] = pd.array(ref[c], dtype="Int64")
    block["micro_swing_bar_start_time"] = pd.to_datetime(ref.micro_swing_bar_start_time, errors="coerce")
    for h in hs:
        p = "h_"+h
        for m in BOOL_METRICS + OBJECT_METRICS: block[p+"_"+m] = np.full(n, None, object)
        for m in SEQ_METRICS: block[p+"_"+m] = np.full(n, -1, np.int64)
        for m in TIME_METRICS: block[p+"_"+m] = np.full(n, nat, dtype="datetime64[ns]")
        for m in FLOAT_METRICS: block[p+"_"+m] = np.full(n, np.nan, float)
    evs = events.reset_index(drop=True)
    for i, ev in evs.iterrows():
        rr = ref.iloc[i]
        for h in hs:
            p = "h_"+h; count = int(base.at[i, p+"_future_tick_count"])
            if count == 0: continue
            a = int(base.at[i, p+"_window_start_seq"]); b = int(base.at[i, p+"_window_end_seq"])
            left = int(np.searchsorted(seq, a, side="left")); right = int(np.searchsorted(seq, b, side="right"))
            if right-left != count or left >= len(seq) or seq[left] != a or seq[right-1] != b:
                raise AssertionError(f"Dev4 window coordinate mismatch for event={ev.event_id}, horizon={h}")
            measured = _measure(ev, rr, seq[left:right], ns[left:right], price[left:right])
            for m, v in measured.items():
                key = p+"_"+m
                if m in SEQ_METRICS: block[key][i] = -1 if v is None or pd.isna(v) else int(v)
                elif m in TIME_METRICS:
                    if v is not None and not pd.isna(v): block[key][i] = np.datetime64(pd.Timestamp(v), "ns")
                else: block[key][i] = v
    out = pd.concat([base, pd.DataFrame(block)], axis=1)
    for h in hs:
        p = "h_"+h
        for m in BOOL_METRICS: out[p+"_"+m] = pd.array(out[p+"_"+m].tolist(), dtype="boolean")
        for m in SEQ_METRICS:
            arr = out[p+"_"+m].to_numpy(np.int64); out[p+"_"+m] = pd.array(np.where(arr < 0, None, arr), dtype="Int64")
    if not validate_probe_outcomes(events, out).all_pass:
        raise AssertionError("Dev4 outcomes violated M4→M5 event contract")
    return out


__all__ = [
    "REVERSAL_SCHEMA_VERSION", "REVERSAL_REFERENCE_SCHEMA_VERSION",
    "MICRO_SWING_ALGORITHM_VERSION", "PIVOT_RADIUS", "PIVOT_SEARCH_LOOKBACK_BARS",
    "REFERENCE_PARAMETERS", "REVERSAL_METRICS", "OBJECT_METRICS",
    "build_reversal_reference_store", "build_reversal_reference_manifest",
    "validate_reversal_reference_store", "compute_reversal_outcomes",
]
