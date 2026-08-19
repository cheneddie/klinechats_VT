from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

OUTRIGHT_RE = re.compile(r"^\d{6}$")


@dataclass
class ScanConfig:
    product: str = "MTX"
    value_area: float = 0.80
    session_start: str = "08:45:00"
    session_end: str = "13:45:00"
    excursion_pct: float = 0.02
    min_excursion_points: float = 2.0
    reclaim_pct: float = 0.08
    reclaim_max_sec: int = 60
    auction_max_sec: int = 180
    turn_points: float = 8.0
    lvn_depth: float = 0.55
    lvn_tolerance: float = 1.0
    pullback_max_sec: int = 120
    mr_stop_points: float = 6.0
    mr_target_r: float = 0.75
    acceptance_outside_ratio: float = 0.70
    acceptance_displacement_pct: float = 0.20
    acceptance_window_sec: int = 20
    bo_response_points: float = 2.0
    bo_stop_points: float = 8.0
    bo_target_r: float = 1.0
    contract_mode: str = "strict"
    roll_blackout_days: int = 1


def _txt(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return str(v)


def _to_dt(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s)
    if pd.api.types.is_integer_dtype(s) or pd.api.types.is_float_dtype(s):
        vals = pd.to_numeric(s, errors="coerce")
        med = float(vals.dropna().abs().median()) if vals.notna().any() else 0
        if med > 1e17:
            unit = "ns"
        elif med > 1e14:
            unit = "us"
        elif med > 1e11:
            unit = "ms"
        else:
            unit = "s"
        return pd.to_datetime(vals, unit=unit)
    return pd.to_datetime(s)


def _session_seconds(text: str) -> int:
    h, m, s = [int(x) for x in text.split(":")]
    return h * 3600 + m * 60 + s


def connect(db: Path):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS datasets(
          file TEXT PRIMARY KEY,year INTEGER,rows INTEGER,start TEXT,end TEXT,
          products TEXT,expiries TEXT,qa TEXT,scanned_at TEXT);
        CREATE TABLE IF NOT EXISTS events(
          event_id TEXT PRIMARY KEY, source_file TEXT, year INTEGER,
          trading_date TEXT, contract TEXT, strategy TEXT, direction TEXT,
          result TEXT, difficulty INTEGER,
          attempt_start_seq INTEGER, attempt_start_time TEXT,
          context_start_seq INTEGER, context_end_seq INTEGER,
          extreme_seq INTEGER, extreme_time TEXT, extreme_price REAL,
          clear_reclaim_seq INTEGER, clear_reclaim_time TEXT, clear_reclaim_price REAL,
          turn_confirm_seq INTEGER, turn_confirm_time TEXT,
          lvn REAL, entry_seq INTEGER, entry_time TEXT, entry_price REAL,
          stop REAL, target REAL,
          vah REAL,val REAL,poc REAL,value_width REAL,
          features_json TEXT,nodes_json TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS node_instances(
          event_id TEXT,node_id TEXT,answer INTEGER,
          decision_seq INTEGER,decision_time TEXT,difficulty INTEGER,
          PRIMARY KEY(event_id,node_id));
        CREATE INDEX IF NOT EXISTS ix_node ON node_instances(node_id,answer);
        CREATE INDEX IF NOT EXISTS ix_event_date ON events(trading_date,strategy);
        CREATE INDEX IF NOT EXISTS ix_event_contract ON events(contract,trading_date);
        CREATE TABLE IF NOT EXISTS scan_runs(
          job_id TEXT PRIMARY KEY,status TEXT,started_at TEXT,finished_at TEXT,
          years TEXT,config_json TEXT,events INTEGER,message TEXT);
        """
    )
    return con


def discover(root: Path):
    return sorted(root.glob("MTX_*.parquet"))


def catalog_file(path: Path):
    pf = pq.ParquetFile(path)
    products, expiries = set(), set()
    first = last = None
    seen = 0
    backward = 0
    previous_last = None
    for batch in pf.iter_batches(
        batch_size=250_000, columns=["datetime", "product", "expiry"]
    ):
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
    m = re.search(r"(\d{4})", path.stem)
    return {
        "file": path.name,
        "year": int(m.group(1)) if m else 0,
        "rows": int(pf.metadata.num_rows),
        "start": first.isoformat() if first is not None else None,
        "end": last.isoformat() if last is not None else None,
        "products": sorted(products),
        "expiries": sorted(expiries),
        "qa": "PASS" if backward == 0 and seen == pf.metadata.num_rows else "FAIL",
    }


def daily_contract_volume(path: Path, cfg: ScanConfig):
    pf = pq.ParquetFile(path)
    acc = defaultdict(lambda: defaultdict(float))
    start_sec = _session_seconds(cfg.session_start)
    end_sec = _session_seconds(cfg.session_end)
    for batch in pf.iter_batches(
        batch_size=400_000, columns=["datetime", "product", "expiry", "volume"]
    ):
        d = batch.to_pandas()
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
        if x.empty:
            continue
        x["date"] = dt.loc[mask].dt.strftime("%Y-%m-%d").to_numpy()
        grouped = x.groupby(["date", "expiry"], sort=False)["volume"].sum()
        for (day, expiry), vol in grouped.items():
            acc[day][expiry] += float(vol)
    return acc


def choose_contracts(volume_map, mode="strict"):
    out = {}
    previous = None
    for day in sorted(volume_map):
        vols = volume_map[day]
        ranked = sorted(vols.items(), key=lambda x: (-x[1], x[0]))
        dominant = ranked[0][0] if ranked else None
        ym = day[:7].replace("-", "")
        valid_front = sorted(e for e in vols if OUTRIGHT_RE.match(e) and e >= ym)
        front = valid_front[0] if valid_front else dominant
        pick = front if mode == "front_month" else dominant
        changed = previous is not None and pick != previous
        ambiguous = len(ranked) > 1 and ranked[0][1] < ranked[1][1] * 1.10
        out[day] = {
            "contract": pick,
            "roll": changed,
            "ambiguous": ambiguous,
            "volume": float(vols.get(pick, 0)),
            "second": float(ranked[1][1]) if len(ranked) > 1 else 0.0,
        }
        previous = pick
    return out


def profile_levels(g: pd.DataFrame, pct=0.80):
    pv = g.groupby("price", sort=True)["volume"].sum()
    prices = pv.index.to_numpy(float)
    vol = pv.to_numpy(float)
    if not len(vol) or vol.sum() <= 0:
        return None
    poc = int(np.argmax(vol))
    lo = hi = poc
    total = float(vol[poc])
    target = float(vol.sum() * pct)
    while total < target and (lo > 0 or hi < len(vol) - 1):
        left = vol[lo - 1] if lo > 0 else -1
        right = vol[hi + 1] if hi < len(vol) - 1 else -1
        if right > left:
            hi += 1
            total += float(vol[hi])
        else:
            lo -= 1
            total += float(vol[lo])
    return {
        "poc": float(prices[poc]),
        "val": float(prices[lo]),
        "vah": float(prices[hi]),
        "width": float(prices[hi] - prices[lo]),
    }


def valley_lvn(leg: pd.DataFrame, prior: dict, cfg: ScanConfig):
    if len(leg) < 10:
        return None, 0.0
    pv = leg.groupby("price", sort=True)["volume"].sum()
    prices = pv.index.to_numpy(float)
    vol = pv.to_numpy(float)
    if len(prices) < 5:
        return None, 0.0
    smooth = np.convolve(vol, np.ones(3) / 3, mode="same")
    low = prior["val"] + 0.05 * prior["width"]
    high = prior["vah"] - 0.05 * prior["width"]
    candidates = []
    for i in range(2, len(prices) - 2):
        if not low <= prices[i] <= high:
            continue
        if smooth[i] <= smooth[i - 1] and smooth[i] <= smooth[i + 1]:
            ref = min(max(smooth[i - 2 : i]), max(smooth[i + 1 : i + 3]))
            depth = 1 - smooth[i] / ref if ref > 0 else 0.0
            if depth >= cfg.lvn_depth:
                candidates.append((depth, float(prices[i])))
    if not candidates:
        return None, 0.0
    depth, price = max(candidates)
    return price, float(depth)


def _node(nodes, node_id, answer, seq=None, time=None):
    nodes[node_id] = {
        "answer": bool(answer),
        "seq": int(seq) if seq is not None else None,
        "time": time.isoformat() if hasattr(time, "isoformat") else time,
    }


def _seq(g, i):
    return int(g["_seq"].iloc[i]) if i is not None else None


def _time(g, i):
    return g["dt"].iloc[i] if i is not None else None


def _base(event_id, file, day, contract, direction, prior, start_i, g):
    return {
        "event_id": event_id,
        "source_file": file.name,
        "year": int(day[:4]),
        "trading_date": day,
        "contract": contract,
        "strategy": "WAIT",
        "direction": direction,
        "result": "WAIT",
        "difficulty": 2,
        "attempt_start_seq": _seq(g, start_i),
        "attempt_start_time": _time(g, start_i).isoformat(),
        "context_start_seq": max(0, _seq(g, start_i) - 20_000),
        "context_end_seq": _seq(g, min(len(g) - 1, start_i + 20_000)),
        "vah": prior["vah"],
        "val": prior["val"],
        "poc": prior["poc"],
        "value_width": prior["width"],
        "features": {},
        "nodes": {},
    }


def _difficulty(distance_to_threshold: float, extra=0):
    # Near-threshold cases are deliberately harder.
    if distance_to_threshold < 0.10:
        base = 5
    elif distance_to_threshold < 0.25:
        base = 4
    elif distance_to_threshold < 0.50:
        base = 3
    else:
        base = 2
    return int(max(1, min(5, base + extra)))


def scan_day(g: pd.DataFrame, prior: dict, cfg: ScanConfig, file: Path, day: str, contract: str):
    events = []
    n = len(g)
    if n < 10 or not prior or prior["width"] <= 0:
        return events
    excursion_need = max(cfg.min_excursion_points, cfg.excursion_pct * prior["width"])
    reclaim_need = max(3.0, cfg.reclaim_pct * prior["width"])
    i = 0
    attempt = 0
    while i < n:
        p0 = float(g["price"].iloc[i])
        up = p0 > prior["vah"]
        down = p0 < prior["val"]
        if not (up or down):
            i += 1
            continue
        attempt += 1
        boundary = prior["vah"] if up else prior["val"]
        start = i
        extreme = p0
        extreme_i = i
        qualified_i = None
        clear_i = None
        j = i + 1
        t_start = _time(g, start)
        while j < n and (_time(g, j) - t_start).total_seconds() <= cfg.auction_max_sec:
            price = float(g["price"].iloc[j])
            if up and price > extreme:
                extreme, extreme_i = price, j
            if down and price < extreme:
                extreme, extreme_i = price, j
            excursion = (extreme - boundary) if up else (boundary - extreme)
            if qualified_i is None and excursion >= excursion_need:
                qualified_i = j
            if qualified_i is not None and (_time(g, j) - _time(g, extreme_i)).total_seconds() <= cfg.reclaim_max_sec:
                if up and price <= boundary - reclaim_need:
                    clear_i = j
                    break
                if down and price >= boundary + reclaim_need:
                    clear_i = j
                    break
            j += 1

        mr_direction = "short" if up else "long"
        bo_direction = "long" if up else "short"
        event_id = f"{day}-{contract}-A{attempt:03d}"
        event = _base(event_id, file, day, contract, mr_direction, prior, start, g)
        nodes = event["nodes"]
        _node(nodes, "CTX_VALUE", True, _seq(g, start), _time(g, start))
        event.update(
            extreme_seq=_seq(g, extreme_i),
            extreme_time=_time(g, extreme_i).isoformat(),
            extreme_price=float(extreme),
        )
        excursion = (extreme - boundary) if up else (boundary - extreme)
        excursion_ratio = excursion / prior["width"]
        event["features"].update(
            auction_side="up" if up else "down",
            excursion_points=float(excursion),
            excursion_pct_value=float(excursion_ratio),
            excursion_threshold=float(excursion_need),
        )
        _node(nodes, "AUC_EXTREME", True, _seq(g, extreme_i), _time(g, extreme_i))

        if qualified_i is None:
            _node(nodes, "AUC_ATTEMPT", False, _seq(g, extreme_i), _time(g, extreme_i))
            _node(nodes, "WAIT_AMBIGUOUS", True, _seq(g, extreme_i), _time(g, extreme_i))
            _node(nodes, "NO_TRADE", True)
            event["difficulty"] = _difficulty(abs(excursion - excursion_need) / max(excursion_need, 1))
            events.append(event)
            i = max(j + 1, start + 1)
            continue

        _node(nodes, "AUC_ATTEMPT", True, _seq(g, qualified_i), _time(g, qualified_i))

        if clear_i is not None:
            event["strategy"] = "MR"
            event["direction"] = mr_direction
            _node(nodes, "MR_REJECTION", True, _seq(g, clear_i), _time(g, clear_i))
            _node(nodes, "MR_CLEAR_RECLAIM", True, _seq(g, clear_i), _time(g, clear_i))
            event.update(
                clear_reclaim_seq=_seq(g, clear_i),
                clear_reclaim_time=_time(g, clear_i).isoformat(),
                clear_reclaim_price=float(g["price"].iloc[clear_i]),
            )
            reclaim_seconds = (_time(g, clear_i) - _time(g, extreme_i)).total_seconds()
            reclaim_points = abs(float(g["price"].iloc[clear_i]) - boundary)
            event["features"].update(
                reclaim_seconds=float(reclaim_seconds),
                reclaim_points=float(reclaim_points),
                reclaim_pct_value=float(reclaim_points / prior["width"]),
            )

            k = clear_i
            best = float(g["price"].iloc[k])
            leg_end = k
            confirm = None
            while k < n and (_time(g, k) - _time(g, clear_i)).total_seconds() <= 600:
                price = float(g["price"].iloc[k])
                if mr_direction == "short":
                    if price < best:
                        best, leg_end = price, k
                    if price >= best + cfg.turn_points:
                        confirm = k
                        break
                else:
                    if price > best:
                        best, leg_end = price, k
                    if price <= best - cfg.turn_points:
                        confirm = k
                        break
                k += 1
            _node(nodes, "MR_RECLAIM_LEG", confirm is not None, _seq(g, confirm), _time(g, confirm))
            if confirm is not None:
                event.update(
                    turn_confirm_seq=_seq(g, confirm),
                    turn_confirm_time=_time(g, confirm).isoformat(),
                )
                leg = g.iloc[min(extreme_i, leg_end) : max(extreme_i, leg_end) + 1]
                lvn, depth = valley_lvn(leg, prior, cfg)
                event["lvn"] = lvn
                event["features"].update(
                    leg_points=float(abs(extreme - best)), lvn_depth=float(depth)
                )
                _node(nodes, "MR_LVN", lvn is not None, _seq(g, confirm), _time(g, confirm))
                if lvn is not None:
                    touch = None
                    k = confirm + 1
                    deadline = _time(g, confirm) + pd.Timedelta(seconds=cfg.pullback_max_sec)
                    while k < n and _time(g, k) <= deadline:
                        if abs(float(g["price"].iloc[k]) - lvn) <= cfg.lvn_tolerance:
                            touch = k
                            break
                        k += 1
                    _node(nodes, "MR_PULLBACK", touch is not None, _seq(g, touch), _time(g, touch))
                    if touch is not None:
                        ep = float(g["price"].iloc[touch])
                        stop = lvn + cfg.mr_stop_points if mr_direction == "short" else lvn - cfg.mr_stop_points
                        risk = abs(stop - ep)
                        target = ep - cfg.mr_target_r * risk if mr_direction == "short" else ep + cfg.mr_target_r * risk
                        event.update(
                            entry_seq=_seq(g, touch),
                            entry_time=_time(g, touch).isoformat(),
                            entry_price=ep,
                            stop=float(stop),
                            target=float(target),
                            result="ENTRY",
                        )
                        _node(nodes, "MR_ENTRY", True, _seq(g, touch), _time(g, touch))
                        _node(nodes, "NO_TRADE", False)
                    else:
                        _node(nodes, "MR_ENTRY", False)
                        _node(nodes, "NO_TRADE", True)
                else:
                    _node(nodes, "NO_TRADE", True)
            else:
                _node(nodes, "NO_TRADE", True)
            threshold_distance = abs(reclaim_points - reclaim_need) / max(reclaim_need, 1)
            event["difficulty"] = _difficulty(threshold_distance)
            events.append(event)
            i = max(clear_i + 1, start + 1)
            continue

        # Qualified auction with no clear reclaim: test causal acceptance.
        _node(nodes, "MR_REJECTION", False, _seq(g, qualified_i), _time(g, qualified_i))
        accept_start = _time(g, qualified_i)
        accept_end = accept_start + pd.Timedelta(seconds=cfg.acceptance_window_sec)
        w = g[(g["dt"] >= accept_start) & (g["dt"] <= accept_end)]
        if len(w):
            outside = (w["price"] > prior["vah"]) if up else (w["price"] < prior["val"])
            outside_ratio = float(outside.mean())
            disp = float(w["price"].max() - boundary) if up else float(boundary - w["price"].min())
            accept_i = int(w.index[-1])
        else:
            outside_ratio, disp, accept_i = 0.0, 0.0, qualified_i
        accept = (
            outside_ratio >= cfg.acceptance_outside_ratio
            and disp >= cfg.acceptance_displacement_pct * prior["width"]
        )
        event["features"].update(
            outside_ratio=float(outside_ratio),
            acceptance_displacement=float(disp),
            acceptance_displacement_pct=float(disp / prior["width"]),
        )
        _node(nodes, "BO_ACCEPTANCE", accept, _seq(g, accept_i), _time(g, accept_i))

        if not accept:
            _node(nodes, "WAIT_AMBIGUOUS", True, _seq(g, accept_i), _time(g, accept_i))
            _node(nodes, "NO_TRADE", True)
            event["difficulty"] = 4
            events.append(event)
            i = max(j + 1, start + 1)
            continue

        event["strategy"] = "BO"
        event["direction"] = bo_direction
        _node(nodes, "BO_DISPLACEMENT", True, _seq(g, accept_i), _time(g, accept_i))
        segment = g.iloc[start : accept_i + 1]
        if bo_direction == "long":
            best = float(segment["price"].max())
            leg_end = int(segment["price"].idxmax())
        else:
            best = float(segment["price"].min())
            leg_end = int(segment["price"].idxmin())
        k = accept_i
        confirm = None
        while k < n and (_time(g, k) - _time(g, accept_i)).total_seconds() <= 600:
            price = float(g["price"].iloc[k])
            if bo_direction == "long":
                if price > best:
                    best, leg_end = price, k
                if price <= best - cfg.turn_points:
                    confirm = k
                    break
            else:
                if price < best:
                    best, leg_end = price, k
                if price >= best + cfg.turn_points:
                    confirm = k
                    break
            k += 1
        _node(nodes, "BO_IMPULSE_LEG", confirm is not None, _seq(g, confirm), _time(g, confirm))
        if confirm is not None:
            event.update(
                turn_confirm_seq=_seq(g, confirm),
                turn_confirm_time=_time(g, confirm).isoformat(),
            )
            leg = g.iloc[start : leg_end + 1]
            lvn, depth = valley_lvn(leg, prior, cfg)
            event["lvn"] = lvn
            event["features"].update(
                leg_points=float(abs(best - boundary)), lvn_depth=float(depth)
            )
            _node(nodes, "BO_LVN", lvn is not None, _seq(g, confirm), _time(g, confirm))
            if lvn is not None:
                touch = None
                k = confirm + 1
                deadline = _time(g, confirm) + pd.Timedelta(seconds=cfg.pullback_max_sec)
                while k < n and _time(g, k) <= deadline:
                    if abs(float(g["price"].iloc[k]) - lvn) <= cfg.lvn_tolerance:
                        touch = k
                        break
                    k += 1
                _node(nodes, "BO_PULLBACK", touch is not None, _seq(g, touch), _time(g, touch))
                response = None
                if touch is not None:
                    touch_price = float(g["price"].iloc[touch])
                    k = touch
                    deadline = _time(g, touch) + pd.Timedelta(seconds=30)
                    while k < n and _time(g, k) <= deadline:
                        price = float(g["price"].iloc[k])
                        progress = price - touch_price if bo_direction == "long" else touch_price - price
                        if progress >= cfg.bo_response_points:
                            response = k
                            break
                        k += 1
                _node(nodes, "BO_RESPONSE", response is not None, _seq(g, response), _time(g, response))
                if response is not None:
                    ep = float(g["price"].iloc[response])
                    stop = lvn - cfg.bo_stop_points if bo_direction == "long" else lvn + cfg.bo_stop_points
                    risk = abs(ep - stop)
                    target = ep + cfg.bo_target_r * risk if bo_direction == "long" else ep - cfg.bo_target_r * risk
                    event.update(
                        entry_seq=_seq(g, response),
                        entry_time=_time(g, response).isoformat(),
                        entry_price=ep,
                        stop=float(stop),
                        target=float(target),
                        result="ENTRY",
                    )
                    _node(nodes, "BO_ENTRY", True, _seq(g, response), _time(g, response))
                    _node(nodes, "NO_TRADE", False)
                else:
                    _node(nodes, "BO_ENTRY", False)
                    _node(nodes, "NO_TRADE", True)
            else:
                _node(nodes, "NO_TRADE", True)
        else:
            _node(nodes, "NO_TRADE", True)
        accept_threshold = cfg.acceptance_displacement_pct * prior["width"]
        event["difficulty"] = _difficulty(abs(disp - accept_threshold) / max(accept_threshold, 1), 0)
        events.append(event)
        i = max(j + 1, start + 1)
    return events


def _iter_active_days(path: Path, active: dict, cfg: ScanConfig):
    pf = pq.ParquetFile(path)
    seq = 0
    current_day = None
    parts = []
    start_sec = _session_seconds(cfg.session_start)
    end_sec = _session_seconds(cfg.session_end)

    def emit(day, frames):
        if day is None or not frames:
            return None
        # concat preserves physical order of the already ordered source chunks.
        return day, pd.concat(frames, ignore_index=True)

    for batch in pf.iter_batches(
        batch_size=300_000,
        columns=["datetime", "product", "expiry", "price", "volume", "side"],
    ):
        d = batch.to_pandas()
        d["_seq"] = np.arange(seq, seq + len(d), dtype=np.int64)
        seq += len(d)
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
    item = emit(current_day, parts)
    if item:
        yield item


def write_events(con, events, created_at):
    cols = [
        "event_id","source_file","year","trading_date","contract","strategy","direction","result","difficulty",
        "attempt_start_seq","attempt_start_time","context_start_seq","context_end_seq",
        "extreme_seq","extreme_time","extreme_price","clear_reclaim_seq","clear_reclaim_time","clear_reclaim_price",
        "turn_confirm_seq","turn_confirm_time","lvn","entry_seq","entry_time","entry_price","stop","target",
        "vah","val","poc","value_width",
    ]
    for original in events:
        e = dict(original)
        nodes = e.pop("nodes", {})
        features = e.pop("features", {})
        vals = [e.get(c) for c in cols] + [
            json.dumps(features, ensure_ascii=False),
            json.dumps({k: v["answer"] for k, v in nodes.items()}, ensure_ascii=False),
            created_at,
        ]
        con.execute(
            f"INSERT OR REPLACE INTO events({','.join(cols)},features_json,nodes_json,created_at) VALUES({','.join(['?']*(len(cols)+3))})",
            vals,
        )
        con.execute("DELETE FROM node_instances WHERE event_id=?", (e["event_id"],))
        for node_id, x in nodes.items():
            con.execute(
                "INSERT OR REPLACE INTO node_instances(event_id,node_id,answer,decision_seq,decision_time,difficulty) VALUES(?,?,?,?,?,?)",
                (
                    e["event_id"], node_id, 1 if x["answer"] else 0,
                    x.get("seq"), x.get("time"), e.get("difficulty", 2),
                ),
            )


def scan_files(root: Path, db: Path, years=None, config=None, progress=None):
    from datetime import datetime, timezone

    cfg = config or ScanConfig()
    files = discover(root)
    if years:
        years = {int(y) for y in years}
        files = [p for p in files if any(str(y) in p.stem for y in years)]
    con = connect(db)
    total_events = 0
    now = lambda: datetime.now(timezone.utc).isoformat()
    for file in files:
        cat = catalog_file(file)
        con.execute(
            "INSERT OR REPLACE INTO datasets VALUES(?,?,?,?,?,?,?,?,?)",
            (
                cat["file"], cat["year"], cat["rows"], cat["start"], cat["end"],
                json.dumps(cat["products"]), json.dumps(cat["expiries"]), cat["qa"], now(),
            ),
        )
        con.commit()
        if progress:
            progress(file.name, "catalog", total_events)
        if cat["qa"] != "PASS":
            if progress:
                progress(file.name, "QA_FAIL", total_events)
            continue
        volume_map = daily_contract_volume(file, cfg)
        active = choose_contracts(volume_map, cfg.contract_mode)
        previous_profile = None
        previous_contract = None
        blackout = 0
        for day, g in _iter_active_days(file, active, cfg):
            contract = active[day]["contract"]
            roll = previous_contract is not None and contract != previous_contract
            if roll:
                blackout = cfg.roll_blackout_days
            profile = profile_levels(g, cfg.value_area)
            ambiguous = cfg.contract_mode == "strict" and active[day].get("ambiguous", False)
            if previous_profile is not None and blackout <= 0 and not ambiguous:
                events = scan_day(g, previous_profile, cfg, file, day, contract)
                write_events(con, events, now())
                total_events += len(events)
            if blackout > 0:
                blackout -= 1
            previous_profile = profile
            previous_contract = contract
            if progress:
                progress(file.name, day, total_events)
        con.commit()
    con.close()
    return total_events


def read_replay_window(root: Path, event: dict, margin=20_000):
    path = root / event["source_file"]
    pf = pq.ParquetFile(path)
    center_lo = int(event.get("context_start_seq") or event["attempt_start_seq"])
    center_hi = int(event.get("context_end_seq") or event["attempt_start_seq"])
    lo = max(0, center_lo - margin)
    hi = center_hi + margin
    offset = 0
    parts = []
    for rg in range(pf.num_row_groups):
        count = pf.metadata.row_group(rg).num_rows
        rg_lo, rg_hi = offset, offset + count - 1
        if rg_hi < lo:
            offset += count
            continue
        if rg_lo > hi:
            break
        d = pf.read_row_group(
            rg, columns=["datetime", "product", "expiry", "price", "volume", "side"]
        ).to_pandas()
        d["_seq"] = np.arange(offset, offset + count, dtype=np.int64)
        d = d.loc[(d["_seq"] >= lo) & (d["_seq"] <= hi)]
        parts.append(d)
        offset += count
    if not parts:
        return []
    d = pd.concat(parts, ignore_index=True)
    d["product"] = d["product"].map(_txt)
    d["expiry"] = d["expiry"].map(_txt)
    d = d.loc[(d["product"] == "MTX") & (d["expiry"] == event["contract"])]
    d["dt"] = _to_dt(d["datetime"])
    rows = []
    for ts, b in d.groupby(d["dt"].dt.floor("1s"), sort=False):
        rows.append(
            {
                "timestamp": int(ts.value // 1_000_000),
                "open": float(b["price"].iloc[0]),
                "high": float(b["price"].max()),
                "low": float(b["price"].min()),
                "close": float(b["price"].iloc[-1]),
                "volume": float(b["volume"].sum()),
                "firstSeq": int(b["_seq"].iloc[0]),
                "lastSeq": int(b["_seq"].iloc[-1]),
            }
        )
    return rows
