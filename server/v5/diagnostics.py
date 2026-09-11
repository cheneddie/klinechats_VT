from __future__ import annotations

import json
from typing import Any, Iterable

VALID_EVAL_STATES = {"EVALUATED", "NOT_REACHED", "NOT_APPLICABLE", "TERMINAL"}


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def causal_diagnostic(
    event: dict[str, Any],
    nodes: Iterable[dict[str, Any]],
    node_chain: Iterable[str],
) -> dict[str, Any]:
    """Describe only facts that were available at/through the strategy decision.

    This function never uses PnL, MFE, MAE, or later path data. It is safe to attach
    to live/replay decisions without leaking ex-post information.
    """
    by_id = {str(n.get("node_id")): dict(n) for n in nodes}
    first_failed = None
    invalid_state = None
    trace = []
    for node_id in node_chain:
        n = by_id.get(str(node_id))
        if not n:
            trace.append({"node_id": node_id, "state": "MISSING", "answer": None})
            if invalid_state is None:
                invalid_state = f"MISSING_NODE:{node_id}"
            continue
        state = str(n.get("evaluation_state") or "EVALUATED")
        answer = _as_bool(n.get("answer"))
        trace.append({
            "node_id": node_id,
            "state": state,
            "answer": answer,
            "decision_seq": n.get("decision_seq"),
            "decision_time": n.get("decision_time"),
            "reason_code": n.get("reason_code"),
            "blocker_node_id": n.get("blocker_node_id"),
        })
        if state not in VALID_EVAL_STATES and invalid_state is None:
            invalid_state = f"INVALID_STATE:{node_id}:{state}"
        if state == "EVALUATED" and answer is False and first_failed is None:
            first_failed = node_id
        if state == "NOT_REACHED" and first_failed is None:
            first_failed = n.get("blocker_node_id") or node_id
    strict_entry = bool(event.get("entry_seq") is not None and event.get("entry_price") is not None)
    valid = invalid_state is None and first_failed is None and strict_entry
    if valid:
        reason = "STRICT_CHAIN_VALID"
    elif invalid_state:
        reason = invalid_state
    elif first_failed:
        reason = f"FIRST_FAILED_NODE:{first_failed}"
    else:
        reason = "NO_STRICT_ENTRY"
    return {
        "causal_valid": valid,
        "causal_reason": reason,
        "first_failed_node": first_failed,
        "strict_entry": strict_entry,
        "trace": trace,
    }


def post_trade_diagnostic(trade: dict[str, Any]) -> dict[str, Any]:
    """Ex-post attribution for research/review only.

    The returned code must never be fed back into historical signal labels. It can
    explain an outcome after the trade has completed, but it is not causal evidence.
    """
    net_r = float(trade.get("net_r") or 0.0)
    gross_r = float(trade.get("gross_r") or 0.0)
    mfe_r = float(trade.get("mfe_r") or 0.0)
    mae_r = float(trade.get("mae_r") or 0.0)
    exit_reason = str(trade.get("exit_reason") or "UNKNOWN")
    commission = float(trade.get("commission_points") or 0.0)
    slippage = float(trade.get("slippage_points") or 0.0)
    risk = float(trade.get("risk_points") or 0.0)

    if gross_r > 0 and net_r <= 0 and risk > 0 and (commission + slippage) > 0:
        code = "COST_SENSITIVE"
    elif exit_reason == "TARGET":
        code = "TARGET_HIT"
    elif exit_reason == "STOP" and mfe_r < 0.25:
        code = "NO_FOLLOW_THROUGH"
    elif exit_reason == "STOP":
        code = "VALID_LOSS"
    elif exit_reason == "TIME" and mfe_r >= 1.0 and gross_r < 0.5:
        code = "EXIT_TOO_EARLY"
    elif exit_reason == "TIME":
        code = "TIME_EXIT"
    elif exit_reason == "END_OF_DATA":
        code = "END_OF_DATA"
    elif net_r < 0:
        code = "VALID_LOSS"
    else:
        code = "VALID_WIN"

    flags = []
    if slippage > 0 and gross_r > net_r:
        flags.append("SLIPPAGE_SENSITIVE")
    if mae_r >= 1.0 and net_r > 0:
        flags.append("DEEP_ADVERSE_EXCURSION")
    if mfe_r >= 2.0 and net_r < 0.5:
        flags.append("LOW_CAPTURE")

    return {
        "post_trade_reason": code,
        "research_only": True,
        "flags": flags,
        "details": {
            "net_r": net_r,
            "gross_r": gross_r,
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "exit_reason": exit_reason,
        },
    }


def infer_regime(event: dict[str, Any]) -> dict[str, Any]:
    features = event.get("features")
    if features is None:
        try:
            features = json.loads(event.get("features_json") or "{}")
        except Exception:
            features = {}
    features = features if isinstance(features, dict) else {}
    keys = (
        "volatility_regime",
        "market_regime",
        "trend_regime",
        "auction_side",
        "time_bucket",
        "session",
    )
    out = {k: features.get(k) for k in keys if features.get(k) is not None}
    if event.get("strategy") is not None:
        out["strategy_family"] = event.get("strategy")
    if event.get("direction") is not None:
        out["direction"] = event.get("direction")
    return out
