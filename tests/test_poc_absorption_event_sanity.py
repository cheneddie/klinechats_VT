from __future__ import annotations
import numpy as np, pandas as pd, pytest
from server.poc_absorption.event_sanity import (
    SANITY_SAMPLING_VERSION, SanitySampleConfig, select_event_sanity_sample,
    validate_sanity_sample, validate_replay_ledger, validate_visual_manifest,
)

def synth(n=120):
    rows=[]; base=pd.Timestamp('2024-01-02')
    kinds=['mfe','mae','bal','str','none']
    for i in range(n):
        kind=kinds[(i//24)%5]; sess='day' if i%2==0 else 'night'; d=base+pd.Timedelta(days=i)
        trig=int((d+pd.Timedelta(hours=9 if sess=='day' else 16)).timestamp())
        mfe,mae,eff,two,br,delay=(100,1,.5,.2,True,300) if kind=='mfe' else (1,100,.5,.2,True,400) if kind=='mae' else (5,5,.0,3,True,200) if kind=='bal' else (3,3,.4,.5,True,1) if kind=='str' else (.2,.2,.4,.1,False,np.nan)
        rows.append({'event_key':f'e{i:03d}','session':sess,'trading_day_int':int(d.timestamp()//86400),'trigger_sec':trig,'atr':5.0,'mfe_30m_atr':mfe,'mae_30m_atr':mae,'balance_5m_eff':eff,'balance_5m_two_sided_min_atr':two,'break_30m':br,'break_second_approx':np.nan if not br else trig+delay,'sanity_full_30m':True})
    return pd.DataFrame(rows)

def cfg(): return SanitySampleConfig(per_category=2,day_quota=1,night_quota=1,month_cap=2,min_observed_span_30m_seconds=1740)

def test_relative_break_delay_not_absolute_timestamp():
    x=synth(); s=select_event_sanity_sample(x,cfg()); z=s[s.sanity_category=='structure_reversal']
    assert z.break_delay_seconds.max() <= 1800
    assert (z.break_second_approx > 1_000_000_000).all()

def test_deterministic_session_date_and_month_coverage():
    x=synth(); a=select_event_sanity_sample(x,cfg()); b=select_event_sanity_sample(x,cfg())
    assert a.event_key.tolist()==b.event_key.tolist(); assert a.event_key.is_unique
    r=validate_sanity_sample(a,cfg()); assert r['all_pass']
    for v in r['categories'].values(): assert v['day']==1 and v['night']==1 and v['unique_dates']==2

def test_truncated_observation_is_not_selectable():
    x=synth(); x.loc[:119,'sanity_full_30m']=False
    with pytest.raises(ValueError): select_event_sanity_sample(x,cfg())

def test_no_reaction_joint_low_raw_and_atr_normalized():
    x=synth();
    # Candidate with tiny R but huge ATR => 100 raw points; should lose to genuinely quiet candidates.
    extra=x.iloc[[0]].copy(); extra['event_key']='fake'; extra['session']='day'; extra['trading_day_int']+=400; extra['trigger_sec']+=400*86400; extra['mfe_30m_atr']=extra['mae_30m_atr']=.1; extra['atr']=1000.;extra['break_30m']=False;extra['break_second_approx']=np.nan
    y=pd.concat([x,extra],ignore_index=True); s=select_event_sanity_sample(y,cfg()); assert 'fake' not in s.loc[s.sanity_category=='no_reaction','event_key'].tolist()

def test_replay_ledger_validator_rejects_mismatch():
    s=select_event_sanity_sample(synth(),cfg()); h=s.sanity_sample_event_ids_sha256.iloc[0]
    led=pd.DataFrame({'event_key':s.event_key,'pass':True,'mismatch_fields':'','observation_span_seconds':1800,'sanity_sampling_version':SANITY_SAMPLING_VERSION,'sanity_sample_event_ids_sha256':h})
    assert validate_replay_ledger(s,led,cfg())['all_pass']; led.loc[0,'mismatch_fields']='mfe'; assert not validate_replay_ledger(s,led,cfg())['all_pass']

def test_visual_manifest_validator():
    s=select_event_sanity_sample(synth(),cfg()); h=s.sanity_sample_event_ids_sha256.iloc[0]
    cats=[{'sanity_category':c,'panels_reviewed':2,'visual_mismatches':0,'visual_verdict':'PASS'} for c in ['strong_mfe','strong_mae','high_balance','structure_reversal','no_reaction']]
    m={'sampling_version':SANITY_SAMPLING_VERSION,'sample_event_ids_sha256':h,'total_panels_reviewed':10,'total_visual_mismatches':0,'categories':cats,'all_pass':True}
    assert validate_visual_manifest(s,m,cfg())['all_pass']; m['total_visual_mismatches']=1; assert not validate_visual_manifest(s,m,cfg())['all_pass']

def test_dev6_defines_no_strategy_output():
    s=select_event_sanity_sample(synth(),cfg()); forbidden={'pnl','profit_factor','best_horizon','entry_signal','trade_signal','edge'}
    assert not (forbidden & {c.lower() for c in s.columns})
