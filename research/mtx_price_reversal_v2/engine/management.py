from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FixedTimeManagement:
    max_holding_sec: int = 300


@dataclass(frozen=True)
class PathState:
    horizon_sec: int
    pnl: float
    mfe: float
    mae: float
    recovery_from_low: float
    new_low_count: int
    seconds_since_new_low: float
    distance_to_entry: float
    distance_to_signal_low: float | None
    path_efficiency: float
    vol_normalized_pnl: float | None
    bounce_ratio: float | None


def _window(ticks: pd.DataFrame, *, entry_seq: int, horizon_sec: int) -> pd.DataFrame:
    if horizon_sec <= 0: raise ValueError("horizon_sec must be positive")
    entry=ticks[ticks["_seq"]==entry_seq]
    if entry.empty: raise ValueError("entry_seq not present in ticks")
    entry_time=pd.Timestamp(entry.iloc[0].datetime)
    dt=pd.to_datetime(ticks["datetime"])
    return ticks[(ticks["_seq"]>=entry_seq)&(dt<=entry_time+pd.Timedelta(seconds=horizon_sec))].copy()


def path_state_at(ticks: pd.DataFrame, *, entry_seq: int, horizon_sec: int, signal_low: float | None = None, prior_causal_vol: float | None = None) -> PathState:
    """Causal state: only prints available through entry+horizon are visible."""
    x=_window(ticks,entry_seq=entry_seq,horizon_sec=horizon_sec)
    p=x["price"].astype(float).to_numpy(); t=pd.to_datetime(x["datetime"])
    entry_price=float(p[0]); last_price=float(p[-1]); low=float(np.min(p)); high=float(np.max(p))
    running_low=np.minimum.accumulate(p); new_low=np.r_[True,running_low[1:]<running_low[:-1]]
    last_low_idx=int(np.where(new_low)[0][-1]); total_variation=float(np.abs(np.diff(p)).sum()) if len(p)>1 else 0.0
    vol_norm=None if prior_causal_vol is None or not np.isfinite(prior_causal_vol) or prior_causal_vol<=0 else float((last_price-entry_price)/prior_causal_vol)
    adverse=entry_price-low; recovery=last_price-low
    return PathState(
        horizon_sec=horizon_sec,pnl=float(last_price-entry_price),mfe=float(high-entry_price),mae=float(low-entry_price),
        recovery_from_low=float(recovery),new_low_count=int(new_low.sum()-1),seconds_since_new_low=float((t.iloc[-1]-t.iloc[last_low_idx]).total_seconds()),
        distance_to_entry=float(last_price-entry_price),distance_to_signal_low=None if signal_low is None else float(last_price-signal_low),
        path_efficiency=float(abs(last_price-entry_price)/total_variation) if total_variation>0 else 0.0,
        vol_normalized_pnl=vol_norm,bounce_ratio=None if adverse<=0 else float(recovery/adverse),
    )


def path_feature_vector(ticks: pd.DataFrame, *, entry_seq: int, horizons: tuple[int,...]=(15,30,60), signal_low: float|None=None, prior_causal_vol: float|None=None) -> dict:
    out={}
    for h in horizons:
        s=path_state_at(ticks,entry_seq=entry_seq,horizon_sec=h,signal_low=signal_low,prior_causal_vol=prior_causal_vol)
        for k,v in s.__dict__.items():
            if k!="horizon_sec": out[f"{k}_{h}"]=v
    return out


def counterfactual_exit_value(*, pnl_now: float, pnl_final: float) -> dict[str,float]:
    saved=max(0.0,pnl_now-pnl_final); lost=max(0.0,pnl_final-pnl_now)
    return {"pnl_now":float(pnl_now),"pnl_final":float(pnl_final),"saved_loss":float(saved),"lost_tail":float(lost),"net_management_value":float(pnl_now-pnl_final)}


# No fitted KEEP/EXIT rule here. Historical path features remain discovery-only
# until one rule is frozen before new OOS is inspected.
