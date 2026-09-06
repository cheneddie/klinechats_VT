from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Iterable


def _finite(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def benjamini_hochberg(p_values: Iterable[float | None]) -> list[float | None]:
    raw = list(p_values)
    valid = []
    for i, value in enumerate(raw):
        p = _finite(value)
        if p is not None:
            valid.append((i, min(1.0, max(0.0, p))))
    if not valid:
        return [None] * len(raw)
    valid.sort(key=lambda x: x[1])
    m = len(valid)
    adjusted = [None] * len(raw)
    running = 1.0
    for rank_from_end in range(m - 1, -1, -1):
        idx, p = valid[rank_from_end]
        rank = rank_from_end + 1
        q = min(running, p * m / rank, 1.0)
        running = q
        adjusted[idx] = q
    return adjusted


def trading_day_cluster_bootstrap(
    rows,
    *,
    answer_key="answer",
    value_key="realized_r",
    day_key="trading_date",
    reps=2000,
    seed=42,
):
    clean = []
    for row in rows:
        value = _finite(row.get(value_key))
        day = row.get(day_key)
        answer = row.get(answer_key)
        if value is None or day is None or answer not in (True, False, 0, 1):
            continue
        clean.append((str(day), bool(answer), value))
    yes = [v for _, a, v in clean if a]
    no = [v for _, a, v in clean if not a]
    observed = (sum(yes) / len(yes) - sum(no) / len(no)) if yes and no else None

    by_day = defaultdict(list)
    for day, answer, value in clean:
        by_day[day].append((answer, value))
    days = sorted(by_day)
    if observed is None or len(days) < 2 or len(yes) < 2 or len(no) < 2 or reps <= 0:
        return {
            "delta": observed,
            "ci_low": None,
            "ci_high": None,
            "p_value": None,
            "cluster_count": len(days),
            "bootstrap_unit": "TRADING_DAY",
            "bootstrap_reps": int(reps),
        }

    rng = random.Random(seed)
    sims = []
    for _ in range(int(reps)):
        sy = []
        sn = []
        for _day in days:
            picked = rng.choice(days)
            for answer, value in by_day[picked]:
                (sy if answer else sn).append(value)
        if sy and sn:
            sims.append(sum(sy) / len(sy) - sum(sn) / len(sn))

    if len(sims) < max(100, int(reps) // 4):
        return {
            "delta": observed,
            "ci_low": None,
            "ci_high": None,
            "p_value": None,
            "cluster_count": len(days),
            "bootstrap_unit": "TRADING_DAY",
            "bootstrap_reps": len(sims),
        }

    sims.sort()

    def quantile(q):
        pos = q * (len(sims) - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return sims[lo]
        w = pos - lo
        return sims[lo] * (1 - w) + sims[hi] * w

    non_pos = sum(x <= 0 for x in sims)
    non_neg = sum(x >= 0 for x in sims)
    p_value = min(1.0, 2.0 * (min(non_pos, non_neg) + 1) / (len(sims) + 1))
    return {
        "delta": observed,
        "ci_low": quantile(0.025),
        "ci_high": quantile(0.975),
        "p_value": p_value,
        "cluster_count": len(days),
        "bootstrap_unit": "TRADING_DAY",
        "bootstrap_reps": len(sims),
    }
