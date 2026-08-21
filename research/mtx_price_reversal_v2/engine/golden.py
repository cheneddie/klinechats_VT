from __future__ import annotations
from pathlib import Path
import json, math
import pandas as pd
from .metrics import profit_factor, max_drawdown

def validate_golden(trades_csv: Path, golden_json: Path, pnl_col="net2") -> dict:
    t=pd.read_csv(trades_csv); g=json.loads(golden_json.read_text(encoding="utf-8"))["expected"]
    pnl=t[pnl_col].astype(float)
    actual={"trades":len(t),"net2_total_points":float(pnl.sum()),"net2_expectancy_points":float(pnl.mean()),"profit_factor_net2_rounded":round(profit_factor(pnl),3),"max_drawdown_net2_points":max_drawdown(pnl)}
    checks={k:(math.isclose(actual[k],v,rel_tol=0,abs_tol=1e-9) if isinstance(v,float) else actual[k]==v) for k,v in g.items()}
    if not all(checks.values()): raise AssertionError({"expected":g,"actual":actual,"checks":checks})
    return actual
