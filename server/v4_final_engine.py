from __future__ import annotations

"""Fabio Decision Gym V4 final causal scanner.

The strict binary nodes are evaluated independently inside a *relaxed terminal
opportunity universe*.  The relaxed universe exists only to answer the reverse
question: what did each strict gate keep or reject?  A terminal opportunity does
NOT mean the full strategy qualified.

Important invariants:
- physical source row order is never sorted or re-ordered;
- node anchor != node decision time when the structure becomes knowable later;
- MR and BO candidates are both evaluated after every qualified auction;
- BO response is never required to create the terminal-opportunity universe;
- display / audit candidates are not labelled as real strategy entries unless the
  complete strict gate chain passes.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .v4_engine import (
    ScanConfigV4 as _BaseV4,
    _base,
    _best_valley,
    _difficulty,
    _first_touch,
    _iso,
    _node,
    _response,
    _turn_confirm,
    migrate_v4_schema,
    write_events_v4,
)
from .engine import _seq, _time


@dataclass
class ScanConfigV4Final(_BaseV4):
    audit_reentry_max_sec: int = 300
    audit_leg_max_sec: int = 600
    audit_lvn_min_depth: float = 0.10
    audit_pullback_max_sec: int = 300
    audit_universe_version: str = "V4.1_RELAXED_TERMINAL"
    strategy_version_mr: str = "MR_BROAD_V3"
    strategy_version_bo: str = "BO_RETEST_V2"
    scanner_version: str = "V4.1"


def _deadline_i(g: pd.DataFrame, start_i: int | None, seconds: int) -> int | None:
    if start_i is None or not len(g):
        return None
    deadline = _time(g, start_i) + pd.Timedelta(seconds=max(0, int(seconds)))
    k = int(start_i)
    last = k
    while k < len(g) and _time(g, k) <= deadline:
        last = k
        k += 1
    return last


def _first_reentry(g: pd.DataFrame, start_i: int | None, boundary: float, up: bool, max_sec: int):
    if start_i is None:
        return None
    deadline = _time(g, start_i) + pd.Timedelta(seconds=max_sec)
    k = start_i + 1
    while k < len(g) and _time(g, k) <= deadline:
        p = float(g["price"].iloc[k])
        if (up and p <= boundary) or ((not up) and p >= boundary):
            return k
        k += 1
    return None


def _first_clear(g: pd.DataFrame, extreme_i: int, reentry_i: int | None, boundary: float, up: bool, need: float, max_sec: int):
    if reentry_i is None:
        return None
    deadline = _time(g, extreme_i) + pd.Timedelta(seconds=max_sec)
    k = reentry_i
    while k < len(g) and _time(g, k) <= deadline:
        p = float(g["price"].iloc[k])
        if (up and p <= boundary - need) or ((not up) and p >= boundary + need):
            return k
        k += 1
    return None


def _best_valley_leg(leg: pd.DataFrame):
    """Strongest valley in the middle 80% of an impulse leg's own price range.

    BO LVN is a feature of the impulse leg, not of the old Value Area.  This is
    intentionally different from MR where the preferred LVN lives back inside
    previous Value.
    """
    if len(leg) < 5:
        return None, 0.0
    pv = leg.groupby("price", sort=True)["volume"].sum()
    prices = pv.index.to_numpy(float)
    vol = pv.to_numpy(float)
    if len(prices) < 5 or float(vol.sum()) <= 0:
        return None, 0.0
    smooth = np.convolve(vol, np.ones(3) / 3, mode="same")
    lo_p, hi_p = float(prices.min()), float(prices.max())
    width = max(1e-9, hi_p - lo_p)
    low, high = lo_p + 0.10 * width, hi_p - 0.10 * width
    best = None
    for i in range(2, len(prices) - 2):
        if not low <= prices[i] <= high:
            continue
        if smooth[i] <= smooth[i - 1] and smooth[i] <= smooth[i + 1]:
            ref = min(max(smooth[i - 2:i]), max(smooth[i + 1:i + 3]))
            depth = 1 - smooth[i] / ref if ref > 0 else 0.0
            cand = (float(depth), float(prices[i]))
            if best is None or cand[0] > best[0]:
                best = cand
    return (best[1], best[0]) if best else (None, 0.0)


def _audit_entry_features(e, *, seq, time, price, stop, risk, kind, cfg):
    e["features"].update(
        terminal_signal=True,
        terminal_signal_kind=kind,
        terminal_entry_seq=int(seq),
        terminal_entry_time=_iso(time),
        terminal_entry_price=float(price),
        terminal_stop=float(stop),
        terminal_risk_points=float(risk),
        audit_universe_version=cfg.audit_universe_version,
    )


def _finish_event(e, chain, cfg, strict_entry):
    nodes = e["nodes"]
    full = all(bool(nodes.get(x, {}).get("answer")) for x in chain)
    e["features"]["strict_chain_pass"] = bool(full)
    e["features"]["scanner_version"] = cfg.scanner_version
    e["features"]["strategy_version"] = cfg.strategy_version_mr if e["strategy"] == "MR" else cfg.strategy_version_bo
    if full and strict_entry:
        e.update(
            entry_seq=int(strict_entry["seq"]),
            entry_time=_iso(strict_entry["time"]),
            entry_price=float(strict_entry["price"]),
            stop=float(strict_entry["stop"]),
            target=float(strict_entry["target"]),
            result="ENTRY",
        )
    elif e["features"].get("terminal_signal"):
        e["result"] = "OPPORTUNITY"
    else:
        e["result"] = "WAIT"
    return full


def _build_mr(
    g, prior, cfg: ScanConfigV4Final, file, day, contract, auction_no,
    start, qualified_i, extreme_i, extreme, boundary, up, strict_reentry_i,
    audit_reentry_i, clear_i, auction_resolve_i,
):
    direction = "short" if up else "long"
    e = _base(f"{day}-{contract}-A{auction_no:03d}-MR", file, day, contract, direction, prior, start, g, "MR")
    n = e["nodes"]
    excursion = (extreme - boundary) if up else (boundary - extreme)
    excursion_need = max(cfg.min_excursion_points, cfg.excursion_pct * prior["width"])
    reclaim_need = max(3.0, cfg.reclaim_pct * prior["width"])
    e.update(extreme_seq=_seq(g, extreme_i), extreme_time=_iso(_time(g, extreme_i)), extreme_price=float(extreme))
    e["features"].update(
        auction_side="up" if up else "down",
        excursion_points=float(excursion),
        excursion_pct_value=float(excursion / prior["width"]),
        excursion_threshold=float(excursion_need),
        audit_universe_version=cfg.audit_universe_version,
    )
    _node(n, "CTX_VALUE", True, decision_i=start, anchor_i=start, g=g, reason_code="PROFILE_READY")
    _node(n, "AUC_ATTEMPT", True, decision_i=qualified_i, anchor_i=start, g=g, anchor_price=boundary,
          reason_code="EXCURSION_PASS", metrics={"actual": excursion, "threshold": excursion_need})
    _node(n, "AUC_EXTREME", True, decision_i=auction_resolve_i, anchor_i=extreme_i, g=g,
          anchor_price=extreme, reason_code="EXTREME_LOCKED", metrics={"excursion": excursion})

    rejection_deadline = _deadline_i(g, extreme_i, cfg.mr_reentry_max_sec)
    rejection = strict_reentry_i is not None
    _node(n, "MR_REJECTION", rejection,
          decision_i=strict_reentry_i if rejection else rejection_deadline,
          anchor_i=audit_reentry_i if audit_reentry_i is not None else extreme_i, g=g,
          anchor_price=boundary,
          reason_code="REENTERED_VALUE_IN_TIME" if rejection else ("LATE_VALUE_REENTRY" if audit_reentry_i is not None else "NO_VALUE_REENTRY"),
          metrics={"max_seconds": cfg.mr_reentry_max_sec,
                   "audit_reentry_seconds": ((_time(g, audit_reentry_i)-_time(g, extreme_i)).total_seconds() if audit_reentry_i is not None else None)})

    clear_deadline = _deadline_i(g, extreme_i, cfg.reclaim_max_sec)
    clear = clear_i is not None
    depth_at_decision = None
    if clear:
        p = float(g["price"].iloc[clear_i])
        depth_at_decision = boundary - p if up else p - boundary
        e.update(clear_reclaim_seq=_seq(g, clear_i), clear_reclaim_time=_iso(_time(g, clear_i)), clear_reclaim_price=p)
    _node(n, "MR_CLEAR_RECLAIM", clear,
          decision_i=clear_i if clear else clear_deadline,
          anchor_i=clear_i if clear else (audit_reentry_i if audit_reentry_i is not None else extreme_i), g=g,
          reason_code="CLEAR_RECLAIM_PASS" if clear else "CLEAR_RECLAIM_DEPTH_OR_TIME_FAIL",
          metrics={"actual_depth": depth_at_decision, "required_depth": reclaim_need, "max_seconds": cfg.reclaim_max_sec})

    # Strict leg uses the strict re-entry.  Audit leg may use a later relaxed re-entry.
    strict_confirm, strict_leg_end, strict_best = _turn_confirm(g, strict_reentry_i, direction, cfg.turn_points, cfg.audit_leg_max_sec) if strict_reentry_i is not None else (None, None, None)
    audit_confirm, audit_leg_end, audit_best = _turn_confirm(g, audit_reentry_i, direction, cfg.turn_points, cfg.audit_leg_max_sec) if audit_reentry_i is not None else (None, None, None)
    leg_fail_i = _deadline_i(g, strict_reentry_i if strict_reentry_i is not None else rejection_deadline, cfg.audit_leg_max_sec)
    leg_ok = strict_confirm is not None
    _node(n, "MR_RECLAIM_LEG", leg_ok,
          decision_i=strict_confirm if leg_ok else leg_fail_i,
          anchor_i=strict_leg_end if strict_leg_end is not None else audit_leg_end, g=g,
          reason_code="TURN_CONFIRMED" if leg_ok else "NO_STRICT_TURN_CONFIRM",
          metrics={"turn_points": cfg.turn_points},
          start_i=strict_reentry_i, end_i=strict_leg_end)

    strict_lvn, strict_depth = None, 0.0
    if strict_reentry_i is not None and strict_leg_end is not None:
        lo, hi = min(extreme_i, strict_leg_end), max(extreme_i, strict_leg_end)
        strict_lvn, strict_depth = _best_valley(g.iloc[lo:hi+1], prior)
    audit_lvn, audit_depth = None, 0.0
    if audit_reentry_i is not None and audit_leg_end is not None:
        lo, hi = min(extreme_i, audit_leg_end), max(extreme_i, audit_leg_end)
        audit_lvn, audit_depth = _best_valley(g.iloc[lo:hi+1], prior)
    lvn_pass = strict_lvn is not None and strict_depth >= cfg.lvn_depth and leg_ok
    visible_lvn = strict_lvn if strict_lvn is not None else audit_lvn
    if visible_lvn is not None:
        e["lvn"] = float(visible_lvn)
    _node(n, "MR_LVN", lvn_pass,
          decision_i=strict_confirm if strict_confirm is not None else leg_fail_i,
          anchor_i=strict_confirm if strict_confirm is not None else audit_confirm, g=g,
          anchor_price=visible_lvn,
          reason_code="LVN_DEPTH_PASS" if lvn_pass else ("LVN_TOO_SHALLOW" if visible_lvn is not None else "NO_VALLEY"),
          metrics={"strict_depth": strict_depth, "audit_depth": audit_depth, "threshold": cfg.lvn_depth,
                   "audit_min_depth": cfg.audit_lvn_min_depth, "candidate_price": visible_lvn})

    strict_touch, strict_touch_deadline = (None, strict_confirm)
    if strict_lvn is not None and strict_confirm is not None:
        strict_touch, strict_touch_deadline = _first_touch(g, strict_confirm, strict_lvn, cfg.lvn_tolerance, cfg.pullback_max_sec)
    pullback_pass = bool(lvn_pass and strict_touch is not None)
    _node(n, "MR_PULLBACK", pullback_pass,
          decision_i=strict_touch if strict_touch is not None else strict_touch_deadline,
          anchor_i=strict_touch if strict_touch is not None else strict_touch_deadline, g=g,
          anchor_price=strict_lvn,
          reason_code="FIRST_PULLBACK_PASS" if pullback_pass else "STRICT_PULLBACK_FAIL",
          metrics={"strict_max_seconds": cfg.pullback_max_sec, "audit_max_seconds": cfg.audit_pullback_max_sec})

    # Relaxed terminal opportunity: late re-entry / shallow LVN / late pullback are
    # allowed into the mother universe so the strict gates can be audited.
    audit_touch, _ = (None, audit_confirm)
    if audit_lvn is not None and audit_depth >= cfg.audit_lvn_min_depth and audit_confirm is not None:
        audit_touch, _ = _first_touch(g, audit_confirm, audit_lvn, cfg.lvn_tolerance, cfg.audit_pullback_max_sec)

    strict_entry = None
    entry_quality = False
    if audit_touch is not None:
        ep = float(g["price"].iloc[audit_touch])
        stop = float(audit_lvn + cfg.mr_stop_points if direction == "short" else audit_lvn - cfg.mr_stop_points)
        risk = abs(ep - stop)
        room = max(0.0, float((ep - prior["poc"]) if direction == "short" else (prior["poc"] - ep)))
        required_room = cfg.mr_entry_min_room_r * risk
        entry_quality = risk <= cfg.mr_entry_max_risk_points and room >= required_room
        _audit_entry_features(e, seq=_seq(g, audit_touch), time=_time(g, audit_touch), price=ep,
                              stop=stop, risk=risk, kind="MR_RELAXED_PULLBACK", cfg=cfg)
        e["features"].update(audit_lvn=float(audit_lvn), audit_lvn_depth=float(audit_depth),
                             entry_room_to_poc=room, entry_required_room=required_room)
        _node(n, "MR_ENTRY", entry_quality, decision_i=audit_touch, anchor_i=audit_touch, g=g,
              reason_code="ENTRY_QUALITY_PASS" if entry_quality else "ENTRY_ROOM_OR_RISK_FAIL",
              metrics={"risk_points": risk, "room_to_poc": room, "required_room": required_room})
        target = ep - cfg.mr_target_r*risk if direction == "short" else ep + cfg.mr_target_r*risk
        strict_entry = {"seq": _seq(g,audit_touch), "time": _time(g,audit_touch), "price": ep, "stop": stop, "target": target}
    else:
        fail_i = _deadline_i(g, audit_confirm if audit_confirm is not None else audit_reentry_i, cfg.audit_pullback_max_sec)
        _node(n, "MR_ENTRY", False, decision_i=fail_i, anchor_i=fail_i, g=g, reason_code="NO_RELAXED_TERMINAL_PULLBACK")
        e["features"].update(terminal_signal=False, terminal_signal_kind="MR_RELAXED_PULLBACK", audit_universe_version=cfg.audit_universe_version)

    chain = ["AUC_ATTEMPT","MR_REJECTION","MR_CLEAR_RECLAIM","MR_RECLAIM_LEG","MR_LVN","MR_PULLBACK","MR_ENTRY"]
    full = _finish_event(e, chain, cfg, strict_entry)
    no_trade_i = n["MR_ENTRY"].get("seq") or n["MR_PULLBACK"].get("seq") or auction_resolve_i
    _node(n, "NO_TRADE", not full, decision_i=None, g=None, reason_code="EXECUTE_MR" if full else "MR_CHAIN_REJECTED")
    n["NO_TRADE"].update(seq=no_trade_i, time=n["MR_ENTRY"].get("time") or n["MR_PULLBACK"].get("time"),
                          decision_price=n["MR_ENTRY"].get("decision_price"), anchor_seq=no_trade_i,
                          anchor_time=n["MR_ENTRY"].get("anchor_time"), anchor_price=n["MR_ENTRY"].get("anchor_price"))
    wait = not rejection and not bool(e["features"].get("terminal_signal"))
    _node(n, "WAIT_AMBIGUOUS", wait, decision_i=rejection_deadline, anchor_i=extreme_i, g=g,
          reason_code="NO_STRICT_REJECTION" if wait else "MR_BRANCH_EVALUATED")
    e["difficulty"] = _difficulty(abs((depth_at_decision or 0.0)-reclaim_need)/max(reclaim_need,1.0))
    return e


def _acceptance(g, qualified_i, boundary, up, cfg):
    if qualified_i is None:
        return False, None, 0.0, None
    end_i = _deadline_i(g, qualified_i, cfg.acceptance_window_sec)
    if end_i is None:
        return False, qualified_i, 0.0, None
    idx = list(range(qualified_i, end_i+1))
    prices = g["price"].iloc[idx].to_numpy(float)
    outside = prices > boundary if up else prices < boundary
    ratio = float(np.mean(outside)) if len(outside) else 0.0
    first_reentry = None
    for k in idx:
        p = float(g["price"].iloc[k])
        if (up and p <= boundary) or ((not up) and p >= boundary):
            first_reentry = k
            break
    return ratio >= cfg.acceptance_outside_ratio and first_reentry is None, end_i, ratio, first_reentry


def _build_bo(
    g, prior, cfg: ScanConfigV4Final, file, day, contract, auction_no,
    start, qualified_i, extreme_i, extreme, boundary, up, strict_reentry_i,
    audit_reentry_i, displacement_i, auction_resolve_i,
):
    direction = "long" if up else "short"
    e = _base(f"{day}-{contract}-A{auction_no:03d}-BO", file, day, contract, direction, prior, start, g, "BO")
    n = e["nodes"]
    excursion = (extreme - boundary) if up else (boundary - extreme)
    excursion_need = max(cfg.min_excursion_points, cfg.excursion_pct * prior["width"])
    displacement_need = cfg.acceptance_displacement_pct * prior["width"]
    e.update(extreme_seq=_seq(g, extreme_i), extreme_time=_iso(_time(g, extreme_i)), extreme_price=float(extreme))
    e["features"].update(
        auction_side="up" if up else "down", excursion_points=float(excursion),
        excursion_pct_value=float(excursion/prior["width"]), excursion_threshold=float(excursion_need),
        audit_universe_version=cfg.audit_universe_version,
    )
    _node(n,"CTX_VALUE",True,decision_i=start,anchor_i=start,g=g,reason_code="PROFILE_READY")
    _node(n,"AUC_ATTEMPT",True,decision_i=qualified_i,anchor_i=start,g=g,anchor_price=boundary,
          reason_code="EXCURSION_PASS",metrics={"actual":excursion,"threshold":excursion_need})
    _node(n,"AUC_EXTREME",True,decision_i=auction_resolve_i,anchor_i=extreme_i,g=g,anchor_price=extreme,
          reason_code="EXTREME_LOCKED")
    rejection_deadline = _deadline_i(g, extreme_i, cfg.mr_reentry_max_sec)
    _node(n,"MR_REJECTION",strict_reentry_i is not None,
          decision_i=strict_reentry_i if strict_reentry_i is not None else rejection_deadline,
          anchor_i=audit_reentry_i if audit_reentry_i is not None else extreme_i,g=g,anchor_price=boundary,
          reason_code="REENTERED_VALUE_IN_TIME" if strict_reentry_i is not None else "NO_STRICT_VALUE_REENTRY")

    displacement = displacement_i is not None
    displacement_deadline = _deadline_i(g, qualified_i, cfg.acceptance_window_sec)
    _node(n,"BO_DISPLACEMENT",displacement,
          decision_i=displacement_i if displacement else displacement_deadline,
          anchor_i=displacement_i if displacement else extreme_i,g=g,
          reason_code="DISPLACEMENT_PASS" if displacement else "DISPLACEMENT_TOO_SMALL",
          metrics={"required_points":displacement_need,"actual_points":excursion})

    acceptance, accept_i, outside_ratio, window_reentry = _acceptance(g, qualified_i, boundary, up, cfg)
    _node(n,"BO_ACCEPTANCE",acceptance,decision_i=accept_i,anchor_i=accept_i,g=g,
          reason_code="ACCEPTANCE_PASS" if acceptance else ("WINDOW_REENTRY" if window_reentry is not None else "OUTSIDE_RATIO_FAIL"),
          metrics={"outside_ratio":outside_ratio,"threshold":cfg.acceptance_outside_ratio,
                   "window_seconds":cfg.acceptance_window_sec},start_i=qualified_i,end_i=accept_i)
    e["features"].update(outside_ratio=outside_ratio, acceptance_displacement=float(excursion),
                         acceptance_displacement_pct=float(excursion/prior["width"]))

    # Impulse structure is evaluated from the qualified auction, not from the
    # displacement gate.  This prevents displacement from defining its own audit universe.
    confirm, leg_end, best = _turn_confirm(g, qualified_i, direction, cfg.turn_points, cfg.audit_leg_max_sec)
    leg_ok = confirm is not None
    leg_fail_i = _deadline_i(g, qualified_i, cfg.audit_leg_max_sec)
    _node(n,"BO_IMPULSE_LEG",leg_ok,decision_i=confirm if leg_ok else leg_fail_i,
          anchor_i=leg_end,g=g,reason_code="IMPULSE_TURN_CONFIRMED" if leg_ok else "NO_IMPULSE_TURN_CONFIRM",
          metrics={"turn_points":cfg.turn_points},start_i=qualified_i,end_i=leg_end)

    candidate_lvn, depth = None, 0.0
    if leg_end is not None and qualified_i is not None:
        lo,hi=min(qualified_i,leg_end),max(qualified_i,leg_end)
        candidate_lvn,depth=_best_valley_leg(g.iloc[lo:hi+1])
    lvn_pass = candidate_lvn is not None and depth >= cfg.lvn_depth and leg_ok
    if candidate_lvn is not None:
        e["lvn"] = float(candidate_lvn)
    _node(n,"BO_LVN",lvn_pass,decision_i=confirm if confirm is not None else leg_fail_i,
          anchor_i=confirm if confirm is not None else leg_end,g=g,anchor_price=candidate_lvn,
          reason_code="LVN_DEPTH_PASS" if lvn_pass else ("LVN_TOO_SHALLOW" if candidate_lvn is not None else "NO_LEG_VALLEY"),
          metrics={"depth":depth,"threshold":cfg.lvn_depth,"audit_min_depth":cfg.audit_lvn_min_depth,
                   "candidate_price":candidate_lvn,"profile_basis":"impulse_leg"})

    audit_touch, audit_touch_deadline = (None, confirm)
    if candidate_lvn is not None and depth >= cfg.audit_lvn_min_depth and confirm is not None:
        audit_touch,audit_touch_deadline=_first_touch(g,confirm,candidate_lvn,cfg.lvn_tolerance,cfg.audit_pullback_max_sec)
    delay=None
    if audit_touch is not None and confirm is not None:
        delay=(_time(g,audit_touch)-_time(g,confirm)).total_seconds()
    pullback_pass=bool(lvn_pass and audit_touch is not None and delay is not None and delay<=cfg.pullback_max_sec)
    _node(n,"BO_PULLBACK",pullback_pass,
          decision_i=audit_touch if audit_touch is not None else audit_touch_deadline,
          anchor_i=audit_touch if audit_touch is not None else audit_touch_deadline,g=g,anchor_price=candidate_lvn,
          reason_code="FIRST_PULLBACK_PASS" if pullback_pass else ("LATE_PULLBACK" if audit_touch is not None else "PULLBACK_TIMEOUT"),
          metrics={"delay_seconds":delay,"strict_max_seconds":cfg.pullback_max_sec,"audit_max_seconds":cfg.audit_pullback_max_sec})

    response_i,response_deadline=(None,audit_touch_deadline)
    if audit_touch is not None:
        response_i,response_deadline=_response(g,audit_touch,direction,cfg.bo_response_points,max_sec=30)
    response_pass=response_i is not None
    _node(n,"BO_RESPONSE",response_pass,
          decision_i=response_i if response_i is not None else response_deadline,
          anchor_i=response_i if response_i is not None else audit_touch,g=g,
          reason_code="RESPONSE_PASS" if response_pass else "NO_DIRECTIONAL_RESPONSE",
          metrics={"required_points":cfg.bo_response_points,"max_seconds":30})

    strict_entry=None
    entry_quality=False
    if audit_touch is not None:
        ep=float(g["price"].iloc[audit_touch])
        stop=float(candidate_lvn-cfg.bo_stop_points if direction=="long" else candidate_lvn+cfg.bo_stop_points)
        risk=abs(ep-stop)
        extension=abs(ep-boundary)/max(prior["width"],1e-9)
        outside_now=ep>prior["vah"] if direction=="long" else ep<prior["val"]
        entry_quality=risk<=cfg.bo_entry_max_risk_points and extension<=cfg.bo_entry_max_extension_vw and outside_now
        _audit_entry_features(e,seq=_seq(g,audit_touch),time=_time(g,audit_touch),price=ep,stop=stop,risk=risk,
                              kind="BO_RELAXED_PULLBACK",cfg=cfg)
        e["features"].update(audit_lvn=float(candidate_lvn),audit_lvn_depth=float(depth),entry_extension_vw=float(extension))
        _node(n,"BO_ENTRY",entry_quality,decision_i=audit_touch,anchor_i=audit_touch,g=g,
              reason_code="ENTRY_QUALITY_PASS" if entry_quality else "ENTRY_EXTENSION_OR_RISK_FAIL",
              metrics={"risk_points":risk,"extension_vw":extension,"max_extension_vw":cfg.bo_entry_max_extension_vw,
                       "outside_old_value":outside_now})
        target=ep+cfg.bo_target_r*risk if direction=="long" else ep-cfg.bo_target_r*risk
        strict_entry={"seq":_seq(g,audit_touch),"time":_time(g,audit_touch),"price":ep,"stop":stop,"target":target}
    else:
        fail_i=_deadline_i(g,confirm if confirm is not None else qualified_i,cfg.audit_pullback_max_sec)
        _node(n,"BO_ENTRY",False,decision_i=fail_i,anchor_i=fail_i,g=g,reason_code="NO_RELAXED_TERMINAL_PULLBACK")
        e["features"].update(terminal_signal=False,terminal_signal_kind="BO_RELAXED_PULLBACK",audit_universe_version=cfg.audit_universe_version)

    chain=["AUC_ATTEMPT","BO_DISPLACEMENT","BO_ACCEPTANCE","BO_IMPULSE_LEG","BO_LVN","BO_PULLBACK","BO_RESPONSE","BO_ENTRY"]
    full=_finish_event(e,chain,cfg,strict_entry)
    no_trade_i=n["BO_ENTRY"].get("seq") or n["BO_RESPONSE"].get("seq") or accept_i
    _node(n,"NO_TRADE",not full,decision_i=None,g=None,reason_code="EXECUTE_BO" if full else "BO_CHAIN_REJECTED")
    n["NO_TRADE"].update(seq=no_trade_i,time=n["BO_ENTRY"].get("time") or n["BO_RESPONSE"].get("time"),
                          decision_price=n["BO_ENTRY"].get("decision_price"),anchor_seq=no_trade_i,
                          anchor_time=n["BO_ENTRY"].get("anchor_time"),anchor_price=n["BO_ENTRY"].get("anchor_price"))
    wait=not acceptance and strict_reentry_i is None
    _node(n,"WAIT_AMBIGUOUS",wait,decision_i=accept_i,anchor_i=extreme_i,g=g,
          reason_code="NO_ACCEPTANCE_OR_REJECTION" if wait else "BO_BRANCH_EVALUATED")
    e["difficulty"]=_difficulty(abs(excursion-displacement_need)/max(displacement_need,1.0))
    return e


def _wait_event(g,prior,cfg,file,day,contract,auction_no,start,extreme_i,extreme,boundary,up,resolve_i,excursion_need):
    direction="short" if up else "long"
    e=_base(f"{day}-{contract}-A{auction_no:03d}-WAIT",file,day,contract,direction,prior,start,g,"WAIT")
    n=e["nodes"]
    excursion=(extreme-boundary) if up else (boundary-extreme)
    _node(n,"CTX_VALUE",True,decision_i=start,anchor_i=start,g=g,reason_code="PROFILE_READY")
    _node(n,"AUC_ATTEMPT",False,decision_i=resolve_i,anchor_i=start,g=g,anchor_price=boundary,
          reason_code="EXCURSION_TOO_SMALL",metrics={"actual":excursion,"threshold":excursion_need})
    _node(n,"AUC_EXTREME",True,decision_i=resolve_i,anchor_i=extreme_i,g=g,anchor_price=extreme,reason_code="EXTREME_TIMEOUT")
    _node(n,"WAIT_AMBIGUOUS",True,decision_i=resolve_i,anchor_i=extreme_i,g=g,reason_code="UNQUALIFIED_AUCTION")
    _node(n,"NO_TRADE",True,decision_i=resolve_i,anchor_i=resolve_i,g=g,reason_code="UNQUALIFIED_AUCTION")
    e["features"].update(terminal_signal=False,audit_universe_version=cfg.audit_universe_version,
                         scanner_version=cfg.scanner_version)
    e["difficulty"]=_difficulty(abs(excursion-excursion_need)/max(excursion_need,1.0))
    return e


def scan_day_v4_final(g: pd.DataFrame, prior: dict, cfg: ScanConfigV4Final, file: Path, day: str, contract: str):
    events=[]
    if len(g)<10 or not prior or prior["width"]<=0:
        return events
    excursion_need=max(cfg.min_excursion_points,cfg.excursion_pct*prior["width"])
    displacement_need=cfg.acceptance_displacement_pct*prior["width"]
    i=0
    attempt=0
    while i<len(g):
        p0=float(g["price"].iloc[i])
        up=p0>prior["vah"]
        down=p0<prior["val"]
        if not(up or down):
            i+=1
            continue
        attempt+=1
        boundary=prior["vah"] if up else prior["val"]
        start=i
        extreme=p0
        extreme_i=i
        qualified_i=None
        displacement_i=None
        raw_reentry_i=None
        t_start=_time(g,start)
        j=i
        while j<len(g) and (_time(g,j)-t_start).total_seconds()<=cfg.auction_max_sec:
            price=float(g["price"].iloc[j])
            # Freeze the auction extreme once the first Value re-entry resolves it.
            if raw_reentry_i is None:
                if up and price>extreme:
                    extreme,extreme_i=price,j
                if down and price<extreme:
                    extreme,extreme_i=price,j
            excursion=(extreme-boundary) if up else (boundary-extreme)
            if qualified_i is None and excursion>=excursion_need:
                qualified_i=j
            if displacement_i is None and excursion>=displacement_need:
                displacement_i=j
            if qualified_i is not None and raw_reentry_i is None and ((up and price<=boundary) or (down and price>=boundary)):
                raw_reentry_i=j
            j+=1

        resolve_i=max(i,min(j-1,len(g)-1))
        if qualified_i is None:
            events.append(_wait_event(g,prior,cfg,file,day,contract,attempt,start,extreme_i,extreme,boundary,up,resolve_i,excursion_need))
            i=max(j,start+1)
            continue

        # If the auction did not re-enter during the strict auction observation,
        # allow a broader late re-entry solely for the reverse-audit universe.
        audit_reentry_i=raw_reentry_i
        if audit_reentry_i is None:
            audit_reentry_i=_first_reentry(g,extreme_i,boundary,up,cfg.audit_reentry_max_sec)
        strict_reentry_i=None
        if audit_reentry_i is not None:
            elapsed=(_time(g,audit_reentry_i)-_time(g,extreme_i)).total_seconds()
            if elapsed<=cfg.mr_reentry_max_sec:
                strict_reentry_i=audit_reentry_i
        reclaim_need=max(3.0,cfg.reclaim_pct*prior["width"])
        clear_i=_first_clear(g,extreme_i,strict_reentry_i,boundary,up,reclaim_need,cfg.reclaim_max_sec)

        # Both branch candidates are emitted for every qualified auction.  This
        # gives the trainer real NO examples and lets the reverse audit compare
        # gates without a branch-definition selection bias.
        events.append(_build_mr(g,prior,cfg,file,day,contract,attempt,start,qualified_i,extreme_i,extreme,boundary,up,
                                strict_reentry_i,audit_reentry_i,clear_i,resolve_i))
        events.append(_build_bo(g,prior,cfg,file,day,contract,attempt,start,qualified_i,extreme_i,extreme,boundary,up,
                                strict_reentry_i,audit_reentry_i,displacement_i,resolve_i))
        i=max(j,start+1)
    return events


__all__=[
    "ScanConfigV4Final","scan_day_v4_final","migrate_v4_schema","write_events_v4",
    "_best_valley_leg",
]
