from __future__ import annotations

import json
import uuid
from bisect import bisect_right
from pathlib import Path
from typing import Any

from .storage import connect, migrate_event_db, tx, utcnow


def _load_physical_rows(path: Path, seqs: list[int]) -> dict[int, dict[str, Any]]:
    if not seqs or not path.exists():
        return {}
    try:
        import pyarrow.parquet as pq
    except Exception:
        return {}
    pf = pq.ParquetFile(path)
    starts: list[int] = []
    total = 0
    for rg in range(pf.num_row_groups):
        starts.append(total)
        total += int(pf.metadata.row_group(rg).num_rows)
    grouped: dict[int, list[int]] = {}
    for seq in sorted(set(int(x) for x in seqs if x is not None)):
        if seq < 0 or seq >= total:
            continue
        rg = max(0, bisect_right(starts, seq) - 1)
        grouped.setdefault(rg, []).append(seq)
    out: dict[int, dict[str, Any]] = {}
    for rg, targets in grouped.items():
        available = set(pf.schema.names)
        names = [x for x in ("datetime", "price", "expiry", "product") if x in available]
        table = pf.read_row_group(rg, columns=names)
        for seq in targets:
            local = seq - starts[rg]
            row = {}
            for name in names:
                value = table.column(name)[local].as_py()
                row[name] = value.isoformat() if hasattr(value, "isoformat") else value
            out[seq] = row
    return out


def _item(items, event_id, node_id, name, passed, message="", details=None):
    items.append({"event_id": event_id, "node_id": node_id, "check_name": name,
                  "passed": bool(passed), "message": message, "details": details or {}})


def run_event_sanity(event_db: str | Path, data_root: str | Path, research_run_id: str, *,
                     physical_validate: bool = True) -> dict[str, Any]:
    migrate_event_db(event_db)
    con = connect(event_db)
    try:
        events = [dict(r) for r in con.execute(
            "SELECT * FROM events WHERE research_run_id=? ORDER BY source_file,trading_date,attempt_start_seq,event_id",
            (research_run_id,),
        ).fetchall()]
        nodes = [dict(r) for r in con.execute(
            "SELECT * FROM event_nodes WHERE research_run_id=? ORDER BY event_id,node_id", (research_run_id,)
        ).fetchall()]
    finally:
        con.close()
    by_event: dict[str, list[dict[str, Any]]] = {}
    for n in nodes:
        by_event.setdefault(n["event_id"], []).append(n)

    items: list[dict[str, Any]] = []
    root = Path(data_root)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        by_source.setdefault(str(e.get("source_file") or ""), []).append(e)

    physical_cache: dict[tuple[str, int], dict[str, Any]] = {}
    if physical_validate:
        for source, evs in by_source.items():
            seqs = []
            for e in evs:
                seqs.extend(int(n["decision_seq"]) for n in by_event.get(e["event_id"], []) if n.get("decision_seq") is not None)
            for seq, row in _load_physical_rows(root/source, seqs).items():
                physical_cache[(source, seq)] = row

    seen_geometry: set[tuple[Any, ...]] = set()
    for e in events:
        event_id = e["event_id"]
        ens = by_event.get(event_id, [])
        key = (e.get("trading_date"), e.get("contract"), e.get("strategy"), e.get("attempt_start_seq"))
        _item(items,event_id,None,"duplicate_event_geometry",key not in seen_geometry,
              "duplicate auction/strategy geometry" if key in seen_geometry else "")
        seen_geometry.add(key)

        ep, stop = e.get("entry_price"), e.get("stop")
        if ep is not None and stop is not None:
            ok = (e.get("direction") == "long" and float(stop) < float(ep)) or (e.get("direction") == "short" and float(stop) > float(ep))
            _item(items,event_id,None,"stop_side",ok,"stop is on wrong side" if not ok else "",{"entry":ep,"stop":stop,"direction":e.get("direction")})

        for n in ens:
            node_id = n["node_id"]
            answer = bool(n.get("answer"))
            dseq, aseq = n.get("decision_seq"), n.get("anchor_seq")
            _item(items,event_id,node_id,"false_has_death_point",answer or (dseq is not None and n.get("decision_time") and n.get("reason_code")),
                  "NO node lacks causal decision position/reason")
            if aseq is not None and dseq is not None:
                _item(items,event_id,node_id,"causal_anchor_before_decision",int(aseq) <= int(dseq),
                      "anchor_seq occurs after decision_seq",{"anchor_seq":aseq,"decision_seq":dseq})
            if n.get("start_seq") is not None and n.get("end_seq") is not None:
                _item(items,event_id,node_id,"geometry_start_end",int(n["start_seq"]) <= int(n["end_seq"]),
                      "start_seq occurs after end_seq")
            if physical_validate and dseq is not None:
                raw = physical_cache.get((str(e.get("source_file") or ""), int(dseq)))
                _item(items,event_id,node_id,"physical_row_exists",raw is not None,"decision_seq not found in source parquet")
                if raw is not None:
                    if n.get("decision_price") is not None and raw.get("price") is not None:
                        ok = abs(float(n["decision_price"]) - float(raw["price"])) < 1e-9
                        _item(items,event_id,node_id,"physical_decision_price",ok,"persisted decision_price != source _seq price",
                              {"persisted":n.get("decision_price"),"source":raw.get("price"),"seq":dseq})
                    if n.get("decision_time") and raw.get("datetime"):
                        # String-normalized comparison is enough to catch index mapping bugs without timezone assumptions.
                        p = str(n["decision_time"]).replace(" ","T")
                        s = str(raw["datetime"]).replace(" ","T")
                        ok = p[:19] == s[:19]
                        _item(items,event_id,node_id,"physical_decision_time",ok,"persisted decision_time != source _seq datetime",
                              {"persisted":n.get("decision_time"),"source":raw.get("datetime"),"seq":dseq})

    failed = [x for x in items if not x["passed"]]
    sanity_run_id = "sanity-" + uuid.uuid4().hex[:12]
    status = "PASS" if not failed else "FAIL"
    with tx(event_db) as con:
        con.execute("INSERT INTO event_sanity_runs(sanity_run_id,research_run_id,created_at,status,total_checks,failed_checks,details_json) VALUES(?,?,?,?,?,?,?)",
                    (sanity_run_id,research_run_id,utcnow(),status,len(items),len(failed),json.dumps({"physical_validate":physical_validate},ensure_ascii=False)))
        con.executemany("INSERT INTO event_sanity_items(sanity_run_id,event_id,node_id,check_name,passed,message,details_json) VALUES(?,?,?,?,?,?,?)",
                        [(sanity_run_id,x["event_id"],x["node_id"],x["check_name"],int(x["passed"]),x["message"],json.dumps(x["details"],ensure_ascii=False,default=str)) for x in items])
    return {"sanity_run_id":sanity_run_id,"research_run_id":research_run_id,"status":status,
            "total_checks":len(items),"failed_checks":len(failed),"failures":failed[:200]}
