from __future__ import annotations
import argparse,gzip,hashlib,json,math,sys,time
from pathlib import Path
from datetime import datetime
import numpy as np,pandas as pd,pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server.v4_release_engine import ScanConfigV4Final,scan_day_v4_final
from server.g2_closeout import apply_g2_closeout,_phys_map,REACHABILITY_VERSION,CAUSAL_REPAIR_VERSION

def norm(v):
    if isinstance(v,dict): return {str(k):norm(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [norm(x) for x in v]
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,np.floating):
        x=float(v); return None if not math.isfinite(x) else x
    if isinstance(v,(pd.Timestamp,datetime)): return v.isoformat()
    return v
def cbytes(o): return json.dumps(norm(o),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(o): return hashlib.sha256(cbytes(o)).hexdigest()
def fsha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8<<20),b''): h.update(b)
    return h.hexdigest()
def dump(p,o):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=Path(str(p)+'.tmp');tmp.write_text(json.dumps(norm(o),ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False),encoding='utf-8');tmp.replace(p)
def write_gz(p,o):
    p=Path(p);tmp=Path(str(p)+'.tmp')
    with gzip.open(tmp,'wt',encoding='utf-8',compresslevel=6) as f: json.dump(norm(o),f,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    tmp.replace(p)
def strategy(e): return {k:e.get(k) for k in ('event_id','strategy','direction','result','entry_seq','entry_time','entry_price','stop','target')}
def relaxed(e):
    f=e.get('features') or {};ks=('terminal_signal','terminal_signal_kind','terminal_entry_seq','terminal_entry_time','terminal_entry_price','terminal_stop','terminal_risk_points','audit_universe_version')
    return {'event_id':e.get('event_id'),**{k:f.get(k) for k in ks}}
def evaluated_sem(e): return {nid:{'answer':n.get('answer'),'reason_code':n.get('reason_code')} for nid,n in (e.get('nodes') or {}).items() if n.get('evaluation_status')=='EVALUATED'}
def baseline_sem(e,ids):
    n=e.get('nodes') or {}; return {i:{'answer':(n.get(i) or {}).get('answer'),'reason_code':(n.get(i) or {}).get('reason_code')} for i in ids}
def compare(base,new):
    v=[];bm={e['event_id']:e for e in base};nm={e['event_id']:e for e in new}
    if set(bm)!=set(nm): v.append({'code':'EVENT_ID_SET_MISMATCH','baseline_n':len(bm),'new_n':len(nm)})
    for eid in sorted(set(bm)&set(nm)):
        b,n=bm[eid],nm[eid];r=(n.get('features') or {}).get('g2_bo_entry_repair_applied') is True
        if cbytes(relaxed(b))!=cbytes(relaxed(n)):v.append({'code':'RELAXED_UNIVERSE_MISMATCH','event_id':eid})
        es=evaluated_sem(n);bs=baseline_sem(b,es.keys())
        for nid,x in es.items():
            if r and nid=='BO_ENTRY': continue
            if cbytes(x)!=cbytes(bs.get(nid)): v.append({'code':'EVALUATED_NODE_SEMANTICS_MISMATCH','event_id':eid,'node_id':nid})
        if not r and cbytes(strategy(b))!=cbytes(strategy(n)): v.append({'code':'UNEXPECTED_STRATEGY_SEMANTICS_MISMATCH','event_id':eid})
    return v
class RangeReader:
    def __init__(self,path):
        self.pf=pq.ParquetFile(path);self.starts=[];s=0
        for i in range(self.pf.num_row_groups):
            n=self.pf.metadata.row_group(i).num_rows;self.starts.append((s,s+n-1,i));s+=n
    def read(self,lo,hi):
        pieces=[]
        for s,e,i in self.starts:
            if e<lo or s>hi: continue
            tab=self.pf.read_row_group(i,columns=['datetime','product','expiry','price','volume','side']).to_pandas();a=max(lo,s)-s;b=min(hi,e)-s+1;sub=tab.iloc[a:b].copy();sub['_seq']=np.arange(max(lo,s),min(hi,e)+1,dtype=np.int64);pieces.append(sub)
        d=pd.concat(pieces,ignore_index=True);dt=pd.to_datetime(d['datetime']);sec=dt.dt.hour*3600+dt.dt.minute*60+dt.dt.second;return d,dt,sec

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--seed',required=True);ap.add_argument('--out',required=True);ap.add_argument('--shard',type=int,required=True);ap.add_argument('--count',type=int,default=2);a=ap.parse_args()
    src=Path(a.source);out=Path(a.out);(out/'daily_events').mkdir(parents=True,exist_ok=True);(out/'daily_regression').mkdir(exist_ok=True)
    seed=json.load(open(a.seed));assert fsha(src)==seed['source_sha256'];days=seed['days'];all_days=sorted(days);eligible=[d for d in all_days if days[d].get('eligible')];work=[d for i,d in enumerate(eligible) if i%a.count==a.shard]
    rr=RangeReader(src);cfg=ScanConfigV4Final(contract_mode='strict');t0=time.time();done=viol=repairs=0
    impl=sha({'reachability':REACHABILITY_VERSION,'repair':CAUSAL_REPAIR_VERSION,'adapter_source_sha256':fsha(ROOT/'server/g2_closeout.py')})
    for day in work:
        ep=out/'daily_events'/f'{day}.json.gz';rp=out/'daily_regression'/f'{day}.json'
        if ep.exists() and rp.exists():
            r=json.load(open(rp));done+=1;viol+=len(r.get('violations',[]));repairs+=len(r.get('expected_repairs',[]));continue
        m=days[day];prev=days[all_days[all_days.index(day)-1]]['profile'];raw,dt,sec=rr.read(int(m['first_seq']),int(m['last_seq']))
        mask=(raw['product'].astype(str)=='MTX')&(raw['expiry'].astype(str)==str(m['contract']))&(sec>=31500)&(sec<=49500)&(dt.dt.strftime('%Y-%m-%d')==day)
        g=raw.loc[mask,['price','volume','side','_seq']].copy();g['dt']=dt.loc[mask].to_numpy();g.reset_index(drop=True,inplace=True)
        if len(g)!=m['rows'] or int(g['_seq'].iloc[0])!=m['first_seq'] or int(g['_seq'].iloc[-1])!=m['last_seq']: raise RuntimeError(f'SEED_RANGE_VERIFY_FAIL {day}')
        base=scan_day_v4_final(g,prev,cfg,src,day,m['contract']);pm=_phys_map(g);new=[];dayrep=[]
        for e in base:
            n,r=apply_g2_closeout(e,g,cfg,pm=pm);new.append(n)
            if r: dayrep.append(r)
        dv=compare(base,new);write_gz(ep,new)
        r={'trading_date':day,'events':len(new),'violations':dv,'expected_repairs':dayrep,'baseline_event_identity_hash':sha(sorted(e['event_id'] for e in base)),'new_event_identity_hash':sha(sorted(e['event_id'] for e in new)),'baseline_strategy_hash':sha([strategy(x) for x in sorted(base,key=lambda z:z['event_id'])]),'new_strategy_hash':sha([strategy(x) for x in sorted(new,key=lambda z:z['event_id'])]),'baseline_relaxed_hash':sha([relaxed(x) for x in sorted(base,key=lambda z:z['event_id'])]),'new_relaxed_hash':sha([relaxed(x) for x in sorted(new,key=lambda z:z['event_id'])]),'new_event_hash':sha(sorted(new,key=lambda z:z['event_id'])),'implementation_identity':impl};dump(rp,r)
        done+=1;viol+=len(dv);repairs+=len(dayrep);dump(out/f'shard_{a.shard}_progress.json',{'completed':done,'total':len(work),'violations':viol,'expected_repairs':repairs,'last_day':day,'elapsed_seconds':round(time.time()-t0,1),'implementation_identity':impl})
        if dv: raise SystemExit(f'VIOLATION {day} {dv[:3]}')
        if done%10==0 or done==len(work): print(json.dumps({'shard':a.shard,'done':done,'total':len(work),'violations':viol,'repairs':repairs,'last_day':day,'elapsed':round(time.time()-t0,1)}),flush=True)
if __name__=='__main__':main()
