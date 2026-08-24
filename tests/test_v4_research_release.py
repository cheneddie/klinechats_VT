from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.engine import connect
from server.v4_research_release import (
    RESEARCH_SCHEMA_VERSION,
    event_sanity_check,
    favorable_capture_ratio,
    finish_research_run,
    migrate_release_schema,
    start_research_run,
    strategy_config_hash,
)


def seed_valid_event(con):
    features = {
        "terminal_signal": True,
        "terminal_entry_seq": 120,
        "terminal_entry_price": 100.0,
        "terminal_stop": 94.0,
        "strict_chain_pass": True,
        "scanner_version": "V4.1",
        "strategy_version": "MR_BROAD_V3",
    }
    nodes = {
        "AUC_ATTEMPT": {"answer": True},
        "MR_REJECTION": {"answer": True},
        "MR_CLEAR_RECLAIM": {"answer": True},
        "MR_RECLAIM_LEG": {"answer": True},
        "MR_LVN": {"answer": True},
        "MR_PULLBACK": {"answer": True},
        "MR_ENTRY": {"answer": True},
    }
    con.execute(
        """INSERT INTO events(
        event_id,source_file,year,trading_date,contract,strategy,direction,result,difficulty,
        attempt_start_seq,attempt_start_time,entry_seq,entry_time,entry_price,stop,target,
        vah,val,poc,value_width,features_json,nodes_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "2025-01-02-202501-A001-MR", "MTX_2025.parquet", 2025, "2025-01-02", "202501",
            "MR", "long", "ENTRY", 2, 100, "2025-01-02T09:00:00", 120,
            "2025-01-02T09:00:20", 100.0, 94.0, 104.5, 110.0, 90.0, 100.0, 20.0,
            json.dumps(features), json.dumps(nodes), "2026-08-21T00:00:00+00:00",
        ),
    )
    rows = [
        ("AUC_ATTEMPT", 1, 101, 101.0, "EXCURSION_PASS"),
        ("MR_REJECTION", 1, 104, 104.0, "REENTERED_VALUE_IN_TIME"),
        ("MR_CLEAR_RECLAIM", 1, 106, 106.0, "CLEAR_RECLAIM_PASS"),
        ("MR_RECLAIM_LEG", 1, 110, 108.0, "TURN_CONFIRMED"),
        ("MR_LVN", 1, 110, 108.0, "LVN_DEPTH_PASS"),
        ("MR_PULLBACK", 1, 120, 100.0, "FIRST_PULLBACK_PASS"),
        ("MR_ENTRY", 1, 120, 100.0, "ENTRY_QUALITY_PASS"),
        # FALSE node proves negative labels can still be causally located.
        ("WAIT_AMBIGUOUS", 0, 120, 100.0, "MR_BRANCH_EVALUATED"),
    ]
    for node_id, answer, seq, price, reason in rows:
        con.execute(
            """INSERT INTO node_instances(
            event_id,node_id,answer,decision_seq,decision_time,difficulty,decision_price,
            anchor_seq,anchor_time,anchor_price,reason_code,metrics_json,node_schema_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "2025-01-02-202501-A001-MR", node_id, answer, seq,
                f"2025-01-02T09:00:{min(seq-100,59):02d}", 2, price,
                min(seq, 110), "2025-01-02T09:00:10", price, reason, "{}", 4,
            ),
        )
    con.commit()


def main():
    assert favorable_capture_ratio(0.75, 4.0) == 0.1875
    assert favorable_capture_ratio(-1.0, 4.0) == 0.0
    assert favorable_capture_ratio(1.0, 0.0) is None
    assert len(strategy_config_hash(ROOT)) == 64

    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "fabio.sqlite3"
        con = connect(db)
        migrate_release_schema(con)
        assert int(con.execute("PRAGMA user_version").fetchone()[0]) >= RESEARCH_SCHEMA_VERSION
        assert con.execute("SELECT 1 FROM schema_meta WHERE key='audit_version'").fetchone()
        assert con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='training_attempts'").fetchone()

        run_id = start_research_run(con, kind="unit", years=[2025], details={"purpose": "software-only"})
        row = con.execute("SELECT * FROM research_runs WHERE run_id=?", (run_id,)).fetchone()
        assert row and row["status"] == "running" and row["config_hash"]
        finish_research_run(con, run_id, status="done", details={"ok": True})
        row = con.execute("SELECT * FROM research_runs WHERE run_id=?", (run_id,)).fetchone()
        assert row["status"] == "done" and row["finished_at"]

        seed_valid_event(con)
        sanity = event_sanity_check(con, years=[2025], require_physical=False)
        assert sanity["ok"], sanity
        assert sanity["funnel"]["terminal_opportunities"] == 1
        assert sanity["funnel"]["strict_entries"] == 1

        # A FALSE node without a causal decision point must fail the formal gate.
        con.execute(
            """INSERT INTO node_instances(event_id,node_id,answer,difficulty,reason_code,node_schema_version)
               VALUES(?,?,?,?,?,?)""",
            ("2025-01-02-202501-A001-MR", "BROKEN_FALSE", 0, 3, "TEST_FAIL", 4),
        )
        con.commit()
        broken = event_sanity_check(con, years=[2025], require_physical=False)
        assert not broken["ok"]
        assert any(x["code"] == "FALSE_NODE_NOT_CAUSALLY_LOCATED" for x in broken["errors"])
        con.close()

    print("V4 research release governance: PASS")


if __name__ == "__main__":
    main()
