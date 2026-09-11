from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.v5.campaigns import (
    create_campaign,
    freeze_campaign,
    pin_run_datasets,
    register_campaign_dataset,
    validate_campaign_governance,
)
from server.v5.registry import NodeDefinition, NodeRegistry
from server.v5.research import reverse_audit
from server.v5.snapshot import MR_CHAIN, snapshot_v4_run
from server.v5.statistics import benjamini_hochberg, trading_day_cluster_bootstrap
from server.v5.storage import (
    connect,
    create_research_run,
    freeze_run,
    migrate_event_db,
    tx,
    verify_run_digest,
)


def registry():
    nodes = {
        "CTX_VALUE": NodeDefinition(
            "CTX_VALUE",
            "SHARED",
            "STATE",
            None,
            {"zh_TW": "CTX_VALUE"},
            ("PASS",),
            ("FAIL",),
            {},
            False,
            False,
        )
    }
    parent = "CTX_VALUE"
    roles = {
        "AUC_ATTEMPT": "STATE",
        "MR_REJECTION": "EDGE_GATE",
        "MR_CLEAR_RECLAIM": "EDGE_GATE",
        "MR_RECLAIM_LEG": "STATE",
        "MR_LVN": "EDGE_GATE",
        "MR_PULLBACK": "EDGE_GATE",
        "MR_ENTRY": "EXECUTION_GATE",
        "BO_DISPLACEMENT": "EDGE_GATE",
        "BO_ACCEPTANCE": "EDGE_GATE",
        "BO_IMPULSE_LEG": "STATE",
        "BO_LVN": "EDGE_GATE",
        "BO_PULLBACK": "EDGE_GATE",
        "BO_RESPONSE": "EDGE_GATE",
        "BO_ENTRY": "EXECUTION_GATE",
    }
    for node_id, role in roles.items():
        if node_id.startswith("BO_") and parent.startswith("MR_"):
            parent = "AUC_ATTEMPT"
        nodes[node_id] = NodeDefinition(
            node_id,
            "BO" if node_id.startswith("BO_") else "MR",
            role,
            parent,
            {"zh_TW": node_id},
            ("PASS",),
            ("FAIL",),
            {},
            True,
            False,
        )
        parent = node_id
    return NodeRegistry(nodes)


def _event_tuple(run_id, eid, day, seq, result="ENTRY"):
    return (
        run_id, eid, "fake.parquet", 2025, day, "202501", "MR", "long", result, 2,
        seq, f"{day}T09:00:00", seq + 10, f"{day}T09:01:00", 100.0, 94.0, 106.0,
        "{}", "{}", "{}",
    )


def _outcome_tuple(run_id, eid, day, seq, rr):
    yes = rr > 0
    return (
        run_id, eid, "terminal", seq + 10, f"{day}T09:01:00", 100.0, 94.0, 1.0, 6.0,
        8.0 if yes else 1.0, 1.0 if yes else 5.0, 1.33 if yes else .16,
        .16 if yes else .83, int(yes), int(yes), int(yes), 0, int(not yes), int(yes),
        rr, .75 if yes else 0, "{}", "now",
    )


def test_bh_fdr_and_cluster_bootstrap_contract():
    q = benjamini_hochberg([0.01, 0.04, 0.03, 0.20, None])
    assert q[4] is None
    assert q[0] <= q[2] <= q[1] <= q[3]
    rows = []
    for day in range(1, 11):
        for i in range(4):
            rows.append({
                "trading_date": f"2025-01-{day:02d}",
                "answer": i < 2,
                "realized_r": 1.0 if i < 2 else -0.5,
            })
    result = trading_day_cluster_bootstrap(rows, reps=500, seed=7)
    assert result["bootstrap_unit"] == "TRADING_DAY"
    assert result["cluster_count"] == 10
    assert result["bootstrap_reps"] == 500
    assert result["delta"] == pytest.approx(1.5)
    assert result["ci_low"] > 0


def test_snapshot_converts_legacy_downstream_nodes_to_not_reached():
    with tempfile.TemporaryDirectory() as td:
        v4 = Path(td) / "v4.sqlite3"
        v5 = Path(td) / "v5.sqlite3"
        c = sqlite3.connect(v4)
        c.executescript(
            """
            CREATE TABLE events(
              event_id TEXT PRIMARY KEY,source_file TEXT,year INTEGER,trading_date TEXT,contract TEXT,
              strategy TEXT,direction TEXT,result TEXT,difficulty INTEGER,attempt_start_seq INTEGER,
              attempt_start_time TEXT,entry_seq INTEGER,entry_time TEXT,entry_price REAL,stop REAL,target REAL,
              features_json TEXT,nodes_json TEXT,created_at TEXT);
            CREATE TABLE node_instances(
              event_id TEXT,node_id TEXT,answer INTEGER,decision_seq INTEGER,decision_time TEXT,
              PRIMARY KEY(event_id,node_id));
            """
        )
        day = "2025-01-02"
        c.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "E1", "fake.parquet", 2025, day, "202501", "MR", "long", "WAIT", 2, 10,
                f"{day}T09:00:00", None, None, None, None, None, "{}", "{}", "now",
            ),
        )
        for i, node_id in enumerate(MR_CHAIN):
            answer = 0 if node_id == "MR_REJECTION" else 1
            c.execute(
                "INSERT INTO node_instances VALUES(?,?,?,?,?)",
                ("E1", node_id, answer, 10 + i, f"{day}T09:00:{i:02d}"),
            )
        c.execute(
            "INSERT INTO node_instances VALUES(?,?,?,?,?)",
            ("E1", "NO_TRADE", 1, 30, f"{day}T09:00:30"),
        )
        c.commit()
        c.close()

        result = snapshot_v4_run(v4, v5, "snap", "DISCOVERY", [2025])
        assert result["nodes"] == len(MR_CHAIN) + 1
        con = connect(v5)
        try:
            rows = {
                r["node_id"]: dict(r)
                for r in con.execute(
                    "SELECT * FROM event_nodes WHERE research_run_id='snap'"
                ).fetchall()
            }
        finally:
            con.close()
        assert rows["MR_REJECTION"]["evaluation_state"] == "EVALUATED"
        assert rows["MR_REJECTION"]["answer"] == 0
        for node_id in MR_CHAIN[2:]:
            assert rows[node_id]["evaluation_state"] == "NOT_REACHED"
            assert rows[node_id]["answer"] is None
            assert rows[node_id]["blocker_node_id"] == "MR_REJECTION"
            assert rows[node_id]["decision_seq"] is None
        assert rows["NO_TRADE"]["evaluation_state"] == "TERMINAL"
        assert rows["NO_TRADE"]["answer"] is None


def test_reverse_audit_uses_evaluated_universe_only():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        create_research_run(db, "r", "DISCOVERY", [2025])
        events = []
        nodes = []
        outcomes = []
        for i in range(60):
            eid = f"E{i:03d}"
            day = f"2025-02-{1 + (i % 20):02d}"
            events.append(_event_tuple("r", eid, day, i * 100))
            evaluated = i < 40
            answer = (i % 2 == 0) if evaluated else None
            state = "EVALUATED" if evaluated else "NOT_REACHED"
            seq = i * 100 + 1 if evaluated else None
            tm = f"{day}T09:00:01" if evaluated else None
            resolution_seq = i * 100 + 1
            resolution_time = f"{day}T09:00:01"
            nodes.append((
                "r", eid, "MR_REJECTION", state, int(answer) if evaluated else None,
                seq, tm, 100.0 if evaluated else None,
                seq, tm, 100.0 if evaluated else None,
                None, None, None, None,
                resolution_seq, resolution_time, 100.0,
                "AUC_ATTEMPT", "AUC_ATTEMPT" if not evaluated else None,
                "BLOCKED" if not evaluated else None, None,
                "PASS" if answer else "FAIL", "{}",
            ))
            outcomes.append(_outcome_tuple("r", eid, day, i * 100, 1.0 if i % 2 == 0 else -0.5))
        with tx(db) as c:
            c.executemany("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", events)
            c.executemany(
                """INSERT INTO event_nodes(
                  research_run_id,event_id,node_id,evaluation_state,answer,
                  decision_seq,decision_time,decision_price,anchor_seq,anchor_time,anchor_price,
                  start_seq,start_time,end_seq,end_time,resolution_seq,resolution_time,resolution_price,
                  parent_node_id,blocker_node_id,blocker_reason_code,counterfactual_answer,reason_code,metrics_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                nodes,
            )
            c.executemany("INSERT INTO opportunity_outcomes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", outcomes)

        result = reverse_audit(db, "r", registry(), bootstrap_reps=300)
        row = next(x for x in result["rows"] if x["strategy"] == "MR" and x["node_id"] == "MR_REJECTION")
        assert row["universe"] == 40
        assert row["yes_n"] == 20
        assert row["no_n"] == 20
        assert row["evaluation_universe"] == "EVALUATED_ONLY"
        assert row["bootstrap_unit"] == "TRADING_DAY"


def test_frozen_run_is_database_immutable_and_digest_verified():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        create_research_run(db, "r", "DISCOVERY", [2025])
        with tx(db) as c:
            c.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                _event_tuple("r", "E1", "2025-01-02", 1),
            )
        digest = freeze_run(db, "r")
        verified = verify_run_digest(db, "r")
        assert verified["valid"] is True
        assert verified["digest"] == digest
        with pytest.raises(sqlite3.IntegrityError, match="frozen research run is immutable"):
            with tx(db) as c:
                c.execute(
                    "UPDATE events SET result='WAIT' WHERE research_run_id='r' AND event_id='E1'"
                )
        with pytest.raises(sqlite3.IntegrityError, match="frozen research run is immutable"):
            with tx(db) as c:
                c.execute("DELETE FROM research_runs WHERE research_run_id='r'")


def test_campaign_governance_supports_custom_year_roles_and_freezes_provenance():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "events.sqlite3"
        create_campaign(db, "c1", "Strategy Campaign")
        sha = "a" * 64
        register_campaign_dataset(db, "c1", "d23", "DISCOVERY", 2023, "MTX_2023.parquet", sha)
        register_campaign_dataset(db, "c1", "d24", "VALIDATION", 2024, "MTX_2024.parquet", "b" * 64)
        register_campaign_dataset(db, "c1", "d25", "FINAL_HOLDOUT", 2025, "MTX_2025.parquet", "c" * 64)
        assert validate_campaign_governance(db, "c1", "DISCOVERY", [2023]) == "DISCOVERY"
        with pytest.raises(ValueError):
            validate_campaign_governance(db, "c1", "DISCOVERY", [2025])
        frozen = freeze_campaign(db, "c1")
        assert frozen["frozen"] == 1
        with pytest.raises((RuntimeError, sqlite3.IntegrityError)):
            register_campaign_dataset(db, "c1", "d26", "FINAL_HOLDOUT", 2026, "MTX_2026.parquet", "d" * 64)

        create_research_run(db, "r-custom", "DISCOVERY", [2023], campaign_id="c1")
        pinned = pin_run_datasets(db, "r-custom", "c1", "DISCOVERY", [2023])
        assert pinned[0]["sha256"] == sha
        con = connect(db)
        try:
            row = con.execute(
                "SELECT * FROM research_run_datasets WHERE research_run_id='r-custom'"
            ).fetchone()
        finally:
            con.close()
        assert row["source_file"] == "MTX_2023.parquet"
        assert row["sha256"] == sha


def test_event_nodes_v5_legacy_schema_migrates_without_null_coercion_regression():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "legacy.sqlite3"
        c = sqlite3.connect(db)
        c.executescript(
            """
            CREATE TABLE event_nodes(
              research_run_id TEXT NOT NULL,event_id TEXT NOT NULL,node_id TEXT NOT NULL,answer INTEGER NOT NULL,
              decision_seq INTEGER,decision_time TEXT,decision_price REAL,anchor_seq INTEGER,anchor_time TEXT,anchor_price REAL,
              start_seq INTEGER,start_time TEXT,end_seq INTEGER,end_time TEXT,reason_code TEXT,metrics_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(research_run_id,event_id,node_id));
            """
        )
        c.execute(
            "INSERT INTO event_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("r", "e", "MR_LVN", 0, 1, "2025-01-01T09:00:00", 100.0, 1,
             "2025-01-01T09:00:00", 100.0, None, None, None, None, "FAIL", "{}"),
        )
        c.commit()
        c.close()
        migrate_event_db(db)
        con = connect(db)
        try:
            info = {r["name"]: dict(r) for r in con.execute("PRAGMA table_info(event_nodes)").fetchall()}
            row = con.execute("SELECT * FROM event_nodes").fetchone()
        finally:
            con.close()
        assert info["answer"]["notnull"] == 0
        assert row["evaluation_state"] == "EVALUATED"
        assert row["answer"] == 0
