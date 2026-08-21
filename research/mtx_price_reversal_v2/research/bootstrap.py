from __future__ import annotations

import numpy as np
import pandas as pd


def cluster_bootstrap_expectancy(trades: pd.DataFrame, *, cluster_col: str, pnl_col: str = "net", n: int = 10000, seed: int = 7) -> dict[str,float]:
    if trades.empty:
        return {"mean":np.nan,"p2_5":np.nan,"median":np.nan,"p97_5":np.nan,"n_clusters":0,"n_bootstrap":int(n),"seed":int(seed)}
    g=trades.groupby(cluster_col)[pnl_col].agg(["sum","size"]).reset_index()
    rng=np.random.default_rng(seed); out=np.empty(n,float)
    for i in range(n):
        s=g.iloc[rng.integers(0,len(g),len(g))]
        out[i]=s["sum"].sum()/s["size"].sum()
    q=np.quantile(out,[.025,.5,.975])
    return {"mean":float(out.mean()),"p2_5":float(q[0]),"median":float(q[1]),"p97_5":float(q[2]),"n_clusters":int(len(g)),"n_bootstrap":int(n),"seed":int(seed)}


def day_cluster_bootstrap(trades: pd.DataFrame, pnl_col="net", day_col="trade_day", n=10000, seed=7):
    return cluster_bootstrap_expectancy(trades,cluster_col=day_col,pnl_col=pnl_col,n=n,seed=seed)
