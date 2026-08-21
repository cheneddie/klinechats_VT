from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import pandas as pd


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class FillModel(str, Enum):
    TRIGGER_PRINT_DIAGNOSTIC = "TRIGGER_PRINT_DIAGNOSTIC"
    NEXT_PHYSICAL_PRINT = "NEXT_PHYSICAL_PRINT"
    DELAYED_PHYSICAL_PRINT = "DELAYED_PHYSICAL_PRINT"


@dataclass(frozen=True)
class Trigger:
    seq: int
    time: pd.Timestamp
    price: float
    reason: str


@dataclass(frozen=True)
class OrderIntent:
    side: Side
    reason: str
    trigger_seq: int
    trigger_time: pd.Timestamp
    trigger_price: float
    submit_after_seq: int
    minimum_submit_time: pd.Timestamp | None = None


@dataclass(frozen=True)
class Fill:
    seq: int
    time: pd.Timestamp
    price: float
    side: Side
    reason: str
    trigger_seq: int | None = None
    trigger_time: pd.Timestamp | None = None
    trigger_price: float | None = None
    slippage_points: float = 0.0


def _assert_seq(ticks: pd.DataFrame) -> None:
    if "_seq" not in ticks or "datetime" not in ticks or "price" not in ticks:
        raise ValueError("ticks require _seq, datetime, price")
    a = ticks["_seq"].to_numpy()
    if len(a) > 1 and (a[1:] <= a[:-1]).any():
        raise ValueError("physical _seq must be strictly increasing")


def _row_to_trigger(r, reason: str) -> Trigger:
    return Trigger(int(r._seq), pd.Timestamp(r.datetime), float(r.price), reason)


def _row_to_fill(r, *, side: Side, reason: str, trigger: Trigger | None = None) -> Fill:
    price = float(r.price)
    slip = 0.0
    if trigger is not None:
        slip = (trigger.price - price) if side == Side.SELL else (price - trigger.price)
    return Fill(
        seq=int(r._seq), time=pd.Timestamp(r.datetime), price=price,
        side=side, reason=reason,
        trigger_seq=None if trigger is None else trigger.seq,
        trigger_time=None if trigger is None else trigger.time,
        trigger_price=None if trigger is None else trigger.price,
        slippage_points=float(slip),
    )


def first_tradable_print(ticks: pd.DataFrame, earliest_time, *, after_seq: int | None = None, side: Side = Side.BUY, reason: str = "ENTRY") -> Fill | None:
    _assert_seq(ticks)
    t = pd.Timestamp(earliest_time)
    x = ticks[pd.to_datetime(ticks["datetime"]) >= t]
    if after_seq is not None:
        x = x[x["_seq"] > after_seq]
    if x.empty:
        return None
    return _row_to_fill(x.iloc[0], side=side, reason=reason)


def first_long_stop_trigger(ticks: pd.DataFrame, stop_price: float, *, after_seq: int, reason: str = "STOP_TRIGGER") -> Trigger | None:
    """First physical print at/below the level. This is a trigger, not a fill."""
    _assert_seq(ticks)
    x = ticks[(ticks["_seq"] > after_seq) & (ticks["price"] <= stop_price)]
    if x.empty:
        return None
    return _row_to_trigger(x.iloc[0], reason)


def first_long_target_trigger(ticks: pd.DataFrame, target_price: float, *, after_seq: int, reason: str = "TARGET_TRIGGER") -> Trigger | None:
    _assert_seq(ticks)
    x = ticks[(ticks["_seq"] > after_seq) & (ticks["price"] >= target_price)]
    if x.empty:
        return None
    return _row_to_trigger(x.iloc[0], reason)


def first_of_triggers(*triggers: Trigger | None) -> Trigger | None:
    x = [t for t in triggers if t is not None]
    return min(x, key=lambda t: t.seq) if x else None


def market_order_from_trigger(trigger: Trigger, *, side: Side, reason: str | None = None, delay_seconds: float = 0.0) -> OrderIntent:
    if delay_seconds < 0:
        raise ValueError("delay_seconds must be >= 0")
    return OrderIntent(
        side=side,
        reason=reason or trigger.reason,
        trigger_seq=trigger.seq,
        trigger_time=trigger.time,
        trigger_price=trigger.price,
        submit_after_seq=trigger.seq,
        minimum_submit_time=trigger.time + pd.Timedelta(seconds=delay_seconds),
    )


def fill_market_order(ticks: pd.DataFrame, order: OrderIntent, *, model: FillModel = FillModel.NEXT_PHYSICAL_PRINT, delayed_prints: int = 1) -> Fill | None:
    """Causal fill model after a trigger-generated market order.

    Trigger print is diagnostic only. NEXT_PHYSICAL_PRINT is the primary
    historical baseline. DELAYED_PHYSICAL_PRINT is an adverse stress model.
    """
    _assert_seq(ticks)
    trigger = Trigger(order.trigger_seq, order.trigger_time, order.trigger_price, order.reason)
    if model == FillModel.TRIGGER_PRINT_DIAGNOSTIC:
        x = ticks[ticks["_seq"] == order.trigger_seq]
        return None if x.empty else _row_to_fill(x.iloc[0], side=order.side, reason=order.reason, trigger=trigger)
    n = 1 if model == FillModel.NEXT_PHYSICAL_PRINT else delayed_prints
    if n < 1:
        raise ValueError("delayed_prints must be >= 1")
    x = ticks[ticks["_seq"] > order.trigger_seq].copy()
    if order.minimum_submit_time is not None:
        x = x[pd.to_datetime(x["datetime"]) >= order.minimum_submit_time]
    if len(x) < n:
        return None
    return _row_to_fill(x.iloc[n-1], side=order.side, reason=order.reason, trigger=trigger)


def trigger_then_market_fill(ticks: pd.DataFrame, trigger: Trigger | None, *, side: Side, reason: str | None = None, model: FillModel = FillModel.NEXT_PHYSICAL_PRINT, delayed_prints: int = 1, delay_seconds: float = 0.0) -> Fill | None:
    if trigger is None:
        return None
    order = market_order_from_trigger(trigger, side=side, reason=reason, delay_seconds=delay_seconds)
    return fill_market_order(ticks, order, model=model, delayed_prints=delayed_prints)
