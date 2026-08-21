from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class FixedTimeManagement:
    max_holding_sec: int = 300

@dataclass(frozen=True)
class PathState:
    pnl_30: float|None=None
    pnl_60: float|None=None
    mfe_30: float|None=None
    mae_30: float|None=None
    mfe_60: float|None=None
    mae_60: float|None=None

# Intentionally no fitted rule here. Historical path features are discovery-only
# until a management rule is frozen before new OOS is inspected.
