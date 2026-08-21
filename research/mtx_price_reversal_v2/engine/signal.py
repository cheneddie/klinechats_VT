from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class SignalSpec:
    lookback_sec: int = 30
    quantile: float = 0.0005
    previous_contracts: int = 3

def full_session(z: pd.DataFrame) -> pd.DataFrame:
    z=z.sort_values(["ts","first_seq"],kind="stable").copy()
    idx=np.arange(int(z.ts.min()),int(z.ts.max())+1,dtype=np.int64)
    s=z.set_index("ts").reindex(idx); s.index.name="ts"
    s["observed"]=s["first_seq"].notna(); s["close"]=s["close"].ffill()
    for c in ("trsv","dir_count","volume","trades"):
        if c in s: s[c]=s[c].fillna(0.0)
    return s

def price_signal(s: pd.DataFrame, lookback_sec: int) -> pd.Series:
    return s["close"] - s["close"].shift(lookback_sec)

def crossings(signal: pd.Series, threshold: float) -> np.ndarray:
    c=(signal<=threshold) & (signal.shift(1)>threshold)
    return signal.index[c.fillna(False)].to_numpy(dtype=np.int64)
