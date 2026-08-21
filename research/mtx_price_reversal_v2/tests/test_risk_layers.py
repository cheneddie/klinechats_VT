import pandas as pd
from engine.execution_tick import FillModel
from engine.risk import StructuralRisk,CatastrophicRisk,RiskPlan,ExitReason,long_risk_triggers,resolve_long_risk_exit


def test_structural_and_catastrophic_stay_separate():
    t=pd.DataFrame({"_seq":[1,2,3,4,5],"datetime":["2026-01-01 09:00:01"]*5,"price":[100,97,94,89,88]})
    p=RiskPlan(StructuralRisk(95,"SIGNAL_EXTREME"),CatastrophicRisk(90,"HARD_MAX"))
    ts=long_risk_triggers(t,p,after_seq=1)
    assert ts.structural.seq==3 and ts.catastrophic.seq==4
    r=resolve_long_risk_exit(t,p,after_seq=1,fill_model=FillModel.NEXT_PHYSICAL_PRINT)
    assert r.reason==ExitReason.STRUCTURAL_STOP and r.trigger.seq==3 and r.fill.seq==4


def test_catastrophic_can_save_when_structural_absent():
    t=pd.DataFrame({"_seq":[1,2,3],"datetime":["2026-01-01 09:00:01"]*3,"price":[100,96,89]})
    p=RiskPlan(StructuralRisk(None),CatastrophicRisk(90,"HARD_MAX"))
    r=resolve_long_risk_exit(t,p,after_seq=1,fill_model=FillModel.TRIGGER_PRINT_DIAGNOSTIC)
    assert r.reason==ExitReason.CATASTROPHIC_STOP
