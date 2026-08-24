import pandas as pd, numpy as np, pytest
from server.poc_absorption.universe_baseline import *

def sample(n=200):
 rows=[]
 for i in range(n):
  mfe=1+(i%5)*.1; mae=1+((i+2)%5)*.1
  rows.append({'event_key':f'e{i}','session':'day' if i%3==0 else 'night','trading_day_int':19724+i//10,'atr':5+(i%7),'mfe_30m_atr':mfe,'mae_30m_atr':mae,'break_30m':i%2==0,'balance_5m_eff':.05+(i%3)*.01,'balance_5m_two_sided_min_atr':.4,'sanity_full_30m':i%17!=0,'poc_delta_1':999+i,'tdp_ratio':-.9})
 return pd.DataFrame(rows)

def test_primary_excludes_noncomparable_30m_observation():
 x=sample(); y=primary_full30_view(x); assert len(y)==int(x.sanity_full_30m.sum())

def test_baseline_ignores_predictor_values():
 x=sample(); a=baseline_metrics(primary_full30_view(x)); x['poc_delta_1']=-1e12; x['tdp_ratio']=1.0; b=baseline_metrics(primary_full30_view(x)); assert a==b

def test_metrics_are_paired_short_side_outcomes():
 x=sample(20); y=primary_full30_view(x); m=baseline_metrics(y); assert np.isclose(m['paired_asym_mean_atr'],(y.mfe_30m_atr-y.mae_30m_atr).mean())

def test_cluster_bootstrap_deterministic():
 y=primary_full30_view(sample()); a=bootstrap_ci(y,mode='trading_day',n_resamples=100,seed=7); b=bootstrap_ci(y,mode='trading_day',n_resamples=100,seed=7); assert a==b

def test_episode_and_day_bootstrap_are_separate():
 y=primary_full30_view(sample()); a=bootstrap_ci(y,mode='episode',n_resamples=100,seed=9); b=bootstrap_ci(y,mode='trading_day',n_resamples=100,seed=9); assert a!=b

def test_neutral_verdict_requires_both_cluster_intervals_cover_null():
 ci={'mean_asym_atr':{'ci95':[-.1,.2]},'p_mfe_gt_mae':{'ci95':[.48,.52]},'break_30m_rate':{'ci95':[.5,.6]}}; assert directional_baseline_verdict(ci)==BASELINE_VERDICT
 ci['p_mfe_gt_mae']['ci95']=[.51,.55]; assert directional_baseline_verdict(ci)!='NO_STABLE_SHORT_DIRECTIONAL_ASYMMETRY_AT_30M'

def test_no_strategy_semantics_are_produced():
 y=primary_full30_view(sample()); m=baseline_metrics(y); forbidden={'pnl','profit_factor','threshold','best_horizon','trade_signal','entry'}; assert not forbidden.intersection(m)

def test_invalid_duplicate_event_store_rejected():
 x=sample(); x.loc[1,'event_key']=x.loc[0,'event_key'];
 with pytest.raises(ValueError): prepare_baseline(x)
