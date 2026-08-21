from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .engine import connect
from .v4_engine import migrate_v4_schema
from .v4_replay import read_tick_path

MR_CHAIN=["AUC_ATTEMPT","MR_REJECTION","MR_CLEAR_RECLAIM","MR_RECLAIM_LEG","MR_LVN","MR_PULLBACK","MR_ENTRY"]
BO_CHAIN=["AUC_ATTEMPT","BO_DISPLACEMENT","BO_ACCEPTANCE","BO_IMPULSE_LEG","BO_LVN","BO_PULLBACK","BO_RESPONSE","BO_ENTRY"]
PARENTS={"MR_REJECTION":"AUC_ATTEMPT","MR_CLEAR_RECLAIM":"MR_REJECTION","MR_RECLAIM_LEG":"MR_CLEAR_RECLAIM","MR_LVN":"MR_RECLAIM_LEG","MR_PULLBACK":"MR_LVN","MR_ENTRY":"MR_PULLBACK","BO_DISPLACEMENT":"AUC_ATTEMPT","BO_ACCEPTANCE":"BO_DISPLACEMENT","BO_IMPULSE_LEG":"BO_ACCEPTANCE","BO_LVN":"BO_IMPULSE_LEG","BO_PULLBACK":"BO_LVN","BO_RESPONSE":"BO_PULLBACK","BO_ENTRY":"BO_RESPONSE"}


def _event_row(r):
    d=dict(r);d["features"]=json.loads(d.get("features_json") or "{}");d["nodes"]=json.loads(d.get("nodes_json") or "{}");d["id"]=d["event_id"];d["date"]=d["trading_date"];return d


def _node_meta(con,event_id):
    rows=con.execute("SELECT node_id,answer,decision_seq,decision_time,decision_price,anchor_seq,anchor_time,anchor_price,reason_code,metrics_json FROM node_instances WHERE event_id=?",(event_id,)).fetchall();out={}
    for r in rows:
        x=dict(r);x["answer"]=bool(x["answer"])
        try:x["metrics"]=json.loads(x.pop("metrics_json") or "{}")
        except Exception:x["metrics"]={}
        out[x.pop("node_id")]=x
    return out


def _directional_move(price,entry,direction):return price-entry if direction=="long" else entry-price

def _stop_move(price,entry,direction):return entry-price if direction=="long" else price-entry


def _simulate_first_hits(path,entry,risk,direction):
    if path.empty or risk<=0:return{}
    mfe=0.0;mae=0.0;hits={1:None,2:None,3:None};stop_at=None
    for _,row in path.iterrows():
        p=float(row["price"]);fav=_directional_move(p,entry,direction);adv=_stop_move(p,entry,direction);mfe=max(mfe,fav);mae=max(mae,adv)
        if stop_at is None and adv>=risk:stop_at=int(row["_seq"])
        for r in (1,2,3):
            if hits[r] is None and fav>=r*risk:hits[r]=int(row["_seq"])
    return{"mfe_points":mfe,"mae_points":mae,"mfe_r":mfe/risk,"mae_r":mae/risk,"hit_stop":stop_at is not None,"hit_1r":hits[1] is not None and (stop_at is None or hits[1]<stop_at),"hit_2r":hits[2] is not None and (stop_at is None or hits[2]<stop_at),"hit_3r":hits[3] is not None and (stop_at is None or hits[3]<stop_at),"first_hit_1r":hits[1],"first_hit_2r":hits[2],"first_hit_3r":hits[3]}


def _fixed_target(path,entry,risk,direction,target_r):
    target=target_r*risk
    for _,row in path.iterrows():
        p=float(row["price"]);fav=_directional_move(p,entry,direction);adv=_stop_move(p,entry,direction)
        if adv>=risk:return-1.0,int(row["_seq"])
        if fav>=target:return float(target_r),int(row["_seq"])
    if path.empty:return 0.0,None
    last=float(path["price"].iloc[-1]);return _directional_move(last,entry,direction)/risk,int(path["_seq"].iloc[-1])


def _fixed_trail(path,entry,risk,direction,trail_points,activate_r=1.0):
    if path.empty:return 0.0,None
    best=entry;active=False
    for _,row in path.iterrows():
        p=float(row["price"]);fav=_directional_move(p,entry,direction);adv=_stop_move(p,entry,direction)
        if adv>=risk and not active:return-1.0,int(row["_seq"])
        if fav>=activate_r*risk:active=True
        if direction=="long":
            best=max(best,p)
            if active and p<=best-trail_points:return(p-entry)/risk,int(row["_seq"])
        else:
            best=min(best,p)
            if active and p>=best+trail_points:return(entry-p)/risk,int(row["_seq"])
    last=float(path["price"].iloc[-1]);return _directional_move(last,entry,direction)/risk,int(path["_seq"].iloc[-1])


def _r_trail(path,entry,risk,direction,trail_r=.5,activate_r=1.0):return _fixed_trail(path,entry,risk,direction,trail_r*risk,activate_r)


def _partial_runner(path,entry,risk,direction,partial_r=1.0,runner_trail_r=.75,partial_weight=.5):
    if path.empty:return 0.0,None
    partial_hit=False;best=entry
    for _,row in path.iterrows():
        p=float(row["price"]);fav=_directional_move(p,entry,direction);adv=_stop_move(p,entry,direction)
        if not partial_hit and adv>=risk:return-1.0,int(row["_seq"])
        if not partial_hit and fav>=partial_r*risk:partial_hit=True;best=p;continue
        if partial_hit:
            if direction=="long":
                best=max(best,p)
                if p<=best-runner_trail_r*risk:return partial_weight*partial_r+(1-partial_weight)*(p-entry)/risk,int(row["_seq"])
            else:
                best=min(best,p)
                if p>=best+runner_trail_r*risk:return partial_weight*partial_r+(1-partial_weight)*(entry-p)/risk,int(row["_seq"])
    last=float(path["price"].iloc[-1]);runner=_directional_move(last,entry,direction)/risk
    return(partial_weight*partial_r+(1-partial_weight)*runner if partial_hit else runner),int(path["_seq"].iloc[-1])


def management_suite(path,entry,risk,direction):
    out={}
    for r in(.75,1.0,2.0,3.0):
        rr,seq=_fixed_target(path,entry,risk,direction,r);out[f"fixed_{r:g}R"]={"r":rr,"exit_seq":seq}
    for pts in(6,8,12,16):
        rr,seq=_fixed_trail(path,entry,risk,direction,pts,1.0);out[f"trail_{pts}pt"]={"r":rr,"exit_seq":seq}
    for tr in(.5,.75,1.0):
        rr,seq=_r_trail(path,entry,risk,direction,tr,1.0);out[f"trail_{tr:g}R"]={"r":rr,"exit_seq":seq}
    rr,seq=_partial_runner(path,entry,risk,direction,1.0,.75,.5);out["partial_1R_runner_0.75R"]={"r":rr,"exit_seq":seq};return out


def compute_outcomes(db:Path,root:Path,years=None,max_after_days=1):
    con=connect(db);migrate_v4_schema(con);where=["json_extract(features_json,'$.terminal_signal')=1"];args=[]
    if years:q=",".join("?" for _ in years);where.append(f"year IN ({q})");args.extend([int(y) for y in years])
    rows=con.execute("SELECT * FROM events WHERE "+" AND ".join(where)+" ORDER BY trading_date,attempt_start_seq",args).fetchall();now=datetime.now(timezone.utc).isoformat();done=0
    for r in rows:
        e=_event_row(r);entry_seq=e.get("entry_seq") or e["features"].get("terminal_entry_seq");entry=e.get("entry_price") or e["features"].get("terminal_entry_price");stop=e.get("stop")
        if entry_seq is None or entry is None or stop is None:continue
        risk=abs(float(entry)-float(stop))
        if risk<=0:continue
        path=read_tick_path(root,e,int(entry_seq),max_after_days);hits=_simulate_first_hits(path,float(entry),risk,e["direction"]);suite=management_suite(path,float(entry),risk,e["direction"])
        con.execute("""INSERT OR REPLACE INTO opportunity_outcomes(event_id,strategy,direction,entry_seq,entry_time,entry_price,risk_points,mfe_points,mae_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,hit_stop,first_hit_1r,first_hit_2r,first_hit_3r,bars_end_time,management_json,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(e["event_id"],e["strategy"],e["direction"],int(entry_seq),e.get("entry_time"),float(entry),risk,hits.get("mfe_points"),hits.get("mae_points"),hits.get("mfe_r"),hits.get("mae_r"),int(bool(hits.get("hit_1r"))),int(bool(hits.get("hit_2r"))),int(bool(hits.get("hit_3r"))),int(bool(hits.get("hit_stop"))),hits.get("first_hit_1r"),hits.get("first_hit_2r"),hits.get("first_hit_3r"),str(path["dt"].iloc[-1]) if not path.empty else None,json.dumps(suite,ensure_ascii=False),now));done+=1
        if done%50==0:con.commit()
    con.commit();con.close();return done


def _avg(vals):
    vals=[float(x) for x in vals if x is not None and math.isfinite(float(x))];return sum(vals)/len(vals) if vals else None


def reverse_node_audit(db:Path,years=None,audit_id=None):
    con=connect(db);migrate_v4_schema(con);audit_id=audit_id or f"v4-{uuid.uuid4().hex[:8]}";where=["json_extract(e.features_json,'$.terminal_signal')=1"];args=[]
    if years:q=",".join("?" for _ in years);where.append(f"e.year IN ({q})");args.extend([int(y) for y in years])
    rows=con.execute("SELECT e.*,o.mfe_r,o.mae_r,o.hit_1r,o.hit_2r,o.hit_3r,o.hit_stop FROM events e JOIN opportunity_outcomes o ON o.event_id=e.event_id WHERE "+" AND ".join(where),args).fetchall();by_strategy={"MR":[],"BO":[]}
    for r in rows:
        e=_event_row(r);e.update({k:r[k] for k in("mfe_r","mae_r","hit_1r","hit_2r","hit_3r","hit_stop")});e["meta"]=_node_meta(con,e["event_id"])
        if e["strategy"] in by_strategy:by_strategy[e["strategy"]].append(e)
    now=datetime.now(timezone.utc).isoformat();output=[]
    for strategy,items in by_strategy.items():
        chain=MR_CHAIN if strategy=="MR" else BO_CHAIN
        for node in chain:
            rows2=[x for x in items if node in x["meta"]]
            if not rows2:continue
            passed=[x for x in rows2 if x["meta"][node]["answer"]];failed=[x for x in rows2 if not x["meta"][node]["answer"]];bigw=[x for x in rows2 if float(x.get("mfe_r") or 0)>=2.0];bigl=[x for x in rows2 if float(x.get("mae_r") or 0)>=1.0 and not bool(x.get("hit_2r"))];bw_kept=sum(1 for x in bigw if x["meta"][node]["answer"]);bl_rej=sum(1 for x in bigl if not x["meta"][node]["answer"]);parent=PARENTS.get(node);same=0;den=0
            if parent:
                for x in rows2:
                    a=x["meta"].get(node,{}).get("decision_seq");b=x["meta"].get(parent,{}).get("decision_seq")
                    if a is not None and b is not None:den+=1;same+=int(a==b)
            bl_rate=bl_rej/len(bigl) if bigl else 0.0;bw_reject=(len(bigw)-bw_kept)/len(bigw) if bigw else 0.0;score=bl_rate-bw_reject
            rec={"audit_id":audit_id,"node_id":node,"strategy":strategy,"universe":len(rows2),"pass_count":len(passed),"fail_count":len(failed),"big_winners":len(bigw),"big_winners_kept":bw_kept,"big_winners_rejected":len(bigw)-bw_kept,"big_losers":len(bigl),"big_losers_rejected":bl_rej,"big_losers_kept":len(bigl)-bl_rej,"pass_avg_mfe_r":_avg([x.get("mfe_r") for x in passed]),"fail_avg_mfe_r":_avg([x.get("mfe_r") for x in failed]),"pass_avg_mae_r":_avg([x.get("mae_r") for x in passed]),"fail_avg_mae_r":_avg([x.get("mae_r") for x in failed]),"pass_2r_rate":sum(bool(x.get("hit_2r")) for x in passed)/len(passed) if passed else None,"fail_2r_rate":sum(bool(x.get("hit_2r")) for x in failed)/len(failed) if failed else None,"same_seq_parent_rate":same/den if den else None,"filter_score":score}
            details={"big_loss_rejection_rate":bl_rate,"big_win_rejection_rate":bw_reject,"interpretation":"positive score means the gate rejects large losers more often than it kills >=2R opportunities","universe":"ungated terminal opportunities (shadow downstream construction)"}
            con.execute("""INSERT OR REPLACE INTO node_edge_audit(audit_id,node_id,strategy,universe,pass_count,fail_count,big_winners,big_winners_kept,big_winners_rejected,big_losers,big_losers_rejected,big_losers_kept,pass_avg_mfe_r,fail_avg_mfe_r,pass_avg_mae_r,fail_avg_mae_r,pass_2r_rate,fail_2r_rate,same_seq_parent_rate,filter_score,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(rec["audit_id"],rec["node_id"],rec["strategy"],rec["universe"],rec["pass_count"],rec["fail_count"],rec["big_winners"],rec["big_winners_kept"],rec["big_winners_rejected"],rec["big_losers"],rec["big_losers_rejected"],rec["big_losers_kept"],rec["pass_avg_mfe_r"],rec["fail_avg_mfe_r"],rec["pass_avg_mae_r"],rec["fail_avg_mae_r"],rec["pass_2r_rate"],rec["fail_2r_rate"],rec["same_seq_parent_rate"],rec["filter_score"],json.dumps(details,ensure_ascii=False),now));rec["details"]=details;output.append(rec)
    con.commit();con.close();return{"audit_id":audit_id,"rows":output}


def ablation_audit(db:Path,years=None):
    con=connect(db);migrate_v4_schema(con);where=["json_extract(e.features_json,'$.terminal_signal')=1"];args=[]
    if years:q=",".join("?" for _ in years);where.append(f"e.year IN ({q})");args.extend([int(y) for y in years])
    rows=con.execute("SELECT e.event_id,e.strategy,o.hit_2r,o.mfe_r,o.mae_r FROM events e JOIN opportunity_outcomes o ON o.event_id=e.event_id WHERE "+" AND ".join(where),args).fetchall();result={}
    for strategy in("MR","BO"):
        chain=MR_CHAIN if strategy=="MR" else BO_CHAIN;items=[r for r in rows if r["strategy"]==strategy];metas={r["event_id"]:_node_meta(con,r["event_id"]) for r in items}
        def subset(required):return[r for r in items if all(metas[r["event_id"]].get(n,{}).get("answer") for n in required)]
        full=subset(chain);rows_out=[]
        for removed in[None]+chain:
            req=chain if removed is None else[n for n in chain if n!=removed];sub=subset(req);rows_out.append({"removed":removed or "NONE","n":len(sub),"hit_2r_rate":sum(bool(r["hit_2r"]) for r in sub)/len(sub) if sub else None,"avg_mfe_r":_avg([r["mfe_r"] for r in sub]),"avg_mae_r":_avg([r["mae_r"] for r in sub]),"added_vs_full":len(sub)-len(full)})
        result[strategy]=rows_out
    con.close();return result
