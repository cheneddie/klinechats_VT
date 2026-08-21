from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from .contracts import is_outright
from .sessions import session_labels

@dataclass(frozen=True)
class RawTickBatch:
    frame: pd.DataFrame
    seq_start: int
    seq_end: int

def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def iter_parquet_ticks(path: Path):
    """Yield raw row-groups with immutable physical seq assigned BEFORE filters."""
    pf = pq.ParquetFile(path)
    seq = 0
    cols = ["datetime","product","expiry","price","volume","side"]
    for rg in range(pf.num_row_groups):
        df = pf.read_row_group(rg, columns=cols).to_pandas()
        n = len(df)
        df["_seq"] = np.arange(seq, seq+n, dtype=np.int64)
        start = seq; seq += n
        yield RawTickBatch(df, start, seq-1)

def clean_mtx_ticks(df: pd.DataFrame) -> pd.DataFrame:
    """Filter only; never re-sort raw physical rows."""
    x = df.loc[df["product"].astype(str).eq("MTX")].copy()
    x = x.loc[x["expiry"].map(is_outright)].copy()
    x["expiry"] = x["expiry"].astype(str)
    x["price"] = pd.to_numeric(x["price"], errors="raise")
    side = pd.to_numeric(x["side"], errors="raise")
    if not side.isin([-1,0,1]).all():
        raise ValueError("invalid side value")
    x["side"] = side.astype(np.int8)
    vol = pd.to_numeric(x["volume"], errors="raise") / 2.0
    if ((vol - np.round(vol)).abs() > 1e-9).any():
        raise ValueError("volume/2 produced non-integer one-sided volume")
    x["volume_one_sided"] = vol
    key, kind = session_labels(x["datetime"])
    x["session_key"] = key; x["session_kind"] = kind
    return x.loc[x["session_key"].notna()].copy()
