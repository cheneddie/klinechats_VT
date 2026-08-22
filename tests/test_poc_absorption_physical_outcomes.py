from __future__ import annotations
import pandas as pd
import pytest
from server.poc_absorption.outcomes import event_store_fingerprint
from server.poc_absorption.physical_outcomes import PHYSICAL_PATH_SCHEMA_VERSION,compute_physical_tick_outcomes,compute_physical_tick_outcomes_with_diagnostics

BASE={
'event_schema_version':'POC_PROBE_EVENT_V1','universe_version':'HIGH_PRICE_PROBE_V1','universe_schema_version':'POC_HIGH_PRICE_PROBE_UNIVERSE_V1','universe_config_hash':'d7bf39afa32582bc06e00b2df9995b9cb9cc14670a6974834d80cf3d079016fb','feature_schema_version':'POC_CONTINUOUS_FEATURES_V1','episode_trigger_number':1,'dataset_id':'MTX_2024','contract':'202408','partition_id':'qa','session':'day','timeframe':'1m','trigger_seq':10,'trigger_time':pd.Timestamp('2024-08-15 09:00:00'),'trigger_price':100.0,'atr':4.0,'bar_start_seq':8,'bar_end_seq':10}
def ev(**kw):
 d=BASE.copy(); d.update(kw); d.setdefault('event_id',f"trigger_{d['trigger_seq']:020d}"); d.setdefault('episode_id',f"episode_{d['trigger_seq']:020d}"); return pd.DataFrame([d])
def tk(rows,expiry=True):
 d=pd.DataFrame(rows,columns=['_seq','datetime','price']);
 if expiry:d['expiry']='202408'
 return d

def test_strict_future_seq_and_same_second_later_tick():
 o=compute_physical_tick_outcomes(ev(),tk([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:00',99),(12,'2024-08-15 09:00:01',101)]),contract='202408',session='day',horizons=['30s']); r=o.iloc[0]
 assert r.h_30s_future_tick_count==2 and r.h_30s_window_start_seq==11 and r.h_30s_short_mfe==1 and r.h_30s_time_to_mfe_seconds==0

def test_deadline_tick_included_after_deadline_excluded():
 r=compute_physical_tick_outcomes(ev(),tk([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:30',97),(12,'2024-08-15 09:00:30.001',95)]),contract='202408',session='day',horizons=['30s']).iloc[0]
 assert r.h_30s_future_tick_count==1 and r.h_30s_window_end_seq==11 and r.h_30s_forward_low==97

def test_day_session_truncation_and_deadline_coordinate():
 e=ev(trigger_seq=20,bar_end_seq=20,bar_start_seq=18,trigger_time=pd.Timestamp('2024-08-15 13:44:30'),event_id='t20',episode_id='e20')
 r=compute_physical_tick_outcomes(e,tk([(20,'2024-08-15 13:44:30',100),(21,'2024-08-15 13:44:59.999',98)]),contract='202408',session='day',horizons=['60m']).iloc[0]
 assert r.h_60m_truncated_by_session_end and r.h_60m_effective_horizon_seconds==30 and pd.Timestamp(r.h_60m_deadline_time)==pd.Timestamp('2024-08-15 13:45:00')

def test_night_cross_midnight_and_near_0500():
 e=ev(session='night',trigger_seq=30,bar_end_seq=30,bar_start_seq=28,trigger_time=pd.Timestamp('2024-08-15 23:59:59'),event_id='t30',episode_id='e30')
 t=tk([(30,'2024-08-15 23:59:59',100),(31,'2024-08-16 00:00:00',99),(32,'2024-08-16 00:00:29',102)])
 r=compute_physical_tick_outcomes(e,t,contract='202408',session='night',horizons=['30s']).iloc[0]
 assert r.h_30s_forward_low==99 and r.h_30s_forward_high==102

def test_equal_extrema_choose_first_physical_seq_and_mfe_mae_coordinates():
 r=compute_physical_tick_outcomes(ev(),tk([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:01',103),(12,'2024-08-15 09:00:02',97),(13,'2024-08-15 09:00:03',103),(14,'2024-08-15 09:00:04',97)]),contract='202408',session='day',horizons=['30s']).iloc[0]
 assert r.h_30s_forward_high_seq==11 and r.h_30s_forward_low_seq==12 and r.h_30s_mfe_seq==12 and r.h_30s_mae_seq==11

def test_zero_excursion_vs_no_observation_are_distinct():
 r=compute_physical_tick_outcomes(ev(),tk([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:01',101)]),contract='202408',session='day',horizons=['30s']).iloc[0]
 assert r.h_30s_short_mfe==0 and pd.isna(r.h_30s_mfe_seq) and pd.isna(r.h_30s_mfe_time)
 r2=compute_physical_tick_outcomes(ev(),tk([(10,'2024-08-15 09:00:00',100)]),contract='202408',session='day',horizons=['30s']).iloc[0]
 assert r2.h_30s_future_tick_count==0 and pd.isna(r2.h_30s_short_mfe) and pd.isna(r2.h_30s_forward_low)

def test_normalization_uses_frozen_atr_and_event_fingerprint_unchanged():
 e=ev(atr=4.0); fp=event_store_fingerprint(e); o=compute_physical_tick_outcomes(e,tk([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:01',96),(12,'2024-08-15 09:00:02',106)]),contract='202408',session='day',horizons=['30s']); r=o.iloc[0]
 assert r.h_30s_mfe_atr==1 and r.h_30s_mae_atr==1.5 and event_store_fingerprint(o)==fp and set(o.physical_path_schema_version)=={PHYSICAL_PATH_SCHEMA_VERSION}

def test_trigger_coordinate_mismatch_rejected():
 with pytest.raises(ValueError,match='trigger_price mismatch'): compute_physical_tick_outcomes(ev(),tk([(10,'2024-08-15 09:00:00',101)]),contract='202408',session='day',horizons=['30s'])

def test_engine_never_sorts_physical_seq():
 with pytest.raises(ValueError,match='strictly increasing'): compute_physical_tick_outcomes(ev(),tk([(10,'2024-08-15 09:00:00',100),(12,'2024-08-15 09:00:02',99),(11,'2024-08-15 09:00:01',98)]),contract='202408',session='day',horizons=['30s'])

def test_outside_session_tick_rejected():
 e=ev(trigger_seq=20,bar_end_seq=20,bar_start_seq=18,trigger_time=pd.Timestamp('2024-08-15 13:44:30'),event_id='t20',episode_id='e20')
 with pytest.raises(ValueError,match='outside requested session'): compute_physical_tick_outcomes(e,tk([(20,'2024-08-15 13:44:30',100),(21,'2024-08-15 13:45:00',99)]),contract='202408',session='day',horizons=['30s'])

def test_multiple_events_same_trigger_seq_not_deduped():
 a=ev(event_id='a',episode_id='ea',timeframe='15s'); b=ev(event_id='b',episode_id='eb',timeframe='1m'); e=pd.concat([a,b],ignore_index=True)
 o=compute_physical_tick_outcomes(e,tk([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:01',98)]),contract='202408',session='day',horizons=['30s'])
 assert o.event_id.tolist()==['a','b'] and o.h_30s_forward_low.tolist()==[98,98]

def test_multi_day_partition_builds_session_local_indices():
 e=pd.concat([ev(event_id='d1',episode_id='e1'),ev(event_id='d2',episode_id='e2',trigger_seq=20,bar_start_seq=18,bar_end_seq=20,trigger_time=pd.Timestamp('2024-08-16 09:00:00'))],ignore_index=True)
 t=tk([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:01',99),(20,'2024-08-16 09:00:00',100),(21,'2024-08-16 09:00:01',97)])
 o,d=compute_physical_tick_outcomes_with_diagnostics(e,t,contract='202408',session='day',horizons=['30s'])
 assert o.h_30s_forward_low.tolist()==[99,97] and d.sessions_indexed==2 and d.physical_ticks_indexed==4 and d.range_queries==2

def test_invalid_or_duplicate_horizon_rejected():
 with pytest.raises(ValueError): compute_physical_tick_outcomes(ev(),tk([(10,'2024-08-15 09:00:00',100)]),contract='202408',session='day',horizons=['30s','30s'])
