from __future__ import annotations

"""Causal TAIFEX session-coverage guard for Previous Value chaining.

The old CALENDAR_GAP_V1 rule treated every long calendar gap as a data hole.
That is safe but wrong around legitimate exchange closures such as Lunar New
Year or typhoon suspensions. V2 instead asks a narrower causal question:

    Between the previous observed regular session and the current observed
    regular session, was there any *official TAIFEX trading session* that should
    have existed but is absent from the source?

Only dates strictly before the current observed session are examined. Official
closure facts are frozen in a versioned calendar file. No future price, volume,
outcome, regime, or strategy result is consulted.
"""

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

COVERAGE_POLICY_VERSION = "TAIFEX_SESSION_CALENDAR_V2"
# Kept only for the legacy persisted SQLite column / caller signature. V2 does
# not decide continuity by an arbitrary number of calendar days.
DEFAULT_MAX_PROFILE_GAP_CALENDAR_DAYS = 3
DEFAULT_CALENDAR_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "research"
    / "taifex_session_calendar_v1.json"
)


@lru_cache(maxsize=4)
def _load_calendar_cached(path_text: str) -> dict:
    path = Path(path_text)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("calendar_version") or not isinstance(payload.get("years"), dict):
        raise ValueError(f"Invalid TAIFEX session calendar: {path}")
    return payload


def load_exchange_calendar(path: str | Path | None = None) -> dict:
    return _load_calendar_cached(str(Path(path or DEFAULT_CALENDAR_PATH).resolve()))


def _year_info(calendar: dict, year: int) -> dict | None:
    return (calendar.get("years") or {}).get(str(int(year)))


def _closed_dates(calendar: dict, year: int) -> set[str] | None:
    info = _year_info(calendar, year)
    if info is None:
        return None
    return {str(x) for x in info.get("closed_dates") or []}


def is_official_trading_day(day: str | date, calendar: dict | None = None) -> bool | None:
    calendar = calendar or load_exchange_calendar()
    d = date.fromisoformat(day) if isinstance(day, str) else day
    closed = _closed_dates(calendar, d.year)
    if closed is None:
        return None
    return d.weekday() < 5 and d.isoformat() not in closed


def official_trading_sessions(year: int, calendar: dict | None = None) -> list[str]:
    calendar = calendar or load_exchange_calendar()
    if _year_info(calendar, year) is None:
        raise KeyError(f"TAIFEX calendar year unavailable: {year}")
    d = date(int(year), 1, 1)
    end = date(int(year), 12, 31)
    out: list[str] = []
    while d <= end:
        if is_official_trading_day(d, calendar):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def expected_sessions_between(
    previous_day: str,
    current_day: str,
    calendar: dict | None = None,
) -> tuple[list[str], list[int]]:
    """Return official trading sessions strictly between two observed dates.

    The second return value lists calendar years missing from the frozen
    calendar. A missing calendar year is fail-closed rather than silently
    interpreted as a holiday.
    """
    calendar = calendar or load_exchange_calendar()
    prev = date.fromisoformat(previous_day)
    cur = date.fromisoformat(current_day)
    expected: list[str] = []
    unavailable: set[int] = set()
    d = prev + timedelta(days=1)
    while d < cur:
        status = is_official_trading_day(d, calendar)
        if status is None:
            unavailable.add(d.year)
        elif status:
            expected.append(d.isoformat())
        d += timedelta(days=1)
    return expected, sorted(unavailable)


def evaluate_profile_coverage(
    previous_day: str | None,
    current_day: str,
    max_gap_calendar_days: int = DEFAULT_MAX_PROFILE_GAP_CALENDAR_DAYS,
    calendar: dict | None = None,
) -> dict:
    """Evaluate whether Previous Value may causally bridge to current_day.

    ``max_gap_calendar_days`` remains in the signature solely for compatibility
    with existing scanner calls and the legacy SQLite audit column. It is not a
    V2 decision input.
    """
    calendar = calendar or load_exchange_calendar()
    calendar_version = str(calendar.get("calendar_version") or "UNKNOWN")

    if previous_day is None:
        return {
            "policy_version": COVERAGE_POLICY_VERSION,
            "calendar_version": calendar_version,
            "previous_trading_date": None,
            "trading_date": current_day,
            "gap_calendar_days": None,
            "expected_sessions_between": [],
            "missing_expected_sessions": [],
            "status": "FIRST_OBSERVED_DAY",
            "reason": "NO_PREVIOUS_OBSERVED_DAY_SESSION",
            "profile_chain_reset": False,
        }

    prev = date.fromisoformat(previous_day)
    cur = date.fromisoformat(current_day)
    gap = (cur - prev).days
    if gap <= 0:
        return {
            "policy_version": COVERAGE_POLICY_VERSION,
            "calendar_version": calendar_version,
            "previous_trading_date": previous_day,
            "trading_date": current_day,
            "gap_calendar_days": gap,
            "expected_sessions_between": [],
            "missing_expected_sessions": [],
            "status": "FAIL",
            "reason": "NON_INCREASING_OBSERVED_DAY_SEQUENCE",
            "profile_chain_reset": True,
        }

    current_status = is_official_trading_day(cur, calendar)
    if current_status is None:
        return {
            "policy_version": COVERAGE_POLICY_VERSION,
            "calendar_version": calendar_version,
            "previous_trading_date": previous_day,
            "trading_date": current_day,
            "gap_calendar_days": gap,
            "expected_sessions_between": [],
            "missing_expected_sessions": [],
            "status": "FAIL",
            "reason": f"EXCHANGE_CALENDAR_YEAR_UNAVAILABLE|{cur.year}",
            "profile_chain_reset": True,
        }
    if current_status is False:
        return {
            "policy_version": COVERAGE_POLICY_VERSION,
            "calendar_version": calendar_version,
            "previous_trading_date": previous_day,
            "trading_date": current_day,
            "gap_calendar_days": gap,
            "expected_sessions_between": [],
            "missing_expected_sessions": [],
            "status": "FAIL",
            "reason": f"OBSERVED_REGULAR_SESSION_ON_OFFICIAL_CLOSED_DAY|{current_day}",
            "profile_chain_reset": True,
        }

    expected, unavailable = expected_sessions_between(previous_day, current_day, calendar)
    if unavailable:
        years = ",".join(str(x) for x in unavailable)
        return {
            "policy_version": COVERAGE_POLICY_VERSION,
            "calendar_version": calendar_version,
            "previous_trading_date": previous_day,
            "trading_date": current_day,
            "gap_calendar_days": gap,
            "expected_sessions_between": expected,
            "missing_expected_sessions": expected,
            "status": "FAIL",
            "reason": f"EXCHANGE_CALENDAR_YEAR_UNAVAILABLE|{years}",
            "profile_chain_reset": True,
        }

    # Because previous_day/current_day are consecutive *observed* regular
    # sessions, every official trading session strictly between them is absent
    # from the source by construction.
    missing = expected
    reset = bool(missing)
    return {
        "policy_version": COVERAGE_POLICY_VERSION,
        "calendar_version": calendar_version,
        "previous_trading_date": previous_day,
        "trading_date": current_day,
        "gap_calendar_days": gap,
        "expected_sessions_between": expected,
        "missing_expected_sessions": missing,
        "status": "PROFILE_CHAIN_RESET" if reset else "PASS",
        "reason": (
            "EXPECTED_TAIFEX_SESSION_MISSING|" + ",".join(missing)
            if reset
            else "EXCHANGE_CALENDAR_CONTIGUOUS"
        ),
        "profile_chain_reset": reset,
    }


def audit_observed_sessions(
    observed_days: list[str] | set[str],
    year: int,
    calendar: dict | None = None,
) -> dict:
    """File-level G1 coverage audit against the frozen official calendar."""
    calendar = calendar or load_exchange_calendar()
    expected = official_trading_sessions(year, calendar)
    expected_set = set(expected)
    observed = sorted({str(x) for x in observed_days if str(x).startswith(f"{int(year):04d}-")})
    observed_set = set(observed)
    missing = sorted(expected_set - observed_set)
    extra = sorted(observed_set - expected_set)
    last_observed = observed[-1] if observed else None
    interior_missing = [x for x in missing if last_observed is not None and x <= last_observed]
    tail_missing = [x for x in missing if last_observed is not None and x > last_observed]
    if extra:
        status = "EXTRA_NONTRADING_SESSION"
        reason = "OBSERVED_DAY_NOT_IN_FROZEN_TAIFEX_CALENDAR"
    elif interior_missing:
        status = "GAP"
        reason = "EXPECTED_TAIFEX_SESSION_MISSING_INSIDE_SOURCE_RANGE"
    elif tail_missing:
        status = "PARTIAL_YEAR"
        reason = "SOURCE_ENDS_BEFORE_LAST_EXPECTED_TAIFEX_SESSION"
    elif not missing:
        status = "PASS"
        reason = "FULL_FROZEN_CALENDAR_COVERAGE"
    else:
        status = "EMPTY"
        reason = "NO_OBSERVED_REGULAR_SESSIONS"
    return {
        "policy_version": COVERAGE_POLICY_VERSION,
        "calendar_version": calendar.get("calendar_version"),
        "year": int(year),
        "expected_days": len(expected),
        "observed_days": len(observed_set & expected_set),
        "coverage_rate": (len(observed_set & expected_set) / len(expected)) if expected else None,
        "first_observed": observed[0] if observed else None,
        "last_observed": last_observed,
        "missing_days": missing,
        "interior_missing_days": interior_missing,
        "tail_missing_days": tail_missing,
        "extra_days": extra,
        "status": status,
        "reason": reason,
    }


__all__ = [
    "COVERAGE_POLICY_VERSION",
    "DEFAULT_MAX_PROFILE_GAP_CALENDAR_DAYS",
    "DEFAULT_CALENDAR_PATH",
    "load_exchange_calendar",
    "is_official_trading_day",
    "official_trading_sessions",
    "expected_sessions_between",
    "evaluate_profile_coverage",
    "audit_observed_sessions",
]
