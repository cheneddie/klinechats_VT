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

def load_lock(path: Path) -> OOSLock:
    d=json.loads(path.read_text(encoding="utf-8"))
    return OOSLock(pd.Timestamp(d["historical_last_seen"]),d["baseline_commit"],d["status"])

def assert_oos_rows_after_lock(timestamps, lock: OOSLock) -> None:
    t=pd.to_datetime(timestamps)
    w=lock.watermark.tz_localize(None) if lock.watermark.tzinfo else lock.watermark
    if (t <= w).any():
        raise ValueError("OOS input contains rows at/before historical watermark")

def config_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
