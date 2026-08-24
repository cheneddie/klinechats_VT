from __future__ import annotations

import json
import math
import random
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .engine import connect
from .v4_engine import migrate_v4_schema
from .v4_replay_final import read_tick_path
from .v4_audit import _simulate_first_hits, management_suite

MR_CHAIN = ["AUC_ATTEMPT","MR_REJECTION","MR_CLEAR_RECLAIM","MR_RECLAIM_LEG","MR_LVN","MR_PULLBACK","MR_ENTRY"]
BO_CHAIN = ["AUC_ATTEMPT","BO_DISPLACEMENT","BO_ACCEPTANCE","BO_IMPULSE_LEG","BO_LVN","BO_PULLBACK","BO_RESPONSE","BO_ENTRY"]
PARENTS = {
    "MR_REJECTION":"AUC_ATTEMPT","MR_CLEAR_RECLAIM":"MR_REJECTION","MR_RECLAIM_LEG":"MR_CLEAR_RECLAIM",
    "MR_LVN":"MR_RECLAIM_LEG","MR_PULLBACK":"MR_LVN","MR_ENTRY":"MR_PULLBACK",
    "BO_DISPLACEMENT":"AUC_ATTEMPT","BO_ACCEPTANCE":"BO_DISPLACEMENT","BO_IMPULSE_LEG":"BO_ACCEPTANCE",
    "BO_LVN":"BO_IMPULSE_LEG","BO_PULLBACK":"BO_LVN","BO_RESPONSE":"BO_PULLBACK","BO_ENTRY":"BO_RESPONSE",
}


def _event_row(r):
    d = dict(r)
    d["features"] = json.loads(d.get("features_json") or "{}")
    d["nodes"] = json.loads(d.get("nodes_json") or "{}")
    d["id"] = d["event_id"]
    d["date"] = d["trading_date"]
    return d


def _node_meta(con, event_id):
    rows = con.execute(
        "SELECT node_id,answer,decision_seq,decision_time,decision_price,anchor_seq,anchor_time,anchor_price,reason_code,metrics_json "
        "FROM node_instances WHERE event_id=?", (event_id,)
    ).fetchall()
    out = {}
    for r in rows:
        x = dict(r)
        node_id = x.pop("node_id")
        x["answer"] = bool(x.get("answer"))
        raw = x.pop("metrics_json", None)
        try:
            x["metrics"] = json.loads(raw or "{}")
        except Exception:
            x["metrics"] = {}
        out[node_id] = x
    return out


def _terminal_spec(e):
    f = e.get("features") or {}
    seq = f.get("terminal_entry_seq")
    price = f.get("terminal_entry_price")
    stop = f.get("terminal_stop")
    if seq is None:
        seq = e.get("entry_seq")
    if price is None:
        price = e.get("entry_price")
    if stop is None:
        stop = e.get("stop")
    if seq is None or price is None or stop is None:
        return None
    risk = abs(float(price) - float(stop))
    if risk <= 0:
        return None
    return {
        "seq": int(seq), "price": float(price), "stop": float(stop), "risk": risk,
        "time": f.get("terminal_entry_time") or e.get("entry_time"),
    }


def compute_outcomes(db: Path, root: Path, years=None, max_after_days=1, progress=None):
    """Compute outcome paths once per trading-day group, not once per event.

    Thousands of opportunities on one year no longer trigger thousands of full
    Parquet rescans.  Events sharing source/trading-date/contract reuse one
    physical tick window and then slice it by immutable `_seq`.
    """
    con = connect(db)
    migrate_v4_schema(con)
    where = ["json_extract(features_json,'$.terminal_signal')=1"]
    args = []
    if years:
        q = ",".join("?" for _ in years)
        where.append(f"year IN ({q})")
        args.extend(int(y) for y in years)
    raw = con.execute("SELECT * FROM events WHERE " + " AND ".join(where) + " ORDER BY source_file,trading_date,contract,attempt_start_seq", args).fetchall()
    events = []
    for r in raw:
        e = _event_row(r)
        spec = _terminal_spec(e)
        if spec:
            e["_terminal"] = spec
            events.append(e)
    groups = defaultdict(list)
    for e in events:
        groups[(e["source_file"], e["trading_date"], e["contract"])].append(e)
    now = datetime.now(timezone.utc).isoformat()
    done = 0
    total = len(events)
    for gi, items in enumerate(groups.values(), 1):
        representative = items[0]
        min_seq = min(x["_terminal"]["seq"] for x in items)
        shared = read_tick_path(root, representative, min_seq, max_after_days)
        for e in items:
            s = e["_terminal"]
            path = shared.loc[shared["_seq"] >= s["seq"]].reset_index(drop=True) if len(shared) else shared
            hits = _simulate_first_hits(path, s["price"], s["risk"], e["direction"])
            suite = management_suite(path, s["price"], s["risk"], e["direction"])
            con.execute(
                """INSERT OR REPLACE INTO opportunity_outcomes(
                event_id,strategy,direction,entry_seq,entry_time,entry_price,risk_points,
                mfe_points,mae_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,hit_stop,
                first_hit_1r,first_hit_2r,first_hit_3r,bars_end_time,management_json,computed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    e["event_id"], e["strategy"], e["direction"], s["seq"], s["time"], s["price"], s["risk"],
                    hits.get("mfe_points"), hits.get("mae_points"), hits.get("mfe_r"), hits.get("mae_r"),
                    int(bool(hits.get("hit_1r"))), int(bool(hits.get("hit_2r"))), int(bool(hits.get("hit_3r"))), int(bool(hits.get("hit_stop"))),
                    hits.get("first_hit_1r"), hits.get("first_hit_2r"), hits.get("first_hit_3r"),
                    str(path["dt"].iloc[-1]) if len(path) else None, json.dumps(suite, ensure_ascii=False), now,
                ),
            )
            done += 1
            if progress:
                progress({"phase":"outcomes","done":done,"total":total,"group":gi,"groups":len(groups),"event_id":e["event_id"]})
        con.commit()
    con.close()
    return done


def _avg(values):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return sum(vals) / len(vals) if vals else None


def _sum(values):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return sum(vals) if vals else 0.0


def _control_name(strategy):
    return "fixed_0.75R" if strategy == "MR" else "fixed_1R"


def _management_r(row, name):
    try:
        m = json.loads(row.get("management_json") or "{}")
        v = m.get(name, {}).get("r")
        return float(v) if v is not None else None
    except Exception:
        return None


def _bootstrap_diff(a, b, reps=500, seed=42):
    a = [float(x) for x in a if x is not None and math.isfinite(float(x))]
    b = [float(x) for x in b if x is not None and math.isfinite(float(x))]
    if len(a) < 10 or len(b) < 10:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        ma = sum(a[rng.randrange(len(a))] for _ in range(len(a))) / len(a)
        mb = sum(b[rng.randrange(len(b))] for _ in range(len(b))) / len(b)
        vals.append(ma - mb)
    vals.sort()
    return [vals[int(.025*(len(vals)-1))], vals[int(.975*(len(vals)-1))]]


def _gate_metrics(rows, node):
    rows2 = [x for x in rows if node in x["meta"]]
    if not rows2:
        return None
    passed = [x for x in rows2 if x["meta"][node]["answer"]]
    failed = [x for x in rows2 if not x["meta"][node]["answer"]]
    bigw = [x for x in rows2 if bool(x.get("hit_2r"))]
    hugew = [x for x in rows2 if bool(x.get("hit_3r"))]
    bigl = [x for x in rows2 if bool(x.get("hit_stop")) and not bool(x.get("hit_1r"))]
    positive = [x for x in rows2 if (x.get("control_r") or 0) > 0]
    bw_kept = sum(1 for x in bigw if x["meta"][node]["answer"])
    hw_kept = sum(1 for x in hugew if x["meta"][node]["answer"])
    bl_rej = sum(1 for x in bigl if not x["meta"][node]["answer"])
    pos_kept = sum(1 for x in positive if x["meta"][node]["answer"])
    bl_rate = bl_rej / len(bigl) if bigl else 0.0
    bw_reject = (len(bigw)-bw_kept) / len(bigw) if bigw else 0.0
    pass_control = [x.get("control_r") for x in passed]
    fail_control = [x.get("control_r") for x in failed]
    delta_control = (_avg(pass_control) - _avg(fail_control)) if _avg(pass_control) is not None and _avg(fail_control) is not None else None
    ci = _bootstrap_diff(pass_control, fail_control, seed=sum(ord(c) for c in node))
    return {
        "rows": rows2, "passed": passed, "failed": failed,
        "bigw": bigw, "hugew": hugew, "bigl": bigl, "positive": positive,
        "bw_kept": bw_kept, "hw_kept": hw_kept, "bl_rej": bl_rej, "pos_kept": pos_kept,
        "big_loss_rejection_rate": bl_rate, "big_win_rejection_rate": bw_reject,
        "filter_score": bl_rate - bw_reject,
        "pass_control_avg_r": _avg(pass_control), "fail_control_avg_r": _avg(fail_control),
        "pass_control_total_r": _sum(pass_control), "fail_control_total_r": _sum(fail_control),
        "delta_control_avg_r": delta_control, "delta_control_avg_r_ci95": ci,
    }


def _status(metric, same_seq):
    n = len(metric["rows"])
    score = metric["filter_score"]
    delta = metric["delta_control_avg_r"]
    if n < 50:
        return "insufficient"
    if same_seq is not None and same_seq >= .80 and abs(score) < .05 and (delta is None or abs(delta) < .05):
        return "redundant"
    if score <= -.10 or (delta is not None and delta <= -.15):
        return "harmful"
    ci = metric.get("delta_control_avg_r_ci95")
    if score >= .15 and delta is not None and delta > 0 and (ci is None or ci[1] > 0):
        return "candidate_keep"
    return "neutral"


def reverse_node_audit(db: Path, years=None, audit_id=None):
    con = connect(db)
    migrate_v4_schema(con)
    audit_id = audit_id or f"v4-{uuid.uuid4().hex[:8]}"
    where = ["json_extract(e.features_json,'$.terminal_signal')=1"]
    args = []
    if years:
        q = ",".join("?" for _ in years)
        where.append(f"e.year IN ({q})")
        args.extend(int(y) for y in years)
    sql = (
        "SELECT e.*,o.mfe_r,o.mae_r,o.hit_1r,o.hit_2r,o.hit_3r,o.hit_stop,o.management_json "
        "FROM events e JOIN opportunity_outcomes o ON o.event_id=e.event_id WHERE " + " AND ".join(where)
    )
    raw = con.execute(sql, args).fetchall()
    by_strategy = {"MR": [], "BO": []}
    for r in raw:
        e = _event_row(r)
        for k in ("mfe_r","mae_r","hit_1r","hit_2r","hit_3r","hit_stop","management_json"):
            e[k] = r[k]
        e["control_r"] = _management_r(e, _control_name(e["strategy"]))
        e["meta"] = _node_meta(con, e["event_id"])
        if e["strategy"] in by_strategy:
            by_strategy[e["strategy"]].append(e)
    now = datetime.now(timezone.utc).isoformat()
    output = []
    for strategy, items in by_strategy.items():
        chain = MR_CHAIN if strategy == "MR" else BO_CHAIN
        for node in chain:
            metric = _gate_metrics(items, node)
            if not metric:
                continue
            parent = PARENTS.get(node)
            same = den = 0
            if parent:
                for x in metric["rows"]:
                    a = x["meta"].get(node, {}).get("decision_seq")
                    b = x["meta"].get(parent, {}).get("decision_seq")
                    if a is not None and b is not None:
                        den += 1
                        same += int(a == b)
            same_rate = same / den if den else None
            per_year = {}
            for year in sorted({int(x["year"]) for x in metric["rows"]}):
                ym = _gate_metrics([x for x in metric["rows"] if int(x["year"]) == year], node)
                if ym:
                    per_year[str(year)] = {
                        "n": len(ym["rows"]), "filter_score": ym["filter_score"],
                        "delta_control_avg_r": ym["delta_control_avg_r"],
                        "big_loss_rejection_rate": ym["big_loss_rejection_rate"],
                        "big_win_rejection_rate": ym["big_win_rejection_rate"],
                    }
            status = _status(metric, same_rate)
            rec = {
                "audit_id": audit_id, "node_id": node, "strategy": strategy,
                "universe": len(metric["rows"]), "pass_count": len(metric["passed"]), "fail_count": len(metric["failed"]),
                "big_winners": len(metric["bigw"]), "big_winners_kept": metric["bw_kept"], "big_winners_rejected": len(metric["bigw"])-metric["bw_kept"],
                "big_losers": len(metric["bigl"]), "big_losers_rejected": metric["bl_rej"], "big_losers_kept": len(metric["bigl"])-metric["bl_rej"],
                "pass_avg_mfe_r": _avg([x.get("mfe_r") for x in metric["passed"]]),
                "fail_avg_mfe_r": _avg([x.get("mfe_r") for x in metric["failed"]]),
                "pass_avg_mae_r": _avg([x.get("mae_r") for x in metric["passed"]]),
                "fail_avg_mae_r": _avg([x.get("mae_r") for x in metric["failed"]]),
                "pass_2r_rate": sum(bool(x.get("hit_2r")) for x in metric["passed"])/len(metric["passed"]) if metric["passed"] else None,
                "fail_2r_rate": sum(bool(x.get("hit_2r")) for x in metric["failed"])/len(metric["failed"]) if metric["failed"] else None,
                "same_seq_parent_rate": same_rate, "filter_score": metric["filter_score"],
            }
            details = {
                "status": status,
                "universe": "relaxed terminal opportunities; strict nodes are evaluated as filters",
                "audit_universe_version": "V4.1_RELAXED_TERMINAL",
                "control_management": _control_name(strategy),
                "big_loss_definition": "stop reached before 1R",
                "big_win_definition": ">=2R before stop",
                "huge_win_definition": ">=3R before stop",
                "big_loss_rejection_rate": metric["big_loss_rejection_rate"],
                "big_win_rejection_rate": metric["big_win_rejection_rate"],
                "huge_winners": len(metric["hugew"]), "huge_winners_kept": metric["hw_kept"],
                "positive_trades": len(metric["positive"]), "positive_trades_kept": metric["pos_kept"],
                "pass_control_avg_r": metric["pass_control_avg_r"], "fail_control_avg_r": metric["fail_control_avg_r"],
                "pass_control_total_r": metric["pass_control_total_r"], "fail_control_total_r": metric["fail_control_total_r"],
                "delta_control_avg_r": metric["delta_control_avg_r"], "delta_control_avg_r_ci95": metric["delta_control_avg_r_ci95"],
                "per_year": per_year,
                "interpretation": "A useful gate should reject losing tails without killing the >=2R / >=3R right tail and should improve control-strategy R.",
            }
            con.execute(
                """INSERT OR REPLACE INTO node_edge_audit(
                audit_id,node_id,strategy,universe,pass_count,fail_count,big_winners,big_winners_kept,big_winners_rejected,
                big_losers,big_losers_rejected,big_losers_kept,pass_avg_mfe_r,fail_avg_mfe_r,pass_avg_mae_r,fail_avg_mae_r,
                pass_2r_rate,fail_2r_rate,same_seq_parent_rate,filter_score,details_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rec["audit_id"],rec["node_id"],rec["strategy"],rec["universe"],rec["pass_count"],rec["fail_count"],
                 rec["big_winners"],rec["big_winners_kept"],rec["big_winners_rejected"],rec["big_losers"],rec["big_losers_rejected"],rec["big_losers_kept"],
                 rec["pass_avg_mfe_r"],rec["fail_avg_mfe_r"],rec["pass_avg_mae_r"],rec["fail_avg_mae_r"],rec["pass_2r_rate"],rec["fail_2r_rate"],
                 rec["same_seq_parent_rate"],rec["filter_score"],json.dumps(details,ensure_ascii=False),now),
            )
            rec["details"] = details
            output.append(rec)
    con.commit()
    con.close()
    return {"audit_id":audit_id,"rows":output}


def ablation_audit(db: Path, years=None):
    con = connect(db)
    migrate_v4_schema(con)
    where = ["json_extract(e.features_json,'$.terminal_signal')=1"]
    args = []
    if years:
        q = ",".join("?" for _ in years)
        where.append(f"e.year IN ({q})")
        args.extend(int(y) for y in years)
    rows = con.execute(
        "SELECT e.event_id,e.strategy,o.hit_1r,o.hit_2r,o.hit_3r,o.mfe_r,o.mae_r,o.management_json "
        "FROM events e JOIN opportunity_outcomes o ON o.event_id=e.event_id WHERE " + " AND ".join(where), args
    ).fetchall()
    result = {}
    for strategy in ("MR","BO"):
        chain = MR_CHAIN if strategy == "MR" else BO_CHAIN
        items = [dict(r) for r in rows if r["strategy"] == strategy]
        metas = {r["event_id"]:_node_meta(con,r["event_id"]) for r in items}
        for r in items:
            r["control_r"] = _management_r(r, _control_name(strategy))
        def subset(required):
            return [r for r in items if all(metas[r["event_id"]].get(n,{}).get("answer") for n in required)]
        full = subset(chain)
        out = []
        for removed in [None] + chain:
            req = chain if removed is None else [n for n in chain if n != removed]
            sub = subset(req)
            out.append({
                "removed": removed or "NONE", "n": len(sub),
                "hit_1r_rate": sum(bool(r["hit_1r"]) for r in sub)/len(sub) if sub else None,
                "hit_2r_rate": sum(bool(r["hit_2r"]) for r in sub)/len(sub) if sub else None,
                "hit_3r_rate": sum(bool(r["hit_3r"]) for r in sub)/len(sub) if sub else None,
                "avg_mfe_r": _avg([r["mfe_r"] for r in sub]), "avg_mae_r": _avg([r["mae_r"] for r in sub]),
                "avg_control_r": _avg([r["control_r"] for r in sub]), "total_control_r": _sum([r["control_r"] for r in sub]),
                "added_vs_full": len(sub)-len(full),
            })
        result[strategy] = out
    con.close()
    return result


__all__ = ["compute_outcomes","reverse_node_audit","ablation_audit","MR_CHAIN","BO_CHAIN"]
