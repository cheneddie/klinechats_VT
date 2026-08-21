from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from . import progress_scanner
from .v4_audit import _simulate_first_hits, management_suite
from .v4_audit_final import ablation_audit, compute_outcomes, reverse_node_audit
from .v4_final_engine import ScanConfigV4Final, migrate_v4_schema, scan_day_v4_final, write_events_v4
from .v4_replay_final import TIMEFRAME_RULES, read_tick_path, replay_trading_window


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def install(base):
    app = base.app
    progress_scanner.scan_day = scan_day_v4_final
    progress_scanner.write_events = write_events_v4
    base.ScanConfig = ScanConfigV4Final
    con = base.connect(base.DB)
    try:
        migrate_v4_schema(con)
    finally:
        con.close()

    def node_meta_v4(con, event_id: str):
        cols = {r[1] for r in con.execute("PRAGMA table_info(node_instances)").fetchall()}
        wanted = [
            "node_id","answer","decision_seq","decision_time","difficulty","decision_price",
            "anchor_seq","anchor_time","anchor_price","start_seq","start_time","end_seq","end_time",
            "reason_code","metrics_json","node_schema_version",
        ]
        selected = [x for x in wanted if x in cols]
        rows = con.execute(
            f"SELECT {','.join(selected)} FROM node_instances WHERE event_id=? ORDER BY decision_seq,node_id",
            (event_id,),
        ).fetchall()
        out = {}
        for r in rows:
            d = dict(r)
            node_id = d.pop("node_id")
            d["answer"] = bool(d.get("answer"))
            raw = d.pop("metrics_json", None)
            try:
                d["metrics"] = json.loads(raw or "{}")
            except Exception:
                d["metrics"] = {}
            out[node_id] = d
        return out

    base.node_meta = node_meta_v4

    audit_jobs: dict[str, dict] = {}
    audit_lock = threading.Lock()

    def audit_view(job):
        out = dict(job)
        started = job.get("started_monotonic")
        if started is not None:
            out["elapsed_seconds"] = round(max(0.0, time.monotonic() - started), 1)
        out.pop("started_monotonic", None)
        return out

    @app.get("/api/v4/health")
    def health_v4():
        return {
            "ok": True, "version": "4.1.0", "node_schema": 4,
            "audit_universe": "V4.1_RELAXED_TERMINAL",
            "replay_timeframes": list(TIMEFRAME_RULES), "reverse_audit": True,
            "trading_day_replay": True, "data_root": str(base.ROOT), "db": str(base.DB),
        }

    @app.get("/api/v4/replay/{event_id}")
    def replay_v4(event_id: str, node_id: str | None = None, days_before: int = 1, days_after: int = 1,
                  timeframe: str = "1m", session: str = "full"):
        if timeframe not in TIMEFRAME_RULES:
            raise HTTPException(400, f"unsupported timeframe: {timeframe}")
        if session not in {"full","day"}:
            raise HTTPException(400, "session must be full or day")
        con = base.connect(base.DB)
        try:
            r = con.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if not r:
                raise HTTPException(404, "case not found")
            event = base.event_row(r)
            meta = base.node_meta(con, event_id)
            event["nodeMeta"] = meta
        finally:
            con.close()
        payload = replay_trading_window(
            base.ROOT, event, meta, node_id=node_id,
            before=max(0,min(5,days_before)), after=max(0,min(5,days_after)),
            timeframe=timeframe, session=session,
        )
        return {"case":event, **payload, "center_node":node_id, "visual_schema":4,
                "decision_price_source":"persisted_physical_seq"}

    @app.get("/api/v4/node-meta/{event_id}")
    def node_meta_endpoint(event_id: str):
        con = base.connect(base.DB)
        try:
            if not con.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone():
                raise HTTPException(404, "case not found")
            return {"event_id":event_id,"items":base.node_meta(con,event_id),"schema":4}
        finally:
            con.close()

    def parse_years(text: str | None):
        return [int(x) for x in text.split(",") if x.strip()] if text else None

    @app.post("/api/v4/audit/outcomes")
    def audit_outcomes(years: str | None = None, max_after_days: int = 1):
        ys = parse_years(years)
        count = compute_outcomes(base.DB,base.ROOT,ys,max(0,min(3,max_after_days)))
        return {"ok":True,"computed":count,"years":ys}

    @app.post("/api/v4/audit/reverse")
    def audit_reverse(years: str | None = None):
        return reverse_node_audit(base.DB,parse_years(years))

    @app.post("/api/v4/audit/run")
    def audit_run(years: str | None = None, max_after_days: int = 1):
        ys = parse_years(years)
        with audit_lock:
            active = next((x for x in audit_jobs.values() if x.get("status") in {"queued","running"}), None)
            if active:
                raise HTTPException(409, f"audit already running: {active['job_id']}")
            job_id = "audit-" + uuid.uuid4().hex[:8]
            job = {
                "job_id":job_id,"status":"queued","phase":"queued","years":ys,
                "max_after_days":max(0,min(3,max_after_days)),"started_at":_utcnow(),
                "started_monotonic":time.monotonic(),"done":0,"total":0,"message":"Audit job created",
            }
            audit_jobs[job_id] = job

        def run():
            try:
                with audit_lock:
                    job.update(status="running",phase="outcomes",message="Computing physical-tick outcomes")
                def progress(p):
                    with audit_lock:
                        job.update(done=int(p.get("done") or 0),total=int(p.get("total") or 0),
                                   group=p.get("group"),groups=p.get("groups"),event_id=p.get("event_id"),
                                   message=f"Outcomes {p.get('done',0)} / {p.get('total',0)}")
                count = compute_outcomes(base.DB,base.ROOT,ys,job["max_after_days"],progress=progress)
                with audit_lock:
                    job.update(phase="reverse_audit",done=count,total=count,message="Reverse-auditing each strict gate")
                audit = reverse_node_audit(base.DB,ys)
                ab = ablation_audit(base.DB,ys)
                with audit_lock:
                    job.update(status="done",phase="done",finished_at=_utcnow(),message=f"Audit complete: {count} terminal opportunities",
                               computed=count,audit_id=audit.get("audit_id"),audit_rows=len(audit.get("rows") or []),ablation=ab)
            except Exception as e:
                with audit_lock:
                    job.update(status="failed",phase="failed",finished_at=_utcnow(),message=f"{type(e).__name__}: {e}")
        threading.Thread(target=run,daemon=True,name=job_id).start()
        return audit_view(job)

    @app.get("/api/v4/audit/jobs")
    def audit_job_list():
        with audit_lock:
            return {"items":[audit_view(x) for x in list(audit_jobs.values())[-20:]]}

    @app.get("/api/v4/audit/jobs/{job_id}")
    def audit_job(job_id: str):
        with audit_lock:
            job = audit_jobs.get(job_id)
            if not job:
                raise HTTPException(404,"audit job not found")
            return audit_view(job)

    @app.get("/api/v4/audit/latest")
    def audit_latest():
        con = base.connect(base.DB)
        try:
            row = con.execute(
                "SELECT audit_id,MAX(created_at) created_at FROM node_edge_audit GROUP BY audit_id ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not row or not row["audit_id"]:
                return {"audit_id":None,"items":[]}
            rows = [dict(x) for x in con.execute(
                "SELECT * FROM node_edge_audit WHERE audit_id=? ORDER BY strategy,node_id", (row["audit_id"],)
            ).fetchall()]
            for x in rows:
                try:
                    x["details"] = json.loads(x.pop("details_json") or "{}")
                except Exception:
                    x["details"] = {}
            return {"audit_id":row["audit_id"],"created_at":row["created_at"],"items":rows}
        finally:
            con.close()

    @app.get("/api/v4/audit/ablation")
    def audit_ablation(years: str | None = None):
        return ablation_audit(base.DB,parse_years(years))

    def terminal_spec(event):
        f = event.get("features",{})
        seq = f.get("terminal_entry_seq") if f.get("terminal_entry_seq") is not None else event.get("entry_seq")
        entry = f.get("terminal_entry_price") if f.get("terminal_entry_price") is not None else event.get("entry_price")
        stop = f.get("terminal_stop") if f.get("terminal_stop") is not None else event.get("stop")
        return seq,entry,stop

    @app.post("/api/v4/management/simulate/{event_id}")
    def management_simulate(event_id: str, max_after_days: int = 1):
        con = base.connect(base.DB)
        try:
            r = con.execute("SELECT * FROM events WHERE event_id=?",(event_id,)).fetchone()
            if not r:
                raise HTTPException(404,"case not found")
            event = base.event_row(r)
        finally:
            con.close()
        entry_seq,entry,stop = terminal_spec(event)
        if entry_seq is None or entry is None or stop is None:
            raise HTTPException(400,"event has no relaxed terminal opportunity")
        risk = abs(float(entry)-float(stop))
        if risk <= 0:
            raise HTTPException(400,"invalid risk")
        path = read_tick_path(base.ROOT,event,int(entry_seq),max(0,min(3,max_after_days)))
        hits = _simulate_first_hits(path,float(entry),risk,event["direction"])
        suite = management_suite(path,float(entry),risk,event["direction"])
        return {"event_id":event_id,"risk_points":risk,**hits,"management":suite,
                "basis":"physical _seq from relaxed terminal opportunity"}

    @app.get("/api/v4/management/summary")
    def management_summary(strategy: str | None = None):
        con = base.connect(base.DB)
        try:
            sql = "SELECT strategy,management_json FROM opportunity_outcomes"
            args = []
            if strategy:
                sql += " WHERE strategy=?"; args=[strategy]
            rows = con.execute(sql,args).fetchall()
        finally:
            con.close()
        acc = {}
        for r in rows:
            try:
                m = json.loads(r["management_json"] or "{}")
            except Exception:
                continue
            for name,x in m.items():
                if x.get("r") is not None:
                    acc.setdefault((r["strategy"],name),[]).append(float(x["r"]))
        items = []
        for (st,name),vals in sorted(acc.items()):
            if not vals:
                continue
            s = sorted(vals)
            pos = sum(v for v in vals if v>0)
            neg = abs(sum(v for v in vals if v<0))
            items.append({
                "strategy":st,"name":name,"n":len(vals),"avg_r":sum(vals)/len(vals),"total_r":sum(vals),
                "win_rate":sum(v>0 for v in vals)/len(vals),"median_r":s[len(s)//2],
                "p10_r":s[min(len(s)-1,int((len(s)-1)*.10))],"p90_r":s[min(len(s)-1,int((len(s)-1)*.90))],
                "max_r":max(vals),"min_r":min(vals),"profit_factor":pos/neg if neg>0 else None,
            })
        return {"items":items}

    @app.get("/api/v4/management/{event_id}")
    def management(event_id: str):
        con = base.connect(base.DB)
        try:
            row = con.execute("SELECT * FROM opportunity_outcomes WHERE event_id=?",(event_id,)).fetchone()
            if not row:
                raise HTTPException(404,"outcome not computed; run V4 audit first")
            d = dict(row)
            try:
                d["management"] = json.loads(d.pop("management_json") or "{}")
            except Exception:
                d["management"] = {}
            return d
        finally:
            con.close()

    return app
