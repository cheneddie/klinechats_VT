from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.jobs import (
    JobSupervisor,
    create_job,
    get_job,
    recover_orphaned_jobs,
    update_job,
)
from server.v5.jobs_api import StrategyJobRequest, install_jobs_api


class FakeProcess:
    def __init__(self, alive=True, exitcode=None):
        self.alive = alive
        self.exitcode = exitcode
        self.terminated = False
        self.joins = []

    def join(self, timeout=None):
        self.joins.append(timeout)

    def is_alive(self):
        return self.alive and not self.terminated

    def terminate(self):
        self.terminated = True
        self.exitcode = -15


class FakeApp:
    def __init__(self):
        self.state = SimpleNamespace()
        self.routes = {}

    def post(self, path):
        def decorate(fn):
            self.routes[("POST", path)] = fn
            return fn
        return decorate

    def get(self, path):
        def decorate(fn):
            self.routes[("GET", path)] = fn
            return fn
        return decorate


def test_job_state_is_durable_and_restart_marks_unfinished_orphaned():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        queued = create_job(db, "BACKTEST", {"research_run_id": "r"})
        running = create_job(db, "OPTIMIZATION", {"research_run_id": "r"})
        update_job(db, running, status="RUNNING", progress=.25, started=True)
        assert get_job(db, queued)["status"] == "QUEUED"
        before = get_job(db, running)
        assert before["status"] == "RUNNING"
        assert before["progress"] == .25
        assert before["heartbeat_at"]

        count = recover_orphaned_jobs(db)
        assert count == 2
        assert get_job(db, queued)["status"] == "ORPHANED"
        after = get_job(db, running)
        assert after["status"] == "ORPHANED"
        assert "server restarted" in after["error_text"]
        assert after["finished_at"]


def test_watchdog_hard_timeout_terminates_child_and_persists_terminal_state():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        supervisor = JobSupervisor(db, td, td, max_concurrent=1)
        job_id = create_job(db, "BACKTEST", {})
        update_job(db, job_id, status="RUNNING", progress=.1, started=True)
        process = FakeProcess(alive=True)
        supervisor._processes[job_id] = process
        supervisor._watch(job_id, process, timeout_seconds=1)

        assert process.terminated is True
        row = get_job(db, job_id)
        assert row["status"] == "TIMED_OUT"
        assert row["progress"] == 1.0
        assert "hard timeout after 1s" in row["error_text"]
        assert job_id not in supervisor._processes


def test_cancel_terminates_process_and_is_idempotent_terminal_state():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        supervisor = JobSupervisor(db, td, td, max_concurrent=1)
        job_id = create_job(db, "OPTIMIZATION", {})
        update_job(db, job_id, status="RUNNING", progress=.4, started=True)
        process = FakeProcess(alive=True)
        supervisor._processes[job_id] = process
        row = supervisor.cancel(job_id)
        assert process.terminated is True
        assert row["status"] == "CANCELLED"
        assert row["finished_at"]

        # A second cancel cannot rewrite a terminal job into another state.
        again = supervisor.cancel(job_id)
        assert again["status"] == "CANCELLED"


def test_jobs_api_returns_retryable_409_when_serial_capacity_is_busy():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "events.sqlite3"
        strategy_root = root / "strategies"
        strategy_root.mkdir()
        app = FakeApp()
        install_jobs_api(
            app,
            event_db=db,
            data_root=root,
            strategy_root=strategy_root,
        )
        supervisor = app.state.strategy_job_supervisor
        assert supervisor.max_concurrent == 1
        supervisor._processes["busy"] = FakeProcess(alive=True)

        submit = app.routes[("POST", "/api/v5/strategy-lab/jobs")]
        with pytest.raises(HTTPException) as exc_info:
            submit(StrategyJobRequest(
                job_type="BACKTEST",
                payload={"research_run_id": "synthetic"},
                timeout_seconds=30,
            ))

        exc = exc_info.value
        assert exc.status_code == 409
        assert exc.detail["code"] == "STRATEGY_JOB_CAPACITY"
        assert exc.detail["retryable"] is True
        assert exc.detail["max_concurrent"] == 1
        assert "concurrency limit reached" in exc.detail["message"]
