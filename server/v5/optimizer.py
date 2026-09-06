from __future__ import annotations

import itertools
import math
import random
import uuid
from statistics import median
from typing import Any, Callable

import pandas as pd

from .backtest import PhysicalPathLoader, RescanRequired, evaluate_backtest
from .statistics import benjamini_hochberg
from .storage import connect, tx, utcnow
from .strategy_registry import StrategyDefinition, canonical_json, content_hash
from .strategy_storage import freeze_optimization_run, migrate_strategy_db


def _research_role(event_db, research_run_id: str) -> dict[str, Any]:
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT * FROM research_runs WHERE research_run_id=?", (research_run_id,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(research_run_id)
    return dict(row)


def normalize_search_space(
    strategy: StrategyDefinition, search_space: dict[str, Any]
) -> dict[str, list[Any]]:
    specs = strategy.parameter_map()
    out: dict[str, list[Any]] = {}
    rescan = []
    for path, raw in search_space.items():
        if path not in specs:
            raise ValueError(f"unknown optimization parameter: {path}")
        if specs[path].requires_rescan:
            rescan.append(path)
            continue
        if isinstance(raw, dict):
            if "values" in raw:
                values = list(raw["values"])
            else:
                start = raw.get("start")
                stop = raw.get("stop")
                step = raw.get("step")
                if start is None or stop is None or step in (None, 0):
                    raise ValueError(f"invalid numeric search range for {path}")
                values = []
                x = float(start)
                step = float(step)
                guard = 0
                while x <= float(stop) + abs(step) * 1e-9:
                    values.append(round(x, 12))
                    x += step
                    guard += 1
                    if guard > 10000:
                        raise ValueError(f"search range too large for {path}")
        elif isinstance(raw, (list, tuple)):
            values = list(raw)
        else:
            values = [raw]
        if not values:
            raise ValueError(f"empty search values for {path}")
        out[path] = [specs[path].validate(v) for v in values]
    if rescan:
        raise RescanRequired(sorted(rescan))
    return out


def _grid(
    space: dict[str, list[Any]], max_trials: int, seed: int
) -> list[dict[str, Any]]:
    keys = sorted(space)
    combos = [
        dict(zip(keys, values))
        for values in itertools.product(*(space[k] for k in keys))
    ]
    if len(combos) <= max_trials:
        return combos
    rng = random.Random(seed)
    # Deterministic bounded sampling with search corners retained.
    chosen = {0, len(combos) - 1}
    while len(chosen) < max_trials:
        chosen.add(rng.randrange(len(combos)))
    return [combos[i] for i in sorted(chosen)]


def _score(
    summary: dict[str, Any], objective: dict[str, Any]
) -> tuple[float, bool, str | None]:
    n = int(summary.get("trades") or 0)
    ev = float(summary.get("net_expectancy_r") or 0.0)
    pf_raw = summary.get("profit_factor")
    unbounded_pf = bool(summary.get("profit_factor_unbounded"))
    pf = (
        float(pf_raw)
        if isinstance(pf_raw, (int, float)) and math.isfinite(float(pf_raw))
        else (3.0 if unbounded_pf else 0.0)
    )
    dd = float(summary.get("max_drawdown_r") or 0.0)
    min_trades = int(objective.get("min_trades", 30))
    min_expectancy = float(objective.get("min_expectancy_r", 0.0))
    min_pf = float(objective.get("min_profit_factor", 1.0))
    max_dd = float(objective.get("max_drawdown_r", float("inf")))
    reasons = []
    if n < min_trades:
        reasons.append("MIN_TRADES")
    if ev < min_expectancy:
        reasons.append("MIN_EXPECTANCY")
    if not unbounded_pf and pf < min_pf:
        reasons.append("MIN_PF")
    if dd > max_dd:
        reasons.append("MAX_DD")
    weights = objective.get("weights") or {}
    w_ev = float(weights.get("expectancy", 1.0))
    w_pf = float(weights.get("profit_factor", 0.15))
    w_dd = float(weights.get("drawdown", 0.08))
    w_capture = float(weights.get("capture", 0.05))
    capture = float(summary.get("avg_capture_ratio") or 0.0)
    score = (
        w_ev * ev
        + w_pf * math.log(max(pf, 1e-9) + 1.0)
        - w_dd * dd
        + w_capture * capture
    )
    return score, not reasons, ",".join(reasons) if reasons else None


def _plateau(
    trials: list[dict[str, Any]], space: dict[str, list[Any]]
) -> dict[str, Any] | None:
    eligible = [
        x
        for x in trials
        if x.get("admissible")
        and (x.get("q_value") is None or x.get("q_value") <= 0.10)
    ]
    if not eligible:
        eligible = [x for x in trials if x.get("admissible")]
    if not eligible:
        return None
    scores = sorted(float(x["score"]) for x in eligible)
    cutoff = scores[max(0, int(len(scores) * 0.70) - 1)]
    top = [x for x in eligible if float(x["score"]) >= cutoff]
    center: dict[str, Any] = {}
    ranges: dict[str, Any] = {}
    for path in sorted(space):
        vals = [x["parameters"][path] for x in top if path in x["parameters"]]
        if not vals:
            continue
        if all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals
        ):
            center[path] = median(float(v) for v in vals)
            ranges[path] = {
                "min": min(vals),
                "max": max(vals),
                "top_values": sorted(set(vals)),
            }
        else:
            freq = {v: vals.count(v) for v in set(vals)}
            center[path] = max(freq, key=freq.get)
            ranges[path] = {"values": sorted(set(vals), key=str)}
    return {
        "plateau_id": "plateau-robust",
        "center_params": center,
        "range": ranges,
        "score": median(float(x["score"]) for x in top),
        "robustness": {
            "eligible_trials": len(eligible),
            "top_trials": len(top),
            "top_fraction": len(top) / len(eligible) if eligible else 0.0,
            "min_top_score": min(float(x["score"]) for x in top),
            "median_top_score": median(float(x["score"]) for x in top),
            "max_top_score": max(float(x["score"]) for x in top),
            "selection_rule": "top 30% of admissible FDR-screened trials; median center",
            "warning": "plateau is a robustness shortlist, not proof of market edge",
        },
    }


def run_optimization(
    event_db,
    data_root,
    research_run_id: str,
    strategy: StrategyDefinition,
    search_space: dict[str, Any],
    *,
    execution_model=None,
    objective: dict[str, Any] | None = None,
    max_trials: int = 200,
    seed: int = 23,
    bootstrap_reps: int = 1000,
    optimization_run_id: str | None = None,
    notes: str | None = None,
    path_loader: Callable[[dict[str, Any], int], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    migrate_strategy_db(event_db)
    research = _research_role(event_db, research_run_id)
    if str(research.get("role")) == "FINAL_HOLDOUT":
        raise RuntimeError("FINAL_HOLDOUT is sealed from parameter optimization")
    if not bool(research.get("frozen")):
        raise RuntimeError("optimization requires a frozen research run")
    space = normalize_search_space(strategy, search_space)
    if not space:
        raise ValueError("optimization search_space cannot be empty")
    objective = dict(objective or {})
    combos = _grid(space, max(1, int(max_trials)), seed)
    loader = path_loader or PhysicalPathLoader(data_root)
    trials = []
    for i, params in enumerate(combos, start=1):
        evaluated = evaluate_backtest(
            event_db,
            data_root,
            research_run_id,
            strategy,
            overrides=params,
            execution_model=execution_model,
            path_loader=loader,
            require_frozen_research=True,
            bootstrap_reps=bootstrap_reps,
        )
        summary = evaluated["report"]["summary"]
        score, admissible, reject = _score(summary, objective)
        trials.append(
            {
                "trial_no": i,
                "parameters": params,
                "parameters_hash": content_hash(params),
                "score": score,
                "expectancy_r": summary.get("net_expectancy_r"),
                "profit_factor": summary.get("profit_factor"),
                "max_drawdown_r": summary.get("max_drawdown_r"),
                "trades": summary.get("trades"),
                "p_value": summary.get("expectancy_p_value"),
                "q_value": None,
                "admissible": bool(admissible),
                "rejection_reason": reject,
                "metrics": summary,
            }
        )
    q_values = benjamini_hochberg([x.get("p_value") for x in trials])
    for row, q in zip(trials, q_values):
        row["q_value"] = q
    plateau = _plateau(trials, space)

    optimization_run_id = optimization_run_id or ("opt-" + uuid.uuid4().hex[:16])
    with tx(event_db) as c:
        if c.execute(
            "SELECT 1 FROM optimization_runs WHERE optimization_run_id=?",
            (optimization_run_id,),
        ).fetchone():
            raise ValueError(
                f"immutable optimization_run_id already exists: {optimization_run_id}"
            )
        c.execute(
            """INSERT INTO optimization_runs(
              optimization_run_id,research_run_id,campaign_id,strategy_key,strategy_hash,
              search_space_json,objective_json,hypotheses_tested,trial_count,status,created_at,notes
            ) VALUES(?,?,?,?,?,?,?,?,?,'OPEN',?,?)""",
            (
                optimization_run_id,
                research_run_id,
                research.get("campaign_id"),
                strategy.strategy_key,
                strategy.definition_hash,
                canonical_json(space),
                canonical_json(objective),
                len(combos),
                len(trials),
                utcnow(),
                notes,
            ),
        )
        c.executemany(
            """INSERT INTO optimization_trials(
              optimization_run_id,trial_no,parameters_json,parameters_hash,score,
              expectancy_r,profit_factor,max_drawdown_r,trades,p_value,q_value,
              admissible,rejection_reason,metrics_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    optimization_run_id,
                    x["trial_no"],
                    canonical_json(x["parameters"]),
                    x["parameters_hash"],
                    x["score"],
                    x["expectancy_r"],
                    x["profit_factor"],
                    x["max_drawdown_r"],
                    x["trades"],
                    x["p_value"],
                    x["q_value"],
                    int(x["admissible"]),
                    x["rejection_reason"],
                    canonical_json(x["metrics"]),
                )
                for x in trials
            ],
        )
        if plateau:
            c.execute(
                "INSERT INTO parameter_plateaus VALUES(?,?,?,?,?,?,1)",
                (
                    optimization_run_id,
                    plateau["plateau_id"],
                    canonical_json(plateau["center_params"]),
                    canonical_json(plateau["range"]),
                    plateau["score"],
                    canonical_json(plateau["robustness"]),
                ),
            )
    digest = freeze_optimization_run(event_db, optimization_run_id)
    ranked = sorted(
        trials, key=lambda x: (not x["admissible"], -(x["score"] or -1e99))
    )
    return {
        "optimization_run_id": optimization_run_id,
        "research_run_id": research_run_id,
        "strategy_key": strategy.strategy_key,
        "hypotheses_tested": len(combos),
        "trials": trials,
        "top_trials": ranked[:20],
        "plateau": plateau,
        "frozen_digest": digest,
        "governance": {
            "holdout_used_for_tuning": False,
            "fdr_method": "BENJAMINI_HOCHBERG",
            "bootstrap_unit": "TRADING_DAY",
            "rescan_parameters_forbidden": True,
        },
    }


def freeze_candidate(
    event_db,
    strategy: StrategyDefinition,
    parameters: dict[str, Any],
    *,
    source_optimization_run_id: str | None = None,
    discovery_run_id: str | None = None,
    candidate_id: str | None = None,
    evidence: dict[str, Any] | None = None,
    allow_rescan_candidate: bool = False,
) -> dict[str, Any]:
    migrate_strategy_db(event_db)
    clean = strategy.validate_overrides(parameters)
    rescan = strategy.rescan_parameters(clean)
    if rescan and not allow_rescan_candidate:
        raise RescanRequired(rescan)
    if rescan and not discovery_run_id:
        raise ValueError(
            "detector-parameter candidate requires a dedicated freshly-scanned discovery_run_id"
        )
    candidate_id = candidate_id or ("cand-" + uuid.uuid4().hex[:16])
    with tx(event_db) as c:
        if c.execute(
            "SELECT 1 FROM strategy_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone():
            raise ValueError(f"candidate already exists: {candidate_id}")
        if discovery_run_id:
            rr = c.execute(
                "SELECT role,frozen,config_hash FROM research_runs WHERE research_run_id=?",
                (discovery_run_id,),
            ).fetchone()
            if not rr or rr["role"] != "DISCOVERY" or not bool(rr["frozen"]):
                raise ValueError("candidate discovery_run_id must be frozen DISCOVERY")
        c.execute(
            "INSERT INTO strategy_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                candidate_id,
                strategy.strategy_key,
                source_optimization_run_id,
                canonical_json(clean),
                content_hash(clean),
                discovery_run_id,
                None,
                None,
                "FROZEN_CANDIDATE",
                utcnow(),
                canonical_json(
                    {
                        **(evidence or {}),
                        "requires_rescan_parameters": rescan,
                        "strategy_definition_hash": strategy.definition_hash,
                    }
                ),
            ),
        )
    return {
        "candidate_id": candidate_id,
        "strategy_key": strategy.strategy_key,
        "parameters": clean,
        "parameters_hash": content_hash(clean),
        "status": "FROZEN_CANDIDATE",
        "requires_rescan_parameters": rescan,
    }
