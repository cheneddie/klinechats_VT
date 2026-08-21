from __future__ import annotations
import pandas as pd

def session_labels(dt: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Exchange-local MTX session key/kind without calendar-day leakage."""
    d = pd.to_datetime(dt)
    sec = d.dt.hour * 3600 + d.dt.minute * 60 + d.dt.second
    day = (sec >= 8*3600 + 45*60) & (sec <= 13*3600 + 45*60)
    night_pm = sec >= 15*3600
    night_am = sec <= 5*3600
    key = pd.Series(pd.NA, index=d.index, dtype="string")
    kind = pd.Series(pd.NA, index=d.index, dtype="string")
    date = d.dt.strftime("%Y-%m-%d")
    prev_date = (d - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    key.loc[day] = date.loc[day] + "_D"; kind.loc[day] = "D"
    key.loc[night_pm] = date.loc[night_pm] + "_N"; kind.loc[night_pm] = "N"
    key.loc[night_am] = prev_date.loc[night_am] + "_N"; kind.loc[night_am] = "N"
    return key, kind
