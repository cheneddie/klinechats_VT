from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.campaigns import (
    create_campaign,
    freeze_campaign,
    pin_run_datasets,
    register_campaign_dataset,
)
from server.v5.candidate import evaluate_candidate
from server.v5.optimizer import freeze_candidate
from server.v5.production_evidence import record_paper_evidence, record_parity_evidence
from server.v5.production_gate import production_gate, verify_candidate_provenance
from server.v5.storage import create_research_run, freeze_run, tx
from server.v5.strategy_registry import normalize_strategy

CHAIN = [
    "AUC_ATTEMPT", "MR_REJECTION", "MR_CLEAR_RECLAIM", "MR_RECLAIM_LEG",
    "MR_LVN", "MR_PULLBACK", "MR_ENTRY",
]


def _strategy():
    return normalize_strategy({
        "name": "PROVENANCE_MR_V1",
        "family": "MR",
        "node_chain": CHAIN,
        "stop": {"type": "lvn_buffer", "points": 6},
        "target": {"type": "r_multiple", "r": 1.0},
        "time_stop_seconds": 300,
        "parameter_schema": [
            {"path": "target.r", "kind": "float", "default": 1.0, "scope": "execution", "requires_rescan": False},
        ],
    })


def _path(event, start):
    return pd.DataFrame({
        "_seq": [10, 11, 12, 13],
        "dt": pd.to_datetime([
            "2025-01-02T09:00:10", "2025-01-02T09:00:11",
            "2025-01-02T09:00:12", "2025-01-02T09:00:13",
        ]),
        "price": [100.0, 102.0, 104.0, 106.0],
    })


def _seed_campaign_and_runs(db: Path):
    create_campaign(db, "campaign-1", "Production provenance fixture")
    role_years = {"DISCOVERY": 2023, "VALIDATION": 2024, "FINAL_HOLDOUT": 2025}
    for i, (role, year) in enumerate(role_years.items(), start=1):
        register_campaign_dataset(
            db,
            "campaign-1",
            f"ds-{year}",
            role,
            year,
            f"MTX_{year}.parquet",
            f"{i:x}" * 64,
        )
    freeze_campaign(db, "campaign-1")

    for role, year in role_years.items():
        run_id = {"DISCOVERY": "d", "VALIDATION": "v", "FINAL_HOLDOUT": "h"}[role]
        create_research_run(
            db,
            run_id,
            role,
            [year],
            campaign_id="campaign-1",
            scanner_version="V4.1",
            strategy_version="PROVENANCE_MR_V1",
        )
        pin_run_datasets(db, run_id, "campaign-1", role, [year])
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


def _parity():
    return [{
        "state": "ENTRY", "node_id": "MR_ENTRY", "answer": True,
        "decision_seq": 10, "decision_price": 100.0,
        "entry_seq": 10, "entry_price": 100.0,
    }]


def test_strict_gate_requires_frozen_campaign_and_exact_dataset_pins():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        _seed_campaign_and_runs(db)
        s = _strategy()
        freeze_candidate(db, s, {}, discovery_run_id="d", candidate_id="cand-prov")
        policy = {
            "min_trades": 1,
            "min_profit_factor": 0,
            "max_drawdown_r": 99,
            "stress_extra_slippage_points": 0,
            "stress_latency_ms": 0,
        }
        for run_id in ("d", "v", "h"):
            out = evaluate_candidate(
                db, td, "cand-prov", run_id, s,
                policy=policy, bootstrap_reps=200, path_loader=_path,
            )
            assert out["status"] == "PASS"

        provenance = verify_candidate_provenance(db, "cand-prov")
        assert provenance["passed"] is True
        assert all(x["run_digest_valid"] for x in provenance["roles"])
        assert all(len(x["datasets"]) == 1 for x in provenance["roles"])

        parity = record_parity_evidence(db, "cand-prov", _parity(), _parity())
        paper = record_paper_evidence(
            db, "cand-prov", source="paper-export", artifact_sha256="f" * 64,
            trades=50, expectancy_r=.2, profit_factor=1.3, max_drawdown_r=3,
        )
        gate = production_gate(
            db, "cand-prov", s,
            parity_evidence_id=parity["parity_evidence_id"],
            paper_evidence_id=paper["paper_evidence_id"],
        )
        assert gate["status"] == "PASS"
        assert gate["provenance"]["passed"] is True


def test_strict_gate_blocks_legacy_unprovenanced_candidate_even_with_evidence():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        s = _strategy()
        create_research_run(db, "legacy", "DISCOVERY", [2025])
        freeze_run(db, "legacy")
        freeze_candidate(db, s, {}, discovery_run_id="legacy", candidate_id="cand-legacy")
        # No campaign/dataset pins and no D/V/H evidence: production must fail before
        # any live/paper evidence can make the candidate appear deployable.
        gate = production_gate(db, "cand-legacy", s)
        assert gate["status"] == "FAIL"
        assert "DISCOVERY_PROVENANCE" in gate["details"]["failed_checks"]
