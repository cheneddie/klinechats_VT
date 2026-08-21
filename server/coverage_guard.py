from __future__ import annotations

"""Causal source-coverage guard for Previous Value chaining.

This module deliberately uses only information known when the current observed
session begins: the previous observed day-session date and the current date.
It never looks at future ticks or outcomes.

The default policy is conservative: a normal Friday->Monday gap is three
calendar days and remains connected; any longer observed-session gap breaks the
Previous Value chain.  An exchange-calendar audit may impose stricter rules for
shorter missing-session gaps, but should never silently bridge a known hole.
"""

from datetime import date

COVERAGE_POLICY_VERSION = "CALENDAR_GAP_V1"
DEFAULT_MAX_PROFILE_GAP_CALENDAR_DAYS = 3


def evaluate_profile_coverage(
    previous_day: str | None,
    current_day: str,
    max_gap_calendar_days: int = DEFAULT_MAX_PROFILE_GAP_CALENDAR_DAYS,
) -> dict:
    if previous_day is None:
        return {
            "policy_version": COVERAGE_POLICY_VERSION,
            "previous_trading_date": None,
            "trading_date": current_day,
            "gap_calendar_days": None,
            "status": "FIRST_OBSERVED_DAY",
            "reason": "NO_PREVIOUS_OBSERVED_DAY_SESSION",
            "profile_chain_reset": False,
        }

    gap = (date.fromisoformat(current_day) - date.fromisoformat(previous_day)).days
    if gap <= 0:
        return {
            "policy_version": COVERAGE_POLICY_VERSION,
            "previous_trading_date": previous_day,
            "trading_date": current_day,
            "gap_calendar_days": gap,
            "status": "FAIL",
            "reason": "NON_INCREASING_OBSERVED_DAY_SEQUENCE",
            "profile_chain_reset": True,
        }

    reset = gap > int(max_gap_calendar_days)
    return {
        "policy_version": COVERAGE_POLICY_VERSION,
        "previous_trading_date": previous_day,
        "trading_date": current_day,
        "gap_calendar_days": gap,
        "status": "PROFILE_CHAIN_RESET" if reset else "PASS",
        "reason": (
            "CALENDAR_GAP_EXCEEDS_FROZEN_LIMIT"
            if reset
            else "CONTIGUOUS_OR_NORMAL_WEEKEND_GAP"
        ),
        "profile_chain_reset": reset,
    }


__all__ = [
    "COVERAGE_POLICY_VERSION",
    "DEFAULT_MAX_PROFILE_GAP_CALENDAR_DAYS",
    "evaluate_profile_coverage",
]
