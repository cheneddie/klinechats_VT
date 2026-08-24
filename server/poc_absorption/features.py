"""Continuous causal features for the POC absorption / reversal study.

This module intentionally emits components, not a tuned composite signal. All
rolling calculations are backward-looking and use completed bars only. Tick-side
fields are named TDP (tick-direction proxy) to preserve the evidence boundary.
"""
from __future__ import annotations

from dataclasses import asdict
from math import sqrt
from typing import Iterable, Literal, Sequence

import numpy as np
import pandas as pd

from .bars import BAR_RESOLUTIONS, CompletedBar, _bucket_start, _to_timestamp

FEATURE_SCHEMA_VERSION = "POC_CONTINUOUS_FEATURES_V1"
TREND_LOOKBACKS = (6, 8, 12, 16, 24)
POC_VELOCITY_LOOKBACKS = (2, 3, 4, 6)
STALL_LOOKBACKS = (3, 6, 12, 24)
HIGH_ZONE_Q = (0.70, 0.80, 0.90)


def bars_to_frame(bars: Sequence[CompletedBar] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(bars, pd.DataFrame):
        frame = bars.copy()
    else:
        frame = pd.DataFrame([asdict(bar) for bar in bars])
    required = {
        "bar_start_seq", "bar_end_seq", "open", "high", "low", "close",
        "volume", "poc", "vah", "val", "profile_width", "price_range", "atr_n",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing completed-bar columns: {sorted(missing)}")
    seq = frame["bar_start_seq"].to_numpy(dtype=np.int64)
    if len(seq) > 1 and np.any(np.diff(seq) <= 0):
        raise ValueError("Completed bars must be in strictly increasing physical order")
    return frame.reset_index(drop=True)


def _rolling_ols(values: np.ndarray, lookback: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(values)
    slope = np.full(n, np.nan, dtype=float)
    r2 = np.full(n, np.nan, dtype=float)
    x = np.arange(lookback, dtype=float)
    x_centered = x - x.mean()
    x_ss = float(np.dot(x_centered, x_centered))
    for i in range(lookback - 1, n):
        y = values[i - lookback + 1 : i + 1]
        if not np.isfinite(y).all():
            continue
        yc = y - y.mean()
        beta = float(np.dot(x_centered, yc) / x_ss)
        fitted = y.mean() + beta * x_centered
        ss_tot = float(np.dot(yc, yc))
        ss_res = float(np.dot(y - fitted, y - fitted))
        slope[i] = beta
        r2[i] = 1.0 if ss_tot == 0 and ss_res == 0 else (np.nan if ss_tot == 0 else 1.0 - ss_res / ss_tot)
    return slope, r2


def _safe_div(num: pd.Series | np.ndarray, den: pd.Series | np.ndarray) -> np.ndarray:
    a = np.asarray(num, dtype=float)
    b = np.asarray(den, dtype=float)
    out = np.full(np.broadcast(a, b).shape, np.nan, dtype=float)
    np.divide(a, b, out=out, where=np.isfinite(b) & (b != 0))
    return out


def _rolling_ratio_of_positive(values: pd.Series, lookback: int) -> pd.Series:
    return values.gt(0).rolling(lookback - 1, min_periods=lookback - 1).mean()


def _rolling_count(values: pd.Series, lookback: int, predicate: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if predicate == "lt0":
        raw = numeric < 0
    elif predicate == "le0":
        raw = numeric <= 0
    else:
        raise ValueError(predicate)
    x = pd.Series(np.where(numeric.isna(), np.nan, raw.astype(float)), index=values.index)
    return x.rolling(lookback, min_periods=lookback).sum()


def _bars_since_rolling_high(values: pd.Series, lookback: int) -> pd.Series:
    arr = values.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    for i in range(lookback - 1, len(arr)):
        window = arr[i - lookback + 1 : i + 1]
        mx = np.nanmax(window)
        positions = np.flatnonzero(window == mx)
        if len(positions):
            out[i] = (lookback - 1) - int(positions[-1])
    return pd.Series(out, index=values.index)


def _alternation_rate(close: pd.Series, lookback: int) -> pd.Series:
    diff = np.sign(close.diff().to_numpy(dtype=float))
    out = np.full(len(diff), np.nan)
    for i in range(lookback - 1, len(diff)):
        signs = diff[i - lookback + 2 : i + 1]
        signs = signs[np.isfinite(signs) & (signs != 0)]
        if len(signs) < 2:
            out[i] = 0.0
        else:
            out[i] = float(np.mean(signs[1:] != signs[:-1]))
    return pd.Series(out, index=close.index)


def compute_bar_features(bars: Sequence[CompletedBar] | pd.DataFrame) -> pd.DataFrame:
    """Create backward-looking channel and POC features from completed bars.

    Callers should partition by contract + session and explicitly break the sequence
    at source-data blackouts. Consecutive valid trading days may remain in one
    partition, which is required for long lookbacks such as 24 x 15m bars.
    """
    base = bars_to_frame(bars)
    atr = pd.to_numeric(base["atr_n"], errors="coerce")
    close = pd.to_numeric(base["close"], errors="coerce")
    high = pd.to_numeric(base["high"], errors="coerce")
    low = pd.to_numeric(base["low"], errors="coerce")
    poc = pd.to_numeric(base["poc"], errors="coerce")
    poc_delta = poc.diff()
    price_delta = close.diff()
    high_delta = high.diff()
    feat: dict[str, object] = {
        "poc_delta_1": poc_delta,
        "price_delta_1": price_delta,
        "high_delta_1": high_delta,
        "poc_down_price_high_1": (high_delta >= 0) & (poc_delta < 0),
    }

    velocities: dict[int, pd.Series] = {}
    for k in POC_VELOCITY_LOOKBACKS:
        velocity = (poc - poc.shift(k)) / float(k)
        velocities[k] = velocity
        feat[f"poc_velocity_{k}"] = velocity
        feat[f"poc_velocity_atr_{k}"] = _safe_div(velocity, atr)
    feat["poc_accel_2_6"] = velocities[2] - velocities[6]

    for lookback in TREND_LOOKBACKS:
        close_slope, close_r2 = _rolling_ols(close.to_numpy(dtype=float), lookback)
        poc_slope, _ = _rolling_ols(poc.to_numpy(dtype=float), lookback)
        rolling_high = high.rolling(lookback, min_periods=lookback).max()
        rolling_low = low.rolling(lookback, min_periods=lookback).min()
        width = rolling_high - rolling_low
        residual_std = np.full(len(base), np.nan)
        for i in range(lookback - 1, len(base)):
            y = close.iloc[i - lookback + 1 : i + 1].to_numpy(dtype=float)
            if not np.isfinite(y).all():
                continue
            x = np.arange(lookback, dtype=float)
            beta, alpha = np.polyfit(x, y, 1)
            residual_std[i] = float(np.std(y - (alpha + beta * x), ddof=0))
        prior_price_high = high.shift(1).rolling(lookback, min_periods=lookback).max()
        prior_poc_high = poc.shift(1).rolling(lookback, min_periods=lookback).max()
        new_price_high = high >= prior_price_high
        new_poc_high = poc >= prior_poc_high
        feat.update({
            f"ols_slope_close_{lookback}": close_slope,
            f"ols_r2_close_{lookback}": close_r2,
            f"slope_atr_{lookback}": _safe_div(close_slope, atr),
            f"poc_slope_{lookback}": poc_slope,
            f"divergence_slope_{lookback}": close_slope - poc_slope,
            f"higher_high_ratio_{lookback}": _rolling_ratio_of_positive(high.diff(), lookback),
            f"higher_low_ratio_{lookback}": _rolling_ratio_of_positive(low.diff(), lookback),
            f"rolling_high_{lookback}": rolling_high,
            f"rolling_low_{lookback}": rolling_low,
            f"channel_width_{lookback}": width,
            f"channel_width_atr_{lookback}": _safe_div(width, atr),
            f"close_location_in_window_{lookback}": _safe_div(close - rolling_low, width),
            f"rolling_high_distance_atr_{lookback}": _safe_div(rolling_high - close, atr),
            f"rolling_low_distance_atr_{lookback}": _safe_div(close - rolling_low, atr),
            f"residual_std_{lookback}": residual_std,
            f"residual_std_atr_{lookback}": _safe_div(residual_std, atr),
            f"swing_amplitude_atr_{lookback}": _safe_div(width, atr),
            f"alternation_rate_{lookback}": _alternation_rate(close, lookback),
            f"poc_price_corr_{lookback}": close.rolling(lookback, min_periods=lookback).corr(poc),
            f"new_price_high_{lookback}": new_price_high,
            f"new_poc_high_{lookback}": new_poc_high,
            f"new_price_high_without_poc_high_{lookback}": new_price_high & ~new_poc_high,
        })

    for lookback in STALL_LOOKBACKS:
        feat[f"bars_since_poc_high_{lookback}"] = _bars_since_rolling_high(poc, lookback)
        feat[f"poc_nonadvance_count_{lookback}"] = _rolling_count(poc_delta, lookback, "le0")
        feat[f"poc_lower_count_{lookback}"] = _rolling_count(poc_delta, lookback, "lt0")

    feat.update({
        "poc_delta_1_atr": _safe_div(poc_delta, atr),
        "poc_delta_1_bar_range": _safe_div(poc_delta, base["price_range"]),
        "poc_delta_1_profile_width": _safe_div(poc_delta, base["profile_width"]),
        "price_delta_1_atr": _safe_div(price_delta, atr),
    })
    derived = pd.DataFrame(feat, index=base.index)
    out = pd.concat([base, derived], axis=1)
    out.insert(0, "feature_schema_version", FEATURE_SCHEMA_VERSION)
    return out


class _PressureBar:
    def __init__(self, timeframe: str, session: str, bucket: pd.Timestamp) -> None:
        self.timeframe = timeframe
        self.session = session
        self.bucket = bucket
        self.start_seq = None
        self.end_seq = None
        self.open = self.high = self.low = self.close = None
        self.total_volume = 0.0
        self.signed_volume = 0.0
        self.positive_volume = 0.0
        self.negative_volume = 0.0
        self.neutral_volume = 0.0
        self.positive_ticks = 0
        self.negative_ticks = 0
        self.neutral_ticks = 0
        self.by_price: dict[float, list[float]] = {}

    def add(self, seq: int, price: float, volume: float, side: int) -> None:
        if self.start_seq is None:
            self.start_seq = seq
            self.open = self.high = self.low = price
        self.end_seq = seq
        self.high = max(float(self.high), price)
        self.low = min(float(self.low), price)
        self.close = price
        self.total_volume += volume
        self.signed_volume += volume * side
        if side > 0:
            self.positive_volume += volume
            self.positive_ticks += 1
        elif side < 0:
            self.negative_volume += volume
            self.negative_ticks += 1
        else:
            self.neutral_volume += volume
            self.neutral_ticks += 1
        slot = self.by_price.setdefault(price, [0.0, 0.0, 0.0, 0.0])
        slot[0] += volume
        if side > 0:
            slot[1] += volume
        elif side < 0:
            slot[2] += volume
        else:
            slot[3] += volume

    def finish(self) -> dict:
        tick_count = self.positive_ticks + self.negative_ticks + self.neutral_ticks
        price_range = float(self.high - self.low)
        result = {
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "timeframe": self.timeframe,
            "session": self.session,
            "bar_start": self.bucket.to_pydatetime(),
            "bar_start_seq": int(self.start_seq),
            "bar_end_seq": int(self.end_seq),
            "tdp_total_volume": self.total_volume,
            "tdp_signed_volume": self.signed_volume,
            "tdp_positive_volume": self.positive_volume,
            "tdp_negative_volume": self.negative_volume,
            "tdp_neutral_volume": self.neutral_volume,
            "tdp_ratio": self.signed_volume / self.total_volume if self.total_volume else np.nan,
            "tdp_positive_share": self.positive_volume / self.total_volume if self.total_volume else np.nan,
            "tdp_positive_tick_share": self.positive_ticks / tick_count if tick_count else np.nan,
            "tdp_signed_tick_ratio": (self.positive_ticks - self.negative_ticks) / tick_count if tick_count else np.nan,
            "bar_internal_up_extension": float(self.high - self.open),
            "bar_internal_net_advance": float(self.close - self.open),
            "close_location_in_bar": 0.5 if price_range == 0 else float((self.close - self.low) / price_range),
            "impact_per_1000_positive_volume": 1000.0 * (self.high - self.open) / self.positive_volume if self.positive_volume else np.nan,
            "impact_per_positive_tick": (self.high - self.open) / self.positive_ticks if self.positive_ticks else np.nan,
            "net_advance_per_1000_positive_volume": 1000.0 * (self.close - self.open) / self.positive_volume if self.positive_volume else np.nan,
        }
        for q in HIGH_ZONE_Q:
            suffix = f"q{int(round(q * 100))}"
            threshold = float(self.low + q * price_range)
            pos = neg = neutral = total = 0.0
            for price, (vol, pv, nv, zv) in self.by_price.items():
                if price >= threshold:
                    total += vol
                    pos += pv
                    neg += nv
                    neutral += zv
            result[f"high_zone_threshold_{suffix}"] = threshold
            result[f"high_zone_volume_{suffix}"] = total
            result[f"high_zone_positive_volume_{suffix}"] = pos
            result[f"high_zone_negative_volume_{suffix}"] = neg
            result[f"high_zone_neutral_volume_{suffix}"] = neutral
            result[f"high_zone_tdp_{suffix}"] = (pos - neg) / total if total else np.nan
            result[f"high_zone_volume_share_{suffix}"] = total / self.total_volume if self.total_volume else np.nan
            result[f"high_zone_positive_share_{suffix}"] = pos / total if total else np.nan
        return result


def compute_pressure_features(
    ticks: pd.DataFrame,
    timeframe: str,
    session: Literal["day", "night"],
) -> pd.DataFrame:
    """Aggregate tick-direction pressure and within-bar effort/result causally."""
    if timeframe not in BAR_RESOLUTIONS:
        raise ValueError(timeframe)
    required = {"_seq", "datetime", "price", "volume", "side"}
    missing = required.difference(ticks.columns)
    if missing:
        raise ValueError(f"Missing tick columns: {sorted(missing)}")
    seq = ticks["_seq"].to_numpy(dtype=np.int64)
    if len(seq) > 1 and np.any(np.diff(seq) <= 0):
        raise ValueError("Tick _seq must be strictly increasing")
    sides = set(pd.to_numeric(ticks["side"], errors="raise").astype(int).unique())
    if not sides.issubset({-1, 0, 1}):
        raise ValueError(f"Unexpected TDP side values: {sorted(sides)}")

    current: _PressureBar | None = None
    out: list[dict] = []
    seconds = BAR_RESOLUTIONS[timeframe]
    last_time: pd.Timestamp | None = None
    for row in ticks[["_seq", "datetime", "price", "volume", "side"]].itertuples(index=False):
        ts = _to_timestamp(row.datetime)
        if last_time is not None and ts < last_time:
            raise ValueError("Tick datetime moved backward")
        last_time = ts
        bucket = _bucket_start(ts, session, seconds)
        if current is None:
            current = _PressureBar(timeframe, session, bucket)
        elif bucket != current.bucket:
            out.append(current.finish())
            current = _PressureBar(timeframe, session, bucket)
        current.add(int(row._0), float(row.price), float(row.volume), int(row.side))
    if current is not None:
        out.append(current.finish())
    return pd.DataFrame(out)


def compute_structural_high_zone_features(
    ticks: pd.DataFrame,
    bar_features: pd.DataFrame,
    *,
    lookback: int = 24,
    atr_multipliers: Sequence[float] = (0.25, 0.50, 1.00),
) -> pd.DataFrame:
    """Aggregate TDP pressure above `rolling_high - x*ATR` for each completed bar.

    The threshold is derived entirely from the completed bar feature row. Early
    warm-up bars without rolling-high/ATR emit NaN rather than inventing a level.
    """
    required_ticks = {"_seq", "price", "volume", "side"}
    missing = required_ticks.difference(ticks.columns)
    if missing:
        raise ValueError(f"Missing tick columns: {sorted(missing)}")
    required_bars = {
        "timeframe", "session", "bar_start_seq", "bar_end_seq", "volume", "atr_n",
        f"rolling_high_{lookback}",
    }
    missing_bars = required_bars.difference(bar_features.columns)
    if missing_bars:
        raise ValueError(f"Missing structural-zone bar columns: {sorted(missing_bars)}")
    seq = ticks["_seq"].to_numpy(dtype=np.int64)
    if len(seq) > 1 and np.any(np.diff(seq) <= 0):
        raise ValueError("Tick _seq must be strictly increasing")
    price = pd.to_numeric(ticks["price"], errors="coerce").to_numpy(dtype=float)
    volume = pd.to_numeric(ticks["volume"], errors="coerce").to_numpy(dtype=float)
    side = pd.to_numeric(ticks["side"], errors="raise").to_numpy(dtype=int)
    rows: list[dict] = []
    for bar in bar_features.itertuples(index=False):
        start_seq = int(getattr(bar, "bar_start_seq"))
        end_seq = int(getattr(bar, "bar_end_seq"))
        left = int(np.searchsorted(seq, start_seq, side="left"))
        right = int(np.searchsorted(seq, end_seq, side="right"))
        base = {
            "timeframe": getattr(bar, "timeframe"),
            "session": getattr(bar, "session"),
            "bar_start_seq": start_seq,
            "bar_end_seq": end_seq,
        }
        rolling_high = float(getattr(bar, f"rolling_high_{lookback}"))
        atr = float(getattr(bar, "atr_n")) if pd.notna(getattr(bar, "atr_n")) else np.nan
        bar_volume = float(getattr(bar, "volume"))
        for multiple in atr_multipliers:
            suffix = f"atr{int(round(multiple * 100)):03d}"
            if not np.isfinite(rolling_high) or not np.isfinite(atr):
                for name in ("threshold", "volume", "positive_volume", "negative_volume", "tdp", "volume_share"):
                    base[f"struct_high_zone_{name}_{suffix}"] = np.nan
                continue
            threshold = rolling_high - float(multiple) * atr
            mask = price[left:right] >= threshold
            v = volume[left:right][mask]
            sd = side[left:right][mask]
            total = float(v.sum()) if len(v) else 0.0
            pos = float(v[sd > 0].sum()) if len(v) else 0.0
            neg = float(v[sd < 0].sum()) if len(v) else 0.0
            base[f"struct_high_zone_threshold_{suffix}"] = float(threshold)
            base[f"struct_high_zone_volume_{suffix}"] = total
            base[f"struct_high_zone_positive_volume_{suffix}"] = pos
            base[f"struct_high_zone_negative_volume_{suffix}"] = neg
            base[f"struct_high_zone_tdp_{suffix}"] = (pos - neg) / total if total else np.nan
            base[f"struct_high_zone_volume_share_{suffix}"] = total / bar_volume if bar_volume else np.nan
        rows.append(base)
    return pd.DataFrame(rows)


def attach_pressure_features(
    bar_features: pd.DataFrame,
    pressure_features: pd.DataFrame,
) -> pd.DataFrame:
    """Join two causal layers by exact physical bar boundaries and add normalizations."""
    keys = ["timeframe", "session", "bar_start_seq", "bar_end_seq"]
    merged = bar_features.merge(
        pressure_features.drop(columns=["feature_schema_version", "bar_start"], errors="ignore"),
        on=keys,
        how="left",
        validate="one_to_one",
    )
    merged["bar_internal_up_extension_atr"] = _safe_div(merged["bar_internal_up_extension"], merged["atr_n"])
    merged["bar_internal_net_advance_atr"] = _safe_div(merged["bar_internal_net_advance"], merged["atr_n"])
    for col in [
        "tdp_positive_volume",
        "tdp_ratio",
        "high_zone_positive_volume_q80",
        "high_zone_tdp_q80",
        "impact_per_1000_positive_volume",
    ]:
        values = pd.to_numeric(merged[col], errors="coerce")
        mean = values.rolling(24, min_periods=12).mean()
        std = values.rolling(24, min_periods=12).std(ddof=0)
        merged[f"{col}_z24"] = _safe_div(values - mean, std)
    return merged
