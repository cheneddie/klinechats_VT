import pytest
from live.state_engine import SharedStateEngine

def test_one_position_only():
    e=SharedStateEngine(); e.on_entry()
    with pytest.raises(RuntimeError): e.on_entry()
    e.on_exit(); assert e.can_enter()
