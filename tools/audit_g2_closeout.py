from __future__ import annotations
import argparse, gzip, hashlib, json, math, sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from server.engine import _to_dt, _txt
from server.g2_closeout import MR_CHAIN, BO_CHAIN, PARENTS, REACHABILITY_VERSION, VALID_STATUSES

AUDIT_VERSION='G2_CAUSAL_TRUTH_AUDIT_V2_20260823'
ANCHOR_REQUIRED=set(MR_CHAIN+BO_CHAIN+['CTX_VALUE','AUC_EXTREME','WAIT_AMBIGUOUS'])


def dump(p,o): Path(p).write_text(json.dumps(o,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
def load_events(daily_dir):
    out=[]
    for p in sorted(Path(daily_dir).glob('*.json.gz')):
        with gzip.open(p,'rt',encoding='utf-8') as f: out.extend(json.load(f))
    return out

def rate(a,b): return a/b if b else None

def status_counts(events):
    c=Counter()
    for e in events:
        for n in (e.get('nodes') or {}).values(): c[n.get('evaluation_status') or 'MISSING']+=1
    return dict(c)

def logical_trace(events):
    total=0; bad=[]; counts=Counter(); status=Counter()
    for e in events:
        for nid,n in (e.get('nodes') or {}).items():
            total+=1; st=n.get('evaluation_status'); status[st]+=1
            if st not in VALID_STATUSES:
                counts['invalid_status']+=1; bad.append({'event_id':e['event_id'],'node_id':nid,'code':'INVALID_STATUS','status':st})
                continue
            if any(n.get(k) is None for k in ('resolution_seq','resolution_time','resolution_price')):
                counts['resolution_incomplete']+=1; bad.append({'event_id':e['event_id'],'node_id':nid,'code':'RESOLUTION_INCOMPLETE','status':st})
            if st=='EVALUATED':
                if n.get('answer') not in (True,False): counts['evaluated_answer_invalid']+=1; bad.append({'event_id':e['event_id'],'node_id':nid,'code':'EVALUATED_ANSWER_INVALID'})
                if any(n.get(k) is None for k in ('seq','time','decision_price')):
                    counts['decision_incomplete']+=1; bad.append({'event_id':e['event_id'],'node_id':nid,'code':'DECISION_INCOMPLETE'})
                if nid in ANCHOR_REQUIRED and any(n.get(k) is None for k in ('anchor_seq','anchor_time','anchor_price')):
                    counts['anchor_incomplete']+=1; bad.append({'event_id':e['event_id'],'node_id':nid,'code':'ANCHOR_INCOMPLETE'})
            elif st=='NOT_REACHED':
                if n.get('answer') is not None: counts['not_reached_answer_nonnull']+=1
                if not n.get('blocker_node_id') or not n.get('blocker_reason_code'):
                    counts['blocker_incomplete']+=1; bad.append({'event_id':e['event_id'],'node_id':nid,'code':'BLOCKER_INCOMPLETE'})
                if any(n.get(k) is not None for k in ('seq','time','decision_price')):
                    counts['not_reached_fake_decision']+=1; bad.append({'event_id':e['event_id'],'node_id':nid,'code':'NOT_REACHED_FAKE_DECISION'})
            elif st=='NOT_APPLICABLE':
                if n.get('answer') is not None: counts['not_applicable_answer_nonnull']+=1
            elif st=='TERMINAL':
                if n.get('answer') is not None: counts['terminal_answer_nonnull']+=1
    res={
        'audit_version':AUDIT_VERSION,'total_node_instances':total,'status_counts':dict(status),'violations':dict(counts),
        'resolution_trace_completeness': rate(total-counts['resolution_incomplete'],total),
        'evaluated_decision_completeness': None,
        'required_anchor_completeness': None,
        'not_reached_blocker_completeness': None,
        'examples':bad[:200],
    }
    evaluated=status['EVALUATED']; reached_anchor=sum(1 for e in events for nid,n in (e.get('nodes') or {}).items() if n.get('evaluation_status')=='EVALUATED' and nid in ANCHOR_REQUIRED); nr=status['NOT_REACHED']
    res['evaluated_decision_completeness']=rate(evaluated-counts['decision_incomplete'],evaluated)
    res['required_anchor_completeness']=rate(reached_anchor-counts['anchor_incomplete'],reached_anchor)
    res['not_reached_blocker_completeness']=rate(nr-counts['blocker_incomplete'],nr)
    res['pass']=not any(counts.values())
    return res

def blocker_lineage(events):
    counts=Counter(); examples=[]
    for e in events:
        nodes=e.get('nodes') or {}; chain=MR_CHAIN if e.get('strategy')=='MR' else BO_CHAIN if e.get('strategy')=='BO' else []
        pos={n:i for i,n in enumerate(chain)}
        for nid,n in nodes.items():
            st=n.get('evaluation_status')
            parent=PARENTS.get(nid)
            if nid in pos and n.get('parent_node_id')!=parent:
                counts['parent_id_mismatch']+=1; examples.append({'event_id':e['event_id'],'node_id':nid,'code':'PARENT_ID_MISMATCH','actual':n.get('parent_node_id'),'expected':parent})
            if parent and parent in nodes and nodes[parent].get('evaluation_status')=='NOT_REACHED' and st=='EVALUATED':
                counts['parent_reachability_violations']+=1; examples.append({'event_id':e['event_id'],'node_id':nid,'code':'PARENT_NOT_REACHED_CHILD_EVALUATED'})
            if st=='NOT_REACHED':
                b=n.get('blocker_node_id')
                if b not in pos or nid not in pos or pos[b]>=pos[nid]:
                    counts['blocker_ancestor_violations']+=1; examples.append({'event_id':e['event_id'],'node_id':nid,'blocker':b,'code':'BLOCKER_NOT_ANCESTOR'})
                elif nodes.get(b,{}).get('evaluation_status')!='EVALUATED' or nodes.get(b,{}).get('answer') is not False:
                    counts['blocker_not_direct_evaluated_no']+=1; examples.append({'event_id':e['event_id'],'node_id':nid,'blocker':b,'code':'BLOCKER_NOT_DIRECT_NO'})
                seen=set(); cur=nid
                while True:
                    if cur in seen:
                        counts['blocker_cycle_count']+=1; examples.append({'event_id':e['event_id'],'node_id':nid,'code':'BLOCKER_CYCLE'}); break
                    seen.add(cur); nx=nodes.get(cur,{}).get('blocker_node_id')
                    if not nx: break
                    cur=nx
        blocker=None
        for nid in chain:
            n=nodes.get(nid)
            if not n: continue
            if blocker is None:
                if n.get('evaluation_status')!='EVALUATED':
                    counts['premature_not_reached']+=1; examples.append({'event_id':e['event_id'],'node_id':nid,'code':'PREMATURE_NOT_REACHED'})
                elif n.get('answer') is False: blocker=nid
            else:
                if n.get('evaluation_status')!='NOT_REACHED' or n.get('blocker_node_id')!=blocker:
                    counts['downstream_reachability_mismatch']+=1; examples.append({'event_id':e['event_id'],'node_id':nid,'code':'DOWNSTREAM_REACHABILITY_MISMATCH','expected_blocker':blocker})
    return {'audit_version':AUDIT_VERSION,'violations':dict(counts),'examples':examples[:200],'pass':not any(counts.values())}

def ordering(events):
    c=Counter(); ex=[]
    for e in events:
        attempt=e.get('attempt_start_seq'); nodes=e.get('nodes') or {}; chain=MR_CHAIN if e.get('strategy')=='MR' else BO_CHAIN if e.get('strategy')=='BO' else []
        for nid,n in nodes.items():
            rs=n.get('resolution_seq')
            if attempt is not None and rs is not None and int(attempt)>int(rs): c['attempt_after_resolution']+=1; ex.append({'event_id':e['event_id'],'node_id':nid,'code':'ATTEMPT_AFTER_RESOLUTION'})
            if n.get('evaluation_status')=='EVALUATED' and n.get('anchor_seq') is not None and n.get('seq') is not None and int(n['anchor_seq'])>int(n['seq']): c['anchor_after_decision']+=1; ex.append({'event_id':e['event_id'],'node_id':nid,'code':'ANCHOR_AFTER_DECISION','anchor_seq':n['anchor_seq'],'decision_seq':n['seq']})
            if n.get('evaluation_status')=='NOT_REACHED':
                b=nodes.get(n.get('blocker_node_id')) or {}
                if b.get('resolution_seq') is not None and rs is not None and int(b['resolution_seq'])>int(rs): c['blocker_after_child_resolution']+=1; ex.append({'event_id':e['event_id'],'node_id':nid,'code':'BLOCKER_AFTER_CHILD'})
        prev=None
        for nid in chain:
            n=nodes.get(nid)
            if not n: continue
            rs=n.get('resolution_seq')
            if prev is not None and rs is not None and int(prev)>int(rs): c['parent_child_order_violation']+=1; ex.append({'event_id':e['event_id'],'node_id':nid,'code':'PARENT_CHILD_ORDER','previous_resolution':prev,'resolution':rs})
            if rs is not None: prev=rs
        if e.get('result')=='ENTRY' and e.get('entry_seq') is not None:
            decisions=[int(nodes[n]['seq']) for n in chain if n in nodes and nodes[n].get('evaluation_status')=='EVALUATED' and nodes[n].get('seq') is not None]
            if decisions and int(e['entry_seq'])<max(decisions): c['strict_entry_before_required_decision']+=1; ex.append({'event_id':e['event_id'],'code':'ENTRY_BEFORE_REQUIRED_DECISION','entry_seq':e['entry_seq'],'max_decision':max(decisions)})
    return {'audit_version':AUDIT_VERSION,'violations':dict(c),'examples':ex[:200],'pass':not any(c.values())}

def build_funnels(events, frame_manifest, g1_summary=None):
    source=g1_summary or {}
    event_month=Counter(); event_dir=Counter(); entry_month=Counter(); entry_dir=Counter(); strategy=Counter(); entries=Counter(); relaxed=Counter()
    for e in events:
        st=e.get('strategy'); strategy[st]+=1; event_month[(st,e['trading_date'][:7])]+=1; event_dir[(st,e.get('direction'))]+=1
        if e.get('result')=='ENTRY': entries[st]+=1; entry_month[(st,e['trading_date'][:7])]+=1; entry_dir[(st,e.get('direction'))]+=1
        if (e.get('features') or {}).get('terminal_signal'): relaxed[st]+=1
    root={
      'source_rows':source.get('rows'),'mtx_rows':source.get('mtx_rows'),'outright_rows':source.get('six_digit_outright_rows'),'day_session_rows':source.get('day_session_rows'),'observed_sessions':frame_manifest.get('observed_sessions'),'eligible_scan_sessions':frame_manifest.get('eligible_sessions'),'events':len(events),'strategy_events':dict(strategy),'strict_entries':dict(entries),'relaxed_terminal_opportunities':dict(relaxed),
      'monthly_event_distribution':{f'{k[0]}|{k[1]}':v for k,v in sorted(event_month.items())},'direction_event_distribution':{f'{k[0]}|{k[1]}':v for k,v in sorted(event_dir.items())},'monthly_entry_distribution':{f'{k[0]}|{k[1]}':v for k,v in sorted(entry_month.items())},'direction_entry_distribution':{f'{k[0]}|{k[1]}':v for k,v in sorted(entry_dir.items())}
    }
    node_rows=[]; first=Counter()
    for st,chain in [('MR',MR_CHAIN),('BO',BO_CHAIN)]:
        ev=[e for e in events if e.get('strategy')==st]; universe=len(ev)
        for nid in chain:
            material=[(e,(e.get('nodes') or {}).get(nid)) for e in ev if nid in (e.get('nodes') or {})]
            reached=[x for x in material if x[1].get('evaluation_status')=='EVALUATED']; yes=[x for x in reached if x[1].get('answer') is True]; no=[x for x in reached if x[1].get('answer') is False]
            nr=[x for x in material if x[1].get('evaluation_status')=='NOT_REACHED']; na=[x for x in material if x[1].get('evaluation_status')=='NOT_APPLICABLE']
            node_rows.append({'strategy':st,'node_id':nid,'universe':universe,'materialized':len(material),'reached':len(reached),'yes':len(yes),'direct_no':len(no),'not_reached':len(nr),'not_applicable':len(na),'conditional_pass_rate':rate(len(yes),len(reached)),'unconditional_yes_rate':rate(len(yes),universe),'monthly_yes':dict(Counter(e['trading_date'][:7] for e,_ in yes)),'monthly_direct_no':dict(Counter(e['trading_date'][:7] for e,_ in no)),'direction_yes':dict(Counter(e.get('direction') for e,_ in yes)),'direction_direct_no':dict(Counter(e.get('direction') for e,_ in no))})
        for e in ev:
            b=(e.get('features') or {}).get('first_failure_node')
            if b:first[(st,b)]+=1
            elif e.get('result')=='ENTRY':first[(st,'STRICT_ENTRY_PASS')]+=1
            else:first[(st,'NO_EVALUATED_FAILURE')]+=1
    first_rows=[{'strategy':k[0],'first_failure_node':k[1],'n':v} for k,v in sorted(first.items())]
    return root,node_rows,first_rows,node_rows

class PhysicalResolver:
    def __init__(self,path):
        self.pf=pq.ParquetFile(path); self.starts=[];s=0
        for i in range(self.pf.num_row_groups):
            n=self.pf.metadata.row_group(i).num_rows;self.starts.append((s,s+n-1,i));s+=n
    def resolve(self,seqs):
        need=sorted(set(int(x) for x in seqs if x is not None));res={};p=0
        for start,end,i in self.starts:
            if p>=len(need):break
            if need[p]>end:continue
            q=p
            while q<len(need) and need[q]<=end:q+=1
            group=[x for x in need[p:q] if x>=start]
            if not group:continue
            tab=self.pf.read_row_group(i,columns=['datetime','product','expiry','price']).to_pandas()
            for seq in group:
                r=tab.iloc[seq-start];res[seq]={'time':pd.Timestamp(r['datetime']).isoformat(),'product':str(r['product']),'expiry':str(r['expiry']),'price':float(r['price'])}
            p=q
        return res

def physical_proof(source,events):
    refs=[]
    for e in events:
        contract=str(e.get('contract'));day=e.get('trading_date')
        for nid,n in (e.get('nodes') or {}).items():
            for kind,sk,tk,pk in [('anchor','anchor_seq','anchor_time','anchor_price'),('decision','seq','time','decision_price'),('resolution','resolution_seq','resolution_time','resolution_price')]:
                if n.get(sk) is not None:refs.append({'event_id':e['event_id'],'node_id':nid,'kind':kind,'seq':int(n[sk]),'time':n.get(tk),'price':n.get(pk),'contract':contract,'day':day})
        if e.get('entry_seq') is not None:refs.append({'event_id':e['event_id'],'node_id':'STRICT_ENTRY','kind':'strict_entry','seq':int(e['entry_seq']),'time':e.get('entry_time'),'price':e.get('entry_price'),'contract':contract,'day':day})
        f=e.get('features') or {}
        if f.get('terminal_entry_seq') is not None:refs.append({'event_id':e['event_id'],'node_id':'TERMINAL_ENTRY','kind':'terminal_entry','seq':int(f['terminal_entry_seq']),'time':f.get('terminal_entry_time'),'price':f.get('terminal_entry_price'),'contract':contract,'day':day})
    seqs=set(r['seq'] for r in refs);resolved=PhysicalResolver(source).resolve(seqs);c=Counter();ex=[]
    for r in refs:
        x=resolved.get(r['seq'])
        if not x:c['missing_seq']+=1;ex.append({**r,'code':'MISSING_SEQ'});continue
        if r['time'] is not None and pd.Timestamp(r['time'])!=pd.Timestamp(x['time']):c['time_mismatch']+=1
        if r['price'] is not None and abs(float(r['price'])-float(x['price']))>1e-9:c['price_mismatch']+=1
        if x['product']!='MTX':c['product_mismatch']+=1
        if x['expiry']!=r['contract']:c['contract_mismatch']+=1
        t=pd.Timestamp(x['time']);sec=t.hour*3600+t.minute*60+t.second
        if t.strftime('%Y-%m-%d')!=r['day'] or sec<31500 or sec>49500:c['session_mismatch']+=1
        if Path(source).name!='MTX_2025(5).parquet':c['source_mismatch']+=1
    return {'audit_version':AUDIT_VERSION,'source_file':Path(source).name,'requested_unique_physical_seq':len(seqs),'resolved_unique_physical_seq':len(resolved),'missing_seq':c['missing_seq'],'time_mismatch':c['time_mismatch'],'price_mismatch':c['price_mismatch'],'product_mismatch':c['product_mismatch'],'contract_mismatch':c['contract_mismatch'],'session_mismatch':c['session_mismatch'],'source_mismatch':c['source_mismatch'],'violations_total':sum(c.values()),'examples':ex[:100],'pass':sum(c.values())==0}

def threshold_margin(nid,n):
    m=n.get('metrics') or {}
    pairs=[('qualified_excursion_points','threshold'),('reclaim_depth_vw','min_reclaim_depth_vw'),('depth','min_depth'),('distance_to_lvn','tolerance'),('outside_ratio','required_outside_ratio'),('displacement_vw','min_displacement_vw'),('risk_points','max_risk_points'),('extension_vw','max_extension_vw')]
    for a,b in pairs:
        if m.get(a) is not None and m.get(b) is not None:return float(m[a])-float(m[b])
    return None

def targeted_qa(events,conversion,physical,frame_manifest):
    cases=[];seen=set()
    def add(cat,e,nid=None,n=None,note=None):
        key=(cat,e['event_id'],nid)
        if key in seen:return
        seen.add(key); cases.append({'category':cat,'event_id':e['event_id'],'trading_date':e['trading_date'],'strategy':e['strategy'],'direction':e.get('direction'),'node_id':nid,'status':n.get('evaluation_status') if n else None,'answer':n.get('answer') if n else None,'reason_code':n.get('reason_code') if n else None,'decision_seq':n.get('seq') if n else None,'resolution_seq':n.get('resolution_seq') if n else None,'note':note})
    for st,nid in [('MR','MR_ENTRY'),('BO','BO_ENTRY')]:
        rows=[(e,(e.get('nodes') or {}).get(nid)) for e in events if e.get('strategy')==st and nid in (e.get('nodes') or {})]
        for ans,label in [(True,'YES'),(False,'DIRECT_NO')]:
            cand=[x for x in rows if x[1].get('evaluation_status')=='EVALUATED' and x[1].get('answer') is ans]
            for e,n in cand[:20]: add(f'{st}_ENTRY_{label}',e,nid,n,note=f'requested=20 available={len(cand)}')
    waits=[]
    for e in events:
        if e.get('strategy')!='WAIT':continue
        n=(e.get('nodes') or {}).get('AUC_ATTEMPT')
        if n:
            m=threshold_margin('AUC_ATTEMPT',n)
            waits.append((abs(m) if m is not None else 1e99,e,n))
    for _,e,n in sorted(waits,key=lambda x:x[0])[:20]: add('WAIT_NEAR_MISS',e,'AUC_ATTEMPT',n)
    b=[]
    for e in events:
        for nid,n in (e.get('nodes') or {}).items():
            if n.get('evaluation_status')!='EVALUATED':continue
            m=threshold_margin(nid,n)
            if m is not None:b.append((abs(m),e,nid,n,m))
    for ans,label in [(True,'YES'),(False,'NO')]:
        sub=sorted([x for x in b if x[3].get('answer') is ans],key=lambda x:x[0])[:10]
        for _,e,nid,n,m in sub:add(f'NEAREST_THRESHOLD_{label}',e,nid,n,note=f'margin={m}')
    byreason=defaultdict(list)
    for e in events:
        bnode=(e.get('features') or {}).get('first_failure_node')
        if bnode:
            n=(e.get('nodes') or {}).get(bnode) or {}; byreason[(bnode,n.get('reason_code'))].append((e,n))
    for (nid,reason),arr in sorted(byreason.items()):
        for e,n in arr[:5]:add('FIRST_FAILURE_REASON',e,nid,n,note=f'{nid}|{reason}; available={len(arr)}')
    deep=[]
    for e in events:
        chain=MR_CHAIN if e.get('strategy')=='MR' else BO_CHAIN if e.get('strategy')=='BO' else []
        bnode=(e.get('features') or {}).get('first_failure_node')
        if bnode in chain: deep.append((chain.index(bnode),e,bnode,(e.get('nodes') or {})[bnode]))
    for _,e,nid,n in sorted(deep,key=lambda x:x[0],reverse=True)[:20]:add('DEEPEST_REACHED_FAILURE',e,nid,n)
    cc=[x for x in conversion if x['reached']>=10 and x['conditional_pass_rate'] is not None]
    collapse=min(cc,key=lambda x:x['conditional_pass_rate']) if cc else None
    if collapse:
        nid=collapse['node_id']; st=collapse['strategy']; rows=[(e,(e.get('nodes') or {}).get(nid)) for e in events if e.get('strategy')==st and nid in (e.get('nodes') or {})]
        no=[x for x in rows if x[1].get('evaluation_status')=='EVALUATED' and x[1].get('answer') is False]; yes=[x for x in rows if x[1].get('evaluation_status')=='EVALUATED' and x[1].get('answer') is True]
        for e,n in no[:20]:add('CONVERSION_COLLAPSE_DIRECT_NO',e,nid,n,note=f"conditional_pass={collapse['conditional_pass_rate']}")
        for e,n in yes[:20]:add('CONVERSION_COLLAPSE_YES',e,nid,n,note=f"conditional_pass={collapse['conditional_pass_rate']}")
    bydate=defaultdict(list)
    for e in events: bydate[e['trading_date']].append(e)
    observed=sorted((frame_manifest.get('days') or {}).keys())
    roll_dates=[d for d in observed if (frame_manifest.get('days') or {}).get(d,{}).get('roll')]
    for rd in roll_dates:
        ix=observed.index(rd)
        prev=next((observed[j] for j in range(ix-1,-1,-1) if bydate.get(observed[j])),None)
        nxt=next((observed[j] for j in range(ix+1,len(observed)) if bydate.get(observed[j])),None)
        if prev:add('ROLL_BOUNDARY_MINUS1',bydate[prev][0],note=f'roll_day={rd}; relative=previous_scannable_session')
        if nxt:add('ROLL_BOUNDARY_PLUS1',bydate[nxt][0],note=f'roll_day={rd}; relative=next_scannable_session')
    import datetime as _dt
    long_closures=[]
    for a,b in zip(observed,observed[1:]):
        gap=(_dt.date.fromisoformat(b)-_dt.date.fromisoformat(a)).days
        if gap>7:
            long_closures.append({'before':a,'after':b,'calendar_gap_days':gap})
            if bydate.get(b):add('LONG_CLOSURE_BOUNDARY',bydate[b][0],note=f'before={a}; after={b}; gap_days={gap}')
    reset_dates=[d for d in observed if (frame_manifest.get('days') or {}).get(d,{}).get('coverage_status')=='PROFILE_CHAIN_RESET']
    requested={'MR_ENTRY_YES':20,'MR_ENTRY_DIRECT_NO':20,'BO_ENTRY_YES':20,'BO_ENTRY_DIRECT_NO':20,'WAIT_NEAR_MISS':20,'NEAREST_THRESHOLD_YES':10,'NEAREST_THRESHOLD_NO':10,'FIRST_FAILURE_REASON':5,'DEEPEST_REACHED_FAILURE':20,'CONVERSION_COLLAPSE_DIRECT_NO':20,'CONVERSION_COLLAPSE_YES':20,'ROLL_BOUNDARY_MINUS1':len(roll_dates),'ROLL_BOUNDARY_PLUS1':len(roll_dates),'LONG_CLOSURE_BOUNDARY':len(long_closures),'COVERAGE_RESET_BOUNDARY':len(reset_dates)}
    actual=Counter(c['category'] for c in cases)
    sample_shortfalls={}
    for cat,req in requested.items():
        if cat=='FIRST_FAILURE_REASON' or req==0: continue
        got=actual.get(cat,0)
        if got<req: sample_shortfalls[cat]={'requested':req,'available_selected':got,'shortfall':req-got}
    manifest={'audit_version':AUDIT_VERSION,'requested_categories':requested,'actual_category_counts':dict(actual),'sample_shortfalls':sample_shortfalls,'roll_dates':roll_dates,'long_closure_boundaries':long_closures,'coverage_reset_dates':reset_dates,'cases':cases,'conversion_collapse_node':collapse}
    results=[]; defects=0
    for c in cases:
        ok=True; reasons=[]
        e=next(x for x in events if x['event_id']==c['event_id']); n=(e.get('nodes') or {}).get(c.get('node_id')) if c.get('node_id') else None
        if n:
            st=n.get('evaluation_status')
            if st=='EVALUATED' and (n.get('seq') is None or n.get('resolution_seq') is None):ok=False;reasons.append('EVALUATED_TRACE_INCOMPLETE')
            if st=='NOT_REACHED' and (not n.get('blocker_node_id') or n.get('answer') is not None):ok=False;reasons.append('NOT_REACHED_SEMANTICS_INVALID')
        if not physical.get('pass'):ok=False;reasons.append('GLOBAL_PHYSICAL_PROOF_FAIL')
        defects+=0 if ok else 1; results.append({**c,'review_status':'PASS' if ok else 'FAIL','defects':reasons})
    return manifest,{'audit_version':AUDIT_VERSION,'review_mode':'deterministic targeted replay semantic review; no future outcomes','cases_reviewed':len(results),'systematic_defects':defects,'sample_shortfalls':sample_shortfalls,'results':results,'pass':defects==0}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--run-dir',required=True);ap.add_argument('--g1-summary');a=ap.parse_args();run=Path(a.run_dir);events=load_events(run/'daily_events');fm=json.load(open(run/'frame_manifest.json'));g1=json.load(open(a.g1_summary)) if a.g1_summary else {}
    logical=logical_trace(events);lineage=blocker_lineage(events);order=ordering(events);root,nodes,failures,conv=build_funnels(events,fm,g1);phys=physical_proof(a.source,events);qa_m,qa_r=targeted_qa(events,conv,phys,fm)
    dump(run/'logical_trace_audit.json',logical);dump(run/'blocker_lineage_audit.json',lineage);dump(run/'causal_ordering_audit.json',order);dump(run/'physical_truth_audit.json',phys);dump(run/'funnel.json',{'root':root,'nodes':nodes});dump(run/'first_failure_funnel.json',{'rows':failures});dump(run/'conditional_node_conversion.json',{'rows':conv});dump(run/'conversion_collapse.json',{'audit_version':AUDIT_VERSION,'row':qa_m.get('conversion_collapse_node'),'pass':qa_m.get('conversion_collapse_node') is not None});dump(run/'targeted_qa_manifest.json',qa_m);dump(run/'targeted_qa_results.json',qa_r)
    eligibility=json.load(open(run/'session_eligibility_audit.json')); migration=json.load(open(run/'migration_regression.json')); strategy_reg=json.load(open(run/'strategy_semantics_regression.json')); relaxed_reg=json.load(open(run/'relaxed_universe_regression.json'))
    checks={'session_eligibility':bool(eligibility.get('pass')),'migration_regression':bool(migration.get('pass')),'strategy_semantics_regression':bool(strategy_reg.get('pass')),'relaxed_universe_regression':bool(relaxed_reg.get('pass')),'logical_trace':bool(logical.get('pass')),'blocker_lineage':bool(lineage.get('pass')),'physical_truth':bool(phys.get('pass')),'causal_ordering':bool(order.get('pass')),'targeted_qa':bool(qa_r.get('pass'))}
    gate={'gate':'G2_CAUSAL_SIGNAL_TRUTH','status':'PASS' if all(checks.values()) else 'FAIL','audit_version':AUDIT_VERSION,'events':len(events),'checks':checks,'logical_trace_pass':logical['pass'],'blocker_lineage_pass':lineage['pass'],'causal_ordering_pass':order['pass'],'physical_truth_pass':phys['pass'],'targeted_qa_pass':qa_r['pass'],'outcomes_computed':False,'pf_computed':False,'statistical_edge_computed':False,'pass':all(checks.values())}
    dump(run/'g2_audit_gate.json',gate);print(json.dumps(gate,indent=2))
if __name__=='__main__':main()
