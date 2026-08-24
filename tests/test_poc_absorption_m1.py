from __future__ import annotations

import json
from pathlib import Path

from server.contracts import causal_front_month

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "config" / "poc_absorption" / "session_calendar_overrides_v1.json"


def test_front_month_rolls_after_third_wednesday():
    assert causal_front_month("2025-03-19", ["202503", "202504"]) == "202503"
    assert causal_front_month("2025-03-20", ["202503", "202504"]) == "202504"


def test_m1_calendar_overrides_keep_data_gap_separate_from_exchange_closure():
    payload = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    gaps = {item["date"] for item in payload["source_data_blackouts"]}
    closures = {item["date"] for item in payload["verified_exchange_closures"]}
    assert gaps == {"2024-12-27"}
    assert {"2026-02-12", "2026-02-13", "2026-07-10"}.issubset(closures)
    assert gaps.isdisjoint(closures)


def test_m1_policy_forbids_imputation():
    payload = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    assert payload["research_policy"]["imputation"] == "forbidden"
