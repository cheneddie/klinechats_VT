from __future__ import annotations
import json,random,uuid
from pathlib import Path
from .storage import connect,migrate_event_db,migrate_training_db,tx,utcnow

def start_certification(training_db:str|Path,event_db:str|Path,*,user_id:str,run_id:str,node_id:str|None=None,count:int=50,seed:int|None=None):
    migrate_training_db(training_db);migrate_event_db(event_db)
    ec=connect(event_db);tc=connect(training_db)
    try:
        sql="SELECT t.*,e.trading_date FROM training_cases t JOIN events e ON e.research_run_id=t.research_run_id AND e.event_id=t.event_id WHERE t.research_run_id=? AND t.training_split='CERTIFICATION'";args=[run_id]
        if node_id:sql+=' AND t.node_id=?';args.append(node_id)
        pool=[dict(r) for r in ec.execute(sql,args).fetchall()]
        seen={(r['event_id'],r['node_id']) for r in tc.execute('SELECT event_id,node_id FROM training_attempts WHERE user_id=?',(user_id,)).fetchall()}
        pool=[x for x in pool if (x['event_id'],x['node_id']) not in seen]
    finally:ec.close();tc.close()
    rng=random.Random(seed if seed is not None else f'{user_id}|{run_id}|{node_id}');rng.shuffle(pool)
    picked=[];days=set()
    for x in pool:
        key=(x['trading_date'],x['node_id'])
        if key in days:continue
        days.add(key);picked.append(x)
        if len(picked)>=max(1,min(500,int(count))):break
    cid='cert-'+uuid.uuid4().hex[:12]
    with tx(training_db) as c:
        c.execute('INSERT INTO certification_attempts VALUES(?,?,?,?,?,?,?,?,?)',(cid,user_id,run_id,node_id,'RUNNING',utcnow(),None,json.dumps({'requested':count,'natural_frequency':True,'never_seen':True,'hide_future':True,'no_structure_hint':True}), '{}'))
        c.executemany('INSERT INTO certification_items(certification_id,position,event_id,node_id,machine_answer) VALUES(?,?,?,?,?)',[(cid,i,x['event_id'],x['node_id'],x['machine_answer']) for i,x in enumerate(picked)])
    return {'certification_id':cid,'items':len(picked),'never_seen':True,'natural_frequency':True}

def next_item(training_db,cid):
    c=connect(training_db)
    try:r=c.execute('SELECT position,event_id,node_id FROM certification_items WHERE certification_id=? AND human_answer IS NULL ORDER BY position LIMIT 1',(cid,)).fetchone();return dict(r) if r else None
    finally:c.close()

def answer(training_db,cid,position,human_answer,confidence,reaction_ms):
    h=str(human_answer).upper()
    if h not in {'YES','NO','WAIT'}:raise ValueError('answer must be YES/NO/WAIT')
    with tx(training_db) as c:
        r=c.execute('SELECT * FROM certification_items WHERE certification_id=? AND position=?',(cid,int(position))).fetchone()
        if not r:raise KeyError('certification item not found')
        if r['human_answer'] is not None:raise ValueError('item already answered')
        truth=bool(r['machine_answer']);correct=(h=='YES')==truth if h in {'YES','NO'} else False
        c.execute('UPDATE certification_items SET human_answer=?,confidence=?,reaction_ms=?,correct=?,answered_at=? WHERE certification_id=? AND position=?',(h,int(confidence),int(reaction_ms),int(correct),utcnow(),cid,int(position)))
    return {'correct':correct}

def finish(training_db,cid):
    with tx(training_db) as c:
        a=c.execute('SELECT * FROM certification_attempts WHERE certification_id=?',(cid,)).fetchone()
        if not a:raise KeyError(cid)
        rows=[dict(r) for r in c.execute('SELECT * FROM certification_items WHERE certification_id=? ORDER BY position',(cid,)).fetchall()]
        answered=[x for x in rows if x['human_answer'] is not None];n=len(answered);correct=sum(int(x['correct'] or 0) for x in answered)
        false_entries=sum(x['human_answer']=='YES' and not bool(x['machine_answer']) for x in answered);missed=sum(x['human_answer']=='NO' and bool(x['machine_answer']) for x in answered);waits=[x for x in answered if x['human_answer']=='WAIT']
        rts=sorted(int(x['reaction_ms'] or 0) for x in answered);median=rts[len(rts)//2] if rts else None;by_node={}
        for x in answered:
            d=by_node.setdefault(x['node_id'],[0,0]);d[0]+=1;d[1]+=int(x['correct'] or 0)
        result={'answered':n,'total':len(rows),'accuracy':correct/n if n else None,'false_entry_rate':false_entries/n if n else None,'missed_entry_rate':missed/n if n else None,'wait_answers':len(waits),'median_reaction_ms':median,'node_accuracy':{k:v[1]/v[0] for k,v in by_node.items()}}
        c.execute('UPDATE certification_attempts SET status=?,finished_at=?,result_json=? WHERE certification_id=?',('DONE',utcnow(),json.dumps(result,ensure_ascii=False),cid))
    return result
