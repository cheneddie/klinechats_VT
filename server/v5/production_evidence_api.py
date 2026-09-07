from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .production_evidence import list_evidence, record_paper_evidence, record_parity_evidence


class ParityEvidenceRequest(BaseModel):
    candidate_id: str
    historical: list[dict[str, Any]] = Field(default_factory=list)
    live: list[dict[str, Any]] = Field(default_factory=list)
    parity_evidence_id: str | None = None


class PaperEvidenceRequest(BaseModel):
    candidate_id: str
    source: str
    artifact_sha256: str
    trades: int = Field(ge=0)
    expectancy_r: float | None = None
    profit_factor: float | None = None
    max_drawdown_r: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    paper_evidence_id: str | None = None


def install_production_evidence_api(app, *, event_db: str | Path):
    @app.post("/api/v5/strategy-lab/evidence/parity")
    def parity_evidence(req: ParityEvidenceRequest):
        return record_parity_evidence(
            event_db,
            req.candidate_id,
            req.historical,
            req.live,
            parity_evidence_id=req.parity_evidence_id,
        )

    @app.post("/api/v5/strategy-lab/evidence/paper")
    def paper_evidence(req: PaperEvidenceRequest):
        return record_paper_evidence(
            event_db,
            req.candidate_id,
            source=req.source,
            artifact_sha256=req.artifact_sha256,
            trades=req.trades,
            expectancy_r=req.expectancy_r,
            profit_factor=req.profit_factor,
            max_drawdown_r=req.max_drawdown_r,
            start_date=req.start_date,
            end_date=req.end_date,
            metrics=req.metrics,
            policy=req.policy,
            notes=req.notes,
            paper_evidence_id=req.paper_evidence_id,
        )

    @app.get("/api/v5/strategy-lab/evidence")
    def evidence_list(candidate_id: str | None = None):
        return list_evidence(event_db, candidate_id)

    return app


__all__ = ["install_production_evidence_api"]
