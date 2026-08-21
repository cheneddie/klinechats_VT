from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class DriftBand:
    reference: float
    warn_relative: float
    halt_relative: float


def relative_drift(current: float, reference: float) -> float:
    if reference == 0: return math.inf if current != 0 else 0.0
    return abs(current-reference)/abs(reference)


def drift_status(current: float, band: DriftBand) -> str:
    d=relative_drift(current,band.reference)
    if d >= band.halt_relative: return "HALT"
    if d >= band.warn_relative: return "WARN"
    return "OK"
