from __future__ import annotations

import pandas as pd
import pytest

from server.poc_absorption.outcomes import (
    FROZEN_EVENT_SCHEMA_VERSION,
    FROZEN_UNIVERSE_CONFIG_HASH,
    FROZEN_UNIVERSE_SCHEMA_VERSION,
    FROZEN_UNIVERSE_VERSION,
    OUTCOME_CONTRACT_VERSION,
    OUTCOME_SCHEMA_VERSION,
    build_event_manifest,
    event_store_fingerprint,
    make_probe_outcome_skeleton,
    validate_probe_events,
    validate_probe_outcomes,
)


def make_events(n=8):
    rows=[]
    for i in range(n):
        seq=1000+i*10
        rows.append({
            'event_schema_version':FROZEN_EVENT_SCHEMA_VERSION,
            'universe_version':FROZEN_UNIVERSE_VERSION,
            'universe_schema_version':FROZEN_UNIVERSE_SCHEMA_VERSION,
            'universe_config_hash':FROZEN_UNIVERSE_CONFIG_HASH,
            'feature_schema_version':'POC_CONTINUOUS_FEATURES_V1',
            'event_id':f'trigger_{i:020d}','episode_id':f'episode_{i//2:020d}',
            'episode_trigger_number':1+(i%2),'dataset_id':'MTX_2024','contract':'202408',
            'partition_id':'qa_2024_08_day_1m','session':'day','timeframe':'1m',
            'trigger_seq':seq,'trigger_time':pd.Timestamp('2024-08-15 09:00')+pd.Timedelta(minutes=i),
            'trigger_price':22000.0+i,'atr':32.0+i*0.1,'bar_start_seq':seq-5,'bar_end_seq':seq,
            'poc_delta_1':float(i),
        })
    return pd.DataFrame(rows)


def test_skeleton_is_one_to_one_and_does_not_mutate_events():
    events=make_events(); before=events.copy(deep=True); fp=event_store_fingerprint(events)
    out=make_probe_outcome_skeleton(events)
    pd.testing.assert_frame_equal(events,before)
    assert len(out)==len(events)
    assert out.event_id.tolist()==events.event_id.tolist()
    assert set(out.outcome_schema_version)=={OUTCOME_SCHEMA_VERSION}
    assert set(out.outcome_contract_version)=={OUTCOME_CONTRACT_VERSION}
    report=validate_probe_outcomes(events,out)
    assert report.all_pass and report.missing_event_ids==report.extra_event_ids==0
    assert report.event_fingerprint_before==report.event_fingerprint_after_join==fp


def test_duplicate_event_id_is_rejected_on_both_sides():
    events=make_events(); events.loc[1,'event_id']=events.loc[0,'event_id']
    with pytest.raises(ValueError,match='event_id'):
        validate_probe_events(events)
    events=make_events(); out=make_probe_outcome_skeleton(events); out.loc[1,'event_id']=out.loc[0,'event_id']
    with pytest.raises(ValueError,match='event_id'):
        validate_probe_outcomes(events,out)


def test_missing_outcome_event_is_rejected():
    events=make_events(); out=make_probe_outcome_skeleton(events).iloc[:-1].copy()
    with pytest.raises(ValueError,match='event_id set mismatch'):
        validate_probe_outcomes(events,out)


def test_unknown_extra_event_is_rejected():
    events=make_events(); out=make_probe_outcome_skeleton(events); extra=out.iloc[[0]].copy(); extra['event_id']='trigger_unknown'; out=pd.concat([out,extra],ignore_index=True)
    with pytest.raises(ValueError,match='event_id set mismatch'):
        validate_probe_outcomes(events,out)


def test_m5_cannot_mutate_trigger_decision_fields():
    events=make_events(); out=make_probe_outcome_skeleton(events); out.loc[3,'trigger_price']+=1
    with pytest.raises(ValueError,match='immutable M4 field mismatch'):
        validate_probe_outcomes(events,out)
    out=make_probe_outcome_skeleton(events); out.loc[3,'trigger_seq']+=1; out.loc[3,'bar_end_seq']+=1
    with pytest.raises(ValueError,match='immutable M4 field mismatch'):
        validate_probe_outcomes(events,out)
    out=make_probe_outcome_skeleton(events); out.loc[3,'atr']+=0.5
    with pytest.raises(ValueError,match='immutable M4 field mismatch'):
        validate_probe_outcomes(events,out)


def test_frozen_m4_provenance_drift_is_rejected():
    events=make_events(); events.loc[:,'universe_config_hash']='not-the-frozen-hash'
    with pytest.raises(ValueError,match='universe_config_hash drift'):
        validate_probe_events(events)


def test_feature_schema_drift_is_rejected():
    events=make_events(); events.loc[:,'feature_schema_version']='POC_CONTINUOUS_FEATURES_V2'
    with pytest.raises(ValueError,match='feature_schema_version drift'):
        validate_probe_events(events)


def test_event_time_atr_is_frozen_positive_and_finite():
    events=make_events(); events.loc[0,'atr']=0.0
    with pytest.raises(ValueError,match='atr must be finite and positive'):
        validate_probe_events(events)
    events=make_events(); events.loc[0,'atr']=float('nan')
    with pytest.raises(ValueError,match='atr must be finite and positive'):
        validate_probe_events(events)


def test_trigger_seq_must_equal_exact_bar_end_seq():
    events=make_events(); events.loc[0,'bar_end_seq']+=1
    with pytest.raises(ValueError,match='trigger_seq'):
        validate_probe_events(events)


def test_manifest_is_deterministic_and_order_sensitive():
    events=make_events(); a=build_event_manifest(events); b=build_event_manifest(events.copy())
    assert a==b and a['event_count']==len(events) and a['unique_event_ids']==len(events)
    rev=events.iloc[::-1].reset_index(drop=True)
    assert build_event_manifest(rev)['event_store_fingerprint'] != a['event_store_fingerprint']
