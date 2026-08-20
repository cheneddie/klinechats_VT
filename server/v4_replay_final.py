from __future__ import annotations

"""Trading-day aware Replay reader for MTX.

A Taiwan futures trading day is represented historically by the observed day
session.  Full-session Replay for trading day T begins at 15:00 of the previous
observed trading day and ends at 13:45 of T.  This correctly keeps Friday night
/ Saturday early-morning ticks with the following Monday trading day when the
observed calendar has a weekend gap.

The row-group index is built once per Parquet file and cached in-process.  All
OHLC aggregation preserves physical `_seq` order for open/close.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .engine import OUTRIGHT_RE, _to_dt, _txt

TIMEFRAME_RULES = {
    "1s": "1s", "5s": "5s", "15s": "15s", "30s": "30s",
    "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min",
}
DAY_START = 8 * 3600 + 45 * 60
DAY_END = 13 * 3600 + 45 * 60
NIGHT_START = 15 * 3600


@dataclass
class RowGroupInfo:
    rg: int
    seq_start: int
    seq_end: int
    min_dt: pd.Timestamp | None
    max_dt: pd.Timestamp | None
    contracts: frozenset[str]


class ReplayFileIndex:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.pf = pq.ParquetFile(self.path)
        self.row_groups: list[RowGroupInfo] = []
        self.day_dates: dict[str, list[str]] = {}
        self._build()

    def _build(self):
        day_sets = defaultdict(set)
        offset = 0
        for rg in range(self.pf.num_row_groups):
            count = int(self.pf.metadata.row_group(rg).num_rows)
            d = self.pf.read_row_group(rg, columns=["datetime", "product", "expiry"]).to_pandas()
            products = d["product"].map(_txt)
            expiries = d["expiry"].map(_txt)
            dt = _to_dt(d["datetime"])
            mask = products.eq("MTX") & expiries.str.match(OUTRIGHT_RE)
            xdt = dt.loc[mask]
            xexp = expiries.loc[mask]
            contracts = frozenset(str(x) for x in xexp.dropna().unique())
            min_dt = pd.Timestamp(xdt.min()) if len(xdt) else None
            max_dt = pd.Timestamp(xdt.max()) if len(xdt) else None
            if len(xdt):
                sec = xdt.dt.hour * 3600 + xdt.dt.minute * 60 + xdt.dt.second
                day_mask = (sec >= DAY_START) & (sec <= DAY_END)
                day_frame = pd.DataFrame({"dt": xdt.loc[day_mask], "expiry": xexp.loc[day_mask]})
                if len(day_frame):
                    day_frame["date"] = day_frame["dt"].dt.strftime("%Y-%m-%d")
                    for contract, grp in day_frame.groupby("expiry", sort=False):
                        day_sets[str(contract)].update(str(x) for x in grp["date"].unique())
            self.row_groups.append(RowGroupInfo(
                rg=rg, seq_start=offset, seq_end=offset + count - 1,
                min_dt=min_dt, max_dt=max_dt, contracts=contracts,
            ))
            offset += count
        self.day_dates = {k: sorted(v) for k, v in day_sets.items()}

    def trading_days(self, contract: str) -> list[str]:
        return list(self.day_dates.get(str(contract), []))

    def target_days(self, center_day: str, contract: str, before=1, after=1) -> list[str]:
        days = self.trading_days(contract)
        if not days:
            return [str(center_day)[:10]]
        center = str(center_day)[:10]
        if center in days:
            i = days.index(center)
        else:
            stamps = [pd.Timestamp(x) for x in days]
            c = pd.Timestamp(center)
            i = min(range(len(stamps)), key=lambda j: abs(stamps[j] - c))
        lo = max(0, i - max(0, int(before)))
        hi = min(len(days), i + max(0, int(after)) + 1)
        return days[lo:hi]

    def full_bounds(self, target_days: list[str], contract: str):
        days = self.trading_days(contract)
        if not target_days:
            return None, None
        first = target_days[0]
        last = target_days[-1]
        try:
            i = days.index(first)
        except ValueError:
            i = 0
        if i > 0:
            prev = pd.Timestamp(days[i - 1])
            start = prev + pd.Timedelta(hours=15)
        else:
            start = pd.Timestamp(first) + pd.Timedelta(hours=0)
        end = pd.Timestamp(last) + pd.Timedelta(hours=13, minutes=45, seconds=59, milliseconds=999)
        return start, end

    def relevant_row_groups(self, start: pd.Timestamp, end: pd.Timestamp, contract: str):
        out = []
        c = str(contract)
        for info in self.row_groups:
            if c not in info.contracts:
                continue
            if info.min_dt is None or info.max_dt is None:
                continue
            if info.max_dt < start or info.min_dt > end:
                continue
            out.append(info)
        return out


_INDEX_CACHE: dict[tuple[str, int], ReplayFileIndex] = {}
_INDEX_LOCK = RLock()


def get_index(path: Path) -> ReplayFileIndex:
    p = Path(path)
    key = (str(p.resolve()), int(p.stat().st_mtime_ns))
    with _INDEX_LOCK:
        hit = _INDEX_CACHE.get(key)
        if hit is not None:
            return hit
        # Drop stale versions of the same path.
        for old in [x for x in _INDEX_CACHE if x[0] == key[0] and x != key]:
            _INDEX_CACHE.pop(old, None)
        idx = ReplayFileIndex(p)
        _INDEX_CACHE[key] = idx
        return idx


def _read_window(path: Path, target_days: list[str], contract: str, session="full"):
    idx = get_index(path)
    if not target_days:
        return pd.DataFrame()
    if session == "day":
        start = pd.Timestamp(target_days[0]) + pd.Timedelta(hours=8, minutes=45)
        end = pd.Timestamp(target_days[-1]) + pd.Timedelta(hours=13, minutes=45, seconds=59, milliseconds=999)
    else:
        start, end = idx.full_bounds(target_days, contract)
    if start is None or end is None:
        return pd.DataFrame()
    parts = []
    wanted_days = set(target_days)
    for info in idx.relevant_row_groups(start, end, contract):
        d = idx.pf.read_row_group(info.rg, columns=["datetime", "product", "expiry", "price", "volume", "side"]).to_pandas()
        d["_seq"] = np.arange(info.seq_start, info.seq_end + 1, dtype=np.int64)
        d["product"] = d["product"].map(_txt)
        d["expiry"] = d["expiry"].map(_txt)
        d["dt"] = _to_dt(d["datetime"])
        mask = d["product"].eq("MTX") & d["expiry"].eq(str(contract)) & (d["dt"] >= start) & (d["dt"] <= end)
        if session == "day":
            sec = d["dt"].dt.hour * 3600 + d["dt"].dt.minute * 60 + d["dt"].dt.second
            cal = d["dt"].dt.strftime("%Y-%m-%d")
            mask &= cal.isin(wanted_days) & (sec >= DAY_START) & (sec <= DAY_END)
        x = d.loc[mask]
        if not x.empty:
            parts.append(x)
    if not parts:
        return pd.DataFrame()
    # Row groups were read in physical order; concat preserves that order.
    return pd.concat(parts, ignore_index=True)


def aggregate_bars(d: pd.DataFrame, timeframe="1s"):
    if d.empty:
        return []
    rule = TIMEFRAME_RULES.get(timeframe)
    if not rule:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    rows = []
    bucket = d["dt"].dt.floor(rule)
    for ts, b in d.groupby(bucket, sort=False):
        rows.append({
            "timestamp": int(pd.Timestamp(ts).value // 1_000_000),
            "open": float(b["price"].iloc[0]),
            "high": float(b["price"].max()),
            "low": float(b["price"].min()),
            "close": float(b["price"].iloc[-1]),
            "volume": float(b["volume"].sum()),
            "firstSeq": int(b["_seq"].iloc[0]),
            "lastSeq": int(b["_seq"].iloc[-1]),
        })
    return rows


def replay_trading_window(root: Path, event: dict, node_meta: dict | None = None, node_id: str | None = None,
                          before=1, after=1, timeframe="1m", session="full"):
    source = event.get("source_file")
    if not source:
        return {"bars": [], "dates": []}
    path = Path(root) / source
    if not path.exists():
        return {"bars": [], "dates": []}
    center = event.get("trading_date") or event.get("date")
    if node_id and node_meta and node_id in node_meta:
        t = node_meta[node_id].get("decision_time") or node_meta[node_id].get("anchor_time")
        if t:
            center = str(t)[:10]
    idx = get_index(path)
    dates = idx.target_days(str(center)[:10], str(event.get("contract")), before, after)
    d = _read_window(path, dates, str(event.get("contract")), session=session)
    bars = aggregate_bars(d, timeframe=timeframe)
    return {
        "bars": bars, "dates": dates, "timeframe": timeframe, "session": session,
        "source_rows": int(len(d)),
        "first_seq": int(d["_seq"].iloc[0]) if len(d) else None,
        "last_seq": int(d["_seq"].iloc[-1]) if len(d) else None,
        "trading_day_definition": "previous observed day 15:00 -> trading day 13:45" if session == "full" else "08:45 -> 13:45",
    }


def read_tick_path(root: Path, event: dict, start_seq: int, max_dates_after=1):
    source = event.get("source_file")
    if not source:
        return pd.DataFrame()
    path = Path(root) / source
    if not path.exists():
        return pd.DataFrame()
    center = event.get("trading_date") or event.get("date")
    idx = get_index(path)
    dates = idx.target_days(str(center)[:10], str(event.get("contract")), 0, max_dates_after)
    d = _read_window(path, dates, str(event.get("contract")), session="full")
    if d.empty:
        return d
    return d.loc[d["_seq"] >= int(start_seq)].reset_index(drop=True)


def clear_index_cache():
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()


__all__ = [
    "TIMEFRAME_RULES", "ReplayFileIndex", "get_index", "aggregate_bars",
    "replay_trading_window", "read_tick_path", "clear_index_cache",
]
