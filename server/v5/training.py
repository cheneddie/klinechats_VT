from __future__ import annotations
import json,math,random,uuid,hashlib
from datetime import datetime,timedelta,timezone
from .registry import NodeRegistry,TRAINING_STATUSES
from .storage import connect,migrate_event_db,migrate_training_db,tx,utcnow

def _sanity_pass(c,run):
    r=c.execute('SELECT status FROM event_sanity_runs WHERE research_run_id=? ORDER BY created_at DESC LIMIT 1',(run,)).fetchone();return bool(r and r['status']=='PASS')
def _flatten_features(event,node):
    out={};f=json.loads(event.get('features_json') or '{}');m=json.loads(node.get('metrics_json') or '{}')
    for k in ('excursion_pct_value','reclaim_seconds','reclaim_points','leg_points','lvn_depth','outside_ratio','acceptance_displacement_pct','entry_extension_vw'):
        v=f.get(k)
        if isinstance(v,(int,float)):out[k]=float(v)
    for k,v in m.items():
        if isinstance(v,(int,float)) and not isinstance(v,bool):out[f'm_{k}']=float(v)
    out['direction_code']=1.0 if event.get('direction')=='long' else -1.0
    return out

def build_training_truth(event_db,run_id,registry:NodeRegistry):
    migrate_event_db(event_db);con=connect(event_db)
    try:
        if not _sanity_pass(con,run_id):raise RuntimeError('training dataset requires EVENT_SANITY_GATE PASS')
        evidence={r['node_id']:dict(r) for r in con.execute('SELECT * FROM node_evidence_registry WHERE research_run_id=?',(run_id,)).fetchall()}
        events={r['event_id']:dict(r) for r in con.execute('SELECT * FROM events WHERE research_run_id=?',(run_id,)).fetchall()};nodes=[dict(r) for r in con.execute('SELECT * FROM event_nodes WHERE research_run_id=?',(run_id,)).fetchall()]
    finally:con.close()
    rows=[]
    for n in nodes:
        node_id=n['node_id'];definition=registry.nodes.get(node_id);ev=evidence.get(node_id)
        if not definition or not definition.training_eligible or not ev or not bool(ev.get('training_eligible')):continue
        event=events[n['event_id']];answer=bool(n['answer']);reason=n.get('reason_code') or ('PASS' if answer else 'FAIL')
        hard=not answer and reason not in {'NO_VALUE_REENTRY','NO_TERMINAL_PULLBACK','NO_RELAXED_TERMINAL_PULLBACK'}
        quality=1.0 if n.get('decision_seq') is not None and n.get('reason_code') else .5
        bucket=int(hashlib.sha256(f"{run_id}|{n['event_id']}|{node_id}".encode()).hexdigest()[:8],16)%10;split='CERTIFICATION' if bucket>=8 else 'TRAIN'
        rows.append((run_id,n['event_id'],node_id,int(answer),reason,'MACHINE_VERIFIED','MACHINE_VERIFIED',ev['evidence_level'],quality,int(event.get('difficulty') or 3),split,int(hard),reason if hard else None,json.dumps(_flatten_features(event,n),ensure_ascii=False)))
    with tx(event_db) as c:
        c.execute('DELETE FROM training_cases WHERE research_run_id=?',(run_id,));c.executemany('''INSERT INTO training_cases(research_run_id,event_id,node_id,machine_answer,machine_reason,semantic_status,human_review_status,evidence_level,case_quality,difficulty,training_split,hard_negative,error_subtype,feature_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',rows)
    return {'research_run_id':run_id,'cases':len(rows),'hard_negatives':sum(r[11] for r in rows),'certification_pool':sum(r[10]=='CERTIFICATION' for r in rows)}

def mine_matched_pairs(event_db,run_id,node_id,limit=500):
    con=connect(event_db)
    try:rows=[dict(r) for r in con.execute('''SELECT t.*,e.trading_date FROM training_cases t JOIN events e ON e.research_run_id=t.research_run_id AND e.event_id=t.event_id WHERE t.research_run_id=? AND t.node_id=? AND t.training_split='TRAIN' ''',(run_id,node_id)).fetchall()]
    finally:con.close()
    yes=[x for x in rows if x['machine_answer']];no=[x for x in rows if not x['machine_answer']]
    features=sorted({k for x in rows for k in json.loads(x['feature_json'] or '{}')});stats={}
    for k in features:
        vals=[json.loads(x['feature_json'] or '{}').get(k) for x in rows];vals=[float(v) for v in vals if isinstance(v,(int,float))];mu=sum(vals)/len(vals) if vals else 0;sd=(sum((v-mu)**2 for v in vals)/len(vals))**.5 if vals else 1;stats[k]=(mu,sd or 1)
    def dist(a,b):
        fa=json.loads(a['feature_json'] or '{}');fb=json.loads(b['feature_json'] or '{}');d=0;n=0;diff={}
        for k,(mu,sd) in stats.items():
            if k in fa and k in fb:
                z=abs(float(fa[k])-float(fb[k]))/sd;d+=z*z;n+=1
                if z>.25:diff[k]=[fa[k],fb[k]]
        return (math.sqrt(d/n) if n else 999),diff
    pairs=[]
    for y in yes:
        choices=[x for x in no if x['event_id']!=y['event_id'] and x.get('trading_date')!=y.get('trading_date')]
        if not choices:continue
        best=None
        for n in choices:
            d,diff=dist(y,n)
            if best is None or d<best[0]:best=(d,n,diff)
        d,n,diff=best;pairs.append((run_id,'pair-'+uuid.uuid4().hex[:12],node_id,y['event_id'],n['event_id'],1/(1+d),json.dumps(diff,ensure_ascii=False)))
        if len(pairs)>=limit:break
    with tx(event_db) as c:
        c.execute('DELETE FROM matched_case_pairs WHERE research_run_id=? AND node_id=?',(run_id,node_id));c.executemany('INSERT INTO matched_case_pairs VALUES(?,?,?,?,?,?,?)',pairs)
    return {'research_run_id':run_id,'node_id':node_id,'pairs':len(pairs)}

def get_cases(event_db,run_id,node_id,*,mode='skill',limit=20,answer=None,hard_negative=None,split='TRAIN'):
    con=connect(event_db)
    try:
        sql='''SELECT t.*,e.trading_date,e.strategy,e.direction,e.difficulty event_difficulty FROM training_cases t JOIN events e ON e.research_run_id=t.research_run_id AND e.event_id=t.event_id WHERE t.research_run_id=? AND t.node_id=? AND t.training_split=?''';args=[run_id,node_id,split]
        if answer is not None:sql+=' AND t.machine_answer=?';args.append(int(bool(answer)))
        if hard_negative is not None:sql+=' AND t.hard_negative=?';args.append(int(bool(hard_negative)))
        rows=[dict(r) for r in con.execute(sql,args).fetchall()]
    finally:con.close()
    rng=random.Random(f'{run_id}|{node_id}|{mode}|{len(rows)}')
    if mode=='skill' and answer is None:
        yes=[x for x in rows if x['machine_answer']];no=[x for x in rows if not x['machine_answer']];n=max(1,limit//2);rng.shuffle(yes);rng.shuffle(no);rows=(yes[:n]+no[:n]);rng.shuffle(rows)
    else:rng.shuffle(rows);rows=rows[:limit]
    return rows[:limit]

def matched_pairs(event_db,run_id,node_id,limit=100):
    con=connect(event_db)
    try:return [dict(r) for r in con.execute('SELECT * FROM matched_case_pairs WHERE research_run_id=? AND node_id=? ORDER BY similarity_score DESC LIMIT ?',(run_id,node_id,limit)).fetchall()]
    finally:con.close()

def _due(conf,correct):
    if not correct:return utcnow()
    return (datetime.now(timezone.utc)+timedelta(days={1:1,2:2,3:3,4:7,5:14}.get(int(conf),3))).isoformat()

def record_attempt(training_db,event_db,*,user_id,run_id,event_id,node_id,human_answer,confidence,reaction_ms,mode='practice',started_at=None,first_wrong_node=None):
    migrate_training_db(training_db);migrate_event_db(event_db);ec=connect(event_db)
    try:t=ec.execute('SELECT * FROM training_cases WHERE research_run_id=? AND event_id=? AND node_id=?',(run_id,event_id,node_id)).fetchone()
    finally:ec.close()
    if not t:raise KeyError('training case not found')
    truth=bool(t['machine_answer']); h=str(human_answer).upper();correct=(h=='YES')==truth if h in {'YES','NO'} else False;error=None if correct else (t['error_subtype'] or 'CLASSIFICATION_ERROR');aid='att-'+uuid.uuid4().hex[:12];now=utcnow();conf=max(1,min(5,int(confidence)))
    with tx(training_db) as c:
        c.execute('INSERT INTO training_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(aid,user_id,run_id,event_id,node_id,mode,int(truth),h,int(correct),conf,int(reaction_ms),error,first_wrong_node,started_at,now))
        r=c.execute('SELECT * FROM user_mastery WHERE user_id=? AND node_id=?',(user_id,node_id)).fetchone();vals=dict(r) if r else {'attempts':0,'correct':0,'hard_negative_attempts':0,'hard_negative_correct':0,'false_entries':0,'missed_entries':0,'total_reaction_ms':0,'confidence_error':0}
        vals['attempts']+=1;vals['correct']+=int(correct);vals['hard_negative_attempts']+=int(bool(t['hard_negative']));vals['hard_negative_correct']+=int(bool(t['hard_negative']) and correct);vals['false_entries']+=int(h=='YES' and not truth);vals['missed_entries']+=int(h=='NO' and truth);vals['total_reaction_ms']+=int(reaction_ms);vals['confidence_error']+=((conf/5)-(1 if correct else 0))**2
        c.execute('''INSERT OR REPLACE INTO user_mastery(user_id,node_id,attempts,correct,hard_negative_attempts,hard_negative_correct,false_entries,missed_entries,total_reaction_ms,confidence_error,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(user_id,node_id,vals['attempts'],vals['correct'],vals['hard_negative_attempts'],vals['hard_negative_correct'],vals['false_entries'],vals['missed_entries'],vals['total_reaction_ms'],vals['confidence_error'],now))
        sr=c.execute('SELECT * FROM spaced_repetition WHERE user_id=? AND event_id=? AND node_id=?',(user_id,event_id,node_id)).fetchone();s=dict(sr) if sr else {'times_seen':0,'correct_streak':0,'incorrect_count':0};s['times_seen']+=1;s['correct_streak']=s['correct_streak']+1 if correct else 0;s['incorrect_count']+=int(not correct)
        c.execute('INSERT OR REPLACE INTO spaced_repetition VALUES(?,?,?,?,?,?,?,?)',(user_id,event_id,node_id,now,s['times_seen'],s['correct_streak'],s['incorrect_count'],_due(conf,correct)))
        if not correct:c.execute('INSERT INTO mistake_queue VALUES(?,?,?,?,?,?,?,?,?)',('mist-'+uuid.uuid4().hex[:12],user_id,run_id,event_id,node_id,error,float(conf*10+(10 if t['hard_negative'] else 0)),utcnow(),0,now))
    return {'attempt_id':aid,'correct':correct,'machine_answer':'YES' if truth else 'NO','error_type':error}

def mastery(training_db,user_id):
    migrate_training_db(training_db);c=connect(training_db)
    try:rows=[dict(r) for r in c.execute('SELECT * FROM user_mastery WHERE user_id=? ORDER BY node_id',(user_id,)).fetchall()]
    finally:c.close()
    for x in rows:
        x['accuracy']=x['correct']/x['attempts'] if x['attempts'] else None;x['hard_negative_accuracy']=x['hard_negative_correct']/x['hard_negative_attempts'] if x['hard_negative_attempts'] else None;x['avg_reaction_ms']=x['total_reaction_ms']/x['attempts'] if x['attempts'] else None;x['confidence_calibration']=1-(x['confidence_error']/x['attempts']) if x['attempts'] else None
    return rows

def mistakes(training_db,user_id,limit=100):
    c=connect(training_db)
    try:return [dict(r) for r in c.execute('SELECT * FROM mistake_queue WHERE user_id=? AND resolved=0 ORDER BY priority DESC,created_at LIMIT ?',(user_id,limit)).fetchall()]
    finally:c.close()

def review_case(training_db,event_db,*,run_id,event_id,node_id,reviewer_id,faithful,status,notes=''):
    if status not in TRAINING_STATUSES:raise ValueError('invalid training status')
    rid='rev-'+uuid.uuid4().hex[:12];migrate_training_db(training_db)
    with tx(training_db) as c:c.execute('INSERT INTO case_reviews VALUES(?,?,?,?,?,?,?,?,?)',(rid,run_id,event_id,node_id,reviewer_id,int(bool(faithful)),status,notes,utcnow()))
    with tx(event_db) as c:c.execute('UPDATE training_cases SET human_review_status=?,semantic_status=? WHERE research_run_id=? AND event_id=? AND node_id=?',(status,status,run_id,event_id,node_id))
    return {'review_id':rid,'status':status}
