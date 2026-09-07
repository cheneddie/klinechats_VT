from __future__ import annotations

import json
import multiprocessing as mp
import os
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from .storage import connect, tx, utcnow
from .strategy_storage import migrate_strategy_db

TERMINAL = {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED", "ORPHANED"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def create_job(event_db: str | Path, job_type: str, request: dict[str, Any]) -> str:
    migrate_strategy_db(event_db)
    job_id = "job-" + uuid.uuid4().hex[:16]
    with tx(event_db) as c:
        c.execute(
            """INSERT INTO strategy_jobs(
              job_id,job_type,status,progress,created_at,request_json,heartbeat_at
            ) VALUES(?,?, 'QUEUED',0,?,?,?)""",
            (job_id, str(job_type).upper(), utcnow(), _json(request), utcnow()),
        )
    return job_id


def update_job(
    event_db: str | Path,
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    result: Any = None,
    error_text: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> None:
    fields = ["heartbeat_at=?"]
    values: list[Any] = [utcnow()]
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if progress is not None:
        fields.append("progress=?")
        values.append(max(0.0, min(1.0, float(progress))))
    if result is not None:
        fields.append("result_json=?")
        values.append(_json(result))
    if error_text is not None:
        fields.append("error_text=?")
        values.append(str(error_text)[-20000:])
    if started:
        fields.append("started_at=COALESCE(started_at,?)")
        values.append(utcnow())
    if finished:
        fields.append("finished_at=?")
        values.append(utcnow())
    values.append(job_id)
    with tx(event_db) as c:
        c.execute(f"UPDATE strategy_jobs SET {','.join(fields)} WHERE job_id=?", values)


def get_job(event_db: str | Path, job_id: str) -> dict[str, Any]:
    migrate_strategy_db(event_db)
    c = connect(event_db)
    try:
        row = c.execute("SELECT * FROM strategy_jobs WHERE job_id=?", (job_id,)).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(job_id)
    out = dict(row)
    for key in ("request_json", "result_json"):
        raw = out.get(key)
        if raw:
            try:
                out[key[:-5]] = json.loads(raw)
            except Exception:
                out[key[:-5]] = raw
    return out


def list_jobs(event_db: str | Path, limit: int = 100) -> list[dict[str, Any]]:
    migrate_strategy_db(event_db)
    c = connect(event_db)
    try:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM strategy_jobs ORDER BY created_at DESC LIMIT ?",
            (min(max(int(limit), 1), 1000),),
        ).fetchall()]
    finally:
        c.close()
    return rows


def recover_orphaned_jobs(event_db: str | Path) -> int:
    migrate_strategy_db(event_db)
    with tx(event_db) as c:
        rows = c.execute(
            "SELECT job_id FROM strategy_jobs WHERE status IN ('QUEUED','RUNNING')"
        ).fetchall()
        for row in rows:
            c.execute(
                "UPDATE strategy_jobs SET status='ORPHANED',finished_at=?,heartbeat_at=?,error_text=? WHERE job_id=?",
                (utcnow(), utcnow(), "server restarted before job completion", row["job_id"]),
            )
    return len(rows)


def _heartbeat_loop(event_db: str, job_id: str, stop: threading.Event) -> None:
    while not stop.wait(5.0):
        try:
            current = get_job(event_db, job_id)
            if current.get("status") in TERMINAL:
                return
            update_job(event_db, job_id)
        except Exception:
            return


def _resolve_strategy(strategy_root: str, key: str):
    from .strategy_registry import find_strategy, load_strategy_directory
    return find_strategy(load_strategy_directory(Path(strategy_root)), key)


def _dispatch_job(
    job_type: str,
    payload: dict[str, Any],
    *,
    event_db: str,
    data_root: str,
    strategy_root: str,
) -> dict[str, Any]:
    job_type = job_type.upper()
    if job_type == "BACKTEST":
        from .backtest import run_backtest
        from .execution import ExecutionModel
        strategy = _resolve_strategy(strategy_root, payload["strategy_key"])
        result = run_backtest(
            event_db,
            data_root,
            payload["research_run_id"],
            strategy,
            overrides=payload.get("parameters") or {},
            execution_model=ExecutionModel.from_dict(payload.get("execution_model") or {}),
            bootstrap_reps=int(payload.get("bootstrap_reps") or 1000),
            backtest_run_id=payload.get("backtest_run_id"),
            code_commit=payload.get("code_commit"),
            notes=payload.get("notes"),
        )
        return {
            "backtest_run_id": result["backtest_run_id"],
            "frozen": result["frozen"],
            "digest": result["digest"],
            "trades": result["trades"],
            "summary": result["report"]["summary"],
        }
    if job_type == "OPTIMIZATION":
        from .execution import ExecutionModel
        from .optimizer import run_optimization
        strategy = _resolve_strategy(strategy_root, payload["strategy_key"])
        result = run_optimization(
            event_db,
            data_root,
            payload["research_run_id"],
            strategy,
            payload["search_space"],
            execution_model=ExecutionModel.from_dict(payload.get("execution_model") or {}),
            objective=payload.get("objective") or {},
            max_trials=int(payload.get("max_trials") or 100),
            seed=int(payload.get("seed") or 23),
            bootstrap_reps=int(payload.get("bootstrap_reps") or 600),
            optimization_run_id=payload.get("optimization_run_id"),
            notes=payload.get("notes"),
        )
        return {
            "optimization_run_id": result["optimization_run_id"],
            "hypotheses_tested": result["hypotheses_tested"],
            "plateau": result.get("plateau"),
            "frozen_digest": result["frozen_digest"],
            "governance": result["governance"],
        }
    if job_type == "CANDIDATE_EVALUATION":
        from .candidate import evaluate_candidate
        from .execution import ExecutionModel
        from .storage import connect
        c = connect(event_db)
        try:
            row = c.execute(
                "SELECT strategy_key FROM strategy_candidates WHERE candidate_id=?",
                (payload["candidate_id"],),
            ).fetchone()
        finally:
            c.close()
        if not row:
            raise KeyError(payload["candidate_id"])
        strategy = _resolve_strategy(strategy_root, row["strategy_key"])
        result = evaluate_candidate(
            event_db,
            data_root,
            payload["candidate_id"],
            payload["research_run_id"],
            strategy,
            execution_model=ExecutionModel.from_dict(payload.get("execution_model") or {}),
            policy=payload.get("policy") or {},
            bootstrap_reps=int(payload.get("bootstrap_reps") or 1000),
            code_commit=payload.get("code_commit"),
        )
        return {
            "evaluation_id": result["evaluation_id"],
            "candidate_id": result["candidate_id"],
            "role": result["role"],
            "status": result["status"],
        }
    if job_type == "PRODUCTION_GATE":
        from .candidate import production_gate
        from .storage import connect
        c = connect(event_db)
        try:
            row = c.execute(
                "SELECT strategy_key FROM strategy_candidates WHERE candidate_id=?",
                (payload["candidate_id"],),
            ).fetchone()
        finally:
            c.close()
        if not row:
            raise KeyError(payload["candidate_id"])
        strategy = _resolve_strategy(strategy_root, row["strategy_key"])
        return production_gate(
            event_db,
            payload["candidate_id"],
            strategy,
            policy=payload.get("policy") or {},
            live_parity_pass=bool(payload.get("live_parity_pass")),
            paper_trading_pass=bool(payload.get("paper_trading_pass")),
            notes=payload.get("notes"),
        )
    raise ValueError(f"unsupported strategy job type: {job_type}")


def _child_main(
    event_db: str,
    data_root: str,
    strategy_root: str,
    job_id: str,
    job_type: str,
    payload: dict[str, Any],
) -> None:
    stop = threading.Event()
    hb = threading.Thread(target=_heartbeat_loop, args=(event_db, job_id, stop), daemon=True)
    try:
        update_job(event_db, job_id, status="RUNNING", progress=0.05, started=True)
        hb.start()
        result = _dispatch_job(
            job_type,
            payload,
            event_db=event_db,
            data_root=data_root,
            strategy_root=strategy_root,
        )
        current = get_job(event_db, job_id)
        if current.get("status") not in TERMINAL:
            update_job(event_db, job_id, status="SUCCEEDED", progress=1.0, result=result, finished=True)
    except BaseException as exc:
        try:
            current = get_job(event_db, job_id)
            if current.get("status") not in TERMINAL:
                update_job(
                    event_db,
                    job_id,
                    status="FAILED",
                    progress=1.0,
                    error_text=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                    finished=True,
                )
        except Exception:
            pass
        raise
    finally:
        stop.set()


class JobSupervisor:
    """Process-isolated long-job supervisor.

    Each job runs in its own child process. Timeout therefore has real enforcement:
    the process is terminated, not merely marked stale. Heartbeats are written from
    the child every five seconds. DB state survives API restarts; unfinished jobs are
    explicitly marked ORPHANED on supervisor construction.
    """

    def __init__(
        self,
        event_db: str | Path,
        data_root: str | Path,
        strategy_root: str | Path,
        *,
        max_concurrent: int = 2,
    ):
        self.event_db = str(Path(event_db))
        self.data_root = str(Path(data_root))
        self.strategy_root = str(Path(strategy_root))
        self.max_concurrent = max(1, int(max_concurrent))
        self._lock = threading.RLock()
        self._processes: dict[str, mp.Process] = {}
        recover_orphaned_jobs(self.event_db)

    def submit(self, job_type: str, payload: dict[str, Any], *, timeout_seconds: int = 900) -> str:
        with self._lock:
            alive = [p for p in self._processes.values() if p.is_alive()]
            if len(alive) >= self.max_concurrent:
                raise RuntimeError("strategy job concurrency limit reached")
            job_id = create_job(self.event_db, job_type, payload)
            ctx = mp.get_context("spawn")
            p = ctx.Process(
                target=_child_main,
                args=(self.event_db, self.data_root, self.strategy_root, job_id, job_type, dict(payload)),
                daemon=True,
            )
            p.start()
            self._processes[job_id] = p
            threading.Thread(
                target=self._watch,
                args=(job_id, p, max(1, int(timeout_seconds))),
                daemon=True,
            ).start()
            return job_id

    def _watch(self, job_id: str, process: mp.Process, timeout_seconds: int) -> None:
        process.join(timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(5)
            try:
                current = get_job(self.event_db, job_id)
                if current.get("status") not in TERMINAL:
                    update_job(
                        self.event_db,
                        job_id,
                        status="TIMED_OUT",
                        progress=1.0,
                        error_text=f"hard timeout after {timeout_seconds}s; child process terminated",
                        finished=True,
                    )
            except Exception:
                pass
        elif process.exitcode not in (0, None):
            try:
                current = get_job(self.event_db, job_id)
                if current.get("status") not in TERMINAL:
                    update_job(
                        self.event_db,
                        job_id,
                        status="FAILED",
                        progress=1.0,
                        error_text=f"child process exit code {process.exitcode}",
                        finished=True,
                    )
            except Exception:
                pass
        with self._lock:
            self._processes.pop(job_id, None)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            process = self._processes.get(job_id)
            if process and process.is_alive():
                process.terminate()
                process.join(5)
            current = get_job(self.event_db, job_id)
            if current.get("status") not in TERMINAL:
                update_job(
                    self.event_db,
                    job_id,
                    status="CANCELLED",
                    progress=1.0,
                    error_text="cancelled by user",
                    finished=True,
                )
            self._processes.pop(job_id, None)
        return get_job(self.event_db, job_id)


__all__ = [
    "JobSupervisor",
    "create_job",
    "get_job",
    "list_jobs",
    "recover_orphaned_jobs",
]
