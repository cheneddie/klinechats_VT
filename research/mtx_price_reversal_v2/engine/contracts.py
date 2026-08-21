from __future__ import annotations

from dataclasses import dataclass
import re
import pandas as pd

OUTRIGHT_RE = re.compile(r"^\d{6}$")


def is_outright(expiry: object) -> bool:
    return bool(OUTRIGHT_RE.fullmatch(str(expiry)))


@dataclass(frozen=True)
class ContractWindow:
    expiry: str
    tradable_from: pd.Timestamp
    tradable_until: pd.Timestamp
    reason: str = "FROZEN_EXCHANGE_SCHEDULE"

    def __post_init__(self):
        if not is_outright(self.expiry):
            raise ValueError(f"invalid outright expiry: {self.expiry}")
        if pd.Timestamp(self.tradable_from) >= pd.Timestamp(self.tradable_until):
            raise ValueError("tradable_from must be before tradable_until")


@dataclass(frozen=True)
class ContractSelection:
    active_contract: str
    next_contract: str | None
    selection_reason: str
    window_start: pd.Timestamp
    window_end: pd.Timestamp


class ContractSelectionError(RuntimeError):
    pass


class ContractSelectionEngine:
    """Causal selector based on a pre-frozen exchange/roll schedule.

    Production deliberately does NOT infer the front month from whole-day volume.
    Missing or overlapping schedule coverage fails closed.
    """

    def __init__(self, windows: list[ContractWindow]):
        self.windows = sorted(windows, key=lambda w: pd.Timestamp(w.tradable_from))
        for a, b in zip(self.windows, self.windows[1:]):
            if pd.Timestamp(a.tradable_until) > pd.Timestamp(b.tradable_from):
                raise ValueError(f"overlapping contract windows: {a.expiry}, {b.expiry}")

    def select(self, ts) -> ContractSelection:
        t = pd.Timestamp(ts)
        matches = [w for w in self.windows if pd.Timestamp(w.tradable_from) <= t < pd.Timestamp(w.tradable_until)]
        if len(matches) != 1:
            raise ContractSelectionError(f"expected exactly one active contract at {t}; found {len(matches)}")
        w = matches[0]
        i = self.windows.index(w)
        nxt = self.windows[i+1].expiry if i+1 < len(self.windows) else None
        return ContractSelection(w.expiry, nxt, w.reason, pd.Timestamp(w.tradable_from), pd.Timestamp(w.tradable_until))

    def assert_feed_contract(self, ts, observed_expiry: str) -> ContractSelection:
        s = self.select(ts)
        if str(observed_expiry) != s.active_contract:
            raise ContractSelectionError(
                f"unexpected contract at {ts}: observed={observed_expiry} active={s.active_contract}"
            )
        return s
