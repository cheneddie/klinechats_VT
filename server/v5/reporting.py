from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import mean, median
from typing import Any, Iterable


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    w = pos - lo
    return xs[lo] * (1 - w) + xs[hi] * w


def _profit_factor(values: list[float]) -> tuple[float | None, bool]:
    gains = sum(x for x in values if x > 0)
    losses = abs(sum(x for x in values if x < 0))
    if losses == 0:
        return None, bool(gains > 0)
    return gains / losses, False


def _drawdown(values: list[float]) -> dict[str, Any]:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    current_duration = 0
    max_duration = 0
    curve = []
    for i, r in enumerate(values):
        equity += r
        peak = max(peak, equity)
        dd = peak - equity
        if dd > 0:
            current_duration += 1
        else:
            current_duration = 0
        max_duration = max(max_duration, current_duration)
        max_dd = max(max_dd, dd)
        curve.append({"trade_no": i + 1, "equity_r": equity, "drawdown_r": dd})
    return {
        "max_drawdown_r": max_dd,
        "max_drawdown_duration_trades": max_duration,
        "equity_curve": curve,
    }


def _max_consecutive_losses(values: list[float]) -> int:
    best = cur = 0
    for x in values:
        if x < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _cluster_expectancy_ci(
    trades: list[dict[str, Any]], reps: int = 2000, seed: int = 19
) -> dict[str, Any]:
    by_day: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        day = str(t.get("trading_date") or "UNKNOWN")
        by_day[day].append(_f(t.get("net_r")))
    days = sorted(by_day)
    if not days:
        return {
            "observed_expectancy_r": None,
            "cluster_count": 0,
            "ci_low": None,
            "ci_high": None,
            "p_value": None,
            "bootstrap_reps": 0,
            "bootstrap_unit": "TRADING_DAY",
        }
    rng = random.Random(seed)
    boot = []
    observed_values = [x for d in days for x in by_day[d]]
    observed = mean(observed_values) if observed_values else 0.0
    for _ in range(max(200, int(reps))):
        sampled_days = [rng.choice(days) for __ in days]
        sample = [x for d in sampled_days for x in by_day[d]]
        boot.append(mean(sample) if sample else 0.0)
    boot.sort()
    ci_low = _percentile(boot, 0.025)
    ci_high = _percentile(boot, 0.975)
    # One-sided sign probability against expectancy <= 0. This is descriptive
    # bootstrap evidence, not an iid-trade p-value.
    p_value = sum(1 for x in boot if x <= 0.0) / len(boot)
    return {
        "observed_expectancy_r": observed,
        "cluster_count": len(days),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "p_value": p_value,
        "bootstrap_reps": len(boot),
        "bootstrap_unit": "TRADING_DAY",
    }


def _period_totals(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for row in rows:
        value = row.get(key)
        if value is not None:
            out[str(value)] += _f(row.get("net_r"))
    return dict(out)


def summarize_trades(
    trades: Iterable[dict[str, Any]], *, bootstrap_reps: int = 2000
) -> dict[str, Any]:
    rows = [dict(x) for x in trades]
    net_r = [_f(x.get("net_r")) for x in rows]
    gross_r = [_f(x.get("gross_r")) for x in rows]
    net_points = [_f(x.get("net_points")) for x in rows]
    gross_points = [_f(x.get("gross_points")) for x in rows]
    mfe_r = [_f(x.get("mfe_r")) for x in rows]
    mae_r = [_f(x.get("mae_r")) for x in rows]
    mfe_points = [_f(x.get("mfe_points")) for x in rows]
    mae_points = [_f(x.get("mae_points")) for x in rows]
    capture = [_f(x.get("capture_ratio")) for x in rows]
    costs = [
        _f(x.get("commission_points")) + _f(x.get("slippage_points")) for x in rows
    ]
    winners = [x for x in net_r if x > 0]
    losers = [x for x in net_r if x < 0]
    wins = len(winners)
    losses = len(losers)
    n = len(rows)
    win_rate = wins / n if n else None
    loss_rate = losses / n if n else None
    avg_win = mean(winners) if winners else None
    avg_loss = mean(losers) if losers else None
    expectancy_formula = None
    if n and avg_win is not None and avg_loss is not None:
        expectancy_formula = (win_rate or 0.0) * avg_win + (loss_rate or 0.0) * avg_loss
    expectancy = mean(net_r) if net_r else None
    dd = _drawdown(net_r)
    pf, pf_unbounded = _profit_factor(net_r)
    payoff = (
        avg_win / abs(avg_loss)
        if avg_win is not None and avg_loss not in (None, 0)
        else None
    )
    cluster = _cluster_expectancy_ci(rows, reps=bootstrap_reps)
    daily = _period_totals(rows, "trading_date")
    monthly = _period_totals(rows, "month")

    metrics = {
        "trades": n,
        "wins": wins,
        "losses": losses,
        "breakeven": n - wins - losses,
        "win_rate": win_rate,
        "gross_total_r": sum(gross_r),
        "net_total_r": sum(net_r),
        "gross_expectancy_r": mean(gross_r) if gross_r else None,
        "net_expectancy_r": expectancy,
        "expectancy_formula_r": expectancy_formula,
        "median_r": median(net_r) if net_r else None,
        "profit_factor": pf,
        "profit_factor_unbounded": int(pf_unbounded),
        "avg_win_r": avg_win,
        "avg_loss_r": avg_loss,
        "payoff_ratio": payoff,
        "gross_points": sum(gross_points),
        "net_points": sum(net_points),
        "points_per_trade": mean(net_points) if net_points else None,
        "total_cost_points": sum(costs),
        "cost_points_per_trade": mean(costs) if costs else None,
        "max_drawdown_r": dd["max_drawdown_r"],
        "max_drawdown_duration_trades": dd["max_drawdown_duration_trades"],
        "max_consecutive_losses": _max_consecutive_losses(net_r),
        "worst_trade_r": min(net_r) if net_r else None,
        "best_trade_r": max(net_r) if net_r else None,
        "worst_day_r": min(daily.values()) if daily else None,
        "best_day_r": max(daily.values()) if daily else None,
        "worst_month_r": min(monthly.values()) if monthly else None,
        "best_month_r": max(monthly.values()) if monthly else None,
        "avg_mfe_r": mean(mfe_r) if mfe_r else None,
        "avg_mae_r": mean(mae_r) if mae_r else None,
        "avg_mfe_points": mean(mfe_points) if mfe_points else None,
        "avg_mae_points": mean(mae_points) if mae_points else None,
        "avg_capture_ratio": mean(capture) if capture else None,
        "mfe_hit_1r_rate": sum(1 for x in mfe_r if x >= 1.0) / n if n else None,
        "mfe_hit_2r_rate": sum(1 for x in mfe_r if x >= 2.0) / n if n else None,
        "mfe_hit_3r_rate": sum(1 for x in mfe_r if x >= 3.0) / n if n else None,
        "mfe_hit_5r_rate": sum(1 for x in mfe_r if x >= 5.0) / n if n else None,
        "realized_ge_1r_rate": sum(1 for x in net_r if x >= 1.0) / n if n else None,
        "realized_ge_2r_rate": sum(1 for x in net_r if x >= 2.0) / n if n else None,
        "realized_ge_3r_rate": sum(1 for x in net_r if x >= 3.0) / n if n else None,
        "realized_ge_5r_rate": sum(1 for x in net_r if x >= 5.0) / n if n else None,
        # Backward-compatible names used by existing V5 consumers.
        "hit_1r_rate": sum(1 for x in mfe_r if x >= 1.0) / n if n else None,
        "hit_2r_rate": sum(1 for x in mfe_r if x >= 2.0) / n if n else None,
        "hit_3r_rate": sum(1 for x in mfe_r if x >= 3.0) / n if n else None,
        "hit_5r_rate": sum(1 for x in mfe_r if x >= 5.0) / n if n else None,
        "p10_r": _percentile(net_r, 0.10),
        "p25_r": _percentile(net_r, 0.25),
        "p50_r": _percentile(net_r, 0.50),
        "p75_r": _percentile(net_r, 0.75),
        "p90_r": _percentile(net_r, 0.90),
        "p95_r": _percentile(net_r, 0.95),
        "expectancy_ci_low": cluster["ci_low"],
        "expectancy_ci_high": cluster["ci_high"],
        "expectancy_p_value": cluster["p_value"],
        "bootstrap_unit": cluster["bootstrap_unit"],
        "bootstrap_reps": cluster["bootstrap_reps"],
        "cluster_count": cluster["cluster_count"],
    }
    return {"metrics": metrics, "equity_curve": dd["equity_curve"]}


def _slice(
    rows: list[dict[str, Any]], key: str, bootstrap_reps: int
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        grouped[str(value)].append(row)
    out = []
    for value, items in sorted(grouped.items()):
        out.append(
            {
                "slice_key": key,
                "slice_value": value,
                **summarize_trades(items, bootstrap_reps=bootstrap_reps),
            }
        )
    return out


def build_full_report(
    trades: Iterable[dict[str, Any]], *, bootstrap_reps: int = 2000
) -> dict[str, Any]:
    rows = [dict(x) for x in trades]
    base = summarize_trades(rows, bootstrap_reps=bootstrap_reps)
    slices = []
    for key in (
        "year",
        "month",
        "direction",
        "strategy_family",
        "exit_reason",
        "post_trade_reason",
    ):
        slices.extend(_slice(rows, key, max(500, bootstrap_reps // 2)))

    by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        tm = str(row.get("signal_time") or "")
        hhmm = tm[11:16] if len(tm) >= 16 else ""
        if hhmm:
            hour = int(hhmm[:2])
            minute = int(hhmm[3:])
            total = hour * 60 + minute
            bucket_total = (total // 30) * 30
            bucket = f"{bucket_total // 60:02d}:{bucket_total % 60:02d}"
            by_time[bucket].append(row)
    for value, items in sorted(by_time.items()):
        slices.append(
            {
                "slice_key": "time_30m",
                "slice_value": value,
                **summarize_trades(
                    items, bootstrap_reps=max(500, bootstrap_reps // 2)
                ),
            }
        )

    return {
        "summary": base["metrics"],
        "equity_curve": base["equity_curve"],
        "slices": slices,
        "methodology": {
            "expectancy": "mean(net_r); cross-check = win_rate*avg_win + loss_rate*avg_loss",
            "profit_factor": "sum positive net R / absolute sum negative net R; null + profit_factor_unbounded=1 means no observed loss",
            "drawdown": "trade-sequence equity R drawdown",
            "inference": "trading-day cluster bootstrap; no iid trade assumption",
            "right_tail": "MFE thresholds and realized R thresholds reported separately",
            "empty_run": "zero-trade reports remain valid structured reports, never synthetic performance",
        },
    }
