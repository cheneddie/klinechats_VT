#!/usr/bin/env python3
"""M1 physical-data / contract / session QA for POC absorption research.

Design invariants:
- `_seq` is the source Parquet physical row number and exists before filtering.
- Never sort ticks. Row groups are scanned in file order and rows in each row group
  remain in source order.
- Only MTX legal outright expiries (`YYYYMM`) enter contract/profile research.
- The production contract selector is the causal calendar front-month policy from
  `server.contracts`; completed-day dominant volume is diagnostic only.
- `side` is audited only as a tick-direction proxy.

The runner is intentionally checkpointable because a full three-year scan is over
126M physical rows. Checkpoints are row-group based and never alter source order.
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.contracts import OUTRIGHT_RE, causal_front_month  # noqa: E402

DAY_START = 8 * 3600 + 45 * 60
DAY_END = 13 * 3600 + 45 * 60
NIGHT_START = 15 * 3600
NIGHT_END = 5 * 3600
SCHEMA_VERSION = "POC_M1_QA_V1"


def _text_series(series: pd.Series) -> pd.Series:
    return series.map(
        lambda x: x.decode("utf-8", "replace")
        if isinstance(x, (bytes, bytearray))
        else (str(x) if x is not None else None)
    )


def _counter_add(target: Counter, values: pd.Series) -> None:
    for key, count in values.items():
        target["<NULL>" if pd.isna(key) else str(key)] += int(count)


def _new_state(year: int, parquet: pq.ParquetFile) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "year": year,
        "next_row_group": 0,
        "physical_rows_seen": 0,
        "metadata_rows": int(parquet.metadata.num_rows),
        "product_counts": Counter(),
        "expiry_counts": Counter(),
        "side_counts": Counter(),
        "null_counts": Counter(),
        "price_min": math.inf,
        "price_max": -math.inf,
        "outright_price_min": math.inf,
        "outright_price_max": -math.inf,
        "volume_min": math.inf,
        "volume_max": -math.inf,
        "negative_volume_count": 0,
        "nonpositive_volume_count": 0,
        "datetime_backward_edges": 0,
        "datetime_equal_edges": 0,
        "datetime_forward_edges": 0,
        "previous_datetime_us": None,
        "first_datetime": None,
        "last_datetime": None,
        "legal_outright_rows": 0,
        "non_outright_rows": 0,
        "mtx_rows": 0,
        "mtx_outright_rows": 0,
        "day_rows_all": 0,
        "night_rows_all": 0,
        "other_session_rows_all": 0,
        "day_rows_mtx_outright": 0,
        "night_rows_mtx_outright": 0,
        "contract_volume_by_day": {},
        "contract_rows_by_day": {},
    }


def _scan_row_group(state: dict[str, Any], parquet: pq.ParquetFile, row_group: int) -> None:
    df = parquet.read_row_group(
        row_group,
        columns=["datetime", "product", "expiry", "price", "volume", "side"],
    ).to_pandas()
    n = len(df)
    dt = pd.to_datetime(df["datetime"])
    if n and state["first_datetime"] is None:
        state["first_datetime"] = dt.iloc[0]
    if n:
        state["last_datetime"] = dt.iloc[-1]

    dt_us = dt.to_numpy(dtype="datetime64[us]").astype("int64")
    if n:
        previous = state["previous_datetime_us"]
        if previous is not None:
            state["datetime_backward_edges"] += int(dt_us[0] < previous)
            state["datetime_equal_edges"] += int(dt_us[0] == previous)
            state["datetime_forward_edges"] += int(dt_us[0] > previous)
        if n > 1:
            diff = np.diff(dt_us)
            state["datetime_backward_edges"] += int((diff < 0).sum())
            state["datetime_equal_edges"] += int((diff == 0).sum())
            state["datetime_forward_edges"] += int((diff > 0).sum())
        state["previous_datetime_us"] = int(dt_us[-1])

    product = _text_series(df["product"])
    expiry = _text_series(df["expiry"])
    _counter_add(state["product_counts"], product.value_counts(dropna=False))
    _counter_add(state["expiry_counts"], expiry.value_counts(dropna=False))
    _counter_add(state["side_counts"], df["side"].value_counts(dropna=False))
    for column in df.columns:
        state["null_counts"][column] += int(df[column].isna().sum())

    price = pd.to_numeric(df["price"], errors="coerce").to_numpy(dtype=float)
    volume = pd.to_numeric(df["volume"], errors="coerce").to_numpy(dtype=float)
    if np.isfinite(price).any():
        state["price_min"] = min(state["price_min"], float(np.nanmin(price)))
        state["price_max"] = max(state["price_max"], float(np.nanmax(price)))
    if np.isfinite(volume).any():
        state["volume_min"] = min(state["volume_min"], float(np.nanmin(volume)))
        state["volume_max"] = max(state["volume_max"], float(np.nanmax(volume)))
        state["negative_volume_count"] += int(np.nansum(volume < 0))
        state["nonpositive_volume_count"] += int(np.nansum(volume <= 0))

    exp = expiry.fillna("")
    legal = exp.str.fullmatch(OUTRIGHT_RE.pattern).fillna(False).to_numpy(dtype=bool)
    is_mtx = (product.fillna("") == "MTX").to_numpy(dtype=bool)
    research_mask = legal & is_mtx
    state["legal_outright_rows"] += int(legal.sum())
    state["non_outright_rows"] += int(n - legal.sum())
    state["mtx_rows"] += int(is_mtx.sum())
    state["mtx_outright_rows"] += int(research_mask.sum())
    if research_mask.any():
        research_prices = price[research_mask]
        state["outright_price_min"] = min(
            state["outright_price_min"], float(np.nanmin(research_prices))
        )
        state["outright_price_max"] = max(
            state["outright_price_max"], float(np.nanmax(research_prices))
        )

    seconds = (dt.dt.hour * 3600 + dt.dt.minute * 60 + dt.dt.second).to_numpy(dtype=np.int64)
    day = (seconds >= DAY_START) & (seconds <= DAY_END)
    night = (seconds >= NIGHT_START) | (seconds <= NIGHT_END)
    other = ~(day | night)
    state["day_rows_all"] += int(day.sum())
    state["night_rows_all"] += int(night.sum())
    state["other_session_rows_all"] += int(other.sum())
    state["day_rows_mtx_outright"] += int((day & research_mask).sum())
    state["night_rows_mtx_outright"] += int((night & research_mask).sum())

    contract_mask = day & research_mask
    if contract_mask.any():
        daily = pd.DataFrame(
            {
                "date": dt.loc[contract_mask].dt.strftime("%Y-%m-%d").to_numpy(),
                "expiry": expiry.loc[contract_mask].to_numpy(),
                "volume": volume[contract_mask],
            }
        )
        grouped = daily.groupby(["date", "expiry"], sort=False)["volume"].agg(["sum", "size"])
        for (trading_date, contract), row in grouped.iterrows():
            d = str(trading_date)
            c = str(contract)
            vol_map = state["contract_volume_by_day"].setdefault(d, {})
            row_map = state["contract_rows_by_day"].setdefault(d, {})
            vol_map[c] = vol_map.get(c, 0.0) + float(row["sum"])
            row_map[c] = row_map.get(c, 0) + int(row["size"])

    state["physical_rows_seen"] += n
    state["next_row_group"] = row_group + 1


def _contract_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous_contract = None
    for day in sorted(state["contract_volume_by_day"]):
        volume_map = state["contract_volume_by_day"][day]
        row_map = state["contract_rows_by_day"][day]
        candidates = sorted(str(x) for x in volume_map if OUTRIGHT_RE.fullmatch(str(x)))
        strict = causal_front_month(day, candidates)
        ranked = sorted(volume_map.items(), key=lambda item: (-item[1], item[0]))
        dominant = ranked[0][0] if ranked else None
        ambiguous = len(ranked) > 1 and ranked[0][1] < ranked[1][1] * 1.10
        roll = previous_contract is not None and strict is not None and strict != previous_contract
        if strict is not None:
            previous_contract = strict
        rows.append(
            {
                "year": state["year"],
                "trading_date": day,
                "candidate_contracts": "|".join(candidates),
                "candidate_count": len(candidates),
                "strict_contract": strict,
                "dominant_volume_contract": dominant,
                "strict_vs_dominant_mismatch": strict != dominant,
                "dominant_ambiguous_10pct": ambiguous,
                "roll": roll,
                "selection_reason": "calendar_front_month",
                "strict_rows": int(row_map.get(strict, 0)) if strict else 0,
                "strict_volume": float(volume_map.get(strict, 0.0)) if strict else 0.0,
                "day_outright_rows_all_contracts": int(sum(row_map.values())),
                "rows_removed_other_outrights": int(sum(row_map.values()) - row_map.get(strict, 0))
                if strict
                else int(sum(row_map.values())),
            }
        )
    return rows


def _finalize(state: dict[str, Any], path: Path, parquet: pq.ParquetFile, out: Path) -> dict[str, Any]:
    contract_rows = _contract_rows(state)
    rolls = [row["trading_date"] for row in contract_rows if row["roll"]]
    result = {
        "schema_version": SCHEMA_VERSION,
        "year": state["year"],
        "file": path.name,
        "file_size_bytes": path.stat().st_size,
        "physical_rows": int(parquet.metadata.num_rows),
        "row_groups": int(parquet.metadata.num_row_groups),
        "schema": str(parquet.schema_arrow),
        "datetime_first_physical": state["first_datetime"].isoformat()
        if state["first_datetime"] is not None
        else None,
        "datetime_last_physical": state["last_datetime"].isoformat()
        if state["last_datetime"] is not None
        else None,
        "product_counts": dict(state["product_counts"]),
        "expiry_counts": dict(state["expiry_counts"]),
        "side_counts": dict(state["side_counts"]),
        "price_min_raw": state["price_min"],
        "price_max_raw": state["price_max"],
        "price_min_mtx_outright": state["outright_price_min"],
        "price_max_mtx_outright": state["outright_price_max"],
        "volume_min": state["volume_min"],
        "volume_max": state["volume_max"],
        "negative_volume_count": state["negative_volume_count"],
        "nonpositive_volume_count": state["nonpositive_volume_count"],
        "null_count_by_column": dict(state["null_counts"]),
        "physical_datetime_edges": {
            "backward": state["datetime_backward_edges"],
            "equal": state["datetime_equal_edges"],
            "forward": state["datetime_forward_edges"],
            "non_decreasing_rate": (
                state["datetime_equal_edges"] + state["datetime_forward_edges"]
            )
            / max(int(parquet.metadata.num_rows) - 1, 1),
        },
        "expiry_format_counts": {
            "legal_outright_rows_all_products": state["legal_outright_rows"],
            "non_outright_or_null_rows_all_products": state["non_outright_rows"],
        },
        "mtx_rows": state["mtx_rows"],
        "mtx_legal_outright_rows": state["mtx_outright_rows"],
        "session_rows_all_products": {
            "day_08_45_13_45": state["day_rows_all"],
            "night_15_00_05_00": state["night_rows_all"],
            "other": state["other_session_rows_all"],
        },
        "session_rows_mtx_outright": {
            "day_08_45_13_45": state["day_rows_mtx_outright"],
            "night_15_00_05_00": state["night_rows_mtx_outright"],
        },
        "contract_qa": {
            "day_session_dates": len(contract_rows),
            "strict_vs_dominant_mismatch_days": sum(
                int(row["strict_vs_dominant_mismatch"]) for row in contract_rows
            ),
            "dominant_ambiguous_days_10pct": sum(
                int(row["dominant_ambiguous_10pct"]) for row in contract_rows
            ),
            "strict_roll_count": len(rolls),
            "strict_roll_dates": rolls,
        },
        "qa_flags": {
            "row_count_matches_metadata": state["physical_rows_seen"] == parquet.metadata.num_rows,
            "datetime_non_decreasing_physical_order": state["datetime_backward_edges"] == 0,
            "no_nulls": sum(state["null_counts"].values()) == 0,
            "no_negative_volume": state["negative_volume_count"] == 0,
            "has_mtx": state["mtx_rows"] > 0,
            "has_legal_outright_mtx": state["mtx_outright_rows"] > 0,
        },
    }
    (out / f"data_qa_{state['year']}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(contract_rows).to_csv(
        out / f"contract_qa_{state['year']}.csv", index=False, encoding="utf-8-sig"
    )
    return result


def scan_file(year: int, path: Path, output_dir: Path, row_groups_per_run: int | None) -> bool:
    parquet = pq.ParquetFile(path)
    state_dir = output_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"m1_{year}.pkl"
    if state_path.exists():
        state = pickle.loads(state_path.read_bytes())
    else:
        state = _new_state(year, parquet)

    start = int(state["next_row_group"])
    end = parquet.metadata.num_row_groups
    if row_groups_per_run is not None:
        end = min(end, start + row_groups_per_run)
    for row_group in range(start, end):
        _scan_row_group(state, parquet, row_group)
        print(
            f"M1 year={year} row_group={row_group + 1}/{parquet.metadata.num_row_groups} "
            f"rows={state['physical_rows_seen']}/{state['metadata_rows']}",
            flush=True,
        )
        state_path.write_bytes(pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL))

    if state["next_row_group"] >= parquet.metadata.num_row_groups:
        _finalize(state, path, parquet, output_dir)
        state_path.unlink(missing_ok=True)
        return True
    return False


def parse_inputs(values: list[str]) -> dict[int, Path]:
    parsed: dict[int, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Expected YEAR=PATH, got: {value}")
        year_s, path_s = value.split("=", 1)
        parsed[int(year_s)] = Path(path_s).expanduser().resolve()
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Repeat as YEAR=/path/to/MTX_YYYY.parquet",
    )
    parser.add_argument("--output-dir", default="reports/poc_absorption")
    parser.add_argument(
        "--row-groups-per-run",
        type=int,
        default=None,
        help="Optional checkpoint chunk size. Re-run the same command to resume.",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    complete = True
    for year, path in sorted(parse_inputs(args.input).items()):
        if not path.exists():
            raise FileNotFoundError(path)
        complete &= scan_file(year, path, output_dir, args.row_groups_per_run)
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
