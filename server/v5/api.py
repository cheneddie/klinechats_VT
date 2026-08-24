from __future__ import annotations
import os
from pathlib import Path
from pydantic import BaseModel,Field
from . import V5_VERSION
from .certification import answer as cert_answer,finish as cert_finish,next_item as cert_next,start_certification
from .integrity import inspect_root
from .outcomes import compute_outcomes
from .registry import load_registry
from .research import ablation,build_evidence,reverse_audit,sequential_contribution
from .sanity import run_event_sanity
from .snapshot import snapshot_v4_run,validate_governance
from .storage import connect,freeze_run,migrate_event_db,migrate_training_db
from .training import build_training_truth,get_cases,mastery,matched_pairs,mine_matched_pairs,mistakes,record_attempt,review_case

HERE=Path(__file__).resolve().parents[2]
REGISTRY_PATH=Path(os.environ.get('FABIO_V5_NODE_REGISTRY',str(HERE/'config/research/node_registry.yaml')))
EVENT_DB=Path(os.environ.get('FABIO_V5_EVENT_DB',str(Path.home()/'.fabio-decision-gym/fabio-events.sqlite3')))
TRAINING_DB=Path(os.environ.get('FABIO_V5_TRAINING_DB',str(Path.home()/'.fabio-decision-gym/fabio-training.sqlite3')))
REGISTRY=load_registry(REGISTRY_PATH)

class SnapshotRequest(BaseModel):
    research_run_id:str;role:str;years:list[int];git_commit:str|None=None;config_hash:str|None=None;notes:str|None=None
class RunRequest(BaseModel):research_run_id:str
class BuildRequest(BaseModel):research_run_id:str
class AttemptRequest(BaseModel):user_id:str='default';research_run_id:str;event_id:str;node_id:str;human_answer:str;confidence:int=Field(3,ge=1,le=5);reaction_ms:int=Field(0,ge=0);mode:str='practice';started_at:str|None=None;first_wrong_node:str|None=None
class ReviewRequest(BaseModel):research_run_id:str;event_id:str;node_id:str;reviewer_id:str='expert';faithful:bool;status:str;notes:str=''
class CertStart(BaseModel):user_id:str='default';research_run_id:str;node_id:str|None=None;count:int=Field(50,ge=1,le=500)
class CertAnswer(BaseModel):position:int;human_answer:str;confidence:int=Field(3,ge=1,le=5);reaction_ms:int=Field(0,ge=0)

def install(base):
    app=base.app;migrate_event_db(EVENT_DB);migrate_training_db(TRAINING_DB)
    @app.get('/api/v5/health')
    def health():return {'ok':True,'version':V5_VERSION,'event_db':str(EVENT_DB),'training_db':str(TRAINING_DB),'registry_nodes':len(REGISTRY.nodes),'v4_shared_engine':True,'production_gate':'BLOCKED_UNTIL_L5_L6','holdout_governance':{'2025':'DISCOVERY','2024':'VALIDATION','2026':'FINAL_HOLDOUT'}}
    @app.get('/api/v5/data/integrity')
    def integrity(years:str|None=None):return inspect_root(base.ROOT,[int(x) for x in years.split(',')] if years else None)
    @app.get('/api/v5/contracts')
    def contracts():
        c=base.connect(base.DB)
        try:
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if 'contract_selection_audit' not in tables:return {'items':[],'source':'V4','message':'contract audit not populated'}
            return {'items':[dict(r) for r in c.execute('SELECT * FROM contract_selection_audit ORDER BY trading_date DESC LIMIT 2000').fetchall()],'source':'V4'}
        finally:c.close()
    @app.get('/api/v5/nodes')
    def nodes():return REGISTRY.to_dict()
    @app.get('/api/v5/research/runs')
    def runs():
        c=connect(EVENT_DB)
        try:return {'items':[dict(r) for r in c.execute('SELECT * FROM research_runs ORDER BY created_at DESC').fetchall()]}
        finally:c.close()
    @app.post('/api/v5/research/scan')
    def scan(req:SnapshotRequest):
        validate_governance(req.role,req.years)
        return snapshot_v4_run(base.DB,EVENT_DB,req.research_run_id,req.role,req.years,metadata={'git_commit':req.git_commit,'scanner_version':'V4.1_SHARED','strategy_version':'MR_BROAD_V3|BO_RETEST_V2','config_hash':req.config_hash,'contract_policy_version':'STRICT_CALENDAR_FRONT','visual_schema_version':'4','outcome_version':'V5_PHYSICAL_1','audit_version':'V5_REVERSE_1','management_version':'V5_MGMT_1','notes':req.notes},include_outcomes=False)
    @app.post('/api/v5/research/sanity')
    def sanity(req:RunRequest):return run_event_sanity(EVENT_DB,base.ROOT,req.research_run_id,physical_validate=True)
    @app.post('/api/v5/research/outcomes')
    def outcomes(req:RunRequest):return compute_outcomes(EVENT_DB,base.ROOT,req.research_run_id)
    @app.post('/api/v5/research/reverse-audit')
    def reverse(req:RunRequest):return reverse_audit(EVENT_DB,req.research_run_id,REGISTRY)
    @app.post('/api/v5/research/sequential')
    def sequential(req:RunRequest):return sequential_contribution(EVENT_DB,req.research_run_id)
    @app.post('/api/v5/research/ablation')
    def ab(req:RunRequest):return ablation(EVENT_DB,req.research_run_id)
    @app.post('/api/v5/research/evidence')
    def evidence(req:RunRequest):return build_evidence(EVENT_DB,req.research_run_id,REGISTRY)
    @app.post('/api/v5/research/freeze')
    def freeze(req:RunRequest):freeze_run(EVENT_DB,req.research_run_id);return {'ok':True,'research_run_id':req.research_run_id,'frozen':True}
    @app.get('/api/v5/research/evidence')
    def evidence_get(research_run_id:str):
        c=connect(EVENT_DB)
        try:return {'items':[dict(r) for r in c.execute('SELECT * FROM node_evidence_registry WHERE research_run_id=? ORDER BY node_id',(research_run_id,)).fetchall()]}
        finally:c.close()
    @app.get('/api/v5/research/node/{node_id}')
    def node_research(node_id:str,research_run_id:str):
        c=connect(EVENT_DB)
        try:return {'node':REGISTRY.get(node_id).__dict__,'edge':[dict(r) for r in c.execute('SELECT * FROM node_edge_results WHERE research_run_id=? AND node_id=?',(research_run_id,node_id)).fetchall()],'evidence':dict(c.execute('SELECT * FROM node_evidence_registry WHERE research_run_id=? AND node_id=?',(research_run_id,node_id)).fetchone() or {})}
        finally:c.close()
    @app.get('/api/v5/events')
    def events(research_run_id:str,node_id:str|None=None,answer:bool|None=None,limit:int=100,offset:int=0):
        c=connect(EVENT_DB)
        try:
            if node_id:
                sql='SELECT e.* FROM events e JOIN event_nodes n ON n.research_run_id=e.research_run_id AND n.event_id=e.event_id WHERE e.research_run_id=? AND n.node_id=?';args=[research_run_id,node_id]
                if answer is not None:sql+=' AND n.answer=?';args.append(int(answer))
            else:sql='SELECT e.* FROM events e WHERE e.research_run_id=?';args=[research_run_id]
            sql+=' ORDER BY e.trading_date,e.attempt_start_seq LIMIT ? OFFSET ?';args.extend([min(10000,limit),offset]);return {'items':[dict(r) for r in c.execute(sql,args).fetchall()]}
        finally:c.close()
    @app.get('/api/v5/events/{event_id}')
    def event_detail(event_id:str,research_run_id:str):
        c=connect(EVENT_DB)
        try:
            e=c.execute('SELECT * FROM events WHERE research_run_id=? AND event_id=?',(research_run_id,event_id)).fetchone();ns=[dict(r) for r in c.execute('SELECT * FROM event_nodes WHERE research_run_id=? AND event_id=? ORDER BY decision_seq,node_id',(research_run_id,event_id)).fetchall()];outs=[dict(r) for r in c.execute('SELECT * FROM opportunity_outcomes WHERE research_run_id=? AND event_id=?',(research_run_id,event_id)).fetchall()]
            return {'event':dict(e) if e else None,'nodes':ns,'outcomes':outs}
        finally:c.close()
    @app.get('/api/v5/events/{event_id}/nodes')
    def event_nodes(event_id:str,research_run_id:str):
        c=connect(EVENT_DB)
        try:return {'items':[dict(r) for r in c.execute('SELECT * FROM event_nodes WHERE research_run_id=? AND event_id=? ORDER BY decision_seq,node_id',(research_run_id,event_id)).fetchall()]}
        finally:c.close()
    @app.post('/api/v5/training/build')
    def training_build(req:BuildRequest):
        out=build_training_truth(EVENT_DB,req.research_run_id,REGISTRY)
        for node in REGISTRY.nodes:
            try:mine_matched_pairs(EVENT_DB,req.research_run_id,node)
            except Exception:pass
        return out
    @app.get('/api/v5/training/nodes')
    def training_nodes(research_run_id:str):
        c=connect(EVENT_DB)
        try:return {'items':[dict(r) for r in c.execute('''SELECT t.node_id,COUNT(*) total,SUM(t.machine_answer) yes_count,COUNT(*)-SUM(t.machine_answer) no_count,SUM(t.hard_negative) hard_negatives,MAX(t.evidence_level) evidence_level FROM training_cases t WHERE research_run_id=? GROUP BY t.node_id ORDER BY t.node_id''',(research_run_id,)).fetchall()]}
        finally:c.close()
    @app.get('/api/v5/training/cases')
    def training_cases(research_run_id:str,node_id:str,mode:str='skill',limit:int=20,answer:bool|None=None,hard_negative:bool|None=None):return {'items':get_cases(EVENT_DB,research_run_id,node_id,mode=mode,limit=limit,answer=answer,hard_negative=hard_negative)}
    @app.get('/api/v5/training/matched-pairs')
    def pairs(research_run_id:str,node_id:str,limit:int=100):return {'items':matched_pairs(EVENT_DB,research_run_id,node_id,limit)}
    @app.post('/api/v5/training/attempt')
    def attempt(req:AttemptRequest):return record_attempt(TRAINING_DB,EVENT_DB,user_id=req.user_id,run_id=req.research_run_id,event_id=req.event_id,node_id=req.node_id,human_answer=req.human_answer,confidence=req.confidence,reaction_ms=req.reaction_ms,mode=req.mode,started_at=req.started_at,first_wrong_node=req.first_wrong_node)
    @app.post('/api/v5/training/tree-attempt')
    def tree_attempt(req:AttemptRequest):return record_attempt(TRAINING_DB,EVENT_DB,user_id=req.user_id,run_id=req.research_run_id,event_id=req.event_id,node_id=req.node_id,human_answer=req.human_answer,confidence=req.confidence,reaction_ms=req.reaction_ms,mode='tree',started_at=req.started_at,first_wrong_node=req.first_wrong_node)
    @app.get('/api/v5/training/mastery')
    def training_mastery(user_id:str='default'):return {'items':mastery(TRAINING_DB,user_id)}
    @app.get('/api/v5/training/mistakes')
    def training_mistakes(user_id:str='default',limit:int=100):return {'items':mistakes(TRAINING_DB,user_id,limit)}
    @app.post('/api/v5/training/review')
    def review(req:ReviewRequest):return review_case(TRAINING_DB,EVENT_DB,run_id=req.research_run_id,event_id=req.event_id,node_id=req.node_id,reviewer_id=req.reviewer_id,faithful=req.faithful,status=req.status,notes=req.notes)
    @app.post('/api/v5/certification/start')
    def cert_start(req:CertStart):return start_certification(TRAINING_DB,EVENT_DB,user_id=req.user_id,run_id=req.research_run_id,node_id=req.node_id,count=req.count)
    @app.get('/api/v5/certification/{cid}/next')
    def cert_n(cid:str):return {'item':cert_next(TRAINING_DB,cid)}
    @app.post('/api/v5/certification/{cid}/answer')
    def cert_a(cid:str,req:CertAnswer):return cert_answer(TRAINING_DB,cid,req.position,req.human_answer,req.confidence,req.reaction_ms)
    @app.post('/api/v5/certification/{cid}/finish')
    def cert_f(cid:str):return cert_finish(TRAINING_DB,cid)
    return app
