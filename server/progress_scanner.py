from __future__ import annotations

"""Observable scanner wrapper for Fabio Decision Gym.

The structural detection logic remains in ``server.engine`` / ``server.causal_engine``.
This module only adds granular progress around the three expensive Parquet passes:

1. catalog / source-order QA
2. contract/session map
3. active-day event scan

It deliberately does not reorder raw ticks.  The first pass also persists the
source-integrity funnel, while the second pass persists the exact causal contract
selection used for each trading day so a real-data diagnostic is auditable.
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# Public scanner behavior (especially choose_contracts) comes through the causal
# facade. Private parsing helpers are imported directly from engine because
# Python wildcard imports intentionally omit names beginning with an underscore.
from .causal_engine import (
    ScanConfig,
    choose_contracts,
    connect,
    discover,
    profile_levels,
    scan_day,
    write_events,
)
from .engine import OUTRIGHT_RE, _session_seconds, _to_dt, _txt


def _emit(progress, **payload):
    if progress:
        progress(payload)


def _ensure_audit_tables(con):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS dataset_integrity(
          file TEXT PRIMARY KEY,
          year INTEGER,
          source_rows INTEGER,
          mtx_rows INTEGER,
          outright_rows INTEGER,
          spread_removed_rows INTEGER,
          outright_contracts_json TEXT,
          source_order_qa TEXT,
          scanned_at TEXT
        );
        CREATE TABLE IF NOT EXISTS contract_selection_audit(
          source_file TEXT,
          trading_date TEXT,
          selected_contract TEXT,
          candidate_contracts_json TEXT,
          candidate_volumes_raw_json TEXT,
          candidate_volumes_normalized_json TEXT,
          selected_volume_raw REAL,
          selected_volume_normalized REAL,
          roll INTEGER,
          ambiguous INTEGER,
          causal INTEGER,
          mode TEXT,
          reason TEXT,
          PRIMARY KEY(source_file,trading_date)
        );
        CREATE INDEX IF NOT EXISTS ix_contract_selection_date
          ON contract_selection_audit(trading_date,selected_contract);
        """
    )
    con.commit()


def _catalog_file(path: Path, cfg: ScanConfig, progress=None, common=None):
    pf = pq.ParquetFile(path)
    total = int(pf.metadata.num_rows)
    products, expiries = set(), set()
    outright_contracts = set()
    first = last = None
    seen = 0
    backward = 0
    previous_last = None
    mtx_rows = 0
    outright_rows = 0
    spread_removed_rows = 0
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
        product = d["product"].map(_txt)
        expiry = d["expiry"].map(_txt)
        products.update(product.dropna().unique())
        expiries.update(expiry.dropna().unique())
        is_mtx = product == cfg.product
        is_outright = expiry.str.fullmatch(OUTRIGHT_RE)
        mtx_rows += int(is_mtx.sum())
        outright_rows += int((is_mtx & is_outright).sum())
        spread_removed_rows += int((is_mtx & ~is_outright).sum())
        outright_contracts.update(expiry.loc[is_mtx & is_outright].unique())
        seen += len(d)
        _emit(
            progress,
            **(common or {}),
            phase="catalog",
            phase_label="資料目錄 / Source-order QA",
            file_rows_processed=seen,
            file_rows_total=total,
            pass_rows_processed=seen,
            pass_rows_total=total,
            mtx_rows=mtx_rows,
            outright_rows=outright_rows,
            spread_removed_rows=spread_removed_rows,
            message=f"Catalog QA：{seen:,} / {total:,} rows",
        )
    m = re.search(r"(\d{4})", path.stem)
    return {
        "file": path.name,
        "year": int(m.group(1)) if m else 0,
        "rows": total,
        "source_rows": total,
        "mtx_rows": mtx_rows,
        "outright_rows": outright_rows,
        "spread_removed_rows": spread_removed_rows,
        "outright_contracts": sorted(str(x) for x in outright_contracts),
        "start": first.isoformat() if first is not None else None,
        "end": last.isoformat() if last is not None else None,
        "products": sorted(str(x) for x in products),
        "expiries": sorted(str(x) for x in expiries),
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
            & d["expiry"].str.fullmatch(OUTRIGHT_RE)
            & (sec >= start_sec)
            & (sec <= end_sec)
        )
        x = d.loc[mask, ["expiry", "volume"]].copy()
        if not x.empty:
            x["date"] = dt.loc[mask].dt.strftime("%Y-%m-%d").to_numpy()
            grouped = x.groupby(["date", "expiry"], sort=False)["volume"].sum()
            for (day, expiry), vol in grouped.items():
                acc[day][expiry] += float(vol)
        _emit(
            progress,
            **(common or {}),
            phase="contract_map",
            phase_label="Contract / Session Map",
            file_rows_processed=seen,
            file_rows_total=total,
            pass_rows_processed=seen,
            pass_rows_total=total,
            trading_days_found=len(acc),
            message=f"合約與日盤索引：{seen:,} / {total:,} rows · {len(acc)} days",
        )
    return acc


def _persist_contract_audit(con, file: Path, volume_map, active):
    """Freeze the exact causal selection inputs/results used by the scanner.

    Raw vendor volume is two-sided in the supplied MTX files.  The normalized
    audit values are therefore raw/2.  Contract ranking itself is invariant to
    this uniform normalization, but both forms are persisted for transparency.
    """
    for day in sorted(active):
        pick = active[day]
        vols = volume_map.get(day, {})
        candidates = sorted(str(e) for e in vols if OUTRIGHT_RE.fullmatch(str(e)))
        raw = {str(e): float(vols[e]) for e in candidates}
        normalized = {e: v / 2.0 for e, v in raw.items()}
        selected = pick.get("contract")
        selected_raw = float(raw.get(selected, 0.0)) if selected else 0.0
        con.execute(
            """INSERT OR REPLACE INTO contract_selection_audit(
            source_file,trading_date,selected_contract,candidate_contracts_json,
            candidate_volumes_raw_json,candidate_volumes_normalized_json,
            selected_volume_raw,selected_volume_normalized,roll,ambiguous,causal,mode,reason)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                file.name,
                day,
                selected,
                json.dumps(candidates, ensure_ascii=False),
                json.dumps(raw, ensure_ascii=False),
                json.dumps(normalized, ensure_ascii=False),
                selected_raw,
                selected_raw / 2.0,
                int(bool(pick.get("roll"))),
                int(bool(pick.get("ambiguous"))),
                int(bool(pick.get("causal", pick.get("mode") != "dominant_volume"))),
                pick.get("mode"),
                pick.get("reason"),
            ),
        )
    con.commit()


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
        # Immutable physical sequence MUST be assigned before any filter.
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
            & d["expiry"].str.fullmatch(OUTRIGHT_RE)
            & (d["sec"] >= start_sec)
            & (d["sec"] <= end_sec)
        )
        # Filtering preserves original row order; no sort_values is permitted.
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
        _emit(
            progress,
            **(common or {}),
            phase="scan_rows",
            phase_label="Active Contract Tick Scan",
            file_rows_processed=seen,
            file_rows_total=total,
            pass_rows_processed=seen,
            pass_rows_total=total,
            current_day=current_day,
            message=f"讀取有效 Tick：{seen:,} / {total:,} rows",
        )
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
    last_work_rows = 0
    total_events = 0
    counters = {"mr": 0, "bo": 0, "wait": 0, "entries": 0}
    node_counts = {}
    con = connect(db)
    _ensure_audit_tables(con)
    now = lambda: datetime.now(timezone.utc).isoformat()

    def report(file, file_index, phase_offset, **extra):
        nonlocal last_work_rows
        pass_rows = int(extra.get("pass_rows_processed") or 0)
        computed = min(total_work_rows, completed_work_rows + pass_rows)
        # Day-level messages may arrive after a raw-batch heartbeat. Never let the
        # API progress percentage move backwards just because that message has no
        # pass-row counter of its own.
        work_rows = max(last_work_rows, computed)
        last_work_rows = work_rows
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
        _emit(
            progress,
            phase="prepare",
            phase_label="準備掃描",
            files_total=len(files),
            source_rows_total=total_source_rows,
            work_rows_total=total_work_rows,
            work_rows_processed=0,
            percent=0.0,
            events=0,
            mr=0,
            bo=0,
            wait=0,
            entries=0,
            node_counts={},
            message=f"找到 {len(files)} 個檔案，共 {total_source_rows:,} source rows；預估需 3-pass 掃描。",
        )
        for file_index, file in enumerate(files, 1):
            def cat_progress(p):
                report(file, file_index, completed_work_rows, **p)

            cat = _catalog_file(file, cfg, cat_progress)
            completed_work_rows += file_rows[file.name]
            con.execute(
                "INSERT OR REPLACE INTO datasets VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    cat["file"], cat["year"], cat["rows"], cat["start"], cat["end"],
                    json.dumps(cat["products"]), json.dumps(cat["expiries"]), cat["qa"], now(),
                ),
            )
            con.execute(
                """INSERT OR REPLACE INTO dataset_integrity(
                file,year,source_rows,mtx_rows,outright_rows,spread_removed_rows,
                outright_contracts_json,source_order_qa,scanned_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    cat["file"], cat["year"], cat["source_rows"], cat["mtx_rows"],
                    cat["outright_rows"], cat["spread_removed_rows"],
                    json.dumps(cat["outright_contracts"], ensure_ascii=False), cat["qa"], now(),
                ),
            )
            con.commit()
            report(
                file,
                file_index,
                completed_work_rows,
                phase="catalog_done",
                phase_label="Catalog QA 完成",
                pass_rows_processed=0,
                pass_rows_total=file_rows[file.name],
                file_rows_processed=file_rows[file.name],
                file_rows_total=file_rows[file.name],
                qa=cat["qa"],
                mtx_rows=cat["mtx_rows"],
                outright_rows=cat["outright_rows"],
                spread_removed_rows=cat["spread_removed_rows"],
                message=f"{file.name} Catalog QA：{cat['qa']}",
            )
            if cat["qa"] != "PASS":
                completed_work_rows += file_rows[file.name] * 2
                report(
                    file,
                    file_index,
                    completed_work_rows,
                    phase="qa_failed",
                    phase_label="Source-order QA 失敗",
                    pass_rows_processed=0,
                    file_rows_processed=file_rows[file.name],
                    file_rows_total=file_rows[file.name],
                    qa=cat["qa"],
                    message=f"{file.name} QA_FAIL，已略過事件掃描。",
                )
                continue

            def contract_progress(p):
                report(file, file_index, completed_work_rows, **p)

            volume_map = _daily_contract_volume(file, cfg, contract_progress)
            completed_work_rows += file_rows[file.name]
            active = choose_contracts(volume_map, cfg.contract_mode)
            _persist_contract_audit(con, file, volume_map, active)
            days_total = len(active)
            roll_days = sum(bool(x.get("roll")) for x in active.values())
            report(
                file,
                file_index,
                completed_work_rows,
                phase="contract_done",
                phase_label="Contract Map 完成",
                pass_rows_processed=0,
                trading_days_found=days_total,
                days_total=days_total,
                roll_days=roll_days,
                message=f"{file.name}：找到 {days_total} 個日盤交易日，{roll_days} 個 roll days。",
            )

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
                # A roll day is blacked out before previous_profile is replaced;
                # the next eligible day therefore uses the new contract's own
                # previous-day profile rather than a cross-contract profile.
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
                    file,
                    file_index,
                    completed_work_rows,
                    phase="scan_day",
                    phase_label="Auction / MR / BO Event Scan",
                    pass_rows_processed=0,
                    file_rows_processed=None,
                    file_rows_total=file_rows[file.name],
                    current_day=day,
                    current_contract=contract,
                    days_processed=days_processed,
                    days_total=days_total,
                    events_today=len(events),
                    message=f"{day} {contract}：+{len(events)} events · 累積 {total_events}",
                )

            completed_work_rows += file_rows[file.name]
            report(
                file,
                file_index,
                completed_work_rows,
                phase="file_done",
                phase_label="年度檔案完成",
                pass_rows_processed=0,
                days_processed=days_processed,
                days_total=days_total,
                message=f"{file.name} 完成：累積 {total_events} events。",
            )

        con.commit()
        last_work_rows = total_work_rows
        _emit(
            progress,
            phase="done",
            phase_label="掃描完成",
            files_total=len(files),
            source_rows_total=total_source_rows,
            work_rows_processed=total_work_rows,
            work_rows_total=total_work_rows,
            percent=1.0,
            events=total_events,
            mr=counters["mr"],
            bo=counters["bo"],
            wait=counters["wait"],
            entries=counters["entries"],
            node_counts=node_counts,
            message=f"掃描完成：{total_events} events。",
        )
        return total_events
    finally:
        con.close()
