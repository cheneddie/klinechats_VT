"""M6 Dev7 HIGH_PRICE_PROBE_V1 baseline; no predictor selection or P&L semantics."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

BASELINE_SCHEMA_VERSION = "POC_M6_UNIVERSE_BASELINE_V1"
BASELINE_VERDICT = "NO_STABLE_SHORT_DIRECTIONAL_ASYMMETRY_AT_30M"
PRIMARY_TIMEFRAME = "1m"
MIN_ACTUAL_30M_OBS_SECONDS = 1740
REQ = {
    "event_key", "session", "trading_day_int", "atr", "mfe_30m_atr", "mae_30m_atr",
    "break_30m", "balance_5m_eff", "balance_5m_two_sided_min_atr", "sanity_full_30m",
}

@dataclass(frozen=True)
class BaselineBootstrapConfig:
    episode_resamples: int = 3000
    trading_day_resamples: int = 3000
    pooled_resamples: int = 5000
    seed: int = 20260824


def prepare_baseline(frame: pd.DataFrame) -> pd.DataFrame:
    miss = REQ - set(frame.columns)
    if miss:
        raise ValueError(f"baseline missing columns: {sorted(miss)}")
    if frame.empty or frame.event_key.isna().any() or not frame.event_key.is_unique:
        raise ValueError("baseline expects unique first-trigger episode events")
    out = frame.copy()
    if not set(out.session.astype(str)).issubset({"day", "night"}):
        raise ValueError("unsupported session")
    for c in ["atr", "mfe_30m_atr", "mae_30m_atr", "balance_5m_eff", "balance_5m_two_sided_min_atr"]:
        out[c] = pd.to_numeric(out[c], errors="raise")
    if (~np.isfinite(out.atr.to_numpy(float)) | (out.atr.to_numpy(float) <= 0)).any():
        raise ValueError("event-time ATR must be finite >0")
    out["trading_date"] = pd.to_datetime(pd.to_numeric(out.trading_day_int), unit="D", origin="unix").dt.strftime("%Y-%m-%d")
    out["month"] = out.trading_date.str[:7]
    out["mfe_points"] = out.mfe_30m_atr * out.atr
    out["mae_points"] = out.mae_30m_atr * out.atr
    out["asym_atr"] = out.mfe_30m_atr - out.mae_30m_atr
    out["asym_points"] = out.mfe_points - out.mae_points
    out["mfe_gt_mae"] = (out.mfe_30m_atr > out.mae_30m_atr).astype(float)
    out["mfe_eq_mae"] = np.isclose(out.mfe_30m_atr, out.mae_30m_atr).astype(float)
    return out


def primary_full30_view(frame: pd.DataFrame) -> pd.DataFrame:
    x = prepare_baseline(frame)
    return x.loc[x.sanity_full_30m.astype(bool)].reset_index(drop=True)


def baseline_metrics(frame: pd.DataFrame) -> dict:
    x = prepare_baseline(frame) if "asym_atr" not in frame else frame
    return {
        "N": int(len(x)), "unique_days": int(x.trading_date.nunique()),
        "mfe_30m_median_atr": float(x.mfe_30m_atr.median()),
        "mae_30m_median_atr": float(x.mae_30m_atr.median()),
        "paired_asym_median_atr": float(x.asym_atr.median()),
        "paired_asym_mean_atr": float(x.asym_atr.mean()),
        "p_mfe_gt_mae": float(x.mfe_gt_mae.mean()), "p_tie": float(x.mfe_eq_mae.mean()),
        "mfe_30m_median_points": float(x.mfe_points.median()),
        "mae_30m_median_points": float(x.mae_points.median()),
        "paired_asym_median_points": float(x.asym_points.median()),
        "break_30m_rate": float(x.break_30m.astype(float).mean()),
        "balance_5m_eff_median": float(x.balance_5m_eff.median()),
        "balance_5m_two_sided_min_atr_median": float(x.balance_5m_two_sided_min_atr.median()),
        "atr_median": float(x.atr.median()),
    }

_STAT_NAMES = ("mean_asym_atr", "p_mfe_gt_mae", "break_30m_rate")

def _calc_arrays(a, g, br, idx):
    return np.array([np.mean(a[idx]), np.mean(g[idx]), np.mean(br[idx])], float)


def bootstrap_ci(frame: pd.DataFrame, *, mode: str, n_resamples: int, seed: int) -> dict:
    x = prepare_baseline(frame) if "asym_atr" not in frame else frame
    if n_resamples < 100:
        raise ValueError("n_resamples must be >=100")
    a=x.asym_atr.to_numpy(float);g=x.mfe_gt_mae.to_numpy(float);br=x.break_30m.to_numpy(float);d=x.trading_date.to_numpy(str)
    rng=np.random.default_rng(seed); vals=np.empty((n_resamples,3)); n=len(x)
    if mode == "episode":
        for b in range(n_resamples): vals[b]=_calc_arrays(a,g,br,rng.integers(0,n,n))
    elif mode == "trading_day":
        days=np.unique(d); groups=[np.flatnonzero(d==day) for day in days]; nd=len(days)
        for b in range(n_resamples):
            pick=rng.integers(0,nd,nd); idx=np.concatenate([groups[j] for j in pick]); vals[b]=_calc_arrays(a,g,br,idx)
    else:
        raise ValueError("mode must be episode or trading_day")
    q=np.quantile(vals,[.025,.5,.975],axis=0)
    return {k:{"median_boot":float(q[1,i]),"ci95":[float(q[0,i]),float(q[2,i])]} for i,k in enumerate(_STAT_NAMES)}


def directional_baseline_verdict(trading_day_ci: dict) -> str:
    asym=trading_day_ci["mean_asym_atr"]["ci95"]; p=trading_day_ci["p_mfe_gt_mae"]["ci95"]
    neutral=(asym[0] <= 0 <= asym[1]) and (p[0] <= .5 <= p[1])
    return BASELINE_VERDICT if neutral else "DIRECTIONAL_ASYMMETRY_REQUIRES_REVIEW"


def monthly_baseline(frame: pd.DataFrame) -> pd.DataFrame:
    x=prepare_baseline(frame) if "asym_atr" not in frame else frame; rows=[]
    for (sess,mo),z in x.groupby(["session","month"],sort=True):
        r={"session":str(sess),"month":str(mo)};r.update(baseline_metrics(z));rows.append(r)
    return pd.DataFrame(rows)
