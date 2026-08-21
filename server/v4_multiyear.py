from __future__ import annotations

"""Multi-year / strict-execution diagnostics for Fabio Decision Gym V4.

The reverse-node audit deliberately uses a relaxed terminal opportunity anchor.
That is correct for causal gate research, but it is NOT the same thing as the
actual strict strategy entry (especially BO, whose strict entry waits for
Response confirmation).

This module therefore keeps two evidence layers separate:

1. relaxed opportunity outcomes -> node/gate research;
2. strict entry outcomes          -> strategy / production diagnostics.

No function in this module changes raw Tick order.  Physical outcomes always
follow the immutable `_seq` created before filtering.
"""

import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .engine import connect
from .v4_audit import management_suite
from .v4_audit_final import BO_CHAIN, MR_CHAIN, PARENTS
from .v4_replay_final import read_tick_path
from .v4_research_release import migrate_release_schema

MULTIYEAR_VERSION = "V4.3_MULTIYEAR_EDGE"
STRICT_OUTCOME_VERSION = "V4.3_STRICT_PHYSICAL"
PRODUCTION_GATE_VERSION = "V4.3_CONSERVATIVE_GATE"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(text, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(text or "")
    except Exception:
        return default


def _avg(values):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return sum(vals) / len(vals) if vals else None


def _median(values):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return statistics.median(vals) if vals else None


def _quantile(values, q: float):
    vals = sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * float(q)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    frac = pos - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def _management_r(text: str | None, name: str):
    value = (_json(text).get(name) or {}).get("r")
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def migrate_multiyear_schema(con) -> None:
    migrate_release_schema(con)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS strict_trade_outcomes(
          event_id TEXT PRIMARY KEY,
          year INTEGER,
          trading_date TEXT,
          contract TEXT,
          strategy TEXT,
          direction TEXT,
          entry_seq INTEGER,
          entry_time TEXT,
          entry_price REAL,
          stop REAL,
          risk_points REAL,
          mfe_points REAL,
          mae_points REAL,
          mfe_r REAL,
          mae_r REAL,
          hit_1r INTEGER,
          hit_2r INTEGER,
          hit_3r INTEGER,
          hit_5r INTEGER,
          hit_stop INTEGER,
          first_hit_1r INTEGER,
          first_hit_2r INTEGER,
          first_hit_3r INTEGER,
          first_hit_5r INTEGER,
          management_json TEXT,
          computed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_strict_outcome_year_strategy
          ON strict_trade_outcomes(year,strategy,trading_date);
        """
    )
    now = _utcnow()
    meta = {
        "multiyear_version": MULTIYEAR_VERSION,
        "strict_outcome_version": STRICT_OUTCOME_VERSION,
        "production_gate_version": PRODUCTION_GATE_VERSION,
    }
    for key, value in meta.items():
        con.execute(
            """INSERT INTO schema_meta(key,value,updated_at) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
            (key, value, now),
        )
    con.commit()


def _directional_move(price: float, entry: float, direction: str) -> float:
    return price - entry if direction == "long" else entry - price


def _adverse_move(price: float, entry: float, direction: str) -> float:
    return entry - price if direction == "long" else price - entry


def _strict_hits(path, entry: float, risk: float, direction: str):
    if path.empty or risk <= 0:
        return {}
    mfe = 0.0
    mae = 0.0
    hits = {1: None, 2: None, 3: None, 5: None}
    stop_at = None
    for _, row in path.iterrows():
        p = float(row["price"])
        seq = int(row["_seq"])
        fav = _directional_move(p, entry, direction)
        adv = _adverse_move(p, entry, direction)
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        if stop_at is None and adv >= risk:
            stop_at = seq
        for r in (1, 2, 3, 5):
            if hits[r] is None and fav >= r * risk:
                hits[r] = seq
    def before_stop(r):
        return hits[r] is not None and (stop_at is None or hits[r] < stop_at)
    return {
        "mfe_points": mfe,
        "mae_points": mae,
        "mfe_r": mfe / risk,
        "mae_r": mae / risk,
        "hit_1r": before_stop(1),
        "hit_2r": before_stop(2),
        "hit_3r": before_stop(3),
        "hit_5r": before_stop(5),
        "hit_stop": stop_at is not None,
        "first_hit_1r": hits[1],
        "first_hit_2r": hits[2],
        "first_hit_3r": hits[3],
        "first_hit_5r": hits[5],
    }


def compute_strict_outcomes(
    db: Path,
    root: Path,
    years=None,
    max_after_days: int = 1,
    progress=None,
) -> int:
    """Compute outcomes from the REAL strict strategy entry, not audit anchor."""
    con = connect(db)
    migrate_multiyear_schema(con)
    where = ["result='ENTRY'", "entry_seq IS NOT NULL", "entry_price IS NOT NULL", "stop IS NOT NULL"]
    args: list[Any] = []
    if years:
        marks = ",".join("?" for _ in years)
        where.append(f"year IN ({marks})")
        args.extend(int(x) for x in years)
    rows = con.execute(
        "SELECT * FROM events WHERE " + " AND ".join(where) +
        " ORDER BY source_file,trading_date,contract,entry_seq",
        args,
    ).fetchall()
    events = [dict(r) for r in rows]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        groups[(e["source_file"], e["trading_date"], e["contract"])].append(e)
    now = _utcnow()
    done = 0
    total = len(events)
    for gi, items in enumerate(groups.values(), 1):
        min_seq = min(int(e["entry_seq"]) for e in items)
        shared = read_tick_path(root, items[0], min_seq, max_after_days)
        for e in items:
            seq = int(e["entry_seq"])
            entry = float(e["entry_price"])
            stop = float(e["stop"])
            risk = abs(entry - stop)
            if risk <= 0:
                continue
            path = shared.loc[shared["_seq"] >= seq].reset_index(drop=True) if len(shared) else shared
            hits = _strict_hits(path, entry, risk, e["direction"])
            suite = management_suite(path, entry, risk, e["direction"])
            con.execute(
                """INSERT OR REPLACE INTO strict_trade_outcomes(
                event_id,year,trading_date,contract,strategy,direction,entry_seq,entry_time,entry_price,stop,risk_points,
                mfe_points,mae_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,hit_5r,hit_stop,
                first_hit_1r,first_hit_2r,first_hit_3r,first_hit_5r,management_json,computed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    e["event_id"], e["year"], e["trading_date"], e["contract"], e["strategy"], e["direction"],
                    seq, e["entry_time"], entry, stop, risk,
                    hits.get("mfe_points"), hits.get("mae_points"), hits.get("mfe_r"), hits.get("mae_r"),
                    int(bool(hits.get("hit_1r"))), int(bool(hits.get("hit_2r"))), int(bool(hits.get("hit_3r"))),
                    int(bool(hits.get("hit_5r"))), int(bool(hits.get("hit_stop"))),
                    hits.get("first_hit_1r"), hits.get("first_hit_2r"), hits.get("first_hit_3r"), hits.get("first_hit_5r"),
                    json.dumps(suite, ensure_ascii=False), now,
                ),
            )
            done += 1
            if progress:
                progress({"phase": "strict_outcomes", "done": done, "total": total, "group": gi, "groups": len(groups), "event_id": e["event_id"]})
        con.commit()
    con.close()
    return done


def _strict_rows(con, years=None, strategy: str | None = None):
    migrate_multiyear_schema(con)
    where = []
    args: list[Any] = []
    if years:
        marks = ",".join("?" for _ in years)
        where.append(f"year IN ({marks})")
        args.extend(int(x) for x in years)
    if strategy:
        where.append("strategy=?")
        args.append(strategy)
    sql = "SELECT * FROM strict_trade_outcomes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY trading_date,entry_seq"
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def _profit_factor(values):
    pos = sum(x for x in values if x > 0)
    neg = abs(sum(x for x in values if x < 0))
    return pos / neg if neg > 0 else None


def _max_drawdown(values):
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in values:
        equity += float(x)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _strict_group_summary(rows, strategy: str):
    management_name = "fixed_1R" if strategy == "MR" else "fixed_2R"
    realized = [_management_r(r.get("management_json"), management_name) for r in rows]
    realized = [x for x in realized if x is not None]
    winner_points = []
    for row in rows:
        rr = _management_r(row.get("management_json"), management_name)
        if rr is not None and rr > 0 and row.get("risk_points") is not None:
            winner_points.append(rr * float(row["risk_points"]))
    mfe = [r.get("mfe_r") for r in rows]
    mae = [r.get("mae_r") for r in rows]
    target_key = "hit_1r" if strategy == "MR" else "hit_2r"
    return {
        "n": len(rows),
        "management_basis": management_name,
        "avg_r": _avg(realized),
        "median_r": _median(realized),
        "total_r": sum(realized),
        "win_rate": sum(x > 0 for x in realized) / len(realized) if realized else None,
        "profit_factor": _profit_factor(realized),
        "max_drawdown_r": _max_drawdown(realized),
        "target_hit_rate": sum(bool(r.get(target_key)) for r in rows) / len(rows) if rows else None,
        "hit_1r_rate": sum(bool(r.get("hit_1r")) for r in rows) / len(rows) if rows else None,
        "hit_2r_rate": sum(bool(r.get("hit_2r")) for r in rows) / len(rows) if rows else None,
        "hit_3r_rate": sum(bool(r.get("hit_3r")) for r in rows) / len(rows) if rows else None,
        "hit_5r_rate": sum(bool(r.get("hit_5r")) for r in rows) / len(rows) if rows else None,
        "avg_mfe_r": _avg(mfe),
        "median_mfe_r": _median(mfe),
        "p90_mfe_r": _quantile(mfe, .90),
        "p95_mfe_r": _quantile(mfe, .95),
        "max_mfe_r": max((float(x) for x in mfe if x is not None), default=None),
        "avg_mae_r": _avg(mae),
        "avg_winner_points": _avg(winner_points),
    }


def strict_trade_summary(con, years=None):
    """Actual strict-entry strategy summary, separated by year and combined."""
    rows = _strict_rows(con, years)
    result: dict[str, Any] = {"strict_outcome_version": STRICT_OUTCOME_VERSION, "years": {}, "combined": {}}
    year_values = sorted({int(r["year"]) for r in rows})
    for year in year_values:
        result["years"][str(year)] = {}
        for strategy in ("MR", "BO"):
            sub = [r for r in rows if int(r["year"]) == year and r["strategy"] == strategy]
            result["years"][str(year)][strategy] = _strict_group_summary(sub, strategy)
    for strategy in ("MR", "BO"):
        result["combined"][strategy] = _strict_group_summary([r for r in rows if r["strategy"] == strategy], strategy)
    return result


def right_tail_summary(con, years=None):
    """Right-tail evidence for both relaxed research opportunities and strict entries."""
    migrate_multiyear_schema(con)
    args: list[Any] = []
    where = ["json_extract(e.features_json,'$.terminal_signal')=1"]
    if years:
        marks = ",".join("?" for _ in years)
        where.append(f"e.year IN ({marks})")
        args.extend(int(x) for x in years)
    relaxed = [dict(r) for r in con.execute(
        """SELECT e.year,e.strategy,o.mfe_r,o.mae_r,o.hit_1r,o.hit_2r,o.hit_3r
           FROM events e JOIN opportunity_outcomes o ON o.event_id=e.event_id WHERE """ + " AND ".join(where),
        args,
    ).fetchall()]
    strict = _strict_rows(con, years)

    def summarize(rows, has_hit5: bool):
        out = {}
        for strategy in ("MR", "BO"):
            sub = [r for r in rows if r["strategy"] == strategy]
            mfe = [r.get("mfe_r") for r in sub]
            out[strategy] = {
                "n": len(sub),
                "p90_mfe_r": _quantile(mfe, .90),
                "p95_mfe_r": _quantile(mfe, .95),
                "max_mfe_r": max((float(x) for x in mfe if x is not None), default=None),
                "hit_2r_rate": sum(bool(r.get("hit_2r")) for r in sub) / len(sub) if sub else None,
                "hit_3r_rate": sum(bool(r.get("hit_3r")) for r in sub) / len(sub) if sub else None,
                "hit_5r_rate": (
                    sum(bool(r.get("hit_5r")) for r in sub) / len(sub)
                    if has_hit5 and sub else
                    sum(float(r.get("mfe_r") or 0) >= 5.0 for r in sub) / len(sub) if sub else None
                ),
            }
        return out

    return {
        "version": MULTIYEAR_VERSION,
        "relaxed_terminal_opportunities": summarize(relaxed, False),
        "strict_entries": summarize(strict, True),
        "warning": "Relaxed opportunity MFE>=5R is descriptive only; strict hit_5R uses physical first-hit ordering versus stop.",
    }


def _control_name(strategy: str) -> str:
    return "fixed_0.75R" if strategy == "MR" else "fixed_1R"


def multi_year_edge_map(con, years=None):
    """Cross-year node map using relaxed terminal opportunities.

    Classification is intentionally conservative.  A node cannot become CORE
    from one sufficient year alone.  Mixed-sign yearly delta-R is explicitly
    REGIME_DEPENDENT rather than averaged away.
    """
    migrate_multiyear_schema(con)
    args: list[Any] = []
    where = ["json_extract(e.features_json,'$.terminal_signal')=1"]
    if years:
        marks = ",".join("?" for _ in years)
        where.append(f"e.year IN ({marks})")
        args.extend(int(x) for x in years)
    events = [dict(r) for r in con.execute(
        """SELECT e.event_id,e.year,e.strategy,o.hit_1r,o.hit_2r,o.hit_3r,o.hit_stop,o.mfe_r,o.mae_r,o.management_json
           FROM events e JOIN opportunity_outcomes o ON o.event_id=e.event_id WHERE """ + " AND ".join(where),
        args,
    ).fetchall()]
    ids = [r["event_id"] for r in events]
    meta: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    if ids:
        for start in range(0, len(ids), 800):
            chunk = ids[start:start + 800]
            marks = ",".join("?" for _ in chunk)
            for r in con.execute(
                f"SELECT event_id,node_id,answer,decision_seq FROM node_instances WHERE event_id IN ({marks})", chunk
            ).fetchall():
                meta[r["event_id"]][r["node_id"]] = {"answer": bool(r["answer"]), "decision_seq": r["decision_seq"]}
    for row in events:
        row["control_r"] = _management_r(row.get("management_json"), _control_name(row["strategy"]))

    result = {"version": MULTIYEAR_VERSION, "years": sorted({int(r["year"]) for r in events}), "nodes": []}
    for strategy, chain in (("MR", MR_CHAIN), ("BO", BO_CHAIN)):
        for node in chain:
            year_rows = []
            for year in result["years"]:
                sub = [r for r in events if r["strategy"] == strategy and int(r["year"]) == year and node in meta[r["event_id"]]]
                if not sub:
                    continue
                passed = [r for r in sub if meta[r["event_id"]][node]["answer"]]
                failed = [r for r in sub if not meta[r["event_id"]][node]["answer"]]
                pass_avg = _avg([r.get("control_r") for r in passed])
                fail_avg = _avg([r.get("control_r") for r in failed])
                delta = pass_avg - fail_avg if pass_avg is not None and fail_avg is not None else None
                bigw = [r for r in sub if bool(r.get("hit_2r"))]
                big3 = [r for r in sub if bool(r.get("hit_3r"))]
                bigl = [r for r in sub if bool(r.get("hit_stop")) and not bool(r.get("hit_1r"))]
                bw_rej = sum(not meta[r["event_id"]][node]["answer"] for r in bigw) / len(bigw) if bigw else 0.0
                b3_rej = sum(not meta[r["event_id"]][node]["answer"] for r in big3) / len(big3) if big3 else 0.0
                bl_rej = sum(not meta[r["event_id"]][node]["answer"] for r in bigl) / len(bigl) if bigl else 0.0
                rejected_total_r = sum((r.get("control_r") or 0.0) for r in failed)
                year_rows.append({
                    "year": year,
                    "n": len(sub),
                    "pass_n": len(passed),
                    "fail_n": len(failed),
                    "pass_avg_control_r": pass_avg,
                    "fail_avg_control_r": fail_avg,
                    "delta_control_avg_r": delta,
                    "big_loss_rejection_rate": bl_rej,
                    "big_win_2r_rejection_rate": bw_rej,
                    "big_win_3r_rejection_rate": b3_rej,
                    "rejected_total_r": rejected_total_r,
                })
            sufficient = [x for x in year_rows if x["n"] >= 50 and x["delta_control_avg_r"] is not None]
            signs = [1 if x["delta_control_avg_r"] > .05 else -1 if x["delta_control_avg_r"] < -.05 else 0 for x in sufficient]
            weighted_delta = (
                sum(x["delta_control_avg_r"] * x["n"] for x in sufficient) / sum(x["n"] for x in sufficient)
                if sufficient else None
            )
            parent = PARENTS.get(node)
            same = den = 0
            if parent:
                for r in events:
                    if r["strategy"] != strategy or node not in meta[r["event_id"]] or parent not in meta[r["event_id"]]:
                        continue
                    a = meta[r["event_id"]][node].get("decision_seq")
                    b = meta[r["event_id"]][parent].get("decision_seq")
                    if a is not None and b is not None:
                        den += 1
                        same += int(a == b)
            same_rate = same / den if den else None
            if len(sufficient) < 2:
                classification = "INSUFFICIENT"
            elif any(s > 0 for s in signs) and any(s < 0 for s in signs):
                classification = "REGIME_DEPENDENT"
            else:
                avg_bl = _avg([x["big_loss_rejection_rate"] for x in sufficient]) or 0.0
                avg_bw = _avg([x["big_win_2r_rejection_rate"] for x in sufficient]) or 0.0
                if same_rate is not None and same_rate >= .80 and weighted_delta is not None and abs(weighted_delta) < .05:
                    classification = "REDUNDANT"
                elif weighted_delta is not None and weighted_delta <= -.10:
                    classification = "HARMFUL"
                elif all(s >= 0 for s in signs) and weighted_delta is not None and weighted_delta >= .10 and avg_bl - avg_bw >= .10:
                    classification = "CORE"
                else:
                    classification = "OPTIONAL"
            result["nodes"].append({
                "strategy": strategy,
                "node_id": node,
                "classification": classification,
                "sufficient_years": len(sufficient),
                "weighted_delta_control_avg_r": weighted_delta,
                "same_seq_parent_rate": same_rate,
                "per_year": year_rows,
                "rule": ">=2 years with n>=50 required for cross-year classification; mixed material signs => REGIME_DEPENDENT",
            })
    return result


def _bootstrap_ci(values, reps=2000, seed=20260821):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if len(vals) < 20:
        return None
    rng = random.Random(seed)
    samples = []
    for _ in range(reps):
        samples.append(sum(vals[rng.randrange(len(vals))] for _ in range(len(vals))) / len(vals))
    samples.sort()
    return [samples[int(.025 * (len(samples) - 1))], samples[int(.975 * (len(samples) - 1))]]


def production_gate(con, years=None):
    """Conservative production-readiness view from strict physical entries.

    The user-defined practical targets are kept literal:
      MR ~1R, BO ~2R, average winner points ideally >= ~10% ATR.

    ATR timeframe/reference was never specified in the source requirements, so
    this code reports the observed winner points but deliberately leaves the ATR
    gate PENDING instead of inventing a timeframe.
    """
    rows = _strict_rows(con, years)
    output = {"version": PRODUCTION_GATE_VERSION, "years": sorted({int(r["year"]) for r in rows}), "strategies": {}}
    for strategy in ("MR", "BO"):
        sub = [r for r in rows if r["strategy"] == strategy]
        target_r = 1.0 if strategy == "MR" else 2.0
        mgmt = "fixed_1R" if strategy == "MR" else "fixed_2R"
        realized = [_management_r(r.get("management_json"), mgmt) for r in sub]
        realized = [x for x in realized if x is not None]
        per_year = {}
        for year in output["years"]:
            yr = [r for r in sub if int(r["year"]) == year]
            rr = [_management_r(r.get("management_json"), mgmt) for r in yr]
            rr = [x for x in rr if x is not None]
            per_year[str(year)] = {"n": len(yr), "avg_r": _avg(rr), "total_r": sum(rr), "profit_factor": _profit_factor(rr)}
        positive_years = [x for x in per_year.values() if x["n"] and x["avg_r"] is not None and x["avg_r"] > 0]
        negative_years = [x for x in per_year.values() if x["n"] and x["avg_r"] is not None and x["avg_r"] <= 0]
        winner_points = []
        for r in sub:
            rr = _management_r(r.get("management_json"), mgmt)
            if rr is not None and rr > 0:
                winner_points.append(rr * float(r["risk_points"]))
        ci = _bootstrap_ci(realized, seed=20260821 + (1 if strategy == "MR" else 2))
        reward_gate = bool(realized) and _avg(realized) is not None and _avg(realized) > 0
        cross_year_gate = len(positive_years) >= 2 and not negative_years
        ci_gate = ci is not None and ci[0] > 0
        required_pending = [
            "ATR_REFERENCE_UNSPECIFIED",
            "COST_STRESS_NOT_YET_RUN_ON_STRICT_ENTRIES",
            "LATENCY_STRESS_NOT_YET_RUN_ON_STRICT_ENTRIES",
            "DRAWDOWN_LIMIT_POLICY_UNSPECIFIED",
            "CONCENTRATION_LIMIT_POLICY_UNSPECIFIED",
        ]
        output["strategies"][strategy] = {
            "n": len(sub),
            "practical_target_r": target_r,
            "management_basis": mgmt,
            "avg_r": _avg(realized),
            "total_r": sum(realized),
            "profit_factor": _profit_factor(realized),
            "avg_winner_points": _avg(winner_points),
            "bootstrap_mean_r_ci95": ci,
            "max_drawdown_r": _max_drawdown(realized),
            "per_year": per_year,
            "gates": {
                "positive_expectancy_at_practical_target": "PASS" if reward_gate else "FAIL",
                "cross_year_positive_consistency": "PASS" if cross_year_gate else "FAIL",
                "mean_r_ci_above_zero": "PASS" if ci_gate else ("INSUFFICIENT" if ci is None else "FAIL"),
                "avg_winner_points_ge_10pct_atr": "PENDING_ATR_REFERENCE",
                "cost_robustness": "PENDING",
                "latency_robustness": "PENDING",
                "drawdown_limit": "PENDING_POLICY",
                "concentration_limit": "PENDING_POLICY",
            },
            "pending_requirements": required_pending,
            "live_approved": False,
            "status": "NOT_LIVE_APPROVED",
        }
    output["policy_note"] = (
        "No strategy can be marked live-approved while ATR reference, cost stress, latency stress, "
        "drawdown limit and concentration limit remain unspecified/unmeasured."
    )
    return output


__all__ = [
    "MULTIYEAR_VERSION",
    "STRICT_OUTCOME_VERSION",
    "PRODUCTION_GATE_VERSION",
    "migrate_multiyear_schema",
    "compute_strict_outcomes",
    "strict_trade_summary",
    "right_tail_summary",
    "multi_year_edge_map",
    "production_gate",
]
