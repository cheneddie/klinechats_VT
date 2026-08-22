from __future__ import annotations
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.run_g2_closeout import RangeReader,compare,sha,strategy,relaxed,dump,write_gz,fsha
from server.v4_release_engine import ScanConfigV4Final,scan_day_v4_final
from server.g2_closeout import apply_g2_closeout,_phys_map,REACHABILITY_VERSION,CAUSAL_REPAIR_VERSION
import pandas as pd

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--seed-manifest',required=True);ap.add_argument('--out',required=True);ap.add_argument('--shard-index',type=int,required=True);ap.add_argument('--shard-count',type=int,required=True);a=ap.parse_args()
 src=Path(a.source);out=Path(a.out);(out/'daily_events').mkdir(parents=True,exist_ok=True);(out/'daily_regression').mkdir(exist_ok=True)
 seed=json.load(open(a.seed_manifest));assert fsha(src)==seed['source_sha256'];days=seed['days'];all_days=sorted(days);eligible=[d for d in all_days if days[d].get('eligible')];work=[d for i,d in enumerate(eligible) if i%a.shard_count==a.shard_index]
 rr=RangeReader(src);cfg=ScanConfigV4Final(contract_mode='strict');done=0;viol=0;repairs=0;t0=time.time()
 for day in work:
  ep=out/'daily_events'/f'{day}.json.gz';rp=out/'daily_regression'/f'{day}.json'
  if ep.exists() and rp.exists():
   r=json.load(open(rp));done+=1;viol+=len(r.get('violations',[]));repairs+=len(r.get('expected_repairs',[]));continue
  m=days[day];prev=days[all_days[all_days.index(day)-1]]['profile'];raw,dt,sec=rr.read(m['first_seq'],m['last_seq']);mask=(raw['product'].astype(str)=='MTX')&(raw['expiry'].astype(str)==m['contract'])&(sec>=31500)&(sec<=49500)&(dt.dt.strftime('%Y-%m-%d')==day);g=raw.loc[mask,['price','volume','side','_seq']].copy();g['dt']=dt.loc[mask].to_numpy();g.reset_index(drop=True,inplace=True)
  if len(g)!=m['rows'] or int(g['_seq'].iloc[0])!=m['first_seq'] or int(g['_seq'].iloc[-1])!=m['last_seq']:raise RuntimeError(f'SEED_RANGE_VERIFY_FAIL {day}')
  base=scan_day_v4_final(g,prev,cfg,src,day,m['contract']);pm=_phys_map(g);new=[];dayrep=[]
  for e in base:
   n,r=apply_g2_closeout(e,g,cfg,pm=pm);new.append(n)
   if r:dayrep.append(r)
  dv=compare(base,new,dayrep);write_gz(ep,new)
  impl=sha({'reachability':REACHABILITY_VERSION,'repair':CAUSAL_REPAIR_VERSION,'adapter_source_sha256':fsha(ROOT/'server/g2_closeout.py')})
  r={'trading_date':day,'events':len(new),'violations':dv,'expected_repairs':dayrep,'baseline_event_identity_hash':sha(sorted(e['event_id'] for e in base)),'new_event_identity_hash':sha(sorted(e['event_id'] for e in new)),'baseline_strategy_hash':sha([strategy(x) for x in sorted(base,key=lambda z:z['event_id'])]),'new_strategy_hash':sha([strategy(x) for x in sorted(new,key=lambda z:z['event_id'])]),'baseline_relaxed_hash':sha([relaxed(x) for x in sorted(base,key=lambda z:z['event_id'])]),'new_relaxed_hash':sha([relaxed(x) for x in sorted(new,key=lambda z:z['event_id'])]),'new_event_hash':sha(sorted(new,key=lambda z:z['event_id'])),'implementation_identity':impl};dump(rp,r)
  done+=1;viol+=len(dv);repairs+=len(dayrep);dump(out/f'shard_{a.shard_index}_progress.json',{'shard':a.shard_index,'shard_count':a.shard_count,'completed':done,'total':len(work),'violations':viol,'expected_repairs':repairs,'last_day':day,'elapsed_seconds':round(time.time()-t0,1)})
  if dv: print('VIOLATION',day,dv[:3],flush=True);raise SystemExit(2)
  if done%10==0 or done==len(work):print(json.dumps({'shard':a.shard_index,'completed':done,'total':len(work),'violations':viol,'repairs':repairs,'last_day':day}),flush=True)
if __name__=='__main__':main()
