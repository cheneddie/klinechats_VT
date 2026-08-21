from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import pandas as pd

from .execution_tick import Fill, FillModel, Side, Trigger, first_long_stop_trigger, first_of_triggers, trigger_then_market_fill


class ExitReason(str, Enum):
    STRUCTURAL_STOP = "STRUCTURAL_STOP"
    CATASTROPHIC_STOP = "CATASTROPHIC_STOP"
    TIME_EXIT = "TIME_EXIT"
    PATH_STATE_EXIT = "PATH_STATE_EXIT"
    TRAILING_EXIT = "TRAILING_EXIT"
    TARGET = "TARGET"


@dataclass(frozen=True)
class StructuralRisk:
    stop_price: float | None
    rule: str = "UNFROZEN"


@dataclass(frozen=True)
class CatastrophicRisk:
    stop_price: float | None
    rule: str = "UNFROZEN"


@dataclass(frozen=True)
class RiskPlan:
    structural: StructuralRisk
    catastrophic: CatastrophicRisk
    version: str = "UNFROZEN"


@dataclass(frozen=True)
class RiskTriggerSet:
    structural: Trigger | None
    catastrophic: Trigger | None
    @property
    def earliest(self) -> Trigger | None:
        return first_of_triggers(self.structural, self.catastrophic)


@dataclass(frozen=True)
class RiskExit:
    reason: ExitReason
    trigger: Trigger
    fill: Fill | None


def signal_extreme_stop(signal_low: float, buffer_points: float) -> float:
    if buffer_points < 0: raise ValueError("buffer_points must be >= 0")
    return float(signal_low-buffer_points)


def volatility_buffer_stop(signal_low: float, prior_causal_vol: float, k: float) -> float:
    if prior_causal_vol <= 0 or k < 0: raise ValueError("invalid causal vol/k")
    return float(signal_low-prior_causal_vol*k)


def catastrophic_points_stop(entry_price: float, max_loss_points: float) -> float:
    if max_loss_points<=0: raise ValueError("max_loss_points must be positive")
    return float(entry_price-max_loss_points)


def long_risk_triggers(ticks: pd.DataFrame, plan: RiskPlan, *, after_seq: int) -> RiskTriggerSet:
    s = None if plan.structural.stop_price is None else first_long_stop_trigger(ticks, plan.structural.stop_price, after_seq=after_seq, reason=ExitReason.STRUCTURAL_STOP.value)
    c = None if plan.catastrophic.stop_price is None else first_long_stop_trigger(ticks, plan.catastrophic.stop_price, after_seq=after_seq, reason=ExitReason.CATASTROPHIC_STOP.value)
    return RiskTriggerSet(s,c)


def resolve_long_risk_exit(ticks: pd.DataFrame, plan: RiskPlan, *, after_seq: int, fill_model: FillModel = FillModel.NEXT_PHYSICAL_PRINT, delayed_prints: int = 1, delay_seconds: float = 0.0) -> RiskExit | None:
    trigger=long_risk_triggers(ticks,plan,after_seq=after_seq).earliest
    if trigger is None: return None
    reason=ExitReason(trigger.reason)
    fill=trigger_then_market_fill(ticks,trigger,side=Side.SELL,reason=reason.value,model=fill_model,delayed_prints=delayed_prints,delay_seconds=delay_seconds)
    return RiskExit(reason,trigger,fill)
