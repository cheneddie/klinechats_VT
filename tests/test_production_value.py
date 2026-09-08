from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.production_deployment import create_deployment_from_gate
from server.v5.production_value import (
    audit_candidate_production_value,
    get_production_value_audit,
    record_production_value_audit,
    require_passing_production_value_audit,
)
from server.v5.storage import migrate_event_db, tx
from server.v5.strategy_storage import migrate_strategy_db

ROLES = (
    ("DISCOVERY", "d", 2023, ("01", "02")),
    ("VALIDATION", "v", 2024, ("03", "04")),
    ("FINAL_HOLDOUT", "h", 2025, ("05", "06")),
)


def seed_value_fixture(db: Path, *, missing_atr_role: str | None = None, year_weights=None):
    migrate_event_db(db)
    migrate_strategy_db(db)
    year_weights = year_weights or {2023: 1.0, 2024: 1.0, 2025: 1.0}
    with tx(db) as c:
        for role, run_id, year, months in ROLES:
            bt = f"bt-{run_id}"
            c.execute(
                """INSERT INTO candidate_evaluations(
                     evaluation_id,candidate_id,role,research_run_id,backtest_run_id,
                     parameters_hash,created_at,result_json
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (f"eval-{run_id}", "cand-value", role, run_id, bt, "p" * 64, "2026-01-01T00:00:00Z", "{}"),
            )
            for i, month in enumerate(months, start=1):
                event_id = f"{run_id}-e{i}"
                day = f"{year}-{month}-02"
                payload = "{}" if role == missing_atr_role else '{"atr":10.0}'
                c.execute(
                    """INSERT INTO events(
                         research_run_id,event_id,year,trading_date,features_json,nodes_json,payload_json
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (run_id, event_id, year, day, "{}", "{}", payload),
                )
                weight = float(year_weights[year])
                c.execute(
                    """INSERT INTO backtest_trades(
                         backtest_run_id,trade_id,event_id,trading_date,year,month,
                         net_points,net_r,regime_json,payload_json
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (bt, f"{bt}-t{i}", event_id, day, year, f"{year}-{month}", 2.0 * weight, 1.0 * weight, "{}", "{}"),
                )


def passing_policy():
    return {
        "min_avg_net_points_over_atr": 0.10,
        "max_positive_month_profit_share": 0.50,
        "max_positive_year_profit_share": 0.50,
    }


def test_value_audit_uses_frozen_event_atr_and_pools_real_years_and_months():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        seed_value_fixture(db)
        audit = audit_candidate_production_value(db, "cand-value", policy=passing_policy())

        assert audit["passed"] is True
        for role in ("DISCOVERY", "VALIDATION", "FINAL_HOLDOUT"):
            assert audit["roles"][role]["atr_coverage_rate"] == 1.0
            assert audit["roles"][role]["avg_net_points_over_atr"] == pytest.approx(0.20)
        assert audit["month_concentration"]["profitable_group_count"] == 6
        assert audit["month_concentration"]["largest_positive_profit_share"] == pytest.approx(1 / 6)
        assert audit["year_concentration"]["profitable_group_count"] == 3
        assert audit["year_concentration"]["largest_positive_profit_share"] == pytest.approx(1 / 3)
        assert audit["methodology"]["roles"].startswith("year/month concentration")


def test_value_audit_fails_closed_when_atr_is_missing_or_concentration_policy_is_unfrozen():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        seed_value_fixture(db, missing_atr_role="VALIDATION")
        audit = audit_candidate_production_value(db, "cand-value", policy={})

        assert audit["passed"] is False
        assert "VALIDATION_ATR_COVERAGE" in audit["failed_checks"]
        assert "VALIDATION_AVG_NET_POINTS_OVER_ATR" in audit["failed_checks"]
        assert "MONTH_CONCENTRATION_POLICY" in audit["failed_checks"]
        assert "YEAR_CONCENTRATION_POLICY" in audit["failed_checks"]


def test_value_audit_rejects_single_year_profit_dependency():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        seed_value_fixture(db, year_weights={2023: 8.0, 2024: 1.0, 2025: 1.0})
        policy = passing_policy()
        policy["max_positive_year_profit_share"] = 0.60
        audit = audit_candidate_production_value(db, "cand-value", policy=policy)

        assert audit["year_concentration"]["largest_positive_profit_share"] == pytest.approx(0.80)
        assert "YEAR_PROFIT_CONCENTRATION" in audit["failed_checks"]
        assert audit["passed"] is False


def test_production_value_audit_is_append_only_hash_verified_and_required_for_deploy():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        seed_value_fixture(db)
        audit = audit_candidate_production_value(db, "cand-value", policy=passing_policy())
        saved = record_production_value_audit(db, "gate-value-1", "cand-value", audit)

        assert saved["passed"] is True
        assert saved["hash_valid"] is True
        assert require_passing_production_value_audit(db, "gate-value-1")["passed"] is True

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            with tx(db) as c:
                c.execute(
                    "UPDATE production_value_audits SET passed=0 WHERE production_gate_id='gate-value-1'"
                )
        with pytest.raises(KeyError, match="production value audit not found"):
            get_production_value_audit(db, "legacy-gate-without-value-audit")


def test_deployment_core_fails_before_gate_context_when_value_audit_is_missing():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        with pytest.raises(KeyError, match="production value audit not found"):
            create_deployment_from_gate(db, "legacy-pass-gate-without-value-audit")
