from __future__ import annotations

"""Run a reproducible Fabio V4 diagnostic.

Research order:

    clean rebuildable year state -> scan -> physical Event Sanity Gate
    -> relaxed outcomes -> reverse audit -> ablation -> sequential contribution
    -> strict-entry outcomes -> multi-year edge map -> right-tail -> production gate

Synthetic data may validate software, but output from synthetic data must never
be described as strategy evidence.  A real single year is still diagnostic,
not final OOS validation.  Multi-year evidence is still not automatically a
live approval: cost/latency/ATR/drawdown/concentration gates remain explicit.
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from server import progress_scanner
from server.engine import connect
from server.v4_audit_final import ablation_audit, compute_outcomes, reverse_node_audit
from server.v4_multiyear import (
    MULTIYEAR_VERSION,
    PRODUCTION_GATE_VERSION,
    STRICT_OUTCOME_VERSION,
    compute_strict_outcomes,
    migrate_multiyear_schema,
    multi_year_edge_map,
    production_gate,
    right_tail_summary,
    strict_trade_summary,
)
from server.v4_release_engine import ScanConfigV4Final, scan_day_v4_final, write_events_v4
from server.v4_research_release import (
    AUDIT_VERSION,
    CONTRACT_POLICY_VERSION,
    MANAGEMENT_VERSION,
    OUTCOME_VERSION,
    enrich_reverse_audit,
    event_sanity_check,
    finish_research_run,
    management_capture_summary,
    migrate_release_schema,
    provenance_manifest,
    sequential_gate_contribution,
    start_research_run,
)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def dump(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def table_exists(con, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def write_audit_csv(path: Path, audit):
    rows = []
    for rec in audit.get("rows") or []:
        d = rec.get("details") or {}
        rows.append({
            "audit_id": rec.get("audit_id"),
            "strategy": rec.get("strategy"),
            "node_id": rec.get("node_id"),
            "classification": d.get("classification"),
            "universe": rec.get("universe"),
            "pass_count": rec.get("pass_count"),
            "fail_count": rec.get("fail_count"),
            "filter_score": rec.get("filter_score"),
            "same_seq_parent_rate": rec.get("same_seq_parent_rate"),
            "pass_avg_mfe_r": rec.get("pass_avg_mfe_r"),
            "fail_avg_mfe_r": rec.get("fail_avg_mfe_r"),
            "pass_avg_mae_r": rec.get("pass_avg_mae_r"),
            "fail_avg_mae_r": rec.get("fail_avg_mae_r"),
            "pass_1r_rate": d.get("pass_1r_rate"),
            "fail_1r_rate": d.get("fail_1r_rate"),
            "pass_2r_rate": d.get("pass_2r_rate"),
            "fail_2r_rate": d.get("fail_2r_rate"),
            "pass_3r_rate": d.get("pass_3r_rate"),
            "fail_3r_rate": d.get("fail_3r_rate"),
            "rejected_total_r": d.get("rejected_total_r"),
            "rejected_positive_tail_r": d.get("rejected_positive_tail_r"),
            "rejected_negative_tail_r": d.get("rejected_negative_tail_r"),
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["audit_id", "strategy", "node_id", "classification"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def clean_rebuildable_years(db: Path, years):
    """Remove only market-derived state for selected years before a fresh scan.

    Human `training_attempts`, research-run history and prior audit snapshots are
    deliberately preserved.  Raw Parquet is the source of truth; Events, Nodes,
    outcomes and data/contract audit rows are rebuildable and must not leak stale
    scanner generations into a new diagnostic.
    """
    con = connect(db)
    try:
        migrate_multiyear_schema(con)
        marks = ",".join("?" for _ in years)
        args = [int(x) for x in years]
        event_ids = [r["event_id"] for r in con.execute(
            f"SELECT event_id FROM events WHERE year IN ({marks})", args
        ).fetchall()]
        source_files = [r["source_file"] for r in con.execute(
            f"SELECT DISTINCT source_file FROM events WHERE year IN ({marks})", args
        ).fetchall() if r["source_file"]]
        source_files.extend(
            r["file"] for r in con.execute(
                f"SELECT file FROM datasets WHERE year IN ({marks})", args
            ).fetchall() if r["file"]
        )
        source_files = sorted(set(source_files))

        for start in range(0, len(event_ids), 800):
            chunk = event_ids[start:start + 800]
            q = ",".join("?" for _ in chunk)
            for table in ("node_instances", "opportunity_outcomes", "strict_trade_outcomes"):
                if table_exists(con, table):
                    con.execute(f"DELETE FROM {table} WHERE event_id IN ({q})", chunk)
        con.execute(f"DELETE FROM events WHERE year IN ({marks})", args)
        con.execute(f"DELETE FROM datasets WHERE year IN ({marks})", args)
        if table_exists(con, "dataset_integrity"):
            con.execute(f"DELETE FROM dataset_integrity WHERE year IN ({marks})", args)
        if table_exists(con, "contract_selection_audit") and source_files:
            q = ",".join("?" for _ in source_files)
            con.execute(f"DELETE FROM contract_selection_audit WHERE source_file IN ({q})", source_files)
        con.commit()
        return {
            "years": list(years),
            "removed_event_ids": len(event_ids),
            "source_files": source_files,
            "preserved_nonrebuildable": ["training_attempts"],
            "preserved_history": ["research_runs", "event_sanity_runs", "node_edge_audit"],
        }
    finally:
        con.close()


def db_summary(db: Path, years):
    con = connect(db)
    try:
        migrate_release_schema(con)
        marks = ",".join("?" for _ in years)
        args = [int(x) for x in years]
        event_rows = con.execute(
            f"SELECT strategy,result,features_json,trading_date,contract,event_id FROM events WHERE year IN ({marks})",
            args,
        ).fetchall()
        datasets = [dict(r) for r in con.execute(
            f"SELECT * FROM datasets WHERE year IN ({marks}) ORDER BY year,file", args
        ).fetchall()]

        integrity = []
        if table_exists(con, "dataset_integrity"):
            integrity = [dict(r) for r in con.execute(
                f"SELECT * FROM dataset_integrity WHERE year IN ({marks}) ORDER BY year,file", args
            ).fetchall()]
        files = [x["file"] for x in integrity] or [x["file"] for x in datasets]
        contract_rows = []
        if files and table_exists(con, "contract_selection_audit"):
            q = ",".join("?" for _ in files)
            contract_rows = [dict(r) for r in con.execute(
                f"SELECT * FROM contract_selection_audit WHERE source_file IN ({q}) ORDER BY trading_date",
                files,
            ).fetchall()]
            for row in contract_rows:
                for key in ("candidate_contracts_json", "candidate_volumes_raw_json", "candidate_volumes_normalized_json"):
                    try:
                        row[key.removesuffix("_json")] = json.loads(row.pop(key) or "{}")
                    except Exception:
                        row[key.removesuffix("_json")] = {}
                row["roll"] = bool(row.get("roll"))
                row["ambiguous"] = bool(row.get("ambiguous"))
                row["causal"] = bool(row.get("causal"))

        contracts_found = set()
        for row in integrity:
            try:
                contracts_found.update(json.loads(row.get("outright_contracts_json") or "[]"))
            except Exception:
                pass
        active_contracts = sorted({r["selected_contract"] for r in contract_rows if r.get("selected_contract")})
        funnel = {
            "source_rows": sum(int(x.get("source_rows") or 0) for x in integrity) if integrity else sum(int(x.get("rows") or 0) for x in datasets),
            "mtx_rows": sum(int(x.get("mtx_rows") or 0) for x in integrity) if integrity else None,
            "outright_rows": sum(int(x.get("outright_rows") or 0) for x in integrity) if integrity else None,
            "spread_removed_rows": sum(int(x.get("spread_removed_rows") or 0) for x in integrity) if integrity else None,
            "contracts_found": sorted(contracts_found),
            "active_contracts": active_contracts,
            "trading_days": len(contract_rows) if contract_rows else len({r["trading_date"] for r in event_rows}),
            "roll_days": sum(bool(r.get("roll")) for r in contract_rows),
            "events": len(event_rows),
            "auction_attempts": len({r["event_id"].rsplit("-", 1)[0] for r in event_rows}),
            "mr_candidates": sum(r["strategy"] == "MR" for r in event_rows),
            "bo_candidates": sum(r["strategy"] == "BO" for r in event_rows),
            "wait_invalid": sum(r["strategy"] not in {"MR", "BO"} for r in event_rows),
            "strict_entries": sum(r["result"] == "ENTRY" for r in event_rows),
            "terminal_opportunities": 0,
        }
        for r in event_rows:
            try:
                f = json.loads(r["features_json"] or "{}")
            except Exception:
                f = {}
            funnel["terminal_opportunities"] += int(bool(f.get("terminal_signal")))
        return {
            "years": list(years),
            "datasets": datasets,
            "dataset_integrity": integrity,
            "contract_selection": contract_rows,
            "source_order_qa_pass": bool(integrity) and all(x.get("source_order_qa") == "PASS" for x in integrity),
            "contract_policy_causal": bool(contract_rows) and all(bool(x.get("causal")) for x in contract_rows),
            "funnel": funnel,
        }
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True, help="Folder containing MTX_YYYY.parquet")
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--year", type=int, action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-after-days", type=int, default=1)
    ap.add_argument("--skip-scan", action="store_true", help="Use an already-built V4 event DB without deleting/rebuilding it")
    args = ap.parse_args()

    years = sorted(set(args.year))
    args.out.mkdir(parents=True, exist_ok=True)
    progress_file = args.out / "progress.json"
    start = time.monotonic()

    # Make the observable scanner use release semantics without changing older APIs.
    progress_scanner.scan_day = scan_day_v4_final
    progress_scanner.write_events = write_events_v4

    con = connect(args.db)
    try:
        migrate_multiyear_schema(con)
        run_id = start_research_run(
            con,
            kind="single_year_diagnostic" if len(years) == 1 else "multi_year_diagnostic",
            years=years,
            details={
                "root": str(args.root),
                "db": str(args.db),
                "out": str(args.out),
                "evidence_label": "Single-Year Diagnostic" if len(years) == 1 else "Multi-Year Diagnostic",
                "strict_outcome_version": STRICT_OUTCOME_VERSION,
                "multiyear_version": MULTIYEAR_VERSION,
                "production_gate_version": PRODUCTION_GATE_VERSION,
                "rebuild_mode": "reuse_existing" if args.skip_scan else "clean_selected_years_then_rescan",
            },
        )
    finally:
        con.close()

    def heartbeat(payload):
        row = {
            "run_id": run_id,
            "at": utcnow(),
            "elapsed_seconds": round(time.monotonic() - start, 1),
            **payload,
        }
        dump(progress_file, row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    manifest = provenance_manifest()
    manifest.update(
        run_id=run_id,
        years=years,
        started_at=utcnow(),
        strict_outcome_version=STRICT_OUTCOME_VERSION,
        multiyear_version=MULTIYEAR_VERSION,
        production_gate_version=PRODUCTION_GATE_VERSION,
        rebuild_mode="reuse_existing" if args.skip_scan else "clean_selected_years_then_rescan",
    )
    dump(args.out / "provenance.json", manifest)

    try:
        if not args.skip_scan:
            heartbeat({"phase": "clean", "done": 0, "total": 0, "message": "Removing stale rebuildable rows for selected years"})
            cleaned = clean_rebuildable_years(args.db, years)
            dump(args.out / "rebuild_cleanup.json", cleaned)
            heartbeat({"phase": "scan", "done": 0, "total": 0, "message": "Starting V4.1 release scanner from raw Parquet"})
            cfg = ScanConfigV4Final(contract_mode="strict")
            count = progress_scanner.scan_files_progress(
                args.root,
                args.db,
                years=years,
                config=cfg,
                progress=lambda p: heartbeat({"phase": "scan", **p}),
            )
            heartbeat({"phase": "scan_done", "done": count, "total": count, "message": f"{count} events persisted"})

        summary = db_summary(args.db, years)
        dump(args.out / "scan_summary.json", summary)
        if summary["source_order_qa_pass"] is False and not args.skip_scan:
            raise RuntimeError("SOURCE_ORDER_QA failed or missing")
        if summary["contract_policy_causal"] is False and not args.skip_scan:
            raise RuntimeError("CONTRACT_POLICY_CAUSAL audit failed or missing")

        # Hard gate: persisted decision/entry prices must map to raw physical rows.
        heartbeat({"phase": "event_sanity", "done": 0, "total": summary["funnel"]["events"], "message": "Validating persisted events against physical _seq"})
        con = connect(args.db)
        try:
            sanity = event_sanity_check(con, args.root, years, require_physical=True)
        finally:
            con.close()
        dump(args.out / "event_sanity.json", sanity)
        if not sanity["ok"]:
            raise RuntimeError(f"EVENT_SANITY_CHECK failed with {sanity['error_count']} errors")
        heartbeat({"phase": "event_sanity_pass", "done": sanity["physical_points_checked"], "total": sanity["physical_points_checked"], "message": "Automatic Event Sanity Gate PASS; manual replay spot-check remains required"})

        # Research universe outcomes: deliberately anchored at relaxed terminal opportunities.
        heartbeat({"phase": "outcomes", "done": 0, "total": sanity["funnel"]["terminal_opportunities"], "message": "Computing relaxed physical-tick outcome paths"})
        outcome_count = compute_outcomes(
            args.db,
            args.root,
            years,
            max(0, min(3, args.max_after_days)),
            progress=lambda p: heartbeat({"phase": "outcomes", **p}),
        )

        heartbeat({"phase": "reverse_audit", "done": 0, "total": outcome_count, "message": "Reverse auditing strict nodes"})
        audit = reverse_node_audit(args.db, years)
        con = connect(args.db)
        try:
            audit = enrich_reverse_audit(con, audit, years)
            sequential = sequential_gate_contribution(con, years)
            management = management_capture_summary(con)
        finally:
            con.close()
        ablation = ablation_audit(args.db, years)

        dump(args.out / "reverse_audit.json", audit)
        write_audit_csv(args.out / "reverse_audit.csv", audit)
        dump(args.out / "sequential_gate_contribution.json", sequential)
        dump(args.out / "ablation.json", ablation)
        dump(args.out / "management_capture.json", management)

        # Actual strategy outcomes must start from strict entry, not the relaxed audit anchor.
        heartbeat({"phase": "strict_outcomes", "done": 0, "total": summary["funnel"]["strict_entries"], "message": "Computing actual strict-entry physical outcomes"})
        strict_count = compute_strict_outcomes(
            args.db,
            args.root,
            years,
            max(0, min(3, args.max_after_days)),
            progress=lambda p: heartbeat(p),
        )
        con = connect(args.db)
        try:
            strict_summary = strict_trade_summary(con, years)
            right_tail = right_tail_summary(con, years)
            edge_map = multi_year_edge_map(con, years)
            live_gate = production_gate(con, years)
        finally:
            con.close()

        dump(args.out / "strict_trade_summary.json", strict_summary)
        dump(args.out / "right_tail.json", right_tail)
        dump(args.out / "multi_year_edge_map.json", edge_map)
        dump(args.out / "production_gate.json", live_gate)

        classifications = {}
        for row in audit.get("rows") or []:
            classifications[f"{row['strategy']}:{row['node_id']}"] = (row.get("details") or {}).get("classification")
        cross_year_classifications = {
            f"{row['strategy']}:{row['node_id']}": row.get("classification")
            for row in edge_map.get("nodes") or []
        }
        final = {
            "run_id": run_id,
            "evidence_label": "Single-Year Diagnostic" if len(years) == 1 else "Multi-Year Diagnostic",
            "years": years,
            "automatic_event_sanity": "PASS",
            "source_order_qa": "PASS" if summary.get("source_order_qa_pass") else "UNKNOWN_OR_FAIL",
            "contract_policy_qa": "PASS" if summary.get("contract_policy_causal") else "UNKNOWN_OR_FAIL",
            "manual_replay_spot_check": "REQUIRED",
            "relaxed_terminal_outcomes": outcome_count,
            "strict_entry_outcomes": strict_count,
            "node_classifications": classifications,
            "cross_year_node_classifications": cross_year_classifications,
            "production_gate": {
                "MR": live_gate.get("strategies", {}).get("MR", {}).get("status"),
                "BO": live_gate.get("strategies", {}).get("BO", {}).get("status"),
                "live_approval_is_automatic": False,
            },
            "versions": {
                "audit": AUDIT_VERSION,
                "outcome": OUTCOME_VERSION,
                "strict_outcome": STRICT_OUTCOME_VERSION,
                "management": MANAGEMENT_VERSION,
                "multiyear": MULTIYEAR_VERSION,
                "production_gate": PRODUCTION_GATE_VERSION,
                "contract_policy": CONTRACT_POLICY_VERSION,
                "config_hash": manifest["config_hash"],
                "git_commit": manifest["git_commit"],
            },
            "evidence_boundary": (
                "Single-year results are diagnostic only. Multi-year results are not automatically final OOS. "
                "Synthetic QA is software validation only. Live approval remains blocked until the explicit "
                "cost/latency/ATR/drawdown/concentration policies are measured and passed."
            ),
            "production_value_targets": {
                "MR": "candidate should support approximately 1R practical reward",
                "BO": "candidate should support approximately 2R practical reward",
                "average_profit_points": "ideally at least about 10% of representative ATR; ATR timeframe/reference remains unspecified",
                "additional_requirements": [
                    "cost robust", "latency robust", "cross-period consistency", "acceptable confidence interval",
                    "no single year/month concentration", "acceptable drawdown",
                ],
            },
            "completed_at": utcnow(),
        }
        dump(args.out / "final_summary.json", final)
        con = connect(args.db)
        try:
            finish_research_run(
                con,
                run_id,
                status="done",
                details={
                    "relaxed_terminal_outcomes": outcome_count,
                    "strict_entry_outcomes": strict_count,
                    "automatic_event_sanity": "PASS",
                    "source_order_qa": final["source_order_qa"],
                    "contract_policy_qa": final["contract_policy_qa"],
                    "production_gate": final["production_gate"],
                },
            )
        finally:
            con.close()
        heartbeat({"phase": "done", "done": strict_count, "total": strict_count, "message": "Diagnostic computation complete; manual replay spot-check and unresolved production gates remain before live interpretation"})
        return 0
    except Exception as exc:
        con = connect(args.db)
        try:
            finish_research_run(con, run_id, status="failed", details={"error": f"{type(exc).__name__}: {exc}"})
        finally:
            con.close()
        heartbeat({"phase": "failed", "done": 0, "total": 0, "message": f"{type(exc).__name__}: {exc}"})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
