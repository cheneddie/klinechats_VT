#!/usr/bin/env python3
"""M5 Development 3 continuous Balance measurement QA.

CI self-test is synthetic. Real mode is 2024-only and reports measurement
correctness/distributions; it defines no signal threshold and makes no edge claim.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
from server.poc_absorption.outcomes import FROZEN_HORIZONS
from server.poc_absorption.balance_outcomes import (
    BALANCE_METRICS, BALANCE_SCHEMA_VERSION, BALANCE_REFERENCE_SCHEMA_VERSION,
    build_balance_reference_manifest, compute_balance_outcomes,
)
from tools.poc_absorption.m5_physical_outcome_qa import (
    _materialize_case, deterministic_audit_sample, choose_night_sample, _session_end,
)

COUNT_METRICS={"one_second_close_count","raw_tick_high_retest_count","high_retest_count","raw_tick_range_cross_count","range_cross_count"}
AUDIT_METRICS=list(BALANCE_METRICS)
DIST_METRICS=["raw_tick_path_efficiency","one_second_path_efficiency","future_range_atr","up_excursion_atr","down_excursion_atr","two_sided_min_excursion_atr","high_retest_count","raw_tick_high_retest_count","range_cross_count","raw_tick_range_cross_count","time_above_trigger_fraction","time_below_trigger_fraction"]


def _bruteforce_balance(ev,ticks,horizon):
    trigger=pd.Timestamp(ev.trigger_time); se=_session_end(trigger,ev.session)
    seconds={"30s":30,"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"60m":3600}
    deadline=se if horizon=='session_end' else min(trigger+pd.Timedelta(seconds=seconds[horizon]),se)
    dt=pd.to_datetime(ticks.datetime,format='mixed')
    w=ticks.loc[(ticks._seq>int(ev.trigger_seq))&(dt<se)&(dt<=deadline),['_seq','datetime','price']].copy()
    out={m:np.nan for m in AUDIT_METRICS}
    if not len(w): return out
    tp=float(ev.trigger_price); atr=float(ev.atr); rh=float(ev.rolling_high); fp=w.price.to_numpy(float); fdt=pd.to_datetime(w.datetime,format='mixed')
    raw=np.r_[tp,fp]; total=float(np.abs(np.diff(raw)).sum()); net=float(fp[-1]-tp); hi=float(fp.max()); lo=float(fp.min()); up=max(hi-tp,0.0)/atr; down=max(tp-lo,0.0)/atr
    out.update(raw_tick_total_path_points=total,raw_tick_path_efficiency=(abs(net)/total if total>0 else np.nan),net_move_points=net,net_move_atr=net/atr,up_excursion_atr=up,down_excursion_atr=down,future_range_atr=(hi-lo)/atr,two_sided_min_excursion_atr=min(up,down),two_sided_total_excursion_atr=up+down)
    w['_second']=fdt.dt.floor('s'); close=w.groupby('_second',sort=False).tail(1).price.to_numpy(float); one=np.r_[tp,close]; tot1=float(np.abs(np.diff(one)).sum()); out['one_second_close_count']=len(close); out['one_second_total_path_points']=tot1; out['one_second_path_efficiency']=abs(float(close[-1]-tp))/tot1 if tot1>0 else np.nan
    times=[trigger]+fdt.tolist()+[deadline]; states=np.r_[tp,fp]; dur=np.array([max(0.0,(times[i+1]-times[i]).total_seconds()) for i in range(len(states))]); effective=max(0.0,(deadline-trigger).total_seconds()); above=float(dur[states>tp].sum()); below=float(dur[states<tp].sum()); equal=float(dur[states==tp].sum()); out['time_above_trigger_seconds']=above; out['time_below_trigger_seconds']=below; out['time_at_trigger_seconds']=equal
    if effective>0: out['time_above_trigger_fraction']=above/effective; out['time_below_trigger_fraction']=below/effective; out['time_at_trigger_fraction']=equal/effective
    def retest(vals):
        z=np.asarray(vals)>=rh; return int(np.sum((~z[:-1])&z[1:]))
    def cross(vals):
        signs=np.sign(np.asarray(vals)-tp); nz=signs[signs!=0]; return int(np.sum(nz[1:]!=nz[:-1])) if len(nz)>=2 else 0
    out['raw_tick_high_retest_count']=retest(raw); out['high_retest_count']=retest(one); out['raw_tick_range_cross_count']=cross(fp); out['range_cross_count']=cross(close)
    return out


def audit_balance(events,ticks,session):
    out=compute_balance_outcomes(events,ticks,contract=str(events.contract.iloc[0]),session=session)
    by=out.set_index('event_id'); rows=[]; mismatches=0
    for ev in events.itertuples(index=False):
        got=by.loc[ev.event_id]
        for h in FROZEN_HORIZONS:
            ref=_bruteforce_balance(ev,ticks,h); p='h_'+h; bad=[]
            for metric in AUDIT_METRICS:
                gv=got[p+'_'+metric]; rv=ref[metric]
                if pd.isna(gv) and pd.isna(rv): continue
                if pd.isna(gv) != pd.isna(rv): bad.append(metric); continue
                if metric in COUNT_METRICS: ok=int(gv)==int(rv)
                else: ok=np.isclose(float(gv),float(rv),rtol=0,atol=1e-12,equal_nan=True)
                if not ok: bad.append(metric)
            mismatches += 1 if bad else 0
            rows.append({'event_id':ev.event_id,'timeframe':ev.timeframe,'trigger_seq':int(ev.trigger_seq),'trigger_time':ev.trigger_time,'horizon':h,'future_tick_count':int(got[p+'_future_tick_count']),'mismatch_fields':'|'.join(bad),'pass':not bad})
    return out,pd.DataFrame(rows),mismatches


def _distribution(out):
    rows=[]
    for h in FROZEN_HORIZONS:
        p='h_'+h
        for metric in DIST_METRICS:
            v=pd.to_numeric(out[p+'_'+metric],errors='coerce').dropna(); q=v.quantile([.1,.25,.5,.75,.9]) if len(v) else pd.Series(dtype=float)
            rows.append({'horizon':h,'metric':metric,'n':int(len(v)),'missing':int(len(out)-len(v)),'p10':float(q.get(.1,np.nan)),'p25':float(q.get(.25,np.nan)),'median':float(q.get(.5,np.nan)),'p75':float(q.get(.75,np.nan)),'p90':float(q.get(.9,np.nan))})
    return pd.DataFrame(rows)


def self_test():
    ticks=pd.DataFrame([(10,'2026-08-03 09:00:00',100,'202608'),(11,'2026-08-03 09:00:00',101,'202608'),(12,'2026-08-03 09:00:00',99,'202608'),(13,'2026-08-03 09:00:01',103,'202608')],columns=['_seq','datetime','price','expiry'])
    events=pd.DataFrame([{'event_schema_version':'POC_PROBE_EVENT_V1','universe_version':'HIGH_PRICE_PROBE_V1','universe_schema_version':'POC_HIGH_PRICE_PROBE_UNIVERSE_V1','universe_config_hash':'d7bf39afa32582bc06e00b2df9995b9cb9cc14670a6974834d80cf3d079016fb','feature_schema_version':'POC_CONTINUOUS_FEATURES_V1','event_id':'trigger_balance_self','episode_id':'episode_balance_self','episode_trigger_number':1,'dataset_id':'SYNTH','contract':'202608','partition_id':'self','session':'day','timeframe':'1m','trigger_seq':10,'trigger_time':pd.Timestamp('2026-08-03 09:00:00'),'trigger_price':100.0,'atr':4.0,'bar_start_seq':10,'bar_end_seq':10,'rolling_high':102.0}])
    out,ledger,mismatch=audit_balance(events,ticks,'day'); r=out.iloc[0]; manifest=build_balance_reference_manifest(events)
    ok=mismatch==0 and len(ledger)==8 and r.h_30s_raw_tick_path_efficiency!=r.h_30s_one_second_path_efficiency and manifest['event_count']==1
    return {'schema_version':'POC_M5_DEV3_SELF_TEST_V1','balance_schema_version':BALANCE_SCHEMA_VERSION,'balance_reference_schema_version':BALANCE_REFERENCE_SCHEMA_VERSION,'events':1,'audit_windows':8,'audit_mismatches':mismatch,'thresholds_defined':False,'classification_defined':False,'all_pass':bool(ok)}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); ap.add_argument('--parquet',type=Path); ap.add_argument('--output-dir',type=Path,default=Path('reports/poc_absorption/m5_dev3_real_qa_runtime')); a=ap.parse_args()
    if a.self_test:
        r=self_test(); print(json.dumps(r,indent=2)); raise SystemExit(0 if r['all_pass'] else 2)
    if not a.parquet: ap.error('--parquet required unless --self-test')
    a.output_dir.mkdir(parents=True,exist_ok=True)
    day_ticks,day_events,parity,_=_materialize_case(a.parquet,['2024-08-15','2024-08-16'],'202408','day',['15s','30s','1m','3m','5m','15m'])
    expected={'15s':471,'30s':237,'1m':108,'3m':36,'5m':31,'15m':16}
    if {k:int(v['raw_triggers']) for k,v in parity.items()}!=expected: raise AssertionError(f'M4 parity drift: {parity}')
    all_day=compute_balance_outcomes(day_events,day_ticks,contract='202408',session='day'); dist=_distribution(all_day); dist.to_csv(a.output_dir/'M5_DEV3_BALANCE_DISTRIBUTION.csv',index=False)
    sample,prov=deterministic_audit_sample(day_events); _,day_ledger,day_mismatch=audit_balance(sample,day_ticks,'day'); day_ledger.to_csv(a.output_dir/'M5_DEV3_BALANCE_AUDIT_LEDGER_DAY_400.csv',index=False)
    night_ticks,night_events,_,_=_materialize_case(a.parquet,['2024-08-16'],'202408','night',['15s','30s','1m','3m','5m','15m']); ns=choose_night_sample(night_events); _,night_ledger,night_mismatch=audit_balance(ns,night_ticks,'night'); night_ledger.to_csv(a.output_dir/'M5_DEV3_BALANCE_AUDIT_LEDGER_NIGHT.csv',index=False)
    manifest=build_balance_reference_manifest(day_events); (a.output_dir/'M5_DEV3_BALANCE_REFERENCE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    result={'schema_version':'POC_M5_DEV3_REAL_QA_V1','verdict':'M5_DEV3_BALANCE_MEASUREMENT_PASS','dataset_id':'MTX_2024','day_events':len(day_events),'day_physical_ticks':len(day_ticks),'day_audit_events':len(sample),'day_audit_windows':len(day_ledger),'day_audit_mismatches':day_mismatch,'night_events':len(night_events),'night_physical_ticks':len(night_ticks),'night_audit_events':len(ns),'night_audit_windows':len(night_ledger),'night_audit_mismatches':night_mismatch,'reference_manifest':manifest,'sample_provenance':prov,'thresholds_defined':False,'classification_defined':False,'research_edge_claimed':False,'all_pass':day_mismatch==0 and night_mismatch==0 and len(day_events)==899}
    (a.output_dir/'M5_DEV3_REAL_QA_SUMMARY.json').write_text(json.dumps(result,indent=2,default=str)+'\n'); print(json.dumps(result,indent=2,default=str)); raise SystemExit(0 if result['all_pass'] else 2)
if __name__=='__main__': main()
