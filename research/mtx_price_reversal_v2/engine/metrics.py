from __future__ import annotations
import numpy as np
import pandas as pd

def profit_factor(pnl) -> float:
    a=np.asarray(pnl,dtype=float); gp=a[a>0].sum(); gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else float("nan")

def max_drawdown(pnl) -> float:
    e=np.cumsum(np.asarray(pnl,dtype=float)); peak=np.maximum.accumulate(np.r_[0.0,e])[1:]
    return float(np.min(e-peak)) if len(e) else 0.0

def expectancy(pnl) -> float:
    a=np.asarray(pnl,dtype=float); return float(a.mean()) if len(a) else float("nan")

def daily_sharpe(daily_pnl, periods=252) -> float:
    a=np.asarray(daily_pnl,dtype=float); sd=a.std(ddof=1)
    return float(a.mean()/sd*np.sqrt(periods)) if len(a)>1 and sd>0 else float("nan")

def day_cluster_bootstrap(trades: pd.DataFrame, pnl_col="net", day_col="trade_day", n=10000, seed=7):
    g=trades.groupby(day_col)[pnl_col].agg(["sum","size"]).reset_index()
    rng=np.random.default_rng(seed); out=[]
    for _ in range(n):
        s=g.iloc[rng.integers(0,len(g),len(g))]
        out.append(s["sum"].sum()/s["size"].sum())
    q=np.quantile(out,[.025,.5,.975])
    return {"mean":float(np.mean(out)),"p2_5":float(q[0]),"median":float(q[1]),"p97_5":float(q[2])}
