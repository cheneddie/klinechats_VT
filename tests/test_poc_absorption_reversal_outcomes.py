from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from server.poc_absorption.outcomes import event_store_fingerprint
from server.poc_absorption.reversal_outcomes import (
    MICRO_SWING_ALGORITHM_VERSION, REVERSAL_REFERENCE_SCHEMA_VERSION,
    REVERSAL_SCHEMA_VERSION, build_reversal_reference_manifest,
    build_reversal_reference_store, compute_reversal_outcomes,
    validate_reversal_reference_store,
)

BASE={
'event_schema_version':'POC_PROBE_EVENT_V1','universe_version':'HIGH_PRICE_PROBE_V1',
'universe_schema_version':'POC_HIGH_PRICE_PROBE_UNIVERSE_V1',
'universe_config_hash':'d7bf39afa32582bc06e00b2df9995b9cb9cc14670a6974834d80cf3d079016fb',
'feature_schema_version':'POC_CONTINUOUS_FEATURES_V1','event_id':'trigger_rev','episode_id':'episode_rev',
'episode_trigger_number':1,'dataset_id':'SYNTH','contract':'202408','partition_id':'qa','session':'day',
'timeframe':'1m','trigger_seq':24,'trigger_time':pd.Timestamp('2024-08-15 09:08:59'),
'trigger_price':100.0,'atr':4.0,'bar_start_seq':24,'bar_end_seq':24,'rolling_high':105.0,'rolling_low':85.0}

def event(**kw):
 d=BASE.copy(); d.update(kw); return pd.DataFrame([d])

def bars(rows=30,pivot_low=92.0,pivot_index=18,no_pivot=False):
 low=np.linspace(96.0,98.0,rows)
 if no_pivot: low=np.arange(rows,dtype=float)+90.0
 else: low[pivot_index-2:pivot_index+3]=[96.0,95.0,pivot_low,95.5,96.5]
 start=pd.Timestamp('2024-08-15 08:45:00')
 return pd.DataFrame({'timeframe':'1m','session':'day','bar_start':[start+pd.Timedelta(minutes=i) for i in range(rows)],'bar_start_seq':np.arange(1,rows+1),'bar_end_seq':np.arange(1,rows+1),'low':low})

def ticks(rows):
 f=pd.DataFrame(rows,columns=['_seq','datetime','price']); f['expiry']='202408'; return f

def refs(e,b=None): return build_reversal_reference_store(e,{'1m':bars() if b is None else b})

def test_reference_is_strict_confirmed_pivot_and_manifest_deterministic():
 e=event(); r=refs(e); x=r.iloc[0]
 assert x.reversal_reference_schema_version==REVERSAL_REFERENCE_SCHEMA_VERSION
 assert x.micro_swing_algorithm_version==MICRO_SWING_ALGORITHM_VERSION
 assert x.micro_swing_low_reference_level==92.0 and x.micro_swing_bar_end_seq==19
 assert x.channel_midline_reference_level==95.0
 assert build_reversal_reference_manifest(e,r)==build_reversal_reference_manifest(e,r.sample(frac=1,random_state=7))

def test_future_bars_cannot_confirm_or_move_reference():
 e=event(); b=bars(); a=refs(e,b); c=b.copy(); c.loc[24:,'low']=[-1000,-900,-800,-700,-600,-500]; z=refs(e,c)
 cols=['micro_swing_low_reference_level','micro_swing_bar_end_seq','channel_midline_reference_level']
 assert a[cols].equals(z[cols])

def test_no_pivot_is_null_no_fallback():
 x=refs(event(),bars(no_pivot=True)).iloc[0]
 assert not x.micro_swing_reference_available and not x.micro_swing_break_eligible and pd.isna(x.micro_swing_low_reference_level)

def test_already_broken_reference_is_ineligible():
 x=refs(event(trigger_price=90.0,rolling_high=110.0,rolling_low=80.0),bars(pivot_low=92.0)).iloc[0]
 assert x.micro_swing_reference_available and not x.micro_swing_break_eligible
 assert x.channel_midline_reference_level==95.0 and not x.channel_midline_break_eligible and x.channel_low_break_eligible

def test_trigger_bar_start_coordinate_must_match_event():
 e=event(bar_start_seq=23)
 with pytest.raises(ValueError,match='bar_start_seq mismatch'): refs(e)

def test_strict_break_new_high_and_same_second_physical_seq():
 e=event(); r=refs(e); t=ticks([(24,'2024-08-15 09:08:59',100),(25,'2024-08-15 09:08:59',105),(26,'2024-08-15 09:08:59',106),(27,'2024-08-15 09:08:59',95),(28,'2024-08-15 09:08:59',94)])
 x=compute_reversal_outcomes(e,t,r,contract='202408',session='day',horizons=['30s']).iloc[0]
 assert x.h_30s_made_new_high and x.h_30s_new_high_seq==26
 assert x.h_30s_break_channel_midline and x.h_30s_channel_midline_break_seq==28
 assert x.h_30s_time_to_new_high_seconds==0 and x.h_30s_time_to_channel_midline_break_seconds==0

def test_simultaneous_first_break_preserves_all_reference_names():
 e=event(); r=refs(e); t=ticks([(24,'2024-08-15 09:08:59',100),(25,'2024-08-15 09:09:00',84)])
 x=compute_reversal_outcomes(e,t,r,contract='202408',session='day',horizons=['30s']).iloc[0]
 assert x.h_30s_first_structure_break_seq==25
 assert x.h_30s_first_structure_break_references=='channel_midline|micro_swing_low|channel_low'

def test_reversal_delay_peak_uses_first_physical_max_before_break():
 e=event(); r=refs(e); t=ticks([(24,'2024-08-15 09:08:59',100),(25,'2024-08-15 09:09:00',103),(26,'2024-08-15 09:09:01',107),(27,'2024-08-15 09:09:02',107),(28,'2024-08-15 09:09:03',94)])
 x=compute_reversal_outcomes(e,t,r,contract='202408',session='day',horizons=['30s']).iloc[0]
 assert x.h_30s_first_structure_break_seq==28 and x.h_30s_pre_break_peak_seq==26
 assert x.h_30s_adverse_extension_before_reversal_atr==1.75
 assert x.h_30s_time_to_peak_after_trigger_seconds==2 and x.h_30s_time_peak_to_structure_break_seconds==2
 assert x.h_30s_new_high_before_first_break

def test_no_future_observation_is_null_not_false():
 e=event(); r=refs(e); t=ticks([(24,'2024-08-15 09:08:59',100)])
 x=compute_reversal_outcomes(e,t,r,contract='202408',session='day',horizons=['30s']).iloc[0]
 assert x.h_30s_future_tick_count==0 and pd.isna(x.h_30s_break_channel_midline)
 assert pd.isna(x.h_30s_made_new_high) and pd.isna(x.h_30s_any_structure_break) and pd.isna(x.h_30s_forward_slope_1s_step)

def test_forward_slope_r2_use_one_second_close_sequence():
 e=event(); r=refs(e); t=ticks([(24,'2024-08-15 09:08:59',100),(25,'2024-08-15 09:09:00',101),(26,'2024-08-15 09:09:01',102),(27,'2024-08-15 09:09:02',103)])
 x=compute_reversal_outcomes(e,t,r,contract='202408',session='day',horizons=['30s']).iloc[0]
 assert x.h_30s_forward_slope_1s_step==pytest.approx(1.0) and x.h_30s_forward_slope_atr_1s_step==pytest.approx(.25) and x.h_30s_forward_r2_1s==pytest.approx(1.0)

def test_reference_mutation_and_future_source_coordinates_rejected():
 e=event(); r=refs(e); bad=r.copy(); bad.loc[0,'channel_low_reference_level']-=1
 with pytest.raises(ValueError,match='channel_low_reference_level drift'): validate_reversal_reference_store(e,bad)
 bad=r.copy(); bad.loc[0,'micro_swing_bar_end_seq']=25
 with pytest.raises(ValueError,match='not causal at trigger_seq'): validate_reversal_reference_store(e,bad)

def test_event_fingerprint_preserved_and_reference_join_is_event_id_based():
 a=event(event_id='a',episode_id='ea'); b=event(event_id='b',episode_id='eb'); e=pd.concat([a,b],ignore_index=True)
 r=build_reversal_reference_store(e,{'1m':bars()}); fp=event_store_fingerprint(e)
 t=ticks([(24,'2024-08-15 09:08:59',100),(25,'2024-08-15 09:09:00',94)])
 o=compute_reversal_outcomes(e,t,r.iloc[::-1].reset_index(drop=True),contract='202408',session='day',horizons=['30s'])
 assert o.event_id.tolist()==['a','b'] and event_store_fingerprint(o)==fp
 assert set(o.reversal_schema_version)=={REVERSAL_SCHEMA_VERSION} and o.h_30s_break_channel_midline.tolist()==[True,True]
