from __future__ import annotations

import json
from fastapi import HTTPException

from . import progress_scanner
from .v4_audit import ablation_audit, compute_outcomes, reverse_node_audit
from .v4_engine import ScanConfigV4, migrate_v4_schema, scan_day_v4, write_events_v4
from .v4_replay import TIMEFRAME_RULES, replay_trading_window


def install(base):
    app=base.app
    progress_scanner.scan_day=scan_day_v4
    progress_scanner.write_events=write_events_v4
    base.ScanConfig=ScanConfigV4
    con=base.connect(base.DB)
    try:migrate_v4_schema(con)
    finally:con.close()

    def node_meta_v4(con,event_id:str):
        cols={r[1] for r in con.execute("PRAGMA table_info(node_instances)").fetchall()};wanted=["node_id","answer","decision_seq","decision_time","difficulty","decision_price","anchor_seq","anchor_time","anchor_price","start_seq","start_time","end_seq","end_time","reason_code","metrics_json","node_schema_version"];selected=[x for x in wanted if x in cols]
        rows=con.execute(f"SELECT {','.join(selected)} FROM node_instances WHERE event_id=? ORDER BY decision_seq,node_id",(event_id,)).fetchall();out={}
        for r in rows:
            d=dict(r);node_id=d.pop("node_id");d["answer"]=bool(d.get("answer"));raw=d.pop("metrics_json",None)
            try:d["metrics"]=json.loads(raw or "{}")
            except Exception:d["metrics"]={}
            out[node_id]=d
        return out
    base.node_meta=node_meta_v4

    @app.get("/api/v4/health")
    def health_v4():
        return{"ok":True,"version":"4.0.0","node_schema":4,"replay_timeframes":list(TIMEFRAME_RULES),"reverse_audit":True,"data_root":str(base.ROOT),"db":str(base.DB)}

    @app.get("/api/v4/replay/{event_id}")
    def replay_v4(event_id:str,node_id:str|None=None,days_before:int=1,days_after:int=1,timeframe:str="1m",session:str="full"):
        if timeframe not in TIMEFRAME_RULES:raise HTTPException(400,f"unsupported timeframe: {timeframe}")
        if session not in{"full","day"}:raise HTTPException(400,"session must be full or day")
        con=base.connect(base.DB)
        try:
            r=con.execute("SELECT * FROM events WHERE event_id=?",(event_id,)).fetchone()
            if not r:raise HTTPException(404,"case not found")
            event=base.event_row(r);meta=base.node_meta(con,event_id);event["nodeMeta"]=meta
        finally:con.close()
        payload=replay_trading_window(base.ROOT,event,meta,node_id=node_id,before=max(0,min(5,days_before)),after=max(0,min(5,days_after)),timeframe=timeframe,session=session)
        return{"case":event,**payload,"center_node":node_id,"visual_schema":4,"decision_price_source":"persisted_or_physical_seq"}

    @app.get("/api/v4/node-meta/{event_id}")
    def node_meta_endpoint(event_id:str):
        con=base.connect(base.DB)
        try:
            r=con.execute("SELECT 1 FROM events WHERE event_id=?",(event_id,)).fetchone()
            if not r:raise HTTPException(404,"case not found")
            return{"event_id":event_id,"items":base.node_meta(con,event_id),"schema":4}
        finally:con.close()

    @app.post("/api/v4/audit/outcomes")
    def audit_outcomes(years:str|None=None,max_after_days:int=1):
        ys=[int(x) for x in years.split(",") if x.strip()] if years else None;count=compute_outcomes(base.DB,base.ROOT,ys,max(0,min(3,max_after_days)));return{"ok":True,"computed":count,"years":ys}

    @app.post("/api/v4/audit/reverse")
    def audit_reverse(years:str|None=None):
        ys=[int(x) for x in years.split(",") if x.strip()] if years else None;return reverse_node_audit(base.DB,ys)

    @app.get("/api/v4/audit/latest")
    def audit_latest():
        con=base.connect(base.DB)
        try:
            row=con.execute("SELECT audit_id,MAX(created_at) created_at FROM node_edge_audit").fetchone()
            if not row or not row["audit_id"]:return{"audit_id":None,"items":[]}
            rows=[dict(x) for x in con.execute("SELECT * FROM node_edge_audit WHERE audit_id=? ORDER BY strategy,node_id",(row["audit_id"],)).fetchall()]
            for x in rows:
                try:x["details"]=json.loads(x.pop("details_json") or "{}")
                except Exception:x["details"]={}
            return{"audit_id":row["audit_id"],"created_at":row["created_at"],"items":rows}
        finally:con.close()

    @app.get("/api/v4/audit/ablation")
    def audit_ablation(years:str|None=None):
        ys=[int(x) for x in years.split(",") if x.strip()] if years else None;return ablation_audit(base.DB,ys)

    @app.post("/api/v4/management/simulate/{event_id}")
    def management_simulate(event_id:str,max_after_days:int=1):
        con=base.connect(base.DB)
        try:
            r=con.execute("SELECT * FROM events WHERE event_id=?",(event_id,)).fetchone()
            if not r:raise HTTPException(404,"case not found")
            event=base.event_row(r)
        finally:con.close()
        from .v4_replay import read_tick_path
        from .v4_audit import _simulate_first_hits,management_suite
        entry_seq=event.get("entry_seq") or event.get("features",{}).get("terminal_entry_seq");entry=event.get("entry_price") or event.get("features",{}).get("terminal_entry_price");stop=event.get("stop")
        if entry_seq is None or entry is None or stop is None:raise HTTPException(400,"event has no terminal opportunity entry")
        risk=abs(float(entry)-float(stop))
        if risk<=0:raise HTTPException(400,"invalid risk")
        path=read_tick_path(base.ROOT,event,int(entry_seq),max(0,min(3,max_after_days)));hits=_simulate_first_hits(path,float(entry),risk,event["direction"]);suite=management_suite(path,float(entry),risk,event["direction"]);return{"event_id":event_id,"risk_points":risk,**hits,"management":suite}

    @app.get("/api/v4/management/summary")
    def management_summary(strategy:str|None=None):
        con=base.connect(base.DB)
        try:
            sql="SELECT strategy,management_json FROM opportunity_outcomes";args=[]
            if strategy:sql+=" WHERE strategy=?";args=[strategy]
            rows=con.execute(sql,args).fetchall()
        finally:con.close()
        acc={}
        for r in rows:
            try:m=json.loads(r["management_json"] or "{}")
            except Exception:continue
            for name,x in m.items():
                z=acc.setdefault((r["strategy"],name),[])
                if x.get("r") is not None:z.append(float(x["r"]))
        items=[]
        for(st,name),vals in sorted(acc.items()):
            if not vals:continue
            vals2=sorted(vals);items.append({"strategy":st,"name":name,"n":len(vals),"avg_r":sum(vals)/len(vals),"win_rate":sum(v>0 for v in vals)/len(vals),"median_r":vals2[len(vals2)//2],"p90_r":vals2[min(len(vals2)-1,int(len(vals2)*.9))]})
        return{"items":items}

    @app.get("/api/v4/management/{event_id}")
    def management(event_id:str):
        con=base.connect(base.DB)
        try:
            row=con.execute("SELECT * FROM opportunity_outcomes WHERE event_id=?",(event_id,)).fetchone()
            if not row:raise HTTPException(404,"outcome not computed; run /api/v4/audit/outcomes first")
            d=dict(row)
            try:d["management"]=json.loads(d.pop("management_json") or "{}")
            except Exception:d["management"]={}
            return d
        finally:con.close()
    return app
