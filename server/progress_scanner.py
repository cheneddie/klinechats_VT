from __future__ import annotations

"""Observable scanner wrapper for Fabio Decision Gym.

The structural detection logic remains in ``server.engine`` / ``server.causal_engine``.
This module only adds granular progress around the three expensive Parquet passes:

1. catalog / source-order QA
2. contract/session map
3. active-day event scan

It deliberately does not reorder raw ticks.
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .causal_engine import (
    OUTRIGHT_RE,
    ScanConfig,
    _session_seconds,
    _to_dt,
    _txt,
    choose_contracts,
    connect,
    discover,
    profile_levels,
    scan_day,
    write_events,
)


def _emit(progress, **payload):
    if progress:
        progress(payload)


def _catalog_file(path: Path, progress=None, common=None):
    pf = pq.ParquetFile(path)
    total = int(pf.metadata.num_rows)
    products, expiries = set(), set()
    first = last = None
    seen = 0
    backward = 0
    previous_last = None
    for batch in pf.iter_batches(batch_size=250_000, columns=["datetime", "product", "expiry"]):
        d = batch.to_pandas()
        dt = _to_dt(d["datetime"])
        if len(dt):
            if first is None:
                first = dt.iloc[0]
            last = dt.iloc[-1]
            if not dt.is_monotonic_increasing:
                backward += 1
            if previous_last is not None and dt.iloc[0] < previous_last:
                backward += 1
            previous_last = dt.iloc[-1]
        products.update(_txt(x) for x in d["product"].dropna().unique())
        expiries.update(_txt(x) for x in d["expiry"].dropna().unique())
        seen += len(d)
        _emit(progress, **(common or {}), phase="catalog", phase_label="資料目錄 / Source-order QA", file_rows_processed=seen, file_rows_total=total, pass_rows_processed=seen, pass_rows_total=total, message=f"Catalog QA：{seen:,} / {total:,} rows")
    m = re.search(r"(\d{4})", path.stem)
    return {
        "file": path.name,
        "year": int(m.group(1)) if m else 0,
        "rows": total,
        "start": first.isoformat() if first is not None else None,
        "end": last.isoformat() if last is not None else None,
        "products": sorted(products),
        "expiries": sorted(expiries),
        "qa": "PASS" if backward == 0 and seen == total else "FAIL",
    }


def _daily_contract_volume(path: Path, cfg: ScanConfig, progress=None, common=None):
    pf = pq.ParquetFile(path)
    total = int(pf.metadata.num_rows)
    acc = defaultdict(lambda: defaultdict(float))
    start_sec = _session_seconds(cfg.session_start)
    end_sec = _session_seconds(cfg.session_end)
    seen = 0
    for batch in pf.iter_batches(batch_size=400_000, columns=["datetime", "product", "expiry", "volume"]):
        d = batch.to_pandas()
        seen += len(d)
        d["product"] = d["product"].map(_txt)
        d["expiry"] = d["expiry"].map(_txt)
        dt = _to_dt(d["datetime"])
        sec = dt.dt.hour * 3600 + dt.dt.minute * 60 + dt.dt.second
        mask = (
            (d["product"] == cfg.product)
            & d["expiry"].str.match(OUTRIGHT_RE)
            & (sec >= start_sec)
            & (sec <= end_sec)
        )
        x = d.loc[mask, ["expiry", "volume"]].copy()
        if not x.empty:
            x["date"] = dt.loc[mask].dt.strftime("%Y-%m-%d").to_numpy()
            grouped = x.groupby(["date", "expiry"], sort=False)["volume"].sum()
            for (day, expiry), vol in grouped.items():
                acc[day][expiry] += float(vol)
        _emit(progress, **(common or {}), phase="contract_map", phase_label="Contract / Session Map", file_rows_processed=seen, file_rows_total=total, pass_rows_processed=seen, pass_rows_total=total, trading_days_found=len(acc), message=f"合約與日盤索引：{seen:,} / {total:,} rows · {len(acc)} days")
    return acc


def _iter_active_days(path: Path, active: dict, cfg: ScanConfig, progress=None, common=None):
    pf = pq.ParquetFile(path)
    total = int(pf.metadata.num_rows)
    seq = 0
    current_day = None
    parts = []
    seen = 0
    start_sec = _session_seconds(cfg.session_start)
    end_sec = _session_seconds(cfg.session_end)

    def emit(day, frames):
        if day is None or not frames:
            return None
        return day, pd.concat(frames, ignore_index=True)

    for batch in pf.iter_batches(batch_size=300_000, columns=["datetime", "product", "expiry", "price", "volume", "side"]):
        d = batch.to_pandas()
        d["_seq"] = np.arange(seq, seq + len(d), dtype=np.int64)
        seq += len(d)
        seen += len(d)
        d["product"] = d["product"].map(_txt)
        d["expiry"] = d["expiry"].map(_txt)
        d["dt"] = _to_dt(d["datetime"])
        d["date"] = d["dt"].dt.strftime("%Y-%m-%d")
        d["sec"] = d["dt"].dt.hour * 3600 + d["dt"].dt.minute * 60 + d["dt"].dt.second
        mask = (
            (d["product"] == cfg.product)
            & d["expiry"].str.match(OUTRIGHT_RE)
            & (d["sec"] >= start_sec)
            & (d["sec"] <= end_sec)
        )
        d = d.loc[mask]
        for day, frame in d.groupby("date", sort=False):
            contract = active.get(day, {}).get("contract")
            frame = frame.loc[frame["expiry"] == contract]
            if frame.empty:
                continue
            if current_day is None:
                current_day = day
            if day != current_day:
                item = emit(current_day, parts)
                if item:
                    yield item
                current_day, parts = day, []
            parts.append(frame)
        _emit(progress, **(common or {}), phase="scan_rows", phase_label="Active Contract Tick Scan", file_rows_processed=seen, file_rows_total=total, pass_rows_processed=seen, pass_rows_total=total, current_day=current_day, message=f"讀取有效 Tick：{seen:,} / {total:,} rows")
    item = emit(current_day, parts)
    if item:
        yield item


def _update_counts(events, counters, nodes):
    for e in events:
        strategy = e.get("strategy") or "WAIT"
        if strategy == "MR":
            counters["mr"] += 1
        elif strategy == "BO":
            counters["bo"] += 1
        else:
            counters["wait"] += 1
        if e.get("result") == "ENTRY":
            counters["entries"] += 1
        for node_id, x in (e.get("nodes") or {}).items():
            row = nodes.setdefault(node_id, {"total": 0, "yes": 0, "no": 0})
            row["total"] += 1
            if x.get("answer"):
                row["yes"] += 1
            else:
                row["no"] += 1


def scan_files_progress(root: Path, db: Path, years=None, config=None, progress=None):
    cfg = config or ScanConfig()
    files = discover(root)
    if years:
        ys = {int(y) for y in years}
        files = [p for p in files if any(str(y) in p.stem for y in ys)]
    if not files:
        raise FileNotFoundError(f"No MTX_*.parquet matched years={years} under {root}")

    file_rows = {p.name: int(pq.ParquetFile(p).metadata.num_rows) for p in files}
    total_source_rows = sum(file_rows.values())
    total_work_rows = total_source_rows * 3
    completed_work_rows = 0
    total_events = 0
    counters = {"mr": 0, "bo": 0, "wait": 0, "entries": 0}
    node_counts = {}
    con = connect(db)
    now = lambda: datetime.now(timezone.utc).isoformat()

    def report(file, file_index, phase_offset, **extra):
        pass_rows = int(extra.get("pass_rows_processed") or 0)
        work_rows = min(total_work_rows, completed_work_rows + pass_rows)
        payload = {
            "file": file.name,
            "file_index": file_index,
            "files_total": len(files),
            "source_rows_total": total_source_rows,
            "work_rows_processed": work_rows,
            "work_rows_total": total_work_rows,
            "percent": (work_rows / total_work_rows) if total_work_rows else 0.0,
            "events": total_events,
            "mr": counters["mr"],
            "bo": counters["bo"],
            "wait": counters["wait"],
            "entries": counters["entries"],
            "node_counts": node_counts,
        }
        payload.update(extra)
        _emit(progress, **payload)

    try:
        _emit(progress, phase="prepare", phase_label="準備掃描", files_total=len(files), source_rows_total=total_source_rows, work_rows_total=total_work_rows, work_rows_processed=0, percent=0.0, events=0, mr=0, bo=0, wait=0, entries=0, node_counts={}, message=f"找到 {len(files)} 個檔案，共 {total_source_rows:,} source rows；預估需 3-pass 掃描。")
        for file_index, file in enumerate(files, 1):
            def cat_progress(p):
                report(file, file_index, completed_work_rows, **p)

            cat = _catalog_file(file, cat_progress)
            completed_work_rows += file_rows[file.name]
            con.execute(
                "INSERT OR REPLACE INTO datasets VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    cat["file"], cat["year"], cat["rows"], cat["start"], cat["end"],
                    json.dumps(cat["products"]), json.dumps(cat["expiries"]), cat["qa"], now(),
                ),
            )
            con.commit()
            report(file, file_index, completed_work_rows, phase="catalog_done", phase_label="Catalog QA 完成", pass_rows_processed=0, pass_rows_total=file_rows[file.name], file_rows_processed=file_rows[file.name], file_rows_total=file_rows[file.name], qa=cat["qa"], message=f"{file.name} Catalog QA：{cat['qa']}")
            if cat["qa"] != "PASS":
                completed_work_rows += file_rows[file.name] * 2
                report(file, file_index, completed_work_rows, phase="qa_failed", phase_label="Source-order QA 失敗", pass_rows_processed=0, file_rows_processed=file_rows[file.name], file_rows_total=file_rows[file.name], qa=cat["qa"], message=f"{file.name} QA_FAIL，已略過事件掃描。")
                continue

            def contract_progress(p):
                report(file, file_index, completed_work_rows, **p)

            volume_map = _daily_contract_volume(file, cfg, contract_progress)
            completed_work_rows += file_rows[file.name]
            active = choose_contracts(volume_map, cfg.contract_mode)
            days_total = len(active)
            report(file, file_index, completed_work_rows, phase="contract_done", phase_label="Contract Map 完成", pass_rows_processed=0, trading_days_found=days_total, days_total=days_total, message=f"{file.name}：找到 {days_total} 個日盤交易日。")

            previous_profile = None
            previous_contract = None
            blackout = 0
            days_processed = 0

            def row_progress(p):
                p["days_processed"] = days_processed
                p["days_total"] = days_total
                report(file, file_index, completed_work_rows, **p)

            for day, g in _iter_active_days(file, active, cfg, row_progress):
                days_processed += 1
                contract = active[day]["contract"]
                roll = previous_contract is not None and contract != previous_contract
                if roll:
                    blackout = cfg.roll_blackout_days
                profile = profile_levels(g, cfg.value_area)
                ambiguous = cfg.contract_mode == "strict" and active[day].get("ambiguous", False)
                events = []
                if previous_profile is not None and blackout <= 0 and not ambiguous:
                    events = scan_day(g, previous_profile, cfg, file, day, contract)
                    write_events(con, events, now())
                    total_events += len(events)
                    _update_counts(events, counters, node_counts)
                    con.commit()
                if blackout > 0:
                    blackout -= 1
                previous_profile = profile
                previous_contract = contract
                report(
                    file, file_index, completed_work_rows,
                    phase="scan_day", phase_label="Auction / MR / BO Event Scan",
                    pass_rows_processed=0, file_rows_processed=None, file_rows_total=file_rows[file.name],
                    current_day=day, current_contract=contract, days_processed=days_processed, days_total=days_total,
                    events_today=len(events),
                    message=f"{day} {contract}：+{len(events)} events · 累積 {total_events}",
                )

            completed_work_rows += file_rows[file.name]
            report(file, file_index, completed_work_rows, phase="file_done", phase_label="年度檔案完成", pass_rows_processed=0, days_processed=days_processed, days_total=days_total, message=f"{file.name} 完成：累積 {total_events} events。")

        con.commit()
        _emit(progress, phase="done", phase_label="掃描完成", files_total=len(files), source_rows_total=total_source_rows, work_rows_processed=total_work_rows, work_rows_total=total_work_rows, percent=1.0, events=total_events, mr=counters["mr"], bo=counters["bo"], wait=counters["wait"], entries=counters["entries"], node_counts=node_counts, message=f"掃描完成：{total_events} events。")
        return total_events
    finally:
        con.close()
