"""Causal multi-resolution bars and developing Volume Profile / POC.

Input rows are consumed in existing physical order and must already contain the
source `_seq`. No sorting is performed here. Completed bars calculate the full
profile once at bar close; developing POC keeps an incremental max-volume-price
set so per-tick snapshots do not rebuild VAH/VAL on every tick.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time
from math import isnan
from typing import Literal, Mapping

import numpy as np
import pandas as pd

BAR_RESOLUTIONS: dict[str, int] = {
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
}


@dataclass(frozen=True)
class ProfileLevels:
    poc: float
    poc_volume: float
    poc_share: float
    vah: float
    val: float
    profile_width: float
    poc_rank_in_range: float
    vwap: float


@dataclass(frozen=True)
class CompletedBar:
    timeframe: str
    session: str
    bar_start: datetime
    bar_end_exclusive: datetime
    bar_start_seq: int
    bar_end_seq: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int
    poc: float
    poc_volume: float
    poc_share: float
    vah: float
    val: float
    profile_width: float
    poc_rank_in_range: float
    vwap: float
    price_range: float
    atr_n: float | None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DevelopingPocSnapshot:
    timeframe: str
    session: str
    bar_start: datetime
    decision_seq: int
    decision_time: datetime
    decision_price: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int
    developing_poc: float
    poc_volume: float
    poc_share: float
    poc_rank_in_range: float
    vwap: float

    def as_dict(self) -> dict:
        return asdict(self)


def _to_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tz is not None:
        ts = ts.tz_localize(None)
    return ts


def _session_anchor(ts: pd.Timestamp, session: str) -> pd.Timestamp:
    """Return the causal wall-clock anchor for a pre-classified session row."""
    d = ts.normalize()
    if session == "day":
        return d + pd.Timedelta(hours=8, minutes=45)
    if session == "night":
        if ts.time() >= time(15, 0):
            return d + pd.Timedelta(hours=15)
        return d - pd.Timedelta(days=1) + pd.Timedelta(hours=15)
    raise ValueError(f"Unsupported session: {session!r}")


def _bucket_start(ts: pd.Timestamp, session: str, seconds: int) -> pd.Timestamp:
    anchor = _session_anchor(ts, session)
    elapsed = int((ts - anchor).total_seconds())
    if elapsed < 0:
        raise ValueError(f"Timestamp {ts} is before session anchor {anchor}")
    return anchor + pd.Timedelta(seconds=(elapsed // seconds) * seconds)


def _pick_poc(
    volume_by_price: Mapping[float, float],
    vwap: float,
    prior_poc: float | None,
) -> tuple[float, float]:
    if not volume_by_price:
        raise ValueError("Cannot choose POC from empty profile")
    max_volume = max(volume_by_price.values())
    tied = [float(price) for price, vol in volume_by_price.items() if vol == max_volume]
    best_vwap_distance = min(abs(price - vwap) for price in tied)
    tied = [price for price in tied if abs(price - vwap) == best_vwap_distance]
    if len(tied) > 1 and prior_poc is not None and not isnan(prior_poc):
        best_prior_distance = min(abs(price - prior_poc) for price in tied)
        tied = [price for price in tied if abs(price - prior_poc) == best_prior_distance]
    # Final deterministic fallback is lower price; alternate tie rules are a later
    # sensitivity test, never hidden optimization in feature extraction.
    return min(tied), float(max_volume)


def volume_profile_levels(
    volume_by_price: Mapping[float, float],
    *,
    total_volume: float,
    vwap: float,
    low: float,
    high: float,
    prior_poc: float | None = None,
    value_area: float = 0.80,
) -> ProfileLevels:
    """Compute completed POC/VAH/VAL from exact traded prices."""
    if not 0 < value_area <= 1:
        raise ValueError("value_area must be in (0, 1]")
    if total_volume <= 0:
        raise ValueError("total_volume must be positive")
    poc, poc_volume = _pick_poc(volume_by_price, vwap, prior_poc)
    prices = np.array(sorted(float(p) for p in volume_by_price), dtype=float)
    volumes = np.array([float(volume_by_price[p]) for p in prices], dtype=float)
    poc_index = int(np.flatnonzero(prices == poc)[0])
    lo = hi = poc_index
    accumulated = float(volumes[poc_index])
    target = float(total_volume * value_area)
    while accumulated < target and (lo > 0 or hi < len(prices) - 1):
        left_index = lo - 1 if lo > 0 else None
        right_index = hi + 1 if hi < len(prices) - 1 else None
        if left_index is None:
            choose_left = False
        elif right_index is None:
            choose_left = True
        else:
            left_volume, right_volume = volumes[left_index], volumes[right_index]
            if left_volume != right_volume:
                choose_left = left_volume > right_volume
            else:
                left_distance = abs(prices[left_index] - vwap)
                right_distance = abs(prices[right_index] - vwap)
                choose_left = left_distance <= right_distance
        if choose_left:
            lo = int(left_index)
            accumulated += float(volumes[lo])
        else:
            hi = int(right_index)
            accumulated += float(volumes[hi])
    price_range = float(high - low)
    poc_rank = 0.5 if price_range == 0 else float((poc - low) / price_range)
    return ProfileLevels(
        poc=float(poc),
        poc_volume=float(poc_volume),
        poc_share=float(poc_volume / total_volume),
        vah=float(prices[hi]),
        val=float(prices[lo]),
        profile_width=float(prices[hi] - prices[lo]),
        poc_rank_in_range=poc_rank,
        vwap=float(vwap),
    )


class BarAccumulator:
    """One timeframe/session causal accumulator consuming physical ticks once."""

    def __init__(
        self,
        timeframe: str,
        session: Literal["day", "night"],
        *,
        value_area: float = 0.80,
        atr_period: int = 14,
    ) -> None:
        if timeframe not in BAR_RESOLUTIONS:
            raise ValueError(f"Unsupported timeframe {timeframe!r}")
        if atr_period <= 0:
            raise ValueError("atr_period must be positive")
        self.timeframe = timeframe
        self.seconds = BAR_RESOLUTIONS[timeframe]
        self.session = session
        self.value_area = value_area
        self.atr_period = atr_period
        self.current_bucket: pd.Timestamp | None = None
        self.start_seq: int | None = None
        self.end_seq: int | None = None
        self.open: float | None = None
        self.high: float | None = None
        self.low: float | None = None
        self.close: float | None = None
        self.total_volume = 0.0
        self.tick_count = 0
        self.pv_sum = 0.0
        self.volume_by_price: dict[float, float] = {}
        self.max_price_volume = 0.0
        self.max_volume_prices: set[float] = set()
        self.prior_poc: float | None = None
        self.prior_close: float | None = None
        self.true_ranges: list[float] = []
        self.last_seq: int | None = None
        self.last_time: pd.Timestamp | None = None

    def _assert_order(self, seq: int, ts: pd.Timestamp) -> None:
        if self.last_seq is not None and seq <= self.last_seq:
            raise ValueError(f"Non-increasing physical _seq: {seq} after {self.last_seq}")
        if self.last_time is not None and ts < self.last_time:
            raise ValueError(f"Datetime moved backward: {ts} after {self.last_time}")
        self.last_seq = seq
        self.last_time = ts

    def _reset(self, bucket: pd.Timestamp) -> None:
        self.current_bucket = bucket
        self.start_seq = self.end_seq = None
        self.open = self.high = self.low = self.close = None
        self.total_volume = 0.0
        self.tick_count = 0
        self.pv_sum = 0.0
        self.volume_by_price = {}
        self.max_price_volume = 0.0
        self.max_volume_prices = set()

    def _add(self, seq: int, price: float, volume: float) -> None:
        if volume <= 0:
            raise ValueError(f"Non-positive volume at seq={seq}: {volume}")
        if self.start_seq is None:
            self.start_seq = seq
            self.open = price
            self.high = price
            self.low = price
        self.end_seq = seq
        self.high = max(float(self.high), price)
        self.low = min(float(self.low), price)
        self.close = price
        self.total_volume += volume
        self.tick_count += 1
        self.pv_sum += price * volume
        new_price_volume = self.volume_by_price.get(price, 0.0) + volume
        self.volume_by_price[price] = new_price_volume
        if new_price_volume > self.max_price_volume:
            self.max_price_volume = new_price_volume
            self.max_volume_prices = {price}
        elif new_price_volume == self.max_price_volume:
            self.max_volume_prices.add(price)

    def _developing_poc(self) -> tuple[float, float, float, float]:
        if self.tick_count == 0 or not self.max_volume_prices:
            raise ValueError("Empty accumulator")
        vwap = self.pv_sum / self.total_volume
        tied = list(self.max_volume_prices)
        best_vwap_distance = min(abs(price - vwap) for price in tied)
        tied = [price for price in tied if abs(price - vwap) == best_vwap_distance]
        if len(tied) > 1 and self.prior_poc is not None and not isnan(self.prior_poc):
            best_prior_distance = min(abs(price - self.prior_poc) for price in tied)
            tied = [price for price in tied if abs(price - self.prior_poc) == best_prior_distance]
        poc = min(tied)
        price_range = float(self.high - self.low)
        poc_rank = 0.5 if price_range == 0 else float((poc - self.low) / price_range)
        return float(poc), float(self.max_price_volume), float(poc_rank), float(vwap)

    def _profile(self) -> ProfileLevels:
        if self.tick_count == 0:
            raise ValueError("Empty accumulator")
        return volume_profile_levels(
            self.volume_by_price,
            total_volume=self.total_volume,
            vwap=self.pv_sum / self.total_volume,
            low=float(self.low),
            high=float(self.high),
            prior_poc=self.prior_poc,
            value_area=self.value_area,
        )

    def _complete_current(self) -> CompletedBar | None:
        if self.current_bucket is None or self.tick_count == 0:
            return None
        profile = self._profile()
        high, low = float(self.high), float(self.low)
        if self.prior_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - self.prior_close),
                abs(low - self.prior_close),
            )
        self.true_ranges.append(float(true_range))
        if len(self.true_ranges) > self.atr_period:
            self.true_ranges.pop(0)
        atr = float(np.mean(self.true_ranges)) if len(self.true_ranges) == self.atr_period else None
        bar = CompletedBar(
            timeframe=self.timeframe,
            session=self.session,
            bar_start=self.current_bucket.to_pydatetime(),
            bar_end_exclusive=(self.current_bucket + pd.Timedelta(seconds=self.seconds)).to_pydatetime(),
            bar_start_seq=int(self.start_seq),
            bar_end_seq=int(self.end_seq),
            open=float(self.open),
            high=high,
            low=low,
            close=float(self.close),
            volume=float(self.total_volume),
            tick_count=int(self.tick_count),
            poc=profile.poc,
            poc_volume=profile.poc_volume,
            poc_share=profile.poc_share,
            vah=profile.vah,
            val=profile.val,
            profile_width=profile.profile_width,
            poc_rank_in_range=profile.poc_rank_in_range,
            vwap=profile.vwap,
            price_range=float(high - low),
            atr_n=atr,
        )
        self.prior_poc = profile.poc
        self.prior_close = float(self.close)
        return bar

    def push(self, seq: int, timestamp, price: float, volume: float) -> CompletedBar | None:
        ts = _to_timestamp(timestamp)
        self._assert_order(int(seq), ts)
        bucket = _bucket_start(ts, self.session, self.seconds)
        completed = None
        if self.current_bucket is None:
            self._reset(bucket)
        elif bucket != self.current_bucket:
            if bucket < self.current_bucket:
                raise ValueError("Bar bucket moved backward")
            completed = self._complete_current()
            self._reset(bucket)
        self._add(int(seq), float(price), float(volume))
        return completed

    def developing_snapshot(self, seq: int, timestamp, price: float) -> DevelopingPocSnapshot:
        ts = _to_timestamp(timestamp)
        if self.current_bucket is None or self.tick_count == 0:
            raise ValueError("No current bar")
        if int(seq) != self.end_seq:
            raise ValueError("Snapshot must be taken at the latest processed physical seq")
        poc, poc_volume, poc_rank, vwap = self._developing_poc()
        return DevelopingPocSnapshot(
            timeframe=self.timeframe,
            session=self.session,
            bar_start=self.current_bucket.to_pydatetime(),
            decision_seq=int(seq),
            decision_time=ts.to_pydatetime(),
            decision_price=float(price),
            open=float(self.open),
            high=float(self.high),
            low=float(self.low),
            close=float(self.close),
            volume=float(self.total_volume),
            tick_count=int(self.tick_count),
            developing_poc=poc,
            poc_volume=poc_volume,
            poc_share=float(poc_volume / self.total_volume),
            poc_rank_in_range=poc_rank,
            vwap=vwap,
        )

    def finish(self) -> CompletedBar | None:
        bar = self._complete_current()
        self.current_bucket = None
        return bar


def _validate_frame(df: pd.DataFrame) -> None:
    required = {"_seq", "datetime", "price", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    seq = df["_seq"].to_numpy(dtype=np.int64)
    if len(seq) > 1 and np.any(np.diff(seq) <= 0):
        raise ValueError("Input _seq must be strictly increasing; do not sort inside bar builder")
    dt = pd.to_datetime(df["datetime"]).to_numpy(dtype="datetime64[us]").astype("int64")
    if len(dt) > 1 and np.any(np.diff(dt) < 0):
        raise ValueError("Input datetime moved backward in physical order")


def build_bars(
    df: pd.DataFrame,
    timeframe: str,
    session: Literal["day", "night"],
    *,
    value_area: float = 0.80,
    atr_period: int = 14,
) -> list[CompletedBar]:
    """Build completed bars without reordering supplied physical ticks."""
    _validate_frame(df)
    acc = BarAccumulator(timeframe, session, value_area=value_area, atr_period=atr_period)
    out: list[CompletedBar] = []
    for row in df[["_seq", "datetime", "price", "volume"]].itertuples(index=False):
        completed = acc.push(int(row._0), row.datetime, float(row.price), float(row.volume))
        if completed is not None:
            out.append(completed)
    final = acc.finish()
    if final is not None:
        out.append(final)
    return out


def build_developing_poc(
    df: pd.DataFrame,
    timeframe: str,
    session: Literal["day", "night"],
    *,
    snapshot_mode: Literal["tick", "second"] = "second",
    value_area: float = 0.80,
) -> list[DevelopingPocSnapshot]:
    """Build causal developing POC snapshots for a bounded replay/window.

    `tick` snapshots after every physical tick. `second` snapshots only after the
    final physical tick observed in each second. Streaming/live callers should use
    `BarAccumulator` directly rather than materializing an unbounded snapshot list.
    """
    _validate_frame(df)
    acc = BarAccumulator(timeframe, session, value_area=value_area)
    rows = list(df[["_seq", "datetime", "price", "volume"]].itertuples(index=False))
    out: list[DevelopingPocSnapshot] = []
    for index, row in enumerate(rows):
        seq = int(row._0)
        acc.push(seq, row.datetime, float(row.price), float(row.volume))
        take = snapshot_mode == "tick"
        if snapshot_mode == "second":
            current_second = _to_timestamp(row.datetime).floor("s")
            next_second = (
                _to_timestamp(rows[index + 1].datetime).floor("s")
                if index + 1 < len(rows)
                else None
            )
            take = next_second != current_second
        if take:
            out.append(acc.developing_snapshot(seq, row.datetime, float(row.price)))
    return out
