from __future__ import annotations

from pathlib import Path
from typing import Any

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
        job_id = supervisor.submit(
            req.job_type,
            req.payload,
            timeout_seconds=req.timeout_seconds,
        )
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
