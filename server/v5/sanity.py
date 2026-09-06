from __future__ import annotations

import json
import uuid
from bisect import bisect_right
from pathlib import Path
from typing import Any

from .storage import EVALUATION_STATES, connect, migrate_event_db, tx, utcnow


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
    items.append(
        {
            "event_id": event_id,
            "node_id": node_id,
            "check_name": name,
            "passed": bool(passed),
            "message": message,
            "details": details or {},
        }
    )


def _no_decision_assertion(node):
    return (
        node.get("decision_seq") is None
        and node.get("decision_time") is None
        and node.get("decision_price") is None
        and node.get("anchor_seq") is None
        and node.get("anchor_time") is None
        and node.get("anchor_price") is None
    )


def _physical_check(items, cache, source, event_id, node_id, seq, time_value, price_value, prefix):
    if seq is None:
        return
    raw = cache.get((source, int(seq)))
    _item(items, event_id, node_id, f"physical_{prefix}_row_exists", raw is not None,
          f"{prefix}_seq not found in source parquet")
    if raw is None:
        return
    if price_value is not None and raw.get("price") is not None:
        ok = abs(float(price_value) - float(raw["price"])) < 1e-9
        _item(
            items, event_id, node_id, f"physical_{prefix}_price", ok,
            f"persisted {prefix}_price != source _seq price",
            {"persisted": price_value, "source": raw.get("price"), "seq": seq},
        )
    if time_value and raw.get("datetime"):
        persisted = str(time_value).replace(" ", "T")
        source_time = str(raw["datetime"]).replace(" ", "T")
        ok = persisted[:19] == source_time[:19]
        _item(
            items, event_id, node_id, f"physical_{prefix}_time", ok,
            f"persisted {prefix}_time != source _seq datetime",
            {"persisted": time_value, "source": raw.get("datetime"), "seq": seq},
        )


def run_event_sanity(
    event_db: str | Path,
    data_root: str | Path,
    research_run_id: str,
    *,
    physical_validate: bool = True,
) -> dict[str, Any]:
    migrate_event_db(event_db)
    con = connect(event_db)
    try:
        events = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM events WHERE research_run_id=? ORDER BY source_file,trading_date,attempt_start_seq,event_id",
                (research_run_id,),
            ).fetchall()
        ]
        nodes = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM event_nodes WHERE research_run_id=? ORDER BY event_id,node_id",
                (research_run_id,),
            ).fetchall()
        ]
    finally:
        con.close()

    by_event: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        by_event.setdefault(node["event_id"], []).append(node)

    items: list[dict[str, Any]] = []
    root = Path(data_root)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_source.setdefault(str(event.get("source_file") or ""), []).append(event)

    physical_cache: dict[tuple[str, int], dict[str, Any]] = {}
    if physical_validate:
        for source, evs in by_source.items():
            seqs = []
            for event in evs:
                for node in by_event.get(event["event_id"], []):
                    if node.get("decision_seq") is not None:
                        seqs.append(int(node["decision_seq"]))
                    if node.get("resolution_seq") is not None:
                        seqs.append(int(node["resolution_seq"]))
            for seq, row in _load_physical_rows(root / source, seqs).items():
                physical_cache[(source, seq)] = row

    seen_geometry: set[tuple[Any, ...]] = set()
    for event in events:
        event_id = event["event_id"]
        ens = by_event.get(event_id, [])
        key = (
            event.get("trading_date"),
            event.get("contract"),
            event.get("strategy"),
            event.get("attempt_start_seq"),
        )
        _item(
            items, event_id, None, "duplicate_event_geometry", key not in seen_geometry,
            "duplicate auction/strategy geometry" if key in seen_geometry else "",
        )
        seen_geometry.add(key)

        ep, stop = event.get("entry_price"), event.get("stop")
        if ep is not None and stop is not None:
            ok = (
                (event.get("direction") == "long" and float(stop) < float(ep))
                or (event.get("direction") == "short" and float(stop) > float(ep))
            )
            _item(
                items, event_id, None, "stop_side", ok,
                "stop is on wrong side" if not ok else "",
                {"entry": ep, "stop": stop, "direction": event.get("direction")},
            )

        for node in ens:
            node_id = node["node_id"]
            state = str(node.get("evaluation_state") or "").upper()
            _item(
                items, event_id, node_id, "evaluation_state_valid",
                state in EVALUATION_STATES,
                f"invalid evaluation_state: {state}" if state not in EVALUATION_STATES else "",
            )
            if state not in EVALUATION_STATES:
                continue

            answer = node.get("answer")
            dseq, aseq = node.get("decision_seq"), node.get("anchor_seq")
            rseq = node.get("resolution_seq")

            if state == "EVALUATED":
                _item(
                    items, event_id, node_id, "evaluated_has_binary_answer",
                    answer in (0, 1, False, True),
                    "EVALUATED node must have YES/NO answer",
                )
                _item(
                    items, event_id, node_id, "evaluated_has_decision_point",
                    dseq is not None and bool(node.get("decision_time")),
                    "EVALUATED node lacks causal decision position",
                )
                if answer in (0, False):
                    _item(
                        items, event_id, node_id, "false_has_death_point",
                        dseq is not None and bool(node.get("decision_time")) and bool(node.get("reason_code")),
                        "NO node lacks causal decision position/reason",
                    )
                if aseq is not None and dseq is not None:
                    _item(
                        items, event_id, node_id, "causal_anchor_before_decision",
                        int(aseq) <= int(dseq),
                        "anchor_seq occurs after decision_seq",
                        {"anchor_seq": aseq, "decision_seq": dseq},
                    )
            else:
                _item(
                    items, event_id, node_id, "non_evaluated_answer_is_null",
                    answer is None,
                    f"{state} node must not be coerced to YES/NO",
                )
                _item(
                    items, event_id, node_id, "non_evaluated_has_no_decision_assertion",
                    _no_decision_assertion(node),
                    f"{state} node must not assert a decision/anchor",
                )
                if state == "NOT_REACHED":
                    _item(
                        items, event_id, node_id, "not_reached_has_blocker",
                        bool(node.get("blocker_node_id")),
                        "NOT_REACHED node lacks blocker_node_id",
                    )
                _item(
                    items, event_id, node_id, "non_evaluated_has_resolution",
                    rseq is not None and bool(node.get("resolution_time")),
                    f"{state} node lacks causal resolution point",
                )

            if node.get("start_seq") is not None and node.get("end_seq") is not None:
                _item(
                    items, event_id, node_id, "geometry_start_end",
                    int(node["start_seq"]) <= int(node["end_seq"]),
                    "start_seq occurs after end_seq",
                )

            if physical_validate:
                source = str(event.get("source_file") or "")
                if state == "EVALUATED":
                    _physical_check(
                        items, physical_cache, source, event_id, node_id,
                        dseq, node.get("decision_time"), node.get("decision_price"), "decision",
                    )
                elif rseq is not None:
                    _physical_check(
                        items, physical_cache, source, event_id, node_id,
                        rseq, node.get("resolution_time"), node.get("resolution_price"), "resolution",
                    )

    failed = [x for x in items if not x["passed"]]
    sanity_run_id = "sanity-" + uuid.uuid4().hex[:12]
    status = "PASS" if not failed else "FAIL"
    with tx(event_db) as con:
        con.execute(
            "INSERT INTO event_sanity_runs(sanity_run_id,research_run_id,created_at,status,total_checks,failed_checks,details_json) VALUES(?,?,?,?,?,?,?)",
            (
                sanity_run_id, research_run_id, utcnow(), status, len(items), len(failed),
                json.dumps(
                    {
                        "physical_validate": physical_validate,
                        "node_semantics": "FOUR_STATE_V6",
                        "evaluation_universe": "EVALUATED_ONLY",
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        con.executemany(
            "INSERT INTO event_sanity_items(sanity_run_id,event_id,node_id,check_name,passed,message,details_json) VALUES(?,?,?,?,?,?,?)",
            [
                (
                    sanity_run_id, x["event_id"], x["node_id"], x["check_name"],
                    int(x["passed"]), x["message"],
                    json.dumps(x["details"], ensure_ascii=False, default=str),
                )
                for x in items
            ],
        )
    return {
        "sanity_run_id": sanity_run_id,
        "research_run_id": research_run_id,
        "status": status,
        "total_checks": len(items),
        "failed_checks": len(failed),
        "failures": failed[:200],
        "node_semantics": "FOUR_STATE_V6",
    }
