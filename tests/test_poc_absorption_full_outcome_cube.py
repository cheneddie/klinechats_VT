import numpy as np,pandas as pd,pytest
from server.poc_absorption.full_outcome_cube import *

def F():
    a=[]
    for i,(tf,s,n,e,p) in enumerate([('15s','day',1,'e1','p1'),('15s','day',2,'e2','p1'),('30s','night',1,'e3','p2'),('1m','day',1,'e4','p3'),('3m','night',1,'e5','p4'),('5m','day',1,'e6','p5'),('15m','night',1,'e7','p6')]):
        a.append(dict(event_id=e,episode_id=p,episode_trigger_number=n,timeframe=tf,session=s,h_30s_mfe_atr=.1+i,h_5m_mfe_atr=.2+i,h_30m_mfe_atr=.4+i,h_30m_mae_atr=.5+i,h_5m_one_second_path_efficiency=.05,h_5m_two_sided_min_excursion_atr=.2,h_5m_any_structure_break=i%2==0,h_15m_any_structure_break=True,h_30m_any_structure_break=i>1,h_session_end_any_structure_break=True))
    return pd.DataFrame(a)
def test_valid_and_first_view(): assert len(first_trigger_per_episode_view(F()))==6
def test_duplicate_rejected():
    x=F();x.loc[1,'event_id']='e1'
    with pytest.raises(ValueError):validate_full_year_outcomes(x)
def test_bad_episode_number_rejected():
    x=F();x.loc[0,'episode_trigger_number']=0
    with pytest.raises(ValueError):validate_full_year_outcomes(x)
def test_cube_has_two_views_and_12_rows():
    x=summarize_full_outcome_cube(F());assert len(x)==12 and set(x.view)=={'raw_trigger','first_trigger_per_episode'}
def test_no_observation_is_na_not_false():
    x=F();x['h_5m_any_structure_break']=pd.array(x.h_5m_any_structure_break,dtype='boolean');x.loc[x.timeframe.eq('1m'),'h_5m_any_structure_break']=pd.NA
    r=summarize_full_outcome_cube(x).query("view=='raw_trigger' and timeframe=='1m'").iloc[0];assert np.isnan(r.break_5m_rate)
def test_audit_requires_exact_count_and_zero_mismatch():
    x=pd.DataFrame({'event_id':['a']*2,'horizon':['30s','1m'],'pass':[True,True],'mismatch_fields':['','']});assert validate_audit_ledger(x,2)['all_pass'];x.loc[1,'mismatch_fields']='mfe';assert not validate_audit_ledger(x,2)['all_pass']
def test_seedless_sample_stable():
    x=pd.DataFrame([{'event_id':f'{t}-{s}-{i}','timeframe':t,'session':s} for t in FROZEN_TIMEFRAMES for s in ('day','night') for i in range(6)]);a=deterministic_full_year_audit_sample(x);b=deterministic_full_year_audit_sample(x.sample(frac=1,random_state=1));assert sorted(a.event_id)==sorted(b.event_id) and len(a)==60
