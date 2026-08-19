from __future__ import annotations

from calendar import WEDNESDAY, monthcalendar
from datetime import date
import re

OUTRIGHT_RE = re.compile(r'^\d{6}$')


def third_wednesday(year: int, month: int) -> date:
    weeks = monthcalendar(year, month)
    days = [w[WEDNESDAY] for w in weeks if w[WEDNESDAY]]
    return date(year, month, days[2])


def next_yyyymm(yyyymm: str) -> str:
    y = int(yyyymm[:4])
    m = int(yyyymm[4:])
    if m == 12:
        return f'{y + 1}01'
    return f'{y}{m + 1:02d}'


def causal_front_month(day: str, available: list[str]) -> str | None:
    """Choose MTX calendar front month without using same-day volume ranking.

    The current monthly contract stays front through the third-Wednesday expiry
    date. From the next trading date the minimum available outright contract at
    or beyond the next YYYYMM is used. If no valid forward contract exists, the
    function returns None rather than silently falling back to an expired month.
    """
    d = date.fromisoformat(day)
    current = f'{d.year}{d.month:02d}'
    target = current if d <= third_wednesday(d.year, d.month) else next_yyyymm(current)
    valid = sorted(
        str(e) for e in available
        if OUTRIGHT_RE.fullmatch(str(e)) and str(e) >= target
    )
    return valid[0] if valid else None


def choose_contracts(volume_map, mode: str = 'strict'):
    """Return one outright contract per trading date.

    `strict` and `front_month` are causal calendar modes. `dominant_volume`
    intentionally uses the completed trading day's volume and is retained only
    for research diagnostics; it must not be used to claim live-causal results.
    """
    out = {}
    previous = None
    for day in sorted(volume_map):
        vols = volume_map[day]
        available = sorted(str(e) for e in vols if OUTRIGHT_RE.fullmatch(str(e)))
        ranked = sorted(
            ((str(e), float(v)) for e, v in vols.items() if OUTRIGHT_RE.fullmatch(str(e))),
            key=lambda x: (-x[1], x[0]),
        )
        if mode == 'dominant_volume':
            pick = ranked[0][0] if ranked else None
            ambiguous = len(ranked) > 1 and ranked[0][1] < ranked[1][1] * 1.10
            causal = False
            reason = 'completed_day_volume_rank'
        else:
            pick = causal_front_month(day, available)
            ambiguous = False
            causal = True
            reason = 'calendar_front_month'
        changed = previous is not None and pick is not None and pick != previous
        out[day] = {
            'contract': pick,
            'roll': changed,
            'ambiguous': ambiguous,
            'causal': causal,
            'mode': mode,
            'reason': reason,
            'volume': float(vols.get(pick, 0)) if pick else 0.0,
            'second': float(ranked[1][1]) if len(ranked) > 1 else 0.0,
        }
        if pick is not None:
            previous = pick
    return out
