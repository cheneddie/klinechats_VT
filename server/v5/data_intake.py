from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REQUIRED_COLUMNS = ("datetime", "product", "expiry", "price", "volume", "side")
OUTRIGHT_RE = re.compile(r"^\d{6}$")
SYNTHETIC_RE = re.compile(r"(?:^|[_\-.])SYNTHETIC(?:[_\-.]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class IntakePolicy:
    product: str = "MTX"
    session_start: str = "08:45:00"
    session_end: str = "13:45:00"
    reject_synthetic: bool = True
    batch_size: int = 250_000


def _txt(value: Any) -> str:
    try:
        if value is None or bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return str(value).strip()


def _to_dt(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    if pd.api.types.is_integer_dtype(series) or pd.api.types.is_float_dtype(series):
        vals = pd.to_numeric(series, errors="coerce")
        clean = vals.dropna().abs()
        med = float(clean.median()) if len(clean) else 0.0
        if med > 1e17:
            unit = "ns"
        elif med > 1e14:
            unit = "us"
        elif med > 1e11:
            unit = "ms"
        else:
            unit = "s"
        return pd.to_datetime(vals, unit=unit, errors="coerce")
    return pd.to_datetime(series, errors="coerce")


def _session_seconds(text: str) -> int:
    h, m, s = [int(x) for x in text.split(":")]
    return h * 3600 + m * 60 + s


def sha256_file(path: str | Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def _canonical_hash(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("generated_at", None)
    clean.pop("report_hash", None)
    clean.pop("path", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _check(checks: list[dict[str, Any]], code: str, passed: bool, details: Any) -> None:
    checks.append({"code": code, "passed": bool(passed), "details": details})


def _schema_payload(pf: pq.ParquetFile) -> list[dict[str, str]]:
    return [{"name": field.name, "type": str(field.type)} for field in pf.schema_arrow]


def _accumulate_groups(state: dict[str, Any], lengths: np.ndarray) -> None:
    if not len(lengths):
        return
    repeated = lengths[lengths > 1]
    state["same_second_groups"] += int(len(repeated))
    state["same_second_rows"] += int(repeated.sum()) if len(repeated) else 0
    state["same_second_adjacent_pairs"] += int((repeated - 1).sum()) if len(repeated) else 0
    state["max_same_second_group"] = max(int(state["max_same_second_group"]), int(lengths.max()))


def _consume_seconds(state: dict[str, Any], seconds: np.ndarray) -> None:
    if not len(seconds):
        return
    cuts = np.flatnonzero(np.diff(seconds) != 0) + 1
    starts = np.concatenate(([0], cuts))
    ends = np.concatenate((cuts, [len(seconds)]))
    values = seconds[starts]
    lengths = (ends - starts).astype(np.int64)

    if state["carry_second"] is not None:
        if int(values[0]) == int(state["carry_second"]):
            lengths[0] += int(state["carry_size"])
        else:
            _accumulate_groups(state, np.array([int(state["carry_size"])], dtype=np.int64))
    if len(lengths) > 1:
        _accumulate_groups(state, lengths[:-1])
    state["carry_second"] = int(values[-1])
    state["carry_size"] = int(lengths[-1])


def _finish_seconds(state: dict[str, Any]) -> None:
    if state["carry_second"] is not None:
        _accumulate_groups(state, np.array([int(state["carry_size"])], dtype=np.int64))
        state["carry_second"] = None
        state["carry_size"] = 0


def _contract_day_table(day_volume: dict[str, dict[str, float]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    previous_dominant = None
    previous_front = None
    dominant_rolls = 0
    front_rolls = 0
    ambiguous_days = 0
    for day in sorted(day_volume):
        vols = day_volume[day]
        ranked = sorted(vols.items(), key=lambda x: (-float(x[1]), x[0]))
        dominant = ranked[0][0] if ranked else None
        dominant_volume = float(ranked[0][1]) if ranked else 0.0
        second_volume = float(ranked[1][1]) if len(ranked) > 1 else 0.0
        ambiguous = bool(len(ranked) > 1 and dominant_volume < second_volume * 1.10)
        ambiguous_days += int(ambiguous)
        ym = day[:7].replace("-", "")
        fronts = sorted(x for x in vols if OUTRIGHT_RE.fullmatch(x) and x >= ym)
        front = fronts[0] if fronts else dominant
        dominant_changed = previous_dominant is not None and dominant != previous_dominant
        front_changed = previous_front is not None and front != previous_front
        dominant_rolls += int(dominant_changed)
        front_rolls += int(front_changed)
        rows.append({
            "trading_date": day,
            "dominant_contract": dominant,
            "dominant_volume": dominant_volume,
            "second_volume": second_volume,
            "front_contract": front,
            "front_volume": float(vols.get(front, 0.0)) if front else 0.0,
            "ambiguous_volume_day": ambiguous,
            "dominant_changed": dominant_changed,
            "front_changed": front_changed,
        })
        previous_dominant = dominant
        previous_front = front
    return {
        "days": len(rows),
        "dominant_rolls": dominant_rolls,
        "front_rolls": front_rolls,
        "ambiguous_days": ambiguous_days,
        "rows": rows,
    }


def _early_fail(base: dict[str, Any]) -> dict[str, Any]:
    failed = [x["code"] for x in base["checks"] if not x["passed"]]
    base["failed_checks"] = failed
    base["status"] = "FAIL"
    base["report_hash"] = _canonical_hash(base)
    return base


def inspect_mtx_parquet(
    path: str | Path,
    *,
    expected_year: int | None = None,
    policy: IntakePolicy | None = None,
) -> dict[str, Any]:
    """Stream-audit MTX Parquet without sorting or rewriting physical source rows."""
    policy = policy or IntakePolicy()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise ValueError(f"not a file: {path}")

    if expected_year is None:
        match = re.search(r"(?:^|_)(20\d{2})(?:_|\.|$)", path.name)
        expected_year = int(match.group(1)) if match else None

    synthetic_name = bool(SYNTHETIC_RE.search(path.name))
    base: dict[str, Any] = {
        "version": "REAL_MTX_INTAKE_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file": path.name,
        "path": str(path.resolve()),
        "file_size_bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
        "expected_year": expected_year,
        "policy": asdict(policy),
        "synthetic_name": synthetic_name,
        "checks": [],
        "warnings": [],
    }
    checks = base["checks"]
    synthetic_ok = not (synthetic_name and policy.reject_synthetic)
    synthetic_detail = (
        "synthetic-like filename rejected from Real MTX intake"
        if not synthetic_ok
        else "synthetic source accepted only because QA override is enabled"
        if synthetic_name
        else "source name is not synthetic"
    )
    _check(checks, "NOT_SYNTHETIC_SOURCE", synthetic_ok, synthetic_detail)

    try:
        pf = pq.ParquetFile(path)
    except Exception as exc:
        _check(checks, "PARQUET_READABLE", False, f"{type(exc).__name__}: {exc}")
        return _early_fail(base)
    _check(checks, "PARQUET_READABLE", True, "pyarrow ParquetFile opened successfully")

    schema = _schema_payload(pf)
    schema_names = [x["name"] for x in schema]
    missing = [x for x in REQUIRED_COLUMNS if x not in schema_names]
    metadata_rows = int(pf.metadata.num_rows)
    row_group_rows = [int(pf.metadata.row_group(i).num_rows) for i in range(pf.num_row_groups)]
    base["parquet"] = {
        "rows": metadata_rows,
        "row_groups": int(pf.num_row_groups),
        "row_group_rows": row_group_rows,
        "row_group_rows_total": int(sum(row_group_rows)),
        "schema": schema,
        "created_by": str(pf.metadata.created_by or ""),
        "format_version": str(getattr(pf.metadata, "format_version", "")),
    }
    _check(checks, "NONEMPTY_PARQUET", metadata_rows > 0, {"rows": metadata_rows})
    _check(checks, "REQUIRED_COLUMNS", not missing, {"required": list(REQUIRED_COLUMNS), "missing": missing})
    _check(
        checks,
        "ROW_GROUP_ROW_COUNT",
        sum(row_group_rows) == metadata_rows,
        {"metadata_rows": metadata_rows, "row_group_rows_total": int(sum(row_group_rows))},
    )
    if missing or metadata_rows <= 0:
        return _early_fail(base)

    product_counts: Counter[str] = Counter()
    expiry_counts: Counter[str] = Counter()
    side_counts: Counter[str] = Counter()
    year_counts: Counter[int] = Counter()
    day_volume: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    scanned_rows = datetime_nulls = physical_reversals = 0
    previous_valid_ns: int | None = None
    min_dt: pd.Timestamp | None = None
    max_dt: pd.Timestamp | None = None
    mtx_rows = mtx_outright_rows = mtx_other_expiry_rows = 0
    invalid_price_rows = invalid_volume_rows = day_session_outright_rows = 0
    second_state = {
        "carry_second": None,
        "carry_size": 0,
        "same_second_groups": 0,
        "same_second_rows": 0,
        "same_second_adjacent_pairs": 0,
        "max_same_second_group": 0,
    }
    start_sec = _session_seconds(policy.session_start)
    end_sec = _session_seconds(policy.session_end)

    for batch in pf.iter_batches(batch_size=int(policy.batch_size), columns=list(REQUIRED_COLUMNS)):
        d = batch.to_pandas()
        scanned_rows += len(d)
        dt = _to_dt(d["datetime"])
        valid_dt = dt.notna()
        datetime_nulls += int((~valid_dt).sum())
        if valid_dt.any():
            vd = dt.loc[valid_dt]
            local_min = pd.Timestamp(vd.min())
            local_max = pd.Timestamp(vd.max())
            min_dt = local_min if min_dt is None else min(min_dt, local_min)
            max_dt = local_max if max_dt is None else max(max_dt, local_max)
            # DatetimeIndex.asi8 is always nanoseconds, regardless of Parquet ms/us/ns storage unit.
            ns = pd.DatetimeIndex(vd).asi8
            if previous_valid_ns is not None and len(ns) and int(ns[0]) < previous_valid_ns:
                physical_reversals += 1
            if len(ns) > 1:
                physical_reversals += int(np.count_nonzero(np.diff(ns) < 0))
            if len(ns):
                previous_valid_ns = int(ns[-1])
                _consume_seconds(second_state, ns // 1_000_000_000)

        product = d["product"].map(_txt)
        expiry = d["expiry"].map(_txt)
        product_counts.update(product.value_counts(dropna=False).to_dict())
        mtx_mask = product.eq(policy.product)
        mtx_rows += int(mtx_mask.sum())
        if mtx_mask.any():
            expiry_counts.update(expiry.loc[mtx_mask].value_counts(dropna=False).to_dict())
        outright_mask = mtx_mask & expiry.str.fullmatch(OUTRIGHT_RE.pattern, na=False)
        mtx_outright_rows += int(outright_mask.sum())
        mtx_other_expiry_rows += int((mtx_mask & ~expiry.str.fullmatch(OUTRIGHT_RE.pattern, na=False)).sum())

        if not outright_mask.any():
            continue
        price = pd.to_numeric(d.loc[outright_mask, "price"], errors="coerce").to_numpy(dtype=float)
        volume = pd.to_numeric(d.loc[outright_mask, "volume"], errors="coerce").to_numpy(dtype=float)
        invalid_price_rows += int(np.count_nonzero(~np.isfinite(price) | (price <= 0)))
        invalid_volume_rows += int(np.count_nonzero(~np.isfinite(volume) | (volume < 0)))
        side_counts.update(d.loc[outright_mask, "side"].map(_txt).value_counts(dropna=False).to_dict())

        idx = d.index[outright_mask]
        odt = dt.loc[idx]
        valid_odt = odt.notna()
        if not valid_odt.any():
            continue
        ov = pd.DataFrame({
            "dt": odt.loc[valid_odt],
            "expiry": expiry.loc[idx].loc[valid_odt],
            "volume": pd.to_numeric(d.loc[idx, "volume"], errors="coerce").loc[valid_odt],
        })
        year_counts.update({int(k): int(v) for k, v in ov["dt"].dt.year.value_counts().to_dict().items()})
        sec = ov["dt"].dt.hour * 3600 + ov["dt"].dt.minute * 60 + ov["dt"].dt.second
        day = ov.loc[(sec >= start_sec) & (sec <= end_sec)].copy()
        day_session_outright_rows += int(len(day))
        if len(day):
            day["date"] = day["dt"].dt.strftime("%Y-%m-%d")
            day["volume"] = pd.to_numeric(day["volume"], errors="coerce").fillna(0.0)
            for (date_text, contract), vol in day.groupby(["date", "expiry"], sort=False)["volume"].sum().items():
                day_volume[str(date_text)][str(contract)] += float(vol)

    _finish_seconds(second_state)
    contract_days = _contract_day_table(day_volume)
    expected_year_rows = int(year_counts.get(int(expected_year), 0)) if expected_year is not None else None
    total_year_rows = int(sum(year_counts.values()))
    base.update({
        "scan": {
            "rows_scanned": int(scanned_rows),
            "datetime_null_rows": int(datetime_nulls),
            "physical_timestamp_reversals": int(physical_reversals),
            "start": min_dt.isoformat() if min_dt is not None else None,
            "end": max_dt.isoformat() if max_dt is not None else None,
            "same_second": {
                "groups_with_multiple_rows": int(second_state["same_second_groups"]),
                "rows_in_multirow_groups": int(second_state["same_second_rows"]),
                "adjacent_same_second_pairs": int(second_state["same_second_adjacent_pairs"]),
                "max_group_rows": int(second_state["max_same_second_group"]),
            },
        },
        "products": dict(sorted(product_counts.items())),
        "mtx": {
            "rows": int(mtx_rows),
            "outright_rows": int(mtx_outright_rows),
            "other_expiry_rows": int(mtx_other_expiry_rows),
            "expiry_counts": dict(sorted(expiry_counts.items())),
            "side_counts": dict(sorted(side_counts.items())),
            "invalid_price_rows": int(invalid_price_rows),
            "invalid_volume_rows": int(invalid_volume_rows),
            "timestamp_year_counts": {str(k): int(v) for k, v in sorted(year_counts.items())},
            "expected_year_rows": expected_year_rows,
            "expected_year_share": (
                float(expected_year_rows / total_year_rows) if expected_year_rows is not None and total_year_rows else None
            ),
            "day_session_outright_rows": int(day_session_outright_rows),
        },
        "contract_days": contract_days,
    })

    _check(checks, "SCANNED_ROW_COUNT", scanned_rows == metadata_rows, {"scanned": scanned_rows, "metadata": metadata_rows})
    _check(checks, "DATETIME_COMPLETE", datetime_nulls == 0, {"null_or_unparseable": datetime_nulls})
    _check(checks, "PHYSICAL_TIME_ORDER", physical_reversals == 0, {"reversals": physical_reversals})
    _check(checks, "MTX_OUTRIGHT_PRESENT", mtx_outright_rows > 0, {"rows": mtx_outright_rows})
    _check(checks, "MTX_OUTRIGHT_PRICE_VALID", invalid_price_rows == 0, {"invalid_rows": invalid_price_rows})
    _check(checks, "MTX_OUTRIGHT_VOLUME_VALID", invalid_volume_rows == 0, {"invalid_rows": invalid_volume_rows})
    _check(
        checks,
        "DAY_SESSION_MTX_OUTRIGHT_PRESENT",
        day_session_outright_rows > 0,
        {"rows": day_session_outright_rows, "session": f"{policy.session_start}-{policy.session_end}"},
    )
    if expected_year is not None:
        _check(
            checks,
            "EXPECTED_YEAR_PRESENT",
            bool(expected_year_rows and expected_year_rows > 0),
            {"expected_year": int(expected_year), "rows": int(expected_year_rows or 0), "share": base["mtx"]["expected_year_share"]},
        )
    else:
        base["warnings"].append(
            "filename did not provide an expected year; timestamp year distribution is reported but not identity-checked"
        )
    if mtx_other_expiry_rows:
        base["warnings"].append(
            f"MTX contains {mtx_other_expiry_rows} non-outright expiry rows; they are excluded from outright contract/day analysis"
        )
    if contract_days["ambiguous_days"]:
        base["warnings"].append(
            f"{contract_days['ambiguous_days']} day-session dates have dominant volume within 10% of the second-ranked contract"
        )

    failed = [x["code"] for x in checks if not x["passed"]]
    base["failed_checks"] = failed
    base["status"] = "PASS" if not failed else "FAIL"
    base["report_hash"] = _canonical_hash(base)
    return base


__all__ = ["IntakePolicy", "REQUIRED_COLUMNS", "inspect_mtx_parquet", "sha256_file"]
