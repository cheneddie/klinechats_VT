from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.monitor import build_monitor_snapshot
from server.v5.production_deployment import (
    create_deployment_from_gate,
    deployment_status,
    persist_deployment_monitor_snapshot,
    record_deployment_action,
)
from server.v5.production_gate import _migrate_gate_contexts
from server.v5.production_observations import (
    execution_observation_digest,
    execution_observation_summary,
    execution_observations_as_trades,
    list_execution_observations,
    record_execution_observation_batch,
)
from server.v5.storage import connect, tx, utcnow
from server.v5.strategy_api import _load_backtest
from server.v5.strategy_registry import content_hash

WARNING = "SYNTHETIC DEPLOYMENT UI FIXTURE - NOT MARKET EDGE OR PRODUCTION EVIDENCE"
CANDIDATE_ID = "cand-synthetic-deployment-ui"
GATE_ID = "pgate-synthetic-deployment-ui"
DEPLOYMENT_ID = "deploy-synthetic-ui-v1"
BACKTEST_ID = "bt-synthetic-mtx-mr-v1"
MONITOR_POLICY = {
    "min_trades": 4,
    "suspend_dd_multiple": 1.5,
    "watch_signal_frequency_ratio_low": 0.0,
    "watch_signal_frequency_ratio_high": 999.0,
    "degraded_signal_frequency_ratio_low": 0.0,
    "degraded_signal_frequency_ratio_high": 999.0,
    "watch_slippage_multiple": 999.0,
    "degraded_slippage_multiple": 999.0,
    "watch_slippage_delta_points": 999.0,
    "degraded_slippage_delta_points": 999.0,
    "watch_regime_tvd": 2.0,
    "degraded_regime_tvd": 2.0,
}


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
            "role": "FINAL_HOLDOUT",
            "backtest_run_id": BACKTEST_ID,
            "passed": True,
            "warning": WARNING,
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


def _observation(i: int, day: str, net_r: float, *, source: str) -> dict:
    minute = i % 50
    risk = 2.0
    entry = 20000.0
    exit_price = entry + net_r * risk
    return {
        "source_execution_id": f"{source}-EXEC-{i:04d}",
        "source_signal_id": f"{source}-SIGNAL-{i:04d}",
        "observed_at": f"{day}T10:{minute:02d}:30+08:00",
        "trading_date": day,
        "direction": "LONG",
        "entry_time": f"{day}T10:{minute:02d}:00+08:00",
        "exit_time": f"{day}T10:{minute:02d}:20+08:00",
        "expected_entry_price": entry,
        "entry_price": entry,
        "expected_exit_price": exit_price,
        "exit_price": exit_price,
        "risk_points": risk,
        "quantity": 1.0,
        "commission_points": 0.0,
        "fees_points": 0.0,
        "regime": {"market_regime": "RANGE" if i % 2 == 0 else "TREND"},
        "payload": {
            "synthetic": True,
            "warning": WARNING,
            "fixture_phase": source,
            "sequence": i,
        },
    }


def _record_fixture_observations(event_db: Path, identity_hash: str) -> dict:
    paper = [_observation(i, f"2026-04-{1 + i // 2:02d}", 0.15 if i % 2 == 0 else -0.05, source="PAPER") for i in range(1, 9)]
    bad = [_observation(100 + i, f"2026-04-{1 + i // 2:02d}", -1.0, source="LIVE-BAD") for i in range(1, 9)]
    recovered_pattern = [0.40, -0.20, 0.40, -0.20]
    recovered = [
        _observation(200 + i, f"2026-05-{1 + i // 4:02d}", recovered_pattern[i % 4], source="LIVE-RECOVERY")
        for i in range(20)
    ]
    # LIVE source_execution_id uniqueness is retained even though fixture_phase differs.
    for row in bad + recovered:
        row["source_execution_id"] = row["source_execution_id"].replace("LIVE-BAD", "LIVE").replace("LIVE-RECOVERY", "LIVE")
        row["source_signal_id"] = row["source_signal_id"].replace("LIVE-BAD", "LIVE").replace("LIVE-RECOVERY", "LIVE")

    paper_batch = record_execution_observation_batch(
        event_db,
        DEPLOYMENT_ID,
        source_type="PAPER",
        producer="synthetic-paper-engine-v1",
        deployment_identity_hash=identity_hash,
        artifact_sha256="c" * 64,
        observations=paper,
        details={"synthetic": True, "warning": WARNING},
        batch_id="exec-batch-synthetic-paper-ui",
    )
    bad_batch = record_execution_observation_batch(
        event_db,
        DEPLOYMENT_ID,
        source_type="LIVE",
        producer="synthetic-broker-adapter-v1",
        deployment_identity_hash=identity_hash,
        observations=bad,
        details={"synthetic": True, "warning": WARNING, "phase": "SUSPEND"},
        batch_id="exec-batch-synthetic-live-bad-ui",
    )
    recovery_batch = record_execution_observation_batch(
        event_db,
        DEPLOYMENT_ID,
        source_type="LIVE",
        producer="synthetic-broker-adapter-v1",
        deployment_identity_hash=identity_hash,
        observations=recovered,
        details={"synthetic": True, "warning": WARNING, "phase": "RECOVERY"},
        batch_id="exec-batch-synthetic-live-recovery-ui",
    )
    return {"paper": paper_batch, "live_bad": bad_batch, "live_recovery": recovery_batch}


def _build_live_health(event_db: Path, *, as_of_date: str, window_days: int) -> dict:
    baseline = _load_backtest(event_db, BACKTEST_ID)
    deployment = deployment_status(event_db, DEPLOYMENT_ID)
    live_trades = execution_observations_as_trades(event_db, DEPLOYMENT_ID, source_type="LIVE")
    snapshot = build_monitor_snapshot(
        live_trades,
        baseline["summary"],
        strategy_key=deployment["strategy_key"],
        as_of_date=as_of_date,
        window_days=window_days,
        policy=MONITOR_POLICY,
        baseline_trades=baseline["trades"],
    )
    rows = list_execution_observations(event_db, DEPLOYMENT_ID, source_type="LIVE", limit=50000)
    active = [x for x in rows if str(x.get("trading_date")) >= str(snapshot["details"]["window_start"]) and str(x.get("trading_date")) <= as_of_date]
    snapshot["details"] = {
        **(snapshot.get("details") or {}),
        "synthetic": True,
        "warning": WARNING,
        "evidence_kind": "EXECUTION_OBSERVATIONS",
        "source_type": "LIVE",
        "authoritative": True,
        "observation_count": len(active),
        "observation_digest": execution_observation_digest(active),
        "baseline_backtest_run_id": BACKTEST_ID,
    }
    return snapshot


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
        deployment = create_deployment_from_gate(
            event_db,
            GATE_ID,
            deployment_id=DEPLOYMENT_ID,
            notes=WARNING,
        )
    except ValueError as exc:
        if "already has an immutable deployment identity" not in str(exc):
            raise
        deployment = deployment_status(event_db, DEPLOYMENT_ID)

    batches = _record_fixture_observations(event_db, deployment["identity_hash"])
    summary = execution_observation_summary(event_db, DEPLOYMENT_ID)
    assert summary["by_source"]["PAPER"]["observations"] == 8, summary
    assert summary["by_source"]["LIVE"]["observations"] == 28, summary

    bad = persist_deployment_monitor_snapshot(
        event_db,
        DEPLOYMENT_ID,
        _build_live_health(event_db, as_of_date="2026-04-05", window_days=5),
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
        _build_live_health(event_db, as_of_date="2026-05-05", window_days=5),
        baseline_backtest_run_id=BACKTEST_ID,
    )
    status = deployment_status(event_db, DEPLOYMENT_ID)

    assert bad["details"]["source_type"] == "LIVE", bad
    assert bad["details"]["authoritative"] is True, bad
    assert bad["state"] == "SUSPEND", bad
    assert recovery["details"]["source_type"] == "LIVE", recovery
    assert recovery["details"]["authoritative"] is True, recovery
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
        "observation_summary": summary,
        "observation_batches": batches,
        "suspended": bad,
        "latched_recovery": recovery,
        "status": status,
        "assertion": "LIVE execution observations drive authoritative deployment health; PAPER is stored separately and the exact deployment remains ineligible after computed NORMAL while lifecycle is SUSPENDED.",
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SYNTHETIC_PRODUCTION_DEPLOYMENT PASS LIVE_OBSERVATIONS NORMAL->SUSPEND_LATCHED production_eligible=false")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
