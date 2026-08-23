"""M5 Dev5: 2024 full outcome cube aggregation; no strategy/P&L semantics."""
from __future__ import annotations
from hashlib import sha256
import numpy as np, pandas as pd

FULL_OUTCOME_CUBE_SCHEMA_VERSION='POC_M5_FULL_OUTCOME_CUBE_V1'
FULL_YEAR_AUDIT_VERSION='M5_DEV5_FULL_YEAR_AUDIT_V1'
FROZEN_TIMEFRAMES=('15s','30s','1m','3m','5m','15m')
EXPECTED_2024_COUNTS={'15s':(264970,111958),'30s':(132719,56095),'1m':(66248,27879),'3m':(22448,9366),'5m':(13848,5764),'15m':(5215,2935)}
REQ={'event_id','episode_id','episode_trigger_number','timeframe','session','h_30s_mfe_atr','h_5m_mfe_atr','h_30m_mfe_atr','h_30m_mae_atr','h_5m_one_second_path_efficiency','h_5m_two_sided_min_excursion_atr','h_5m_any_structure_break','h_15m_any_structure_break','h_30m_any_structure_break','h_session_end_any_structure_break'}

def validate_full_year_outcomes(x):
    miss=REQ-set(x.columns)
    if miss: raise ValueError(f'full_year_outcomes missing columns: {sorted(miss)}')
    if x.empty or x.event_id.isna().any() or not x.event_id.is_unique: raise ValueError('event_id must be non-null and unique')
    if x.episode_id.isna().any(): raise ValueError('episode_id must be non-null')
    if (pd.to_numeric(x.episode_trigger_number,errors='raise')<1).any(): raise ValueError('episode_trigger_number must be >=1')
    if not set(x.timeframe.astype(str)).issubset(FROZEN_TIMEFRAMES): raise ValueError('unsupported timeframe')
    if not set(x.session.astype(str)).issubset({'day','night'}): raise ValueError('unsupported session')
    return {'schema_version':FULL_OUTCOME_CUBE_SCHEMA_VERSION,'rows':len(x),'unique_event_id':x.event_id.nunique(),'unique_episode_id':x.episode_id.nunique()}

def first_trigger_per_episode_view(x):
    validate_full_year_outcomes(x); y=x.loc[pd.to_numeric(x.episode_trigger_number).eq(1)].copy()
    if not y.episode_id.is_unique: raise ValueError('first-trigger view must contain one row per episode')
    return y.reset_index(drop=True)

def validate_2024_frozen_counts(x):
    first=first_trigger_per_episode_view(x); rows={}; ok=True
    for tf,(er,ee) in EXPECTED_2024_COUNTS.items():
        r=int(x.timeframe.astype(str).eq(tf).sum()); e=int(first.timeframe.astype(str).eq(tf).sum()); p=(r,e)==(er,ee); ok &= p
        rows[tf]={'raw_triggers':r,'episodes':e,'expected_raw_triggers':er,'expected_episodes':ee,'pass':bool(p)}
    return {'timeframes':rows,'all_pass':bool(ok)}

def _med(x,c):
    v=pd.to_numeric(x[c],errors='coerce').dropna(); return float(v.median()) if len(v) else np.nan

def _rate(x,c):
    v=x[c].dropna()
    if not len(v): return np.nan
    if pd.api.types.is_bool_dtype(v.dtype): return float(v.astype(bool).mean())
    v=pd.to_numeric(v,errors='coerce').dropna(); return float(v.mean()) if len(v) else np.nan

def summarize_full_outcome_cube(x):
    validate_full_year_outcomes(x); first=first_trigger_per_episode_view(x); eps={tf:int(first.timeframe.astype(str).eq(tf).sum()) for tf in FROZEN_TIMEFRAMES}; rows=[]
    for view,src in [('raw_trigger',x),('first_trigger_per_episode',first)]:
        for tf in FROZEN_TIMEFRAMES:
            z=src.loc[src.timeframe.astype(str).eq(tf)]
            rows.append({'view':view,'timeframe':tf,'N':len(z),'episodes':eps[tf],'mfe_30s_median_atr':_med(z,'h_30s_mfe_atr'),'mfe_5m_median_atr':_med(z,'h_5m_mfe_atr'),'mfe_30m_median_atr':_med(z,'h_30m_mfe_atr'),'mae_30m_median_atr':_med(z,'h_30m_mae_atr'),'balance_5m_1s_efficiency_median':_med(z,'h_5m_one_second_path_efficiency'),'balance_5m_two_sided_min_atr_median':_med(z,'h_5m_two_sided_min_excursion_atr'),'break_5m_rate':_rate(z,'h_5m_any_structure_break'),'break_15m_rate':_rate(z,'h_15m_any_structure_break'),'break_30m_rate':_rate(z,'h_30m_any_structure_break'),'break_session_end_rate':_rate(z,'h_session_end_any_structure_break')})
    return pd.DataFrame(rows)

def deterministic_full_year_audit_sample(x,n=5):
    if not {'event_id','timeframe','session'}.issubset(x.columns) or n<1: raise ValueError('invalid audit input')
    y=x.copy(); y['_h']=y.event_id.astype(str).map(lambda s:sha256(s.encode()).hexdigest()); out=[]
    for tf in FROZEN_TIMEFRAMES:
        for sess in ('day','night'):
            g=y.loc[y.timeframe.astype(str).eq(tf)&y.session.astype(str).eq(sess)]
            if len(g)<n: raise ValueError('insufficient events for audit sample')
            out.append(g.sort_values(['_h','event_id'],kind='stable').head(n))
    return pd.concat(out,ignore_index=True).drop(columns='_h')

def validate_audit_ledger(x,expected_windows=576):
    if not {'event_id','horizon','pass','mismatch_fields'}.issubset(x.columns): raise ValueError('audit_ledger missing columns')
    passed=x['pass'].astype(str).str.lower().isin({'true','1'}); bad=(~passed)|x.mismatch_fields.fillna('').astype(str).str.strip().ne('')
    return {'schema_version':FULL_YEAR_AUDIT_VERSION,'windows':len(x),'expected_windows':expected_windows,'mismatches':int(bad.sum()),'all_pass':bool(len(x)==expected_windows and not bad.any())}
