"""M6 Dev8 POC dose-response statistics; discovery-only, no P&L or cutoff optimization."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd

POC_DOSE_SCHEMA_VERSION = "POC_M6_DEV8_DOSE_RESPONSE_V1"
FINAL_VERDICT = "POC_WEAK_SHORT_HORIZON_SIGNAL_NOT_MULTIPLICITY_ROBUST"


def bh_fdr(pvalues) -> np.ndarray:
    p=np.asarray(pvalues,float)
    if np.any((p<0)|(p>1)|~np.isfinite(p)): raise ValueError("pvalues must be finite in [0,1]")
    o=np.argsort(p);sp=p[o];n=len(p);adj=np.minimum.accumulate((sp*n/np.arange(1,n+1))[::-1])[::-1]
    out=np.empty(n);out[o]=np.minimum(adj,1.0);return out


def within_session_weakness_rank(frame: pd.DataFrame, feature: str, direction: int) -> pd.Series:
    if direction not in (-1,1): raise ValueError("direction must be +/-1")
    if feature not in frame or "session" not in frame: raise ValueError("missing feature/session")
    x=pd.to_numeric(frame[feature],errors="coerce")*direction
    return x.groupby(frame["session"].astype(str),sort=False).rank(method="average",pct=True)


def cluster_robust_slope(x,y,cluster) -> dict:
    x=np.asarray(x,float);y=np.asarray(y,float);c=np.asarray(cluster)
    m=np.isfinite(x)&np.isfinite(y);x=x[m];y=y[m];c=c[m]
    if len(x)<10 or len(np.unique(c))<2: raise ValueError("insufficient clustered sample")
    X=np.c_[np.ones(len(x)),x];inv=np.linalg.inv(X.T@X);b=inv@(X.T@y);u=y-X@b;M=np.zeros((2,2));groups=np.unique(c)
    for g in groups:
        z=X[c==g].T@u[c==g];M+=np.outer(z,z)
    N=len(x);G=len(groups);K=2;V=inv@M@inv*(G/(G-1))*((N-1)/(N-K));se=float(np.sqrt(max(V[1,1],0)));s=float(b[1]);p=math.erfc(abs(s/se)/math.sqrt(2)) if se else np.nan
    return {"N":N,"clusters":G,"slope":s,"se_cluster":se,"ci95":[s-1.96*se,s+1.96*se],"p_cluster":p}


def decile_summary(frame: pd.DataFrame, feature: str, direction: int, outcome: str) -> pd.DataFrame:
    if outcome not in frame: raise ValueError("missing outcome")
    z=frame.copy();z["weak_rank"]=within_session_weakness_rank(z,feature,direction);z=z[np.isfinite(z.weak_rank)&np.isfinite(pd.to_numeric(z[outcome],errors="coerce"))].copy()
    z["decile"]=np.minimum(np.ceil(z.weak_rank*10).astype(int),10)
    return z.groupby("decile",sort=True)[outcome].agg(["count","mean","median"]).reindex(range(1,11))


def global_multiplicity_verdict(results: pd.DataFrame, *, q_limit: float=.10) -> dict:
    req={"p_cluster","slope"};miss=req-set(results.columns)
    if miss: raise ValueError(f"missing {sorted(miss)}")
    q=bh_fdr(results.p_cluster.to_numpy(float));positive=(results.slope.to_numpy(float)>0)&(q<=q_limit)
    return {"tests":int(len(results)),"q_limit":float(q_limit),"positive_global_fdr_count":int(positive.sum()),"any_positive_global_fdr":bool(positive.any()),"q_values":q}


def classify_dev8(*, primary_30m_present: bool, short_15m_within_horizon_present: bool, global_fdr_present: bool) -> str:
    if primary_30m_present or global_fdr_present:
        return "POC_DOSE_RESPONSE_PRESENT"
    if short_15m_within_horizon_present:
        return FINAL_VERDICT
    return "POC_NO_INCREMENTAL_INFORMATION"
