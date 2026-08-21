from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class PaperExecutionRecord:
    signal_latency_ms:float
    order_latency_ms:float
    fill_latency_ms:float
    slippage_points:float
    missed_signal:bool=False
    feed_gap:bool=False
    broker_rejection:bool=False
