import numpy as np
import pandas as pd
import pytest
from server.poc_absorption.pressure_efficiency_edge import (
    DEV9_VERDICT, EdgeMapConfig, assign_pressure_efficiency_cells, cell_outcome_means,
    d_minus_b, cluster_ols, classify_dev9,
)

def sample():
    p=[1,2,3,4,5,6,7,8]
    e=[8,1,7,2,6,3,5,4]
    return pd.DataFrame({
        "session":["day"]*8+["night"]*8,
        "pressure":p+[v*10 for v in p],
        "eff":e+[v*10 for v in e],
        "y":np.linspace(.1,1.6,16),
    })

def test_cells_are_session_ranked_and_complete():
    x=assign_pressure_efficiency_cells(sample(),EdgeMapConfig("pressure","eff"))
    assert set(x.edge_cell)=={"A","B","C","D"}
    assert x.pressure_rank.between(0,1).all() and x.efficiency_rank.between(0,1).all()

def test_d_minus_b_is_explicit_incremental_pressure_contrast():
    x=assign_pressure_efficiency_cells(sample(),EdgeMapConfig("pressure","eff"))
    m=cell_outcome_means(x,["y"]); got=d_minus_b(m)["y"]
    assert np.isfinite(got)

def test_missing_columns_fail_closed():
    with pytest.raises(ValueError): assign_pressure_efficiency_cells(pd.DataFrame({"session":["day"]}))

def test_bad_split_fails_closed():
    with pytest.raises(ValueError): EdgeMapConfig(split_quantile=1.0).validate()

def test_cluster_ols_returns_finite_cluster_se():
    rng=np.random.default_rng(7); n=200; g=np.repeat(np.arange(20),10); x=rng.normal(size=n); y=.3*x+rng.normal(size=n)
    b,se=cluster_ols(y,np.c_[np.ones(n),x],g)
    assert np.isfinite(b).all() and np.isfinite(se).all() and se[1]>0

def test_classifier_rejects_original_absorption_when_all_incremental_gates_fail():
    r=classify_dev9(directional_pressure_supported=False,activity_adjusted_pressure_supported=False,buy_side_specific=False,efficiency_directional_edge=False)
    assert r["verdict"]==DEV9_VERDICT
    assert r["classification"]["raw_pressure_magnitude"]=="ACTIVITY_REGIME_ONLY"

def test_classifier_does_not_overclaim_when_any_core_gate_is_positive():
    r=classify_dev9(directional_pressure_supported=True,activity_adjusted_pressure_supported=False,buy_side_specific=False,efficiency_directional_edge=False)
    assert r["verdict"]=="DEV9_REQUIRES_REVIEW"

def test_no_strategy_or_pnl_api_exposed():
    import server.poc_absorption.pressure_efficiency_edge as m
    names=set(dir(m)); assert "profit_factor" not in names and "optimize_threshold" not in names and "strategy" not in names
