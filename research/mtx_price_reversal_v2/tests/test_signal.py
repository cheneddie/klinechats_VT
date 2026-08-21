import pandas as pd
from engine.signal import crossings

def test_true_crossing_not_first_window_below():
    s=pd.Series([-10,-12,-15],index=[1,2,3],dtype=float)
    assert len(crossings(s,-5))==0
    s=pd.Series([-1,-2,-6,-7],index=[1,2,3,4],dtype=float)
    assert crossings(s,-5).tolist()==[3]
