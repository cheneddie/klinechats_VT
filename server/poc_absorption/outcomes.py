"""M5 outcome-store contract and M4 read-only firewall.

Development 1 intentionally contains no future-path calculations.  It only
formalizes the one-to-one boundary between frozen M4 probe events and the M5
outcome store.  Physical-tick outcomes are added in later M5 developments.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Iterable

import numpy as np
import pandas as pd

OUTCOME_SCHEMA_VERSION = "POC_PROBE_OUTCOME_V1"
OUTCOME_CONTRACT_VERSION = "POC_M5_OUTCOME_CONTRACT_V1"
FROZEN_EVENT_SCHEMA_VERSION = "POC_PROBE_EVENT_V1"
FROZEN_UNIVERSE_VERSION = "HIGH_PRICE_PROBE_V1"
FROZEN_UNIVERSE_SCHEMA_VERSION = "POC_HIGH_PRICE_PROBE_UNIVERSE_V1"
FROZEN_UNIVERSE_CONFIG_HASH = "d7bf39afa32582bc06e00b2df9995b9cb9cc14670a6974834d80cf3d079016fb"
FROZEN_FEATURE_SCHEMA_VERSION = "POC_CONTINUOUS_FEATURES_V1"

# These columns define immutable M4 membership/provenance/decision semantics.
# M5 may copy them, but never mutate, delete, re-rank, or regenerate them.
IMMUTABLE_EVENT_COLUMNS = (
    "event_schema_version",
    "universe_version",
    "universe_schema_version",
    "universe_config_hash",
    "feature_schema_version",
    "event_id",
    "episode_id",
    "episode_trigger_number",
    "dataset_id",
    "contract",
    "partition_id",
    "session",
    "timeframe",
    "trigger_seq",
    "trigger_time",
    "trigger_price",
    "atr",
    "bar_start_seq",
    "bar_end_seq",
)

OUTCOME_PROVENANCE_COLUMNS = (
    "outcome_schema_version",
    "outcome_contract_version",
    *IMMUTABLE_EVENT_COLUMNS,
)

FROZEN_HORIZONS = ("30s", "1m", "3m", "5m", "15m", "30m", "60m", "session_end")


@dataclass(frozen=True)
class JoinIntegrityReport:
    event_count_before: int
    outcome_count: int
    joined_event_count: int
    unique_event_ids_before: int
    unique_event_ids_outcomes: int
    missing_event_ids: int
    extra_event_ids: int
    duplicated_event_ids: int
    immutable_field_mismatches: int
    event_order_preserved: bool
    event_fingerprint_before: str
    event_fingerprint_after_join: str
    all_pass: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = set(required).difference(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def _canonical_scalar(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        if not np.isfinite(value):
            return str(value)
        return float(value)
    if isinstance(value, (int, bool, str)):
        return value
    return str(value)


def event_store_fingerprint(events: pd.DataFrame) -> str:
    """Stable SHA-256 over immutable event columns in current event-store order."""
    _require_columns(events, IMMUTABLE_EVENT_COLUMNS, "probe_events")
    h = sha256()
    h.update((OUTCOME_CONTRACT_VERSION + "\n").encode("utf-8"))
    h.update(("|".join(IMMUTABLE_EVENT_COLUMNS) + "\n").encode("utf-8"))
    for row in events.loc[:, IMMUTABLE_EVENT_COLUMNS].itertuples(index=False, name=None):
        payload = [_canonical_scalar(v) for v in row]
        h.update(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def validate_probe_events(events: pd.DataFrame) -> dict:
    """Validate the frozen M4 side of the firewall without altering the frame."""
    _require_columns(events, IMMUTABLE_EVENT_COLUMNS, "probe_events")
    if events.empty:
        raise ValueError("probe_events must not be empty")
    if events["event_id"].isna().any() or not events["event_id"].is_unique:
        raise ValueError("probe_events event_id must be non-null and unique")
    expected = {
        "event_schema_version": FROZEN_EVENT_SCHEMA_VERSION,
        "universe_version": FROZEN_UNIVERSE_VERSION,
        "universe_schema_version": FROZEN_UNIVERSE_SCHEMA_VERSION,
        "universe_config_hash": FROZEN_UNIVERSE_CONFIG_HASH,
    }
    for col, value in expected.items():
        observed = set(events[col].dropna().astype(str).unique())
        if observed != {value}:
            raise ValueError(f"probe_events {col} drift: expected {value!r}, observed {sorted(observed)!r}")
    feature_versions = set(events["feature_schema_version"].dropna().astype(str).unique())
    if feature_versions != {FROZEN_FEATURE_SCHEMA_VERSION}:
        raise ValueError(
            f"probe_events feature_schema_version drift: expected {FROZEN_FEATURE_SCHEMA_VERSION!r}, observed {sorted(feature_versions)!r}"
        )
    seq = pd.to_numeric(events["trigger_seq"], errors="raise")
    end_seq = pd.to_numeric(events["bar_end_seq"], errors="raise")
    start_seq = pd.to_numeric(events["bar_start_seq"], errors="raise")
    if (seq < 0).any() or (start_seq < 0).any() or (end_seq < start_seq).any():
        raise ValueError("probe_events contain invalid physical seq values")
    if not np.array_equal(seq.to_numpy(dtype=np.int64), end_seq.to_numpy(dtype=np.int64)):
        raise ValueError("trigger_seq must equal physical bar_end_seq")
    if pd.to_datetime(events["trigger_time"], errors="coerce").isna().any():
        raise ValueError("probe_events trigger_time contains invalid/null values")
    if pd.to_numeric(events["trigger_price"], errors="coerce").isna().any():
        raise ValueError("probe_events trigger_price contains invalid/null values")
    atr = pd.to_numeric(events["atr"], errors="coerce")
    if atr.isna().any() or (~np.isfinite(atr.to_numpy(dtype=float))).any() or (atr <= 0).any():
        raise ValueError("probe_events atr must be finite and positive; M5 must use frozen M4 event-time ATR")
    if (pd.to_numeric(events["episode_trigger_number"], errors="raise") < 1).any():
        raise ValueError("episode_trigger_number must be >= 1")
    if not set(events["session"].astype(str).unique()).issubset({"day", "night"}):
        raise ValueError("unsupported session in probe_events")
    if not set(events["timeframe"].astype(str).unique()).issubset({"15s", "30s", "1m", "3m", "5m", "15m"}):
        raise ValueError("unsupported timeframe in probe_events")
    return build_event_manifest(events)


def build_event_manifest(events: pd.DataFrame) -> dict:
    """Return a machine-readable frozen-input manifest; no outcome columns used."""
    _require_columns(events, IMMUTABLE_EVENT_COLUMNS, "probe_events")
    tf_counts = {str(k): int(v) for k, v in events["timeframe"].value_counts().sort_index().items()}
    session_counts = {str(k): int(v) for k, v in events["session"].value_counts().sort_index().items()}
    dataset_counts = {str(k): int(v) for k, v in events["dataset_id"].value_counts().sort_index().items()}
    return {
        "schema_version": "POC_M5_EVENT_MANIFEST_V1",
        "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
        "event_schema_version": FROZEN_EVENT_SCHEMA_VERSION,
        "universe_version": FROZEN_UNIVERSE_VERSION,
        "universe_schema_version": FROZEN_UNIVERSE_SCHEMA_VERSION,
        "universe_config_hash": FROZEN_UNIVERSE_CONFIG_HASH,
        "event_count": int(len(events)),
        "unique_event_ids": int(events["event_id"].nunique(dropna=False)),
        "timeframe_counts": tf_counts,
        "session_counts": session_counts,
        "dataset_counts": dataset_counts,
        "first_trigger_seq": int(pd.to_numeric(events["trigger_seq"]).min()),
        "last_trigger_seq": int(pd.to_numeric(events["trigger_seq"]).max()),
        "event_store_fingerprint": event_store_fingerprint(events),
    }


def make_probe_outcome_skeleton(events: pd.DataFrame) -> pd.DataFrame:
    """Create one outcome-store row per frozen event, with no future outcomes yet."""
    validate_probe_events(events)
    out = events.loc[:, IMMUTABLE_EVENT_COLUMNS].copy(deep=True)
    out.insert(0, "outcome_contract_version", OUTCOME_CONTRACT_VERSION)
    out.insert(0, "outcome_schema_version", OUTCOME_SCHEMA_VERSION)
    return out


def validate_probe_outcomes(events: pd.DataFrame, outcomes: pd.DataFrame, *, require_complete: bool = True) -> JoinIntegrityReport:
    """Enforce event_id one-to-one join and immutable provenance parity."""
    validate_probe_events(events)
    _require_columns(outcomes, OUTCOME_PROVENANCE_COLUMNS, "probe_outcomes")
    if outcomes["event_id"].isna().any():
        raise ValueError("probe_outcomes event_id contains null")
    duplicated = int(outcomes["event_id"].duplicated(keep=False).sum())
    if duplicated:
        raise ValueError("probe_outcomes event_id must be unique")
    if set(outcomes["outcome_schema_version"].astype(str).unique()) != {OUTCOME_SCHEMA_VERSION}:
        raise ValueError("probe_outcomes outcome_schema_version drift")
    if set(outcomes["outcome_contract_version"].astype(str).unique()) != {OUTCOME_CONTRACT_VERSION}:
        raise ValueError("probe_outcomes outcome_contract_version drift")
    event_ids = events["event_id"].astype(str)
    outcome_ids = outcomes["event_id"].astype(str)
    event_set, outcome_set = set(event_ids), set(outcome_ids)
    missing = event_set - outcome_set
    extra = outcome_set - event_set
    if require_complete and (missing or extra):
        raise ValueError(f"event_id set mismatch: missing={len(missing)}, extra={len(extra)}")
    if extra:
        raise ValueError(f"probe_outcomes contain {len(extra)} unknown event_id values")
    event_indexed = events.set_index("event_id", drop=False)
    outcome_indexed = outcomes.set_index("event_id", drop=False)
    common_ids = [eid for eid in event_ids if eid in outcome_set]
    mismatches = 0
    for col in IMMUTABLE_EVENT_COLUMNS:
        left = event_indexed.loc[common_ids, col].reset_index(drop=True)
        right = outcome_indexed.loc[common_ids, col].reset_index(drop=True)
        if col == "trigger_time":
            equal = pd.to_datetime(left).equals(pd.to_datetime(right))
        elif pd.api.types.is_numeric_dtype(left) or pd.api.types.is_numeric_dtype(right):
            lnum = pd.to_numeric(left, errors="coerce").to_numpy(dtype=float)
            rnum = pd.to_numeric(right, errors="coerce").to_numpy(dtype=float)
            equal = np.array_equal(lnum, rnum, equal_nan=True)
        else:
            equal = left.astype(str).equals(right.astype(str))
        if not equal:
            lvals = left.map(_canonical_scalar).tolist()
            rvals = right.map(_canonical_scalar).tolist()
            mismatches += sum(a != b for a, b in zip(lvals, rvals))
    if mismatches:
        raise ValueError(f"immutable M4 field mismatch in {mismatches} values")
    joined = events.loc[:, IMMUTABLE_EVENT_COLUMNS].merge(
        outcomes.drop(columns=[c for c in IMMUTABLE_EVENT_COLUMNS if c != "event_id"]),
        on="event_id",
        how="left" if require_complete else "inner",
        validate="one_to_one",
        sort=False,
    )
    joined_ids = joined["event_id"].astype(str).tolist()
    order_preserved = joined_ids == event_ids.astype(str).tolist()[: len(joined_ids)]
    after_fingerprint = event_store_fingerprint(joined.loc[:, IMMUTABLE_EVENT_COLUMNS])
    before_fingerprint = event_store_fingerprint(events)
    all_pass = (
        (not require_complete or len(joined) == len(events))
        and len(missing) == 0
        and len(extra) == 0
        and duplicated == 0
        and mismatches == 0
        and order_preserved
        and before_fingerprint == after_fingerprint
    )
    return JoinIntegrityReport(
        event_count_before=int(len(events)), outcome_count=int(len(outcomes)), joined_event_count=int(len(joined)),
        unique_event_ids_before=int(events["event_id"].nunique()), unique_event_ids_outcomes=int(outcomes["event_id"].nunique()),
        missing_event_ids=int(len(missing)), extra_event_ids=int(len(extra)), duplicated_event_ids=duplicated,
        immutable_field_mismatches=int(mismatches), event_order_preserved=bool(order_preserved),
        event_fingerprint_before=before_fingerprint, event_fingerprint_after_join=after_fingerprint, all_pass=bool(all_pass),
    )


__all__ = [
    "OUTCOME_SCHEMA_VERSION", "OUTCOME_CONTRACT_VERSION", "FROZEN_EVENT_SCHEMA_VERSION", "FROZEN_UNIVERSE_VERSION",
    "FROZEN_UNIVERSE_SCHEMA_VERSION", "FROZEN_UNIVERSE_CONFIG_HASH", "FROZEN_FEATURE_SCHEMA_VERSION", "FROZEN_HORIZONS",
    "IMMUTABLE_EVENT_COLUMNS", "JoinIntegrityReport", "event_store_fingerprint", "build_event_manifest", "validate_probe_events",
    "make_probe_outcome_skeleton", "validate_probe_outcomes",
]
