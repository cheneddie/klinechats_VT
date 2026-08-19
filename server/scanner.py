"""Compatibility module for the Fabio Decision Gym V2 scanner.

The production implementation lives in :mod:`server.engine`.  This wrapper is
kept so existing scripts importing ``server.scanner`` continue to work.
"""
from .engine import *  # noqa: F401,F403
