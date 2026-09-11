from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVENT_SCHEMA_VERSION = 6
TRAINING_SCHEMA_VERSION = 5
EVALUATION_STATES = {"EVALUATED", "NOT_REACHED", "NOT_APPLICABLE", "TERMINAL"}
CANONICAL_RUN_TABLES = (
    "events",
    "event_nodes",
    "opportunity_outcomes",
    "node_edge_results",
    "ablation_results",
    "sequential_results",
    "node_evidence_registry",
    "research_run_datasets",
)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def connect(path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def tx(path):
    con = connect(path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _columns(c: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {r["name"]: r for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(c: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    if name not in _columns(c, table):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _migrate_event_nodes_v6(c: sqlite3.Connection) -> None:
    cols = _columns(c, "event_nodes")
    if not cols:
        return
    answer_notnull = bool(cols["answer"]["notnull"]) if "answer" in cols else True
    if "evaluation_state" in cols and not answer_notnull:
        for name, ddl in (
            ("resolution_seq", "INTEGER"),
            ("resolution_time", "TEXT"),
            ("resolution_price", "REAL"),
            ("parent_node_id", "TEXT"),
            ("blocker_node_id", "TEXT"),
            ("blocker_reason_code", "TEXT"),
            ("counterfactual_answer", "INTEGER"),
        ):
            _add_column(c, "event_nodes", name, ddl)
        return

    c.execute("DROP TABLE IF EXISTS event_nodes_v6")
    c.execute(
        """
        CREATE TABLE event_nodes_v6(
          research_run_id TEXT NOT NULL,event_id TEXT NOT NULL,node_id TEXT NOT NULL,
          evaluation_state TEXT NOT NULL DEFAULT 'EVALUATED',
          answer INTEGER,
          decision_seq INTEGER,decision_time TEXT,decision_price REAL,
          anchor_seq INTEGER,anchor_time TEXT,anchor_price REAL,
          start_seq INTEGER,start_time TEXT,end_seq INTEGER,end_time TEXT,
          resolution_seq INTEGER,resolution_time TEXT,resolution_price REAL,
          parent_node_id TEXT,blocker_node_id TEXT,blocker_reason_code TEXT,
          counterfactual_answer INTEGER,reason_code TEXT,metrics_json TEXT NOT NULL DEFAULT '{}',
          PRIMARY KEY(research_run_id,event_id,node_id),
          CHECK(evaluation_state IN ('EVALUATED','NOT_REACHED','NOT_APPLICABLE','TERMINAL')),
          CHECK(
            (evaluation_state='EVALUATED' AND answer IN (0,1))
            OR (evaluation_state<>'EVALUATED' AND answer IS NULL)
          )
        )
        """
    )
    legacy = list(cols)
    wanted = [
        "research_run_id", "event_id", "node_id", "answer",
        "decision_seq", "decision_time", "decision_price",
        "anchor_seq", "anchor_time", "anchor_price",
        "start_seq", "start_time", "end_seq", "end_time",
        "reason_code", "metrics_json",
    ]
    present = [x for x in wanted if x in legacy]
    if present:
        rows = [dict(r) for r in c.execute(f"SELECT {','.join(present)} FROM event_nodes").fetchall()]
        insert_sql = """
        INSERT INTO event_nodes_v6(
          research_run_id,event_id,node_id,evaluation_state,answer,
          decision_seq,decision_time,decision_price,anchor_seq,anchor_time,anchor_price,
          start_seq,start_time,end_seq,end_time,resolution_seq,resolution_time,resolution_price,
          parent_node_id,blocker_node_id,blocker_reason_code,counterfactual_answer,reason_code,metrics_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        payload = []
        for r in rows:
            ans = r.get("answer")
            payload.append((
                r.get("research_run_id"), r.get("event_id"), r.get("node_id"), "EVALUATED",
                None if ans is None else int(bool(ans)),
                r.get("decision_seq"), r.get("decision_time"), r.get("decision_price"),
                r.get("anchor_seq"), r.get("anchor_time"), r.get("anchor_price"),
                r.get("start_seq"), r.get("start_time"), r.get("end_seq"), r.get("end_time"),
                r.get("decision_seq"), r.get("decision_time"), r.get("decision_price"),
                None, None, None, None, r.get("reason_code"), r.get("metrics_json") or "{}",
            ))
        c.executemany(insert_sql, payload)
    c.execute("DROP TABLE event_nodes")
    c.execute("ALTER TABLE event_nodes_v6 RENAME TO event_nodes")


def _install_run_immutability_triggers(c: sqlite3.Connection) -> None:
    c.execute("DROP TRIGGER IF EXISTS protect_frozen_research_runs_update")
    c.execute("DROP TRIGGER IF EXISTS protect_frozen_research_runs_delete")
    c.execute(
        """
        CREATE TRIGGER protect_frozen_research_runs_update
        BEFORE UPDATE ON research_runs
        WHEN OLD.frozen=1
        BEGIN
          SELECT RAISE(ABORT,'frozen research run is immutable');
        END
        """
    )
    c.execute(
        """
        CREATE TRIGGER protect_frozen_research_runs_delete
        BEFORE DELETE ON research_runs
        WHEN OLD.frozen=1
        BEGIN
          SELECT RAISE(ABORT,'frozen research run is immutable');
        END
        """
    )
    for table in CANONICAL_RUN_TABLES:
        for action, ref in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("DELETE", "OLD")):
            name = f"protect_frozen_{table}_{action.lower()}"
            c.execute(f"DROP TRIGGER IF EXISTS {name}")
            c.execute(
                f"""
                CREATE TRIGGER {name}
                BEFORE {action} ON {table}
                WHEN EXISTS(
                  SELECT 1 FROM research_runs
                  WHERE research_run_id={ref}.research_run_id AND frozen=1
                )
                BEGIN
                  SELECT RAISE(ABORT,'frozen research run is immutable');
                END
                """
            )

    for action, ref in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("DELETE", "OLD")):
        name = f"protect_frozen_campaign_datasets_{action.lower()}"
        c.execute(f"DROP TRIGGER IF EXISTS {name}")
        c.execute(
            f"""
            CREATE TRIGGER {name}
            BEFORE {action} ON campaign_datasets
            WHEN EXISTS(
              SELECT 1 FROM research_campaigns
              WHERE campaign_id={ref}.campaign_id AND frozen=1
            )
            BEGIN
              SELECT RAISE(ABORT,'frozen research campaign is immutable');
            END
            """
        )
    c.execute("DROP TRIGGER IF EXISTS protect_frozen_campaign_update")
    c.execute("DROP TRIGGER IF EXISTS protect_frozen_campaign_delete")
    c.execute(
        """
        CREATE TRIGGER protect_frozen_campaign_update
        BEFORE UPDATE ON research_campaigns
        WHEN OLD.frozen=1
        BEGIN
          SELECT RAISE(ABORT,'frozen research campaign is immutable');
        END
        """
    )
    c.execute(
        """
        CREATE TRIGGER protect_frozen_campaign_delete
        BEFORE DELETE ON research_campaigns
        WHEN OLD.frozen=1
        BEGIN
          SELECT RAISE(ABORT,'frozen research campaign is immutable');
        END
        """
    )


def migrate_event_db(path):
    with tx(path) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_campaigns(
              campaign_id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT,created_at TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'OPEN',frozen INTEGER NOT NULL DEFAULT 0,frozen_at TEXT,
              governance_json TEXT NOT NULL DEFAULT '{}',notes TEXT);
            CREATE TABLE IF NOT EXISTS campaign_datasets(
              campaign_id TEXT NOT NULL,dataset_id TEXT NOT NULL,role TEXT NOT NULL,year INTEGER,
              source_file TEXT NOT NULL,sha256 TEXT NOT NULL,start_time TEXT,end_time TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(campaign_id,dataset_id));
            CREATE TABLE IF NOT EXISTS research_runs(
              research_run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, role TEXT NOT NULL,
              years_json TEXT NOT NULL, git_commit TEXT, scanner_version TEXT, strategy_version TEXT,
              config_hash TEXT, contract_policy_version TEXT, visual_schema_version TEXT,
              outcome_version TEXT, audit_version TEXT, management_version TEXT,
              frozen INTEGER NOT NULL DEFAULT 0, parent_run_id TEXT, notes TEXT);
            CREATE TABLE IF NOT EXISTS research_run_datasets(
              research_run_id TEXT NOT NULL,dataset_id TEXT NOT NULL,role TEXT NOT NULL,year INTEGER,
              source_file TEXT NOT NULL,sha256 TEXT NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(research_run_id,dataset_id));
            CREATE TABLE IF NOT EXISTS events(
              research_run_id TEXT NOT NULL,event_id TEXT NOT NULL,source_file TEXT,year INTEGER,trading_date TEXT,
              contract TEXT,strategy TEXT,direction TEXT,result TEXT,difficulty INTEGER,attempt_start_seq INTEGER,
              attempt_start_time TEXT,entry_seq INTEGER,entry_time TEXT,entry_price REAL,stop REAL,target REAL,
              features_json TEXT NOT NULL DEFAULT '{}',nodes_json TEXT NOT NULL DEFAULT '{}',payload_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(research_run_id,event_id));
            CREATE TABLE IF NOT EXISTS event_nodes(
              research_run_id TEXT NOT NULL,event_id TEXT NOT NULL,node_id TEXT NOT NULL,
              evaluation_state TEXT NOT NULL DEFAULT 'EVALUATED',answer INTEGER,
              decision_seq INTEGER,decision_time TEXT,decision_price REAL,
              anchor_seq INTEGER,anchor_time TEXT,anchor_price REAL,
              start_seq INTEGER,start_time TEXT,end_seq INTEGER,end_time TEXT,
              resolution_seq INTEGER,resolution_time TEXT,resolution_price REAL,
              parent_node_id TEXT,blocker_node_id TEXT,blocker_reason_code TEXT,
              counterfactual_answer INTEGER,reason_code TEXT,metrics_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(research_run_id,event_id,node_id),
              CHECK(evaluation_state IN ('EVALUATED','NOT_REACHED','NOT_APPLICABLE','TERMINAL')),
              CHECK(
                (evaluation_state='EVALUATED' AND answer IN (0,1))
                OR (evaluation_state<>'EVALUATED' AND answer IS NULL)
              ));
            CREATE TABLE IF NOT EXISTS event_sanity_runs(
              sanity_run_id TEXT PRIMARY KEY,research_run_id TEXT NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL,
              total_checks INTEGER NOT NULL,failed_checks INTEGER NOT NULL,details_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS event_sanity_items(
              sanity_run_id TEXT NOT NULL,event_id TEXT,node_id TEXT,check_name TEXT NOT NULL,passed INTEGER NOT NULL,message TEXT,details_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS opportunity_outcomes(
              research_run_id TEXT NOT NULL,event_id TEXT NOT NULL,basis TEXT NOT NULL,entry_seq INTEGER,entry_time TEXT,entry_price REAL,
              stop REAL,target_r REAL,risk_points REAL,mfe_points REAL,mae_points REAL,mfe_r REAL,mae_r REAL,
              hit_1r INTEGER,hit_2r INTEGER,hit_3r INTEGER,hit_5r INTEGER,stop_first INTEGER,target_first INTEGER,
              realized_r REAL,capture_ratio REAL,management_json TEXT NOT NULL DEFAULT '{}',computed_at TEXT NOT NULL,
              PRIMARY KEY(research_run_id,event_id,basis));
            CREATE TABLE IF NOT EXISTS node_edge_results(
              research_run_id TEXT NOT NULL,node_id TEXT NOT NULL,strategy TEXT NOT NULL,classification TEXT,
              universe INTEGER,yes_n INTEGER,no_n INTEGER,yes_avg_r REAL,no_avg_r REAL,delta_avg_r REAL,
              ci_low REAL,ci_high REAL,p_value REAL,q_value REAL,bootstrap_unit TEXT,bootstrap_reps INTEGER,cluster_count INTEGER,
              evaluation_universe TEXT,
              same_seq_parent_rate REAL,big_winner_retention REAL,big_loser_rejection REAL,
              rejected_total_r REAL,rejected_positive_r REAL,rejected_negative_r REAL,details_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(research_run_id,node_id,strategy));
            CREATE TABLE IF NOT EXISTS ablation_results(
              research_run_id TEXT NOT NULL,strategy TEXT NOT NULL,variant TEXT NOT NULL,n INTEGER,avg_r REAL,total_r REAL,pf REAL,
              hit_1r_rate REAL,hit_2r_rate REAL,hit_3r_rate REAL,hit_5r_rate REAL,details_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(research_run_id,strategy,variant));
            CREATE TABLE IF NOT EXISTS sequential_results(
              research_run_id TEXT NOT NULL,strategy TEXT NOT NULL,step_no INTEGER NOT NULL,node_id TEXT NOT NULL,n INTEGER,
              avg_r REAL,total_r REAL,delta_n INTEGER,delta_avg_r REAL,delta_total_r REAL,details_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(research_run_id,strategy,step_no));
            CREATE TABLE IF NOT EXISTS node_evidence_registry(
              research_run_id TEXT NOT NULL,node_id TEXT NOT NULL,role TEXT NOT NULL,classification TEXT NOT NULL,evidence_level TEXT NOT NULL,
              discovery_n INTEGER NOT NULL DEFAULT 0,validation_n INTEGER NOT NULL DEFAULT 0,holdout_n INTEGER NOT NULL DEFAULT 0,
              effect_size REAL,ci_low REAL,ci_high REAL,positive_years INTEGER NOT NULL DEFAULT 0,negative_years INTEGER NOT NULL DEFAULT 0,
              right_tail_retention REAL,loser_rejection REAL,known_regime_dependency TEXT,training_eligible INTEGER NOT NULL DEFAULT 0,
              production_eligible INTEGER NOT NULL DEFAULT 0,last_research_run TEXT,PRIMARY KEY(research_run_id,node_id));
            CREATE TABLE IF NOT EXISTS training_cases(
              research_run_id TEXT NOT NULL,event_id TEXT NOT NULL,node_id TEXT NOT NULL,machine_answer INTEGER NOT NULL,machine_reason TEXT,
              semantic_status TEXT NOT NULL,human_review_status TEXT NOT NULL,evidence_level TEXT NOT NULL,case_quality REAL NOT NULL DEFAULT 0,
              difficulty INTEGER NOT NULL DEFAULT 3,training_split TEXT NOT NULL,hard_negative INTEGER NOT NULL DEFAULT 0,error_subtype TEXT,
              feature_json TEXT NOT NULL DEFAULT '{}',PRIMARY KEY(research_run_id,event_id,node_id));
            CREATE TABLE IF NOT EXISTS matched_case_pairs(
              research_run_id TEXT NOT NULL,pair_id TEXT NOT NULL,node_id TEXT NOT NULL,yes_event_id TEXT NOT NULL,no_event_id TEXT NOT NULL,
              similarity_score REAL NOT NULL,differing_features_json TEXT NOT NULL DEFAULT '{}',PRIMARY KEY(research_run_id,pair_id));
            """
        )
        _add_column(c, "research_runs", "campaign_id", "TEXT")
        _add_column(c, "research_runs", "frozen_at", "TEXT")
        _add_column(c, "research_runs", "frozen_digest", "TEXT")
        _migrate_event_nodes_v6(c)
        for name, ddl in (
            ("p_value", "REAL"),
            ("q_value", "REAL"),
            ("bootstrap_unit", "TEXT"),
            ("bootstrap_reps", "INTEGER"),
            ("cluster_count", "INTEGER"),
            ("evaluation_universe", "TEXT"),
        ):
            _add_column(c, "node_edge_results", name, ddl)
        _install_run_immutability_triggers(c)
        c.execute(
            "INSERT OR REPLACE INTO schema_meta VALUES('event_schema_version',?)",
            (str(EVENT_SCHEMA_VERSION),),
        )


def migrate_training_db(path):
    with tx(path) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS training_attempts(
              attempt_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,research_run_id TEXT,event_id TEXT NOT NULL,node_id TEXT NOT NULL,mode TEXT NOT NULL,
              machine_answer INTEGER,human_answer TEXT NOT NULL,correct INTEGER NOT NULL,confidence INTEGER NOT NULL,reaction_ms INTEGER NOT NULL,
              error_type TEXT,first_wrong_node TEXT,started_at TEXT,answered_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS human_labels(
              label_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,research_run_id TEXT,event_id TEXT NOT NULL,node_id TEXT NOT NULL,label TEXT NOT NULL,
              confidence INTEGER,notes TEXT,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS case_reviews(
              review_id TEXT PRIMARY KEY,research_run_id TEXT,event_id TEXT NOT NULL,node_id TEXT NOT NULL,reviewer_id TEXT NOT NULL,
              machine_definition_faithful INTEGER NOT NULL,status TEXT NOT NULL,notes TEXT,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS user_mastery(
              user_id TEXT NOT NULL,node_id TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,correct INTEGER NOT NULL DEFAULT 0,
              hard_negative_attempts INTEGER NOT NULL DEFAULT 0,hard_negative_correct INTEGER NOT NULL DEFAULT 0,false_entries INTEGER NOT NULL DEFAULT 0,
              missed_entries INTEGER NOT NULL DEFAULT 0,total_reaction_ms INTEGER NOT NULL DEFAULT 0,confidence_error REAL NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL,PRIMARY KEY(user_id,node_id));
            CREATE TABLE IF NOT EXISTS mistake_queue(
              mistake_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,research_run_id TEXT,event_id TEXT NOT NULL,node_id TEXT NOT NULL,error_type TEXT,
              priority REAL NOT NULL,due_at TEXT NOT NULL,resolved INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS spaced_repetition(
              user_id TEXT NOT NULL,event_id TEXT NOT NULL,node_id TEXT NOT NULL,last_seen TEXT,times_seen INTEGER NOT NULL DEFAULT 0,
              correct_streak INTEGER NOT NULL DEFAULT 0,incorrect_count INTEGER NOT NULL DEFAULT 0,next_review_at TEXT,PRIMARY KEY(user_id,event_id,node_id));
            CREATE TABLE IF NOT EXISTS certification_attempts(
              certification_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,research_run_id TEXT NOT NULL,node_id TEXT,status TEXT NOT NULL,
              started_at TEXT NOT NULL,finished_at TEXT,settings_json TEXT NOT NULL DEFAULT '{}',result_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS certification_items(
              certification_id TEXT NOT NULL,position INTEGER NOT NULL,event_id TEXT NOT NULL,node_id TEXT NOT NULL,machine_answer INTEGER NOT NULL,
              human_answer TEXT,confidence INTEGER,reaction_ms INTEGER,correct INTEGER,answered_at TEXT,PRIMARY KEY(certification_id,position));
            """
        )
        c.execute(
            "INSERT OR REPLACE INTO schema_meta VALUES('training_schema_version',?)",
            (str(TRAINING_SCHEMA_VERSION),),
        )


def create_research_run(path, research_run_id, role, years, **meta):
    migrate_event_db(path)
    with tx(path) as c:
        if c.execute(
            "SELECT 1 FROM research_runs WHERE research_run_id=?", (research_run_id,)
        ).fetchone():
            raise ValueError(f"immutable research_run_id already exists: {research_run_id}")
        c.execute(
            """
            INSERT INTO research_runs(
              research_run_id,created_at,role,years_json,git_commit,scanner_version,strategy_version,config_hash,
              contract_policy_version,visual_schema_version,outcome_version,audit_version,management_version,
              frozen,parent_run_id,notes,campaign_id,frozen_at,frozen_digest
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                research_run_id, utcnow(), role, json.dumps(years),
                meta.get("git_commit"), meta.get("scanner_version"), meta.get("strategy_version"),
                meta.get("config_hash"), meta.get("contract_policy_version"),
                meta.get("visual_schema_version"), meta.get("outcome_version"),
                meta.get("audit_version"), meta.get("management_version"),
                0, meta.get("parent_run_id"), meta.get("notes"), meta.get("campaign_id"),
                None, None,
            ),
        )


def assert_run_mutable(path, research_run_id):
    migrate_event_db(path)
    c = connect(path)
    try:
        row = c.execute(
            "SELECT frozen FROM research_runs WHERE research_run_id=?", (research_run_id,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(research_run_id)
    if bool(row["frozen"]):
        raise RuntimeError(f"research run is frozen and immutable: {research_run_id}")
    return True


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def research_run_digest(path, research_run_id):
    migrate_event_db(path)
    c = connect(path)
    try:
        rr = c.execute(
            "SELECT * FROM research_runs WHERE research_run_id=?", (research_run_id,)
        ).fetchone()
        if not rr:
            raise KeyError(research_run_id)
        run = dict(rr)
        for key in ("frozen", "frozen_at", "frozen_digest"):
            run.pop(key, None)
        h = hashlib.sha256()
        h.update(_canonical_json({"research_run": run}).encode("utf-8"))
        for table in CANONICAL_RUN_TABLES:
            rows = [
                dict(r)
                for r in c.execute(
                    f"SELECT * FROM {table} WHERE research_run_id=?", (research_run_id,)
                ).fetchall()
            ]
            encoded = sorted(_canonical_json(r) for r in rows)
            h.update(_canonical_json({"table": table, "rows": encoded}).encode("utf-8"))
        return h.hexdigest()
    finally:
        c.close()


def freeze_run(path, research_run_id):
    digest = research_run_digest(path, research_run_id)
    with tx(path) as c:
        row = c.execute(
            "SELECT frozen,frozen_digest FROM research_runs WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()
        if not row:
            raise KeyError(research_run_id)
        if bool(row["frozen"]):
            if row["frozen_digest"] != digest:
                raise RuntimeError("frozen research run digest mismatch")
            return digest
        c.execute(
            "UPDATE research_runs SET frozen=1,frozen_at=?,frozen_digest=? WHERE research_run_id=?",
            (utcnow(), digest, research_run_id),
        )
    return digest


def verify_run_digest(path, research_run_id):
    migrate_event_db(path)
    c = connect(path)
    try:
        row = c.execute(
            "SELECT frozen,frozen_digest FROM research_runs WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(research_run_id)
    if not bool(row["frozen"]) or not row["frozen_digest"]:
        return {"research_run_id": research_run_id, "frozen": False, "valid": False, "digest": None}
    actual = research_run_digest(path, research_run_id)
    return {
        "research_run_id": research_run_id,
        "frozen": True,
        "valid": actual == row["frozen_digest"],
        "digest": row["frozen_digest"],
        "actual_digest": actual,
    }
