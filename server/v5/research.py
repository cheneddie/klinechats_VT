from __future__ import annotations
import json,math,random
from pathlib import Path
from .registry import NodeRegistry
from .storage import connect,migrate_event_db,tx

MR_CHAIN=['AUC_ATTEMPT','MR_REJECTION','MR_CLEAR_RECLAIM','MR_RECLAIM_LEG','MR_LVN','MR_PULLBACK','MR_ENTRY']
BO_CHAIN=['AUC_ATTEMPT','BO_DISPLACEMENT','BO_ACCEPTANCE','BO_IMPULSE_LEG','BO_LVN','BO_PULLBACK','BO_RESPONSE','BO_ENTRY']

def _avg(v):
    a=[float(x) for x in v if x is not None and math.isfinite(float(x))];return sum(a)/len(a) if a else None
def _pf(v):
    pos=sum(x for x in v if x>0);neg=abs(sum(x for x in v if x<0));return pos/neg if neg else (999.0 if pos else None)
def _bootstrap(a,b,reps=500,seed=42):
    a=[float(x) for x in a if x is not None];b=[float(x) for x in b if x is not None]
    if len(a)<10 or len(b)<10:return (None,None)
    rng=random.Random(seed); vals=[]
    for _ in range(reps):vals.append(sum(rng.choice(a) for _ in a)/len(a)-sum(rng.choice(b) for _ in b)/len(b))
    vals.sort();return vals[int(.025*(len(vals)-1))],vals[int(.975*(len(vals)-1))]

def _dataset(con,run_id,strategy):
    rows=con.execute('''SELECT e.event_id,e.strategy,e.year,e.trading_date,o.realized_r,o.hit_1r,o.hit_2r,o.hit_3r,o.hit_5r,o.stop_first,o.mfe_r,o.mae_r
      FROM events e JOIN opportunity_outcomes o ON o.research_run_id=e.research_run_id AND o.event_id=e.event_id AND o.basis='terminal'
      WHERE e.research_run_id=? AND e.strategy=?''',(run_id,strategy)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); ns=con.execute('SELECT node_id,answer,decision_seq FROM event_nodes WHERE research_run_id=? AND event_id=?',(run_id,d['event_id'])).fetchall()
        d['nodes']={x['node_id']:{'answer':bool(x['answer']),'decision_seq':x['decision_seq']} for x in ns};out.append(d)
    return out

def _classify(role,metric,registry_role):
    if registry_role=='STATE':return 'STATE'
    n=metric['universe'];delta=metric['delta_avg_r'];ret=metric['big_winner_retention'];rej=metric['big_loser_rejection'];same=metric['same_seq_parent_rate']
    if n<50:return 'INSUFFICIENT'
    if same is not None and same>=.8 and abs(delta or 0)<.05 and abs((rej or 0)-(1-(ret or 1)))<.05:return 'REDUNDANT'
    if delta is not None and delta<=-.15:return 'HARMFUL'
    if delta is not None and delta>0 and (rej or 0)>=.15:return 'CORE' if role in {'VALIDATION','FINAL_HOLDOUT'} else 'OPTIONAL'
    return 'OPTIONAL'

def reverse_audit(event_db:str|Path,run_id:str,registry:NodeRegistry):
    migrate_event_db(event_db);con=connect(event_db)
    try:
        rr=con.execute('SELECT role FROM research_runs WHERE research_run_id=?',(run_id,)).fetchone();role=rr['role'] if rr else 'DISCOVERY'; results=[]
        for strategy,chain in [('MR',MR_CHAIN),('BO',BO_CHAIN)]:
            data=_dataset(con,run_id,strategy)
            for node_id in chain:
                parent=registry.get(node_id).parent; eligible=[x for x in data if node_id in x['nodes']]
                yes=[x for x in eligible if x['nodes'][node_id]['answer']];no=[x for x in eligible if not x['nodes'][node_id]['answer']]
                yr=[x['realized_r'] for x in yes];nr=[x['realized_r'] for x in no];delta=(_avg(yr)-_avg(nr)) if _avg(yr) is not None and _avg(nr) is not None else None
                big=[x for x in eligible if x.get('hit_2r')];los=[x for x in eligible if x.get('stop_first') and not x.get('hit_1r')]
                ret=sum(x['nodes'][node_id]['answer'] for x in big)/len(big) if big else None;rej=sum(not x['nodes'][node_id]['answer'] for x in los)/len(los) if los else None
                rvals=[float(x.get('realized_r') or 0) for x in no];same_vals=[]
                if parent:
                    for x in eligible:
                        if parent in x['nodes'] and x['nodes'][parent]['decision_seq'] is not None and x['nodes'][node_id]['decision_seq'] is not None:same_vals.append(x['nodes'][parent]['decision_seq']==x['nodes'][node_id]['decision_seq'])
                lo,hi=_bootstrap(yr,nr,seed=sum(map(ord,node_id)))
                metric={'research_run_id':run_id,'node_id':node_id,'strategy':strategy,'universe':len(eligible),'yes_n':len(yes),'no_n':len(no),'yes_avg_r':_avg(yr),'no_avg_r':_avg(nr),'delta_avg_r':delta,'ci_low':lo,'ci_high':hi,'same_seq_parent_rate':sum(same_vals)/len(same_vals) if same_vals else None,'big_winner_retention':ret,'big_loser_rejection':rej,'rejected_total_r':sum(rvals),'rejected_positive_r':sum(x for x in rvals if x>0),'rejected_negative_r':sum(x for x in rvals if x<0)}
                metric['classification']=_classify(role,metric,registry.get(node_id).role);results.append(metric)
    finally:con.close()
    with tx(event_db) as c:
        for x in results:
            c.execute('''INSERT OR REPLACE INTO node_edge_results(research_run_id,node_id,strategy,classification,universe,yes_n,no_n,yes_avg_r,no_avg_r,delta_avg_r,ci_low,ci_high,same_seq_parent_rate,big_winner_retention,big_loser_rejection,rejected_total_r,rejected_positive_r,rejected_negative_r,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(*[x[k] for k in ['research_run_id','node_id','strategy','classification','universe','yes_n','no_n','yes_avg_r','no_avg_r','delta_avg_r','ci_low','ci_high','same_seq_parent_rate','big_winner_retention','big_loser_rejection','rejected_total_r','rejected_positive_r','rejected_negative_r']],json.dumps({'opportunity_cost_included':True},ensure_ascii=False)))
    return {'research_run_id':run_id,'rows':results}

def sequential_contribution(event_db,run_id):
    con=connect(event_db);rows=[]
    try:
        for strategy,chain in [('MR',MR_CHAIN),('BO',BO_CHAIN)]:
            data=_dataset(con,run_id,strategy);prev=[];pn=0;pavg=ptotal=0.0
            for i,node in enumerate(chain,1):
                prev.append(node);kept=[x for x in data if all(x['nodes'].get(n,{}).get('answer') for n in prev)];vals=[float(x.get('realized_r') or 0) for x in kept];avg=_avg(vals) or 0.0;total=sum(vals)
                rows.append({'strategy':strategy,'step_no':i,'node_id':node,'n':len(kept),'avg_r':avg,'total_r':total,'delta_n':len(kept)-pn,'delta_avg_r':avg-pavg,'delta_total_r':total-ptotal});pn=len(kept);pavg=avg;ptotal=total
    finally:con.close()
    with tx(event_db) as c:
        for x in rows:c.execute('''INSERT OR REPLACE INTO sequential_results(research_run_id,strategy,step_no,node_id,n,avg_r,total_r,delta_n,delta_avg_r,delta_total_r,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(run_id,x['strategy'],x['step_no'],x['node_id'],x['n'],x['avg_r'],x['total_r'],x['delta_n'],x['delta_avg_r'],x['delta_total_r'],'{}'))
    return {'research_run_id':run_id,'rows':rows}

def ablation(event_db,run_id):
    con=connect(event_db);out=[]
    try:
        for strategy,chain in [('MR',MR_CHAIN),('BO',BO_CHAIN)]:
            data=_dataset(con,run_id,strategy)
            for removed in [None]+chain:
                gates=[n for n in chain if n!=removed];kept=[x for x in data if all(x['nodes'].get(n,{}).get('answer') for n in gates)];vals=[float(x.get('realized_r') or 0) for x in kept]
                rec={'strategy':strategy,'variant':'FULL' if removed is None else f'FULL - {removed}','n':len(vals),'avg_r':_avg(vals),'total_r':sum(vals),'pf':_pf(vals),'hit_1r_rate':sum(bool(x.get('hit_1r')) for x in kept)/len(kept) if kept else None,'hit_2r_rate':sum(bool(x.get('hit_2r')) for x in kept)/len(kept) if kept else None,'hit_3r_rate':sum(bool(x.get('hit_3r')) for x in kept)/len(kept) if kept else None,'hit_5r_rate':sum(bool(x.get('hit_5r')) for x in kept)/len(kept) if kept else None};out.append(rec)
    finally:con.close()
    with tx(event_db) as c:
        for x in out:c.execute('''INSERT OR REPLACE INTO ablation_results(research_run_id,strategy,variant,n,avg_r,total_r,pf,hit_1r_rate,hit_2r_rate,hit_3r_rate,hit_5r_rate,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(run_id,x['strategy'],x['variant'],x['n'],x['avg_r'],x['total_r'],x['pf'],x['hit_1r_rate'],x['hit_2r_rate'],x['hit_3r_rate'],x['hit_5r_rate'],'{}'))
    return {'research_run_id':run_id,'rows':out}

def build_evidence(event_db,run_id,registry:NodeRegistry):
    con=connect(event_db);items=[]
    try:
        rr=con.execute('SELECT role,years_json FROM research_runs WHERE research_run_id=?',(run_id,)).fetchone()
        if not rr:raise KeyError(run_id)
        role=rr['role']; edges=[dict(r) for r in con.execute('SELECT * FROM node_edge_results WHERE research_run_id=?',(run_id,)).fetchall()];emap={x['node_id']:x for x in edges}
        for node_id,node in registry.items():
            e=emap.get(node_id,{});n=int(e.get('universe') or 0)
            if n==0:
                r=con.execute('SELECT COUNT(*) n FROM event_nodes WHERE research_run_id=? AND node_id=?',(run_id,node_id)).fetchone();n=int(r['n'] or 0) if r else 0
            classification=e.get('classification') or ('STATE' if node.role=='STATE' else 'INSUFFICIENT');level={'DISCOVERY':'L2','VALIDATION':'L3','FINAL_HOLDOUT':'L4'}.get(role,'L0')
            train=bool(node.training_eligible and classification in {'CORE','OPTIONAL','STATE','REGIME_DEPENDENT'} and n>0)
            # L4 is frozen OOS, not production. L5 cost/latency and L6 live parity remain separate gates.
            prod=False
            items.append({'node_id':node_id,'role':node.role,'classification':classification,'evidence_level':level,'discovery_n':n if role=='DISCOVERY' else 0,'validation_n':n if role=='VALIDATION' else 0,'holdout_n':n if role=='FINAL_HOLDOUT' else 0,'effect_size':e.get('delta_avg_r'),'ci_low':e.get('ci_low'),'ci_high':e.get('ci_high'),'right_tail_retention':e.get('big_winner_retention'),'loser_rejection':e.get('big_loser_rejection'),'training_eligible':train,'production_eligible':prod})
    finally:con.close()
    with tx(event_db) as c:
        for x in items:c.execute('''INSERT OR REPLACE INTO node_evidence_registry(research_run_id,node_id,role,classification,evidence_level,discovery_n,validation_n,holdout_n,effect_size,ci_low,ci_high,positive_years,negative_years,right_tail_retention,loser_rejection,known_regime_dependency,training_eligible,production_eligible,last_research_run) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(run_id,x['node_id'],x['role'],x['classification'],x['evidence_level'],x['discovery_n'],x['validation_n'],x['holdout_n'],x['effect_size'],x['ci_low'],x['ci_high'],0,0,x['right_tail_retention'],x['loser_rejection'],None,int(x['training_eligible']),int(x['production_eligible']),run_id))
    return {'research_run_id':run_id,'items':items}
