from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .storage import connect
from .strategy_registry import canonical_json
from .strategy_storage import migrate_strategy_db


def _json(raw: Any, default: Any = None):
    if raw is None:
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _run_context(event_db: Path, run_id: str) -> dict[str, Any]:
    c = connect(event_db)
    try:
        run = c.execute("SELECT * FROM backtest_runs WHERE backtest_run_id=?", (run_id,)).fetchone()
        if not run:
            raise KeyError(run_id)
        run = dict(run)
        rr = c.execute(
            "SELECT campaign_id,contract_policy_version,frozen_digest FROM research_runs WHERE research_run_id=?",
            (run["research_run_id"],),
        ).fetchone()
        rr = dict(rr) if rr else {}
        pins = [dict(r) for r in c.execute(
            "SELECT dataset_id,role,year,source_file,sha256 FROM research_run_datasets WHERE research_run_id=? ORDER BY dataset_id",
            (run["research_run_id"],),
        ).fetchall()]
        model = c.execute(
            "SELECT definition_hash,definition_json FROM execution_models WHERE execution_model_id=? AND version=?",
            (run["execution_model_id"], run["execution_model_version"]),
        ).fetchone()
        model = dict(model) if model else {}
        audit = c.execute(
            "SELECT payload_json FROM backtest_metrics WHERE backtest_run_id=? AND metric_key='portfolio_policy_audit' LIMIT 1",
            (run_id,),
        ).fetchone()
        audit = _json(audit["payload_json"], {}) if audit else {}
        summary_rows = c.execute(
            "SELECT metric_key,value FROM backtest_metrics WHERE backtest_run_id=? AND slice_key='ALL' AND slice_value='ALL'",
            (run_id,),
        ).fetchall()
    finally:
        c.close()

    definition = _json(model.get("definition_json"), {}) or {}
    execution = definition.get("execution_model") if isinstance(definition, dict) else None
    if not isinstance(execution, dict):
        execution = definition if isinstance(definition, dict) else {}
    policy = (audit or {}).get("policy") or (definition.get("portfolio_policy") if isinstance(definition, dict) else None) or {}
    portfolio_hash = (audit or {}).get("policy_hash") or (definition.get("portfolio_policy_hash") if isinstance(definition, dict) else None)
    dataset_basis = "EXACT_RESEARCH_RUN_DATASET_PINS" if pins else "RESEARCH_FROZEN_DIGEST_FALLBACK"
    dataset_digest = _digest(pins) if pins else str(run.get("data_digest") or rr.get("frozen_digest") or "")
    cost_profile = {
        "fill_timing": execution.get("fill_timing"),
        "entry_slippage_points": execution.get("entry_slippage_points"),
        "exit_slippage_points": execution.get("exit_slippage_points"),
        "commission_points_per_side": execution.get("commission_points_per_side"),
        "latency_ms": execution.get("latency_ms"),
    }
    summary = {r["metric_key"]: r["value"] for r in summary_rows}
    return {
        "run": run,
        "summary": summary,
        "campaign_id": run.get("campaign_id") or rr.get("campaign_id"),
        "dataset_basis": dataset_basis,
        "dataset_digest": dataset_digest,
        "dataset_pins": pins,
        "contract_policy_version": rr.get("contract_policy_version"),
        "execution_hash": run.get("execution_hash"),
        "execution_definition_hash": model.get("definition_hash"),
        "cost_profile": cost_profile,
        "portfolio_policy": policy,
        "portfolio_policy_hash": portfolio_hash,
        "mode": run.get("mode"),
        "code_commit": run.get("code_commit"),
    }


def _check(name: str, contexts: list[dict[str, Any]], getter, *, require_known: bool = True) -> dict[str, Any]:
    values = [getter(x) for x in contexts]
    known = all(v not in (None, "", {}) for v in values)
    equal = len({canonical_json(v) for v in values}) <= 1
    passed = equal and (known or not require_known)
    return {"name": name, "passed": passed, "known": known, "values": values}


def compare_contexts(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    if len(contexts) < 2:
        return {"status": "INSUFFICIENT", "checks": [], "failed": ["NEED_AT_LEAST_TWO_RUNS"], "warnings": []}
    checks = [
        _check("CAMPAIGN_ID", contexts, lambda x: x["campaign_id"], require_known=False),
        _check("DATASET_DIGEST", contexts, lambda x: x["dataset_digest"], require_known=True),
        _check("CONTRACT_POLICY_VERSION", contexts, lambda x: x["contract_policy_version"], require_known=False),
        _check("RUN_MODE", contexts, lambda x: x["mode"], require_known=True),
        _check("EXECUTION_HASH", contexts, lambda x: x["execution_hash"], require_known=True),
        _check("COST_SLIPPAGE_LATENCY", contexts, lambda x: x["cost_profile"], require_known=True),
        _check("PORTFOLIO_POLICY_HASH", contexts, lambda x: x["portfolio_policy_hash"], require_known=True),
        _check("CODE_COMMIT", contexts, lambda x: x["code_commit"], require_known=False),
    ]
    failed = [x["name"] for x in checks if not x["passed"]]
    warnings = []
    for x in checks:
        if not x["known"] and x["passed"]:
            warnings.append(f"{x['name']}_UNPINNED")
    return {
        "status": "COMPARABLE" if not failed else "BLOCKED",
        "checks": checks,
        "failed": failed,
        "warnings": warnings,
        "policy": "Metrics may be interpreted as strategy/parameter differences only when status=COMPARABLE.",
    }


def install_compare_api(app, *, event_db: str | Path):
    event_db = Path(event_db)
    migrate_strategy_db(event_db)

    @app.get("/api/v5/strategy-lab/compare-governed")
    def compare_governed(backtest_run_ids: str):
        ids = [x.strip() for x in backtest_run_ids.split(",") if x.strip()]
        if not ids or len(ids) > 20:
            raise ValueError("compare requires 1..20 backtest_run_ids")
        contexts = [_run_context(event_db, run_id) for run_id in ids]
        gate = compare_contexts(contexts)
        items = [
            {
                "run": x["run"],
                "summary": x["summary"],
                "comparability_context": {
                    "campaign_id": x["campaign_id"],
                    "dataset_basis": x["dataset_basis"],
                    "dataset_digest": x["dataset_digest"],
                    "contract_policy_version": x["contract_policy_version"],
                    "execution_hash": x["execution_hash"],
                    "cost_profile": x["cost_profile"],
                    "portfolio_policy": x["portfolio_policy"],
                    "portfolio_policy_hash": x["portfolio_policy_hash"],
                    "mode": x["mode"],
                    "code_commit": x["code_commit"],
                },
            }
            for x in contexts
        ]
        return {"items": items, "comparability": gate}

    return app


__all__ = ["install_compare_api", "compare_contexts", "_run_context"]
