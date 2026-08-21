from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyRiskLimits:
    max_daily_loss_points: float
    max_trades_per_day: int
    max_consecutive_losses: int
    max_slippage_points: float
    max_position: int = 1
    max_open_orders: int = 3


@dataclass(frozen=True)
class RiskSnapshot:
    daily_pnl_points: float
    trades_today: int
    consecutive_losses: int
    last_slippage_points: float
    position_qty: int
    open_orders: int


def entry_allowed(lim: StrategyRiskLimits, s: RiskSnapshot) -> tuple[bool, tuple[str,...]]:
    reasons=[]
    if s.daily_pnl_points <= -abs(lim.max_daily_loss_points): reasons.append("DAILY_LOSS_LIMIT")
    if s.trades_today >= lim.max_trades_per_day: reasons.append("MAX_TRADES_PER_DAY")
    if s.consecutive_losses >= lim.max_consecutive_losses: reasons.append("CONSECUTIVE_LOSS_LIMIT")
    if s.last_slippage_points > lim.max_slippage_points: reasons.append("SLIPPAGE_LIMIT")
    if abs(s.position_qty) >= lim.max_position: reasons.append("MAX_POSITION")
    if s.open_orders >= lim.max_open_orders: reasons.append("MAX_OPEN_ORDERS")
    return (not reasons,tuple(reasons))
