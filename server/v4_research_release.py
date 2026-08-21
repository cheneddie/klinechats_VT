from __future__ import annotations

"""Release research governance for Fabio Decision Gym V4.

This module implements the research-process requirements that sit above the
V4.1 causal scanner:

- versioned, traceable research runs;
- explicit SQLite schema versioning;
- a formal Event Sanity Gate before statistical interpretation;
- reverse-audit opportunity-cost accounting;
- sequential gate contribution analysis;
- trade-management favorable capture ratio;
- a production-oriented node classification vocabulary.

The raw MTX Parquet remains the source of truth.  The SQLite event store is an
index/derived research artifact and must remain rebuildable from raw data.
"""

import hashlib
import json
import math
import os
import statistics
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .v4_audit_final import BO_CHAIN, MR_CHAIN, reverse_node_audit
from .v4_engine import migrate_v4_schema
from .v4_replay_final import read_tick_path

RESEARCH_SCHEMA_VERSION = 5
AUDIT_VERSION = "V4.2_EDGE_AUDIT"
OUTCOME_VERSION = "V4.2_PHYSICAL_TICK"
MANAGEMENT_VERSION = "V4.2_CAPTURE"
VISUAL_SCHEMA_VERSION = 4
CONTRACT_POLICY_VERSION = "STRICT_CALENDAR_FRONT_CAUSAL"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rowdict(row) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _json(text, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(text or "")
    except Exception:
        return default


def migrate_release_schema(con) -> None:
    """Migrate V4 research tables without destroying older derived data."""
    migrate_v4_schema(con)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS research_runs(
          run_id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          status TEXT NOT NULL,
          years_json TEXT,
          scanner_version TEXT,
          strategy_version_mr TEXT,
          strategy_version_bo TEXT,
          config_hash TEXT,
          visual_schema_version INTEGER,
          contract_policy_version TEXT,
          audit_version TEXT,
          outcome_version TEXT,
          management_version TEXT,
          git_commit TEXT,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          details_json TEXT
        );

        CREATE TABLE IF NOT EXISTS event_sanity_runs(
          run_id TEXT PRIMARY KEY,
          years_json TEXT,
          physical INTEGER NOT NULL DEFAULT 0,
          ok INTEGER NOT NULL,
          error_count INTEGER NOT NULL,
          warning_count INTEGER NOT NULL,
          funnel_json TEXT,
          details_json TEXT,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS training_attempts(
          attempt_id TEXT PRIMARY KEY,
          event_id TEXT NOT NULL,
          node_id TEXT NOT NULL,
          human_answer INTEGER,
          correct INTEGER,
          confidence INTEGER,
          reaction_ms INTEGER,
          mode TEXT,
          difficulty INTEGER,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_training_node_time
          ON training_attempts(node_id,created_at);
        CREATE INDEX IF NOT EXISTS ix_training_event
          ON training_attempts(event_id);
        """
    )
    current = int(con.execute("PRAGMA user_version").fetchone()[0])
    if current < RESEARCH_SCHEMA_VERSION:
        con.execute(f"PRAGMA user_version={RESEARCH_SCHEMA_VERSION}")
    now = _utcnow()
    meta = {
        "research_schema_version": str(RESEARCH_SCHEMA_VERSION),
        "audit_version": AUDIT_VERSION,
        "outcome_version": OUTCOME_VERSION,
        "management_version": MANAGEMENT_VERSION,
        "visual_schema_version": str(VISUAL_SCHEMA_VERSION),
        "contract_policy_version": CONTRACT_POLICY_VERSION,
    }
    for key, value in meta.items():
        con.execute(
            """INSERT INTO schema_meta(key,value,updated_at) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
            (key, value, now),
        )
    con.commit()


def strategy_config_hash(project_root: Path | None = None) -> str:
    """Hash versioned strategy configs so every research run is reproducible."""
    root = project_root or Path(__file__).resolve().parents[1]
    folder = root / "config" / "strategies"
    h = hashlib.sha256()
    for path in sorted(folder.glob("*.json")):
        h.update(path.name.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def provenance_manifest(project_root: Path | None = None) -> dict[str, Any]:
    return {
        "research_schema_version": RESEARCH_SCHEMA_VERSION,
        "audit_version": AUDIT_VERSION,
        "outcome_version": OUTCOME_VERSION,
        "management_version": MANAGEMENT_VERSION,
        "visual_schema_version": VISUAL_SCHEMA_VERSION,
        "contract_policy_version": CONTRACT_POLICY_VERSION,
        "config_hash": strategy_config_hash(project_root),
        "git_commit": os.environ.get("FABIO_GIT_COMMIT") or os.environ.get("GITHUB_SHA"),
    }


def start_research_run(
    con,
    *,
    kind: str,
    years=None,
    scanner_version: str = "V4.1",
    strategy_version_mr: str = "MR_BROAD_V3",
    strategy_version_bo: str = "BO_RETEST_V2",
    details: dict[str, Any] | None = None,
) -> str:
    """Create a unique result-set identity; never reuse an old run id."""
    migrate_release_schema(con)
    manifest = provenance_manifest()
    run_id = f"{kind}-{uuid.uuid4().hex[:12]}"
    con.execute(
        """INSERT INTO research_runs(
        run_id,kind,status,years_json,scanner_version,strategy_version_mr,strategy_version_bo,
        config_hash,visual_schema_version,contract_policy_version,audit_version,outcome_version,
        management_version,git_commit,started_at,details_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id,
            kind,
            "running",
            json.dumps(years or [], ensure_ascii=False),
            scanner_version,
            strategy_version_mr,
            strategy_version_bo,
            manifest["config_hash"],
            manifest["visual_schema_version"],
            manifest["contract_policy_version"],
            manifest["audit_version"],
            manifest["outcome_version"],
            manifest["management_version"],
            manifest["git_commit"],
            _utcnow(),
            json.dumps(details or {}, ensure_ascii=False),
        ),
    )
    con.commit()
    return run_id


def finish_research_run(con, run_id: str, *, status: str, details: dict[str, Any] | None = None) -> None:
    """Only operational status/details are updated; the run identity/provenance stays fixed."""
    row = con.execute("SELECT details_json FROM research_runs WHERE run_id=?", (run_id,)).fetchone()
    old = _json(row["details_json"] if row else None)
    old.update(details or {})
    con.execute(
        "UPDATE research_runs SET status=?,finished_at=?,details_json=? WHERE run_id=?",
        (status, _utcnow(), json.dumps(old, ensure_ascii=False), run_id),
    )
    con.commit()


def classify_release_status(status: str, details: dict[str, Any] | None = None) -> str:
    """Translate low-level audit status into the production research vocabulary."""
    status = (status or "").lower()
    mapping = {
        "candidate_keep": "CORE",
        "neutral": "OPTIONAL",
        "redundant": "REDUNDANT",
        "harmful": "HARMFUL",
        "insufficient": "INSUFFICIENT",
    }
    base = mapping.get(status, "OPTIONAL")
    if base in {"REDUNDANT", "HARMFUL", "INSUFFICIENT"}:
        return base
    per_year = (details or {}).get("per_year") or {}
    signed = []
    for item in per_year.values():
        if int(item.get("n") or 0) < 50:
            continue
        d = item.get("delta_control_avg_r")
        if d is None or abs(float(d)) < 1e-12:
            continue
        signed.append(1 if float(d) > 0 else -1)
    if len(signed) >= 2 and min(signed) < 0 < max(signed):
        return "REGIME_DEPENDENT"
    return base


def favorable_capture_ratio(realized_r, mfe_r):
    """Share of available favorable excursion actually monetized.

    Negative realized R has zero favorable capture.  This is intentionally not
    an efficiency score for losing trades; loss quality remains an MAE/tail-risk
    question.
    """
    if realized_r is None or mfe_r is None:
        return None
    mfe = float(mfe_r)
    if not math.isfinite(mfe) or mfe <= 0:
        return None
    realized = float(realized_r)
    if not math.isfinite(realized):
        return None
    return max(0.0, realized) / mfe


def _control_r(strategy: str, management_json: str | None):
    name = "fixed_0.75R" if strategy == "MR" else "fixed_1R"
    obj = _json(management_json)
    value = (obj.get(name) or {}).get("r")
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def _rate(rows, key: str):
    return sum(bool(x.get(key)) for x in rows) / len(rows) if rows else None


def _avg(values):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return sum(vals) / len(vals) if vals else None


def _median(values):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return statistics.median(vals) if vals else None


def _query_terminal_rows(con, years=None):
    where = ["json_extract(e.features_json,'$.terminal_signal')=1"]
    args: list[Any] = []
    if years:
        marks = ",".join("?" for _ in years)
        where.append(f"e.year IN ({marks})")
        args.extend(int(x) for x in years)
    rows = con.execute(
        """SELECT e.event_id,e.year,e.trading_date,e.strategy,e.direction,e.result,e.entry_seq,
                  e.entry_price,e.stop,e.features_json,o.mfe_r,o.mae_r,o.hit_1r,o.hit_2r,o.hit_3r,
                  o.hit_stop,o.management_json
           FROM events e JOIN opportunity_outcomes o ON o.event_id=e.event_id
           WHERE """ + " AND ".join(where),
        args,
    ).fetchall()
    return [_rowdict(x) for x in rows]


def enrich_reverse_audit(con, audit_result: dict[str, Any], years=None) -> dict[str, Any]:
    """Add opportunity cost and full right-tail rates to a fresh reverse audit."""
    migrate_release_schema(con)
    terminal = _query_terminal_rows(con, years)
    node_rows = con.execute(
        "SELECT event_id,node_id,answer FROM node_instances"
    ).fetchall()
    answers = {(r["event_id"], r["node_id"]): bool(r["answer"]) for r in node_rows}
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in terminal:
        row["control_r"] = _control_r(row["strategy"], row.get("management_json"))
    for rec in audit_result.get("rows") or []:
        key = (rec["strategy"], rec["node_id"])
        if key not in by_key:
            for row in terminal:
                answer = answers.get((row["event_id"], rec["node_id"]))
                if answer is None or row["strategy"] != rec["strategy"]:
                    continue
                x = dict(row)
                x["answer"] = answer
                by_key[key].append(x)
        rows = by_key[key]
        passed = [x for x in rows if x["answer"]]
        failed = [x for x in rows if not x["answer"]]
        rejected = [x.get("control_r") for x in failed if x.get("control_r") is not None]
        rejected_pos = [x for x in rejected if x > 0]
        rejected_neg = [x for x in rejected if x < 0]
        details = rec.setdefault("details", {})
        details.update(
            audit_version=AUDIT_VERSION,
            rejected_total_r=sum(rejected),
            rejected_positive_tail_r=sum(rejected_pos),
            rejected_negative_tail_r=sum(rejected_neg),
            pass_1r_rate=_rate(passed, "hit_1r"),
            fail_1r_rate=_rate(failed, "hit_1r"),
            pass_2r_rate=_rate(passed, "hit_2r"),
            fail_2r_rate=_rate(failed, "hit_2r"),
            pass_3r_rate=_rate(passed, "hit_3r"),
            fail_3r_rate=_rate(failed, "hit_3r"),
            opportunity_cost_interpretation=(
                "Rejected Total R is signed. Positive means the gate rejected net profitable control-R; "
                "negative means it rejected net losing control-R."
            ),
        )
        details["classification"] = classify_release_status(details.get("status", ""), details)
        audit_id = rec.get("audit_id")
        if audit_id:
            con.execute(
                "UPDATE node_edge_audit SET details_json=? WHERE audit_id=? AND node_id=? AND strategy=?",
                (json.dumps(details, ensure_ascii=False), audit_id, rec["node_id"], rec["strategy"]),
            )
    con.commit()
    audit_result["audit_version"] = AUDIT_VERSION
    audit_result["evidence_scope"] = "relaxed terminal opportunities; physical-tick outcomes"
    return audit_result


def sequential_gate_contribution(con, years=None) -> dict[str, list[dict[str, Any]]]:
    """Measure incremental contribution of each gate in actual chain order."""
    migrate_release_schema(con)
    terminal = _query_terminal_rows(con, years)
    ids = [x["event_id"] for x in terminal]
    answers: dict[str, dict[str, bool]] = defaultdict(dict)
    if ids:
        # Chunk to stay below SQLite variable limits on large studies.
        for start in range(0, len(ids), 800):
            chunk = ids[start:start + 800]
            marks = ",".join("?" for _ in chunk)
            for r in con.execute(
                f"SELECT event_id,node_id,answer FROM node_instances WHERE event_id IN ({marks})", chunk
            ).fetchall():
                answers[r["event_id"]][r["node_id"]] = bool(r["answer"])
    for row in terminal:
        row["control_r"] = _control_r(row["strategy"], row.get("management_json"))
    output: dict[str, list[dict[str, Any]]] = {}
    for strategy, chain in (("MR", MR_CHAIN), ("BO", BO_CHAIN)):
        universe = [x for x in terminal if x["strategy"] == strategy]
        rows_out = []
        previous = None
        prefix: list[str] = []
        for node in chain:
            prefix.append(node)
            sub = [
                x for x in universe
                if all(answers.get(x["event_id"], {}).get(n, False) for n in prefix)
            ]
            avg_r = _avg([x.get("control_r") for x in sub])
            total_r = sum(x.get("control_r") or 0.0 for x in sub)
            rec = {
                "node_id": node,
                "required_prefix": list(prefix),
                "n": len(sub),
                "hit_1r_rate": _rate(sub, "hit_1r"),
                "hit_2r_rate": _rate(sub, "hit_2r"),
                "hit_3r_rate": _rate(sub, "hit_3r"),
                "avg_control_r": avg_r,
                "total_control_r": total_r,
                "delta_n_vs_previous": None if previous is None else len(sub) - previous["n"],
                "delta_avg_r_vs_previous": None if previous is None or avg_r is None or previous["avg_control_r"] is None else avg_r - previous["avg_control_r"],
                "delta_total_r_vs_previous": None if previous is None else total_r - previous["total_control_r"],
            }
            rows_out.append(rec)
            previous = rec
        output[strategy] = rows_out
    return output


def management_capture_summary(con, strategy: str | None = None) -> dict[str, Any]:
    """Summarize extraction quality relative to each opportunity's MFE."""
    migrate_release_schema(con)
    sql = "SELECT strategy,mfe_r,management_json FROM opportunity_outcomes"
    args: list[Any] = []
    if strategy:
        sql += " WHERE strategy=?"
        args.append(strategy)
    rows = con.execute(sql, args).fetchall()
    groups: dict[tuple[str, str], list[tuple[float, float | None]]] = defaultdict(list)
    for row in rows:
        management = _json(row["management_json"])
        for name, item in management.items():
            value = item.get("r")
            if value is None:
                continue
            realized = float(value)
            groups[(row["strategy"], name)].append((realized, favorable_capture_ratio(realized, row["mfe_r"])))
    items = []
    for (st, name), vals in sorted(groups.items()):
        rs = [x[0] for x in vals]
        captures = [x[1] for x in vals if x[1] is not None]
        pos = sum(x for x in rs if x > 0)
        neg = abs(sum(x for x in rs if x < 0))
        items.append(
            {
                "strategy": st,
                "name": name,
                "n": len(rs),
                "avg_r": _avg(rs),
                "total_r": sum(rs),
                "profit_factor": pos / neg if neg > 0 else None,
                "capture_n": len(captures),
                "avg_favorable_capture_ratio": _avg(captures),
                "median_favorable_capture_ratio": _median(captures),
                "capture_definition": "max(realized_R,0) / MFE_R when MFE_R > 0",
            }
        )
    return {"management_version": MANAGEMENT_VERSION, "items": items}


def _event_filters(years=None):
    where = []
    args: list[Any] = []
    if years:
        marks = ",".join("?" for _ in years)
        where.append(f"year IN ({marks})")
        args.extend(int(x) for x in years)
    return (" WHERE " + " AND ".join(where)) if where else "", args


def event_sanity_check(
    con,
    root: Path | None = None,
    years=None,
    *,
    require_physical: bool = False,
    max_errors: int = 500,
) -> dict[str, Any]:
    """Formal pre-audit gate for persisted V4 events.

    Static checks always run.  Physical checks additionally prove that persisted
    node/entry prices map back to the exact source `_seq` in raw Parquet.
    """
    migrate_release_schema(con)
    suffix, args = _event_filters(years)
    events = [_rowdict(r) for r in con.execute("SELECT * FROM events" + suffix, args).fetchall()]
    event_ids = {x["event_id"] for x in events}
    nodes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    if event_ids:
        ids = list(event_ids)
        for start in range(0, len(ids), 800):
            chunk = ids[start:start + 800]
            marks = ",".join("?" for _ in chunk)
            for r in con.execute(
                f"SELECT * FROM node_instances WHERE event_id IN ({marks})", chunk
            ).fetchall():
                d = _rowdict(r)
                nodes[d["event_id"]][d["node_id"]] = d

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def issue(kind: str, event_id: str, code: str, **extra):
        target = errors if kind == "error" else warnings
        if len(target) < max_errors:
            target.append({"event_id": event_id, "code": code, **extra})

    attempts = set()
    funnel = {
        "events": len(events),
        "trading_days": len({x["trading_date"] for x in events}),
        "mr_candidates": 0,
        "bo_candidates": 0,
        "wait_candidates": 0,
        "terminal_opportunities": 0,
        "strict_entries": 0,
    }
    for e in events:
        eid = e["event_id"]
        attempts.add(eid.rsplit("-", 1)[0])
        strategy = e.get("strategy")
        if strategy == "MR":
            funnel["mr_candidates"] += 1
        elif strategy == "BO":
            funnel["bo_candidates"] += 1
        else:
            funnel["wait_candidates"] += 1
        features = _json(e.get("features_json"))
        if features.get("terminal_signal"):
            funnel["terminal_opportunities"] += 1
        if e.get("result") == "ENTRY":
            funnel["strict_entries"] += 1
            if not features.get("strict_chain_pass"):
                issue("error", eid, "ENTRY_WITHOUT_STRICT_CHAIN_PASS")
        if e.get("entry_seq") is not None:
            if e.get("entry_price") is None or e.get("stop") is None:
                issue("error", eid, "STRICT_ENTRY_MISSING_PRICE_OR_STOP")
            elif e.get("direction") == "long" and not float(e["stop"]) < float(e["entry_price"]):
                issue("error", eid, "LONG_STOP_NOT_BELOW_ENTRY")
            elif e.get("direction") == "short" and not float(e["stop"]) > float(e["entry_price"]):
                issue("error", eid, "SHORT_STOP_NOT_ABOVE_ENTRY")
        terminal_seq = features.get("terminal_entry_seq")
        if terminal_seq is not None and e.get("entry_seq") is not None and int(terminal_seq) > int(e["entry_seq"]):
            issue("error", eid, "TERMINAL_ENTRY_AFTER_STRICT_ENTRY")
        if strategy == "BO" and e.get("result") == "ENTRY":
            response = nodes[eid].get("BO_RESPONSE") or {}
            if not bool(response.get("answer")):
                issue("error", eid, "BO_ENTRY_WITHOUT_RESPONSE")
            elif response.get("decision_seq") is not None and int(e["entry_seq"]) != int(response["decision_seq"]):
                issue("error", eid, "BO_STRICT_ENTRY_NOT_AT_RESPONSE", entry_seq=e["entry_seq"], response_seq=response["decision_seq"])

        for node_id, n in nodes[eid].items():
            if not n.get("reason_code"):
                issue("error", eid, "NODE_REASON_MISSING", node_id=node_id)
            if not bool(n.get("answer")):
                missing = [k for k in ("decision_seq", "decision_time", "decision_price") if n.get(k) is None]
                if missing:
                    issue("error", eid, "FALSE_NODE_NOT_CAUSALLY_LOCATED", node_id=node_id, missing=missing)
            if n.get("anchor_seq") is not None and n.get("decision_seq") is not None and int(n["anchor_seq"]) > int(n["decision_seq"]):
                issue("error", eid, "ANCHOR_AFTER_DECISION", node_id=node_id, anchor_seq=n["anchor_seq"], decision_seq=n["decision_seq"])

    funnel["auction_attempts"] = len(attempts)
    strict_rate = funnel["strict_entries"] / funnel["terminal_opportunities"] if funnel["terminal_opportunities"] else None
    funnel["terminal_to_strict_rate"] = strict_rate

    physical_checked = 0
    if require_physical:
        if root is None:
            raise ValueError("root is required when require_physical=True")
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for e in events:
            grouped[(e["source_file"], e["trading_date"], e["contract"])].append(e)
        for items in grouped.values():
            relevant = []
            for e in items:
                relevant.extend(
                    int(n["decision_seq"])
                    for n in nodes[e["event_id"]].values()
                    if n.get("decision_seq") is not None
                )
                if e.get("entry_seq") is not None:
                    relevant.append(int(e["entry_seq"]))
                f = _json(e.get("features_json"))
                if f.get("terminal_entry_seq") is not None:
                    relevant.append(int(f["terminal_entry_seq"]))
            if not relevant:
                continue
            representative = dict(items[0])
            try:
                path = read_tick_path(root, representative, min(relevant), 1)
            except Exception as exc:
                for e in items:
                    issue("error", e["event_id"], "PHYSICAL_PATH_READ_FAILED", message=f"{type(exc).__name__}: {exc}")
                continue
            prices = {int(r["_seq"]): float(r["price"]) for _, r in path.iterrows()}
            for e in items:
                eid = e["event_id"]
                for node_id, n in nodes[eid].items():
                    seq = n.get("decision_seq")
                    price = n.get("decision_price")
                    if seq is None or price is None:
                        continue
                    actual = prices.get(int(seq))
                    physical_checked += 1
                    if actual is None:
                        issue("error", eid, "DECISION_SEQ_NOT_IN_PHYSICAL_PATH", node_id=node_id, decision_seq=seq)
                    elif abs(actual - float(price)) > 1e-9:
                        issue("error", eid, "DECISION_PRICE_PHYSICAL_MISMATCH", node_id=node_id, decision_seq=seq, persisted=price, actual=actual)
                if e.get("entry_seq") is not None and e.get("entry_price") is not None:
                    actual = prices.get(int(e["entry_seq"]))
                    physical_checked += 1
                    if actual is None or abs(actual - float(e["entry_price"])) > 1e-9:
                        issue("error", eid, "STRICT_ENTRY_PHYSICAL_MISMATCH", entry_seq=e["entry_seq"], persisted=e["entry_price"], actual=actual)
                f = _json(e.get("features_json"))
                if f.get("terminal_entry_seq") is not None and f.get("terminal_entry_price") is not None:
                    actual = prices.get(int(f["terminal_entry_seq"]))
                    physical_checked += 1
                    if actual is None or abs(actual - float(f["terminal_entry_price"])) > 1e-9:
                        issue("error", eid, "TERMINAL_ENTRY_PHYSICAL_MISMATCH", terminal_entry_seq=f["terminal_entry_seq"], persisted=f["terminal_entry_price"], actual=actual)

    run_id = "sanity-" + uuid.uuid4().hex[:12]
    result = {
        "run_id": run_id,
        "ok": not errors,
        "years": [int(x) for x in years] if years else None,
        "physical_requested": bool(require_physical),
        "physical_points_checked": physical_checked,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "funnel": funnel,
        "manual_spot_check_required": {
            "MR_YES": 20,
            "MR_NO": 20,
            "BO_YES": 20,
            "BO_NO": 20,
            "WAIT_OR_NEAR_MISS": 20,
        },
        "gate_rule": "Do not interpret reverse-audit statistics until this gate passes and manual replay spot checks are completed.",
    }
    con.execute(
        """INSERT INTO event_sanity_runs(
        run_id,years_json,physical,ok,error_count,warning_count,funnel_json,details_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            run_id,
            json.dumps(result["years"] or [], ensure_ascii=False),
            int(bool(require_physical)),
            int(bool(result["ok"])),
            result["error_count"],
            result["warning_count"],
            json.dumps(funnel, ensure_ascii=False),
            json.dumps({"errors": errors, "warnings": warnings, "manual_spot_check_required": result["manual_spot_check_required"]}, ensure_ascii=False),
            _utcnow(),
        ),
    )
    con.commit()
    return result


__all__ = [
    "RESEARCH_SCHEMA_VERSION",
    "AUDIT_VERSION",
    "OUTCOME_VERSION",
    "MANAGEMENT_VERSION",
    "VISUAL_SCHEMA_VERSION",
    "CONTRACT_POLICY_VERSION",
    "migrate_release_schema",
    "strategy_config_hash",
    "provenance_manifest",
    "start_research_run",
    "finish_research_run",
    "classify_release_status",
    "favorable_capture_ratio",
    "enrich_reverse_audit",
    "sequential_gate_contribution",
    "management_capture_summary",
    "event_sanity_check",
    "reverse_node_audit",
]
