"""M6 Dev10 Trend / Broad Channel contribution helpers.

Context features remain explanatory variables over the frozen HIGH_PRICE_PROBE
universe. This module does not filter the universe, optimize thresholds or
calculate P&L.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

DEV10_SCHEMA_VERSION="POC_M6_TREND_CONTEXT_V1"
DEV10_VERDICT="M6_DEV10_TREND_BROAD_CHANNEL_NO_INCREMENTAL_SHORT_EDGE"
DEV10_CLASSIFICATION="REDUNDANT_FOR_SHORT_DIRECTION_WITH_UNADJUSTED_TREND_CONTINUATION_HINT"
LOOKBACKS=(6,8,12,16,24)

@dataclass(frozen=True)
class TrendContextConfig:
    lookback:int=24
    broad_quantile:float=.50
    def validate(self):
        if self.lookback not in LOOKBACKS: raise ValueError("unsupported lookback")
        if not 0 < self.broad_quantile < 1: raise ValueError("broad_quantile must be in (0,1)")

def session_rank(frame:pd.DataFrame,column:str)->pd.Series:
    if column not in frame or "session" not in frame: raise ValueError("missing session/rank column")
    return frame.groupby("session",sort=False)[column].rank(pct=True,method="average")

def label_context(frame:pd.DataFrame,config:TrendContextConfig=TrendContextConfig())->pd.DataFrame:
    config.validate(); L=config.lookback
    sc=f"slope_atr_{L}"; wc=f"channel_width_atr_{L}"
    miss={sc,wc,"session"}-set(frame.columns)
    if miss: raise ValueError(f"missing context columns: {sorted(miss)}")
    out=frame.copy(); out["rising_context"]=pd.to_numeric(out[sc],errors="raise")>0
    out["channel_width_rank"]=session_rank(out,wc)
    out["broad_context"]=out.channel_width_rank>=config.broad_quantile
    out["rising_broad_context"]=out.rising_context & out.broad_context
    return out

def bh_fdr(pvalues):
    p=np.asarray(pvalues,float)
    if p.ndim!=1 or len(p)==0 or np.any(~np.isfinite(p)) or np.any((p<0)|(p>1)): raise ValueError("invalid p-values")
    n=len(p); order=np.argsort(p); q=np.empty(n); prev=1.0
    for j in range(n-1,-1,-1):
        i=order[j]; prev=min(prev,p[i]*n/(j+1),1.0); q[i]=prev
    return q

def classify_dev10(*,global_positive:bool,context_directional_increment:bool,conditional_increment:bool)->dict:
    if global_positive or context_directional_increment or conditional_increment:
        return {"verdict":"DEV10_REQUIRES_REVIEW","classification":None}
    return {"verdict":DEV10_VERDICT,"classification":DEV10_CLASSIFICATION}
