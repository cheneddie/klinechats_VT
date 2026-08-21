from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class ClockObservation:
    exchange_time: pd.Timestamp
    receive_time: pd.Timestamp
    decision_time: pd.Timestamp | None = None
    submit_time: pd.Timestamp | None = None
    ack_time: pd.Timestamp | None = None

    @property
    def feed_latency_ms(self) -> float:
        return float((self.receive_time-self.exchange_time).total_seconds()*1000)

    def drift_ok(self, max_abs_ms: float) -> bool:
        return abs(self.feed_latency_ms) <= max_abs_ms
