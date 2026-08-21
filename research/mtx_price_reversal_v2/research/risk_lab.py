from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from engine.execution_tick import first_long_stop_trigger

@dataclass(frozen=True)
class StopResult:
    triggered:bool
    seq:int|None
    price:float|None

def evaluate_long_stop(ticks:pd.DataFrame,entry_seq:int,stop_price:float)->StopResult:
    f=first_long_stop_trigger(ticks,stop_price,after_seq=entry_seq)
    return StopResult(False,None,None) if f is None else StopResult(True,f.seq,f.price)
