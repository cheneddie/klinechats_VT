#!/usr/bin/env python3
"""M5 Development 2 physical-tick outcome QA.

Self-test is synthetic and CI-safe. Real mode uses only 2024 M4 frozen events and
raw physical ticks; it does not interpret predictive edge.
"""
from __future__ import annotations
import argparse, hashlib, json, resource, time
from pathlib import Path
import numpy as np
import pandas as pd

from server.poc_absorption.outcomes import FROZEN_HORIZONS
from server.poc_absorption.physical_outcomes import (
    HORIZON_SECONDS,
    PHYSICAL_PATH_SCHEMA_VERSION,
    compute_physical_tick_outcomes_with_diagnostics,
)

AUDIT_SAMPLING_VERSION='M5_DEV2_AUDIT_SAMPLE_V1'
AUDIT_COUNTS={'15s':10,'30s':10,'1m':10,'3m':8,'5m':6,'15m':6}
BENCHMARK_VERSION='M5_DEV2_PERF_BENCH_V1'


def _hash_ids(ids):
    return hashlib.sha256(('\n'.join(map(str,ids))+'\n').encode()).hexdigest()

def deterministic_audit_sample(events:pd.DataFrame,counts=AUDIT_COUNTS):
    selected=[]; candidates=[]
    for tf,n in counts.items():
        c=events.loc[events.timeframe.astype(str).eq(tf)].copy()
        candidates += c.event_id.astype(str).tolist()
        c['_audit_hash']=c.event_id.astype(str).map(lambda x:hashlib.sha256(x.encode()).hexdigest())
        c=c.sort_values(['_audit_hash','event_id'],kind='stable').head(n).drop(columns='_audit_hash')
        if len(c)!=n: raise AssertionError(f'{tf}: need {n} audit events, found {len(c)}')
        selected.append(c)
    out=pd.concat(selected,ignore_index=True)
    provenance={
        'audit_sampling_version':AUDIT_SAMPLING_VERSION,
        'sampling_rule':'per timeframe sort ascending by SHA256(event_id), take frozen N',
        'random_seed':None,
        'counts':counts,
        'candidate_event_ids_hash':_hash_ids(sorted(candidates)),
        'selected_event_ids':out.event_id.astype(str).tolist(),
        'selected_event_ids_hash':_hash_ids(out.event_id.astype(str).tolist()),
    }
    return out,provenance

def _session_end(ts,session):
    ts=pd.Timestamp(ts); d=ts.normalize()
    if session=='day': return d+pd.Timedelta(hours=13,minutes=45)
    if ts.hour>=15: return d+pd.Timedelta(days=1,hours=5)
    return d+pd.Timedelta(hours=5)

def _bruteforce(ev,ticks,horizon):
    trigger=pd.Timestamp(ev.trigger_time); se=_session_end(trigger,ev.session)
    if horizon=='session_end': deadline=se; requested=None; truncated=False
    else:
        requested=HORIZON_SECONDS[horizon]; raw=trigger+pd.Timedelta(seconds=requested); truncated=raw>=se; deadline=min(raw,se)
    mask=(ticks._seq>int(ev.trigger_seq))&(pd.to_datetime(ticks.datetime)<se)&(pd.to_datetime(ticks.datetime)<=deadline)
    w=ticks.loc[mask,['_seq','datetime','price']]
    out={'deadline_time':deadline,'requested_horizon_seconds':requested,'effective_horizon_seconds':max(0,(deadline-trigger).total_seconds()),'truncated_by_session_end':truncated,'future_tick_count':len(w),'window_start_seq':None,'window_end_seq':None,'forward_high':None,'forward_high_seq':None,'forward_high_time':None,'forward_low':None,'forward_low_seq':None,'forward_low_time':None,'short_mfe':None,'mfe_seq':None,'mfe_time':None,'mfe_atr':None,'short_mae':None,'mae_seq':None,'mae_time':None,'mae_atr':None,'time_to_mfe_seconds':None,'time_to_mae_seconds':None}
    if not len(w): return out
    out['window_start_seq']=int(w._seq.iloc[0]); out['window_end_seq']=int(w._seq.iloc[-1])
    mx=float(w.price.max()); mn=float(w.price.min()); hi=w.loc[w.price.eq(mx)].iloc[0]; lo=w.loc[w.price.eq(mn)].iloc[0]
    out.update(forward_high=mx,forward_high_seq=int(hi._seq),forward_high_time=pd.Timestamp(hi.datetime),forward_low=mn,forward_low_seq=int(lo._seq),forward_low_time=pd.Timestamp(lo.datetime))
    mfe=max(float(ev.trigger_price)-mn,0.0); mae=max(mx-float(ev.trigger_price),0.0); out['short_mfe']=mfe; out['short_mae']=mae; out['mfe_atr']=mfe/float(ev.atr); out['mae_atr']=mae/float(ev.atr)
    if mfe>0: out['mfe_seq']=int(lo._seq); out['mfe_time']=pd.Timestamp(lo.datetime); out['time_to_mfe_seconds']=(out['mfe_time']-trigger).total_seconds()
    if mae>0: out['mae_seq']=int(hi._seq); out['mae_time']=pd.Timestamp(hi.datetime); out['time_to_mae_seconds']=(out['mae_time']-trigger).total_seconds()
    return out

def audit(events,ticks,session):
    outcomes,diag=compute_physical_tick_outcomes_with_diagnostics(events,ticks,contract=str(events.contract.iloc[0]),session=session)
    by=outcomes.set_index('event_id'); rows=[]; mismatches=0
    for ev in events.itertuples(index=False):
        got=by.loc[ev.event_id]
        for h in FROZEN_HORIZONS:
            ref=_bruteforce(ev,ticks,h); p='h_'+h
            def int_or_none(x): return None if pd.isna(x) else int(x)
            def ts_or_none(x): return None if pd.isna(x) else pd.Timestamp(x)
            checks={
                'future_tick_count':int(got[p+'_future_tick_count'])==ref['future_tick_count'],
                'window_start_seq':int_or_none(got[p+'_window_start_seq'])==ref['window_start_seq'],
                'window_end_seq':int_or_none(got[p+'_window_end_seq'])==ref['window_end_seq'],
                'deadline_time':pd.Timestamp(got[p+'_deadline_time'])==pd.Timestamp(ref['deadline_time']),
                'forward_high':(pd.isna(got[p+'_forward_high']) and ref['forward_high'] is None) or (ref['forward_high'] is not None and float(got[p+'_forward_high'])==ref['forward_high']),
                'forward_high_seq':int_or_none(got[p+'_forward_high_seq'])==ref['forward_high_seq'],
                'forward_high_time':ts_or_none(got[p+'_forward_high_time'])==ref['forward_high_time'],
                'forward_low':(pd.isna(got[p+'_forward_low']) and ref['forward_low'] is None) or (ref['forward_low'] is not None and float(got[p+'_forward_low'])==ref['forward_low']),
                'forward_low_seq':int_or_none(got[p+'_forward_low_seq'])==ref['forward_low_seq'],
                'forward_low_time':ts_or_none(got[p+'_forward_low_time'])==ref['forward_low_time'],
                'mfe_seq':int_or_none(got[p+'_mfe_seq'])==ref['mfe_seq'],
                'mae_seq':int_or_none(got[p+'_mae_seq'])==ref['mae_seq'],
            }
            ok=all(checks.values()); mismatches += 0 if ok else 1
            rows.append({'event_id':ev.event_id,'timeframe':ev.timeframe,'trigger_seq':int(ev.trigger_seq),'trigger_time':ev.trigger_time,'trigger_price':float(ev.trigger_price),'atr':float(ev.atr),'horizon':h,**ref,'pass':ok})
    return outcomes,pd.DataFrame(rows),mismatches,diag

def _materialize_case(parquet:Path,dates:list[str],expiry:str,session:str,timeframes:list[str],dataset_id='MTX_2024'):
    from server.poc_absorption.bars import build_bars
    from server.poc_absorption.features import attach_pressure_features,compute_bar_features,compute_pressure_features,compute_structural_high_zone_features
    from server.poc_absorption.universe import HighPriceProbeConfig,build_high_price_probe_universe
    from tools.poc_absorption.m3_feature_qa import read_ticks
    ticks,meta=read_ticks(parquet,dates,expiry,'MTX',session)
    cfg=HighPriceProbeConfig(); keys=['timeframe','session','bar_start_seq','bar_end_seq']; frames=[]; parity={}
    for tf in timeframes:
        bars=build_bars(ticks.drop(columns=['product','expiry','side'],errors='ignore'),tf,session,atr_period=14)
        bf=compute_bar_features(bars); pf=compute_pressure_features(ticks,tf,session); full=attach_pressure_features(bf,pf); sf=compute_structural_high_zone_features(ticks,bf,lookback=24); full=full.merge(sf,on=keys,how='left',validate='one_to_one')
        if session=='night':
            bs=pd.to_datetime(full.bar_start); full['trading_date']=(bs.dt.normalize()+pd.to_timedelta((bs.dt.hour>=15).astype(int),unit='D')).dt.date.astype(str)
        else: full['trading_date']=pd.to_datetime(full.bar_start).dt.date.astype(str)
        part='_'.join(dates)+f'_{session}_{tf}'; u=build_high_price_probe_universe(full,ticks[['_seq','datetime','price']],dataset_id=dataset_id,contract=expiry,partition_id=part,config=cfg)
        frames.append(u.triggers); parity[tf]={'bars':len(full),'raw_triggers':len(u.triggers),'episodes':len(u.episodes)}
    return ticks,pd.concat(frames,ignore_index=True),parity,meta

def choose_night_sample(events):
    chosen=[]; cross=events[(pd.to_datetime(events.trigger_time)>=pd.Timestamp('2024-08-15 23:50'))&(pd.to_datetime(events.trigger_time)<pd.Timestamp('2024-08-16 00:00'))]
    for tf in ['15s','1m','5m']:
        c=cross[cross.timeframe.eq(tf)].sort_values(['trigger_time','event_id'],kind='stable')
        if len(c): chosen.append(c.head(2))
    near=events[(pd.to_datetime(events.trigger_time)>=pd.Timestamp('2024-08-16 04:40'))&(pd.to_datetime(events.trigger_time)<pd.Timestamp('2024-08-16 05:00'))]
    for tf in ['30s','3m','15m']:
        c=near[near.timeframe.eq(tf)].sort_values(['trigger_time','event_id'],ascending=[False,True],kind='stable')
        if len(c): chosen.append(c.head(2))
    out=pd.concat(chosen,ignore_index=True).drop_duplicates('event_id') if chosen else pd.DataFrame()
    if len(out)<6: raise AssertionError('night QA could not find >=6 boundary events')
    return out

def benchmark(day_events,day_ticks,target=10_000):
    reps=[]
    for i in range((target+len(day_events)-1)//len(day_events)):
        z=day_events.copy(); z['event_id']=[f'{v}_bench{i:03d}' for v in z.event_id]; reps.append(z)
    events=pd.concat(reps,ignore_index=True).head(target)
    rss0=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; t0=time.perf_counter(); _,diag=compute_physical_tick_outcomes_with_diagnostics(events,day_ticks,contract='202408',session='day'); wall=time.perf_counter()-t0; rss1=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    index_tps=diag.physical_ticks_indexed/diag.extrema_index_build_seconds; qeps=target/(diag.range_query_seconds+diag.output_finalize_seconds)
    est_idx=50_862_751/index_tps; est_query=505_448/qeps; est=est_idx+est_query
    return {'benchmark_version':BENCHMARK_VERSION,'source':'10,000 deterministic replicated frozen events over real 2024-08-15+16 day physical ticks; performance-only, no research inference','physical_ticks':len(day_ticks),'events':target,'outcome_windows':target*8,'wall_seconds':wall,'events_per_sec_total':target/wall,'windows_per_sec_total':target*8/wall,**diag.as_dict(),'index_ticks_per_sec':index_tps,'query_plus_materialize_events_per_sec':qeps,'ru_maxrss_kb_before':rss0,'ru_maxrss_kb_after':rss1,'estimated_2024_physical_rows':50_862_751,'estimated_2024_events':505_448,'estimated_2024_windows':4_043_584,'estimated_full_2024_index_seconds':est_idx,'estimated_full_2024_query_materialize_seconds':est_query,'estimated_full_2024_engine_seconds':est,'algorithm':'session-partitioned vectorized segment-tree RMQ; each session tick indexed once; horizon range queries batched; exact first physical position on price ties','verdict':'FULL_YEAR_SCALE_FEASIBLE' if est<3600 else 'REQUIRES_INDEX_OPTIMIZATION'}

def self_test():
    rows=[]
    for i,p in enumerate([100,99,102,98,101]): rows.append((10+i,pd.Timestamp('2026-08-03 09:00:00')+pd.Timedelta(seconds=i),p,'202608'))
    ticks=pd.DataFrame(rows,columns=['_seq','datetime','price','expiry'])
    event=pd.DataFrame([{'event_schema_version':'POC_PROBE_EVENT_V1','universe_version':'HIGH_PRICE_PROBE_V1','universe_schema_version':'POC_HIGH_PRICE_PROBE_UNIVERSE_V1','universe_config_hash':'d7bf39afa32582bc06e00b2df9995b9cb9cc14670a6974834d80cf3d079016fb','feature_schema_version':'POC_CONTINUOUS_FEATURES_V1','event_id':'trigger_self','episode_id':'episode_self','episode_trigger_number':1,'dataset_id':'SYNTH','contract':'202608','partition_id':'self','session':'day','timeframe':'1m','trigger_seq':10,'trigger_time':pd.Timestamp('2026-08-03 09:00:00'),'trigger_price':100.0,'atr':4.0,'bar_start_seq':10,'bar_end_seq':10}])
    out,ledger,mismatch,diag=audit(event,ticks,'day'); r=out.iloc[0]
    ok=mismatch==0 and len(ledger)==8 and r.h_30s_forward_high==102 and r.h_30s_forward_low==98 and r.h_30s_mfe_seq==13 and r.h_30s_mae_seq==12
    return {'schema_version':'POC_M5_DEV2_SELF_TEST_V1','physical_path_schema_version':PHYSICAL_PATH_SCHEMA_VERSION,'future_tick_rule':'_seq > trigger_seq','events':1,'audit_windows':8,'audit_mismatches':mismatch,'diagnostics':diag.as_dict(),'all_pass':bool(ok)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); ap.add_argument('--parquet',type=Path); ap.add_argument('--output-dir',type=Path,default=Path('reports/poc_absorption/m5_dev2_real_qa_runtime')); a=ap.parse_args()
    if a.self_test:
        r=self_test(); print(json.dumps(r,indent=2,default=str)); raise SystemExit(0 if r['all_pass'] else 2)
    if not a.parquet: ap.error('--parquet required unless --self-test')
    outdir=a.output_dir; outdir.mkdir(parents=True,exist_ok=True)
    day_ticks,day_events,day_parity,day_meta=_materialize_case(a.parquet,['2024-08-15','2024-08-16'],'202408','day',['15s','30s','1m','3m','5m','15m'])
    expected={'15s':471,'30s':237,'1m':108,'3m':36,'5m':31,'15m':16}
    if {k:int(v['raw_triggers']) for k,v in day_parity.items()}!=expected: raise AssertionError(f'M4 day parity drift: {day_parity}')
    sample,prov=deterministic_audit_sample(day_events); _,day_ledger,day_mismatch,day_diag=audit(sample,day_ticks,'day'); day_ledger.to_csv(outdir/'M5_DEV2_AUDIT_LEDGER_2024_DAY_400.csv',index=False); (outdir/'M5_DEV2_AUDIT_SAMPLE_PROVENANCE.json').write_text(json.dumps(prov,indent=2))
    night_ticks,night_events,night_parity,night_meta=_materialize_case(a.parquet,['2024-08-16'],'202408','night',['15s','30s','1m','3m','5m','15m']); ns=choose_night_sample(night_events); _,night_ledger,night_mismatch,night_diag=audit(ns,night_ticks,'night'); night_ledger.to_csv(outdir/'M5_DEV2_REAL_NIGHT_AUDIT_LEDGER.csv',index=False)
    nt=pd.to_datetime(ns.trigger_time); cross=int(((nt>=pd.Timestamp('2024-08-15 23:50'))&(nt<pd.Timestamp('2024-08-16 00:00'))).sum()); near=int((nt>=pd.Timestamp('2024-08-16 04:40')).sum())
    bench=benchmark(day_events,day_ticks); (outdir/'M5_DEV2_PERFORMANCE_BENCHMARK.json').write_text(json.dumps(bench,indent=2,default=str))
    result={'schema_version':'POC_M5_DEV2_REAL_QA_V1','verdict':'M5_DEV2_EXACT_PHYSICAL_OUTCOME_PASS','day':{'physical_ticks':len(day_ticks),'events':len(day_events),'parity':day_parity,'audit_windows':len(day_ledger),'audit_mismatches':day_mismatch,'sampling':prov,'diagnostics':day_diag.as_dict(),'meta':day_meta},'night':{'physical_ticks':len(night_ticks),'events':len(night_events),'parity':night_parity,'selected_events':len(ns),'selected_timeframes':sorted(ns.timeframe.unique().tolist()),'cross_midnight_events':cross,'near_0500_events':near,'audit_windows':len(night_ledger),'audit_mismatches':night_mismatch,'selected_event_ids':ns.event_id.tolist(),'diagnostics':night_diag.as_dict(),'meta':night_meta},'benchmark':bench,'m5_milestone_complete':False,'development_3_started':False}
    result['all_pass']=bool(day_mismatch==0 and len(day_ledger)==400 and night_mismatch==0 and cross>=1 and near>=1 and len(result['night']['selected_timeframes'])>=3 and bench['verdict']=='FULL_YEAR_SCALE_FEASIBLE')
    (outdir/'M5_DEV2_REAL_QA_SUMMARY.json').write_text(json.dumps(result,indent=2,default=str)); print(json.dumps(result,indent=2,default=str)); raise SystemExit(0 if result['all_pass'] else 2)
if __name__=='__main__': main()
