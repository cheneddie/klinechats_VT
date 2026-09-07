from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.campaigns import create_campaign, freeze_campaign, pin_run_datasets, register_campaign_dataset
from server.v5.candidate import evaluate_candidate
from server.v5.execution import ExecutionModel
from server.v5.monitor import build_monitor_snapshot
from server.v5.optimizer import freeze_candidate
from server.v5.production_deployment import (
    create_deployment_from_gate,
    deployment_status,
    persist_deployment_monitor_snapshot,
    record_deployment_action,
    verify_backtest_matches_deployment,
    verify_deployment_identity,
)
from server.v5.production_evidence import record_paper_evidence, record_parity_evidence
from server.v5.production_gate import get_production_gate_context, production_gate
from server.v5.storage import create_research_run, freeze_run, tx
from server.v5.strategy_registry import normalize_strategy

CHAIN = [
    "AUC_ATTEMPT", "MR_REJECTION", "MR_CLEAR_RECLAIM", "MR_RECLAIM_LEG",
    "MR_LVN", "MR_PULLBACK", "MR_ENTRY",
]


def strategy():
    return normalize_strategy({
        "name": "DEPLOYMENT_MR_V1",
        "family": "MR",
        "node_chain": CHAIN,
        "stop": {"type": "lvn_buffer", "points": 6},
        "target": {"type": "r_multiple", "r": 1.0},
        "time_stop_seconds": 300,
        "parameter_schema": [
            {"path": "target.r", "kind": "float", "default": 1.0, "scope": "execution", "requires_rescan": False},
        ],
    })


def path_loader(event, start):
    return pd.DataFrame({
        "_seq": [10, 11, 12, 13],
        "dt": pd.to_datetime([
            "2025-01-02T09:00:10", "2025-01-02T09:00:11",
            "2025-01-02T09:00:12", "2025-01-02T09:00:13",
        ]),
        "price": [100.0, 102.0, 104.0, 106.0],
    })


def parity_trace():
    return [{
        "state": "ENTRY", "node_id": "MR_ENTRY", "answer": True,
        "decision_seq": 10, "decision_price": 100.0,
        "entry_seq": 10, "entry_price": 100.0,
    }]


def seed_campaign(db: Path):
    create_campaign(db, "deploy-campaign", "Deployment identity fixture")
    role_years = {"DISCOVERY": 2023, "VALIDATION": 2024, "FINAL_HOLDOUT": 2025}
    for i, (role, year) in enumerate(role_years.items(), start=1):
        register_campaign_dataset(
            db, "deploy-campaign", f"ds-{year}", role, year,
            f"MTX_{year}.parquet", f"{i:x}" * 64,
        )
    freeze_campaign(db, "deploy-campaign")

    for role, year in role_years.items():
        run_id = {"DISCOVERY": "d", "VALIDATION": "v", "FINAL_HOLDOUT": "h"}[role]
        create_research_run(
            db, run_id, role, [year], campaign_id="deploy-campaign",
            scanner_version="V4.1", strategy_version="DEPLOYMENT_MR_V1",
        )
        pin_run_datasets(db, run_id, "deploy-campaign", role, [year])
        day = "2025-01-02"
        with tx(db) as c:
            c.execute(
                """INSERT INTO events(
                  research_run_id,event_id,source_file,year,trading_date,contract,strategy,direction,result,difficulty,
                  attempt_start_seq,attempt_start_time,entry_seq,entry_time,entry_price,stop,target,features_json,nodes_json,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, f"{run_id}-E1", f"MTX_{year}.parquet", year, day, "202501", "MR", "long", "ENTRY", 2,
                    1, f"{day}T09:00:00", 10, f"{day}T09:00:10", 100.0, 94.0, 106.0,
                    "{}", "{}", json.dumps({"lvn": 100.0}),
                ),
            )
            for j, node_id in enumerate(CHAIN):
                c.execute(
                    """INSERT INTO event_nodes(
                      research_run_id,event_id,node_id,evaluation_state,answer,
                      decision_seq,decision_time,decision_price,anchor_seq,anchor_time,anchor_price,
                      resolution_seq,resolution_time,resolution_price,parent_node_id,reason_code,metrics_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id, f"{run_id}-E1", node_id, "EVALUATED", 1,
                        2+j, f"{day}T09:00:{2+j:02d}", 100.0,
                        2+j, f"{day}T09:00:{2+j:02d}", 100.0,
                        2+j, f"{day}T09:00:{2+j:02d}", 100.0,
                        CHAIN[j-1] if j else "CTX_VALUE", "PASS", "{}",
                    ),
                )
        freeze_run(db, run_id)


def evaluate_all(db: Path, td: str, s, *, mismatch_validation=False):
    policy = {
        "min_trades": 1,
        "min_profit_factor": 0,
        "max_drawdown_r": 99,
        "stress_extra_slippage_points": 0.5,
        "stress_latency_ms": 50,
    }
    outputs = {}
    for run_id in ("d", "v", "h"):
        model = ExecutionModel(
            execution_model_id="DEPLOY_BASE",
            version="V1",
            fill_timing="SIGNAL",
            entry_slippage_points=0.25 if not (mismatch_validation and run_id == "v") else 0.75,
            exit_slippage_points=0.25,
            commission_points_per_side=0.10,
            latency_ms=0,
        )
        outputs[run_id] = evaluate_candidate(
            db, td, "cand-deploy", run_id, s,
            execution_model=model,
            policy=policy,
            bootstrap_reps=200,
            path_loader=path_loader,
            code_commit="test-commit-identity",
        )
        assert outputs[run_id]["status"] == "PASS"
    return outputs


def pass_gate(db: Path, s):
    parity = record_parity_evidence(db, "cand-deploy", parity_trace(), parity_trace())
    paper = record_paper_evidence(
        db, "cand-deploy", source="paper-export", artifact_sha256="a" * 64,
        trades=50, expectancy_r=.2, profit_factor=1.3, max_drawdown_r=3,
    )
    return production_gate(
        db, "cand-deploy", s,
        parity_evidence_id=parity["parity_evidence_id"],
        paper_evidence_id=paper["paper_evidence_id"],
    )


def health_trades(pattern, *, start="2026-04-01"):
    out = []
    base = pd.Timestamp(start)
    for i in range(20):
        r = float(pattern[i % len(pattern)])
        day = (base + pd.Timedelta(days=i // 2)).date().isoformat()
        out.append({
            "trade_id": f"H-{i}", "trading_date": day, "month": day[:7],
            "net_r": r, "gross_r": r + .02,
            "net_points": r * 10, "gross_points": (r + .02) * 10,
            "mfe_r": max(r, 0) + .25, "mae_r": abs(min(r, 0)) + .05,
            "mfe_points": (max(r, 0) + .25) * 10,
            "mae_points": (abs(min(r, 0)) + .05) * 10,
            "capture_ratio": .5 if r > 0 else 0,
            "commission_points": .1, "slippage_points": .2,
            "regime": {"market_regime": "RANGE" if i % 2 == 0 else "TREND"},
        })
    return out


def test_production_gate_rejects_dvh_base_execution_identity_mismatch():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        seed_campaign(db)
        s = strategy()
        freeze_candidate(db, s, {}, discovery_run_id="d", candidate_id="cand-deploy")
        evaluate_all(db, td, s, mismatch_validation=True)
        gate = pass_gate(db, s)
        assert gate["status"] == "FAIL"
        assert gate["execution_identity"]["passed"] is False
        assert "BASE_EXECUTION_HASH_MISMATCH" in gate["execution_identity"]["reasons"]
        ctx = get_production_gate_context(db, gate["production_gate_id"])
        assert ctx["context_hash_valid"] is True
        with pytest.raises(RuntimeError, match="PASS production gate"):
            create_deployment_from_gate(db, gate["production_gate_id"])


def test_deployment_pins_exact_identity_and_suspend_blocks_production_until_fresh_normal():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        seed_campaign(db)
        s = strategy()
        freeze_candidate(db, s, {}, discovery_run_id="d", candidate_id="cand-deploy")
        outputs = evaluate_all(db, td, s)
        gate = pass_gate(db, s)
        assert gate["status"] == "PASS"
        assert gate["execution_identity"]["passed"] is True
        ctx = get_production_gate_context(db, gate["production_gate_id"])
        assert ctx["context_hash_valid"] is True

        deployment = create_deployment_from_gate(
            db, gate["production_gate_id"], deployment_id="deploy-1", notes="fixture"
        )
        assert deployment["production_eligible"] is True
        assert verify_deployment_identity(db, "deploy-1")["valid"] is True

        base_bt = outputs["h"]["scenarios"]["BASE"]["backtest_run_id"]
        stress_bt = outputs["h"]["scenarios"]["SLIPPAGE"]["backtest_run_id"]
        assert verify_backtest_matches_deployment(db, "deploy-1", base_bt)["passed"] is True
        mismatch = verify_backtest_matches_deployment(db, "deploy-1", stress_bt)
        assert mismatch["passed"] is False
        assert "EXECUTION_HASH" in mismatch["failed"]

        baseline = health_trades([1.0, -0.5, 0.8, -0.6])
        baseline_summary = __import__("server.v5.reporting", fromlist=["summarize_trades"]).summarize_trades(
            baseline, bootstrap_reps=200
        )["metrics"]
        bad = health_trades([-0.8, -0.7, 0.1, -0.6])
        bad_snapshot = build_monitor_snapshot(
            bad, baseline_summary, strategy_key=s.strategy_key,
            as_of_date="2026-04-10", window_days=30,
            policy={"min_trades": 10, "suspend_dd_multiple": 1.5},
            baseline_trades=baseline,
        )
        assert bad_snapshot["state"] == "SUSPEND"
        persisted_bad = persist_deployment_monitor_snapshot(db, "deploy-1", bad_snapshot)
        assert persisted_bad["state"] == "SUSPEND"
        assert persisted_bad["production_eligible"] is False
        assert deployment_status(db, "deploy-1")["production_eligible"] is False

        with pytest.raises(ValueError, match="computed deployment health state NORMAL"):
            record_deployment_action(db, "deploy-1", "RESUME", "too early")

        recovered = build_monitor_snapshot(
            baseline, baseline_summary, strategy_key=s.strategy_key,
            as_of_date="2026-04-20", window_days=30,
            policy={"min_trades": 10, "suspend_dd_multiple": 1.5},
            baseline_trades=baseline,
        )
        assert recovered["state"] == "NORMAL"
        latched = persist_deployment_monitor_snapshot(db, "deploy-1", recovered)
        assert latched["details"]["computed_state"] == "NORMAL"
        assert latched["state"] == "SUSPEND"
        assert "SUSPEND_LATCHED_BY_DEPLOYMENT_CONTROL" in latched["details"]["reasons"]

        action = record_deployment_action(db, "deploy-1", "RESUME", "reviewed recovery and execution parity")
        assert action["previous_state"] == "SUSPENDED"
        assert action["next_state"] == "ACTIVE"
        # The old latched health row still proves the suspension. A fresh NORMAL
        # snapshot is required before production eligibility becomes true again.
        assert deployment_status(db, "deploy-1")["production_eligible"] is False

        fresh = build_monitor_snapshot(
            baseline, baseline_summary, strategy_key=s.strategy_key,
            as_of_date="2026-04-21", window_days=30,
            policy={"min_trades": 10, "suspend_dd_multiple": 1.5},
            baseline_trades=baseline,
        )
        fresh = persist_deployment_monitor_snapshot(db, "deploy-1", fresh)
        assert fresh["state"] == "NORMAL"
        assert fresh["production_eligible"] is True
        assert deployment_status(db, "deploy-1")["production_eligible"] is True

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            with tx(db) as c:
                c.execute("UPDATE production_deployments SET candidate_id='tampered' WHERE deployment_id='deploy-1'")
