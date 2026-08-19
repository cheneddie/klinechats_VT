"""Compatibility module for the Fabio Decision Gym V2 scanner.

The production implementation is exposed by :mod:`server.causal_engine` so
strict/front-month scans do not use future whole-day volume to choose contracts.
"""
from .causal_engine import *  # noqa: F401,F403
