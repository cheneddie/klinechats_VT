from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .engine import (
    ScanConfig as BaseScanConfig,
    _seq,
    _time,
)


@dataclass
class ScanConfigV4(BaseScanConfig):
    mr_reentry_max_sec: int = 60
    mr_entry_min_room_r: float = 0.75
    mr_entry_max_risk_points: float = 8.0
    bo_entry_max_extension_vw: float = 1.50
    bo_entry_max_risk_points: float = 12.0
    audit_lvn_min_depth: float = 0.10
    audit_pullback_max_sec: int = 300
    node_schema_version: int = 4


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _at(g: pd.DataFrame, i: int | None):
    if i is None or i < 0 or i >= len(g):
        return None, None, None
    return _seq(g, i), _time(g, i), float(g["price"].iloc[i])


def _node(nodes: dict[str, dict[str, Any]], node_id: str, answer: bool, *, decision_i: int | None = None, anchor_i: int | None = None, g: pd.DataFrame | None = None, anchor_price: float | None = None, reason_code: str = "", metrics: dict[str, Any] | None = None, start_i: int | None = None, end_i: int | None = None):
    row: dict[str, Any] = {"answer": bool(answer), "reason_code": reason_code or ("PASS" if answer else "FAIL"), "metrics": metrics or {}, "schema_version": 4}
    if g is not None:
        dseq, dtime, dprice = _at(g, decision_i)
        aseq, atime, aprice = _at(g, anchor_i if anchor_i is not None else decision_i)
        row.update(seq=dseq, time=_iso(dtime), decision_price=dprice, anchor_seq=aseq, anchor_time=_iso(atime), anchor_price=float(anchor_price) if anchor_price is not None else aprice)
        if start_i is not None:
            sseq, stime, _ = _at(g, start_i); row["start_seq"] = sseq; row["start_time"] = _iso(stime)
        if end_i is not None:
            eseq, etime, _ = _at(g, end_i); row["end_seq"] = eseq; row["end_time"] = _iso(etime)
    nodes[node_id] = row
    return row


def _base(event_id, file, day, contract, direction, prior, start_i, g, branch):
    return {"event_id": event_id, "source_file": file.name, "year": int(day[:4]), "trading_date": day, "contract": contract, "strategy": branch, "direction": direction, "result": "WAIT", "difficulty": 2, "attempt_start_seq": _seq(g, start_i), "attempt_start_time": _time(g, start_i).isoformat(), "context_start_seq": max(0, _seq(g, start_i) - 20_000), "context_end_seq": _seq(g, min(len(g) - 1, start_i + 20_000)), "vah": prior["vah"], "val": prior["val"], "poc": prior["poc"], "value_width": prior["width"], "features": {"node_schema_version": 4}, "nodes": {}}


def _difficulty(distance_to_threshold: float, extra=0):
    if distance_to_threshold < 0.10: base = 5
    elif distance_to_threshold < 0.25: base = 4
    elif distance_to_threshold < 0.50: base = 3
    else: base = 2
    return int(max(1, min(5, base + extra)))


def _best_valley(leg: pd.DataFrame, prior: dict):
    if len(leg) < 5: return None, 0.0
    pv = leg.groupby("price", sort=True)["volume"].sum(); prices = pv.index.to_numpy(float); vol = pv.to_numpy(float)
    if len(prices) < 5: return None, 0.0
    smooth = np.convolve(vol, np.ones(3) / 3, mode="same"); low = prior["val"] + 0.05 * prior["width"]; high = prior["vah"] - 0.05 * prior["width"]
    best = None
    for i in range(2, len(prices) - 2):
        if not low <= prices[i] <= high: continue
        if smooth[i] <= smooth[i - 1] and smooth[i] <= smooth[i + 1]:
            ref = min(max(smooth[i - 2:i]), max(smooth[i + 1:i + 3])); depth = 1 - smooth[i] / ref if ref > 0 else 0.0; cand = (float(depth), float(prices[i]))
            if best is None or cand[0] > best[0]: best = cand
    return (best[1], best[0]) if best else (None, 0.0)


def _first_touch(g, start_i, price, tolerance, max_sec):
    if price is None or start_i is None or start_i >= len(g): return None, None
    deadline = _time(g, start_i) + pd.Timedelta(seconds=max_sec); k = start_i + 1; last = start_i
    while k < len(g) and _time(g, k) <= deadline:
        last = k
        if abs(float(g["price"].iloc[k]) - float(price)) <= tolerance: return k, last
        k += 1
    return None, last


def _turn_confirm(g, start_i, direction, turn_points, max_sec=600):
    if start_i is None: return None, None, None
    best = float(g["price"].iloc[start_i]); leg_end = start_i; k = start_i; deadline = _time(g, start_i) + pd.Timedelta(seconds=max_sec)
    while k < len(g) and _time(g, k) <= deadline:
        p = float(g["price"].iloc[k])
        if direction == "short":
            if p < best: best, leg_end = p, k
            if p >= best + turn_points: return k, leg_end, best
        else:
            if p > best: best, leg_end = p, k
            if p <= best - turn_points: return k, leg_end, best
        k += 1
    return None, leg_end, best


def _response(g, touch_i, direction, points, max_sec=30):
    if touch_i is None: return None, touch_i
    touch = float(g["price"].iloc[touch_i]); deadline = _time(g, touch_i) + pd.Timedelta(seconds=max_sec); k = touch_i; last = touch_i
    while k < len(g) and _time(g, k) <= deadline:
        last = k; p = float(g["price"].iloc[k]); progress = p - touch if direction == "long" else touch - p
        if progress >= points: return k, last
        k += 1
    return None, last


def _build_mr_event(g, prior, cfg: ScanConfigV4, file, day, contract, auction_no, start, qualified_i, extreme_i, extreme, boundary, up, reentry_i, clear_i):
    direction = "short" if up else "long"; e = _base(f"{day}-{contract}-A{auction_no:03d}-MR", file, day, contract, direction, prior, start, g, "MR"); n = e["nodes"]
    excursion = (extreme - boundary) if up else (boundary - extreme); excursion_need = max(cfg.min_excursion_points, cfg.excursion_pct * prior["width"]); reclaim_need = max(3.0, cfg.reclaim_pct * prior["width"])
    e.update(extreme_seq=_seq(g, extreme_i), extreme_time=_iso(_time(g, extreme_i)), extreme_price=float(extreme)); e["features"].update(auction_side="up" if up else "down", excursion_points=float(excursion), excursion_pct_value=float(excursion / prior["width"]), excursion_threshold=float(excursion_need))
    _node(n, "CTX_VALUE", True, decision_i=start, anchor_i=start, g=g, reason_code="PROFILE_READY")
    _node(n, "AUC_ATTEMPT", qualified_i is not None, decision_i=qualified_i if qualified_i is not None else extreme_i, anchor_i=start, g=g, anchor_price=boundary, reason_code="EXCURSION_PASS" if qualified_i is not None else "EXCURSION_TOO_SMALL", metrics={"actual": excursion, "threshold": excursion_need})
    resolve_i = clear_i if clear_i is not None else (reentry_i if reentry_i is not None else extreme_i)
    _node(n, "AUC_EXTREME", True, decision_i=resolve_i, anchor_i=extreme_i, g=g, anchor_price=extreme, reason_code="EXTREME_LOCKED", metrics={"excursion": excursion})
    rejection = reentry_i is not None
    _node(n, "MR_REJECTION", rejection, decision_i=reentry_i if rejection else resolve_i, anchor_i=reentry_i if rejection else extreme_i, g=g, reason_code="REENTERED_VALUE" if rejection else "NO_VALUE_REENTRY", metrics={"boundary": boundary})
    clear = clear_i is not None; clear_decision = clear_i if clear else (reentry_i if reentry_i is not None else resolve_i); actual_depth = None
    if clear_decision is not None:
        p = float(g["price"].iloc[clear_decision]); actual_depth = (boundary - p) if up else (p - boundary)
    _node(n, "MR_CLEAR_RECLAIM", clear, decision_i=clear_decision, anchor_i=clear_decision, g=g, reason_code="CLEAR_RECLAIM_PASS" if clear else "REENTRY_WITHOUT_DEPTH", metrics={"actual_depth": actual_depth, "required_depth": reclaim_need, "max_seconds": cfg.reclaim_max_sec})
    if clear:
        e.update(clear_reclaim_seq=_seq(g, clear_i), clear_reclaim_time=_iso(_time(g, clear_i)), clear_reclaim_price=float(g["price"].iloc[clear_i])); e["features"].update(reclaim_seconds=float((_time(g, clear_i) - _time(g, extreme_i)).total_seconds()), reclaim_points=float(abs(float(g["price"].iloc[clear_i]) - boundary)))
    shadow_start = reentry_i; confirm, leg_end, best = _turn_confirm(g, shadow_start, direction, cfg.turn_points) if shadow_start is not None else (None, None, None); leg_ok = confirm is not None; leg_decision = confirm if confirm is not None else leg_end
    _node(n, "MR_RECLAIM_LEG", leg_ok, decision_i=leg_decision, anchor_i=leg_end, g=g, reason_code="TURN_CONFIRMED" if leg_ok else "NO_TURN_CONFIRM", metrics={"turn_points": cfg.turn_points}, start_i=shadow_start, end_i=leg_end)
    lvn = None; depth = 0.0
    if leg_end is not None and shadow_start is not None:
        lo = min(extreme_i, leg_end); hi = max(extreme_i, leg_end); lvn, depth = _best_valley(g.iloc[lo:hi + 1], prior)
    lvn_pass = lvn is not None and depth >= cfg.lvn_depth
    if lvn is not None: e["lvn"] = float(lvn)
    e["features"].update(leg_points=float(abs(extreme - best)) if best is not None else None, lvn_depth=float(depth), shadow_terminal_universe=True)
    _node(n, "MR_LVN", lvn_pass, decision_i=confirm if confirm is not None else leg_decision, anchor_i=confirm if confirm is not None else leg_decision, g=g, anchor_price=lvn, reason_code="LVN_DEPTH_PASS" if lvn_pass else ("LVN_TOO_SHALLOW" if lvn is not None else "NO_VALLEY"), metrics={"depth": depth, "threshold": cfg.lvn_depth, "candidate_price": lvn})
    touch, touch_deadline_i = _first_touch(g, confirm if confirm is not None else leg_decision, lvn, cfg.lvn_tolerance, cfg.audit_pullback_max_sec) if lvn is not None and leg_decision is not None else (None, leg_decision)
    strict_delay_ok = False; delay = None
    if touch is not None and confirm is not None:
        delay = (_time(g, touch) - _time(g, confirm)).total_seconds(); strict_delay_ok = delay <= cfg.pullback_max_sec
    pullback_pass = touch is not None and strict_delay_ok
    _node(n, "MR_PULLBACK", pullback_pass, decision_i=touch if touch is not None else touch_deadline_i, anchor_i=touch if touch is not None else touch_deadline_i, g=g, anchor_price=float(g["price"].iloc[touch]) if touch is not None else lvn, reason_code="FIRST_PULLBACK_PASS" if pullback_pass else ("LATE_PULLBACK" if touch is not None else "PULLBACK_TIMEOUT"), metrics={"delay_seconds": delay, "strict_max_seconds": cfg.pullback_max_sec, "audit_max_seconds": cfg.audit_pullback_max_sec})
    terminal_signal = touch is not None; e["features"]["terminal_signal"] = bool(terminal_signal); e["features"]["terminal_signal_kind"] = "MR_PULLBACK"
    if terminal_signal:
        ep = float(g["price"].iloc[touch]); stop = float(lvn + cfg.mr_stop_points if direction == "short" else lvn - cfg.mr_stop_points); risk = abs(ep - stop); room = (ep - prior["poc"]) if direction == "short" else (prior["poc"] - ep); room = max(0.0, float(room)); required_room = cfg.mr_entry_min_room_r * risk; quality = pullback_pass and risk <= cfg.mr_entry_max_risk_points and room >= required_room; target = ep - cfg.mr_target_r * risk if direction == "short" else ep + cfg.mr_target_r * risk
        e.update(entry_seq=_seq(g, touch), entry_time=_iso(_time(g, touch)), entry_price=ep, stop=stop, target=float(target), result="ENTRY" if quality else "OPPORTUNITY"); e["features"].update(terminal_entry_price=ep, terminal_entry_seq=_seq(g, touch), entry_risk_points=risk, entry_room_to_poc=room, entry_required_room=required_room)
        _node(n, "MR_ENTRY", quality, decision_i=touch, anchor_i=touch, g=g, reason_code="ENTRY_QUALITY_PASS" if quality else "ENTRY_ROOM_OR_RISK_FAIL", metrics={"risk_points": risk, "room_to_poc": room, "required_room": required_room}); _node(n, "NO_TRADE", not quality, decision_i=touch, anchor_i=touch, g=g, reason_code="EXECUTE_MR" if quality else "ENTRY_GATE_REJECTED")
    else:
        fail_i = touch_deadline_i if touch_deadline_i is not None else leg_decision; _node(n, "MR_ENTRY", False, decision_i=fail_i, anchor_i=fail_i, g=g, reason_code="NO_TERMINAL_PULLBACK"); _node(n, "NO_TRADE", True, decision_i=fail_i, anchor_i=fail_i, g=g, reason_code="NO_TERMINAL_PULLBACK")
    _node(n, "WAIT_AMBIGUOUS", False, decision_i=resolve_i, anchor_i=resolve_i, g=g, reason_code="MR_BRANCH_OBSERVED"); e["difficulty"] = _difficulty(abs((actual_depth or 0) - reclaim_need) / max(reclaim_need, 1)); return e


def _build_bo_event(g, prior, cfg: ScanConfigV4, file, day, contract, auction_no, start, qualified_i, extreme_i, extreme, boundary, up, reentry_i, displacement_i):
    direction = "long" if up else "short"; e = _base(f"{day}-{contract}-A{auction_no:03d}-BO", file, day, contract, direction, prior, start, g, "BO"); n = e["nodes"]; excursion = (extreme - boundary) if up else (boundary - extreme); excursion_need = max(cfg.min_excursion_points, cfg.excursion_pct * prior["width"]); displacement_need = cfg.acceptance_displacement_pct * prior["width"]
    e.update(extreme_seq=_seq(g, extreme_i), extreme_time=_iso(_time(g, extreme_i)), extreme_price=float(extreme)); e["features"].update(auction_side="up" if up else "down", excursion_points=float(excursion), excursion_pct_value=float(excursion / prior["width"]), excursion_threshold=float(excursion_need))
    _node(n, "CTX_VALUE", True, decision_i=start, anchor_i=start, g=g, reason_code="PROFILE_READY"); _node(n, "AUC_ATTEMPT", qualified_i is not None, decision_i=qualified_i if qualified_i is not None else extreme_i, anchor_i=start, g=g, anchor_price=boundary, reason_code="EXCURSION_PASS" if qualified_i is not None else "EXCURSION_TOO_SMALL", metrics={"actual": excursion, "threshold": excursion_need})
    resolve_anchor = displacement_i if displacement_i is not None else extreme_i; _node(n, "AUC_EXTREME", True, decision_i=resolve_anchor, anchor_i=extreme_i, g=g, anchor_price=extreme, reason_code="EXTREME_OBSERVED"); _node(n, "MR_REJECTION", reentry_i is not None, decision_i=reentry_i if reentry_i is not None else resolve_anchor, anchor_i=reentry_i if reentry_i is not None else extreme_i, g=g, reason_code="REENTERED_VALUE" if reentry_i is not None else "NO_VALUE_REENTRY")
    displacement = displacement_i is not None; _node(n, "BO_DISPLACEMENT", displacement, decision_i=displacement_i if displacement else extreme_i, anchor_i=displacement_i if displacement else extreme_i, g=g, reason_code="DISPLACEMENT_PASS" if displacement else "DISPLACEMENT_TOO_SMALL", metrics={"required_points": displacement_need, "actual_points": excursion})
    outside_ratio = 0.0; accept_i = displacement_i; acceptance = False
    if displacement_i is not None:
        accept_start = _time(g, displacement_i); accept_end = accept_start + pd.Timedelta(seconds=cfg.acceptance_window_sec); idxs = []; k = displacement_i
        while k < len(g) and _time(g, k) <= accept_end: idxs.append(k); k += 1
        if idxs:
            prices = g["price"].iloc[idxs].to_numpy(float); outside = prices > prior["vah"] if up else prices < prior["val"]; outside_ratio = float(np.mean(outside)); accept_i = idxs[-1]; acceptance = outside_ratio >= cfg.acceptance_outside_ratio and reentry_i is None
    _node(n, "BO_ACCEPTANCE", acceptance, decision_i=accept_i if accept_i is not None else extreme_i, anchor_i=accept_i if accept_i is not None else extreme_i, g=g, reason_code="ACCEPTANCE_PASS" if acceptance else ("REENTRY_INVALIDATES_ACCEPTANCE" if reentry_i is not None else "OUTSIDE_RATIO_FAIL"), metrics={"outside_ratio": outside_ratio, "threshold": cfg.acceptance_outside_ratio, "window_seconds": cfg.acceptance_window_sec}, start_i=displacement_i, end_i=accept_i); e["features"].update(outside_ratio=outside_ratio, acceptance_displacement=float(excursion), acceptance_displacement_pct=float(excursion / prior["width"]))
    confirm, leg_end, best = _turn_confirm(g, displacement_i, direction, cfg.turn_points) if displacement_i is not None else (None, None, None); leg_ok = confirm is not None; _node(n, "BO_IMPULSE_LEG", leg_ok, decision_i=confirm if confirm is not None else leg_end, anchor_i=leg_end, g=g, reason_code="TURN_CONFIRMED" if leg_ok else "NO_TURN_CONFIRM", metrics={"turn_points": cfg.turn_points}, start_i=displacement_i, end_i=leg_end)
    lvn = None; depth = 0.0
    if displacement_i is not None and leg_end is not None:
        lo, hi = min(displacement_i, leg_end), max(displacement_i, leg_end); lvn, depth = _best_valley(g.iloc[lo:hi + 1], prior)
    lvn_pass = lvn is not None and depth >= cfg.lvn_depth
    if lvn is not None: e["lvn"] = float(lvn)
    e["features"].update(leg_points=float(abs(best - boundary)) if best is not None else None, lvn_depth=float(depth), shadow_terminal_universe=True); _node(n, "BO_LVN", lvn_pass, decision_i=confirm if confirm is not None else leg_end, anchor_i=confirm if confirm is not None else leg_end, g=g, anchor_price=lvn, reason_code="LVN_DEPTH_PASS" if lvn_pass else ("LVN_TOO_SHALLOW" if lvn is not None else "NO_VALLEY"), metrics={"depth": depth, "threshold": cfg.lvn_depth, "candidate_price": lvn})
    touch, touch_deadline_i = _first_touch(g, confirm if confirm is not None else leg_end, lvn, cfg.lvn_tolerance, cfg.audit_pullback_max_sec) if lvn is not None and leg_end is not None else (None, leg_end); delay = None; strict_pullback = False
    if touch is not None and confirm is not None: delay = (_time(g, touch) - _time(g, confirm)).total_seconds(); strict_pullback = delay <= cfg.pullback_max_sec
    _node(n, "BO_PULLBACK", strict_pullback, decision_i=touch if touch is not None else touch_deadline_i, anchor_i=touch if touch is not None else touch_deadline_i, g=g, anchor_price=float(g["price"].iloc[touch]) if touch is not None else lvn, reason_code="FIRST_PULLBACK_PASS" if strict_pullback else ("LATE_PULLBACK" if touch is not None else "PULLBACK_TIMEOUT"), metrics={"delay_seconds": delay, "strict_max_seconds": cfg.pullback_max_sec, "audit_max_seconds": cfg.audit_pullback_max_sec})
    response, response_deadline_i = _response(g, touch, direction, cfg.bo_response_points, max_sec=30); response_pass = response is not None; _node(n, "BO_RESPONSE", response_pass, decision_i=response if response is not None else response_deadline_i, anchor_i=response if response is not None else response_deadline_i, g=g, reason_code="RESPONSE_PASS" if response_pass else "NO_DIRECTIONAL_RESPONSE", metrics={"required_points": cfg.bo_response_points, "max_seconds": 30})
    terminal_signal = response is not None; e["features"]["terminal_signal"] = bool(terminal_signal); e["features"]["terminal_signal_kind"] = "BO_RESPONSE"
    if terminal_signal:
        ep = float(g["price"].iloc[response]); stop = float(lvn - cfg.bo_stop_points if direction == "long" else lvn + cfg.bo_stop_points); risk = abs(ep - stop); extension = abs(ep - boundary) / max(prior["width"], 1e-9); outside_now = ep > prior["vah"] if direction == "long" else ep < prior["val"]; quality = strict_pullback and response_pass and risk <= cfg.bo_entry_max_risk_points and extension <= cfg.bo_entry_max_extension_vw and outside_now; target = ep + cfg.bo_target_r * risk if direction == "long" else ep - cfg.bo_target_r * risk
        e.update(entry_seq=_seq(g, response), entry_time=_iso(_time(g, response)), entry_price=ep, stop=stop, target=float(target), result="ENTRY" if quality else "OPPORTUNITY"); e["features"].update(terminal_entry_price=ep, terminal_entry_seq=_seq(g, response), entry_risk_points=risk, entry_extension_vw=extension); _node(n, "BO_ENTRY", quality, decision_i=response, anchor_i=response, g=g, reason_code="ENTRY_QUALITY_PASS" if quality else "ENTRY_EXTENSION_OR_RISK_FAIL", metrics={"risk_points": risk, "extension_vw": extension, "max_extension_vw": cfg.bo_entry_max_extension_vw}); _node(n, "NO_TRADE", not quality, decision_i=response, anchor_i=response, g=g, reason_code="EXECUTE_BO" if quality else "ENTRY_GATE_REJECTED")
    else:
        fail_i = response_deadline_i if response_deadline_i is not None else touch_deadline_i; _node(n, "BO_ENTRY", False, decision_i=fail_i, anchor_i=fail_i, g=g, reason_code="NO_TERMINAL_RESPONSE"); _node(n, "NO_TRADE", True, decision_i=fail_i, anchor_i=fail_i, g=g, reason_code="NO_TERMINAL_RESPONSE")
    _node(n, "WAIT_AMBIGUOUS", not acceptance and reentry_i is None, decision_i=accept_i if accept_i is not None else extreme_i, anchor_i=accept_i if accept_i is not None else extreme_i, g=g, reason_code="NO_ACCEPTANCE_OR_REJECTION" if not acceptance and reentry_i is None else "BRANCH_RESOLVED"); e["difficulty"] = _difficulty(abs(excursion - displacement_need) / max(displacement_need, 1)); return e


def scan_day_v4(g: pd.DataFrame, prior: dict, cfg: ScanConfigV4, file: Path, day: str, contract: str):
    events = []; n = len(g)
    if n < 10 or not prior or prior["width"] <= 0: return events
    excursion_need = max(cfg.min_excursion_points, cfg.excursion_pct * prior["width"]); displacement_need = cfg.acceptance_displacement_pct * prior["width"]; i = 0; attempt = 0
    while i < n:
        p0 = float(g["price"].iloc[i]); up = p0 > prior["vah"]; down = p0 < prior["val"]
        if not (up or down): i += 1; continue
        attempt += 1; boundary = prior["vah"] if up else prior["val"]; start = i; extreme = p0; extreme_i = i; qualified_i = None; displacement_i = None; reentry_i = None; clear_i = None; t_start = _time(g, start); j = i
        while j < n and (_time(g, j) - t_start).total_seconds() <= cfg.auction_max_sec:
            price = float(g["price"].iloc[j])
            if up and price > extreme: extreme, extreme_i = price, j
            if down and price < extreme: extreme, extreme_i = price, j
            excursion = (extreme - boundary) if up else (boundary - extreme)
            if qualified_i is None and excursion >= excursion_need: qualified_i = j
            if displacement_i is None and excursion >= displacement_need: displacement_i = j
            if qualified_i is not None and reentry_i is None and ((up and price <= boundary) or (down and price >= boundary)): reentry_i = j
            if reentry_i is not None and clear_i is None:
                since_extreme = (_time(g, j) - _time(g, extreme_i)).total_seconds(); need = max(3.0, cfg.reclaim_pct * prior["width"])
                if since_extreme <= cfg.reclaim_max_sec and ((up and price <= boundary - need) or (down and price >= boundary + need)): clear_i = j
            j += 1
        if reentry_i is not None: events.append(_build_mr_event(g, prior, cfg, file, day, contract, attempt, start, qualified_i, extreme_i, extreme, boundary, up, reentry_i, clear_i))
        if displacement_i is not None: events.append(_build_bo_event(g, prior, cfg, file, day, contract, attempt, start, qualified_i, extreme_i, extreme, boundary, up, reentry_i, displacement_i))
        if reentry_i is None and displacement_i is None:
            direction = "short" if up else "long"; e = _base(f"{day}-{contract}-A{attempt:03d}-WAIT", file, day, contract, direction, prior, start, g, "WAIT"); nmap = e["nodes"]; excursion = (extreme - boundary) if up else (boundary - extreme)
            _node(nmap, "CTX_VALUE", True, decision_i=start, anchor_i=start, g=g, reason_code="PROFILE_READY"); _node(nmap, "AUC_ATTEMPT", qualified_i is not None, decision_i=qualified_i if qualified_i is not None else extreme_i, anchor_i=start, g=g, anchor_price=boundary, reason_code="EXCURSION_PASS" if qualified_i is not None else "EXCURSION_TOO_SMALL", metrics={"actual": excursion, "threshold": excursion_need}); _node(nmap, "AUC_EXTREME", True, decision_i=extreme_i, anchor_i=extreme_i, g=g, anchor_price=extreme, reason_code="EXTREME_TIMEOUT"); _node(nmap, "WAIT_AMBIGUOUS", True, decision_i=min(j - 1, n - 1), anchor_i=extreme_i, g=g, reason_code="NO_BRANCH_RESOLUTION"); _node(nmap, "NO_TRADE", True, decision_i=min(j - 1, n - 1), anchor_i=min(j - 1, n - 1), g=g, reason_code="NO_BRANCH_RESOLUTION"); e["features"].update(terminal_signal=False, shadow_terminal_universe=True); e["difficulty"] = _difficulty(abs(excursion - excursion_need) / max(excursion_need, 1)); events.append(e)
        i = max(j, start + 1)
    return events


V4_NODE_COLUMNS = {"decision_price":"REAL","anchor_seq":"INTEGER","anchor_time":"TEXT","anchor_price":"REAL","start_seq":"INTEGER","start_time":"TEXT","end_seq":"INTEGER","end_time":"TEXT","reason_code":"TEXT","metrics_json":"TEXT","node_schema_version":"INTEGER"}

def migrate_v4_schema(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(node_instances)").fetchall()}
    for name, typ in V4_NODE_COLUMNS.items():
        if name not in cols: con.execute(f"ALTER TABLE node_instances ADD COLUMN {name} {typ}")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS opportunity_outcomes(event_id TEXT PRIMARY KEY,strategy TEXT,direction TEXT,entry_seq INTEGER,entry_time TEXT,entry_price REAL,risk_points REAL,mfe_points REAL,mae_points REAL,mfe_r REAL,mae_r REAL,hit_1r INTEGER,hit_2r INTEGER,hit_3r INTEGER,hit_stop INTEGER,first_hit_1r TEXT,first_hit_2r TEXT,first_hit_3r TEXT,bars_end_time TEXT,management_json TEXT,computed_at TEXT);
    CREATE TABLE IF NOT EXISTS node_edge_audit(audit_id TEXT,node_id TEXT,strategy TEXT,universe INTEGER,pass_count INTEGER,fail_count INTEGER,big_winners INTEGER,big_winners_kept INTEGER,big_winners_rejected INTEGER,big_losers INTEGER,big_losers_rejected INTEGER,big_losers_kept INTEGER,pass_avg_mfe_r REAL,fail_avg_mfe_r REAL,pass_avg_mae_r REAL,fail_avg_mae_r REAL,pass_2r_rate REAL,fail_2r_rate REAL,same_seq_parent_rate REAL,filter_score REAL,details_json TEXT,created_at TEXT,PRIMARY KEY(audit_id,node_id,strategy));
    """); con.commit()


def write_events_v4(con, events, created_at):
    migrate_v4_schema(con); cols = ["event_id","source_file","year","trading_date","contract","strategy","direction","result","difficulty","attempt_start_seq","attempt_start_time","context_start_seq","context_end_seq","extreme_seq","extreme_time","extreme_price","clear_reclaim_seq","clear_reclaim_time","clear_reclaim_price","turn_confirm_seq","turn_confirm_time","lvn","entry_seq","entry_time","entry_price","stop","target","vah","val","poc","value_width"]
    for original in events:
        e = dict(original); nodes = e.pop("nodes", {}); features = e.pop("features", {}); vals = [e.get(c) for c in cols] + [json.dumps(features, ensure_ascii=False), json.dumps({k: bool(v.get("answer")) for k, v in nodes.items()}, ensure_ascii=False), created_at]
        con.execute(f"INSERT OR REPLACE INTO events({','.join(cols)},features_json,nodes_json,created_at) VALUES({','.join(['?']*(len(cols)+3))})", vals); con.execute("DELETE FROM node_instances WHERE event_id=?", (e["event_id"],))
        for node_id, x in nodes.items():
            con.execute("""INSERT OR REPLACE INTO node_instances(event_id,node_id,answer,decision_seq,decision_time,difficulty,decision_price,anchor_seq,anchor_time,anchor_price,start_seq,start_time,end_seq,end_time,reason_code,metrics_json,node_schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (e["event_id"], node_id, 1 if x.get("answer") else 0, x.get("seq"), x.get("time"), e.get("difficulty", 2), x.get("decision_price"), x.get("anchor_seq"), x.get("anchor_time"), x.get("anchor_price"), x.get("start_seq"), x.get("start_time"), x.get("end_seq"), x.get("end_time"), x.get("reason_code"), json.dumps(x.get("metrics") or {}, ensure_ascii=False), int(x.get("schema_version") or 4)))
