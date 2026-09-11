from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from server.v5.real_mtx_bootstrap import bootstrap_real_mtx_campaign


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Atomically intake and freeze the governed Real MTX D/V/H campaign. "
            "All three physical Parquet files must pass before any campaign row is written."
        )
    )
    p.add_argument("--event-db", required=True, help="V5 event SQLite path")
    p.add_argument("--data-root", required=True, help="directory containing physical MTX Parquet files")
    p.add_argument("--campaign-id", required=True)
    p.add_argument("--name", default="Real MTX D/V/H Campaign")
    p.add_argument("--description", default="Governed Real MTX Discovery/Validation/Final Holdout campaign")
    p.add_argument("--notes", default="")
    p.add_argument("--discovery", default="MTX_2025.parquet")
    p.add_argument("--discovery-year", type=int, default=2025)
    p.add_argument("--validation", default="MTX_2024.parquet")
    p.add_argument("--validation-year", type=int, default=2024)
    p.add_argument("--holdout", default="MTX_2026.parquet")
    p.add_argument("--holdout-year", type=int, default=2026)
    p.add_argument("--out", help="optional JSON output path")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    specs = [
        {
            "dataset_id": f"mtx-{args.discovery_year}-discovery",
            "role": "DISCOVERY",
            "year": args.discovery_year,
            "source_file": args.discovery,
        },
        {
            "dataset_id": f"mtx-{args.validation_year}-validation",
            "role": "VALIDATION",
            "year": args.validation_year,
            "source_file": args.validation,
        },
        {
            "dataset_id": f"mtx-{args.holdout_year}-final-holdout",
            "role": "FINAL_HOLDOUT",
            "year": args.holdout_year,
            "source_file": args.holdout,
        },
    ]
    try:
        campaign = bootstrap_real_mtx_campaign(
            Path(args.event_db),
            Path(args.data_root),
            args.campaign_id,
            args.name,
            specs,
            description=args.description,
            notes=args.notes,
        )
        payload = {
            "status": "PASS",
            "campaign_id": campaign["campaign_id"],
            "frozen": bool(campaign["frozen"]),
            "frozen_at": campaign.get("frozen_at"),
            "dataset_evidence_policy": (campaign.get("governance") or {}).get("dataset_evidence_policy"),
            "datasets": [
                {
                    "dataset_id": d["dataset_id"],
                    "role": d["role"],
                    "year": d["year"],
                    "source_file": d["source_file"],
                    "sha256": d["sha256"],
                    "intake_report_hash": ((d.get("metadata") or {}).get("real_mtx_intake") or {}).get("report_hash"),
                    "start_time": d.get("start_time"),
                    "end_time": d.get("end_time"),
                }
                for d in campaign.get("datasets") or []
            ],
        }
        code = 0
    except Exception as exc:
        payload = {
            "status": "FAIL",
            "campaign_id": args.campaign_id,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "database_mutation_contract": "NO_CAMPAIGN_WRITE_BEFORE_ALL_DVH_PREFLIGHT_PASS",
        }
        code = 2

    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
