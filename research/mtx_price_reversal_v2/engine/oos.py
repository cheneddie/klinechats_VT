from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json, hashlib
import pandas as pd


@dataclass(frozen=True)
class OOSLock:
    watermark: pd.Timestamp
    baseline_commit: str
    status: str


@dataclass(frozen=True)
class EvaluationPolicy:
    information_days: tuple[int,...] = (30,60)
    formal_days: int = 120
    minimum_event_clusters: int = 100


def load_lock(path: Path) -> OOSLock:
    d=json.loads(path.read_text(encoding="utf-8"))
    return OOSLock(pd.Timestamp(d["historical_last_seen"]),d["baseline_commit"],d["status"])


def assert_oos_rows_after_lock(timestamps, lock: OOSLock) -> None:
    t=pd.to_datetime(timestamps); w=lock.watermark.tz_localize(None) if lock.watermark.tzinfo else lock.watermark
    if (t <= w).any(): raise ValueError("OOS input contains rows at/before historical watermark")


def evaluation_status(*, trading_days:int, event_clusters:int, policy:EvaluationPolicy=EvaluationPolicy())->str:
    return "FORMAL_GATE_ELIGIBLE" if trading_days>=policy.formal_days and event_clusters>=policy.minimum_event_clusters else "INFORMATION_ONLY"


def failed_oos_requires_new_version(current_version:str, inspected_last_timestamp)->dict:
    return {"failed_version":current_version,"failed_sample_reclassified_as":"DISCOVERY_RESEARCH","new_version_required":True,"new_oos_watermark":str(pd.Timestamp(inspected_last_timestamp))}


def config_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
