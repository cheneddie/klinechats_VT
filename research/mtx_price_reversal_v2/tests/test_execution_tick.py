import pandas as pd
from engine.execution_tick import first_long_stop_trigger,first_long_target_trigger,first_of

def test_same_second_stop_target_uses_physical_seq():
    t=pd.DataFrame({"_seq":[10,11,12],"datetime":["2026-01-01 09:00:01"]*3,"price":[100,95,105]})
    stop=first_long_stop_trigger(t,96,after_seq=10); target=first_long_target_trigger(t,104,after_seq=10)
    assert stop.seq==11 and target.seq==12 and first_of(stop,target).seq==11

def test_reject_non_monotonic_seq():
    t=pd.DataFrame({"_seq":[2,1],"datetime":["2026-01-01 09:00:01"]*2,"price":[100,99]})
    try: first_long_stop_trigger(t,99,after_seq=0)
    except ValueError: return
    assert False
