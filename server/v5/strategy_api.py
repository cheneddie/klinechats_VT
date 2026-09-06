from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .backtest import RescanRequired, run_backtest
from .execution import ExecutionModel
from .monitor import build_monitor_snapshot, persist_monitor_snapshot
from .optimizer import freeze_candidate, run_optimization
from .storage import connect
from .strategy_registry import (
    StrategyDefinition,
    content_hash,
    find_strategy,
    load_strategy_directory,
)
from .strategy_storage import (
    get_execution_model,
    list_registered_strategies,
    migrate_strategy_db,
    register_execution_model,
    register_strategy,
    verify_backtest_digest,
)


class BacktestRequest(BaseModel):
    research_run_id: str
    strategy_key: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    execution_model: dict[str, Any] = Field(default_factory=dict)
    backtest_run_id: str | None = None
    code_commit: str | None = None
    notes: str | None = None
    bootstrap_reps: int = Field(1000, ge=200, le=10000)


class OptimizationRequest(BaseModel):
    research_run_id: str
    strategy_key: str
    search_space: dict[str, Any]
    execution_model: dict[str, Any] = Field(default_factory=dict)
    objective: dict[str, Any] = Field(default_factory=dict)
    max_trials: int = Field(100, ge=1, le=2000)
    seed: int = 23
    bootstrap_reps: int = Field(600, ge=200, le=5000)
    optimization_run_id: str | None = None
    notes: str | None = None


class CandidateRequest(BaseModel):
    strategy_key: str
    parameters: dict[str, Any]
    source_optimization_run_id: str | None = None
    discovery_run_id: str | None = None
    candidate_id: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class MonitorRequest(BaseModel):
    strategy_key: str
    backtest_run_id: str
    baseline_backtest_run_id: str
    as_of_date: str
    window_days: int = Field(60, ge=5, le=730)
    policy: dict[str, Any] = Field(default_factory=dict)


def _strategy_map(strategy_root: Path) -> dict[str, StrategyDefinition]:
    items = load_strategy_directory(strategy_root)
    return {x.strategy_key: x for x in items}


def _resolve_strategy(strategy_root: Path, key: str) -> StrategyDefinition:
    items = list(_strategy_map(strategy_root).values())
    return find_strategy(items, key)


def _normalize_execution(payload: dict[str, Any]) -> ExecutionModel:
    raw = dict(payload or {})
    if raw and "version" not in raw:
        copy = dict(raw)
        copy.pop("version", None)
        raw["version"] = "CUSTOM-" + content_hash(copy)[:8]
    return ExecutionModel.from_dict(raw)


def _json(value):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except Exception:
        return value


def _load_backtest(event_db: Path, run_id: str, *, trade_limit: int = 5000) -> dict[str, Any]:
    c = connect(event_db)
    try:
        run = c.execute("SELECT * FROM backtest_runs WHERE backtest_run_id=?", (run_id,)).fetchone()
        if not run:
            raise KeyError(run_id)
        metrics = [dict(r) for r in c.execute(
            "SELECT * FROM backtest_metrics WHERE backtest_run_id=? ORDER BY slice_key,slice_value,metric_key",
            (run_id,),
        ).fetchall()]
        trades = [dict(r) for r in c.execute(
            "SELECT * FROM backtest_trades WHERE backtest_run_id=? ORDER BY trading_date,entry_seq LIMIT ?",
            (run_id, int(trade_limit)),
        ).fetchall()]
    finally:
        c.close()
    out = dict(run)
    out["parameters"] = _json(out.get("parameters_json"))
    for t in trades:
        t["regime"] = _json(t.get("regime_json")) or {}
        t["payload"] = _json(t.get("payload_json")) or {}
    summary = {
        x["metric_key"]: x["value"]
        for x in metrics
        if x["slice_key"] == "ALL" and x["slice_value"] == "ALL"
    }
    return {"run": out, "summary": summary, "metrics": metrics, "trades": trades}


def install_strategy_api(
    app,
    *,
    event_db: str | Path,
    data_root: str | Path,
    strategy_root: str | Path | None = None,
):
    event_db = Path(event_db)
    data_root = Path(data_root)
    strategy_root = Path(strategy_root or (Path(__file__).resolve().parents[2] / "config" / "strategies"))
    migrate_strategy_db(event_db)
    strategies = load_strategy_directory(strategy_root)
    for strategy in strategies:
        register_strategy(event_db, strategy)
    default_model = ExecutionModel()
    register_execution_model(
        event_db,
        default_model.execution_model_id,
        default_model.version,
        default_model.to_dict(),
    )

    @app.get("/api/v5/strategy-lab/health")
    def strategy_lab_health():
        c = connect(event_db)
        try:
            counts = {
                "strategies": c.execute("SELECT COUNT(*) n FROM strategy_definitions").fetchone()["n"],
                "backtests": c.execute("SELECT COUNT(*) n FROM backtest_runs").fetchone()["n"],
                "optimizations": c.execute("SELECT COUNT(*) n FROM optimization_runs").fetchone()["n"],
                "candidates": c.execute("SELECT COUNT(*) n FROM strategy_candidates").fetchone()["n"],
            }
        finally:
            c.close()
        return {
            "ok": True,
            "engine": "STRATEGY_LAB_V1",
            "counts": counts,
            "truth_boundary": "V6_EVALUATED_ONLY_PHYSICAL_SEQ",
            "formal_backtest_requires_frozen_research": True,
            "optimizer_holdout_access": "DENIED",
        }

    @app.get("/api/v5/strategy-lab/strategies")
    def strategy_list():
        fresh = load_strategy_directory(strategy_root)
        return {"items": [x.to_dict() for x in fresh]}

    @app.get("/api/v5/strategy-lab/strategies/{strategy_key}")
    def strategy_get(strategy_key: str):
        return _resolve_strategy(strategy_root, strategy_key).to_dict()

    @app.get("/api/v5/strategy-lab/execution-models")
    def execution_models():
        c = connect(event_db)
        try:
            items = [dict(r) for r in c.execute(
                "SELECT * FROM execution_models WHERE active=1 ORDER BY execution_model_id,version"
            ).fetchall()]
        finally:
            c.close()
        for item in items:
            item["definition"] = _json(item.get("definition_json"))
        return {"items": items}

    @app.post("/api/v5/strategy-lab/backtests")
    def backtest_run(req: BacktestRequest):
        strategy = _resolve_strategy(strategy_root, req.strategy_key)
        model = _normalize_execution(req.execution_model)
        return run_backtest(
            event_db,
            data_root,
            req.research_run_id,
            strategy,
            overrides=req.parameters,
            execution_model=model,
            bootstrap_reps=req.bootstrap_reps,
            backtest_run_id=req.backtest_run_id,
            code_commit=req.code_commit,
            notes=req.notes,
        )

    @app.get("/api/v5/strategy-lab/backtests")
    def backtest_list(limit: int = 100):
        c = connect(event_db)
        try:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
                (min(max(int(limit), 1), 1000),),
            ).fetchall()]
        finally:
            c.close()
        return {"items": rows}

    @app.get("/api/v5/strategy-lab/backtests/{backtest_run_id}")
    def backtest_get(backtest_run_id: str, trade_limit: int = 5000):
        result = _load_backtest(event_db, backtest_run_id, trade_limit=trade_limit)
        result["integrity"] = verify_backtest_digest(event_db, backtest_run_id)
        return result

    @app.get("/api/v5/strategy-lab/backtests/{backtest_run_id}/trades")
    def backtest_trades(backtest_run_id: str, limit: int = 1000, offset: int = 0):
        c = connect(event_db)
        try:
            rows = [dict(r) for r in c.execute(
                """SELECT * FROM backtest_trades WHERE backtest_run_id=?
                   ORDER BY trading_date,entry_seq LIMIT ? OFFSET ?""",
                (backtest_run_id, min(max(limit, 1), 10000), max(offset, 0)),
            ).fetchall()]
        finally:
            c.close()
        for r in rows:
            r["regime"] = _json(r.get("regime_json")) or {}
            r["payload"] = _json(r.get("payload_json")) or {}
        return {"items": rows}

    @app.get("/api/v5/strategy-lab/backtests/{backtest_run_id}/trades/{trade_id}")
    def backtest_trade(backtest_run_id: str, trade_id: str):
        c = connect(event_db)
        try:
            trade = c.execute(
                "SELECT * FROM backtest_trades WHERE backtest_run_id=? AND trade_id=?",
                (backtest_run_id, trade_id),
            ).fetchone()
            if not trade:
                raise KeyError(trade_id)
            trade = dict(trade)
            run = c.execute(
                "SELECT research_run_id FROM backtest_runs WHERE backtest_run_id=?", (backtest_run_id,)
            ).fetchone()
            event = c.execute(
                "SELECT * FROM events WHERE research_run_id=? AND event_id=?",
                (run["research_run_id"], trade["event_id"]),
            ).fetchone()
            nodes = [dict(r) for r in c.execute(
                "SELECT * FROM event_nodes WHERE research_run_id=? AND event_id=? ORDER BY resolution_seq,node_id",
                (run["research_run_id"], trade["event_id"]),
            ).fetchall()]
        finally:
            c.close()
        trade["regime"] = _json(trade.get("regime_json")) or {}
        trade["payload"] = _json(trade.get("payload_json")) or {}
        return {"trade": trade, "event": dict(event) if event else None, "nodes": nodes}

    @app.post("/api/v5/strategy-lab/optimizations")
    def optimization_run(req: OptimizationRequest):
        strategy = _resolve_strategy(strategy_root, req.strategy_key)
        model = _normalize_execution(req.execution_model)
        return run_optimization(
            event_db,
            data_root,
            req.research_run_id,
            strategy,
            req.search_space,
            execution_model=model,
            objective=req.objective,
            max_trials=req.max_trials,
            seed=req.seed,
            bootstrap_reps=req.bootstrap_reps,
            optimization_run_id=req.optimization_run_id,
            notes=req.notes,
        )

    @app.get("/api/v5/strategy-lab/optimizations")
    def optimization_list(limit: int = 100):
        c = connect(event_db)
        try:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM optimization_runs ORDER BY created_at DESC LIMIT ?",
                (min(max(limit, 1), 1000),),
            ).fetchall()]
        finally:
            c.close()
        return {"items": rows}

    @app.get("/api/v5/strategy-lab/optimizations/{optimization_run_id}")
    def optimization_get(optimization_run_id: str):
        c = connect(event_db)
        try:
            run = c.execute(
                "SELECT * FROM optimization_runs WHERE optimization_run_id=?", (optimization_run_id,)
            ).fetchone()
            if not run:
                raise KeyError(optimization_run_id)
            trials = [dict(r) for r in c.execute(
                "SELECT * FROM optimization_trials WHERE optimization_run_id=? ORDER BY admissible DESC,score DESC",
                (optimization_run_id,),
            ).fetchall()]
            plateaus = [dict(r) for r in c.execute(
                "SELECT * FROM parameter_plateaus WHERE optimization_run_id=? ORDER BY selected DESC,score DESC",
                (optimization_run_id,),
            ).fetchall()]
        finally:
            c.close()
        for row in trials:
            row["parameters"] = _json(row.get("parameters_json"))
            row["metrics"] = _json(row.get("metrics_json"))
        for row in plateaus:
            row["center_params"] = _json(row.get("center_params_json"))
            row["range"] = _json(row.get("range_json"))
            row["robustness"] = _json(row.get("robustness_json"))
        return {"run": dict(run), "trials": trials, "plateaus": plateaus}

    @app.post("/api/v5/strategy-lab/candidates")
    def candidate_freeze(req: CandidateRequest):
        strategy = _resolve_strategy(strategy_root, req.strategy_key)
        return freeze_candidate(
            event_db,
            strategy,
            req.parameters,
            source_optimization_run_id=req.source_optimization_run_id,
            discovery_run_id=req.discovery_run_id,
            candidate_id=req.candidate_id,
            evidence=req.evidence,
        )

    @app.get("/api/v5/strategy-lab/candidates")
    def candidate_list():
        c = connect(event_db)
        try:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM strategy_candidates ORDER BY frozen_at DESC"
            ).fetchall()]
        finally:
            c.close()
        for r in rows:
            r["parameters"] = _json(r.get("parameters_json"))
            r["evidence"] = _json(r.get("evidence_json"))
        return {"items": rows}

    @app.get("/api/v5/strategy-lab/compare")
    def compare(backtest_run_ids: str):
        ids = [x.strip() for x in backtest_run_ids.split(",") if x.strip()]
        if not ids or len(ids) > 20:
            raise ValueError("compare requires 1..20 backtest_run_ids")
        items = []
        for run_id in ids:
            x = _load_backtest(event_db, run_id, trade_limit=0)
            items.append({"run": x["run"], "summary": x["summary"]})
        return {"items": items}

    @app.post("/api/v5/strategy-lab/monitor")
    def monitor(req: MonitorRequest):
        current = _load_backtest(event_db, req.backtest_run_id)
        baseline = _load_backtest(event_db, req.baseline_backtest_run_id, trade_limit=0)
        snapshot = build_monitor_snapshot(
            current["trades"],
            baseline["summary"],
            strategy_key=req.strategy_key,
            as_of_date=req.as_of_date,
            window_days=req.window_days,
            policy=req.policy,
        )
        persist_monitor_snapshot(event_db, snapshot)
        return snapshot

    @app.get("/api/v5/strategy-lab/monitor")
    def monitor_list(strategy_key: str | None = None, limit: int = 200):
        c = connect(event_db)
        try:
            if strategy_key:
                rows = [dict(r) for r in c.execute(
                    "SELECT * FROM strategy_monitor_snapshots WHERE strategy_key=? ORDER BY as_of_date DESC LIMIT ?",
                    (strategy_key, min(max(limit, 1), 2000)),
                ).fetchall()]
            else:
                rows = [dict(r) for r in c.execute(
                    "SELECT * FROM strategy_monitor_snapshots ORDER BY as_of_date DESC LIMIT ?",
                    (min(max(limit, 1), 2000),),
                ).fetchall()]
        finally:
            c.close()
        for r in rows:
            r["regime"] = _json(r.get("regime_json"))
            r["details"] = _json(r.get("details_json"))
        return {"items": rows}

    return app
