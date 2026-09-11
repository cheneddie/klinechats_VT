from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .campaigns import get_campaign, pin_run_datasets, validate_campaign_governance
from .storage import EVALUATION_STATES, connect, create_research_run, tx

ROLE_YEARS = {"DISCOVERY": {2025}, "VALIDATION": {2024}, "FINAL_HOLDOUT": {2026}}
MR_CHAIN = ["AUC_ATTEMPT", "MR_REJECTION", "MR_CLEAR_RECLAIM", "MR_RECLAIM_LEG", "MR_LVN", "MR_PULLBACK", "MR_ENTRY"]
BO_CHAIN = ["AUC_ATTEMPT", "BO_DISPLACEMENT", "BO_ACCEPTANCE", "BO_IMPULSE_LEG", "BO_LVN", "BO_PULLBACK", "BO_RESPONSE", "BO_ENTRY"]
PARENTS = {
    "AUC_ATTEMPT": "CTX_VALUE",
    "AUC_EXTREME": "AUC_ATTEMPT",
    "MR_REJECTION": "AUC_ATTEMPT",
    "MR_CLEAR_RECLAIM": "MR_REJECTION",
    "MR_RECLAIM_LEG": "MR_CLEAR_RECLAIM",
    "MR_LVN": "MR_RECLAIM_LEG",
    "MR_PULLBACK": "MR_LVN",
    "MR_ENTRY": "MR_PULLBACK",
    "BO_DISPLACEMENT": "AUC_ATTEMPT",
    "BO_ACCEPTANCE": "BO_DISPLACEMENT",
    "BO_IMPULSE_LEG": "BO_ACCEPTANCE",
    "BO_LVN": "BO_IMPULSE_LEG",
    "BO_PULLBACK": "BO_LVN",
    "BO_RESPONSE": "BO_PULLBACK",
    "BO_ENTRY": "BO_RESPONSE",
}


def validate_governance(role: str, years: list[int] | tuple[int, ...]):
    role = role.upper()
    ys = {int(y) for y in years}
    if role not in ROLE_YEARS:
        raise ValueError(f"unsupported research role: {role}")
    if ys != ROLE_YEARS[role]:
        raise ValueError(f"{role} must use exactly {sorted(ROLE_YEARS[role])}, got {sorted(ys)}")
    return role


def _json(raw, default):
    try:
        return json.loads(raw or default)
    except Exception:
        return json.loads(default)


def _source_nodes(event):
    return _json(event.get("nodes_json"), "{}")


def _value(db_node, rich, db_key, rich_key=None):
    rich_key = rich_key or db_key
    if rich_key in rich and rich.get(rich_key) is not None:
        return rich.get(rich_key)
    return db_node.get(db_key)


def _normalize_nodes(event, db_nodes):
    rich_nodes = _source_nodes(event)
    rows = {}
    for raw in db_nodes:
        node_id = raw["node_id"]
        rich = rich_nodes.get(node_id) or {}
        state = rich.get("evaluation_status") or rich.get("evaluation_state") or raw.get("evaluation_status") or raw.get("evaluation_state")
        answer = rich.get("answer") if "answer" in rich else raw.get("answer")
        rows[node_id] = {
            "node_id": node_id,
            "evaluation_state": str(state).upper() if state else None,
            "answer": answer,
            "decision_seq": _value(raw, rich, "decision_seq", "seq"),
            "decision_time": _value(raw, rich, "decision_time", "time"),
            "decision_price": _value(raw, rich, "decision_price"),
            "anchor_seq": _value(raw, rich, "anchor_seq"),
            "anchor_time": _value(raw, rich, "anchor_time"),
            "anchor_price": _value(raw, rich, "anchor_price"),
            "start_seq": _value(raw, rich, "start_seq"),
            "start_time": _value(raw, rich, "start_time"),
            "end_seq": _value(raw, rich, "end_seq"),
            "end_time": _value(raw, rich, "end_time"),
            "resolution_seq": rich.get("resolution_seq"),
            "resolution_time": rich.get("resolution_time"),
            "resolution_price": rich.get("resolution_price"),
            "parent_node_id": rich.get("parent_node_id") or PARENTS.get(node_id),
            "blocker_node_id": rich.get("blocker_node_id"),
            "blocker_reason_code": rich.get("blocker_reason_code"),
            "counterfactual_answer": rich.get("counterfactual_answer"),
            "reason_code": rich.get("reason_code") or raw.get("reason_code"),
            "metrics": rich.get("metrics") if isinstance(rich.get("metrics"), dict) else _json(raw.get("metrics_json"), "{}"),
        }

    strategy = event.get("strategy")
    chain = MR_CHAIN if strategy == "MR" else BO_CHAIN if strategy == "BO" else []
    blocker_id = None
    for node_id in chain:
        row = rows.get(node_id)
        if not row:
            continue
        if row["evaluation_state"] in EVALUATION_STATES:
            if row["evaluation_state"] == "EVALUATED" and row["answer"] is None:
                raise ValueError(f"EVALUATED node lacks YES/NO answer: {event.get('event_id')} {node_id}")
            if row["evaluation_state"] == "EVALUATED" and not bool(row["answer"]) and blocker_id is None:
                blocker_id = node_id
            elif row["evaluation_state"] == "NOT_REACHED" and not row.get("blocker_node_id"):
                row["blocker_node_id"] = blocker_id
            continue
        if blocker_id is not None:
            row["evaluation_state"] = "NOT_REACHED"
            row["blocker_node_id"] = blocker_id
            row["blocker_reason_code"] = (rows.get(blocker_id) or {}).get("reason_code")
            row["answer"] = None
        else:
            row["evaluation_state"] = "EVALUATED"
            row["answer"] = bool(row["answer"])
            if row["answer"] is False:
                blocker_id = node_id

    for node_id, row in rows.items():
        if row["evaluation_state"] in EVALUATION_STATES:
            continue
        if node_id == "NO_TRADE":
            row["evaluation_state"] = "TERMINAL"
            row["answer"] = None
            row["blocker_node_id"] = blocker_id
            row["blocker_reason_code"] = (rows.get(blocker_id) or {}).get("reason_code")
        elif strategy == "BO" and node_id.startswith("MR_"):
            row["evaluation_state"] = "NOT_APPLICABLE"
            row["answer"] = None
        elif strategy == "MR" and node_id.startswith("BO_"):
            row["evaluation_state"] = "NOT_APPLICABLE"
            row["answer"] = None
        else:
            row["evaluation_state"] = "EVALUATED"
            row["answer"] = bool(row["answer"])

    for row in rows.values():
        state = row["evaluation_state"]
        if state != "EVALUATED":
            if row["resolution_seq"] is None:
                if state == "NOT_REACHED" and row.get("blocker_node_id") in rows:
                    blocker = rows[row["blocker_node_id"]]
                    row["resolution_seq"] = blocker.get("resolution_seq") or blocker.get("decision_seq")
                    row["resolution_time"] = blocker.get("resolution_time") or blocker.get("decision_time")
                    row["resolution_price"] = blocker.get("resolution_price") or blocker.get("decision_price")
                else:
                    row["resolution_seq"] = row.get("decision_seq")
                    row["resolution_time"] = row.get("decision_time")
                    row["resolution_price"] = row.get("decision_price")
            row["answer"] = None
            row["decision_seq"] = None
            row["decision_time"] = None
            row["decision_price"] = None
            row["anchor_seq"] = None
            row["anchor_time"] = None
            row["anchor_price"] = None
        else:
            row["answer"] = int(bool(row["answer"]))
            if row["resolution_seq"] is None:
                row["resolution_seq"] = row.get("decision_seq")
                row["resolution_time"] = row.get("decision_time")
                row["resolution_price"] = row.get("decision_price")
    return list(rows.values())


def snapshot_v4_run(
    v4_db: str | Path,
    event_db: str | Path,
    research_run_id: str,
    role: str,
    years: list[int],
    *,
    metadata: dict[str, Any] | None = None,
    include_outcomes: bool = False,
    campaign_id: str | None = None,
):
    metadata = metadata or {}
    if campaign_id:
        role = validate_campaign_governance(event_db, campaign_id, role, years)
        campaign = get_campaign(event_db, campaign_id)
        registered_files = {
            x["source_file"] for x in campaign["datasets"] if x["role"] == role
        }
    else:
        role = validate_governance(role, years)
        registered_files = set()

    src = connect(v4_db)
    try:
        q = ",".join("?" for _ in years)
        events = [
            dict(r)
            for r in src.execute(
                f"SELECT * FROM events WHERE year IN ({q}) ORDER BY source_file,trading_date,attempt_start_seq,event_id",
                tuple(years),
            ).fetchall()
        ]
        if registered_files:
            event_files = {str(e.get("source_file") or "") for e in events}
            missing = event_files - registered_files
            if missing:
                raise RuntimeError(
                    f"event source files are not registered in campaign {campaign_id}: {sorted(missing)}"
                )

        node_cols = {r[1] for r in src.execute("PRAGMA table_info(node_instances)").fetchall()}
        wanted = [
            "event_id", "node_id", "answer", "evaluation_status", "evaluation_state",
            "decision_seq", "decision_time", "decision_price",
            "anchor_seq", "anchor_time", "anchor_price",
            "start_seq", "start_time", "end_seq", "end_time",
            "reason_code", "metrics_json",
        ]
        cols = [x for x in wanted if x in node_cols]
        nodes_by_event = {}
        if events and cols:
            ids = [e["event_id"] for e in events]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" for _ in chunk)
                for row in src.execute(
                    f"SELECT {','.join(cols)} FROM node_instances WHERE event_id IN ({marks})", chunk
                ).fetchall():
                    d = dict(row)
                    nodes_by_event.setdefault(d["event_id"], []).append(d)

        outcomes = []
        if include_outcomes:
            out_cols = {r[1] for r in src.execute("PRAGMA table_info(opportunity_outcomes)").fetchall()}
            if out_cols and events:
                ids = [e["event_id"] for e in events]
                for i in range(0, len(ids), 500):
                    chunk = ids[i:i + 500]
                    marks = ",".join("?" for _ in chunk)
                    outcomes.extend(
                        dict(r)
                        for r in src.execute(
                            f"SELECT * FROM opportunity_outcomes WHERE event_id IN ({marks})", chunk
                        ).fetchall()
                    )
    finally:
        src.close()

    create_research_run(
        event_db,
        research_run_id,
        role,
        years,
        **{**metadata, "campaign_id": campaign_id},
    )
    if campaign_id:
        pin_run_datasets(event_db, research_run_id, campaign_id, role, years)

    normalized_nodes = []
    with tx(event_db) as dst:
        for e in events:
            payload = dict(e)
            features = _json(e.get("features_json"), "{}")
            nodes_json = _json(e.get("nodes_json"), "{}")
            dst.execute(
                """INSERT INTO events(
                  research_run_id,event_id,source_file,year,trading_date,contract,strategy,direction,result,difficulty,
                  attempt_start_seq,attempt_start_time,entry_seq,entry_time,entry_price,stop,target,features_json,nodes_json,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    research_run_id, e["event_id"], e.get("source_file"), e.get("year"),
                    e.get("trading_date"), e.get("contract"), e.get("strategy"), e.get("direction"),
                    e.get("result"), e.get("difficulty"), e.get("attempt_start_seq"),
                    e.get("attempt_start_time"), e.get("entry_seq"), e.get("entry_time"),
                    e.get("entry_price"), e.get("stop"), e.get("target"),
                    json.dumps(features, ensure_ascii=False), json.dumps(nodes_json, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
            )
            for n in _normalize_nodes(e, nodes_by_event.get(e["event_id"], [])):
                normalized_nodes.append((e["event_id"], n))
                dst.execute(
                    """INSERT INTO event_nodes(
                      research_run_id,event_id,node_id,evaluation_state,answer,
                      decision_seq,decision_time,decision_price,anchor_seq,anchor_time,anchor_price,
                      start_seq,start_time,end_seq,end_time,resolution_seq,resolution_time,resolution_price,
                      parent_node_id,blocker_node_id,blocker_reason_code,counterfactual_answer,reason_code,metrics_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        research_run_id, e["event_id"], n["node_id"], n["evaluation_state"], n["answer"],
                        n.get("decision_seq"), n.get("decision_time"), n.get("decision_price"),
                        n.get("anchor_seq"), n.get("anchor_time"), n.get("anchor_price"),
                        n.get("start_seq"), n.get("start_time"), n.get("end_seq"), n.get("end_time"),
                        n.get("resolution_seq"), n.get("resolution_time"), n.get("resolution_price"),
                        n.get("parent_node_id"), n.get("blocker_node_id"), n.get("blocker_reason_code"),
                        n.get("counterfactual_answer"), n.get("reason_code"),
                        json.dumps(n.get("metrics") or {}, ensure_ascii=False, default=str),
                    ),
                )

        if include_outcomes:
            for o in outcomes:
                dst.execute(
                    """INSERT OR IGNORE INTO opportunity_outcomes(
                      research_run_id,event_id,basis,entry_seq,entry_time,entry_price,risk_points,
                      mfe_points,mae_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,management_json,computed_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        research_run_id, o.get("event_id"), "terminal", o.get("entry_seq"),
                        o.get("entry_time"), o.get("entry_price"), o.get("risk_points"),
                        o.get("mfe_points"), o.get("mae_points"), o.get("mfe_r"), o.get("mae_r"),
                        o.get("hit_1r"), o.get("hit_2r"), o.get("hit_3r"),
                        o.get("management_json") or "{}", o.get("computed_at") or "",
                    ),
                )
    return {
        "research_run_id": research_run_id,
        "campaign_id": campaign_id,
        "role": role,
        "years": years,
        "events": len(events),
        "nodes": len(normalized_nodes),
        "imported_outcomes": len(outcomes),
        "evaluation_states": sorted(EVALUATION_STATES),
    }
