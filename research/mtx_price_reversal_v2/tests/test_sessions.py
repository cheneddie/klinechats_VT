import pandas as pd
from engine.sessions import session_labels

def test_after_midnight_belongs_previous_night_session():
    d=pd.Series(pd.to_datetime(["2026-08-21 16:00:00","2026-08-22 01:00:00","2026-08-22 09:00:00"]))
    key,kind=session_labels(d)
    assert key.iloc[0]=="2026-08-21_N" and key.iloc[1]=="2026-08-21_N" and key.iloc[2]=="2026-08-22_D"
