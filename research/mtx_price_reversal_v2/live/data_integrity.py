from __future__ import annotations

from dataclasses import dataclass
import math
import pandas as pd


@dataclass(frozen=True)
class FeedCheck:
    ok: bool
    reasons: tuple[str, ...]


@dataclass
class OnlineDataIntegrityMonitor:
    stale_after_sec: float = 3.0
    last_seq: int | None = None
    last_exchange_ts: pd.Timestamp | None = None
    last_receive_ts: pd.Timestamp | None = None

    def on_tick(self, *, seq: int, exchange_ts, receive_ts, price: float, expected_contract: str, observed_contract: str) -> FeedCheck:
        reasons=[]
        ex=pd.Timestamp(exchange_ts); rx=pd.Timestamp(receive_ts)
        if self.last_seq is not None:
            if seq == self.last_seq: reasons.append("DUPLICATE_SEQ")
            elif seq < self.last_seq: reasons.append("OUT_OF_ORDER_SEQ")
        if self.last_exchange_ts is not None and ex < self.last_exchange_ts:
            reasons.append("TIMESTAMP_REVERSAL")
        if not math.isfinite(price) or price <= 0:
            reasons.append("INVALID_PRICE")
        if str(observed_contract) != str(expected_contract):
            reasons.append("UNEXPECTED_CONTRACT")
        if rx < ex:
            reasons.append("RECEIVE_BEFORE_EXCHANGE_TIME")
        self.last_seq=seq; self.last_exchange_ts=ex; self.last_receive_ts=rx
        return FeedCheck(not reasons,tuple(reasons))

    def heartbeat(self, now) -> FeedCheck:
        if self.last_receive_ts is None:
            return FeedCheck(False,("NO_DATA_YET",))
        age=(pd.Timestamp(now)-self.last_receive_ts).total_seconds()
        return FeedCheck(age <= self.stale_after_sec, () if age <= self.stale_after_sec else ("STALE_FEED",))
