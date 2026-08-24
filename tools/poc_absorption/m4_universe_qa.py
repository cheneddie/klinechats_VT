#!/usr/bin/env python3
"""Reproducible M4 unbiased-universe QA on synthetic or real MTX Parquet."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from server.poc_absorption.universe import (
    EVENT_SCHEMA_VERSION,UNIVERSE_VERSION,UNIVERSE_SCHEMA_VERSION,
    HighPriceProbeConfig,build_high_price_probe_universe,first_trigger_per_episode,
)


def load_cfg(path):
    c=json.loads(Path(path).read_text());d=c['detector'];return c,HighPriceProbeConfig(**d)


def non_price_mutation(frame):
    m=frame.copy();cols=[c for c in m if c.startswith('poc_') or c.startswith('tdp_') or 'high_zone' in c or 'impact_' in c or 'advance_per_' in c]
    for j,c in enumerate(cols):
        if pd.api.types.is_bool_dtype(m[c]):m[c]=~m[c].fillna(False)
        else:m[c]=(j+1)*1e9
    return m,cols


def self_test():
    rows=[];ticks=[];start=pd.Timestamp('2026-08-03 08:45:00')
    for i in range(36):
        s=i*3;tm=start+pd.Timedelta(minutes=i);base=100+i*.5;o=base-.5;h=base+1;l=base-1;c=base+.5
        rows.append({'feature_schema_version':'POC_CONTINUOUS_FEATURES_V1','timeframe':'1m','session':'day','trading_date':'2026-08-03','bar_start':tm,'bar_start_seq':s,'bar_end_seq':s+2,'open':o,'high':h,'low':l,'close':c,'atr_n':2.0,'poc_delta_1':i,'tdp_ratio':0.1,'impact_per_1000_positive_volume':99.0})
        ticks += [(s,tm,o),(s+1,tm+pd.Timedelta(seconds=20),h),(s+2,tm+pd.Timedelta(seconds=40),c)]
    f=pd.DataFrame(rows);t=pd.DataFrame(ticks,columns=['_seq','datetime','price']);cfg=HighPriceProbeConfig(lookback_bars=6,max_episode_seconds=600)
    r=build_high_price_probe_universe(f,t,dataset_id='SYNTH',contract='202608',partition_id='self',config=cfg)
    m,_=non_price_mutation(f);rm=build_high_price_probe_universe(m,t,dataset_id='SYNTH',contract='202608',partition_id='self',config=cfg)
    keys=['event_id','episode_id','trigger_seq']; inv=r.triggers[keys].reset_index(drop=True).equals(rm.triggers[keys].reset_index(drop=True))
    schema_ok=(len(r.triggers)>0 and set(r.triggers.event_schema_version)=={EVENT_SCHEMA_VERSION} and set(r.triggers.universe_version)=={UNIVERSE_VERSION} and set(r.triggers.universe_schema_version)=={UNIVERSE_SCHEMA_VERSION} and r.triggers.universe_config_hash.nunique()==1 and r.triggers.feature_snapshot.map(type).eq(dict).all())
    return {'schema_version':'POC_M4_QA_SELF_TEST_V1','event_schema_version':EVENT_SCHEMA_VERSION,'universe_version':UNIVERSE_VERSION,'universe_schema_version':UNIVERSE_SCHEMA_VERSION,'universe_config_hash':cfg.config_hash,'raw_triggers':len(r.triggers),'episodes':len(r.episodes),'non_price_selection_invariant':bool(inv),'event_schema_frozen':bool(schema_ok),'all_pass':bool(inv and schema_ok and len(r.triggers)>len(r.episodes)>0)}


def validate_real(path,cfg_path,tf):
    from server.poc_absorption.bars import build_bars
    from server.poc_absorption.features import compute_bar_features,compute_pressure_features,attach_pressure_features,compute_structural_high_zone_features
    from tools.poc_absorption.m3_feature_qa import read_ticks
    keys=['timeframe','session','bar_start_seq','bar_end_seq']
    c,dcfg=load_cfg(cfg_path);q=c['real_qa_case'];t,meta=read_ticks(Path(path),q['dates'],str(q['expiry']),q['product'],q['session'])
    b=build_bars(t.drop(columns=['product','expiry','side'],errors='ignore'),tf,q['session'],atr_period=14);bf=compute_bar_features(b);pf=compute_pressure_features(t,tf,q['session']);f=attach_pressure_features(bf,pf);sf=compute_structural_high_zone_features(t,bf,lookback=24);f=f.merge(sf,on=keys,how='left',validate='one_to_one')
    seq_to_td=t.set_index('_seq')['datetime'].map(lambda x: str(pd.Timestamp(x).date()));f['trading_date']=[seq_to_td.get(int(x)) for x in f.bar_end_seq]
    pid='_'.join(q['dates'])+f'_{q["session"]}_{tf}'
    r=build_high_price_probe_universe(f,t[['_seq','datetime','price']],dataset_id=q['dataset_id'],contract=str(q['expiry']),partition_id=pid,config=dcfg)
    mutated,mutcols=non_price_mutation(f);rm=build_high_price_probe_universe(mutated,t[['_seq','datetime','price']],dataset_id=q['dataset_id'],contract=str(q['expiry']),partition_id=pid,config=dcfg)
    invariant=r.triggers[['event_id','episode_id','trigger_seq']].reset_index(drop=True).equals(rm.triggers[['event_id','episode_id','trigger_seq']].reset_index(drop=True))
    first=first_trigger_per_episode(r.triggers);warm=max(0,len(f)-dcfg.lookback_bars+1);exact=True
    if len(r.triggers):
        lookup=t.set_index('_seq')[['datetime','price']]
        for x in r.triggers.itertuples(index=False):
            tick=lookup.loc[x.trigger_seq]
            if pd.Timestamp(x.trigger_time)!=pd.Timestamp(tick.datetime) or float(x.trigger_price)!=float(tick.price) or float(x.trigger_price)!=float(x.close): exact=False;break
    attached={'poc_delta_1','tdp_ratio','impact_per_1000_positive_volume'}.issubset(r.triggers.columns) if len(r.triggers) else True
    cross_day=int((r.episodes.episode_start_trading_date.astype(str)!=r.episodes.last_trigger_trading_date.astype(str)).sum()) if len(r.episodes) else 0
    ok=invariant and exact and attached and len(first)==len(r.episodes) and cross_day==0
    return {'schema_version':'POC_M4_REAL_QA_V1','event_schema_version':EVENT_SCHEMA_VERSION,'universe_version':UNIVERSE_VERSION,'universe_schema_version':UNIVERSE_SCHEMA_VERSION,'universe_config_hash':dcfg.config_hash,'timeframe':tf,'ticks':len(t),'bars':len(f),'warm_bars':warm,'feature_columns':len(f.columns),'raw_triggers':len(r.triggers),'episodes':len(r.episodes),'first_trigger_view':len(first),'trigger_rate_warm_bars':len(r.triggers)/warm if warm else None,'multi_trigger_episodes':int((r.episodes.trigger_count>1).sum()) if len(r.episodes) else 0,'max_triggers_per_episode':int(r.episodes.trigger_count.max()) if len(r.episodes) else 0,'reason_counts':r.triggers.trigger_reason_class.value_counts().to_dict() if len(r.triggers) else {},'non_price_mutated_columns':len(mutcols),'non_price_selection_invariant':bool(invariant),'exact_physical_decision_point':bool(exact),'feature_snapshot_attached_after_selection':bool(attached),'raw_trigger_store_preserved':len(first)==len(r.episodes) and len(r.triggers)>=len(first),'episodes_crossing_trading_day':cross_day,'contract_checks':meta['contract_checks'],'all_pass':bool(ok)}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--parquet',type=Path);ap.add_argument('--config',type=Path,default=Path('config/poc_absorption/m4_universe_v1.json'));ap.add_argument('--timeframe',choices=['15s','30s','1m','3m','5m','15m']);ap.add_argument('--self-test',action='store_true');ap.add_argument('--output',type=Path);a=ap.parse_args()
    if a.self_test:r=self_test()
    else:
        if not a.parquet or not a.timeframe:ap.error('--parquet and --timeframe required unless --self-test')
        r=validate_real(a.parquet,a.config,a.timeframe)
    txt=json.dumps(r,ensure_ascii=False,indent=2,default=str);print(txt)
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(txt+'\n')
    raise SystemExit(0 if r['all_pass'] else 2)
if __name__=='__main__':main()
