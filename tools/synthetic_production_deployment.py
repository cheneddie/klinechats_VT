from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.production_deployment import (
    create_deployment_from_gate,
    deployment_status,
    persist_deployment_monitor_snapshot,
    record_deployment_action,
)
from server.v5.production_gate import _migrate_gate_contexts
from server.v5.storage import connect, tx, utcnow
from server.v5.strategy_registry import content_hash

WARNING = "SYNTHETIC DEPLOYMENT UI FIXTURE - NOT MARKET EDGE OR PRODUCTION EVIDENCE"
CANDIDATE_ID = "cand-synthetic-deployment-ui"
GATE_ID = "pgate-synthetic-deployment-ui"
DEPLOYMENT_ID = "deploy-synthetic-ui-v1"
BACKTEST_ID = "bt-synthetic-mtx-mr-v1"


def _source_identity(event_db: Path) -> dict:
    c = connect(event_db)
    try:
        bt = c.execute(
            "SELECT * FROM backtest_runs WHERE backtest_run_id=?",
            (BACKTEST_ID,),
        ).fetchone()
        if not bt:
            raise RuntimeError(f"synthetic source backtest missing: {BACKTEST_ID}")
        bt = dict(bt)
        audit = c.execute(
            """SELECT slice_value FROM backtest_metrics
               WHERE backtest_run_id=? AND metric_key='portfolio_policy_audit' LIMIT 1""",
            (BACKTEST_ID,),
        ).fetchone()
    finally:
        c.close()
    if not audit:
        raise RuntimeError("synthetic source backtest is missing portfolio policy audit")
    return {
        "candidate_id": CANDIDATE_ID,
        "passed": True,
        "strategy_key": bt["strategy_key"],
        "strategy_hash": bt["strategy_hash"],
        "parameters_hash": bt["parameters_hash"],
        "execution_hash": bt["execution_hash"],
        "execution_model_id": bt["execution_model_id"],
        "execution_model_version": bt["execution_model_version"],
        "portfolio_policy_hash": str(audit["slice_value"]),
        "code_commit": bt.get("code_commit"),
        "roles": [{
            "role": "SYNTHETIC_UI_ONLY",
            "backtest_run_id": BACKTEST_ID,
            "passed": True,
        }],
        "reasons": [],
        "warnings": [WARNING],
        "policy": "SYNTHETIC_UI_FIXTURE_ONLY",
    }


def _seed_pass_gate_context(event_db: Path, execution_identity: dict) -> None:
    _migrate_gate_contexts(event_db)
    provenance = {
        "candidate_id": CANDIDATE_ID,
        "passed": True,
        "roles": [],
        "policy": "SYNTHETIC_UI_FIXTURE_ONLY",
        "warning": WARNING,
    }
    context = {
        "candidate_id": CANDIDATE_ID,
        "production_gate_id": GATE_ID,
        "gate_status": "PASS",
        "provenance": provenance,
        "execution_identity": execution_identity,
    }
    context_hash = content_hash(context)
    with tx(event_db) as c:
        c.execute(
            """INSERT OR IGNORE INTO production_gates(
                 production_gate_id,candidate_id,created_at,status,checklist_json,details_json
               ) VALUES(?,?,?,?,?,?)""",
            (
                GATE_ID,
                CANDIDATE_ID,
                utcnow(),
                "PASS",
                json.dumps([
                    {"name": "SYNTHETIC_UI_FIXTURE_ONLY", "passed": True, "details": WARNING}
                ], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                json.dumps({
                    "synthetic": True,
                    "warning": WARNING,
                    "research_pass": True,
                }, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
        c.execute(
            """INSERT OR IGNORE INTO production_gate_contexts(
                 production_gate_id,candidate_id,created_at,context_hash,provenance_json,execution_identity_json
               ) VALUES(?,?,?,?,?,?)""",
            (
                GATE_ID,
                CANDIDATE_ID,
                utcnow(),
                context_hash,
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                json.dumps(execution_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )


def _snapshot(strategy_key: str, *, as_of_date: str, state: str, recovered: bool) -> dict:
    if recovered:
        ev, pf, dd, slip, freq = 0.18, 1.65, 1.10, 0.20, 2.0
        reasons = []
        drift = {
            "expectancy_ratio": 1.0,
            "profit_factor_ratio": 1.0,
            "drawdown_multiple": 1.0,
            "signal_frequency_ratio": 1.0,
            "slippage_multiple": 1.0,
            "slippage_delta_points": 0.0,
            "regime_tvd": 0.0,
        }
    else:
        ev, pf, dd, slip, freq = -0.40, 0.20, 7.85, 0.90, 1.0
        reasons = ["DRAWDOWN_BREACH"]
        drift = {
            "expectancy_ratio": -2.2,
            "profit_factor_ratio": 0.12,
            "drawdown_multiple": 7.14,
            "signal_frequency_ratio": 0.5,
            "slippage_multiple": 4.5,
            "slippage_delta_points": 0.70,
            "regime_tvd": 0.50,
        }
    return {
        "strategy_key": strategy_key,
        "as_of_date": as_of_date,
        "window_days": 30,
        "trades": 20,
        "expectancy_r": ev,
        "profit_factor": pf,
        "max_drawdown_r": dd,
        "win_rate": 0.50 if recovered else 0.25,
        "avg_slippage_points": slip,
        "signal_frequency": freq,
        "state": state,
        "regime": {"RANGE": 10, "TREND": 10} if recovered else {"HIGH_VOL": 10, "TREND": 10},
        "details": {
            "synthetic": True,
            "warning": WARNING,
            "reasons": reasons,
            "drift": drift,
            "baseline": {
                "net_expectancy_r": 0.18,
                "profit_factor": 1.65,
                "max_drawdown_r": 1.10,
            },
            "baseline_profile": {
                "signal_frequency": 2.0,
                "avg_slippage_points": 0.20,
            },
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event-db", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    event_db = Path(args.event_db)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    identity = _source_identity(event_db)
    _seed_pass_gate_context(event_db, identity)
    try:
        create_deployment_from_gate(
            event_db,
            GATE_ID,
            deployment_id=DEPLOYMENT_ID,
            notes=WARNING,
        )
    except ValueError as exc:
        if "already has an immutable deployment identity" not in str(exc):
            raise

    bad = persist_deployment_monitor_snapshot(
        event_db,
        DEPLOYMENT_ID,
        _snapshot(identity["strategy_key"], as_of_date="2026-05-01", state="SUSPEND", recovered=False),
        source_backtest_run_id=BACKTEST_ID,
        baseline_backtest_run_id=BACKTEST_ID,
    )
    record_deployment_action(
        event_db,
        DEPLOYMENT_ID,
        "ACKNOWLEDGE",
        "synthetic operator acknowledged deployment suspension",
        details={"synthetic": True, "warning": WARNING},
    )
    recovery = persist_deployment_monitor_snapshot(
        event_db,
        DEPLOYMENT_ID,
        _snapshot(identity["strategy_key"], as_of_date="2026-05-02", state="NORMAL", recovered=True),
        source_backtest_run_id=BACKTEST_ID,
        baseline_backtest_run_id=BACKTEST_ID,
    )
    status = deployment_status(event_db, DEPLOYMENT_ID)

    assert bad["state"] == "SUSPEND", bad
    assert recovery["details"]["computed_state"] == "NORMAL", recovery
    assert recovery["state"] == "SUSPEND", recovery
    assert status["control"]["lifecycle_state"] == "SUSPENDED", status
    assert status["production_eligible"] is False, status
    assert status["identity_verification"]["valid"] is True, status

    result = {
        "synthetic": True,
        "warning": WARNING,
        "deployment_id": DEPLOYMENT_ID,
        "source_backtest_run_id": BACKTEST_ID,
        "suspended": bad,
        "latched_recovery": recovery,
        "status": status,
        "assertion": "Exact deployment identity remains ineligible after a computed NORMAL window while lifecycle is SUSPENDED.",
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SYNTHETIC_PRODUCTION_DEPLOYMENT PASS NORMAL->SUSPEND_LATCHED production_eligible=false")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
