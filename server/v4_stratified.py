from __future__ import annotations

"""Stratified Fabio V4 edge diagnostics.

The handoff requires more than a pooled PF: month, direction, intraday segment
and structural feature regimes must be visible.  This module uses only persisted
causal event features and strict physical outcomes.  Regimes that are not yet
persisted (true volatility/trend/range state) are explicitly reported missing
rather than inferred after the fact.
"""

import json
import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from .v4_multiyear import BO_CHAIN, MR_CHAIN, migrate_multiyear_schema

STRATIFIED_VERSION = "V4.3_STRATIFIED_EDGE"


def _json(text):
    try:
        return json.loads(text or "{}")
    except Exception:
        return {}


def _management_name(strategy: str) -> str:
    return "fixed_1R" if strategy == "MR" else "fixed_2R"


def _control_name(strategy: str) -> str:
    return "fixed_0.75R" if strategy == "MR" else "fixed_1R"


def _management_r(text, name):
    value = (_json(text).get(name) or {}).get("r")
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


def _metrics(rows):
    rr = [x.get("realized_r") for x in rows if x.get("realized_r") is not None]
    return {
        "n": len(rows),
        "avg_r": _avg(rr),
        "total_r": sum(float(x) for x in rr),
        "profit_factor": _profit_factor(rr),
        "win_rate": sum(float(x) > 0 for x in rr) / len(rr) if rr else None,
        "avg_mfe_r": _avg([x.get("mfe_r") for x in rows]),
        "avg_mae_r": _avg([x.get("mae_r") for x in rows]),
        "hit_1r_rate": sum(bool(x.get("hit_1r")) for x in rows) / len(rows) if rows else None,
        "hit_2r_rate": sum(bool(x.get("hit_2r")) for x in rows) / len(rows) if rows else None,
        "hit_3r_rate": sum(bool(x.get("hit_3r")) for x in rows) / len(rows) if rows else None,
        "hit_5r_rate": sum(bool(x.get("hit_5r")) for x in rows) / len(rows) if rows else None,
    }


def _entry_hhmm(text):
    if not text:
        return None
    s = str(text)
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.hour * 60 + dt.minute
        parts = s.split(":")
        return int(parts[0][-2:]) * 60 + int(parts[1])
    except Exception:
        return None


def _time_bucket(text):
    minute = _entry_hhmm(text)
    if minute is None:
        return "UNKNOWN"
    cuts = [
        (8 * 60 + 45, 9 * 60, "08:45-09:00"),
        (9 * 60, 9 * 60 + 30, "09:00-09:30"),
        (9 * 60 + 30, 10 * 60 + 30, "09:30-10:30"),
        (10 * 60 + 30, 11 * 60 + 30, "10:30-11:30"),
        (11 * 60 + 30, 13 * 60 + 46, "11:30-13:45"),
    ]
    for lo, hi, name in cuts:
        if lo <= minute < hi:
            return name
    return "OUTSIDE_DETECTION_WINDOW"


def _quantiles(values):
    vals = sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not vals:
        return None
    def q(p):
        if len(vals) == 1:
            return vals[0]
        pos = (len(vals) - 1) * p
        lo = int(math.floor(pos)); hi = int(math.ceil(pos))
        if lo == hi:
            return vals[lo]
        f = pos - lo
        return vals[lo] * (1 - f) + vals[hi] * f
    return [q(.25), q(.50), q(.75)]


def _quartile(value, cuts):
    if value is None or cuts is None:
        return "MISSING"
    v = float(value)
    if v <= cuts[0]: return "Q1"
    if v <= cuts[1]: return "Q2"
    if v <= cuts[2]: return "Q3"
    return "Q4"


def _group(rows, key_fn):
    groups = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row))].append(row)
    return {k: _metrics(v) for k, v in sorted(groups.items())}


def _strict_rows(con, years=None):
    migrate_multiyear_schema(con)
    where = ["s.event_id=e.event_id"]
    args: list[Any] = []
    if years:
        marks = ",".join("?" for _ in years)
        where.append(f"s.year IN ({marks})")
        args.extend(int(x) for x in years)
    rows = con.execute(
        """SELECT s.*,e.features_json,e.value_width,e.source_file
           FROM strict_trade_outcomes s JOIN events e ON """ + " AND ".join(where) +
        " ORDER BY s.trading_date,s.entry_seq",
        args,
    ).fetchall()
    out = []
    for r in rows:
        x = dict(r)
        x["features"] = _json(x.get("features_json"))
        x["realized_r"] = _management_r(x.get("management_json"), _management_name(x["strategy"]))
        out.append(x)
    return out


def strict_stratified_summary(con, years=None):
    rows = _strict_rows(con, years)
    result = {
        "version": STRATIFIED_VERSION,
        "years": sorted({int(x["year"]) for x in rows}),
        "detection_session": "DAY_SESSION_08:45-13:45",
        "strategies": {},
        "unavailable_regimes": {
            "volatility_regime": "NOT_PERSISTED_IN_V4_EVENT_SCHEMA",
            "trend_regime": "NOT_PERSISTED_IN_V4_EVENT_SCHEMA",
            "range_regime": "NOT_PERSISTED_IN_V4_EVENT_SCHEMA",
            "night_detection": "CURRENT_V4_SCANNER_DETECTION_WINDOW_IS_DAY_SESSION_ONLY",
        },
    }
    for strategy in ("MR", "BO"):
        sub = [x for x in rows if x["strategy"] == strategy]
        vw_cuts = _quantiles([x.get("value_width") for x in sub])
        exc_cuts = _quantiles([x["features"].get("excursion_pct_value") for x in sub])
        lvn_cuts = _quantiles([x["features"].get("audit_lvn_depth") for x in sub])
        for x in sub:
            x["value_width_q"] = _quartile(x.get("value_width"), vw_cuts)
            x["excursion_q"] = _quartile(x["features"].get("excursion_pct_value"), exc_cuts)
            x["lvn_depth_q"] = _quartile(x["features"].get("audit_lvn_depth"), lvn_cuts)
        result["strategies"][strategy] = {
            "overall": _metrics(sub),
            "by_month": _group(sub, lambda x: str(x.get("trading_date") or "")[:7]),
            "by_direction": _group(sub, lambda x: x.get("direction") or "UNKNOWN"),
            "by_intraday_time": _group(sub, lambda x: _time_bucket(x.get("entry_time"))),
            "by_auction_side": _group(sub, lambda x: x["features"].get("auction_side") or "MISSING"),
            "by_value_width_quartile": _group(sub, lambda x: x["value_width_q"]),
            "by_excursion_quartile": _group(sub, lambda x: x["excursion_q"]),
            "by_lvn_depth_quartile": _group(sub, lambda x: x["lvn_depth_q"]),
            "quantile_cuts": {
                "value_width": vw_cuts,
                "excursion_pct_value": exc_cuts,
                "audit_lvn_depth": lvn_cuts,
            },
        }
    return result


def monthly_node_consistency(con, years=None, min_month_n: int = 20):
    """Cross-month consistency for every research gate inside relaxed universe."""
    where = ["json_extract(e.features_json,'$.terminal_signal')=1"]
    args: list[Any] = []
    if years:
        marks = ",".join("?" for _ in years)
        where.append(f"e.year IN ({marks})")
        args.extend(int(x) for x in years)
    rows = [dict(r) for r in con.execute(
        """SELECT e.event_id,e.strategy,e.trading_date,o.management_json
           FROM events e JOIN opportunity_outcomes o ON o.event_id=e.event_id
           WHERE """ + " AND ".join(where), args
    ).fetchall()]
    ids = [x["event_id"] for x in rows]
    meta = defaultdict(dict)
    for start in range(0, len(ids), 800):
        chunk = ids[start:start + 800]
        if not chunk:
            continue
        marks = ",".join("?" for _ in chunk)
        for r in con.execute(
            f"SELECT event_id,node_id,answer FROM node_instances WHERE event_id IN ({marks})", chunk
        ).fetchall():
            meta[r["event_id"]][r["node_id"]] = bool(r["answer"])
    for x in rows:
        x["month"] = str(x["trading_date"])[:7]
        x["control_r"] = _management_r(x.get("management_json"), _control_name(x["strategy"]))

    output = {"version": STRATIFIED_VERSION, "min_month_n": int(min_month_n), "nodes": []}
    for strategy, chain in (("MR", MR_CHAIN), ("BO", BO_CHAIN)):
        for node in chain:
            months = []
            for month in sorted({x["month"] for x in rows if x["strategy"] == strategy}):
                sub = [x for x in rows if x["strategy"] == strategy and x["month"] == month and node in meta[x["event_id"]]]
                if not sub:
                    continue
                passed = [x for x in sub if meta[x["event_id"]][node]]
                failed = [x for x in sub if not meta[x["event_id"]][node]]
                pa = _avg([x.get("control_r") for x in passed])
                fa = _avg([x.get("control_r") for x in failed])
                delta = pa - fa if pa is not None and fa is not None else None
                months.append({"month": month, "n": len(sub), "pass_n": len(passed), "fail_n": len(failed), "delta_control_avg_r": delta})
            sufficient = [m for m in months if m["n"] >= min_month_n and m["delta_control_avg_r"] is not None]
            positive = sum(m["delta_control_avg_r"] > .05 for m in sufficient)
            negative = sum(m["delta_control_avg_r"] < -.05 for m in sufficient)
            neutral = len(sufficient) - positive - negative
            output["nodes"].append({
                "strategy": strategy,
                "node_id": node,
                "months": months,
                "sufficient_months": len(sufficient),
                "positive_months": positive,
                "negative_months": negative,
                "neutral_months": neutral,
                "weighted_delta_control_avg_r": (
                    sum(m["delta_control_avg_r"] * m["n"] for m in sufficient) / sum(m["n"] for m in sufficient)
                    if sufficient else None
                ),
                "cross_month_sign_consistent": bool(sufficient) and not (positive and negative),
            })
    return output


def stratified_edge_report(con, years=None):
    return {
        "version": STRATIFIED_VERSION,
        "strict_strategy": strict_stratified_summary(con, years),
        "node_month_consistency": monthly_node_consistency(con, years),
    }


__all__ = [
    "STRATIFIED_VERSION",
    "strict_stratified_summary",
    "monthly_node_consistency",
    "stratified_edge_report",
]
