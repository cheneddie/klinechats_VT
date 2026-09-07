from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class PortfolioPolicy:
    """Portfolio-level arbitration applied after causal signal/trade evaluation.

    Raw physical tick rows are never reordered here. Only already-causal trade
    candidates are ordered for portfolio arbitration.
    """

    mode: str = "INDEPENDENT_EVENT"
    overlap_policy: str = "ALLOW"
    max_open_positions: int = 1
    reentry_cooldown_seconds: int = 0
    fixed_quantity: float = 1.0
    force_flat_time: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "PortfolioPolicy":
        raw = dict(value or {})
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"unknown portfolio policy fields: {unknown}")

        # JSON has only one numeric type, while Python distinguishes int/float.
        # Portfolio Policy is hashed as an immutable execution assumption, so
        # semantically identical values such as JS `1` and Python `1.0` must
        # canonicalize to the same typed representation before hashing.
        if "mode" in raw:
            raw["mode"] = str(raw["mode"]).upper()
        if "overlap_policy" in raw:
            raw["overlap_policy"] = str(raw["overlap_policy"]).upper()
        if "max_open_positions" in raw:
            raw["max_open_positions"] = int(raw["max_open_positions"])
        if "reentry_cooldown_seconds" in raw:
            raw["reentry_cooldown_seconds"] = int(raw["reentry_cooldown_seconds"])
        if "fixed_quantity" in raw:
            raw["fixed_quantity"] = float(raw["fixed_quantity"])
        if "force_flat_time" in raw:
            flat = str(raw["force_flat_time"] or "").strip()
            raw["force_flat_time"] = flat or None

        policy = cls(**raw)
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.mode not in {"INDEPENDENT_EVENT", "SINGLE_POSITION"}:
            raise ValueError("portfolio mode must be INDEPENDENT_EVENT or SINGLE_POSITION")
        if self.overlap_policy not in {"ALLOW", "SKIP_WHILE_OPEN"}:
            raise ValueError("overlap_policy must be ALLOW or SKIP_WHILE_OPEN")
        if int(self.max_open_positions) < 1:
            raise ValueError("max_open_positions must be >= 1")
        if int(self.reentry_cooldown_seconds) < 0:
            raise ValueError("reentry_cooldown_seconds cannot be negative")
        if float(self.fixed_quantity) <= 0:
            raise ValueError("fixed_quantity must be > 0")
        if self.mode == "SINGLE_POSITION":
            if int(self.max_open_positions) != 1:
                raise ValueError("SINGLE_POSITION requires max_open_positions=1")
            if self.overlap_policy != "SKIP_WHILE_OPEN":
                raise ValueError("SINGLE_POSITION requires overlap_policy=SKIP_WHILE_OPEN")
        if self.force_flat_time is not None:
            parts = str(self.force_flat_time).split(":")
            if len(parts) not in {2, 3}:
                raise ValueError("force_flat_time must be HH:MM or HH:MM:SS")
            try:
                hour, minute = int(parts[0]), int(parts[1])
                second = int(parts[2]) if len(parts) == 3 else 0
            except Exception as exc:
                raise ValueError("force_flat_time must be HH:MM or HH:MM:SS") from exc
            if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
                raise ValueError("force_flat_time has invalid clock components")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        ts = pd.Timestamp(value)
        return ts if not pd.isna(ts) else None
    except Exception:
        return None


def _candidate_key(trade: dict[str, Any]) -> tuple[Any, ...]:
    ts = _timestamp(trade.get("entry_time") or trade.get("signal_time"))
    # Event ordering is allowed to be deterministic here; this does not reorder
    # raw physical tick paths. Missing timestamps sort last and are handled
    # conservatively by overlap checks.
    ts_key = ts.value if ts is not None else 2**63 - 1
    return (
        ts_key,
        str(trade.get("trading_date") or ""),
        int(trade.get("entry_seq") or trade.get("signal_seq") or 0),
        str(trade.get("event_id") or ""),
        str(trade.get("trade_id") or ""),
    )


def _same_physical_stream(a: dict[str, Any], b: dict[str, Any]) -> bool:
    pa = a.get("payload") or {}
    pb = b.get("payload") or {}
    return all(
        str(pa.get(key) or "") == str(pb.get(key) or "")
        for key in ("source_file", "contract")
    ) and str(a.get("trading_date") or "") == str(b.get("trading_date") or "")


def _entry_after_exit(candidate: dict[str, Any], active: dict[str, Any]) -> tuple[bool, str]:
    entry_ts = _timestamp(candidate.get("entry_time"))
    exit_ts = _timestamp(active.get("exit_time"))
    if entry_ts is not None and exit_ts is not None:
        if entry_ts > exit_ts:
            return True, "TIME_AFTER_EXIT"
        if entry_ts < exit_ts:
            return False, "TIME_OVERLAP"
        # Same timestamp is only safely ordered when both trades share the same
        # physical stream and the new entry seq is strictly after the old exit seq.
        if _same_physical_stream(candidate, active):
            return int(candidate.get("entry_seq") or -1) > int(active.get("exit_seq") or -1), "SAME_TIME_SEQ"
        return False, "SAME_TIME_CROSS_STREAM"

    if _same_physical_stream(candidate, active):
        return int(candidate.get("entry_seq") or -1) > int(active.get("exit_seq") or -1), "SEQ_ONLY"
    return False, "PORTFOLIO_ORDER_UNRESOLVED"


def _cooldown_satisfied(candidate: dict[str, Any], previous: dict[str, Any], seconds: int) -> bool:
    if seconds <= 0:
        return True
    entry_ts = _timestamp(candidate.get("entry_time"))
    exit_ts = _timestamp(previous.get("exit_time"))
    if entry_ts is None or exit_ts is None:
        return False
    return float((entry_ts - exit_ts).total_seconds()) >= float(seconds)


def _stamp_position(trade: dict[str, Any], policy: PortfolioPolicy) -> dict[str, Any]:
    trade["position_id"] = f"pos:{trade.get('trade_id')}"
    trade["quantity"] = float(policy.fixed_quantity)
    payload = trade.setdefault("payload", {})
    payload["portfolio_policy"] = policy.to_dict()
    payload["position_id"] = trade["position_id"]
    payload["quantity"] = trade["quantity"]
    payload["position_gross_points"] = float(trade.get("gross_points") or 0.0) * trade["quantity"]
    payload["position_net_points"] = float(trade.get("net_points") or 0.0) * trade["quantity"]
    return trade


def arbitrate_trades(
    trades: list[dict[str, Any]],
    policy: PortfolioPolicy | dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply deterministic portfolio constraints to already-simulated trades.

    Returns accepted trades and audit skips. The independent mode preserves the
    input trade ordering and current historical behavior.
    """
    policy = policy if isinstance(policy, PortfolioPolicy) else PortfolioPolicy.from_dict(policy)
    policy.validate()

    if policy.mode == "INDEPENDENT_EVENT":
        return [_stamp_position(dict(trade), policy) for trade in trades], []

    ordered = sorted((dict(t) for t in trades), key=_candidate_key)
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None

    for trade in ordered:
        if previous is not None:
            after, ordering_basis = _entry_after_exit(trade, previous)
            if not after:
                skipped.append({
                    "event_id": trade.get("event_id"),
                    "trade_id": trade.get("trade_id"),
                    "signal_seq": trade.get("signal_seq"),
                    "signal_time": trade.get("signal_time"),
                    "reason": "PORTFOLIO_OVERLAP",
                    "details": {
                        "blocked_by_trade_id": previous.get("trade_id"),
                        "blocked_by_position_id": previous.get("position_id"),
                        "ordering_basis": ordering_basis,
                        "policy": policy.to_dict(),
                    },
                })
                continue
            if not _cooldown_satisfied(trade, previous, int(policy.reentry_cooldown_seconds)):
                skipped.append({
                    "event_id": trade.get("event_id"),
                    "trade_id": trade.get("trade_id"),
                    "signal_seq": trade.get("signal_seq"),
                    "signal_time": trade.get("signal_time"),
                    "reason": "PORTFOLIO_REENTRY_COOLDOWN",
                    "details": {
                        "previous_trade_id": previous.get("trade_id"),
                        "cooldown_seconds": int(policy.reentry_cooldown_seconds),
                        "policy": policy.to_dict(),
                    },
                })
                continue

        trade = _stamp_position(trade, policy)
        accepted.append(trade)
        previous = trade

    return accepted, skipped
