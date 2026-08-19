from __future__ import annotations

import calendar
import re
from datetime import date

OUTRIGHT_RE = re.compile(r"^\d{6}$")


def third_wednesday(year: int, month: int) -> date:
    """Return the third Wednesday for the given calendar month."""
    cal = calendar.Calendar(firstweekday=calendar.MONDAY)
    wednesdays = [d for d in cal.itermonthdates(year, month) if d.month == month and d.weekday() == calendar.WEDNESDAY]
    return wednesdays[2]


def next_month_contract(year: int, month: int) -> str:
    if month == 12:
        return f"{year + 1}01"
    return f"{year}{month + 1:02d}"


def calendar_front_contract(day: str, available_expiries) -> tuple[str | None, dict]:
    """Choose the live-causal calendar front contract for a trading date.

    MTX monthly contracts expire on the third Wednesday. The expiring month stays
    front for the whole expiry-day research session; from the next trading day the
    next month becomes front. Only the *set* of available outright contracts is
    used. Completed-day volume ranking is never used for the strict decision.
    """
    d = date.fromisoformat(day)
    current = f"{d.year}{d.month:02d}"
    expiry_day = third_wednesday(d.year, d.month)
    preferred = current if d <= expiry_day else next_month_contract(d.year, d.month)
    available = sorted(str(x) for x in available_expiries if OUTRIGHT_RE.fullmatch(str(x)))
    candidates = [x for x in available if x >= preferred]
    pick = candidates[0] if candidates else None
    return pick, {
        "preferred": preferred,
        "expiry_day": expiry_day.isoformat(),
        "available": available,
        "causal": True,
        "reason": "calendar_front_month",
    }


def choose_contracts(volume_map, mode: str = "strict"):
    """Return one active contract per trading date.

    strict/front_month are live-causal calendar policies. dominant_volume is kept
    only as an explicitly non-causal diagnostic mode.
    """
    out = {}
    previous = None
    for day in sorted(volume_map):
        vols = volume_map[day]
        ranked = sorted(vols.items(), key=lambda x: (-x[1], x[0]))
        dominant = ranked[0][0] if ranked else None
        if mode == "dominant_volume":
            pick = dominant
            ambiguous = len(ranked) > 1 and ranked[0][1] < ranked[1][1] * 1.10
            meta = {
                "preferred": dominant,
                "expiry_day": None,
                "available": sorted(vols),
                "causal": False,
                "reason": "completed_day_volume_rank",
            }
        else:
            pick, meta = calendar_front_contract(day, vols.keys())
            ambiguous = False
        changed = previous is not None and pick is not None and pick != previous
        out[day] = {
            "contract": pick,
            "roll": changed,
            "ambiguous": ambiguous,
            "volume": float(vols.get(pick, 0)) if pick else 0.0,
            "second": float(ranked[1][1]) if len(ranked) > 1 else 0.0,
            **meta,
        }
        if pick is not None:
            previous = pick
    return out
