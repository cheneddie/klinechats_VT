from __future__ import annotations

from enum import Enum


class StrategyStage(str, Enum):
    RESEARCH="RESEARCH"
    FROZEN="FROZEN"
    FORWARD_OOS="FORWARD_OOS"
    PAPER="PAPER"
    SHADOW_LIVE="SHADOW_LIVE"
    LIMITED_LIVE="LIMITED_LIVE"
    PRODUCTION="PRODUCTION"
    DEGRADED="DEGRADED"
    SUSPENDED="SUSPENDED"


_ALLOWED={
    StrategyStage.RESEARCH:{StrategyStage.FROZEN},
    StrategyStage.FROZEN:{StrategyStage.FORWARD_OOS,StrategyStage.RESEARCH},
    StrategyStage.FORWARD_OOS:{StrategyStage.PAPER,StrategyStage.RESEARCH,StrategyStage.SUSPENDED},
    StrategyStage.PAPER:{StrategyStage.SHADOW_LIVE,StrategyStage.SUSPENDED},
    StrategyStage.SHADOW_LIVE:{StrategyStage.LIMITED_LIVE,StrategyStage.SUSPENDED},
    StrategyStage.LIMITED_LIVE:{StrategyStage.PRODUCTION,StrategyStage.DEGRADED,StrategyStage.SUSPENDED},
    StrategyStage.PRODUCTION:{StrategyStage.DEGRADED,StrategyStage.SUSPENDED},
    StrategyStage.DEGRADED:{StrategyStage.PRODUCTION,StrategyStage.SUSPENDED},
    StrategyStage.SUSPENDED:{StrategyStage.RESEARCH},
}


def assert_transition(a: StrategyStage,b: StrategyStage) -> None:
    if b not in _ALLOWED.get(a,set()):
        raise ValueError(f"illegal lifecycle transition: {a}->{b}")
