import numpy as np
import pandas as pd
from research.risk_lab import right_tail_retention,risk_efficiency,stop_cause_matrix


def test_right_tail_retention_uses_baseline_winner_identity():
    b=np.array([-10,-5,1,10,100],float); c=np.array([-5,-2,1,8,50],float)
    r=right_tail_retention(b,c,top_fracs=(0.2,))
    assert r["top_20pct_baseline_pnl"]==100 and r["top_20pct_candidate_pnl"]==50 and r["top_20pct_retention"]==0.5


def test_risk_efficiency():
    b=np.array([-100,-50,100,200],float); c=np.array([-60,-40,90,180],float)
    r=risk_efficiency(b,c); assert r["left_tail_loss_removed"]==50 and r["right_tail_profit_removed"]==30


def test_stop_cause_matrix():
    x=pd.DataFrame({"exit_reason":["TIME_EXIT","STRUCTURAL_STOP","TIME_EXIT"]}); m=stop_cause_matrix(x)
    assert m["count"].sum()==3 and abs(m["share"].sum()-1)<1e-12
