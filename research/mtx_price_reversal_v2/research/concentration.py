from __future__ import annotations
import pandas as pd

def top_day_concentration(trades:pd.DataFrame,pnl_col="net",date_col="trade_day",top_n=(1,3,5)):
    d=trades.groupby(date_col)[pnl_col].sum().sort_values(ascending=False); total=trades[pnl_col].sum()
    return {f"top_{n}_days_share":float(d.head(n).sum()/total) if total else float("nan") for n in top_n}
