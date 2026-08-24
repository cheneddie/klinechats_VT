import numpy as np,pandas as pd,pytest
from server.poc_absorption.poc_dose_response import *

def test_bh_fdr_known_values():
 q=bh_fdr([.001,.01,.04,.5]); assert np.allclose(q,[.004,.02,.05333333333333334,.5])
def test_bh_rejects_invalid():
 with pytest.raises(ValueError): bh_fdr([-.1,.2])
def test_session_rank_is_session_local_and_directional():
 d=pd.DataFrame({'session':['day']*3+['night']*3,'x':[1,2,3,10,20,30]});r=within_session_weakness_rank(d,'x',1);assert np.allclose(r,[1/3,2/3,1,1/3,2/3,1]);r2=within_session_weakness_rank(d,'x',-1);assert r2.iloc[0]==1 and r2.iloc[3]==1
def test_cluster_slope_positive():
 x=np.tile(np.linspace(0,1,20),5);c=np.repeat(np.arange(5),20);y=.2+.1*x+np.sin(np.arange(100))*.001;r=cluster_robust_slope(x,y,c);assert r['slope']>0 and r['ci95'][0]>0
def test_decile_summary_has_ten_bins():
 d=pd.DataFrame({'session':['day']*100,'x':np.arange(100),'y':np.arange(100)});s=decile_summary(d,'x',1,'y');assert len(s)==10 and s.loc[10,'mean']>s.loc[1,'mean']
def test_global_scope_can_downgrade_local_significance():
 r=pd.DataFrame({'p_cluster':[.005]+[.2]*137,'slope':[.04]+[.01]*137});g=global_multiplicity_verdict(r);assert g['tests']==138 and not g['any_positive_global_fdr'] and g['q_values'][0]>.10
def test_classifier_preserves_short_horizon_watchlist_not_edge():
 assert classify_dev8(primary_30m_present=False,short_15m_within_horizon_present=True,global_fdr_present=False)==FINAL_VERDICT
def test_classifier_promotes_only_global_or_primary_evidence():
 assert classify_dev8(primary_30m_present=False,short_15m_within_horizon_present=True,global_fdr_present=True)=='POC_DOSE_RESPONSE_PRESENT'
