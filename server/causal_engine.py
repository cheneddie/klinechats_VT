"""Production Fabio Decision Gym scanner facade.

This module binds the core state/event scanner to the causal calendar contract
selector. Import this module (rather than `server.engine`) for research, replay
indexing and future live-compatible scans.
"""
from . import engine as _engine
from .contracts import choose_contracts as _causal_choose_contracts

# `scan_files` resolves `choose_contracts` in server.engine's global namespace at
# runtime, so bind the causal selector once during module import.
_engine.choose_contracts = _causal_choose_contracts

from .engine import *  # noqa: F401,F403,E402
