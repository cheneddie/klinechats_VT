#!/usr/bin/env python3
"""M5 Dev4 frozen-reference reversal QA. CI self-test is synthetic; real mode is 2024-only."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

from server.poc_absorption.bars import build_bars
from server.poc_absorption.outcomes import FROZEN_HORIZONS
from server.poc_absorption.reversal_outcomes import (
    REVERSAL_SCHEMA_VERSION, REVERSAL_REFERENCE_SCHEMA_VERSION,
    MICRO_SWING_ALGORITHM_VERSION, build_reversal_reference_store,
    build_reversal_reference_manifest, compute_reversal_outcomes,
)
from tools.poc_absorption.m5_physical_outcome_qa import (
    HORIZON_SECONDS, _materialize_case, deterministic_audit_sample,
    choose_night_sample, _session_end,
)

RATE_METRICS=("made_new_high","break_channel_midline","break_micro_swing_low","break_channel_low","any_structure_break","new_high_before_first_break")
QUANT_METRICS=("time_to_first_break_seconds","time_to_new_high_seconds","adverse_extension_before_reversal_atr","time_to_peak_after_trigger_seconds","time_peak_to_structure_break_seconds","forward_slope_atr_1s_step","forward_r2_1s")


def _bars_for_reference(ticks,session,timeframes):
    source=ticks.drop(columns=['product','expiry','side'],errors='ignore')
    return {tf:pd.DataFrame([b.as_dict() for b in build_bars(source,tf,session,atr_period=14)]) for tf in timeframes}

def _deadline(trigger,session,h):
    se=_session_end(trigger,session)
    return se if h=='session_end' else min(pd.Timestamp(trigger)+pd.Timedelta(seconds=HORIZON_SECONDS[h]),se)

def _empty():
    d={'made_new_high':None,'new_high_seq':None,'new_high_time':pd.NaT,'new_high_price':np.nan,'time_to_new_high_seconds':np.nan,
       'any_structure_break':None,'first_structure_break_references':None,'first_structure_break_seq':None,'first_structure_break_time':pd.NaT,'first_structure_break_price':np.nan,'time_to_first_break_seconds':np.nan,
       'pre_break_peak_seq':None,'pre_break_peak_time':pd.NaT,'pre_break_peak_price':np.nan,'time_to_peak_after_trigger_seconds':np.nan,'time_peak_to_structure_break_seconds':np.nan,
       'adverse_extension_before_reversal_points':np.nan,'adverse_extension_before_reversal_atr':np.nan,'new_high_before_first_break':None,
       'forward_slope_1s_step':np.nan,'forward_slope_atr_1s_step':np.nan,'forward_r2_1s':np.nan}
    for n in ('channel_midline','micro_swing_low','channel_low'):
        d.update({f'break_{n}':None,f'{n}_break_seq':None,f'{n}_break_time':pd.NaT,f'{n}_break_price':np.nan,f'time_to_{n}_break_seconds':np.nan})
    return d

def _bruteforce(ev,ref,ticks,h):
    """Independent pandas/raw-mask reference; never calls the production Dev4 measurement helper."""
    trigger=pd.Timestamp(ev.trigger_time); se=_session_end(trigger,ev.session); deadline=_deadline(trigger,ev.session,h)
    dt=pd.to_datetime(ticks.datetime,format='mixed')
    w=ticks.loc[(ticks._seq>int(ev.trigger_seq))&(dt<se)&(dt<=deadline),['_seq','datetime','price']].copy(); out=_empty()
    if w.empty:return out,0
    w['datetime']=pd.to_datetime(w.datetime,format='mixed'); tp=float(ev.trigger_price); atr=float(ev.atr)
    w['_second']=w.datetime.dt.floor('s'); close=w.groupby('_second',sort=False).tail(1).price.to_numpy(float)
    if len(close)>=2:
        x=np.arange(len(close),dtype=float); y=close; xc=x-x.mean(); yc=y-y.mean(); beta=float((xc@yc)/(xc@xc)); fit=y.mean()+beta*xc; sst=float(yc@yc); ssr=float(((y-fit)**2).sum()); r2=1.0 if sst==0 and ssr==0 else (np.nan if sst==0 else 1.0-ssr/sst)
        out['forward_slope_1s_step']=beta; out['forward_slope_atr_1s_step']=beta/atr; out['forward_r2_1s']=r2
    nh=w.loc[w.price>float(ref.channel_high_reference_level)]; nseq=None
    if len(nh):
        q=nh.iloc[0]; nseq=int(q._seq); nt=pd.Timestamp(q.datetime); pr=float(q.price); out.update(made_new_high=True,new_high_seq=nseq,new_high_time=nt,new_high_price=pr,time_to_new_high_seconds=(nt-trigger).total_seconds())
    else:out['made_new_high']=False
    first=[]
    defs=(('channel_midline',ref.channel_midline_reference_level,bool(ref.channel_midline_break_eligible)),('micro_swing_low',ref.micro_swing_low_reference_level,bool(ref.micro_swing_break_eligible)),('channel_low',ref.channel_low_reference_level,bool(ref.channel_low_break_eligible)))
    for name,level,eligible in defs:
        if not eligible or pd.isna(level):continue
        q=w.loc[w.price<float(level)]
        if q.empty:out[f'break_{name}']=False;continue
        z=q.iloc[0]; s=int(z._seq); tm=pd.Timestamp(z.datetime); pr=float(z.price); first.append((name,s,tm,pr)); out[f'break_{name}']=True; out[f'{name}_break_seq']=s; out[f'{name}_break_time']=tm; out[f'{name}_break_price']=pr; out[f'time_to_{name}_break_seconds']=(tm-trigger).total_seconds()
    if not first:out['any_structure_break']=False;return out,len(w)
    first_seq=min(x[1] for x in first); same=[x for x in first if x[1]==first_seq]; bs=first_seq; bt=same[0][2]; bp=same[0][3]
    out.update(any_structure_break=True,first_structure_break_references='|'.join(x[0] for x in same),first_structure_break_seq=bs,first_structure_break_time=bt,first_structure_break_price=bp,time_to_first_break_seconds=(bt-trigger).total_seconds())
    pre=w.loc[w._seq<bs]
    if len(pre) and float(pre.price.max())>tp:
        mx=float(pre.price.max()); q=pre.loc[pre.price.eq(mx)].iloc[0]; ps=int(q._seq); pt=pd.Timestamp(q.datetime)
    else:mx=tp;ps=int(ev.trigger_seq);pt=trigger
    ext=max(mx-tp,0.0); out.update(pre_break_peak_seq=ps,pre_break_peak_time=pt,pre_break_peak_price=mx,time_to_peak_after_trigger_seconds=(pt-trigger).total_seconds(),time_peak_to_structure_break_seconds=(bt-pt).total_seconds(),adverse_extension_before_reversal_points=ext,adverse_extension_before_reversal_atr=ext/atr,new_high_before_first_break=bool(nseq is not None and nseq<bs))
    return out,len(w)

def _same(a,b,name):
    if pd.isna(a) and pd.isna(b):return True
    if pd.isna(a)!=pd.isna(b):return False
    if name.endswith('_time'):return pd.Timestamp(a)==pd.Timestamp(b)
    if name.endswith('_seq'):return int(a)==int(b)
    if name=='first_structure_break_references':return str(a)==str(b)
    if name.startswith('break_') or name in {'made_new_high','any_structure_break','new_high_before_first_break'}:return bool(a)==bool(b)
    return bool(np.isclose(float(a),float(b),rtol=0,atol=1e-10,equal_nan=True))

def audit(events,ticks,references,session):
    out=compute_reversal_outcomes(events,ticks,references,contract=str(events.contract.iloc[0]),session=session); by=out.set_index('event_id'); ref=references.set_index('event_id'); rows=[]; mismatches=0
    fields=['made_new_high','new_high_seq','new_high_time','new_high_price','time_to_new_high_seconds','break_channel_midline','channel_midline_break_seq','channel_midline_break_time','channel_midline_break_price','time_to_channel_midline_break_seconds','break_micro_swing_low','micro_swing_low_break_seq','micro_swing_low_break_time','micro_swing_low_break_price','time_to_micro_swing_low_break_seconds','break_channel_low','channel_low_break_seq','channel_low_break_time','channel_low_break_price','time_to_channel_low_break_seconds','any_structure_break','first_structure_break_references','first_structure_break_seq','first_structure_break_time','first_structure_break_price','time_to_first_break_seconds','pre_break_peak_seq','pre_break_peak_time','pre_break_peak_price','time_to_peak_after_trigger_seconds','time_peak_to_structure_break_seconds','adverse_extension_before_reversal_points','adverse_extension_before_reversal_atr','new_high_before_first_break','forward_slope_1s_step','forward_slope_atr_1s_step','forward_r2_1s']
    for ev in events.itertuples(index=False):
        got=by.loc[ev.event_id]; rr=ref.loc[ev.event_id]
        for h in FROZEN_HORIZONS:
            exp,count=_bruteforce(ev,rr,ticks,h); p='h_'+h; bad=[]
            if int(got[p+'_future_tick_count'])!=count:bad.append('future_tick_count')
            for f in fields:
                if not _same(got[p+'_'+f],exp[f],f):bad.append(f)
            mismatches+=1 if bad else 0; rows.append({'event_id':ev.event_id,'timeframe':ev.timeframe,'trigger_seq':int(ev.trigger_seq),'trigger_time':ev.trigger_time,'horizon':h,'future_tick_count':count,'mismatch_fields':'|'.join(bad),'pass':not bad})
    return out,pd.DataFrame(rows),mismatches

def distributions(out,by_timeframe=False):
    rows=[]
    for h in FROZEN_HORIZONS:
        for tf in (sorted(out.timeframe.unique()) if by_timeframe else [None]):
            g=out[out.timeframe.eq(tf)] if tf is not None else out; base={'horizon':h};
            if tf is not None:base['timeframe']=tf
            p='h_'+h
            for m in RATE_METRICS:
                s=g[p+'_'+m].dropna(); rows.append({**base,'metric':m,'n':int(len(s)),'stat':'rate','value':float(s.astype(bool).mean()) if len(s) else np.nan})
            for m in QUANT_METRICS:
                s=pd.to_numeric(g[p+'_'+m],errors='coerce').dropna(); q=s.quantile([.1,.25,.5,.75,.9]) if len(s) else pd.Series(dtype=float)
                for qq,v in q.items():rows.append({**base,'metric':m,'n':int(len(s)),'stat':f'p{int(qq*100)}','value':float(v)})
    return pd.DataFrame(rows)

def self_test():
    low=np.linspace(96.,98.,30); low[16:21]=[96,95,92,95.5,96.5]; start=pd.Timestamp('2026-08-03 08:45:00')
    bars=pd.DataFrame({'timeframe':'1m','session':'day','bar_start':[start+pd.Timedelta(minutes=i) for i in range(30)],'bar_start_seq':np.arange(1,31),'bar_end_seq':np.arange(1,31),'low':low})
    events=pd.DataFrame([{'event_schema_version':'POC_PROBE_EVENT_V1','universe_version':'HIGH_PRICE_PROBE_V1','universe_schema_version':'POC_HIGH_PRICE_PROBE_UNIVERSE_V1','universe_config_hash':'d7bf39afa32582bc06e00b2df9995b9cb9cc14670a6974834d80cf3d079016fb','feature_schema_version':'POC_CONTINUOUS_FEATURES_V1','event_id':'trigger_rev_self','episode_id':'episode_rev_self','episode_trigger_number':1,'dataset_id':'SYNTH','contract':'202608','partition_id':'self','session':'day','timeframe':'1m','trigger_seq':24,'trigger_time':pd.Timestamp('2026-08-03 09:08:59'),'trigger_price':100.,'atr':4.,'bar_start_seq':24,'bar_end_seq':24,'rolling_high':105.,'rolling_low':85.}])
    ticks=pd.DataFrame([(24,'2026-08-03 09:08:59',100,'202608'),(25,'2026-08-03 09:09:00',107,'202608'),(26,'2026-08-03 09:09:01',84,'202608')],columns=['_seq','datetime','price','expiry'])
    refs=build_reversal_reference_store(events,{'1m':bars}); out,ledger,mismatch=audit(events,ticks,refs,'day'); x=out.iloc[0]; man=build_reversal_reference_manifest(events,refs)
    ok=mismatch==0 and len(ledger)==8 and x.h_30s_first_structure_break_seq==26 and x.h_30s_first_structure_break_references=='channel_midline|micro_swing_low|channel_low' and x.h_30s_pre_break_peak_seq==25 and x.h_30s_adverse_extension_before_reversal_atr==1.75 and man['micro_swing_reference_available']==1
    return {'schema_version':'POC_M5_DEV4_SELF_TEST_V1','reversal_schema_version':REVERSAL_SCHEMA_VERSION,'reversal_reference_schema_version':REVERSAL_REFERENCE_SCHEMA_VERSION,'micro_swing_algorithm_version':MICRO_SWING_ALGORITHM_VERSION,'events':1,'audit_windows':8,'audit_mismatches':mismatch,'thresholds_defined':False,'classification_defined':False,'all_pass':bool(ok)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); ap.add_argument('--parquet',type=Path); ap.add_argument('--output-dir',type=Path,default=Path('reports/poc_absorption/m5_dev4_real_qa_runtime')); a=ap.parse_args()
    if a.self_test:
        r=self_test(); print(json.dumps(r,indent=2,default=str)); raise SystemExit(0 if r['all_pass'] else 2)
    if not a.parquet:ap.error('--parquet required unless --self-test')
    a.output_dir.mkdir(parents=True,exist_ok=True); tfs=['15s','30s','1m','3m','5m','15m']
    day_ticks,day_events,parity,_=_materialize_case(a.parquet,['2024-08-15','2024-08-16'],'202408','day',tfs); expected={'15s':471,'30s':237,'1m':108,'3m':36,'5m':31,'15m':16}
    if {k:int(v['raw_triggers']) for k,v in parity.items()}!=expected:raise AssertionError(f'M4 parity drift: {parity}')
    day_refs=build_reversal_reference_store(day_events,_bars_for_reference(day_ticks,'day',tfs)); day_man=build_reversal_reference_manifest(day_events,day_refs); day_refs.to_csv(a.output_dir/'M5_DEV4_REFERENCE_STORE_2024_DAY_899.csv',index=False); (a.output_dir/'M5_DEV4_REFERENCE_MANIFEST_DAY.json').write_text(json.dumps(day_man,indent=2,default=str)+'\n')
    all_day=compute_reversal_outcomes(day_events,day_ticks,day_refs,contract='202408',session='day'); distributions(all_day).to_csv(a.output_dir/'M5_DEV4_REVERSAL_DISTRIBUTION.csv',index=False); distributions(all_day,True).to_csv(a.output_dir/'M5_DEV4_REVERSAL_DISTRIBUTION_BY_TF.csv',index=False)
    sample,prov=deterministic_audit_sample(day_events); _,dl,dm=audit(sample,day_ticks,day_refs,'day'); dl.to_csv(a.output_dir/'M5_DEV4_REVERSAL_AUDIT_LEDGER_DAY_400.csv',index=False)
    night_ticks,night_events,_,_=_materialize_case(a.parquet,['2024-08-16'],'202408','night',tfs); night_refs=build_reversal_reference_store(night_events,_bars_for_reference(night_ticks,'night',tfs)); night_man=build_reversal_reference_manifest(night_events,night_refs); ns=choose_night_sample(night_events); _,nl,nm=audit(ns,night_ticks,night_refs,'night'); nl.to_csv(a.output_dir/'M5_DEV4_REVERSAL_AUDIT_LEDGER_NIGHT_64.csv',index=False); (a.output_dir/'M5_DEV4_REFERENCE_MANIFEST_NIGHT.json').write_text(json.dumps(night_man,indent=2,default=str)+'\n')
    result={'schema_version':'POC_M5_DEV4_REAL_QA_V1','verdict':'M5_DEV4_FROZEN_STRUCTURE_REVERSAL_PASS','dataset_id':'MTX_2024','day_events':len(day_events),'day_physical_ticks':len(day_ticks),'m4_raw_trigger_parity':expected,'day_reference_manifest':day_man,'day_audit_events':len(sample),'day_audit_windows':len(dl),'day_audit_mismatches':dm,'sample_provenance':prov,'night_events':len(night_events),'night_physical_ticks':len(night_ticks),'night_reference_manifest':night_man,'night_audit_events':len(ns),'night_audit_windows':len(nl),'night_audit_mismatches':nm,'thresholds_defined':False,'classification_defined':False,'research_edge_claimed':False,'development_5_started':False,'all_pass':dm==0 and nm==0 and len(day_events)==899}
    (a.output_dir/'M5_DEV4_REAL_QA_SUMMARY.json').write_text(json.dumps(result,indent=2,default=str)+'\n'); print(json.dumps(result,indent=2,default=str)); raise SystemExit(0 if result['all_pass'] else 2)
if __name__=='__main__':main()
