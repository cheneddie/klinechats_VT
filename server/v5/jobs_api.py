from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .jobs import JobSupervisor, get_job, list_jobs


class StrategyJobRequest(BaseModel):
    job_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(900, ge=30, le=21600)


def install_jobs_api(
    app,
    *,
    event_db: str | Path,
    data_root: str | Path,
    strategy_root: str | Path | None = None,
):
    strategy_root = Path(
        strategy_root
        or (Path(__file__).resolve().parents[2] / "config" / "strategies")
    )
    # The research/event store is SQLite. Serialize write-heavy optimization and
    # candidate jobs to preserve deterministic transactions and avoid lock races.
    supervisor = JobSupervisor(event_db, data_root, strategy_root, max_concurrent=1)

    @app.post("/api/v5/strategy-lab/jobs")
    def job_submit(req: StrategyJobRequest):
        job_type = req.job_type.strip().upper()
        if job_type == "PRODUCTION_GATE":
            raise HTTPException(
                status_code=400,
                detail="PRODUCTION_GATE is not a background job; use the evidence-governed candidate production-gate endpoint",
            )
        if job_type not in {"BACKTEST", "OPTIMIZATION", "CANDIDATE_EVALUATION"}:
            raise HTTPException(
                status_code=400,
                detail=f"unsupported strategy job type: {job_type}",
            )
        try:
            job_id = supervisor.submit(
                job_type,
                req.payload,
                timeout_seconds=req.timeout_seconds,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "concurrency limit reached" in message:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "STRATEGY_JOB_CAPACITY",
                        "message": message,
                        "max_concurrent": supervisor.max_concurrent,
                        "retryable": True,
                    },
                ) from exc
            raise
        return {
            "job_id": job_id,
            "status": "QUEUED",
            "poll": f"/api/v5/strategy-lab/jobs/{job_id}",
        }

    @app.get("/api/v5/strategy-lab/jobs")
    def job_list(limit: int = 100):
        return {"items": list_jobs(event_db, limit)}

    @app.get("/api/v5/strategy-lab/jobs/{job_id}")
    def job_get(job_id: str):
        return get_job(event_db, job_id)

    @app.post("/api/v5/strategy-lab/jobs/{job_id}/cancel")
    def job_cancel(job_id: str):
        return supervisor.cancel(job_id)

    app.state.strategy_job_supervisor = supervisor
    return app


__all__ = ["install_jobs_api"]
