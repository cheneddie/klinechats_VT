from __future__ import annotations
import json, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

EVENT_SCHEMA_VERSION=5
TRAINING_SCHEMA_VERSION=5

def utcnow(): return datetime.now(timezone.utc).isoformat()
def connect(path):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(p); con.row_factory=sqlite3.Row; con.execute('PRAGMA foreign_keys=ON'); return con

@contextmanager
def tx(path):
    con=connect(path)
    try:
        yield con; con.commit()
    except Exception:
        con.rollback(); raise
    finally: con.close()

def migrate_event_db(path):
    with tx(path) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS research_runs(
          research_run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, role TEXT NOT NULL,
          years_json TEXT NOT NULL, git_commit TEXT, scanner_version TEXT, strategy_version TEXT,
          config_hash TEXT, contract_policy_version TEXT, visual_schema_version TEXT,
          outcome_version TEXT, audit_version TEXT, management_version TEXT,
          frozen INTEGER NOT NULL DEFAULT 0, parent_run_id TEXT, notes TEXT);
        CREATE TABLE IF NOT EXISTS events(
          research_run_id TEXT NOT NULL,event_id TEXT NOT NULL,source_file TEXT,year INTEGER,trading_date TEXT,
          contract TEXT,strategy TEXT,direction TEXT,result TEXT,difficulty INTEGER,attempt_start_seq INTEGER,
          attempt_start_time TEXT,entry_seq INTEGER,entry_time TEXT,entry_price REAL,stop REAL,target REAL,
          features_json TEXT NOT NULL DEFAULT '{}',nodes_json TEXT NOT NULL DEFAULT '{}',payload_json TEXT NOT NULL DEFAULT '{}',
          PRIMARY KEY(research_run_id,event_id));
        CREATE TABLE IF NOT EXISTS event_nodes(
          research_run_id TEXT NOT NULL,event_id TEXT NOT NULL,node_id TEXT NOT NULL,answer INTEGER NOT NULL,
          decision_seq INTEGER,decision_time TEXT,decision_price REAL,anchor_seq INTEGER,anchor_time TEXT,anchor_price REAL,
          start_seq INTEGER,start_time TEXT,end_seq INTEGER,end_time TEXT,reason_code TEXT,metrics_json TEXT NOT NULL DEFAULT '{}',
          PRIMARY KEY(research_run_id,event_id,node_id));
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
          ci_low REAL,ci_high REAL,same_seq_parent_rate REAL,big_winner_retention REAL,big_loser_rejection REAL,
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
        ''')
        c.execute("INSERT OR REPLACE INTO schema_meta VALUES('event_schema_version',?)",(str(EVENT_SCHEMA_VERSION),))

def migrate_training_db(path):
    with tx(path) as c:
        c.executescript('''
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
        ''')
        c.execute("INSERT OR REPLACE INTO schema_meta VALUES('training_schema_version',?)",(str(TRAINING_SCHEMA_VERSION),))

def create_research_run(path,research_run_id,role,years,**meta):
    migrate_event_db(path)
    with tx(path) as c:
        if c.execute('SELECT 1 FROM research_runs WHERE research_run_id=?',(research_run_id,)).fetchone():
            raise ValueError(f'immutable research_run_id already exists: {research_run_id}')
        c.execute('''INSERT INTO research_runs(research_run_id,created_at,role,years_json,git_commit,scanner_version,strategy_version,config_hash,
        contract_policy_version,visual_schema_version,outcome_version,audit_version,management_version,frozen,parent_run_id,notes)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(research_run_id,utcnow(),role,json.dumps(years),meta.get('git_commit'),meta.get('scanner_version'),meta.get('strategy_version'),
        meta.get('config_hash'),meta.get('contract_policy_version'),meta.get('visual_schema_version'),meta.get('outcome_version'),meta.get('audit_version'),
        meta.get('management_version'),int(bool(meta.get('frozen'))),meta.get('parent_run_id'),meta.get('notes')))

def freeze_run(path,research_run_id):
    with tx(path) as c:
        if not c.execute('SELECT 1 FROM research_runs WHERE research_run_id=?',(research_run_id,)).fetchone(): raise KeyError(research_run_id)
        c.execute('UPDATE research_runs SET frozen=1 WHERE research_run_id=?',(research_run_id,))
