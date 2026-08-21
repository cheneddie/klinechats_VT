from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import numpy as np

@dataclass
class CausalVolState:
    history_sessions: int = 60
    percentile_cut: float = 0.80
    _history: deque = None
    def __post_init__(self):
        if self._history is None: self._history=deque(maxlen=self.history_sessions)
    def percentile(self, current_prior14_range: float) -> float:
        if len(self._history)==0 or not np.isfinite(current_prior14_range): return np.nan
        a=np.asarray(self._history,dtype=float)
        return float(np.mean(a <= current_prior14_range))
    def is_high(self, current_prior14_range: float) -> bool:
        p=self.percentile(current_prior14_range)
        return bool(np.isfinite(p) and p>=self.percentile_cut)
    def observe_completed(self, prior14_range: float) -> None:
        if np.isfinite(prior14_range): self._history.append(float(prior14_range))

def in_time_window(ts_local, start="09:00:00", end="10:30:00") -> bool:
    t=ts_local.strftime("%H:%M:%S")
    return start <= t < end
