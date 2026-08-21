from __future__ import annotations
import pandas as pd

def path_features(prices:pd.DataFrame,entry_price:float,entry_time,horizons=(30,60)):
    out={}; t=pd.to_datetime(prices["datetime"])
    for h in horizons:
        x=prices[(t>=pd.Timestamp(entry_time))&(t<=pd.Timestamp(entry_time)+pd.Timedelta(seconds=h))]
        if x.empty: continue
        out.update({f"pnl_{h}":float(x.iloc[-1].price-entry_price),f"mfe_{h}":float(x.price.max()-entry_price),f"mae_{h}":float(x.price.min()-entry_price)})
    return out
