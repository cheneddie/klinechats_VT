from pathlib import Path
import pandas as pd
import pytest
from engine.oos import load_lock,assert_oos_rows_after_lock

def test_oos_lock_rejects_historical_rows():
    lock=load_lock(Path(__file__).parents[1]/"OOS_LOCK.json")
    with pytest.raises(ValueError): assert_oos_rows_after_lock(pd.Series(["2026-08-14 13:44:59"]),lock)
