"""Production Fabio Decision Gym scanner bindings.

The market-state/event implementation lives in :mod:`server.engine`.  This
module injects the causal MTX contract policy before exporting the production
API.  Keeping the binding explicit prevents an old diagnostic selector from
silently becoming the live/replay policy.
"""
from . import engine as _engine
from .contract_policy import choose_contracts as _causal_choose_contracts

# scan_files resolves choose_contracts from engine globals at call time.
_engine.choose_contracts = _causal_choose_contracts

ScanConfig = _engine.ScanConfig
connect = _engine.connect
discover = _engine.discover
catalog_file = _engine.catalog_file
daily_contract_volume = _engine.daily_contract_volume
profile_levels = _engine.profile_levels
valley_lvn = _engine.valley_lvn
scan_day = _engine.scan_day
write_events = _engine.write_events
read_replay_window = _engine.read_replay_window
scan_files = _engine.scan_files
choose_contracts = _causal_choose_contracts

__all__ = [
    "ScanConfig", "connect", "discover", "catalog_file", "daily_contract_volume",
    "profile_levels", "valley_lvn", "scan_day", "write_events",
    "read_replay_window", "scan_files", "choose_contracts",
]
