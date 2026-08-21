from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class Fill:
    seq: int
    time: pd.Timestamp
    price: float

def _assert_seq(ticks: pd.DataFrame) -> None:
    a=ticks["_seq"].to_numpy()
    if len(a)>1 and (a[1:]<=a[:-1]).any():
        raise ValueError("physical _seq must be strictly increasing")

def first_tradable_print(ticks: pd.DataFrame, earliest_time, *, after_seq: int|None=None) -> Fill|None:
    _assert_seq(ticks)
    t=pd.Timestamp(earliest_time)
    x=ticks[pd.to_datetime(ticks["datetime"])>=t]
    if after_seq is not None: x=x[x["_seq"]>after_seq]
    if x.empty: return None
    r=x.iloc[0]; return Fill(int(r._seq),pd.Timestamp(r.datetime),float(r.price))

def first_long_stop_trigger(ticks: pd.DataFrame, stop_price: float, *, after_seq: int) -> Fill|None:
    """First physical print at/below trigger; sequence resolves same-second order."""
    _assert_seq(ticks)
    x=ticks[(ticks["_seq"]>after_seq) & (ticks["price"]<=stop_price)]
    if x.empty: return None
    r=x.iloc[0]; return Fill(int(r._seq),pd.Timestamp(r.datetime),float(r.price))

def first_long_target_trigger(ticks: pd.DataFrame, target_price: float, *, after_seq: int) -> Fill|None:
    _assert_seq(ticks)
    x=ticks[(ticks["_seq"]>after_seq) & (ticks["price"]>=target_price)]
    if x.empty: return None
    r=x.iloc[0]; return Fill(int(r._seq),pd.Timestamp(r.datetime),float(r.price))

def first_of(*fills: Fill|None) -> Fill|None:
    x=[f for f in fills if f is not None]
    return min(x,key=lambda f:f.seq) if x else None
