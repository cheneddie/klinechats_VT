from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class RiskPlan:
    structural_stop_price: float|None
    catastrophic_stop_price: float|None
    version: str = "UNFROZEN"
    def effective_long_stop(self) -> float|None:
        vals=[x for x in (self.structural_stop_price,self.catastrophic_stop_price) if x is not None]
        return max(vals) if vals else None

def signal_extreme_stop(signal_low: float, buffer_points: float) -> float:
    return float(signal_low-buffer_points)

def catastrophic_points_stop(entry_price: float, max_loss_points: float) -> float:
    if max_loss_points<=0: raise ValueError("max_loss_points must be positive")
    return float(entry_price-max_loss_points)
