from __future__ import annotations
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.v5.registry import NodeRegistry,NodeDefinition
from server.v5.storage import create_research_run,tx
from server.v5.sanity import run_event_sanity
from server.v5.research import reverse_audit,sequential_contribution,ablation,build_evidence
from server.v5.training import build_training_truth,get_cases,mine_matched_pairs,record_attempt,mastery
from server.v5.certification import start_certification,next_item,answer,finish

def reg():
    nodes={};roles={'AUC_ATTEMPT':'STATE','MR_REJECTION':'EDGE_GATE','MR_CLEAR_RECLAIM':'EDGE_GATE','MR_RECLAIM_LEG':'STATE','MR_LVN':'EDGE_GATE','MR_PULLBACK':'EDGE_GATE','MR_ENTRY':'EXECUTION_GATE','BO_DISPLACEMENT':'EDGE_GATE','BO_ACCEPTANCE':'EDGE_GATE','BO_IMPULSE_LEG':'STATE','BO_LVN':'EDGE_GATE','BO_PULLBACK':'EDGE_GATE','BO_RESPONSE':'EDGE_GATE','BO_ENTRY':'EXECUTION_GATE'};parent=None
    for n,r in roles.items():
        nodes[n]=NodeDefinition(n,'BO' if n.startswith('BO_') else 'MR',r,parent,{'zh_TW':n},('PASS',),('FAIL','HARD_FAIL'),{},True,False);parent=n
    return NodeRegistry(nodes)

def seed(db):
    create_research_run(db,'r1','DISCOVERY',[2025],scanner_version='V4.1');rows=[];nodes=[];outs=[]
    for i in range(60):
        eid=f'E{i:03d}'; yes=i%2==0; day=f'2025-01-{1+(i%28):02d}'
        rows.append(('r1',eid,'fake.parquet',2025,day,'202501','MR','long','ENTRY',2,i*100,f'{day}T09:00:00',i*100+10,f'{day}T09:01:00',100.0,94.0,106.0,'{}','{}','{}'))
        chain=['AUC_ATTEMPT','MR_REJECTION','MR_CLEAR_RECLAIM','MR_RECLAIM_LEG','MR_LVN','MR_PULLBACK','MR_ENTRY']
        for j,n in enumerate(chain):
            ans=True if n in {'AUC_ATTEMPT','MR_RECLAIM_LEG'} else yes
            nodes.append(('r1',eid,n,int(ans),i*100+j,f'{day}T09:00:{j:02d}',100+j,i*100+j,f'{day}T09:00:{j:02d}',100+j,None,None,None,None,'PASS' if ans else 'HARD_FAIL','{}'))
        rr=1.2 if yes else -0.7
        outs.append(('r1',eid,'terminal',i*100+10,f'{day}T09:01:00',100.0,94.0,1.0,6.0,8.0 if yes else 1.0,5.0 if not yes else 1.0,1.33 if yes else .16,.83 if not yes else .16,int(yes),int(yes),int(yes),0,int(not yes),int(yes),rr,.75 if yes else 0,'{}','now'))
    with tx(db) as c:
        c.executemany('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',rows);c.executemany('INSERT INTO event_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',nodes);c.executemany('INSERT INTO opportunity_outcomes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',outs)

def test_v5_full_research_training_certification_flow():
    with tempfile.TemporaryDirectory() as td:
        event=Path(td)/'events.sqlite3';training=Path(td)/'training.sqlite3';seed(event);r=reg()
        try:create_research_run(event,'r1','DISCOVERY',[2025]);assert False
        except ValueError:pass
        sane=run_event_sanity(event,td,'r1',physical_validate=False);assert sane['status']=='PASS'
        assert reverse_audit(event,'r1',r)['rows'];assert sequential_contribution(event,'r1')['rows'];assert any(x['variant']=='FULL' for x in ablation(event,'r1')['rows'])
        ev=build_evidence(event,'r1',r);assert any(x['training_eligible'] for x in ev['items']);assert build_training_truth(event,'r1',r)['cases']>0
        with tx(event) as c:c.execute("UPDATE training_cases SET training_split='CERTIFICATION' WHERE CAST(substr(event_id,2) AS INTEGER)%5=0")
        cases=get_cases(event,'r1','MR_LVN',mode='skill',limit=20);assert cases and any(x['machine_answer'] for x in cases) and any(not x['machine_answer'] for x in cases)
        mine_matched_pairs(event,'r1','MR_LVN')
        a=record_attempt(training,event,user_id='u',run_id='r1',event_id=cases[0]['event_id'],node_id='MR_LVN',human_answer='YES' if cases[0]['machine_answer'] else 'NO',confidence=4,reaction_ms=900);assert a['correct'];assert mastery(training,'u')[0]['accuracy']==1.0
        cert=start_certification(training,event,user_id='new-user',run_id='r1',node_id='MR_LVN',count=3,seed=1);assert cert['items']>0;item=next_item(training,cert['certification_id']);assert item;answer(training,cert['certification_id'],item['position'],'YES',3,1000);assert finish(training,cert['certification_id'])['answered']==1

def test_holdout_governance_and_schema_split():
    from server.v5.snapshot import validate_governance
    assert validate_governance('DISCOVERY',[2025])=='DISCOVERY'
    for role,years in [('DISCOVERY',[2026]),('VALIDATION',[2025]),('FINAL_HOLDOUT',[2024])]:
        try:validate_governance(role,years);assert False
        except ValueError:pass
