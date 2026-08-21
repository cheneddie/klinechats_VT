import pandas as pd
from engine.execution_tick import FillModel,Side,first_long_stop_trigger,first_long_target_trigger,first_of_triggers,market_order_from_trigger,fill_market_order


def _ticks(prices,seqs=None,times=None):
    n=len(prices)
    return pd.DataFrame({"_seq":seqs or list(range(10,10+n)),"datetime":times or ["2026-01-01 09:00:01"]*n,"price":prices})


def test_same_second_stop_target_uses_physical_seq():
    t=_ticks([100,95,105]); stop=first_long_stop_trigger(t,96,after_seq=10); target=first_long_target_trigger(t,104,after_seq=10)
    assert stop.seq==11 and target.seq==12 and first_of_triggers(stop,target).seq==11


def test_stop_trigger_is_not_fill_and_next_print_slips():
    t=_ticks([100,95,92],seqs=[100,101,102]); trig=first_long_stop_trigger(t,96,after_seq=100)
    order=market_order_from_trigger(trig,side=Side.SELL,reason="STRUCTURAL_STOP"); fill=fill_market_order(t,order,model=FillModel.NEXT_PHYSICAL_PRINT)
    assert trig.seq==101 and trig.price==95 and fill.seq==102 and fill.price==92 and fill.slippage_points==3


def test_trigger_print_is_diagnostic_only():
    t=_ticks([100,95,92],seqs=[100,101,102]); trig=first_long_stop_trigger(t,96,after_seq=100); order=market_order_from_trigger(trig,side=Side.SELL)
    fill=fill_market_order(t,order,model=FillModel.TRIGGER_PRINT_DIAGNOSTIC); assert fill.seq==101 and fill.price==95


def test_delayed_print_stress():
    t=_ticks([100,95,92,90],seqs=[100,101,102,103]); trig=first_long_stop_trigger(t,96,after_seq=100); order=market_order_from_trigger(trig,side=Side.SELL)
    fill=fill_market_order(t,order,model=FillModel.DELAYED_PHYSICAL_PRINT,delayed_prints=2); assert fill.seq==103 and fill.price==90 and fill.slippage_points==5


def test_reject_non_monotonic_seq():
    t=_ticks([100,99],seqs=[2,1])
    try: first_long_stop_trigger(t,99,after_seq=0)
    except ValueError: return
    assert False
