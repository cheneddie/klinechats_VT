from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from .storage import connect, create_research_run, tx

ROLE_YEARS={"DISCOVERY":{2025},"VALIDATION":{2024},"FINAL_HOLDOUT":{2026}}

def validate_governance(role:str, years:list[int]|tuple[int,...]):
    role=role.upper(); ys={int(y) for y in years}
    if role not in ROLE_YEARS: raise ValueError(f"unsupported research role: {role}")
    if ys != ROLE_YEARS[role]: raise ValueError(f"{role} must use exactly {sorted(ROLE_YEARS[role])}, got {sorted(ys)}")
    return role

def _json(raw, default):
    try:return json.loads(raw or default)
    except Exception:return json.loads(default)

def snapshot_v4_run(v4_db:str|Path,event_db:str|Path,research_run_id:str,role:str,years:list[int],*,metadata:dict[str,Any]|None=None,include_outcomes:bool=False):
    """Copy V4 causal truth into an immutable V5 run.

    Outcomes are deliberately excluded by default. V5 requires Event Sanity PASS
    before any future path is computed/imported.
    """
    role=validate_governance(role,years); metadata=metadata or {}
    create_research_run(event_db,research_run_id,role,years,**metadata)
    src=connect(v4_db)
    try:
        q=','.join('?' for _ in years)
        events=[dict(r) for r in src.execute(f"SELECT * FROM events WHERE year IN ({q}) ORDER BY source_file,trading_date,attempt_start_seq,event_id",tuple(years)).fetchall()]
        node_cols={r[1] for r in src.execute('PRAGMA table_info(node_instances)').fetchall()}
        wanted=['event_id','node_id','answer','decision_seq','decision_time','decision_price','anchor_seq','anchor_time','anchor_price','start_seq','start_time','end_seq','end_time','reason_code','metrics_json']
        cols=[x for x in wanted if x in node_cols]
        nodes=[]
        if events and cols:
            ids=[e['event_id'] for e in events]
            for i in range(0,len(ids),500):
                chunk=ids[i:i+500]; marks=','.join('?' for _ in chunk)
                nodes.extend(dict(r) for r in src.execute(f"SELECT {','.join(cols)} FROM node_instances WHERE event_id IN ({marks})",chunk).fetchall())
        outcomes=[]
        if include_outcomes:
            out_cols={r[1] for r in src.execute('PRAGMA table_info(opportunity_outcomes)').fetchall()}
            if out_cols and events:
                ids=[e['event_id'] for e in events]
                for i in range(0,len(ids),500):
                    chunk=ids[i:i+500]; marks=','.join('?' for _ in chunk)
                    outcomes.extend(dict(r) for r in src.execute(f"SELECT * FROM opportunity_outcomes WHERE event_id IN ({marks})",chunk).fetchall())
    finally: src.close()
    with tx(event_db) as dst:
        for e in events:
            payload=dict(e); features=_json(e.get('features_json'),'{}'); nodes_json=_json(e.get('nodes_json'),'{}')
            dst.execute('''INSERT INTO events(research_run_id,event_id,source_file,year,trading_date,contract,strategy,direction,result,difficulty,
            attempt_start_seq,attempt_start_time,entry_seq,entry_time,entry_price,stop,target,features_json,nodes_json,payload_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(research_run_id,e['event_id'],e.get('source_file'),e.get('year'),e.get('trading_date'),e.get('contract'),e.get('strategy'),e.get('direction'),e.get('result'),e.get('difficulty'),e.get('attempt_start_seq'),e.get('attempt_start_time'),e.get('entry_seq'),e.get('entry_time'),e.get('entry_price'),e.get('stop'),e.get('target'),json.dumps(features,ensure_ascii=False),json.dumps(nodes_json,ensure_ascii=False),json.dumps(payload,ensure_ascii=False,default=str)))
        for n in nodes:
            dst.execute('''INSERT INTO event_nodes(research_run_id,event_id,node_id,answer,decision_seq,decision_time,decision_price,anchor_seq,anchor_time,anchor_price,start_seq,start_time,end_seq,end_time,reason_code,metrics_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(research_run_id,n.get('event_id'),n.get('node_id'),int(bool(n.get('answer'))),n.get('decision_seq'),n.get('decision_time'),n.get('decision_price'),n.get('anchor_seq'),n.get('anchor_time'),n.get('anchor_price'),n.get('start_seq'),n.get('start_time'),n.get('end_seq'),n.get('end_time'),n.get('reason_code'),n.get('metrics_json') or '{}'))
        if include_outcomes:
            for o in outcomes:
                dst.execute('''INSERT OR IGNORE INTO opportunity_outcomes(research_run_id,event_id,basis,entry_seq,entry_time,entry_price,risk_points,mfe_points,mae_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,management_json,computed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(research_run_id,o.get('event_id'),'terminal',o.get('entry_seq'),o.get('entry_time'),o.get('entry_price'),o.get('risk_points'),o.get('mfe_points'),o.get('mae_points'),o.get('mfe_r'),o.get('mae_r'),o.get('hit_1r'),o.get('hit_2r'),o.get('hit_3r'),o.get('management_json') or '{}',o.get('computed_at') or ''))
    return {'research_run_id':research_run_id,'role':role,'years':years,'events':len(events),'nodes':len(nodes),'imported_outcomes':len(outcomes)}
