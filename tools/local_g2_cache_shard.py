from pathlib import Path
import argparse,json,time,sys,hashlib
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server.v4_release_engine import ScanConfigV4Final,scan_day_v4_final
from server.g2_closeout import apply_g2_closeout,_phys_map,REACHABILITY_VERSION,CAUSAL_REPAIR_VERSION
from tools.local_g2_shard import sha,fsha,dump,write_gz,strategy,relaxed,compare

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--seed',required=True);ap.add_argument('--cache',required=True);ap.add_argument('--out',required=True);ap.add_argument('--shard',type=int,required=True);ap.add_argument('--count',type=int,default=2);a=ap.parse_args()
 src=Path(a.source);out=Path(a.out);cache=Path(a.cache);seed=json.load(open(a.seed));assert fsha(src)==seed['source_sha256'];days=seed['days'];all_days=sorted(days);eligible=[d for d in all_days if days[d].get('eligible')];work=[d for i,d in enumerate(eligible) if i%a.count==a.shard]
 cfg=ScanConfigV4Final(contract_mode='strict');t0=time.time();done=viol=repairs=0;impl=sha({'reachability':REACHABILITY_VERSION,'repair':CAUSAL_REPAIR_VERSION,'adapter_source_sha256':fsha(ROOT/'server/g2_closeout.py')})
 for day in work:
  ep=out/'daily_events'/f'{day}.json.gz';rp=out/'daily_regression'/f'{day}.json'
  if ep.exists() and rp.exists():
   r=json.load(open(rp));
   if r.get('implementation_identity')!=impl: raise RuntimeError(f'IMPL_ID_MISMATCH {day}')
   done+=1;viol+=len(r.get('violations',[]));repairs+=len(r.get('expected_repairs',[]));continue
  m=days[day];g=pd.read_feather(cache/f'{day}.feather');g['dt']=pd.to_datetime(g['dt'])
  if len(g)!=m['rows'] or int(g['_seq'].iloc[0])!=m['first_seq'] or int(g['_seq'].iloc[-1])!=m['last_seq']:raise RuntimeError(f'CACHE_RANGE_VERIFY_FAIL {day}')
  prev=days[all_days[all_days.index(day)-1]]['profile'];base=scan_day_v4_final(g,prev,cfg,src,day,m['contract']);pm=_phys_map(g);new=[];dayrep=[]
  for e in base:
   n,r=apply_g2_closeout(e,g,cfg,pm=pm);new.append(n)
   if r:dayrep.append(r)
  dv=compare(base,new);write_gz(ep,new)
  r={'trading_date':day,'events':len(new),'violations':dv,'expected_repairs':dayrep,'baseline_event_identity_hash':sha(sorted(e['event_id'] for e in base)),'new_event_identity_hash':sha(sorted(e['event_id'] for e in new)),'baseline_strategy_hash':sha([strategy(x) for x in sorted(base,key=lambda z:z['event_id'])]),'new_strategy_hash':sha([strategy(x) for x in sorted(new,key=lambda z:z['event_id'])]),'baseline_relaxed_hash':sha([relaxed(x) for x in sorted(base,key=lambda z:z['event_id'])]),'new_relaxed_hash':sha([relaxed(x) for x in sorted(new,key=lambda z:z['event_id'])]),'new_event_hash':sha(sorted(new,key=lambda z:z['event_id'])),'implementation_identity':impl};dump(rp,r)
  done+=1;viol+=len(dv);repairs+=len(dayrep);dump(out/f'cache_shard_{a.shard}_progress.json',{'completed':done,'total':len(work),'violations':viol,'expected_repairs':repairs,'last_day':day,'elapsed_seconds':round(time.time()-t0,1),'implementation_identity':impl})
  if dv: raise SystemExit(f'VIOLATION {day} {dv[:3]}')
  if done%10==0 or done==len(work):print(json.dumps({'shard':a.shard,'done':done,'total':len(work),'violations':viol,'repairs':repairs,'last_day':day,'elapsed':round(time.time()-t0,1)}),flush=True)
if __name__=='__main__':main()
