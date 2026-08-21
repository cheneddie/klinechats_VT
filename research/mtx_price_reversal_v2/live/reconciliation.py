from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalPositionState:
    contract: str | None
    qty: int
    open_order_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BrokerSnapshot:
    contract: str | None
    qty: int
    open_order_ids: tuple[str, ...] = ()
    connected: bool = True


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    allow_new_entry: bool
    reasons: tuple[str, ...]


def reconcile(local: LocalPositionState, broker: BrokerSnapshot) -> ReconciliationResult:
    reasons=[]
    if not broker.connected:
        reasons.append("BROKER_DISCONNECTED")
    if local.contract != broker.contract and (local.qty != 0 or broker.qty != 0):
        reasons.append("CONTRACT_MISMATCH")
    if local.qty != broker.qty:
        reasons.append("POSITION_MISMATCH")
    if set(local.open_order_ids) != set(broker.open_order_ids):
        reasons.append("OPEN_ORDER_MISMATCH")
    ok=not reasons
    return ReconciliationResult(ok=ok,allow_new_entry=ok,reasons=tuple(reasons))
