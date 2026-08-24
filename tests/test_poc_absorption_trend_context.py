import numpy as np,pandas as pd,pytest
from server.poc_absorption.trend_context import *

def frame():
 return pd.DataFrame({'session':['day']*4+['night']*4,'slope_atr_24':[-.1,.1,.2,.3,-.2,.05,.1,.2],'channel_width_atr_24':[1,2,3,4,10,20,30,40]})
def test_rising_is_fixed_zero_sign_not_outcome_tuned():
 x=label_context(frame()); assert x.rising_context.tolist()==[False,True,True,True,False,True,True,True]
def test_broad_is_within_session_ranked():
 x=label_context(frame()); assert x.broad_context.tolist()==[False,True,True,True,False,True,True,True]
def test_rising_broad_is_intersection():
 x=label_context(frame()); assert np.array_equal(x.rising_broad_context,x.rising_context&x.broad_context)
def test_invalid_quantile_fails_closed():
 with pytest.raises(ValueError): TrendContextConfig(broad_quantile=1).validate()
def test_invalid_lookback_fails_closed():
 with pytest.raises(ValueError): TrendContextConfig(lookback=7).validate()
def test_bh_fdr_is_monotone_in_sorted_order():
 p=np.array([.01,.03,.2,.8]); q=bh_fdr(p); o=np.argsort(p); assert np.all(np.diff(q[o])>=-1e-12)
def test_classifier_rejects_context_as_short_edge_when_all_gates_fail():
 r=classify_dev10(global_positive=False,context_directional_increment=False,conditional_increment=False); assert r['verdict']==DEV10_VERDICT and r['classification'].startswith('REDUNDANT')
def test_no_pnl_or_threshold_optimizer_surface():
 import server.poc_absorption.trend_context as m
 n=set(dir(m)); assert 'profit_factor' not in n and 'optimize_threshold' not in n
