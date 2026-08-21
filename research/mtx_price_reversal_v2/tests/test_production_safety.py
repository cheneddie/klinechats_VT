from pathlib import Path
import pandas as pd
import pytest
from engine.contracts import ContractWindow,ContractSelectionEngine,ContractSelectionError
from engine.manifest import source_descriptor,environment_descriptor
from engine.oos import EvaluationPolicy,evaluation_status,failed_oos_requires_new_version
from live.data_integrity import OnlineDataIntegrityMonitor
from live.lifecycle import StrategyStage,assert_transition
from live.persistent_state import SQLiteStateStore,StrategyState,deterministic_signal_id
from live.reconciliation import LocalPositionState,BrokerSnapshot,reconcile
from live.risk_limits import StrategyRiskLimits,RiskSnapshot,entry_allowed


def test_contract_schedule_is_causal_and_unique():
    e=ContractSelectionEngine([ContractWindow('202609',pd.Timestamp('2026-08-19 15:00'),pd.Timestamp('2026-09-16 15:00')),ContractWindow('202610',pd.Timestamp('2026-09-16 15:00'),pd.Timestamp('2026-10-21 15:00'))])
    assert e.select('2026-09-16 14:59:59').active_contract=='202609'
    assert e.select('2026-09-16 15:00:00').active_contract=='202610'
    with pytest.raises(ContractSelectionError): e.select('2026-08-01')


def test_signal_claim_is_idempotent(tmp_path:Path):
    s=SQLiteStateStore(tmp_path/'state.sqlite3'); sig=deterministic_signal_id('V1','202609',123)
    assert s.claim_signal(sig) and not s.claim_signal(sig)
    state=StrategyState('V1','202609',1,'E1','S1',999,sig); s.save_state(state); assert s.load_state()==state; s.close()


def test_reconciliation_feed_risk_lifecycle_and_oos(tmp_path:Path):
    r=reconcile(LocalPositionState('202609',0),BrokerSnapshot('202609',1)); assert not r.allow_new_entry and 'POSITION_MISMATCH' in r.reasons
    m=OnlineDataIntegrityMonitor(stale_after_sec=3); assert m.on_tick(seq=1,exchange_ts='2026-01-01 09:00:00',receive_ts='2026-01-01 09:00:00.1',price=100,expected_contract='202601',observed_contract='202601').ok
    assert 'DUPLICATE_SEQ' in m.on_tick(seq=1,exchange_ts='2026-01-01 09:00:01',receive_ts='2026-01-01 09:00:01.1',price=100,expected_contract='202601',observed_contract='202601').reasons
    lim=StrategyRiskLimits(100,20,5,3,1,3); ok,reasons=entry_allowed(lim,RiskSnapshot(-101,3,1,0.5,0,0)); assert not ok and 'DAILY_LOSS_LIMIT' in reasons
    with pytest.raises(ValueError): assert_transition(StrategyStage.FROZEN,StrategyStage.LIMITED_LIVE)
    assert evaluation_status(trading_days=120,event_clusters=99,policy=EvaluationPolicy())=='INFORMATION_ONLY'
    assert evaluation_status(trading_days=120,event_clusters=100,policy=EvaluationPolicy())=='FORMAL_GATE_ELIGIBLE'
    assert failed_oos_requires_new_version('V1','2027-01-31')['new_version_required']
    f=tmp_path/'raw'; f.write_bytes(b'abc'); assert source_descriptor(f)['size_bytes']==3 and len(source_descriptor(f)['sha256'])==64 and 'python' in environment_descriptor()
