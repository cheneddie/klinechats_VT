from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .backtest import run_backtest
from .execution import ExecutionModel
from .portfolio import PortfolioPolicy
from .production_evidence import get_paper_evidence, get_parity_evidence
from .storage import connect, verify_run_digest, tx, utcnow
from .strategy_registry import StrategyDefinition, content_hash
from .strategy_storage import migrate_strategy_db, verify_backtest_digest

ROLES = ("DISCOVERY", "VALIDATION", "FINAL_HOLDOUT")

DEFAULT_EVALUATION_POLICY: dict[str, Any] = {
    "min_trades": 20,
    "min_expectancy_r": 0.0,
    "min_profit_factor": 1.0,
    "max_drawdown_r": 12.0,
    "require_positive_ci_low": False,
    "stress_extra_slippage_points": 1.0,
    "stress_latency_ms": 250,
    "stress_min_expectancy_r": 0.0,
}

DEFAULT_PRODUCTION_POLICY: dict[str, Any] = {
    "mr_min_target_r": 1.0,
    "bo_min_target_r": 2.0,
    "require_all_roles": True,
    "require_combined_stress_positive": True,
    "require_live_parity": True,
    "require_paper_trading": True,
}


def _json(value: Any, default=None):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _candidate(event_db: str | Path, candidate_id: str) -> dict[str, Any]:
    migrate_strategy_db(event_db)
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT * FROM strategy_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(f"candidate not found: {candidate_id}")
    out = dict(row)
    out["parameters"] = _json(out.get("parameters_json"), {}) or {}
    out["evidence"] = _json(out.get("evidence_json"), {}) or {}
    return out


def _research(event_db: str | Path, research_run_id: str) -> dict[str, Any]:
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT * FROM research_runs WHERE research_run_id=?", (research_run_id,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(f"research run not found: {research_run_id}")
    out = dict(row)
    if not bool(out.get("frozen")):
        raise RuntimeError("candidate evaluation requires frozen research run")
    verified = verify_run_digest(event_db, research_run_id)
    if not verified.get("valid"):
        raise RuntimeError("research run digest verification failed")
    return out


def _existing_evaluations(event_db: str | Path, candidate_id: str) -> dict[str, dict[str, Any]]:
    c = connect(event_db)
    try:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM candidate_evaluations WHERE candidate_id=? ORDER BY created_at",
            (candidate_id,),
        ).fetchall()]
    finally:
        c.close()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        row["result"] = _json(row.get("result_json"), {}) or {}
        out[row["role"]] = row
    return out


def _merge_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_EVALUATION_POLICY)
    out.update(dict(policy or {}))
    return out


def _stress_models(base: ExecutionModel, policy: dict[str, Any]) -> dict[str, ExecutionModel]:
    slip = float(policy.get("stress_extra_slippage_points", 1.0))
    latency = int(policy.get("stress_latency_ms", 250))
    suffix = content_hash(base.to_dict())[:8]
    return {
        "BASE": base,
        "SLIPPAGE": replace(
            base,
            execution_model_id=f"{base.execution_model_id}_STRESS_SLIPPAGE",
            version=f"{base.version}-{suffix}",
            entry_slippage_points=float(base.entry_slippage_points) + slip,
            exit_slippage_points=float(base.exit_slippage_points) + slip,
        ),
        "LATENCY": replace(
            base,
            execution_model_id=f"{base.execution_model_id}_STRESS_LATENCY",
            version=f"{base.version}-{suffix}",
            latency_ms=max(int(base.latency_ms), latency),
        ),
        "COMBINED": replace(
            base,
            execution_model_id=f"{base.execution_model_id}_STRESS_COMBINED",
            version=f"{base.version}-{suffix}",
            entry_slippage_points=float(base.entry_slippage_points) + slip,
            exit_slippage_points=float(base.exit_slippage_points) + slip,
            latency_ms=max(int(base.latency_ms), latency),
        ),
    }


def _acceptance(summary: dict[str, Any], policy: dict[str, Any], *, stress: bool = False) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, actual: Any, passed: bool, threshold: Any = None):
        checks.append({"name": name, "actual": actual, "threshold": threshold, "passed": bool(passed)})

    n = int(summary.get("trades") or 0)
    ev = summary.get("net_expectancy_r")
    pf = summary.get("profit_factor")
    pf_unbounded = bool(summary.get("profit_factor_unbounded"))
    dd = float(summary.get("max_drawdown_r") or 0.0)
    ci_low = summary.get("expectancy_ci_low")
    check("MIN_TRADES", n, n >= int(policy["min_trades"]), policy["min_trades"])
    min_ev = float(policy["stress_min_expectancy_r"] if stress else policy["min_expectancy_r"])
    check("EXPECTANCY", ev, ev is not None and float(ev) > min_ev, f"> {min_ev}")
    if not stress:
        check(
            "PROFIT_FACTOR",
            "UNBOUNDED" if pf_unbounded else pf,
            pf_unbounded or (pf is not None and float(pf) >= float(policy["min_profit_factor"])),
            policy["min_profit_factor"],
        )
        check("MAX_DRAWDOWN_R", dd, dd <= float(policy["max_drawdown_r"]), policy["max_drawdown_r"])
        if bool(policy.get("require_positive_ci_low")):
            check("EXPECTANCY_CI_LOW", ci_low, ci_low is not None and float(ci_low) > 0.0, "> 0")
    failed = [x for x in checks if not x["passed"]]
    if n < int(policy["min_trades"]):
        status = "INSUFFICIENT"
    else:
        status = "PASS" if not failed else "FAIL"
    return {"status": status, "checks": checks, "failed": [x["name"] for x in failed]}


def evaluate_candidate(
    event_db: str | Path,
    data_root: str | Path,
    candidate_id: str,
    research_run_id: str,
    strategy: StrategyDefinition,
    *,
    execution_model: ExecutionModel | dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    bootstrap_reps: int = 1000,
    code_commit: str | None = None,
    path_loader: Callable[[dict[str, Any], int], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    candidate = _candidate(event_db, candidate_id)
    research = _research(event_db, research_run_id)
    role = str(research.get("role"))
    if role not in ROLES:
        raise ValueError(f"unsupported research role for candidate evaluation: {role}")
    if candidate["strategy_key"] != strategy.strategy_key:
        raise ValueError("candidate strategy_key does not match supplied strategy")
    params = dict(candidate["parameters"])
    if content_hash(params) != candidate["parameters_hash"]:
        raise RuntimeError("candidate parameter digest mismatch")
    strategy.validate_overrides(params)

    candidate_evidence = dict(candidate.get("evidence") or {})
    raw_portfolio = candidate_evidence.get("portfolio_policy")
    if raw_portfolio is None:
        raise RuntimeError("candidate is missing frozen portfolio policy")
    portfolio = PortfolioPolicy.from_dict(raw_portfolio)
    portfolio_hash = content_hash(portfolio.to_dict())
    if portfolio_hash != str(candidate_evidence.get("portfolio_policy_hash") or ""):
        raise RuntimeError("candidate portfolio policy digest mismatch")

    existing = _existing_evaluations(event_db, candidate_id)
    if role in existing:
        raise ValueError(f"candidate already has immutable {role} evaluation")
    if role == "DISCOVERY" and candidate.get("discovery_run_id") and candidate["discovery_run_id"] != research_run_id:
        raise ValueError("candidate is pinned to a different discovery research run")
    if role == "VALIDATION":
        prev = existing.get("DISCOVERY")
        if not prev or (prev.get("result") or {}).get("status") != "PASS":
            raise RuntimeError("VALIDATION requires a passing DISCOVERY candidate evaluation")
    if role == "FINAL_HOLDOUT":
        prev = existing.get("VALIDATION")
        if not prev or (prev.get("result") or {}).get("status") != "PASS":
            raise RuntimeError("FINAL_HOLDOUT requires a passing VALIDATION candidate evaluation")

    merged_policy = _merge_policy(policy)
    model = execution_model if isinstance(execution_model, ExecutionModel) else ExecutionModel.from_dict(execution_model)
    scenario_models = _stress_models(model, merged_policy)
    scenario_results: dict[str, Any] = {}
    base_backtest_id = None

    for scenario, scenario_model in scenario_models.items():
        run_id = f"bt-candidate-{candidate_id}-{role.lower()}-{scenario.lower()}-{uuid.uuid4().hex[:8]}"
        result = run_backtest(
            event_db,
            data_root,
            research_run_id,
            strategy,
            overrides=params,
            execution_model=scenario_model,
            portfolio_policy=portfolio,
            bootstrap_reps=bootstrap_reps,
            backtest_run_id=run_id,
            code_commit=code_commit,
            notes=f"candidate={candidate_id}; role={role}; scenario={scenario}; portfolio={portfolio_hash}",
            path_loader=path_loader,
        )
        summary = result["report"]["summary"]
        scenario_results[scenario] = {
            "backtest_run_id": result["backtest_run_id"],
            "digest": result["digest"],
            "summary": summary,
            "portfolio_policy_hash": result.get("portfolio_policy_hash"),
            "acceptance": _acceptance(summary, merged_policy, stress=scenario != "BASE"),
        }
        if scenario == "BASE":
            base_backtest_id = result["backtest_run_id"]

    baseline_status = scenario_results["BASE"]["acceptance"]["status"]
    combined_status = scenario_results["COMBINED"]["acceptance"]["status"]
    status = baseline_status
    if status == "PASS" and combined_status != "PASS":
        status = "FAIL"

    evaluation_id = "ceval-" + uuid.uuid4().hex[:16]
    result_payload = {
        "status": status,
        "role": role,
        "policy": merged_policy,
        "scenarios": scenario_results,
        "parameter_hash": candidate["parameters_hash"],
        "portfolio_policy": portfolio.to_dict(),
        "portfolio_policy_hash": portfolio_hash,
        "research_digest": research.get("frozen_digest"),
    }
    with tx(event_db) as c:
        c.execute(
            """INSERT INTO candidate_evaluations(
              evaluation_id,candidate_id,role,research_run_id,backtest_run_id,
              parameters_hash,created_at,result_json
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                evaluation_id,
                candidate_id,
                role,
                research_run_id,
                base_backtest_id,
                candidate["parameters_hash"],
                utcnow(),
                json.dumps(result_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
    return {"evaluation_id": evaluation_id, "candidate_id": candidate_id, **result_payload}


def list_candidate_evaluations(event_db: str | Path, candidate_id: str) -> list[dict[str, Any]]:
    return list(_existing_evaluations(event_db, candidate_id).values())


def production_gate(
    event_db: str | Path,
    candidate_id: str,
    strategy: StrategyDefinition,
    *,
    policy: dict[str, Any] | None = None,
    parity_evidence_id: str | None = None,
    paper_evidence_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create an append-only production readiness decision.

    Live/Paper gates require immutable evidence IDs. A request can no longer promote
    a candidate by supplying naked boolean `pass` flags.
    """
    candidate = _candidate(event_db, candidate_id)
    if candidate["strategy_key"] != strategy.strategy_key:
        raise ValueError("candidate strategy_key does not match supplied strategy")
    merged = dict(DEFAULT_PRODUCTION_POLICY)
    merged.update(dict(policy or {}))
    evaluations = _existing_evaluations(event_db, candidate_id)
    checklist: list[dict[str, Any]] = []

    def add(name: str, passed: bool, details: Any = None):
        checklist.append({"name": name, "passed": bool(passed), "details": details})

    candidate_evidence = dict(candidate.get("evidence") or {})
    expected_portfolio_hash = str(candidate_evidence.get("portfolio_policy_hash") or "")
    try:
        expected_policy = PortfolioPolicy.from_dict(candidate_evidence.get("portfolio_policy"))
        computed_policy_hash = content_hash(expected_policy.to_dict())
    except Exception as exc:
        expected_policy = None
        computed_policy_hash = ""
        add("CANDIDATE_PORTFOLIO_POLICY", False, str(exc))
    else:
        add(
            "CANDIDATE_PORTFOLIO_POLICY",
            bool(expected_portfolio_hash) and expected_portfolio_hash == computed_policy_hash,
            {"expected": expected_portfolio_hash, "computed": computed_policy_hash, "policy": expected_policy.to_dict()},
        )

    for role in ROLES:
        row = evaluations.get(role)
        status = (row.get("result") or {}).get("status") if row else None
        add(f"{role}_EVALUATION", status == "PASS", status or "MISSING")
        if row:
            add(
                f"{role}_PARAMETER_HASH",
                row.get("parameters_hash") == candidate["parameters_hash"],
                row.get("parameters_hash"),
            )
            evaluation_portfolio_hash = str((row.get("result") or {}).get("portfolio_policy_hash") or "")
            add(
                f"{role}_PORTFOLIO_POLICY_HASH",
                bool(expected_portfolio_hash) and evaluation_portfolio_hash == expected_portfolio_hash,
                evaluation_portfolio_hash or "MISSING",
            )
            scenario_map = (row.get("result") or {}).get("scenarios") or {}
            for scenario, item in scenario_map.items():
                add(
                    f"{role}_{scenario}_PORTFOLIO_POLICY_HASH",
                    str(item.get("portfolio_policy_hash") or "") == expected_portfolio_hash,
                    item.get("portfolio_policy_hash") or "MISSING",
                )
                bt = item.get("backtest_run_id")
                try:
                    integrity = verify_backtest_digest(event_db, bt)
                    add(f"{role}_{scenario}_BACKTEST_DIGEST", bool(integrity.get("valid")), integrity)
                except Exception as exc:
                    add(f"{role}_{scenario}_BACKTEST_DIGEST", False, str(exc))

    resolved = strategy.resolved_config(candidate["parameters"])
    target = resolved.get("target") or {}
    target_r = target.get("r") if target.get("type") == "r_multiple" else None
    if strategy.family == "MR":
        floor = float(merged["mr_min_target_r"])
        add("MR_TARGET_R", target_r is not None and float(target_r) >= floor, {"actual": target_r, "minimum": floor})
    elif strategy.family == "BO":
        floor = float(merged["bo_min_target_r"])
        add("BO_TARGET_R", target_r is not None and float(target_r) >= floor, {"actual": target_r, "minimum": floor})

    holdout = evaluations.get("FINAL_HOLDOUT")
    combined = (((holdout or {}).get("result") or {}).get("scenarios") or {}).get("COMBINED") or {}
    combined_ev = (combined.get("summary") or {}).get("net_expectancy_r")
    if bool(merged.get("require_combined_stress_positive", True)):
        add("HOLDOUT_COMBINED_STRESS", combined_ev is not None and float(combined_ev) > 0.0, combined_ev)

    if bool(merged.get("require_live_parity", True)):
        try:
            parity = get_parity_evidence(event_db, str(parity_evidence_id or "")) if parity_evidence_id else None
            parity_ok = bool(parity and parity.get("candidate_id") == candidate_id and parity.get("status") == "PASS")
            add("LIVE_PARITY", parity_ok, {"evidence_id": parity_evidence_id, "status": parity.get("status") if parity else "MISSING"})
        except Exception as exc:
            add("LIVE_PARITY", False, {"evidence_id": parity_evidence_id, "error": str(exc)})
    if bool(merged.get("require_paper_trading", True)):
        try:
            paper = get_paper_evidence(event_db, str(paper_evidence_id or "")) if paper_evidence_id else None
            paper_ok = bool(paper and paper.get("candidate_id") == candidate_id and paper.get("status") == "PASS")
            add("PAPER_TRADING", paper_ok, {"evidence_id": paper_evidence_id, "status": paper.get("status") if paper else "MISSING"})
        except Exception as exc:
            add("PAPER_TRADING", False, {"evidence_id": paper_evidence_id, "error": str(exc)})

    failed = [x for x in checklist if not x["passed"]]
    research_checks = [x for x in checklist if x["name"] not in {"LIVE_PARITY", "PAPER_TRADING"}]
    research_pass = bool(research_checks) and all(x["passed"] for x in research_checks)
    status = "PASS" if not failed else ("BLOCKED_LIVE" if research_pass else "FAIL")
    gate_id = "pgate-" + uuid.uuid4().hex[:16]
    details = {
        "policy": merged,
        "research_pass": research_pass,
        "failed_checks": [x["name"] for x in failed],
        "portfolio_policy": expected_policy.to_dict() if expected_policy else None,
        "portfolio_policy_hash": expected_portfolio_hash or None,
        "parity_evidence_id": parity_evidence_id,
        "paper_evidence_id": paper_evidence_id,
        "notes": notes,
    }
    with tx(event_db) as c:
        c.execute(
            "INSERT INTO production_gates VALUES(?,?,?,?,?,?)",
            (
                gate_id,
                candidate_id,
                utcnow(),
                status,
                json.dumps(checklist, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
    return {
        "production_gate_id": gate_id,
        "candidate_id": candidate_id,
        "status": status,
        "checklist": checklist,
        "details": details,
    }


def list_production_gates(event_db: str | Path, candidate_id: str | None = None) -> list[dict[str, Any]]:
    c = connect(event_db)
    try:
        if candidate_id:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM production_gates WHERE candidate_id=? ORDER BY created_at DESC",
                (candidate_id,),
            ).fetchall()]
        else:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM production_gates ORDER BY created_at DESC LIMIT 500"
            ).fetchall()]
    finally:
        c.close()
    for row in rows:
        row["checklist"] = _json(row.get("checklist_json"), []) or []
        row["details"] = _json(row.get("details_json"), {}) or {}
    return rows


__all__ = [
    "evaluate_candidate",
    "list_candidate_evaluations",
    "production_gate",
    "list_production_gates",
    "DEFAULT_EVALUATION_POLICY",
    "DEFAULT_PRODUCTION_POLICY",
]
