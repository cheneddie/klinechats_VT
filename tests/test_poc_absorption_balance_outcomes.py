from __future__ import annotations
import numpy as np,pandas as pd,pytest
from server.poc_absorption.outcomes import FROZEN_EVENT_SCHEMA_VERSION,FROZEN_UNIVERSE_CONFIG_HASH,FROZEN_UNIVERSE_SCHEMA_VERSION,FROZEN_UNIVERSE_VERSION,event_store_fingerprint
from server.poc_absorption.balance_outcomes import BALANCE_SCHEMA_VERSION,build_balance_reference_manifest,compute_balance_outcomes

def event(seq=10,tm='2024-08-15 09:00:00',price=100.,atr=10.,rolling_high=103.,session='day',tf='1m',eid=None):
 return pd.DataFrame([{'event_schema_version':FROZEN_EVENT_SCHEMA_VERSION,'universe_version':FROZEN_UNIVERSE_VERSION,'universe_schema_version':FROZEN_UNIVERSE_SCHEMA_VERSION,'universe_config_hash':FROZEN_UNIVERSE_CONFIG_HASH,'feature_schema_version':'POC_CONTINUOUS_FEATURES_V1','event_id':eid or f'trigger_{seq:020d}','episode_id':f'episode_{seq:020d}','episode_trigger_number':1,'dataset_id':'MTX_2024','contract':'202408','partition_id':'qa','session':session,'timeframe':tf,'trigger_seq':seq,'trigger_time':pd.Timestamp(tm),'trigger_price':price,'atr':atr,'bar_start_seq':max(0,seq-2),'bar_end_seq':seq,'rolling_high':rolling_high}])
def ticks(rows):
 f=pd.DataFrame(rows,columns=['_seq','datetime','price']);f['expiry']='202408';return f

def test_reference_manifest_is_deterministic_and_detects_level_drift():
 e=event();a=build_balance_reference_manifest(e);b=build_balance_reference_manifest(e.copy());assert a==b
 e2=e.copy();e2.loc[0,'rolling_high']+=1;assert build_balance_reference_manifest(e2)['balance_reference_hash']!=a['balance_reference_hash']

def test_raw_and_one_second_efficiency_separate_same_second_churn():
 e=event();t=ticks([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:00',101),(12,'2024-08-15 09:00:00',100),(13,'2024-08-15 09:00:00',104),(14,'2024-08-15 09:00:00',99),(15,'2024-08-15 09:00:01',102)])
 r=compute_balance_outcomes(e,t,contract='202408',session='day',horizons=['30s']).iloc[0]
 assert np.isclose(r.h_30s_raw_tick_path_efficiency,2/14);assert np.isclose(r.h_30s_one_second_path_efficiency,.5)
 assert r.h_30s_raw_tick_high_retest_count==1 and r.h_30s_high_retest_count==0
 assert r.h_30s_raw_tick_range_cross_count==2 and r.h_30s_range_cross_count==1

def test_no_future_observation_remains_missing_not_zero_balance():
 e=event(seq=20,tm='2024-08-15 13:44:59');t=ticks([(20,'2024-08-15 13:44:59',100)])
 r=compute_balance_outcomes(e,t,contract='202408',session='day',horizons=['30s']).iloc[0]
 assert r.h_30s_future_tick_count==0 and pd.isna(r.h_30s_raw_tick_path_efficiency) and pd.isna(r.h_30s_range_cross_count)

def test_static_observed_path_has_zero_path_and_undefined_efficiency():
 e=event();t=ticks([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:01',100),(12,'2024-08-15 09:00:02',100)])
 r=compute_balance_outcomes(e,t,contract='202408',session='day',horizons=['30s']).iloc[0]
 assert r.h_30s_raw_tick_total_path_points==0 and pd.isna(r.h_30s_raw_tick_path_efficiency)
 assert r.h_30s_future_range_atr==0 and r.h_30s_time_at_trigger_fraction==1

def test_time_weighted_balance_sums_to_full_horizon():
 e=event();t=ticks([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:01',101),(12,'2024-08-15 09:00:03',99)])
 r=compute_balance_outcomes(e,t,contract='202408',session='day',horizons=['30s']).iloc[0]
 assert np.isclose(r.h_30s_time_above_trigger_seconds,2) and np.isclose(r.h_30s_time_below_trigger_seconds,27) and np.isclose(r.h_30s_time_at_trigger_seconds,1)
 assert np.isclose(r.h_30s_time_above_trigger_fraction+r.h_30s_time_below_trigger_fraction+r.h_30s_time_at_trigger_fraction,1)

def test_canonical_retest_uses_frozen_m4_rolling_high():
 e=event(rolling_high=102);t=ticks([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:01',103),(12,'2024-08-15 09:00:02',101),(13,'2024-08-15 09:00:03',103)])
 r=compute_balance_outcomes(e,t,contract='202408',session='day',horizons=['30s']).iloc[0];assert r.h_30s_high_retest_count==2 and r.high_retest_reference_level==102

def test_range_cross_ignores_exact_trigger_touches_and_bridges_sign():
 e=event();t=ticks([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:01',101),(12,'2024-08-15 09:00:02',100),(13,'2024-08-15 09:00:03',99),(14,'2024-08-15 09:00:04',100),(15,'2024-08-15 09:00:05',101)])
 r=compute_balance_outcomes(e,t,contract='202408',session='day',horizons=['30s']).iloc[0];assert r.h_30s_range_cross_count==2

def test_missing_or_invalid_rolling_high_is_rejected():
 e=event().drop(columns='rolling_high')
 with pytest.raises(ValueError,match='rolling_high'): build_balance_reference_manifest(e)
 e=event();e.loc[0,'rolling_high']=np.nan
 with pytest.raises(ValueError,match='rolling_high'): build_balance_reference_manifest(e)

def test_balance_attachment_does_not_change_core_event_fingerprint():
 e=event();fp=event_store_fingerprint(e);t=ticks([(10,'2024-08-15 09:00:00',100),(11,'2024-08-15 09:00:01',99)])
 o=compute_balance_outcomes(e,t,contract='202408',session='day',horizons=['30s']);assert event_store_fingerprint(o)==fp and set(o.balance_schema_version)=={BALANCE_SCHEMA_VERSION}

def test_night_balance_path_crosses_midnight_in_same_session():
 e=event(seq=30,tm='2024-08-15 23:59:59',session='night',rolling_high=102);t=ticks([(30,'2024-08-15 23:59:59',100),(31,'2024-08-16 00:00:00',99),(32,'2024-08-16 00:00:01',103)])
 r=compute_balance_outcomes(e,t,contract='202408',session='night',horizons=['30s']).iloc[0];assert r.h_30s_future_tick_count==2 and r.h_30s_range_cross_count==1 and r.h_30s_high_retest_count==1
