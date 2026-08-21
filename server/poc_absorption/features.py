"""Continuous causal features for the POC absorption/reversal research branch.

This module deliberately stores continuous components rather than a tuned signal.
All predictor features are computed from completed/current causal state. Future
price movement belongs in the M5 outcome engine and is never used here.

Partitioning rule
-----------------
Callers should partition completed bars/ticks by contract + session and break a
partition at explicit source-data gaps. Consecutive valid trading days for the
same contract/session may remain continuous so longer lookbacks (notably 24 bars
on 15m) have usable history. Reset on a contract roll or DATA_GAP_BLACKOUT.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict

import numpy as np
import pandas as pd

FEATURE_SCHEMA_VERSION = "POC_CONTINUOUS_FEATURES_V1"
TREND_LOOKBACKS = (6, 8, 12, 16, 24)
POC_VELOCITY_LOOKBACKS = (2, 3, 4, 6)
STALL_LOOKBACKS = (3, 6, 12, 24)
HIGH_ZONE_Q = (0.70, 0.80, 0.90)
STRUCTURAL_HIGH_ZONE_ATR = (0.25, 0.50, 1.00)


def _bars_frame(bars) -> pd.DataFrame:
    if isinstance(bars, pd.DataFrame):
        frame = bars.copy()
    else:
        rows = [asdict(row) if hasattr(row, "__dataclass_fields__") else dict(row) for row in bars]
        frame = pd.DataFrame(rows)
    required = {
        "timeframe",
        "session",
        "bar_start_seq",
        "bar_end_seq",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "poc",
        "vah",
        "val",
        "profile_width",
        "price_range",
        "atr_n",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Missing completed-bar fields: {missing}")
    if len(frame) > 1 and np.any(np.diff(frame["bar_start_seq"].to_numpy(dtype=np.int64)) <= 0):
        raise ValueError("bar_start_seq must be strictly increasing; features never sort input")
    return frame.reset_index(drop=True)


def _safe_div(numerator, denominator):
    n = pd.Series(numerator, dtype=float)
    d = pd.Series(denominator, dtype=float)
    return n.div(d.where(d.abs() > 0))


def _rolling_ols(series: pd.Series, lookback: int) -> tuple[pd.Series, pd.Series]:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    slopes = np.full(len(values), np.nan, dtype=float)
    r2 = np.full(len(values), np.nan, dtype=float)
    x = np.arange(lookback, dtype=float)
    x_centered = x - x.mean()
    x_ss = float(np.dot(x_centered, x_centered))
    for end in range(lookback - 1, len(values)):
        y = values[end - lookback + 1 : end + 1]
        if not np.isfinite(y).all():
            continue
        yc = y - y.mean()
        slope = float(np.dot(x_centered, yc) / x_ss)
        denom = float(np.dot(yc, yc))
        slopes[end] = slope
        if denom == 0:
            r2[end] = 1.0
        else:
            fitted = slope * x_centered
            residual = yc - fitted
            r2[end] = max(0.0, min(1.0, 1.0 - float(np.dot(residual, residual)) / denom))
    return pd.Series(slopes, index=series.index), pd.Series(r2, index=series.index)


def _rolling_count(mask: pd.Series, lookback: int) -> pd.Series:
    numeric = mask.astype("Float64")
    return numeric.rolling(lookback, min_periods=lookback).sum().astype(float)


def _bars_since_rolling_high(series: pd.Series, lookback: int) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(lookback - 1, len(values)):
        window = values[i - lookback + 1 : i + 1]
        if not np.isfinite(window).all():
            continue
        maximum = np.max(window)
        latest = np.flatnonzero(window == maximum)[-1]
        out[i] = float((lookback - 1) - latest)
    return pd.Series(out, index=series.index)


def _rolling_alternation(series: pd.Series, lookback: int) -> pd.Series:
    diff = pd.to_numeric(series, errors="coerce").diff()
    signs = np.sign(diff)
    out = np.full(len(series), np.nan, dtype=float)
    for i in range(lookback - 1, len(series)):
        window = signs.iloc[i - lookback + 2 : i + 1].to_numpy(dtype=float)
        if len(window) != lookback - 1 or not np.isfinite(window).all():
            continue
        nonzero = window[window != 0]
        if len(nonzero) <= 1:
            out[i] = 0.0
        else:
            out[i] = float(np.mean(nonzero[1:] != nonzero[:-1]))
    return pd.Series(out, index=series.index)


def compute_bar_features(bars) -> pd.DataFrame:
    """Attach causal trend/channel/POC-migration features to completed bars."""
    frame = _bars_frame(bars)
    derived: dict[str, pd.Series] = {}
    poc = pd.to_numeric(frame["poc"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    atr = pd.to_numeric(frame["atr_n"], errors="coerce")
    bar_range = pd.to_numeric(frame["price_range"], errors="coerce")
    profile_width = pd.to_numeric(frame["profile_width"], errors="coerce")

    derived["feature_schema_version"] = pd.Series(FEATURE_SCHEMA_VERSION, index=frame.index)
    derived["poc_delta_1"] = poc.diff()
    derived["price_delta_1"] = close.diff()
    derived["high_delta_1"] = high.diff()
    derived["poc_down_price_high_1"] = ((derived["high_delta_1"] >= 0) & (derived["poc_delta_1"] < 0)).astype(float)
    derived["poc_delta_1_atr"] = _safe_div(derived["poc_delta_1"], atr)
    derived["poc_delta_1_bar_range"] = _safe_div(derived["poc_delta_1"], bar_range)
    derived["poc_delta_1_profile_width"] = _safe_div(derived["poc_delta_1"], profile_width)
    derived["price_delta_1_atr"] = _safe_div(derived["price_delta_1"], atr)

    for k in POC_VELOCITY_LOOKBACKS:
        velocity = (poc - poc.shift(k)) / float(k)
        derived[f"poc_velocity_{k}"] = velocity
        derived[f"poc_velocity_atr_{k}"] = _safe_div(velocity, atr)
    derived["poc_accel_2_6"] = derived["poc_velocity_2"] - derived["poc_velocity_6"]

    for lookback in TREND_LOOKBACKS:
        price_slope, price_r2 = _rolling_ols(close, lookback)
        poc_slope, _ = _rolling_ols(poc, lookback)
        rolling_high = high.rolling(lookback, min_periods=lookback).max()
        rolling_low = low.rolling(lookback, min_periods=lookback).min()
        channel_width = rolling_high - rolling_low
        new_price_high = high >= rolling_high
        rolling_poc_high = poc.rolling(lookback, min_periods=lookback).max()
        new_poc_high = poc >= rolling_poc_high
        residual_std = pd.Series(np.nan, index=frame.index, dtype=float)
        swing_amp = pd.Series(np.nan, index=frame.index, dtype=float)
        for i in range(lookback - 1, len(frame)):
            y = close.iloc[i - lookback + 1 : i + 1].to_numpy(dtype=float)
            if not np.isfinite(y).all():
                continue
            x = np.arange(lookback, dtype=float)
            fit = np.polyval(np.polyfit(x, y, 1), x)
            residual_std.iloc[i] = float(np.std(y - fit, ddof=0))
            swing_amp.iloc[i] = float((np.max(y) - np.min(y)))

        derived[f"ols_slope_close_{lookback}"] = price_slope
        derived[f"ols_r2_close_{lookback}"] = price_r2
        derived[f"slope_atr_{lookback}"] = _safe_div(price_slope, atr)
        derived[f"poc_slope_{lookback}"] = poc_slope
        derived[f"divergence_slope_{lookback}"] = price_slope - poc_slope
        derived[f"higher_high_ratio_{lookback}"] = _rolling_count(high.diff() > 0, lookback - 1) / float(lookback - 1)
        derived[f"higher_low_ratio_{lookback}"] = _rolling_count(low.diff() > 0, lookback - 1) / float(lookback - 1)
        derived[f"rolling_high_{lookback}"] = rolling_high
        derived[f"rolling_low_{lookback}"] = rolling_low
        derived[f"channel_width_{lookback}"] = channel_width
        derived[f"channel_width_atr_{lookback}"] = _safe_div(channel_width, atr)
        derived[f"close_location_in_window_{lookback}"] = _safe_div(close - rolling_low, channel_width)
        derived[f"rolling_high_distance_atr_{lookback}"] = _safe_div(rolling_high - close, atr)
        derived[f"rolling_low_distance_atr_{lookback}"] = _safe_div(close - rolling_low, atr)
        derived[f"residual_std_{lookback}"] = residual_std
        derived[f"residual_std_atr_{lookback}"] = _safe_div(residual_std, atr)
        derived[f"swing_amplitude_atr_{lookback}"] = _safe_div(swing_amp, atr)
        derived[f"alternation_rate_{lookback}"] = _rolling_alternation(close, lookback)
        derived[f"poc_price_corr_{lookback}"] = close.rolling(lookback, min_periods=lookback).corr(poc)
        derived[f"new_price_high_{lookback}"] = new_price_high.astype(float).where(rolling_high.notna())
        derived[f"new_poc_high_{lookback}"] = new_poc_high.astype(float).where(rolling_poc_high.notna())
        derived[f"new_price_high_without_poc_high_{lookback}"] = (
            new_price_high & ~new_poc_high
        ).astype(float).where(rolling_high.notna() & rolling_poc_high.notna())

    for lookback in STALL_LOOKBACKS:
        derived[f"bars_since_poc_high_{lookback}"] = _bars_since_rolling_high(poc, lookback)
        nonadvance = poc.diff() <= 0
        lower = poc.diff() < 0
        derived[f"poc_nonadvance_count_{lookback}"] = _rolling_count(nonadvance, lookback - 1)
        derived[f"poc_lower_count_{lookback}"] = _rolling_count(lower, lookback - 1)

    return pd.concat([frame, pd.DataFrame(derived, index=frame.index)], axis=1)


def _validate_ticks(ticks: pd.DataFrame) -> pd.DataFrame:
    required = {"_seq", "datetime", "price", "volume", "side"}
    missing = sorted(required.difference(ticks.columns))
    if missing:
        raise ValueError(f"Missing tick fields: {missing}")
    out = ticks.copy()
    seq = out["_seq"].to_numpy(dtype=np.int64)
    if len(seq) > 1 and np.any(np.diff(seq) <= 0):
        raise ValueError("Tick _seq must be strictly increasing; pressure features never sort")
    side = pd.to_numeric(out["side"], errors="coerce")
    if not side.dropna().isin([-1, 0, 1]).all():
        raise ValueError("side must stay the source tick-direction proxy {-1,0,1}")
    return out


def compute_pressure_features(
    ticks: pd.DataFrame,
    bars,
    *,
    high_zone_q: Sequence[float] = HIGH_ZONE_Q,
) -> pd.DataFrame:
    """Compute bar-internal tick-direction pressure/effort-result components."""
    ticks = _validate_ticks(ticks)
    bars_frame = _bars_frame(bars)
    result: list[dict] = []
    seq_values = ticks["_seq"].to_numpy(dtype=np.int64)
    for bar in bars_frame.itertuples(index=False):
        left = int(np.searchsorted(seq_values, int(bar.bar_start_seq), side="left"))
        right = int(np.searchsorted(seq_values, int(bar.bar_end_seq), side="right"))
        g = ticks.iloc[left:right]
        if g.empty or int(g["_seq"].iloc[0]) != int(bar.bar_start_seq) or int(g["_seq"].iloc[-1]) != int(bar.bar_end_seq):
            raise ValueError("Bar/tick physical seq boundaries do not match exactly")
        price = pd.to_numeric(g["price"], errors="coerce").to_numpy(dtype=float)
        volume = pd.to_numeric(g["volume"], errors="coerce").to_numpy(dtype=float)
        side = pd.to_numeric(g["side"], errors="coerce").to_numpy(dtype=int)
        total_volume = float(volume.sum())
        positive_mask = side > 0
        negative_mask = side < 0
        neutral_mask = side == 0
        positive_volume = float(volume[positive_mask].sum())
        negative_volume = float(volume[negative_mask].sum())
        neutral_volume = float(volume[neutral_mask].sum())
        signed_volume = float(np.sum(volume * side))
        positive_ticks = int(positive_mask.sum())
        signed_ticks = int(side.sum())
        up_extension = float(bar.high - bar.open)
        net_advance = float(bar.close - bar.open)
        bar_range = float(bar.high - bar.low)
        row = {
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "timeframe": bar.timeframe,
            "session": bar.session,
            "bar_start_seq": int(bar.bar_start_seq),
            "bar_end_seq": int(bar.bar_end_seq),
            "tdp_total_volume": total_volume,
            "tdp_signed_volume": signed_volume,
            "tdp_positive_volume": positive_volume,
            "tdp_negative_volume": negative_volume,
            "tdp_neutral_volume": neutral_volume,
            "tdp_ratio": signed_volume / total_volume if total_volume > 0 else np.nan,
            "tdp_positive_share": positive_volume / total_volume if total_volume > 0 else np.nan,
            "tdp_positive_tick_share": positive_ticks / len(g) if len(g) else np.nan,
            "tdp_signed_tick_ratio": signed_ticks / len(g) if len(g) else np.nan,
            "bar_internal_up_extension": up_extension,
            "bar_internal_net_advance": net_advance,
            "close_location_in_bar": 0.5 if bar_range == 0 else float((bar.close - bar.low) / bar_range),
            "impact_per_1000_positive_volume": (up_extension * 1000.0 / positive_volume) if positive_volume > 0 else np.nan,
            "impact_per_positive_tick": (up_extension / positive_ticks) if positive_ticks > 0 else np.nan,
            "net_advance_per_1000_positive_volume": (net_advance * 1000.0 / positive_volume) if positive_volume > 0 else np.nan,
        }
        for q in high_zone_q:
            if not 0 <= q <= 1:
                raise ValueError(f"Invalid high-zone fraction: {q}")
            suffix = f"q{int(round(q * 100)):02d}"
            threshold = float(bar.low + q * (bar.high - bar.low))
            zone = price >= threshold
            zone_volume = float(volume[zone].sum())
            zone_positive = float(volume[zone & positive_mask].sum())
            zone_negative = float(volume[zone & negative_mask].sum())
            zone_neutral = float(volume[zone & neutral_mask].sum())
            zone_signed = float(np.sum(volume[zone] * side[zone]))
            row.update(
                {
                    f"high_zone_threshold_{suffix}": threshold,
                    f"high_zone_volume_{suffix}": zone_volume,
                    f"high_zone_positive_volume_{suffix}": zone_positive,
                    f"high_zone_negative_volume_{suffix}": zone_negative,
                    f"high_zone_neutral_volume_{suffix}": zone_neutral,
                    f"high_zone_tdp_{suffix}": zone_signed / zone_volume if zone_volume > 0 else np.nan,
                    f"high_zone_volume_share_{suffix}": zone_volume / total_volume if total_volume > 0 else np.nan,
                    f"high_zone_positive_share_{suffix}": zone_positive / zone_volume if zone_volume > 0 else np.nan,
                }
            )
        result.append(row)
    return pd.DataFrame(result)


def compute_structural_high_zone_features(
    ticks: pd.DataFrame,
    bars,
    *,
    lookback: int = 24,
    atr_multipliers: Sequence[float] = STRUCTURAL_HIGH_ZONE_ATR,
) -> pd.DataFrame:
    """Alternative structural high-zone pressure: price >= rolling high - x*ATR."""
    ticks = _validate_ticks(ticks)
    bar_features = compute_bar_features(bars)
    seq_values = ticks["_seq"].to_numpy(dtype=np.int64)
    rolling_col = f"rolling_high_{lookback}"
    if rolling_col not in bar_features:
        raise ValueError(f"Unsupported structural lookback: {lookback}")
    rows: list[dict] = []
    for bar in bar_features.itertuples(index=False):
        row = {
            "timeframe": bar.timeframe,
            "session": bar.session,
            "bar_start_seq": int(bar.bar_start_seq),
            "bar_end_seq": int(bar.bar_end_seq),
        }
        rolling_high = getattr(bar, rolling_col)
        atr = float(bar.atr_n) if pd.notna(bar.atr_n) else np.nan
        left = int(np.searchsorted(seq_values, int(bar.bar_start_seq), side="left"))
        right = int(np.searchsorted(seq_values, int(bar.bar_end_seq), side="right"))
        g = ticks.iloc[left:right]
        price = pd.to_numeric(g["price"], errors="coerce").to_numpy(dtype=float)
        volume = pd.to_numeric(g["volume"], errors="coerce").to_numpy(dtype=float)
        side = pd.to_numeric(g["side"], errors="coerce").to_numpy(dtype=int)
        total_volume = float(volume.sum())
        for multiplier in atr_multipliers:
            suffix = f"atr{str(multiplier).replace('.', 'p')}"
            if pd.isna(rolling_high) or not np.isfinite(atr):
                row[f"struct_high_threshold_{suffix}"] = np.nan
                row[f"struct_high_volume_{suffix}"] = np.nan
                row[f"struct_high_positive_volume_{suffix}"] = np.nan
                row[f"struct_high_negative_volume_{suffix}"] = np.nan
                row[f"struct_high_tdp_{suffix}"] = np.nan
                row[f"struct_high_volume_share_{suffix}"] = np.nan
                continue
            threshold = float(rolling_high - float(multiplier) * atr)
            zone = price >= threshold
            zone_volume = float(volume[zone].sum())
            zone_positive = float(volume[zone & (side > 0)].sum())
            zone_negative = float(volume[zone & (side < 0)].sum())
            zone_signed = float(np.sum(volume[zone] * side[zone]))
            row[f"struct_high_threshold_{suffix}"] = threshold
            row[f"struct_high_volume_{suffix}"] = zone_volume
            row[f"struct_high_positive_volume_{suffix}"] = zone_positive
            row[f"struct_high_negative_volume_{suffix}"] = zone_negative
            row[f"struct_high_tdp_{suffix}"] = zone_signed / zone_volume if zone_volume > 0 else np.nan
            row[f"struct_high_volume_share_{suffix}"] = zone_volume / total_volume if total_volume > 0 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _rolling_z(series: pd.Series, lookback: int = 24) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    mean = x.rolling(lookback, min_periods=lookback).mean()
    std = x.rolling(lookback, min_periods=lookback).std(ddof=0)
    return (x - mean) / std.where(std > 0)


def attach_pressure_features(
    bar_features: pd.DataFrame,
    pressure_features: pd.DataFrame,
) -> pd.DataFrame:
    """Join pressure to bars by exact physical boundaries and add causal ranks/z-scores."""
    keys = ["timeframe", "session", "bar_start_seq", "bar_end_seq"]
    if pressure_features.duplicated(keys).any():
        raise ValueError("Duplicate pressure rows for exact bar boundaries")
    merged = bar_features.merge(pressure_features, on=keys, how="left", validate="one_to_one", suffixes=("", "_pressure"))
    if merged["tdp_total_volume"].isna().any():
        raise ValueError("Pressure features missing for one or more completed bars")
    derived: dict[str, pd.Series] = {
        "bar_internal_up_extension_atr": _safe_div(merged["bar_internal_up_extension"], merged["atr_n"]),
        "bar_internal_net_advance_atr": _safe_div(merged["bar_internal_net_advance"], merged["atr_n"]),
    }
    for column in (
        "tdp_positive_volume",
        "tdp_ratio",
        "high_zone_positive_volume_q80",
        "high_zone_tdp_q80",
        "impact_per_1000_positive_volume",
    ):
        if column in merged:
            derived[f"{column}_z24"] = _rolling_z(merged[column], 24)
    return pd.concat([merged, pd.DataFrame(derived, index=merged.index)], axis=1)
