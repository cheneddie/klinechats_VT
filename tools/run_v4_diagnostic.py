from __future__ import annotations

"""Run a reproducible Fabio V4 Single-Year Diagnostic.

This runner intentionally enforces the research order documented for V4:

    scan -> physical Event Sanity Gate -> outcomes -> reverse audit
         -> ablation -> sequential contribution -> management extraction

Synthetic data may validate software, but output from synthetic data must never
be described as strategy evidence.  A real single year is still diagnostic,
not final OOS validation.
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
        funnel = {
            "events": len(event_rows),
            "trading_days": len({r["trading_date"] for r in event_rows}),
            "contracts": sorted({r["contract"] for r in event_rows if r["contract"]}),
            "auction_attempts": len({r["event_id"].rsplit("-", 1)[0] for r in event_rows}),
            "mr_candidates": sum(r["strategy"] == "MR" for r in event_rows),
            "bo_candidates": sum(r["strategy"] == "BO" for r in event_rows),
            "wait_candidates": sum(r["strategy"] not in {"MR", "BO"} for r in event_rows),
            "strict_entries": sum(r["result"] == "ENTRY" for r in event_rows),
            "terminal_opportunities": 0,
        }
        for r in event_rows:
            try:
                f = json.loads(r["features_json"] or "{}")
            except Exception:
                f = {}
            funnel["terminal_opportunities"] += int(bool(f.get("terminal_signal")))
        return {"datasets": datasets, "funnel": funnel}
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True, help="Folder containing MTX_YYYY.parquet")
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--year", type=int, action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-after-days", type=int, default=1)
    ap.add_argument("--skip-scan", action="store_true", help="Use an already-built V4 event DB")
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
        migrate_release_schema(con)
        run_id = start_research_run(
            con,
            kind="single_year_diagnostic" if len(years) == 1 else "multi_year_diagnostic",
            years=years,
            details={
                "root": str(args.root),
                "db": str(args.db),
                "out": str(args.out),
                "evidence_label": "Single-Year Diagnostic" if len(years) == 1 else "Multi-Year Diagnostic",
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
    manifest.update(run_id=run_id, years=years, started_at=utcnow())
    dump(args.out / "provenance.json", manifest)

    try:
        if not args.skip_scan:
            heartbeat({"phase": "scan", "done": 0, "total": 0, "message": "Starting V4.1 release scanner"})
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

        # Formal hard gate: exact persisted decision/entry prices must map to raw physical rows.
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

        heartbeat({"phase": "outcomes", "done": 0, "total": sanity["funnel"]["terminal_opportunities"], "message": "Computing physical-tick outcome paths"})
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

        classifications = {}
        for row in audit.get("rows") or []:
            classifications[f"{row['strategy']}:{row['node_id']}"] = (row.get("details") or {}).get("classification")
        final = {
            "run_id": run_id,
            "evidence_label": "Single-Year Diagnostic" if len(years) == 1 else "Multi-Year Diagnostic",
            "years": years,
            "automatic_event_sanity": "PASS",
            "manual_replay_spot_check": "REQUIRED",
            "outcomes": outcome_count,
            "node_classifications": classifications,
            "versions": {
                "audit": AUDIT_VERSION,
                "outcome": OUTCOME_VERSION,
                "management": MANAGEMENT_VERSION,
                "contract_policy": CONTRACT_POLICY_VERSION,
                "config_hash": manifest["config_hash"],
                "git_commit": manifest["git_commit"],
            },
            "evidence_boundary": (
                "A single year is diagnostic evidence only. Do not label it final OOS or production edge. "
                "Synthetic QA is software validation only."
            ),
            "production_value_targets": {
                "MR": "candidate should support approximately 1R practical reward",
                "BO": "candidate should support approximately 2R practical reward",
                "average_profit_points": "ideally at least about 10% of representative ATR",
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
            finish_research_run(con, run_id, status="done", details={"outcomes": outcome_count, "automatic_event_sanity": "PASS"})
        finally:
            con.close()
        heartbeat({"phase": "done", "done": outcome_count, "total": outcome_count, "message": "Diagnostic computation complete; manual replay spot-check remains before interpretation"})
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
