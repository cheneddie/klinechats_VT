from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from engine.execution_tick import FillModel
from engine.risk import RiskPlan, resolve_long_risk_exit


@dataclass(frozen=True)
class StopSimulation:
    exit_reason: str
    trigger_seq: int | None
    trigger_price: float | None
    fill_seq: int | None
    fill_price: float | None
    slippage_points: float | None


def evaluate_long_risk(ticks: pd.DataFrame, *, entry_seq: int, plan: RiskPlan, fill_model: FillModel = FillModel.NEXT_PHYSICAL_PRINT, delayed_prints: int = 1) -> StopSimulation:
    r=resolve_long_risk_exit(ticks,plan,after_seq=entry_seq,fill_model=fill_model,delayed_prints=delayed_prints)
    if r is None:
        return StopSimulation("NONE",None,None,None,None,None)
    return StopSimulation(r.reason.value,r.trigger.seq,r.trigger.price,None if r.fill is None else r.fill.seq,None if r.fill is None else r.fill.price,None if r.fill is None else r.fill.slippage_points)


def right_tail_retention(baseline_pnl, candidate_pnl, *, top_fracs=(0.01,0.05)) -> dict[str,float]:
    b=np.asarray(baseline_pnl,float); c=np.asarray(candidate_pnl,float)
    if len(b)!=len(c): raise ValueError("baseline and candidate must align one-to-one")
    out={}; order=np.argsort(b)[::-1]
    for frac in top_fracs:
        n=max(1,int(np.ceil(len(b)*frac))); idx=order[:n]; base=float(b[idx].sum()); cand=float(c[idx].sum()); k=int(frac*100)
        out[f"top_{k}pct_baseline_pnl"]=base; out[f"top_{k}pct_candidate_pnl"]=cand; out[f"top_{k}pct_retention"]=float(cand/base) if base!=0 else np.nan
    return out


def risk_efficiency(baseline_pnl, candidate_pnl) -> dict[str,float]:
    b=np.asarray(baseline_pnl,float); c=np.asarray(candidate_pnl,float)
    if len(b)!=len(c): raise ValueError("baseline and candidate must align one-to-one")
    delta=c-b; left=float(delta[b<0].clip(min=0).sum()); right=float((-delta[b>0]).clip(min=0).sum())
    return {"left_tail_loss_removed":left,"right_tail_profit_removed":right,"risk_efficiency":float(left/right) if right>0 else float("inf"),"net_management_value":float(delta.sum())}


def stop_cause_matrix(simulations: pd.DataFrame, reason_col="exit_reason") -> pd.DataFrame:
    if simulations.empty: return pd.DataFrame(columns=[reason_col,"count","share"])
    x=simulations[reason_col].value_counts(dropna=False).rename_axis(reason_col).reset_index(name="count"); x["share"]=x["count"]/x["count"].sum(); return x
