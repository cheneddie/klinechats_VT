from __future__ import annotations
import argparse,gzip,hashlib,json,math,sys,time
from datetime import datetime,timezone
from pathlib import Path
import numpy as np,pandas as pd,pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server.v4_release_engine import ScanConfigV4Final,scan_day_v4_final
from server.g2_closeout import apply_g2_closeout,REACHABILITY_VERSION,CAUSAL_REPAIR_VERSION,_phys_map

RUNNER_VERSION='G2_CLOSEOUT_RELEASE_V1_20260823'
def utc():return datetime.now(timezone.utc).isoformat()
def norm(v):
    if isinstance(v,dict):return {str(k):norm(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [norm(x) for x in v]
    if isinstance(v,np.integer):return int(v)
    if isinstance(v,np.floating):
        x=float(v);return None if not math.isfinite(x) else x
    if isinstance(v,(pd.Timestamp,datetime)):return v.isoformat()
    return v
def cbytes(o):return json.dumps(norm(o),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def sha(o):return hashlib.sha256(cbytes(o)).hexdigest()
def fsha(p):
 h=hashlib.sha256();f=open(p,'rb')
 for b in iter(lambda:f.read(8<<20),b''):h.update(b)
 f.close();return h.hexdigest()
def dump(p,o):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(norm(o),ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False),encoding='utf-8');tmp.replace(p)
def write_gz(p,o):
 p=Path(p);tmp=Path(str(p)+'.tmp');
 with gzip.open(tmp,'wt',encoding='utf-8',compresslevel=6) as f:json.dump(norm(o),f,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
 tmp.replace(p)
def strategy(e):return {k:e.get(k) for k in ('event_id','strategy','direction','result','entry_seq','entry_time','entry_price','stop','target')}
def relaxed(e):
 f=e.get('features') or {};ks=('terminal_signal','terminal_signal_kind','terminal_entry_seq','terminal_entry_time','terminal_entry_price','terminal_stop','terminal_risk_points','audit_universe_version')
 return {'event_id':e.get('event_id'),**{k:f.get(k) for k in ks}}
def evaluated_sem(e):return {nid:{'answer':n.get('answer'),'reason_code':n.get('reason_code')} for nid,n in (e.get('nodes') or {}).items() if n.get('evaluation_status')=='EVALUATED'}
def baseline_sem(e,ids):
 n=e.get('nodes') or {};return {i:{'answer':(n.get(i) or {}).get('answer'),'reason_code':(n.get(i) or {}).get('reason_code')} for i in ids}

def compare(base,new,repair):
 v=[];bm={e['event_id']:e for e in base};nm={e['event_id']:e for e in new}
 if set(bm)!=set(nm):v.append({'code':'EVENT_ID_SET_MISMATCH','baseline_n':len(bm),'new_n':len(nm)})
 for eid in sorted(set(bm)&set(nm)):
  b,n=bm[eid],nm[eid];r=(n.get('features') or {}).get('g2_bo_entry_repair_applied') is True
  if cbytes(relaxed(b))!=cbytes(relaxed(n)):v.append({'code':'RELAXED_UNIVERSE_MISMATCH','event_id':eid})
  es=evaluated_sem(n);bs=baseline_sem(b,es.keys())
  # All evaluated nodes except repaired BO_ENTRY must preserve answer+reason.
  for nid,x in es.items():
   if r and nid=='BO_ENTRY':continue
   if cbytes(x)!=cbytes(bs.get(nid)):v.append({'code':'EVALUATED_NODE_SEMANTICS_MISMATCH','event_id':eid,'node_id':nid})
  if not r and cbytes(strategy(b))!=cbytes(strategy(n)):v.append({'code':'UNEXPECTED_STRATEGY_SEMANTICS_MISMATCH','event_id':eid})
  if r and repair is None:v.append({'code':'REPAIR_FLAG_WITHOUT_REPAIR_RECORD','event_id':eid})
 return v

class RangeReader:
 def __init__(self,path):
  self.pf=pq.ParquetFile(path);self.starts=[];s=0
  for i in range(self.pf.num_row_groups):
   n=self.pf.metadata.row_group(i).num_rows;self.starts.append((s,s+n-1,i));s+=n
 def read(self,lo,hi):
  pieces=[]
  for s,e,i in self.starts:
   if e<lo or s>hi:continue
   tab=self.pf.read_row_group(i,columns=['datetime','product','expiry','price','volume','side']).to_pandas();a=max(lo,s)-s;b=min(hi,e)-s+1;sub=tab.iloc[a:b].copy();sub['_seq']=np.arange(max(lo,s),min(hi,e)+1,dtype=np.int64);pieces.append(sub)
  d=pd.concat(pieces,ignore_index=True);dt=pd.to_datetime(d['datetime']);sec=dt.dt.hour*3600+dt.dt.minute*60+dt.dt.second;return d,dt,sec

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--seed-manifest',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
 src=Path(a.source);out=Path(a.out);(out/'daily_events').mkdir(parents=True,exist_ok=True);(out/'daily_regression').mkdir(exist_ok=True)
 seed=json.load(open(a.seed_manifest));source_sha=fsha(src)
 if source_sha!=seed['source_sha256']:raise SystemExit('SOURCE_SHA_MISMATCH')
 cfg=ScanConfigV4Final(contract_mode='strict');days=seed['days'];eligible=[d for d in sorted(days) if days[d].get('eligible')]
 # eligibility audit
 excluded=[];session_rows=[];sdays=sorted(days)
 for ix,d in enumerate(sdays):
  x=days[d];reason='ELIGIBLE';prev_contract=days[sdays[ix-1]].get('contract') if ix>0 else None
  if not x.get('eligible'):reason='FIRST_OBSERVED_SESSION' if x.get('coverage_status')=='FIRST_OBSERVED_DAY' else ('ROLL_BLACKOUT' if x.get('roll') else 'UNKNOWN')
  row={'trading_date':d,'observed':True,'eligible':bool(x.get('eligible')),'reason_code':reason,'selected_contract':x.get('contract'),'previous_profile_contract':prev_contract,'roll_state':bool(x.get('roll')),'previous_value_valid':bool(ix>0 and x.get('coverage_status')=='PASS' and not x.get('roll')),'coverage_status':x.get('coverage_status')}
  session_rows.append(row)
  if reason!='ELIGIBLE':excluded.append(row)
 elig={'observed_sessions':len(days),'eligible_sessions':len(eligible),'excluded_sessions':len(excluded),'unknown_exclusion_reason':sum(x['reason_code']=='UNKNOWN' for x in excluded),'identity_holds':len(days)==len(eligible)+len(excluded),'sessions':session_rows,'excluded':excluded,'pass':len(days)==len(eligible)+len(excluded) and not any(x['reason_code']=='UNKNOWN' for x in excluded)};dump(out/'session_eligibility_audit.json',elig)
 rr=RangeReader(src);started=utc();results=[];repairs=[];viol=[]
 for i,day in enumerate(eligible,1):
  ep=out/'daily_events'/f'{day}.json.gz';rp=out/'daily_regression'/f'{day}.json'
  if ep.exists() and rp.exists():
   r=json.load(open(rp));results.append(r);repairs.extend(r.get('expected_repairs',[]));viol.extend(r.get('violations',[]));continue
  meta=days[day];prev_day=sorted(days).index(day)-1;prev=days[sorted(days)[prev_day]]['profile']
  raw,dt,sec=rr.read(int(meta['first_seq']),int(meta['last_seq']))
  prod=raw['product'].astype(str);exp=raw['expiry'].astype(str);mask=(prod=='MTX')&(exp==str(meta['contract']))&(sec>=8*3600+45*60)&(sec<=13*3600+45*60)&(dt.dt.strftime('%Y-%m-%d')==day)
  sub=raw.loc[mask,['price','volume','side','_seq']].copy();sub['dt']=dt.loc[mask].to_numpy();sub.reset_index(drop=True,inplace=True)
  # verify seed, which is used only as seq/profile index.
  if len(sub)!=meta['rows'] or int(sub['_seq'].iloc[0])!=meta['first_seq'] or int(sub['_seq'].iloc[-1])!=meta['last_seq']:raise RuntimeError(f'SEED_RANGE_VERIFY_FAIL {day}')
  base=scan_day_v4_final(sub,prev,cfg,src,day,meta['contract']);new=[];dayrep=[];pm=_phys_map(sub)
  for e in base:
   n,r=apply_g2_closeout(e,sub,cfg,pm=pm);new.append(n)
   if r:dayrep.append(r)
  dv=compare(base,new,dayrep)
  write_gz(ep,new)
  r={'trading_date':day,'events':len(new),'violations':dv,'expected_repairs':dayrep,'baseline_event_identity_hash':sha(sorted(e['event_id'] for e in base)),'new_event_identity_hash':sha(sorted(e['event_id'] for e in new)),'baseline_strategy_hash':sha([strategy(x) for x in sorted(base,key=lambda z:z['event_id'])]),'new_strategy_hash':sha([strategy(x) for x in sorted(new,key=lambda z:z['event_id'])]),'baseline_relaxed_hash':sha([relaxed(x) for x in sorted(base,key=lambda z:z['event_id'])]),'new_relaxed_hash':sha([relaxed(x) for x in sorted(new,key=lambda z:z['event_id'])]),'new_event_hash':sha(sorted(new,key=lambda z:z['event_id'])),'implementation_identity':sha({'runner':RUNNER_VERSION,'reachability':REACHABILITY_VERSION,'repair':CAUSAL_REPAIR_VERSION})};dump(rp,r);results.append(r);repairs.extend(dayrep);viol.extend(dv)
  dump(out/'progress.json',{'phase':'regression','completed_sessions':i,'eligible_sessions':len(eligible),'violations':len(viol),'expected_repairs':len(repairs),'last_day':day,'updated_at':utc()})
 results.sort(key=lambda x:x['trading_date'])
 agg=lambda key:hashlib.sha256('\n'.join(f"{r['trading_date']}:{r[key]}" for r in results).encode()).hexdigest()
 # no-repair strategy equality is checked per event; overall baseline/new strategy hash may differ because expected repairs are real causal fixes.
 impl_ids=sorted(set(r.get('implementation_identity') for r in results))
 reg={'runner_version':RUNNER_VERSION,'reachability_version':REACHABILITY_VERSION,'causal_repair_version':CAUSAL_REPAIR_VERSION,'source_file':src.name,'source_sha256':source_sha,'observed_sessions':len(days),'eligible_sessions':len(eligible),'completed_sessions':len(results),'failed_sessions':0,'regression_violations':len(viol),'implementation_identities':impl_ids,'implementation_identity_count':len(impl_ids),'violations':viol[:500],'expected_causal_repairs':len(repairs),'expected_repairs':repairs,'deterministic_event_aggregate_hash':agg('new_event_hash'),'baseline_strategy_aggregate_hash':agg('baseline_strategy_hash'),'new_strategy_aggregate_hash':agg('new_strategy_hash'),'baseline_relaxed_aggregate_hash':agg('baseline_relaxed_hash'),'new_relaxed_aggregate_hash':agg('new_relaxed_hash'),'canonical_serialization':{'encoding':'UTF-8','json_keys':'sorted','separators':[',',':'],'null':'JSON null','float':'Python JSON finite decimal representation','timezone':'ISO-8601 persisted by scanner','newline_policy':'aggregate uses LF joining sorted trading_date:hash lines'},'outcomes_computed':False,'pf_computed':False,'statistical_edge_computed':False,'started_at':started,'finished_at':utc(),'pass':len(results)==len(eligible) and len(viol)==0 and len(impl_ids)==1};dump(out/'migration_regression.json',reg)
 strat={'event_identity_differences':0 if not any(v['code']=='EVENT_ID_SET_MISMATCH' for v in viol) else 1,'unexpected_strategy_semantic_differences':sum(v['code']=='UNEXPECTED_STRATEGY_SEMANTICS_MISMATCH' for v in viol),'evaluated_node_semantic_differences':sum(v['code']=='EVALUATED_NODE_SEMANTICS_MISMATCH' for v in viol),'expected_causal_repairs':len(repairs),'pass':not viol};dump(out/'strategy_semantics_regression.json',strat)
 rel={'baseline_aggregate_hash':reg['baseline_relaxed_aggregate_hash'],'new_aggregate_hash':reg['new_relaxed_aggregate_hash'],'differences':sum(v['code']=='RELAXED_UNIVERSE_MISMATCH' for v in viol),'pass':reg['baseline_relaxed_aggregate_hash']==reg['new_relaxed_aggregate_hash'] and not any(v['code']=='RELAXED_UNIVERSE_MISMATCH' for v in viol)};dump(out/'relaxed_universe_regression.json',rel)
 # frame manifest copies seed identity plus verified eligibility; no strategy outputs from seed are trusted.
 fm={'source_file':src.name,'source_sha256':source_sha,'seed_manifest_sha256':fsha(a.seed_manifest),'seed_use':'physical seq/profile index only; every eligible day range re-read and verified from raw parquet','coverage_policy_version':seed.get('coverage_policy_version'),'coverage':seed.get('coverage',[]),'observed_sessions':len(days),'eligible_sessions':len(eligible),'days':days};dump(out/'frame_manifest.json',fm)
 dump(out/'progress.json',{'phase':'regression_done','completed_sessions':len(results),'eligible_sessions':len(eligible),'violations':len(viol),'expected_repairs':len(repairs),'updated_at':utc()})
 print(json.dumps({'completed_sessions':len(results),'eligible_sessions':len(eligible),'violations':len(viol),'expected_repairs':len(repairs)},indent=2))
if __name__=='__main__':main()
