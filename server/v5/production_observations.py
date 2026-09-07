from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .production_deployment import get_deployment, verify_deployment_identity
from .storage import connect, tx, utcnow
from .strategy_registry import content_hash
from .strategy_storage import migrate_strategy_db

OBSERVATION_SOURCES = {"PAPER", "LIVE"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _json(value: Any, default=None):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _migrate(event_db: str | Path) -> None:
    migrate_strategy_db(event_db)
    with tx(event_db) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS production_execution_observation_batches(
              batch_id TEXT PRIMARY KEY,
              deployment_id TEXT NOT NULL,
              source_type TEXT NOT NULL,
              producer TEXT NOT NULL,
              artifact_sha256 TEXT,
              created_at TEXT NOT NULL,
              deployment_identity_hash TEXT NOT NULL,
              observation_count INTEGER NOT NULL,
              batch_hash TEXT NOT NULL,
              details_json TEXT NOT NULL DEFAULT '{}',
              CHECK(source_type IN ('PAPER','LIVE')),
              UNIQUE(deployment_id,source_type,batch_hash)
            );
            CREATE INDEX IF NOT EXISTS ix_production_execution_batches_deployment
              ON production_execution_observation_batches(deployment_id,source_type,created_at);

            CREATE TABLE IF NOT EXISTS production_execution_observations(
              observation_id TEXT PRIMARY KEY,
              batch_id TEXT NOT NULL,
              deployment_id TEXT NOT NULL,
              source_type TEXT NOT NULL,
              source_execution_id TEXT NOT NULL,
              source_signal_id TEXT NOT NULL,
              observed_at TEXT NOT NULL,
              trading_date TEXT NOT NULL,
              direction TEXT NOT NULL,
              expected_entry_price REAL NOT NULL,
              entry_price REAL NOT NULL,
              expected_exit_price REAL NOT NULL,
              exit_price REAL NOT NULL,
              risk_points REAL NOT NULL,
              quantity REAL NOT NULL,
              commission_points REAL NOT NULL,
              fees_points REAL NOT NULL,
              gross_points REAL NOT NULL,
              net_points REAL NOT NULL,
              gross_r REAL NOT NULL,
              net_r REAL NOT NULL,
              slippage_points REAL NOT NULL,
              holding_seconds REAL,
              regime_json TEXT NOT NULL DEFAULT '{}',
              payload_json TEXT NOT NULL DEFAULT '{}',
              payload_hash TEXT NOT NULL,
              CHECK(source_type IN ('PAPER','LIVE')),
              CHECK(direction IN ('LONG','SHORT')),
              UNIQUE(deployment_id,source_type,source_execution_id)
            );
            CREATE INDEX IF NOT EXISTS ix_production_execution_observations_window
              ON production_execution_observations(deployment_id,source_type,trading_date,observed_at);

            DROP TRIGGER IF EXISTS protect_production_execution_batches_update;
            CREATE TRIGGER protect_production_execution_batches_update
              BEFORE UPDATE ON production_execution_observation_batches
              BEGIN SELECT RAISE(ABORT,'production execution observation batch is append-only'); END;
            DROP TRIGGER IF EXISTS protect_production_execution_batches_delete;
            CREATE TRIGGER protect_production_execution_batches_delete
              BEFORE DELETE ON production_execution_observation_batches
              BEGIN SELECT RAISE(ABORT,'production execution observation batch is append-only'); END;
            DROP TRIGGER IF EXISTS protect_production_execution_observations_update;
            CREATE TRIGGER protect_production_execution_observations_update
              BEFORE UPDATE ON production_execution_observations
              BEGIN SELECT RAISE(ABORT,'production execution observation is append-only'); END;
            DROP TRIGGER IF EXISTS protect_production_execution_observations_delete;
            CREATE TRIGGER protect_production_execution_observations_delete
              BEFORE DELETE ON production_execution_observations
              BEGIN SELECT RAISE(ABORT,'production execution observation is append-only'); END;
            """
        )


def _finite(value: Any, name: str, *, minimum: float | None = None) -> float:
    try:
        out = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and out < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return out


def _timestamp(value: Any, name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc


def _source_type(value: Any) -> str:
    source = str(value or "").strip().upper()
    if source not in OBSERVATION_SOURCES:
        raise ValueError(f"source_type must be one of {sorted(OBSERVATION_SOURCES)}")
    return source


def _normalize_observation(raw: dict[str, Any]) -> dict[str, Any]:
    source_execution_id = str(raw.get("source_execution_id") or "").strip()
    source_signal_id = str(raw.get("source_signal_id") or "").strip()
    if not source_execution_id:
        raise ValueError("source_execution_id is required")
    if not source_signal_id:
        raise ValueError("source_signal_id is required")

    observed = _timestamp(raw.get("observed_at"), "observed_at")
    entry_time = _timestamp(raw.get("entry_time"), "entry_time")
    exit_time = _timestamp(raw.get("exit_time"), "exit_time")
    if exit_time < entry_time:
        raise ValueError("exit_time must be >= entry_time")

    trading_date = str(raw.get("trading_date") or entry_time.date().isoformat()).strip()
    try:
        datetime.fromisoformat(trading_date[:10])
    except Exception as exc:
        raise ValueError("trading_date must be YYYY-MM-DD") from exc
    trading_date = trading_date[:10]

    direction = str(raw.get("direction") or "").strip().upper()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    sign = 1.0 if direction == "LONG" else -1.0

    expected_entry = _finite(raw.get("expected_entry_price"), "expected_entry_price")
    entry = _finite(raw.get("entry_price"), "entry_price")
    expected_exit = _finite(raw.get("expected_exit_price"), "expected_exit_price")
    exit_price = _finite(raw.get("exit_price"), "exit_price")
    risk = _finite(raw.get("risk_points"), "risk_points", minimum=0.0)
    if risk <= 0:
        raise ValueError("risk_points must be > 0")
    quantity = _finite(raw.get("quantity", 1.0), "quantity", minimum=0.0)
    if quantity <= 0:
        raise ValueError("quantity must be > 0")
    commission = _finite(raw.get("commission_points", 0.0), "commission_points", minimum=0.0)
    fees = _finite(raw.get("fees_points", 0.0), "fees_points", minimum=0.0)

    entry_slippage = (entry - expected_entry) * sign
    exit_slippage = (expected_exit - exit_price) * sign
    slippage = entry_slippage + exit_slippage
    gross_points = (exit_price - entry) * sign
    net_points = gross_points - commission - fees
    gross_r = gross_points / risk
    net_r = net_points / risk
    holding_seconds = max(0.0, (exit_time - entry_time).total_seconds())

    regime = raw.get("regime") or {}
    payload = raw.get("payload") or {}
    if not isinstance(regime, dict):
        raise ValueError("regime must be an object")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    normalized = {
        "source_execution_id": source_execution_id,
        "source_signal_id": source_signal_id,
        "observed_at": observed.isoformat(),
        "trading_date": trading_date,
        "direction": direction,
        "entry_time": entry_time.isoformat(),
        "exit_time": exit_time.isoformat(),
        "expected_entry_price": expected_entry,
        "entry_price": entry,
        "expected_exit_price": expected_exit,
        "exit_price": exit_price,
        "risk_points": risk,
        "quantity": quantity,
        "commission_points": commission,
        "fees_points": fees,
        "gross_points": gross_points,
        "net_points": net_points,
        "gross_r": gross_r,
        "net_r": net_r,
        "slippage_points": slippage,
        "entry_slippage_points": entry_slippage,
        "exit_slippage_points": exit_slippage,
        "holding_seconds": holding_seconds,
        "regime": regime,
        "payload": payload,
    }
    normalized["payload_hash"] = content_hash(normalized)
    return normalized


def record_execution_observation_batch(
    event_db: str | Path,
    deployment_id: str,
    *,
    source_type: str,
    producer: str,
    deployment_identity_hash: str,
    observations: Iterable[dict[str, Any]],
    artifact_sha256: str | None = None,
    details: dict[str, Any] | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    _migrate(event_db)
    deployment = get_deployment(event_db, deployment_id)
    identity_check = verify_deployment_identity(event_db, deployment_id)
    if not identity_check.get("valid"):
        raise RuntimeError("deployment identity verification failed")
    expected_identity = str(deployment.get("identity_hash") or "")
    if str(deployment_identity_hash or "") != expected_identity:
        raise ValueError("observation deployment_identity_hash does not match exact deployment identity")

    source = _source_type(source_type)
    producer = str(producer or "").strip()
    if len(producer) < 2:
        raise ValueError("producer is required")
    artifact = str(artifact_sha256 or "").strip().lower() or None
    if artifact is not None and not _SHA256_RE.fullmatch(artifact):
        raise ValueError("artifact_sha256 must be a lowercase 64-character SHA-256")
    detail_obj = dict(details or {})

    rows = [_normalize_observation(dict(x)) for x in observations]
    if not rows:
        raise ValueError("at least one execution observation is required")
    if len(rows) > 5000:
        raise ValueError("execution observation batch exceeds 5000 rows")
    source_ids = [x["source_execution_id"] for x in rows]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("duplicate source_execution_id inside observation batch")

    canonical_batch = {
        "deployment_id": deployment_id,
        "deployment_identity_hash": expected_identity,
        "source_type": source,
        "producer": producer,
        "artifact_sha256": artifact,
        "observation_payload_hashes": [x["payload_hash"] for x in rows],
        "details": detail_obj,
    }
    batch_hash = content_hash(canonical_batch)
    batch_id = batch_id or ("exec-batch-" + uuid.uuid4().hex[:20])
    created_at = utcnow()

    with tx(event_db) as c:
        existing = c.execute(
            "SELECT batch_id FROM production_execution_observation_batches WHERE deployment_id=? AND source_type=? AND batch_hash=?",
            (deployment_id, source, batch_hash),
        ).fetchone()
        if existing:
            raise ValueError(f"duplicate immutable execution observation batch: {existing['batch_id']}")
        placeholders = ",".join(["?"] * len(source_ids))
        dup_rows = c.execute(
            f"SELECT source_execution_id FROM production_execution_observations WHERE deployment_id=? AND source_type=? AND source_execution_id IN ({placeholders})",
            (deployment_id, source, *source_ids),
        ).fetchall()
        if dup_rows:
            raise ValueError(
                "duplicate source execution observation(s): "
                + ",".join(str(x["source_execution_id"]) for x in dup_rows)
            )

        c.execute(
            """INSERT INTO production_execution_observation_batches(
                 batch_id,deployment_id,source_type,producer,artifact_sha256,created_at,
                 deployment_identity_hash,observation_count,batch_hash,details_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                batch_id,
                deployment_id,
                source,
                producer,
                artifact,
                created_at,
                expected_identity,
                len(rows),
                batch_hash,
                json.dumps(detail_obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
        for item in rows:
            observation_id = "exec-obs-" + uuid.uuid4().hex[:20]
            stored_payload = {
                "entry_time": item["entry_time"],
                "exit_time": item["exit_time"],
                "entry_slippage_points": item["entry_slippage_points"],
                "exit_slippage_points": item["exit_slippage_points"],
                **item["payload"],
            }
            c.execute(
                """INSERT INTO production_execution_observations(
                     observation_id,batch_id,deployment_id,source_type,source_execution_id,source_signal_id,
                     observed_at,trading_date,direction,expected_entry_price,entry_price,expected_exit_price,
                     exit_price,risk_points,quantity,commission_points,fees_points,gross_points,net_points,
                     gross_r,net_r,slippage_points,holding_seconds,regime_json,payload_json,payload_hash
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    observation_id,
                    batch_id,
                    deployment_id,
                    source,
                    item["source_execution_id"],
                    item["source_signal_id"],
                    item["observed_at"],
                    item["trading_date"],
                    item["direction"],
                    item["expected_entry_price"],
                    item["entry_price"],
                    item["expected_exit_price"],
                    item["exit_price"],
                    item["risk_points"],
                    item["quantity"],
                    item["commission_points"],
                    item["fees_points"],
                    item["gross_points"],
                    item["net_points"],
                    item["gross_r"],
                    item["net_r"],
                    item["slippage_points"],
                    item["holding_seconds"],
                    json.dumps(item["regime"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    json.dumps(stored_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    item["payload_hash"],
                ),
            )

    return {
        "batch_id": batch_id,
        "deployment_id": deployment_id,
        "source_type": source,
        "producer": producer,
        "artifact_sha256": artifact,
        "deployment_identity_hash": expected_identity,
        "observation_count": len(rows),
        "batch_hash": batch_hash,
        "created_at": created_at,
    }


def _decode_observation(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["regime"] = _json(out.get("regime_json"), {}) or {}
    out["payload"] = _json(out.get("payload_json"), {}) or {}
    return out


def list_execution_observations(
    event_db: str | Path,
    deployment_id: str,
    *,
    source_type: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    _migrate(event_db)
    params: list[Any] = [deployment_id]
    where = "deployment_id=?"
    if source_type:
        where += " AND source_type=?"
        params.append(_source_type(source_type))
    params.append(min(max(int(limit), 1), 50000))
    c = connect(event_db)
    try:
        rows = [
            _decode_observation(dict(r))
            for r in c.execute(
                f"SELECT * FROM production_execution_observations WHERE {where} ORDER BY trading_date DESC,observed_at DESC,source_execution_id DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        ]
    finally:
        c.close()
    return rows


def list_execution_observation_batches(
    event_db: str | Path,
    deployment_id: str,
    *,
    source_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    _migrate(event_db)
    params: list[Any] = [deployment_id]
    where = "deployment_id=?"
    if source_type:
        where += " AND source_type=?"
        params.append(_source_type(source_type))
    params.append(min(max(int(limit), 1), 5000))
    c = connect(event_db)
    try:
        rows = [dict(r) for r in c.execute(
            f"SELECT * FROM production_execution_observation_batches WHERE {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()]
    finally:
        c.close()
    for row in rows:
        row["details"] = _json(row.get("details_json"), {}) or {}
    return rows


def execution_observations_as_trades(
    event_db: str | Path,
    deployment_id: str,
    *,
    source_type: str,
) -> list[dict[str, Any]]:
    source = _source_type(source_type)
    _migrate(event_db)
    c = connect(event_db)
    try:
        rows = [
            _decode_observation(dict(r))
            for r in c.execute(
                """SELECT * FROM production_execution_observations
                   WHERE deployment_id=? AND source_type=?
                   ORDER BY trading_date,observed_at,source_execution_id""",
                (deployment_id, source),
            ).fetchall()
        ]
    finally:
        c.close()
    trades = []
    for row in rows:
        trades.append({
            "trade_id": row["source_execution_id"],
            "event_id": row["source_signal_id"],
            "trading_date": row["trading_date"],
            "strategy_family": get_deployment(event_db, deployment_id)["strategy_key"].split("@", 1)[0],
            "direction": row["direction"].lower(),
            "entry_price": row["entry_price"],
            "exit_price": row["exit_price"],
            "risk_points": row["risk_points"],
            "quantity": row["quantity"],
            "gross_points": row["gross_points"],
            "net_points": row["net_points"],
            "gross_r": row["gross_r"],
            "net_r": row["net_r"],
            "commission_points": float(row["commission_points"] or 0.0) + float(row["fees_points"] or 0.0),
            "slippage_points": row["slippage_points"],
            "holding_seconds": row["holding_seconds"],
            "regime": row.get("regime") or {},
            "payload": {
                "source_type": source,
                "observation_id": row["observation_id"],
                "batch_id": row["batch_id"],
                "payload_hash": row["payload_hash"],
                **(row.get("payload") or {}),
            },
        })
    return trades


def execution_observation_digest(rows: Iterable[dict[str, Any]]) -> str:
    ordered = sorted(
        (
            {
                "source_type": x.get("source_type"),
                "source_execution_id": x.get("source_execution_id"),
                "payload_hash": x.get("payload_hash"),
            }
            for x in rows
        ),
        key=lambda x: (str(x["source_type"]), str(x["source_execution_id"])),
    )
    return content_hash(ordered)


def execution_observation_summary(event_db: str | Path, deployment_id: str) -> dict[str, Any]:
    _migrate(event_db)
    c = connect(event_db)
    try:
        rows = c.execute(
            """SELECT source_type,COUNT(*) AS n,MIN(trading_date) AS first_date,MAX(trading_date) AS last_date
               FROM production_execution_observations WHERE deployment_id=? GROUP BY source_type""",
            (deployment_id,),
        ).fetchall()
    finally:
        c.close()
    by_source = {
        str(r["source_type"]): {
            "observations": int(r["n"]),
            "first_date": r["first_date"],
            "last_date": r["last_date"],
        }
        for r in rows
    }
    return {"deployment_id": deployment_id, "by_source": by_source}


__all__ = [
    "OBSERVATION_SOURCES",
    "record_execution_observation_batch",
    "list_execution_observations",
    "list_execution_observation_batches",
    "execution_observations_as_trades",
    "execution_observation_digest",
    "execution_observation_summary",
]
