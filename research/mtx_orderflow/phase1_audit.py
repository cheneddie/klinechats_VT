from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

OUTRIGHT_RE = re.compile(r"^\d{6}$")


def _jsonable_counter(c: Counter) -> dict[str, int]:
    return {str(k): int(v) for k, v in sorted(c.items(), key=lambda kv: str(kv[0]))}


def audit(path: Path) -> tuple[dict, pd.DataFrame]:
    pf = pq.ParquetFile(path)
    names = pf.schema_arrow.names
    required = ["datetime", "product", "expiry", "price", "volume", "side"]
    missing = [c for c in required if c not in names]
    if missing:
        raise ValueError(f"missing required columns: {missing}")

    row_count = 0
    expiry_counts: Counter = Counter()
    product_counts: Counter = Counter()
    side_counts: Counter = Counter()
    spread_examples: Counter = Counter()
    volume_gcd = 0
    volume_min = math.inf
    volume_max = -math.inf
    outright_price_min = math.inf
    outright_price_max = -math.inf
    outright_rows = 0
    non_outight_rows = 0
    same_second_adjacent = 0
    backwards_timestamp_pairs = 0
    first_ts = None
    last_ts = None
    previous_ts = None

    semantic_total = 0
    semantic_match = 0
    semantic_nonzero_total = 0
    semantic_nonzero_match = 0

    per_rg = []
    prev_rg_last_expiry = None
    prev_rg_last_price = None
    prev_rg_last_ts = None

    for rg in range(pf.num_row_groups):
        table = pf.read_row_group(rg, columns=required)
        df = table.to_pandas()

        # IMPORTANT: do not sort. Original row order is the event order we are auditing.
        dt = pd.to_datetime(df["datetime"], errors="raise")
        expiry = df["expiry"].astype(str)
        product = df["product"].astype(str)
        price = pd.to_numeric(df["price"], errors="raise").to_numpy(dtype=np.float64)
        volume = pd.to_numeric(df["volume"], errors="raise").to_numpy(dtype=np.float64)
        side = pd.to_numeric(df["side"], errors="raise").to_numpy(dtype=np.int8)

        n = len(df)
        row_count += n
        expiry_counts.update(expiry.tolist())
        product_counts.update(product.tolist())
        side_counts.update(side.tolist())

        if first_ts is None and n:
            first_ts = dt.iloc[0]
        if n:
            last_ts = dt.iloc[-1]

        if n > 1:
            ns = dt.astype("int64").to_numpy()
            d = np.diff(ns)
            same_second_adjacent += int(np.sum(d == 0))
            backwards_timestamp_pairs += int(np.sum(d < 0))
        if previous_ts is not None and n:
            cur0 = dt.iloc[0]
            if cur0 == previous_ts:
                same_second_adjacent += 1
            elif cur0 < previous_ts:
                backwards_timestamp_pairs += 1
        if n:
            previous_ts = dt.iloc[-1]

        for v in volume:
            if np.isfinite(v):
                volume_gcd = math.gcd(volume_gcd, int(round(v)))
        if n:
            volume_min = min(volume_min, float(np.nanmin(volume)))
            volume_max = max(volume_max, float(np.nanmax(volume)))

        outright = expiry.map(lambda x: bool(OUTRIGHT_RE.fullmatch(x))).to_numpy()
        outright_rows += int(outright.sum())
        non_outight_rows += int((~outright).sum())
        for x in expiry[~outright]:
            spread_examples[x] += 1

        if outright.any():
            p = price[outright]
            outright_price_min = min(outright_price_min, float(np.nanmin(p)))
            outright_price_max = max(outright_price_max, float(np.nanmax(p)))

        # Validate side semantics against sign(price_t - price_{t-1}) only where
        # adjacent rows belong to the same outright expiry. This avoids roll/spread contamination.
        if n > 1:
            same_contract = (
                outright[1:]
                & outright[:-1]
                & (expiry.iloc[1:].to_numpy() == expiry.iloc[:-1].to_numpy())
            )
            observed = side[1:][same_contract]
            inferred = np.sign(price[1:] - price[:-1]).astype(np.int8)[same_contract]
            semantic_total += int(len(observed))
            semantic_match += int(np.sum(observed == inferred))
            nz = observed != 0
            semantic_nonzero_total += int(nz.sum())
            semantic_nonzero_match += int(np.sum(observed[nz] == inferred[nz]))

        # Cross-row-group semantic check.
        if prev_rg_last_expiry is not None and n:
            cur_exp = expiry.iloc[0]
            if OUTRIGHT_RE.fullmatch(prev_rg_last_expiry) and OUTRIGHT_RE.fullmatch(cur_exp) and prev_rg_last_expiry == cur_exp:
                inferred = int(np.sign(price[0] - prev_rg_last_price))
                semantic_total += 1
                semantic_match += int(side[0] == inferred)
                if side[0] != 0:
                    semantic_nonzero_total += 1
                    semantic_nonzero_match += int(side[0] == inferred)

        if n:
            prev_rg_last_expiry = expiry.iloc[-1]
            prev_rg_last_price = float(price[-1])
            prev_rg_last_ts = dt.iloc[-1]

        per_rg.append(
            {
                "row_group": rg,
                "rows": n,
                "start": None if n == 0 else dt.iloc[0].isoformat(),
                "end": None if n == 0 else dt.iloc[-1].isoformat(),
                "outright_rows": int(outright.sum()),
                "non_outright_rows": int((~outright).sum()),
                "price_min_outright": None if not outright.any() else float(np.nanmin(price[outright])),
                "price_max_outright": None if not outright.any() else float(np.nanmax(price[outright])),
            }
        )

    summary = {
        "file": str(path),
        "rows": int(row_count),
        "row_groups": int(pf.num_row_groups),
        "columns": names,
        "time_start": None if first_ts is None else first_ts.isoformat(),
        "time_end": None if last_ts is None else last_ts.isoformat(),
        "product_counts": _jsonable_counter(product_counts),
        "expiry_counts": _jsonable_counter(expiry_counts),
        "side_counts": _jsonable_counter(side_counts),
        "outright_rows": int(outright_rows),
        "non_outright_rows": int(non_outight_rows),
        "non_outright_expiry_counts": _jsonable_counter(spread_examples),
        "outright_price_min": float(outright_price_min),
        "outright_price_max": float(outright_price_max),
        "volume_min": float(volume_min),
        "volume_max": float(volume_max),
        "volume_gcd": int(volume_gcd),
        "same_second_adjacent_pairs": int(same_second_adjacent),
        "timestamp_backwards_pairs": int(backwards_timestamp_pairs),
        "side_semantic_pairs": int(semantic_total),
        "side_equals_sign_price_change_pairs": int(semantic_match),
        "side_equals_sign_price_change_rate": None if semantic_total == 0 else semantic_match / semantic_total,
        "nonzero_side_semantic_pairs": int(semantic_nonzero_total),
        "nonzero_side_equals_sign_price_change_rate": None
        if semantic_nonzero_total == 0
        else semantic_nonzero_match / semantic_nonzero_total,
        "interpretation": {
            "side": "tick-rule price direction if semantic match rate is ~1; not independent aggressor side",
            "volume": "all-volume GCD is diagnostic only; verify vendor unit before interpreting absolute contract counts",
            "expiry": "only ^\\d{6}$ is treated as outright in research returns",
        },
    }
    return summary, pd.DataFrame(per_rg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("parquet", type=Path)
    ap.add_argument("--out", type=Path, default=Path("reports/mtx_orderflow"))
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    summary, row_groups = audit(args.parquet)
    (args.out / "phase1_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    row_groups.to_csv(args.out / "phase1_row_groups.csv", index=False)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
