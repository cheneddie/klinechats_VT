import pandas as pd
from engine.management import path_state_at,path_feature_vector,counterfactual_exit_value


def _ticks():
    return pd.DataFrame({"_seq":[1,2,3,4,5],"datetime":["2026-01-01 09:00:00","2026-01-01 09:00:10","2026-01-01 09:00:20","2026-01-01 09:00:40","2026-01-01 09:01:10"],"price":[100,95,97,104,200]})


def test_30s_state_cannot_see_future():
    s=path_state_at(_ticks(),entry_seq=1,horizon_sec=30,signal_low=94,prior_causal_vol=50)
    assert s.pnl==-3 and s.mfe==0 and s.mae==-5 and s.vol_normalized_pnl==-0.06


def test_feature_horizons_are_causal():
    f=path_feature_vector(_ticks(),entry_seq=1,horizons=(15,30,60))
    assert f["pnl_15"]==-5 and f["pnl_30"]==-3 and f["pnl_60"]==4


def test_counterfactual_saved_loss_vs_lost_tail():
    a=counterfactual_exit_value(pnl_now=-10,pnl_final=-100); b=counterfactual_exit_value(pnl_now=5,pnl_final=80)
    assert a["saved_loss"]==90 and b["lost_tail"]==75
