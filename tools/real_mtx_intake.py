from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.data_intake import IntakePolicy, inspect_mtx_parquet


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Stream-audit a real MTX Parquet source before campaign registration."
    )
    ap.add_argument("parquet", help="Path to MTX_YYYY.parquet")
    ap.add_argument("--expected-year", type=int, default=None)
    ap.add_argument("--product", default="MTX")
    ap.add_argument("--session-start", default="08:45:00")
    ap.add_argument("--session-end", default="13:45:00")
    ap.add_argument("--batch-size", type=int, default=250_000)
    ap.add_argument("--allow-synthetic", action="store_true", help="QA only; never use for real campaign evidence")
    ap.add_argument("--out", default=None, help="Optional JSON output path")
    ap.add_argument("--compact", action="store_true")
    args = ap.parse_args()

    policy = IntakePolicy(
        product=args.product,
        session_start=args.session_start,
        session_end=args.session_end,
        reject_synthetic=not args.allow_synthetic,
        batch_size=args.batch_size,
    )
    report = inspect_mtx_parquet(
        Path(args.parquet), expected_year=args.expected_year, policy=policy
    )
    text = json.dumps(
        report,
        ensure_ascii=False,
        indent=None if args.compact else 2,
        sort_keys=args.compact,
    )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")

    print(
        "REAL_MTX_INTAKE",
        report["status"],
        report["file"],
        f"rows={report.get('parquet', {}).get('rows')}",
        f"sha256={report['sha256']}",
        f"report_hash={report['report_hash']}",
    )
    if report.get("failed_checks"):
        print("FAILED_CHECKS", ",".join(report["failed_checks"]))
    if not args.out:
        print(text)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
