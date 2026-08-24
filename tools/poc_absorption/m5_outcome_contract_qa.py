#!/usr/bin/env python3
"""M5 Development 1: read-only event/outcome contract QA.

Production-facing use accepts an already-materialized M4 `probe_events` table.
A QA-only `--parquet` mode may materialize the *frozen existing M4 real-QA case*
through committed M4 code solely to prove interface parity. It reads no future
outcomes and is not an outcome-engine event selection path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from server.poc_absorption.outcomes import (
    FROZEN_EVENT_SCHEMA_VERSION,
    FROZEN_UNIVERSE_CONFIG_HASH,
    FROZEN_UNIVERSE_SCHEMA_VERSION,
    FROZEN_UNIVERSE_VERSION,
    OUTCOME_CONTRACT_VERSION,
    OUTCOME_SCHEMA_VERSION,
    build_event_manifest,
    make_probe_outcome_skeleton,
    validate_probe_outcomes,
)


def _synthetic_events(n=12):
    rows=[]
    for i in range(n):
        seq=100+i*3
        rows.append({
            'event_schema_version':FROZEN_EVENT_SCHEMA_VERSION,'universe_version':FROZEN_UNIVERSE_VERSION,
            'universe_schema_version':FROZEN_UNIVERSE_SCHEMA_VERSION,'universe_config_hash':FROZEN_UNIVERSE_CONFIG_HASH,
            'feature_schema_version':'POC_CONTINUOUS_FEATURES_V1','event_id':f'trigger_{i:020d}',
            'episode_id':f'episode_{i//3:020d}','episode_trigger_number':1+(i%3),'dataset_id':'SYNTH',
            'contract':'202608','partition_id':'self','session':'day','timeframe':'1m','trigger_seq':seq,
            'trigger_time':pd.Timestamp('2026-08-03 09:00')+pd.Timedelta(minutes=i),'trigger_price':100+i,'atr':2.0,
            'bar_start_seq':seq-2,'bar_end_seq':seq,
        })
    return pd.DataFrame(rows)


def materialize_frozen_m4_real_qa(parquet: Path, config_path: Path):
    """QA-only adapter: reproduce the existing two-day frozen M4 real-QA events."""
    from server.poc_absorption.bars import build_bars
    from server.poc_absorption.features import (
        attach_pressure_features, compute_bar_features, compute_pressure_features, compute_structural_high_zone_features,
    )
    from server.poc_absorption.universe import HighPriceProbeConfig, build_high_price_probe_universe
    from tools.poc_absorption.m3_feature_qa import read_ticks

    cfg=json.loads(config_path.read_text()); q=cfg['real_qa_case']; detector=HighPriceProbeConfig(**cfg['detector'])
    ticks,meta=read_ticks(parquet,q['dates'],str(q['expiry']),q.get('product','MTX'),q.get('session','day'))
    keys=['timeframe','session','bar_start_seq','bar_end_seq']; frames=[]; parity={}
    seq_to_td=ticks.set_index('_seq')['datetime'].map(lambda x:str(pd.Timestamp(x).date()))
    for tf in q['timeframes']:
        bars=build_bars(ticks.drop(columns=['product','expiry','side'],errors='ignore'),tf,q['session'],atr_period=14)
        bf=compute_bar_features(bars); pf=compute_pressure_features(ticks,tf,q['session']); full=attach_pressure_features(bf,pf)
        sf=compute_structural_high_zone_features(ticks,bf,lookback=24); full=full.merge(sf,on=keys,how='left',validate='one_to_one')
        full['trading_date']=[seq_to_td.get(int(x)) for x in full.bar_end_seq]
        partition_id='_'.join(q['dates'])+f'_{q["session"]}_{tf}'
        universe=build_high_price_probe_universe(
            full,ticks[['_seq','datetime','price']],dataset_id=q['dataset_id'],contract=str(q['expiry']),
            partition_id=partition_id,config=detector,
        )
        frames.append(universe.triggers)
        parity[tf]={'bars':int(len(full)),'raw_triggers':int(len(universe.triggers)),'episodes':int(len(universe.episodes))}
    events=pd.concat(frames,ignore_index=True)
    source_case={
        'dataset_id':q['dataset_id'],'dates':q['dates'],'session':q['session'],'contract':str(q['expiry']),
        'physical_ticks':int(len(ticks)),'m4_parity':parity,'total_raw_triggers':int(len(events)),
        'total_unique_event_ids':int(events.event_id.nunique()),'future_ticks_read_for_contract_qa':False,
        'outcomes_calculated':False,'atr_source':'frozen_M4_event_time_atr','contract_checks':meta.get('contract_checks'),
    }
    return events,source_case


def evaluate(events: pd.DataFrame, source: str, *, source_case: dict | None = None) -> dict:
    manifest=build_event_manifest(events); skeleton=make_probe_outcome_skeleton(events); integrity=validate_probe_outcomes(events,skeleton)
    result={
        'schema_version':'POC_M5_OUTCOME_CONTRACT_QA_V1','outcome_schema_version':OUTCOME_SCHEMA_VERSION,
        'outcome_contract_version':OUTCOME_CONTRACT_VERSION,'source':source,'future_ticks_read':False,
        'future_outcomes_calculated':False,'probe_events_policy':'READ_ONLY','join_key':'event_id',
        'manifest':manifest,'join_integrity':integrity.as_dict(),'all_pass':bool(integrity.all_pass),
    }
    if source_case is not None: result['source_case']=source_case
    return result


def read_events(path: Path) -> pd.DataFrame:
    suffix=path.suffix.lower()
    if suffix=='.parquet': return pd.read_parquet(path)
    if suffix in {'.jsonl','.ndjson'}: return pd.read_json(path,lines=True)
    if suffix=='.csv': return pd.read_csv(path)
    raise ValueError('events file must be parquet, jsonl/ndjson, or csv')


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--events',type=Path); ap.add_argument('--parquet',type=Path)
    ap.add_argument('--m4-config',type=Path,default=Path('config/poc_absorption/m4_universe_v1.json'))
    ap.add_argument('--self-test',action='store_true'); ap.add_argument('--output',type=Path); a=ap.parse_args()
    modes=int(a.self_test)+int(a.events is not None)+int(a.parquet is not None)
    if modes!=1: ap.error('choose exactly one of --self-test, --events, or --parquet')
    if a.self_test: r=evaluate(_synthetic_events(),'synthetic_self_test')
    elif a.events is not None: r=evaluate(read_events(a.events),str(a.events))
    else:
        events,source_case=materialize_frozen_m4_real_qa(a.parquet,a.m4_config)
        label=f"{source_case['dataset_id']} / {'+'.join(source_case['dates'])} / {source_case['session']} / strict {source_case['contract']} / six-timeframe M4 real-QA event store"
        r=evaluate(events,label,source_case=source_case)
    text=json.dumps(r,ensure_ascii=False,indent=2,default=str); print(text)
    if a.output: a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(text+'\n')
    raise SystemExit(0 if r['all_pass'] else 2)

if __name__=='__main__': main()
