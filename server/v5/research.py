from __future__ import annotations

import json
import math
from pathlib import Path

from .registry import NodeRegistry
from .statistics import benjamini_hochberg, trading_day_cluster_bootstrap
from .storage import assert_run_mutable, connect, migrate_event_db, tx

MR_CHAIN = ["AUC_ATTEMPT", "MR_REJECTION", "MR_CLEAR_RECLAIM", "MR_RECLAIM_LEG", "MR_LVN", "MR_PULLBACK", "MR_ENTRY"]
BO_CHAIN = ["AUC_ATTEMPT", "BO_DISPLACEMENT", "BO_ACCEPTANCE", "BO_IMPULSE_LEG", "BO_LVN", "BO_PULLBACK", "BO_RESPONSE", "BO_ENTRY"]


def _avg(values):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return sum(vals) / len(vals) if vals else None


def _pf(values):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    pos = sum(x for x in vals if x > 0)
    neg = abs(sum(x for x in vals if x < 0))
    return pos / neg if neg else (999.0 if pos else None)


def _dataset(con, run_id, strategy):
    events = [
        dict(r)
        for r in con.execute(
            """SELECT e.event_id,e.strategy,e.year,e.trading_date,
                      o.realized_r,o.hit_1r,o.hit_2r,o.hit_3r,o.hit_5r,o.stop_first,o.mfe_r,o.mae_r
               FROM events e
               JOIN opportunity_outcomes o
                 ON o.research_run_id=e.research_run_id
                AND o.event_id=e.event_id
                AND o.basis='terminal'
               WHERE e.research_run_id=? AND e.strategy=?""",
            (run_id, strategy),
        ).fetchall()
    ]
    by_event = {x["event_id"]: x for x in events}
    if not by_event:
        return []
    nodes = con.execute(
        """SELECT n.*
           FROM event_nodes n
           JOIN events e
             ON e.research_run_id=n.research_run_id AND e.event_id=n.event_id
           WHERE n.research_run_id=? AND e.strategy=?""",
        (run_id, strategy),
    ).fetchall()
    for row in nodes:
        n = dict(row)
        event = by_event.get(n["event_id"])
        if event is None:
            continue
        state = n.get("evaluation_state") or "EVALUATED"
        event.setdefault("nodes", {})[n["node_id"]] = {
            "evaluation_state": state,
            "answer": bool(n["answer"]) if state == "EVALUATED" and n.get("answer") is not None else None,
            "decision_seq": n.get("decision_seq"),
            "reason_code": n.get("reason_code"),
            "blocker_node_id": n.get("blocker_node_id"),
        }
    return events


def _classify(role, metric, registry_role):
    if registry_role == "STATE":
        return "STATE"
    n = int(metric.get("universe") or 0)
    yes_n = int(metric.get("yes_n") or 0)
    no_n = int(metric.get("no_n") or 0)
    delta = metric.get("delta_avg_r")
    ret = metric.get("big_winner_retention")
    rej = metric.get("big_loser_rejection")
    same = metric.get("same_seq_parent_rate")
    q = metric.get("q_value")
    lo = metric.get("ci_low")
    hi = metric.get("ci_high")
    if n < 50 or yes_n < 10 or no_n < 10:
        return "INSUFFICIENT"
    if (
        same is not None
        and same >= 0.8
        and abs(delta or 0) < 0.05
        and abs((rej or 0) - (1 - (ret or 1))) < 0.05
    ):
        return "REDUNDANT"
    if q is not None and q <= 0.10 and hi is not None and hi < 0:
        return "HARMFUL"
    if (
        q is not None
        and q <= 0.10
        and lo is not None
        and lo > 0
        and delta is not None
        and delta > 0
        and (rej or 0) >= 0.15
    ):
        return "CORE" if role in {"VALIDATION", "FINAL_HOLDOUT"} else "OPTIONAL"
    return "OPTIONAL"


def reverse_audit(event_db: str | Path, run_id: str, registry: NodeRegistry, *, bootstrap_reps=2000):
    migrate_event_db(event_db)
    assert_run_mutable(event_db, run_id)
    con = connect(event_db)
    try:
        rr = con.execute(
            "SELECT role FROM research_runs WHERE research_run_id=?", (run_id,)
        ).fetchone()
        role = rr["role"] if rr else "DISCOVERY"
        results = []
        for strategy, chain in (("MR", MR_CHAIN), ("BO", BO_CHAIN)):
            data = _dataset(con, run_id, strategy)
            for node_id in chain:
                parent = registry.get(node_id).parent
                eligible = [
                    x
                    for x in data
                    if node_id in x.get("nodes", {})
                    and x["nodes"][node_id].get("evaluation_state") == "EVALUATED"
                ]
                yes = [x for x in eligible if x["nodes"][node_id]["answer"] is True]
                no = [x for x in eligible if x["nodes"][node_id]["answer"] is False]
                yr = [x["realized_r"] for x in yes]
                nr = [x["realized_r"] for x in no]
                delta = (
                    _avg(yr) - _avg(nr)
                    if _avg(yr) is not None and _avg(nr) is not None
                    else None
                )
                big = [x for x in eligible if x.get("hit_2r")]
                losers = [x for x in eligible if x.get("stop_first") and not x.get("hit_1r")]
                ret = (
                    sum(x["nodes"][node_id]["answer"] is True for x in big) / len(big)
                    if big
                    else None
                )
                rej = (
                    sum(x["nodes"][node_id]["answer"] is False for x in losers) / len(losers)
                    if losers
                    else None
                )
                rejected = [float(x.get("realized_r") or 0) for x in no]
                same_vals = []
                if parent:
                    for x in eligible:
                        p = x["nodes"].get(parent)
                        n = x["nodes"].get(node_id)
                        if (
                            p
                            and p.get("evaluation_state") == "EVALUATED"
                            and p.get("decision_seq") is not None
                            and n.get("decision_seq") is not None
                        ):
                            same_vals.append(p["decision_seq"] == n["decision_seq"])

                boot_rows = [
                    {
                        "trading_date": x["trading_date"],
                        "answer": x["nodes"][node_id]["answer"],
                        "realized_r": x["realized_r"],
                    }
                    for x in eligible
                ]
                boot = trading_day_cluster_bootstrap(
                    boot_rows,
                    reps=bootstrap_reps,
                    seed=sum(map(ord, f"{strategy}|{node_id}")),
                )
                metric = {
                    "research_run_id": run_id,
                    "node_id": node_id,
                    "strategy": strategy,
                    "universe": len(eligible),
                    "yes_n": len(yes),
                    "no_n": len(no),
                    "yes_avg_r": _avg(yr),
                    "no_avg_r": _avg(nr),
                    "delta_avg_r": delta,
                    "ci_low": boot["ci_low"],
                    "ci_high": boot["ci_high"],
                    "p_value": boot["p_value"],
                    "q_value": None,
                    "bootstrap_unit": boot["bootstrap_unit"],
                    "bootstrap_reps": boot["bootstrap_reps"],
                    "cluster_count": boot["cluster_count"],
                    "evaluation_universe": "EVALUATED_ONLY",
                    "same_seq_parent_rate": (
                        sum(same_vals) / len(same_vals) if same_vals else None
                    ),
                    "big_winner_retention": ret,
                    "big_loser_rejection": rej,
                    "rejected_total_r": sum(rejected),
                    "rejected_positive_r": sum(x for x in rejected if x > 0),
                    "rejected_negative_r": sum(x for x in rejected if x < 0),
                }
                results.append(metric)

        q_values = benjamini_hochberg([x.get("p_value") for x in results])
        for metric, q in zip(results, q_values):
            metric["q_value"] = q
            metric["classification"] = _classify(
                role, metric, registry.get(metric["node_id"]).role
            )
    finally:
        con.close()

    with tx(event_db) as c:
        for x in results:
            c.execute(
                """INSERT OR REPLACE INTO node_edge_results(
                  research_run_id,node_id,strategy,classification,universe,yes_n,no_n,
                  yes_avg_r,no_avg_r,delta_avg_r,ci_low,ci_high,p_value,q_value,
                  bootstrap_unit,bootstrap_reps,cluster_count,evaluation_universe,
                  same_seq_parent_rate,big_winner_retention,big_loser_rejection,
                  rejected_total_r,rejected_positive_r,rejected_negative_r,details_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    x["research_run_id"], x["node_id"], x["strategy"], x["classification"],
                    x["universe"], x["yes_n"], x["no_n"], x["yes_avg_r"],
                    x["no_avg_r"], x["delta_avg_r"], x["ci_low"], x["ci_high"],
                    x["p_value"], x["q_value"], x["bootstrap_unit"], x["bootstrap_reps"],
                    x["cluster_count"], x["evaluation_universe"],
                    x["same_seq_parent_rate"], x["big_winner_retention"],
                    x["big_loser_rejection"], x["rejected_total_r"],
                    x["rejected_positive_r"], x["rejected_negative_r"],
                    json.dumps(
                        {
                            "opportunity_cost_included": True,
                            "multiple_testing": "BH_FDR_GLOBAL_NODE_EDGE_RUN",
                            "q_threshold": 0.10,
                            "bootstrap_unit": "TRADING_DAY",
                            "g3_universe": "EVALUATED_ONLY",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
    return {
        "research_run_id": run_id,
        "rows": results,
        "multiple_testing": "BH_FDR_GLOBAL_NODE_EDGE_RUN",
        "bootstrap_unit": "TRADING_DAY",
        "evaluation_universe": "EVALUATED_ONLY",
    }


def _passes_observed_chain(event, gates):
    for node_id in gates:
        node = event.get("nodes", {}).get(node_id)
        if (
            not node
            or node.get("evaluation_state") != "EVALUATED"
            or node.get("answer") is not True
        ):
            return False
    return True


def sequential_contribution(event_db, run_id):
    migrate_event_db(event_db)
    assert_run_mutable(event_db, run_id)
    con = connect(event_db)
    rows = []
    try:
        for strategy, chain in (("MR", MR_CHAIN), ("BO", BO_CHAIN)):
            data = _dataset(con, run_id, strategy)
            previous = []
            prev_n = 0
            prev_avg = prev_total = 0.0
            for i, node in enumerate(chain, 1):
                previous.append(node)
                kept = [x for x in data if _passes_observed_chain(x, previous)]
                vals = [float(x.get("realized_r") or 0) for x in kept]
                avg = _avg(vals) or 0.0
                total = sum(vals)
                rows.append(
                    {
                        "strategy": strategy,
                        "step_no": i,
                        "node_id": node,
                        "n": len(kept),
                        "avg_r": avg,
                        "total_r": total,
                        "delta_n": len(kept) - prev_n,
                        "delta_avg_r": avg - prev_avg,
                        "delta_total_r": total - prev_total,
                    }
                )
                prev_n = len(kept)
                prev_avg = avg
                prev_total = total
    finally:
        con.close()
    with tx(event_db) as c:
        for x in rows:
            c.execute(
                """INSERT OR REPLACE INTO sequential_results(
                  research_run_id,strategy,step_no,node_id,n,avg_r,total_r,
                  delta_n,delta_avg_r,delta_total_r,details_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, x["strategy"], x["step_no"], x["node_id"], x["n"],
                    x["avg_r"], x["total_r"], x["delta_n"], x["delta_avg_r"],
                    x["delta_total_r"],
                    json.dumps({"evaluation_universe": "EVALUATED_ONLY"}),
                ),
            )
    return {"research_run_id": run_id, "rows": rows, "evaluation_universe": "EVALUATED_ONLY"}


def ablation(event_db, run_id):
    migrate_event_db(event_db)
    assert_run_mutable(event_db, run_id)
    con = connect(event_db)
    out = []
    try:
        for strategy, chain in (("MR", MR_CHAIN), ("BO", BO_CHAIN)):
            data = _dataset(con, run_id, strategy)
            for removed in [None] + chain:
                gates = [n for n in chain if n != removed]
                kept = [x for x in data if _passes_observed_chain(x, gates)]
                vals = [float(x.get("realized_r") or 0) for x in kept]
                rec = {
                    "strategy": strategy,
                    "variant": "FULL" if removed is None else f"FULL - {removed}",
                    "n": len(vals),
                    "avg_r": _avg(vals),
                    "total_r": sum(vals),
                    "pf": _pf(vals),
                    "hit_1r_rate": (
                        sum(bool(x.get("hit_1r")) for x in kept) / len(kept) if kept else None
                    ),
                    "hit_2r_rate": (
                        sum(bool(x.get("hit_2r")) for x in kept) / len(kept) if kept else None
                    ),
                    "hit_3r_rate": (
                        sum(bool(x.get("hit_3r")) for x in kept) / len(kept) if kept else None
                    ),
                    "hit_5r_rate": (
                        sum(bool(x.get("hit_5r")) for x in kept) / len(kept) if kept else None
                    ),
                }
                out.append(rec)
    finally:
        con.close()
    with tx(event_db) as c:
        for x in out:
            c.execute(
                """INSERT OR REPLACE INTO ablation_results(
                  research_run_id,strategy,variant,n,avg_r,total_r,pf,
                  hit_1r_rate,hit_2r_rate,hit_3r_rate,hit_5r_rate,details_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, x["strategy"], x["variant"], x["n"], x["avg_r"],
                    x["total_r"], x["pf"], x["hit_1r_rate"], x["hit_2r_rate"],
                    x["hit_3r_rate"], x["hit_5r_rate"],
                    json.dumps(
                        {
                            "evaluation_universe": "EVALUATED_ONLY",
                            "counterfactual_reconstruction": False,
                            "warning": "Removed-gate rows are observed evaluated-only subsets; NOT_REACHED descendants are never relabelled as NO or reconstructed.",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
    return {
        "research_run_id": run_id,
        "rows": out,
        "evaluation_universe": "EVALUATED_ONLY",
        "counterfactual_reconstruction": False,
    }


def build_evidence(event_db, run_id, registry: NodeRegistry):
    migrate_event_db(event_db)
    assert_run_mutable(event_db, run_id)
    con = connect(event_db)
    items = []
    try:
        rr = con.execute(
            "SELECT role,years_json FROM research_runs WHERE research_run_id=?", (run_id,)
        ).fetchone()
        if not rr:
            raise KeyError(run_id)
        role = rr["role"]
        edges = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM node_edge_results WHERE research_run_id=?", (run_id,)
            ).fetchall()
        ]
        emap = {}
        for edge in edges:
            current = emap.get(edge["node_id"])
            if current is None or int(edge.get("universe") or 0) > int(current.get("universe") or 0):
                emap[edge["node_id"]] = edge

        for node_id, node in registry.items():
            edge = emap.get(node_id, {})
            n = int(edge.get("universe") or 0)
            if n == 0:
                r = con.execute(
                    "SELECT COUNT(*) n FROM event_nodes WHERE research_run_id=? AND node_id=? AND evaluation_state='EVALUATED'",
                    (run_id, node_id),
                ).fetchone()
                n = int(r["n"] or 0) if r else 0
            classification = edge.get("classification") or (
                "STATE" if node.role == "STATE" else "INSUFFICIENT"
            )
            level = {"DISCOVERY": "L2", "VALIDATION": "L3", "FINAL_HOLDOUT": "L4"}.get(role, "L0")
            train = bool(
                node.training_eligible
                and classification in {"CORE", "OPTIONAL", "STATE", "REGIME_DEPENDENT"}
                and n > 0
            )
            items.append(
                {
                    "node_id": node_id,
                    "role": node.role,
                    "classification": classification,
                    "evidence_level": level,
                    "discovery_n": n if role == "DISCOVERY" else 0,
                    "validation_n": n if role == "VALIDATION" else 0,
                    "holdout_n": n if role == "FINAL_HOLDOUT" else 0,
                    "effect_size": edge.get("delta_avg_r"),
                    "ci_low": edge.get("ci_low"),
                    "ci_high": edge.get("ci_high"),
                    "right_tail_retention": edge.get("big_winner_retention"),
                    "loser_rejection": edge.get("big_loser_rejection"),
                    "training_eligible": train,
                    "production_eligible": False,
                }
            )
    finally:
        con.close()

    with tx(event_db) as c:
        for x in items:
            c.execute(
                """INSERT OR REPLACE INTO node_evidence_registry(
                  research_run_id,node_id,role,classification,evidence_level,
                  discovery_n,validation_n,holdout_n,effect_size,ci_low,ci_high,
                  positive_years,negative_years,right_tail_retention,loser_rejection,
                  known_regime_dependency,training_eligible,production_eligible,last_research_run
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, x["node_id"], x["role"], x["classification"],
                    x["evidence_level"], x["discovery_n"], x["validation_n"],
                    x["holdout_n"], x["effect_size"], x["ci_low"], x["ci_high"],
                    0, 0, x["right_tail_retention"], x["loser_rejection"], None,
                    int(x["training_eligible"]), int(x["production_eligible"]), run_id,
                ),
            )
    return {
        "research_run_id": run_id,
        "items": items,
        "evaluation_universe": "EVALUATED_ONLY",
    }
