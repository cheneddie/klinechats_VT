from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .candidate import (
    evaluate_candidate,
    list_candidate_evaluations,
    list_production_gates,
    production_gate,
)
from .execution import ExecutionModel
from .strategy_registry import find_strategy, load_strategy_directory


class CandidateEvaluationRequest(BaseModel):
    research_run_id: str
    execution_model: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    bootstrap_reps: int = Field(1000, ge=200, le=10000)
    code_commit: str | None = None


class ProductionGateRequest(BaseModel):
    policy: dict[str, Any] = Field(default_factory=dict)
    parity_evidence_id: str | None = None
    paper_evidence_id: str | None = None
    notes: str | None = None


def install_candidate_api(
    app,
    *,
    event_db: str | Path,
    data_root: str | Path,
    strategy_root: str | Path | None = None,
):
    event_db = Path(event_db)
    data_root = Path(data_root)
    strategy_root = Path(
        strategy_root
        or (Path(__file__).resolve().parents[2] / "config" / "strategies")
    )

    def resolve(key: str):
        return find_strategy(load_strategy_directory(strategy_root), key)

    @app.post("/api/v5/strategy-lab/candidates/{candidate_id}/evaluate")
    def candidate_evaluate(candidate_id: str, req: CandidateEvaluationRequest):
        from .strategy_storage import migrate_strategy_db
        from .storage import connect

        migrate_strategy_db(event_db)
        c = connect(event_db)
        try:
            row = c.execute(
                "SELECT strategy_key FROM strategy_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        finally:
            c.close()
        if not row:
            raise KeyError(candidate_id)
        strategy = resolve(row["strategy_key"])
        model = ExecutionModel.from_dict(req.execution_model)
        return evaluate_candidate(
            event_db,
            data_root,
            candidate_id,
            req.research_run_id,
            strategy,
            execution_model=model,
            policy=req.policy,
            bootstrap_reps=req.bootstrap_reps,
            code_commit=req.code_commit,
        )

    @app.get("/api/v5/strategy-lab/candidates/{candidate_id}/evaluations")
    def candidate_evaluation_list(candidate_id: str):
        return {"items": list_candidate_evaluations(event_db, candidate_id)}

    @app.post("/api/v5/strategy-lab/candidates/{candidate_id}/production-gates")
    def candidate_production_gate(candidate_id: str, req: ProductionGateRequest):
        from .strategy_storage import migrate_strategy_db
        from .storage import connect

        migrate_strategy_db(event_db)
        c = connect(event_db)
        try:
            row = c.execute(
                "SELECT strategy_key FROM strategy_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        finally:
            c.close()
        if not row:
            raise KeyError(candidate_id)
        strategy = resolve(row["strategy_key"])
        return production_gate(
            event_db,
            candidate_id,
            strategy,
            policy=req.policy,
            parity_evidence_id=req.parity_evidence_id,
            paper_evidence_id=req.paper_evidence_id,
            notes=req.notes,
        )

    @app.get("/api/v5/strategy-lab/production-gates")
    def production_gate_list(candidate_id: str | None = None):
        return {"items": list_production_gates(event_db, candidate_id)}

    return app


__all__ = ["install_candidate_api"]
