from __future__ import annotations

"""Execution robustness diagnostics for actual strict Fabio V4 entries.

This module does not invent missing research policy.  It computes objective
0/1/2/3-point round-trip cost stress and period concentration from strict-entry
outcomes.  Latency remains explicitly pending until an execution-delay model is
frozen (delay grid, structural-stop handling, session handling and fill rule).
"""

import json
import math
from collections import defaultdict
from typing import Any

from .v4_multiyear import migrate_multiyear_schema

EXECUTION_STRESS_VERSION = "V4.3_EXECUTION_STRESS"


def _json(text):
    try:
        return json.loads(text or "{}")
    except Exception:
        return {}


def _management_name(strategy: str) -> str:
    return "fixed_1R" if strategy == "MR" else "fixed_2R"


def _gross_r(row):
    value = (_json(row.get("management_json")).get(_management_name(row["strategy"])) or {}).get("r")
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def _avg(values):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return sum(vals) / len(vals) if vals else None


def _profit_factor(values):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    pos = sum(x for x in vals if x > 0)
    neg = abs(sum(x for x in vals if x < 0))
    return pos / neg if neg > 0 else None


def _max_drawdown(values):
    equity = peak = max_dd = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _rows(con, years=None):
    migrate_multiyear_schema(con)
    where = []
    args: list[Any] = []
    if years:
        marks = ",".join("?" for _ in years)
        where.append(f"year IN ({marks})")
        args.extend(int(x) for x in years)
    sql = "SELECT * FROM strict_trade_outcomes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY trading_date,entry_seq"
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def _net_values(rows, cost_points: float):
    values = []
    for row in rows:
        gross = _gross_r(row)
        risk = row.get("risk_points")
        if gross is None or risk is None or float(risk) <= 0:
            continue
        # round-trip cost is expressed directly in index points and translated to R
        values.append(float(gross) - float(cost_points) / float(risk))
    return values


def _cost_block(rows, cost_points):
    vals = _net_values(rows, cost_points)
    return {
        "cost_points_round_trip": float(cost_points),
        "n": len(vals),
        "avg_net_r": _avg(vals),
        "total_net_r": sum(vals),
        "win_rate": sum(x > 0 for x in vals) / len(vals) if vals else None,
        "profit_factor": _profit_factor(vals),
        "max_drawdown_r": _max_drawdown(vals),
    }


def _period_concentration(rows, period_len: int):
    totals = defaultdict(float)
    positive_trade_r = 0.0
    negative_trade_r = 0.0
    for row in rows:
        gross = _gross_r(row)
        if gross is None:
            continue
        key = str(row.get("trading_date") or "")[:period_len]
        totals[key] += gross
        if gross > 0:
            positive_trade_r += gross
        elif gross < 0:
            negative_trade_r += gross
    ordered = [{"period": k, "total_r": totals[k]} for k in sorted(totals)]
    positive_periods = [max(0.0, x["total_r"]) for x in ordered]
    positive_period_total = sum(positive_periods)
    largest_positive = max(positive_periods, default=0.0)
    return {
        "periods": ordered,
        "positive_periods": sum(x["total_r"] > 0 for x in ordered),
        "negative_or_flat_periods": sum(x["total_r"] <= 0 for x in ordered),
        "largest_positive_period_share": largest_positive / positive_period_total if positive_period_total > 0 else None,
        "positive_trade_r": positive_trade_r,
        "negative_trade_r": negative_trade_r,
    }


def execution_stress_summary(con, years=None, cost_points=(0, 1, 2, 3)):
    rows = _rows(con, years)
    output = {
        "version": EXECUTION_STRESS_VERSION,
        "cost_definition": "round-trip index points subtracted from strict-entry realized R as cost_points/risk_points",
        "latency": {
            "status": "PENDING_FROZEN_SPEC",
            "reason": (
                "The source requirements demand latency robustness but do not freeze delay seconds, delayed-fill rule, "
                "structural-stop handling or session-crossing behavior. No latency PASS/FAIL is invented."
            ),
        },
        "strategies": {},
    }
    for strategy in ("MR", "BO"):
        sub = [r for r in rows if r["strategy"] == strategy]
        per_year = {}
        for year in sorted({int(r["year"]) for r in sub}):
            yr = [r for r in sub if int(r["year"]) == year]
            per_year[str(year)] = {
                "cost_stress": [_cost_block(yr, c) for c in cost_points],
                "monthly_concentration": _period_concentration(yr, 7),
            }
        output["strategies"][strategy] = {
            "n": len(sub),
            "management_basis": _management_name(strategy),
            "cost_stress": [_cost_block(sub, c) for c in cost_points],
            "monthly_concentration": _period_concentration(sub, 7),
            "yearly_concentration": _period_concentration(sub, 4),
            "per_year": per_year,
            "policy": {
                "cost_pass_fail": "PENDING_USER_OR_RESEARCH_COST_THRESHOLD",
                "concentration_pass_fail": "PENDING_CONCENTRATION_LIMIT",
            },
        }
    return output


__all__ = ["EXECUTION_STRESS_VERSION", "execution_stress_summary"]
