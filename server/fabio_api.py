from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .causal_engine import ScanConfig, connect, discover, read_replay_window
from .progress_scanner import scan_files_progress

ROOT = Path(os.environ.get("FABIO_DATA_ROOT", r"D:\tools\traderChatV1\data\parquet\Future"))
DB = Path(os.environ.get("FABIO_EVENT_DB", str(Path.home() / ".fabio-decision-gym" / "events.sqlite3")))
app = FastAPI(title="Fabio Decision Gym Local API", version="2.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

jobs: dict[str, dict] = {}
_job_lock = threading.Lock()


class ScanRequest(BaseModel):
    years: list[int] | None = None
    contract_mode: str = "strict"


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _job_view(job: dict):
    out = dict(job)
    out["logs"] = list(job.get("logs", []))
    out["node_counts"] = dict(job.get("node_counts", {}))
    started = job.get("started_monotonic")
    if started is not None:
        elapsed = max(0.0, time.monotonic() - started)
        out["elapsed_seconds"] = round(elapsed, 1)
        work = float(job.get("work_rows_processed") or 0)
        out["work_rows_per_sec"] = round(work / elapsed, 0) if elapsed > 0 and work > 0 else 0
        pct = float(job.get("percent") or 0)
        if 0.005 <= pct < 1 and elapsed > 0:
            out["eta_seconds"] = round(elapsed * (1 - pct) / pct, 0)
        else:
            out["eta_seconds"] = None
    out.pop("started_monotonic", None)
    out.pop("last_persist_monotonic", None)
    return out


def _persist_job(job: dict, force=False):
    now_mono = time.monotonic()
    last = float(job.get("last_persist_monotonic") or 0)
    if not force and now_mono - last < 2.0:
        return
    job["last_persist_monotonic"] = now_mono
    view = _job_view(job)
    con = connect(DB)
    try:
        con.execute(
            "INSERT OR REPLACE INTO scan_runs(job_id,status,started_at,finished_at,years,config_json,events,message) VALUES(?,?,?,?,?,?,?,?)",
            (
                job["job_id"],
                job["status"],
                job.get("started_at"),
                job.get("finished_at"),
                json.dumps(job.get("years"), ensure_ascii=False),
                json.dumps({"contract_mode": job.get("contract_mode")}, ensure_ascii=False),
                int(job.get("events") or 0),
                json.dumps(view, ensure_ascii=False),
            ),
        )
        con.commit()
    finally:
        con.close()


def _append_log(job: dict, text: str, phase: str | None = None):
    if not text:
        return
    logs = job.setdefault("logs", [])
    last = logs[-1] if logs else None
    if last and last.get("message") == text:
        return
    logs.append({"at": _utcnow(), "phase": phase or job.get("phase"), "message": text})
    del logs[:-40]


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": "2.1.0",
        "data_root": str(ROOT),
        "db": str(DB),
        "files": len(discover(ROOT)) if ROOT.exists() else 0,
    }


@app.get("/api/datasets")
def datasets():
    con = connect(DB)
    rows = [dict(r) for r in con.execute("SELECT * FROM datasets ORDER BY year,file").fetchall()]
    con.close()
    if not rows and ROOT.exists():
        for p in discover(ROOT):
            try:
                y = int(p.stem.split("_")[-1])
                rows.append({"file": p.name, "year": y, "rows": 0, "qa": "DISCOVERED"})
            except Exception:
                pass
    return {"items": rows, "root": str(ROOT)}


def event_row(r):
    d = dict(r)
    d["nodes"] = json.loads(d.pop("nodes_json") or "{}")
    d["features"] = json.loads(d.pop("features_json") or "{}")
    d["id"] = d["event_id"]
    d["date"] = d["trading_date"]
    d["attemptStartTime"] = d.get("attempt_start_time")
    d["extremeTime"] = d.get("extreme_time")
    d["extremePrice"] = d.get("extreme_price")
    d["clearReclaimTime"] = d.get("clear_reclaim_time")
    d["clearReclaimPrice"] = d.get("clear_reclaim_price")
    d["turnConfirmTime"] = d.get("turn_confirm_time")
    d["entryTime"] = d.get("entry_time")
    d["entryPrice"] = d.get("entry_price")
    d["priorProfile"] = {"vah": d.get("vah"), "val": d.get("val"), "poc": d.get("poc"), "width": d.get("value_width")}
    return d


@app.get("/api/cases")
def cases(limit: int = 1000, offset: int = 0, node_id: str | None = None, answer: bool | None = None, strategy: str | None = None, year: int | None = None, direction: str | None = None, difficulty: int | None = None):
    con = connect(DB)
    where, args, join = [], [], ""
    if node_id:
        join = " JOIN node_instances n ON n.event_id=e.event_id "
        where.append("n.node_id=?")
        args.append(node_id)
        if answer is not None:
            where.append("n.answer=?")
            args.append(1 if answer else 0)
    if strategy:
        where.append("e.strategy=?")
        args.append(strategy)
    if year:
        where.append("e.year=?")
        args.append(year)
    if direction:
        where.append("e.direction=?")
        args.append(direction)
    if difficulty:
        where.append("e.difficulty=?")
        args.append(difficulty)
    sql = "SELECT e.* FROM events e " + join + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY e.trading_date,e.attempt_start_seq LIMIT ? OFFSET ?"
    args.extend([min(limit, 10000), offset])
    rows = [event_row(r) for r in con.execute(sql, args).fetchall()]
    con.close()
    return {"items": rows, "limit": limit, "offset": offset}


@app.get("/api/cases/{event_id}")
def case(event_id: str):
    con = connect(DB)
    r = con.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
    con.close()
    if not r:
        raise HTTPException(404, "case not found")
    return event_row(r)


@app.get("/api/nodes/stats")
def node_stats():
    con = connect(DB)
    rows = [dict(r) for r in con.execute("SELECT node_id,COUNT(*) total,SUM(answer) yes_count,COUNT(*)-SUM(answer) no_count FROM node_instances GROUP BY node_id ORDER BY node_id").fetchall()]
    con.close()
    return {"items": rows}


@app.get("/api/replay/{event_id}")
def replay(event_id: str, margin: int = 20000):
    con = connect(DB)
    r = con.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
    con.close()
    if not r:
        raise HTTPException(404, "case not found")
    event = event_row(r)
    bars = read_replay_window(ROOT, event, margin=max(1000, min(margin, 100000)))
    return {"case": event, "bars": bars, "period": "1s"}


@app.get("/api/research/summary")
def research_summary():
    con = connect(DB)
    summary = dict(con.execute("SELECT COUNT(*) events,SUM(strategy='MR') mr,SUM(strategy='BO') bo,SUM(strategy='WAIT') wait,SUM(result='ENTRY') entries FROM events").fetchone())
    by_year = [dict(r) for r in con.execute("SELECT year,COUNT(*) events,SUM(result='ENTRY') entries FROM events GROUP BY year ORDER BY year").fetchall()]
    con.close()
    return {"summary": summary, "by_year": by_year}


@app.get("/api/scan/status")
def scan_status():
    with _job_lock:
        return {"items": [_job_view(x) for x in list(jobs.values())[-20:]]}


@app.get("/api/scan/{job_id}")
def scan_job(job_id: str):
    with _job_lock:
        job = jobs.get(job_id)
        if job:
            return _job_view(job)
    con = connect(DB)
    row = con.execute("SELECT message FROM scan_runs WHERE job_id=?", (job_id,)).fetchone()
    con.close()
    if row and row["message"]:
        try:
            return json.loads(row["message"])
        except Exception:
            pass
    raise HTTPException(404, "scan job not found")


@app.post("/api/scan")
def scan(req: ScanRequest):
    if not ROOT.exists():
        raise HTTPException(400, f"data root not found: {ROOT}")
    if req.contract_mode not in {"strict", "front_month", "dominant_volume"}:
        raise HTTPException(400, "invalid contract_mode")

    with _job_lock:
        active = next((x for x in jobs.values() if x.get("status") in {"queued", "running"}), None)
        if active:
            raise HTTPException(409, f"scan already running: {active['job_id']}")
        job_id = str(uuid.uuid4())[:8]
        job = {
            "job_id": job_id,
            "status": "queued",
            "years": req.years,
            "contract_mode": req.contract_mode,
            "started_at": _utcnow(),
            "started_monotonic": time.monotonic(),
            "heartbeat_at": _utcnow(),
            "phase": "queued",
            "phase_label": "等待背景執行緒",
            "percent": 0.0,
            "events": 0,
            "mr": 0,
            "bo": 0,
            "wait": 0,
            "entries": 0,
            "node_counts": {},
            "message": "掃描任務已建立。",
            "logs": [],
        }
        _append_log(job, job["message"], "queued")
        jobs[job_id] = job
        _persist_job(job, force=True)

    def run():
        with _job_lock:
            job["status"] = "running"
            job["phase"] = "prepare"
            job["phase_label"] = "準備掃描"
            job["heartbeat_at"] = _utcnow()
            _append_log(job, "Scanner 背景執行緒已啟動。", "prepare")
            _persist_job(job, force=True)

        last_phase = None

        def progress(payload: dict):
            nonlocal last_phase
            with _job_lock:
                phase = payload.get("phase")
                job.update(payload)
                job["status"] = "running"
                job["heartbeat_at"] = _utcnow()
                message = payload.get("message") or ""
                # Keep the log readable: phase changes and completed trading days are logged;
                # raw batch heartbeats still update the numeric progress fields.
                if phase != last_phase or phase in {"scan_day", "file_done", "qa_failed"}:
                    _append_log(job, message, phase)
                    last_phase = phase
                _persist_job(job)

        try:
            cfg = ScanConfig(contract_mode=req.contract_mode)
            count = scan_files_progress(ROOT, DB, req.years, cfg, progress)
            with _job_lock:
                job.update(status="done", phase="done", phase_label="掃描完成", percent=1.0, events=count, finished_at=_utcnow(), heartbeat_at=_utcnow())
                _append_log(job, f"掃描完成，共 {count} events。", "done")
                _persist_job(job, force=True)
        except Exception as e:
            with _job_lock:
                job.update(status="failed", phase="failed", phase_label="掃描失敗", message=f"{type(e).__name__}: {e}", finished_at=_utcnow(), heartbeat_at=_utcnow())
                _append_log(job, job["message"], "failed")
                _persist_job(job, force=True)

    threading.Thread(target=run, daemon=True, name=f"fabio-scan-{job_id}").start()
    return _job_view(job)


def main():
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FABIO_API_PORT", "8765")))


if __name__ == "__main__":
    main()
