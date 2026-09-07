from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_production_deployment import evaluate_all, pass_gate, seed_campaign, strategy

from server.v5.optimizer import freeze_candidate
from server.v5.production_deployment import create_deployment_from_gate
from server.v5.production_deployment_api import install_production_deployment_api
from server.v5.production_observations import (
    execution_observation_summary,
    list_execution_observation_batches,
    list_execution_observations,
    record_execution_observation_batch,
)
from server.v5.storage import tx


def _setup(td: str):
    db = Path(td) / "events.sqlite3"
    seed_campaign(db)
    s = strategy()
    freeze_candidate(db, s, {}, discovery_run_id="d", candidate_id="cand-deploy")
    outputs = evaluate_all(db, td, s)
    gate = pass_gate(db, s)
    assert gate["status"] == "PASS"
    deployment = create_deployment_from_gate(
        db,
        gate["production_gate_id"],
        deployment_id="deploy-observations",
        notes="execution observation fixture",
    )
    return db, s, outputs, deployment


def _observation(i: int, day: str, *, winner: bool = True):
    minute = i % 50
    expected_exit = 102.0 if winner else 98.0
    actual_exit = 101.75 if winner else 97.75
    return {
        "source_execution_id": f"BROKER-EXEC-{i:04d}",
        "source_signal_id": f"LIVE-SIGNAL-{i:04d}",
        "observed_at": f"{day}T10:{minute:02d}:30+08:00",
        "trading_date": day,
        "direction": "LONG",
        "entry_time": f"{day}T10:{minute:02d}:00+08:00",
        "exit_time": f"{day}T10:{minute:02d}:20+08:00",
        "expected_entry_price": 100.0,
        "entry_price": 100.25,
        "expected_exit_price": expected_exit,
        "exit_price": actual_exit,
        "risk_points": 2.0,
        "quantity": 1.0,
        "commission_points": 0.10,
        "fees_points": 0.05,
        "regime": {"market_regime": "RANGE" if i % 2 == 0 else "TREND"},
        "payload": {"broker": "synthetic-broker", "sequence": i},
    }


def test_execution_observation_ledger_requires_exact_deployment_identity_and_is_append_only():
    with tempfile.TemporaryDirectory() as td:
        db, _, _, deployment = _setup(td)
        identity_hash = deployment["identity_hash"]

        batch = record_execution_observation_batch(
            db,
            "deploy-observations",
            source_type="LIVE",
            producer="broker-adapter-v1",
            deployment_identity_hash=identity_hash,
            artifact_sha256="b" * 64,
            details={"account_scope": "SIM-LIVE"},
            observations=[_observation(1, "2026-04-01")],
            batch_id="exec-batch-live-1",
        )
        assert batch["source_type"] == "LIVE"
        assert batch["observation_count"] == 1
        assert batch["deployment_identity_hash"] == identity_hash

        rows = list_execution_observations(db, "deploy-observations", source_type="LIVE")
        assert len(rows) == 1
        row = rows[0]
        assert row["source_execution_id"] == "BROKER-EXEC-0001"
        assert row["gross_points"] == pytest.approx(1.50)
        assert row["net_points"] == pytest.approx(1.35)
        assert row["gross_r"] == pytest.approx(0.75)
        assert row["net_r"] == pytest.approx(0.675)
        assert row["slippage_points"] == pytest.approx(0.50)
        assert row["payload_hash"]

        batches = list_execution_observation_batches(db, "deploy-observations", source_type="LIVE")
        assert len(batches) == 1
        assert batches[0]["batch_hash"] == batch["batch_hash"]
        assert execution_observation_summary(db, "deploy-observations")["by_source"]["LIVE"]["observations"] == 1

        with pytest.raises(ValueError, match="deployment_identity_hash"):
            record_execution_observation_batch(
                db,
                "deploy-observations",
                source_type="LIVE",
                producer="broker-adapter-v1",
                deployment_identity_hash="0" * 64,
                observations=[_observation(2, "2026-04-01")],
            )

        with pytest.raises(ValueError, match="duplicate source execution observation"):
            record_execution_observation_batch(
                db,
                "deploy-observations",
                source_type="LIVE",
                producer="broker-adapter-v1",
                deployment_identity_hash=identity_hash,
                observations=[_observation(1, "2026-04-01")],
            )

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            with tx(db) as c:
                c.execute(
                    "UPDATE production_execution_observations SET net_r=999 WHERE source_execution_id='BROKER-EXEC-0001'"
                )


def test_only_live_observations_persist_authoritative_deployment_health():
    with tempfile.TemporaryDirectory() as td:
        db, _, outputs, deployment = _setup(td)
        identity_hash = deployment["identity_hash"]
        app = FastAPI()
        install_production_deployment_api(app, event_db=db)
        client = TestClient(app)

        paper_payload = {
            "source_type": "PAPER",
            "producer": "paper-engine-v2",
            "deployment_identity_hash": identity_hash,
            "artifact_sha256": "c" * 64,
            "observations": [_observation(i, f"2026-04-{1 + i // 2:02d}") for i in range(1, 9)],
        }
        r = client.post(
            "/api/v5/strategy-lab/deployments/deploy-observations/execution-observations",
            json=paper_payload,
        )
        assert r.status_code == 200, r.text
        assert r.json()["summary"]["by_source"]["PAPER"]["observations"] == 8

        r = client.post(
            "/api/v5/strategy-lab/deployments/deploy-observations/monitor-health-observations",
            json={"source_type": "PAPER", "as_of_date": "2026-04-10", "window_days": 30, "policy": {"min_trades": 1}},
        )
        assert r.status_code == 200, r.text
        paper_health = r.json()
        assert paper_health["authoritative"] is False
        assert paper_health["snapshot"]["details"]["evidence_kind"] == "EXECUTION_OBSERVATIONS"
        assert paper_health["snapshot"]["details"]["source_type"] == "PAPER"
        assert paper_health["snapshot"]["details"]["authoritative"] is False

        r = client.get("/api/v5/strategy-lab/deployments/deploy-observations/monitor-health")
        assert r.status_code == 200
        assert r.json()["items"] == []

        live_payload = {
            "source_type": "LIVE",
            "producer": "broker-adapter-v1",
            "deployment_identity_hash": identity_hash,
            "observations": [_observation(100 + i, f"2026-04-{1 + i // 2:02d}") for i in range(1, 9)],
        }
        r = client.post(
            "/api/v5/strategy-lab/deployments/deploy-observations/execution-observations",
            json=live_payload,
        )
        assert r.status_code == 200, r.text
        assert r.json()["summary"]["by_source"]["LIVE"]["observations"] == 8

        r = client.post(
            "/api/v5/strategy-lab/deployments/deploy-observations/monitor-health-observations",
            json={"source_type": "LIVE", "as_of_date": "2026-04-10", "window_days": 30, "policy": {"min_trades": 1}},
        )
        assert r.status_code == 200, r.text
        live_health = r.json()
        assert live_health["authoritative"] is True
        assert live_health["snapshot"]["details"]["evidence_kind"] == "EXECUTION_OBSERVATIONS"
        assert live_health["snapshot"]["details"]["source_type"] == "LIVE"
        assert live_health["snapshot"]["details"]["authoritative"] is True
        assert live_health["snapshot"]["details"]["observation_count"] == 8
        assert len(live_health["snapshot"]["details"]["observation_digest"]) == 64
        assert live_health["baseline_backtest_run_id"] == outputs["h"]["scenarios"]["BASE"]["backtest_run_id"]
        assert live_health["baseline_identity_check"]["passed"] is True

        r = client.get("/api/v5/strategy-lab/deployments/deploy-observations/monitor-health")
        assert r.status_code == 200
        persisted = r.json()["items"]
        assert len(persisted) == 1
        assert persisted[0]["details"]["source_type"] == "LIVE"
        assert persisted[0]["details"]["authoritative"] is True

        baseline_id = outputs["h"]["scenarios"]["BASE"]["backtest_run_id"]
        r = client.post(
            "/api/v5/strategy-lab/deployments/deploy-observations/monitor-health",
            json={
                "backtest_run_id": baseline_id,
                "baseline_backtest_run_id": baseline_id,
                "as_of_date": "2025-01-02",
                "window_days": 30,
                "policy": {"min_trades": 1},
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["authoritative"] is False
        assert r.json()["snapshot"]["details"]["evidence_kind"] == "BACKTEST_PREVIEW"

        r = client.get("/api/v5/strategy-lab/deployments/deploy-observations/monitor-health")
        assert len(r.json()["items"]) == 1
