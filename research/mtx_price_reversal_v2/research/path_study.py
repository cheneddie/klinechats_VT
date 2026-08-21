from __future__ import annotations

import pandas as pd
from engine.management import path_feature_vector, counterfactual_exit_value


def build_path_features(ticks: pd.DataFrame, *, entry_seq: int, signal_low: float | None = None, prior_causal_vol: float | None = None, horizons: tuple[int,...]=(15,30,60)) -> dict:
    return path_feature_vector(ticks,entry_seq=entry_seq,horizons=horizons,signal_low=signal_low,prior_causal_vol=prior_causal_vol)


def management_counterfactuals(row: pd.Series, horizons=(30,60), final_col="gross_300") -> list[dict]:
    out=[]; final=float(row[final_col])
    for h in horizons:
        col=f"pnl_{h}"
        if col not in row or pd.isna(row[col]): continue
        d=counterfactual_exit_value(pnl_now=float(row[col]),pnl_final=final); d["horizon_sec"]=h; out.append(d)
    return out
