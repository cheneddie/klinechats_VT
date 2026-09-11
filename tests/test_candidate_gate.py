from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.candidate import evaluate_candidate, production_gate
from server.v5.optimizer import freeze_candidate
from server.v5.production_evidence import record_paper_evidence, record_parity_evidence
from server.v5.storage import create_research_run, freeze_run, tx
from server.v5.strategy_registry import normalize_strategy

MR_CHAIN = [
    "AUC_ATTEMPT", "MR_REJECTION", "MR_CLEAR_RECLAIM", "MR_RECLAIM_LEG",
    "MR_LVN", "MR_PULLBACK", "MR_ENTRY",
]


def strategy():
    return normalize_strategy({
        "name": "CANDIDATE_MR_V1",
        "family": "MR",
        "node_chain": MR_CHAIN,
        "stop": {"type": "lvn_buffer", "points": 6},
        "target": {"type": "r_multiple", "r": 1.0},
        "time_stop_seconds": 300,
        "lvn": {"depth": 0.55},
        "parameter_schema": [
            {"path": "target.r", "kind": "float", "default": 1.0, "scope": "execution", "requires_rescan": False, "minimum": .25, "maximum": 5},
            {"path": "stop.points", "kind": "float", "default": 6.0, "scope": "execution", "requires_rescan": False, "minimum": 1, "maximum": 20},
            {"path": "lvn.depth", "kind": "float", "default": .55, "scope": "detector", "requires_rescan": True, "minimum": 0, "maximum": 1},
        ],
    })


def seed_run(db: Path, run_id: str, role: str):
    create_research_run(db, run_id, role, [2025], scanner_version="V4.1", strategy_version="CANDIDATE_MR_V1")
    day = "2025-01-02"
    with tx(db) as c:
        c.execute(
            """INSERT INTO events(
              research_run_id,event_id,source_file,year,trading_date,contract,strategy,direction,result,difficulty,
              attempt_start_seq,attempt_start_time,entry_seq,entry_time,entry_price,stop,target,features_json,nodes_json,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, f"{run_id}-E1", "fake.parquet", 2025, day, "202501", "MR", "long", "ENTRY", 2,
             1, f"{day}T09:00:00", 10, f"{day}T09:00:10", 100.0, 94.0, 106.0,
             json.dumps({"market_regime": "RANGE"}), "{}", json.dumps({"lvn": 100.0})),
        )
        for i, node_id in enumerate(MR_CHAIN):
            c.execute(
                """INSERT INTO event_nodes(
                  research_run_id,event_id,node_id,evaluation_state,answer,
                  decision_seq,decision_time,decision_price,anchor_seq,anchor_time,anchor_price,
                  resolution_seq,resolution_time,resolution_price,parent_node_id,reason_code,metrics_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, f"{run_id}-E1", node_id, "EVALUATED", 1,
                 2+i, f"{day}T09:00:{2+i:02d}", 100.0,
                 2+i, f"{day}T09:00:{2+i:02d}", 100.0,
                 2+i, f"{day}T09:00:{2+i:02d}", 100.0,
                 MR_CHAIN[i-1] if i else "CTX_VALUE", "PASS", "{}"),
            )
    freeze_run(db, run_id)


def path_loader(event, start):
    return pd.DataFrame({
        "_seq": [10, 11, 12, 13, 14],
        "dt": pd.to_datetime([
            "2025-01-02T09:00:10", "2025-01-02T09:00:11", "2025-01-02T09:00:12",
            "2025-01-02T09:00:13", "2025-01-02T09:00:14",
        ]),
        "price": [100.0, 101.0, 103.0, 106.0, 105.0],
    })


def parity_trace():
    return [{
        "state": "ENTRY",
        "node_id": "MR_ENTRY",
        "answer": True,
        "decision_seq": 10,
        "decision_price": 100.0,
        "entry_seq": 10,
        "entry_price": 100.0,
    }]


def test_candidate_must_follow_discovery_validation_holdout_and_gate_is_append_only():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        for run_id, role in (("d", "DISCOVERY"), ("v", "VALIDATION"), ("h", "FINAL_HOLDOUT")):
            seed_run(db, run_id, role)
        s = strategy()
        cand = freeze_candidate(db, s, {}, discovery_run_id="d", candidate_id="cand-1")
        assert cand["status"] == "FROZEN_CANDIDATE"
        policy = {
            "min_trades": 1,
            "min_profit_factor": 0,
            "max_drawdown_r": 99,
            "stress_extra_slippage_points": 0,
            "stress_latency_ms": 0,
        }

        with pytest.raises(RuntimeError, match="DISCOVERY"):
            evaluate_candidate(db, td, "cand-1", "v", s, policy=policy, path_loader=path_loader, bootstrap_reps=200)

        d = evaluate_candidate(db, td, "cand-1", "d", s, policy=policy, path_loader=path_loader, bootstrap_reps=200)
        assert d["status"] == "PASS"
        v = evaluate_candidate(db, td, "cand-1", "v", s, policy=policy, path_loader=path_loader, bootstrap_reps=200)
        assert v["status"] == "PASS"
        h = evaluate_candidate(db, td, "cand-1", "h", s, policy=policy, path_loader=path_loader, bootstrap_reps=200)
        assert h["status"] == "PASS"
        assert set(h["scenarios"]) == {"BASE", "SLIPPAGE", "LATENCY", "COMBINED"}

        blocked = production_gate(db, "cand-1", s)
        assert blocked["status"] == "BLOCKED_LIVE"

        parity = record_parity_evidence(db, "cand-1", parity_trace(), parity_trace(), parity_evidence_id="parity-1")
        assert parity["status"] == "PASS"
        paper = record_paper_evidence(
            db,
            "cand-1",
            source="paper-simulator-export",
            artifact_sha256="a" * 64,
            trades=40,
            expectancy_r=.25,
            profit_factor=1.4,
            max_drawdown_r=3.0,
            paper_evidence_id="paper-1",
        )
        assert paper["status"] == "PASS"
        passed = production_gate(
            db, "cand-1", s,
            parity_evidence_id=parity["parity_evidence_id"],
            paper_evidence_id=paper["paper_evidence_id"],
        )
        assert passed["status"] == "PASS"

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            with tx(db) as c:
                c.execute("UPDATE production_gates SET status='FAIL' WHERE production_gate_id=?", (passed["production_gate_id"],))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            with tx(db) as c:
                c.execute("UPDATE parity_evidence SET status='FAIL' WHERE parity_evidence_id='parity-1'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            with tx(db) as c:
                c.execute("DELETE FROM paper_evidence WHERE paper_evidence_id='paper-1'")


def test_paper_evidence_cannot_be_naked_pass_and_candidate_mismatch_fails_gate():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        seed_run(db, "d", "DISCOVERY")
        s = strategy()
        freeze_candidate(db, s, {}, discovery_run_id="d", candidate_id="cand-a")
        freeze_candidate(db, s, {}, discovery_run_id="d", candidate_id="cand-b")
        with pytest.raises(ValueError, match="artifact_sha256"):
            record_paper_evidence(
                db, "cand-a", source="paper", artifact_sha256="not-a-sha", trades=100,
                expectancy_r=1, profit_factor=2, max_drawdown_r=1,
            )
        insufficient = record_paper_evidence(
            db, "cand-a", source="paper", artifact_sha256="b" * 64, trades=2,
            expectancy_r=1, profit_factor=2, max_drawdown_r=1,
        )
        assert insufficient["status"] == "INSUFFICIENT"


def test_candidate_rejects_parameter_digest_or_strategy_mismatch():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        seed_run(db, "d", "DISCOVERY")
        s = strategy()
        freeze_candidate(db, s, {"target.r": 1.0}, discovery_run_id="d", candidate_id="cand-2")
        other = normalize_strategy({
            "name": "OTHER_BO_V1", "family": "BO", "node_chain": ["AUC_ATTEMPT", "BO_ENTRY"],
            "stop": {"type": "fixed", "points": 5}, "target": {"type": "r_multiple", "r": 2.0},
            "parameter_schema": [],
        })
        with pytest.raises(ValueError, match="strategy_key"):
            evaluate_candidate(db, td, "cand-2", "d", other, path_loader=path_loader, policy={"min_trades": 1}, bootstrap_reps=200)
