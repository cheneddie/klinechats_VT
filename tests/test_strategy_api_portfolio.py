from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.storage import tx, utcnow
from server.v5.strategy_api import _load_backtest
from server.v5.strategy_storage import migrate_strategy_db


def test_load_backtest_decodes_portfolio_audit_payload():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        migrate_strategy_db(db)
        policy = {
            "mode": "SINGLE_POSITION",
            "overlap_policy": "SKIP_WHILE_OPEN",
            "max_open_positions": 1,
            "reentry_cooldown_seconds": 60,
            "fixed_quantity": 2.0,
            "force_flat_time": "13:40:00",
        }
        audit = {
            "policy": policy,
            "policy_hash": "a" * 64,
            "skips": [
                {
                    "event_id": "E2",
                    "trade_id": "T2",
                    "reason": "PORTFOLIO_OVERLAP",
                }
            ],
        }
        with tx(db) as c:
            c.execute(
                """INSERT INTO backtest_runs(
                  backtest_run_id,research_run_id,campaign_id,strategy_key,strategy_hash,
                  parameters_json,parameters_hash,execution_model_id,execution_model_version,
                  execution_hash,code_commit,data_digest,mode,status,created_at,notes
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'COMPLETE',?,?)""",
                (
                    "bt-api-portfolio",
                    "research-qa",
                    None,
                    "MR_BROAD@V3",
                    "b" * 64,
                    "{}",
                    "c" * 64,
                    "PHYSICAL_MARKET",
                    "V1-PF-aaaaaaaa",
                    "d" * 64,
                    "qa",
                    "e" * 64,
                    "PHYSICAL_TICK",
                    utcnow(),
                    "portfolio API regression",
                ),
            )
            c.execute(
                "INSERT INTO backtest_metrics VALUES(?,?,?,?,?,?)",
                (
                    "bt-api-portfolio",
                    "portfolio_policy_audit",
                    "AUDIT",
                    "a" * 64,
                    1.0,
                    json.dumps(audit, sort_keys=True),
                ),
            )
            c.execute(
                "INSERT INTO backtest_metrics VALUES(?,?,?,?,?,?)",
                (
                    "bt-api-portfolio",
                    "trades",
                    "ALL",
                    "ALL",
                    1.0,
                    "{}",
                ),
            )

        loaded = _load_backtest(db, "bt-api-portfolio", trade_limit=0)
        assert loaded["summary"]["trades"] == 1.0
        assert loaded["portfolio_audit"]["policy"] == policy
        assert loaded["portfolio_audit"]["policy_hash"] == "a" * 64
        assert loaded["portfolio_audit"]["skips"][0]["reason"] == "PORTFOLIO_OVERLAP"


def test_load_backtest_uses_empty_default_for_malformed_portfolio_audit():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        migrate_strategy_db(db)
        with tx(db) as c:
            c.execute(
                """INSERT INTO backtest_runs(
                  backtest_run_id,research_run_id,campaign_id,strategy_key,strategy_hash,
                  parameters_json,parameters_hash,execution_model_id,execution_model_version,
                  execution_hash,code_commit,data_digest,mode,status,created_at,notes
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'COMPLETE',?,?)""",
                (
                    "bt-api-malformed",
                    "research-qa",
                    None,
                    "MR_BROAD@V3",
                    "b" * 64,
                    "{}",
                    "c" * 64,
                    "PHYSICAL_MARKET",
                    "V1",
                    "d" * 64,
                    "qa",
                    "e" * 64,
                    "PHYSICAL_TICK",
                    utcnow(),
                    "malformed portfolio API regression",
                ),
            )
            c.execute(
                "INSERT INTO backtest_metrics VALUES(?,?,?,?,?,?)",
                (
                    "bt-api-malformed",
                    "portfolio_policy_audit",
                    "AUDIT",
                    "bad",
                    0.0,
                    "{not-json",
                ),
            )

        loaded = _load_backtest(db, "bt-api-malformed", trade_limit=0)
        assert loaded["portfolio_audit"] == {}
