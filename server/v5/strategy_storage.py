from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .storage import connect, tx, utcnow
from .strategy_registry import StrategyDefinition, canonical_json

STRATEGY_DB_SCHEMA_VERSION = 2

BACKTEST_DIGEST_TABLES = (
    "backtest_trades",
    "backtest_metrics",
)
OPTIMIZATION_DIGEST_TABLES = (
    "optimization_trials",
    "parameter_plateaus",
)


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def migrate_strategy_db(path: str | Path) -> None:
    with tx(path) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategy_schema_meta(
              key TEXT PRIMARY KEY,value TEXT NOT NULL);

            CREATE TABLE IF NOT EXISTS strategy_definitions(
              strategy_key TEXT PRIMARY KEY,
              strategy_id TEXT NOT NULL,
              version TEXT NOT NULL,
              name TEXT NOT NULL,
              family TEXT NOT NULL,
              schema_version INTEGER NOT NULL,
              definition_hash TEXT NOT NULL,
              definition_json TEXT NOT NULL,
              source_path TEXT,
              created_at TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_strategy_identity
              ON strategy_definitions(strategy_id,version);

            CREATE TABLE IF NOT EXISTS execution_models(
              execution_model_id TEXT NOT NULL,
              version TEXT NOT NULL,
              definition_hash TEXT NOT NULL,
              definition_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              PRIMARY KEY(execution_model_id,version));

            CREATE TABLE IF NOT EXISTS backtest_runs(
              backtest_run_id TEXT PRIMARY KEY,
              research_run_id TEXT NOT NULL,
              campaign_id TEXT,
              strategy_key TEXT NOT NULL,
              strategy_hash TEXT NOT NULL,
              parameters_json TEXT NOT NULL DEFAULT '{}',
              parameters_hash TEXT NOT NULL,
              execution_model_id TEXT NOT NULL,
              execution_model_version TEXT NOT NULL,
              execution_hash TEXT NOT NULL,
              code_commit TEXT,
              data_digest TEXT,
              mode TEXT NOT NULL DEFAULT 'PHYSICAL_TICK',
              status TEXT NOT NULL DEFAULT 'OPEN',
              created_at TEXT NOT NULL,
              completed_at TEXT,
              frozen INTEGER NOT NULL DEFAULT 0,
              frozen_at TEXT,
              frozen_digest TEXT,
              notes TEXT);

            CREATE TABLE IF NOT EXISTS backtest_trades(
              backtest_run_id TEXT NOT NULL,
              trade_id TEXT NOT NULL,
              event_id TEXT NOT NULL,
              trading_date TEXT,
              year INTEGER,
              month TEXT,
              strategy_family TEXT,
              direction TEXT,
              signal_seq INTEGER,
              signal_time TEXT,
              signal_price REAL,
              entry_seq INTEGER,
              entry_time TEXT,
              entry_price REAL,
              stop_price REAL,
              target_price REAL,
              exit_seq INTEGER,
              exit_time TEXT,
              exit_price REAL,
              exit_reason TEXT,
              risk_points REAL,
              mfe_points REAL,
              mae_points REAL,
              mfe_r REAL,
              mae_r REAL,
              gross_points REAL,
              net_points REAL,
              gross_r REAL,
              net_r REAL,
              capture_ratio REAL,
              commission_points REAL,
              slippage_points REAL,
              latency_ms INTEGER,
              holding_seconds REAL,
              causal_valid INTEGER,
              causal_reason TEXT,
              first_failed_node TEXT,
              post_trade_reason TEXT,
              regime_json TEXT NOT NULL DEFAULT '{}',
              payload_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(backtest_run_id,trade_id));
            CREATE INDEX IF NOT EXISTS ix_backtest_trade_event
              ON backtest_trades(backtest_run_id,event_id);
            CREATE INDEX IF NOT EXISTS ix_backtest_trade_date
              ON backtest_trades(backtest_run_id,trading_date);

            CREATE TABLE IF NOT EXISTS backtest_metrics(
              backtest_run_id TEXT NOT NULL,
              metric_key TEXT NOT NULL,
              slice_key TEXT NOT NULL DEFAULT 'ALL',
              slice_value TEXT NOT NULL DEFAULT 'ALL',
              value REAL,
              payload_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(backtest_run_id,metric_key,slice_key,slice_value));

            CREATE TABLE IF NOT EXISTS optimization_runs(
              optimization_run_id TEXT PRIMARY KEY,
              research_run_id TEXT NOT NULL,
              campaign_id TEXT,
              strategy_key TEXT NOT NULL,
              strategy_hash TEXT NOT NULL,
              search_space_json TEXT NOT NULL,
              objective_json TEXT NOT NULL,
              hypotheses_tested INTEGER NOT NULL DEFAULT 0,
              trial_count INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'OPEN',
              created_at TEXT NOT NULL,
              completed_at TEXT,
              frozen INTEGER NOT NULL DEFAULT 0,
              frozen_at TEXT,
              frozen_digest TEXT,
              notes TEXT);

            CREATE TABLE IF NOT EXISTS optimization_trials(
              optimization_run_id TEXT NOT NULL,
              trial_no INTEGER NOT NULL,
              parameters_json TEXT NOT NULL,
              parameters_hash TEXT NOT NULL,
              score REAL,
              expectancy_r REAL,
              profit_factor REAL,
              max_drawdown_r REAL,
              trades INTEGER,
              p_value REAL,
              q_value REAL,
              admissible INTEGER NOT NULL DEFAULT 0,
              rejection_reason TEXT,
              metrics_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(optimization_run_id,trial_no));

            CREATE TABLE IF NOT EXISTS parameter_plateaus(
              optimization_run_id TEXT NOT NULL,
              plateau_id TEXT NOT NULL,
              center_params_json TEXT NOT NULL,
              range_json TEXT NOT NULL,
              score REAL,
              robustness_json TEXT NOT NULL DEFAULT '{}',
              selected INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(optimization_run_id,plateau_id));

            CREATE TABLE IF NOT EXISTS strategy_candidates(
              candidate_id TEXT PRIMARY KEY,
              strategy_key TEXT NOT NULL,
              source_optimization_run_id TEXT,
              parameters_json TEXT NOT NULL,
              parameters_hash TEXT NOT NULL,
              discovery_run_id TEXT,
              validation_run_id TEXT,
              holdout_run_id TEXT,
              status TEXT NOT NULL DEFAULT 'FROZEN_CANDIDATE',
              frozen_at TEXT NOT NULL,
              evidence_json TEXT NOT NULL DEFAULT '{}');

            CREATE TABLE IF NOT EXISTS candidate_evaluations(
              evaluation_id TEXT PRIMARY KEY,
              candidate_id TEXT NOT NULL,
              role TEXT NOT NULL,
              research_run_id TEXT NOT NULL,
              backtest_run_id TEXT NOT NULL,
              parameters_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              result_json TEXT NOT NULL DEFAULT '{}',
              CHECK(role IN ('DISCOVERY','VALIDATION','FINAL_HOLDOUT')));
            CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_role_evaluation
              ON candidate_evaluations(candidate_id,role);

            CREATE TABLE IF NOT EXISTS production_gates(
              production_gate_id TEXT PRIMARY KEY,
              candidate_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              status TEXT NOT NULL,
              checklist_json TEXT NOT NULL,
              details_json TEXT NOT NULL DEFAULT '{}');

            CREATE TABLE IF NOT EXISTS strategy_monitor_snapshots(
              strategy_key TEXT NOT NULL,
              as_of_date TEXT NOT NULL,
              window_days INTEGER NOT NULL,
              trades INTEGER NOT NULL,
              expectancy_r REAL,
              profit_factor REAL,
              max_drawdown_r REAL,
              win_rate REAL,
              avg_slippage_points REAL,
              signal_frequency REAL,
              state TEXT NOT NULL,
              regime_json TEXT NOT NULL DEFAULT '{}',
              details_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(strategy_key,as_of_date,window_days));

            CREATE TABLE IF NOT EXISTS strategy_jobs(
              job_id TEXT PRIMARY KEY,
              job_type TEXT NOT NULL,
              status TEXT NOT NULL,
              progress REAL NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT,
              request_json TEXT NOT NULL DEFAULT '{}',
              result_json TEXT,
              error_text TEXT,
              heartbeat_at TEXT);
            """
        )
        c.execute(
            "INSERT OR REPLACE INTO strategy_schema_meta(key,value) VALUES('strategy_db_schema_version',?)",
            (str(STRATEGY_DB_SCHEMA_VERSION),),
        )
        _install_immutability_triggers(c)


def _install_child_freeze_triggers(
    c: sqlite3.Connection,
    parent_table: str,
    parent_id: str,
    child_tables: tuple[str, ...],
    error_text: str,
) -> None:
    for table in child_tables:
        for action, ref in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("DELETE", "OLD")):
            name = f"protect_frozen_{table}_{action.lower()}"
            c.execute(f"DROP TRIGGER IF EXISTS {name}")
            c.execute(
                f"""
                CREATE TRIGGER {name}
                BEFORE {action} ON {table}
                WHEN EXISTS(
                  SELECT 1 FROM {parent_table}
                  WHERE {parent_id}={ref}.{parent_id} AND frozen=1
                )
                BEGIN SELECT RAISE(ABORT,'{error_text}'); END
                """
            )


def _install_immutability_triggers(c: sqlite3.Connection) -> None:
    _install_child_freeze_triggers(
        c,
        "backtest_runs",
        "backtest_run_id",
        ("backtest_trades", "backtest_metrics"),
        "frozen backtest run is immutable",
    )
    for suffix, ddl in (
        (
            "update",
            """CREATE TRIGGER protect_frozen_backtest_run_update
               BEFORE UPDATE ON backtest_runs WHEN OLD.frozen=1
               BEGIN SELECT RAISE(ABORT,'frozen backtest run is immutable'); END""",
        ),
        (
            "delete",
            """CREATE TRIGGER protect_frozen_backtest_run_delete
               BEFORE DELETE ON backtest_runs WHEN OLD.frozen=1
               BEGIN SELECT RAISE(ABORT,'frozen backtest run is immutable'); END""",
        ),
    ):
        c.execute(f"DROP TRIGGER IF EXISTS protect_frozen_backtest_run_{suffix}")
        c.execute(ddl)

    _install_child_freeze_triggers(
        c,
        "optimization_runs",
        "optimization_run_id",
        ("optimization_trials", "parameter_plateaus"),
        "frozen optimization run is immutable",
    )
    for suffix, ddl in (
        (
            "update",
            """CREATE TRIGGER protect_frozen_optimization_run_update
               BEFORE UPDATE ON optimization_runs WHEN OLD.frozen=1
               BEGIN SELECT RAISE(ABORT,'frozen optimization run is immutable'); END""",
        ),
        (
            "delete",
            """CREATE TRIGGER protect_frozen_optimization_run_delete
               BEFORE DELETE ON optimization_runs WHEN OLD.frozen=1
               BEGIN SELECT RAISE(ABORT,'frozen optimization run is immutable'); END""",
        ),
    ):
        c.execute(f"DROP TRIGGER IF EXISTS protect_frozen_optimization_run_{suffix}")
        c.execute(ddl)

    # Candidate parameters are immutable. Validation/Holdout evidence is append-only
    # in candidate_evaluations instead of mutating the candidate row.
    for action in ("UPDATE", "DELETE"):
        name = f"protect_strategy_candidates_{action.lower()}"
        c.execute(f"DROP TRIGGER IF EXISTS {name}")
        c.execute(
            f"""CREATE TRIGGER {name}
                BEFORE {action} ON strategy_candidates
                BEGIN SELECT RAISE(ABORT,'strategy candidate is immutable'); END"""
        )
    for action in ("UPDATE", "DELETE"):
        name = f"protect_candidate_evaluations_{action.lower()}"
        c.execute(f"DROP TRIGGER IF EXISTS {name}")
        c.execute(
            f"""CREATE TRIGGER {name}
                BEFORE {action} ON candidate_evaluations
                BEGIN SELECT RAISE(ABORT,'candidate evaluation is append-only'); END"""
        )
    for action in ("UPDATE", "DELETE"):
        name = f"protect_production_gates_{action.lower()}"
        c.execute(f"DROP TRIGGER IF EXISTS {name}")
        c.execute(
            f"""CREATE TRIGGER {name}
                BEFORE {action} ON production_gates
                BEGIN SELECT RAISE(ABORT,'production gate record is append-only'); END"""
        )


def register_strategy(path: str | Path, strategy: StrategyDefinition) -> dict[str, Any]:
    migrate_strategy_db(path)
    row = strategy.to_dict()
    with tx(path) as c:
        existing = c.execute(
            "SELECT definition_hash FROM strategy_definitions WHERE strategy_key=?",
            (strategy.strategy_key,),
        ).fetchone()
        if existing and existing["definition_hash"] != strategy.definition_hash:
            raise ValueError(
                f"strategy_key {strategy.strategy_key} already exists with different immutable definition"
            )
        c.execute(
            """INSERT OR IGNORE INTO strategy_definitions(
              strategy_key,strategy_id,version,name,family,schema_version,
              definition_hash,definition_json,source_path,created_at,active
            ) VALUES(?,?,?,?,?,?,?,?,?,?,1)""",
            (
                strategy.strategy_key,
                strategy.strategy_id,
                strategy.version,
                strategy.name,
                strategy.family,
                strategy.schema_version,
                strategy.definition_hash,
                canonical_json(row),
                strategy.source_path,
                utcnow(),
            ),
        )
    return row


def list_registered_strategies(path: str | Path) -> list[dict[str, Any]]:
    migrate_strategy_db(path)
    c = connect(path)
    try:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM strategy_definitions WHERE active=1 ORDER BY family,name,version"
            ).fetchall()
        ]
    finally:
        c.close()


def register_execution_model(
    path: str | Path,
    execution_model_id: str,
    version: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    migrate_strategy_db(path)
    raw = canonical_json(definition)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    with tx(path) as c:
        existing = c.execute(
            "SELECT definition_hash FROM execution_models WHERE execution_model_id=? AND version=?",
            (execution_model_id, version),
        ).fetchone()
        if existing and existing["definition_hash"] != digest:
            raise ValueError("execution model version is immutable")
        c.execute(
            "INSERT OR IGNORE INTO execution_models VALUES(?,?,?,?,?,1)",
            (execution_model_id, version, digest, raw, utcnow()),
        )
    return {
        "execution_model_id": execution_model_id,
        "version": version,
        "definition_hash": digest,
        "definition": definition,
    }


def get_execution_model(
    path: str | Path, execution_model_id: str, version: str
) -> dict[str, Any]:
    migrate_strategy_db(path)
    c = connect(path)
    try:
        row = c.execute(
            "SELECT * FROM execution_models WHERE execution_model_id=? AND version=?",
            (execution_model_id, version),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(f"execution model not found: {execution_model_id}@{version}")
    out = dict(row)
    out["definition"] = json.loads(out["definition_json"])
    return out


def _digest_rows(
    con: sqlite3.Connection, table: str, id_column: str, id_value: str
) -> bytes:
    rows = [
        dict(r)
        for r in con.execute(
            f"SELECT * FROM {table} WHERE {id_column}=? ORDER BY rowid", (id_value,)
        ).fetchall()
    ]
    return canonical_json(rows).encode("utf-8")


def compute_backtest_digest(path: str | Path, backtest_run_id: str) -> str:
    migrate_strategy_db(path)
    c = connect(path)
    try:
        h = hashlib.sha256()
        run = c.execute(
            "SELECT * FROM backtest_runs WHERE backtest_run_id=?", (backtest_run_id,)
        ).fetchone()
        if not run:
            raise KeyError(backtest_run_id)
        run_dict = dict(run)
        for key in ("frozen", "frozen_at", "frozen_digest"):
            run_dict.pop(key, None)
        h.update(canonical_json(run_dict).encode("utf-8"))
        for table in BACKTEST_DIGEST_TABLES:
            h.update(table.encode("utf-8"))
            h.update(_digest_rows(c, table, "backtest_run_id", backtest_run_id))
        return h.hexdigest()
    finally:
        c.close()


def freeze_backtest_run(path: str | Path, backtest_run_id: str) -> str:
    migrate_strategy_db(path)
    c = connect(path)
    try:
        row = c.execute(
            "SELECT frozen,frozen_digest FROM backtest_runs WHERE backtest_run_id=?",
            (backtest_run_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(backtest_run_id)
    if row["frozen"]:
        return row["frozen_digest"]

    completed = utcnow()
    with tx(path) as c:
        c.execute(
            "UPDATE backtest_runs SET status='COMPLETE',completed_at=? WHERE backtest_run_id=? AND frozen=0",
            (completed, backtest_run_id),
        )
    digest = compute_backtest_digest(path, backtest_run_id)
    with tx(path) as c:
        c.execute(
            "UPDATE backtest_runs SET frozen=1,frozen_at=?,frozen_digest=? WHERE backtest_run_id=? AND frozen=0",
            (utcnow(), digest, backtest_run_id),
        )
    return digest


def verify_backtest_digest(path: str | Path, backtest_run_id: str) -> dict[str, Any]:
    migrate_strategy_db(path)
    c = connect(path)
    try:
        row = c.execute(
            "SELECT frozen,frozen_digest FROM backtest_runs WHERE backtest_run_id=?",
            (backtest_run_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(backtest_run_id)
    actual = compute_backtest_digest(path, backtest_run_id)
    return {
        "backtest_run_id": backtest_run_id,
        "frozen": bool(row["frozen"]),
        "stored_digest": row["frozen_digest"],
        "digest": actual,
        "valid": bool(row["frozen"] and row["frozen_digest"] == actual),
    }


def compute_optimization_digest(path: str | Path, optimization_run_id: str) -> str:
    migrate_strategy_db(path)
    c = connect(path)
    try:
        h = hashlib.sha256()
        run = c.execute(
            "SELECT * FROM optimization_runs WHERE optimization_run_id=?",
            (optimization_run_id,),
        ).fetchone()
        if not run:
            raise KeyError(optimization_run_id)
        run_dict = dict(run)
        for key in ("frozen", "frozen_at", "frozen_digest"):
            run_dict.pop(key, None)
        h.update(canonical_json(run_dict).encode("utf-8"))
        for table in OPTIMIZATION_DIGEST_TABLES:
            h.update(table.encode("utf-8"))
            h.update(
                _digest_rows(c, table, "optimization_run_id", optimization_run_id)
            )
        return h.hexdigest()
    finally:
        c.close()


def freeze_optimization_run(path: str | Path, optimization_run_id: str) -> str:
    migrate_strategy_db(path)
    c = connect(path)
    try:
        row = c.execute(
            "SELECT frozen,frozen_digest FROM optimization_runs WHERE optimization_run_id=?",
            (optimization_run_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(optimization_run_id)
    if row["frozen"]:
        return row["frozen_digest"]

    completed = utcnow()
    with tx(path) as c:
        c.execute(
            "UPDATE optimization_runs SET status='COMPLETE',completed_at=? WHERE optimization_run_id=? AND frozen=0",
            (completed, optimization_run_id),
        )
    digest = compute_optimization_digest(path, optimization_run_id)
    with tx(path) as c:
        c.execute(
            "UPDATE optimization_runs SET frozen=1,frozen_at=?,frozen_digest=? WHERE optimization_run_id=? AND frozen=0",
            (utcnow(), digest, optimization_run_id),
        )
    return digest
