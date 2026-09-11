from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from .parity import compare_traces
from .storage import connect, tx, utcnow
from .strategy_registry import canonical_json
from .strategy_storage import migrate_strategy_db

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_PAPER_POLICY = {
    "min_trades": 30,
    "min_expectancy_r": 0.0,
    "min_profit_factor": 1.0,
    "max_drawdown_r": 12.0,
}


def migrate_production_evidence_db(path: str | Path) -> None:
    migrate_strategy_db(path)
    with tx(path) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS parity_evidence(
              parity_evidence_id TEXT PRIMARY KEY,
              candidate_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              status TEXT NOT NULL,
              historical_trace_sha256 TEXT NOT NULL,
              live_trace_sha256 TEXT NOT NULL,
              historical_rows INTEGER NOT NULL,
              live_rows INTEGER NOT NULL,
              diff_count INTEGER NOT NULL,
              result_json TEXT NOT NULL);

            CREATE TABLE IF NOT EXISTS paper_evidence(
              paper_evidence_id TEXT PRIMARY KEY,
              candidate_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              status TEXT NOT NULL,
              source TEXT NOT NULL,
              artifact_sha256 TEXT NOT NULL,
              start_date TEXT,
              end_date TEXT,
              trades INTEGER NOT NULL,
              expectancy_r REAL,
              profit_factor REAL,
              max_drawdown_r REAL,
              policy_json TEXT NOT NULL,
              metrics_json TEXT NOT NULL,
              notes TEXT);
            """
        )
        for table in ("parity_evidence", "paper_evidence"):
            for action in ("UPDATE", "DELETE"):
                name = f"protect_{table}_{action.lower()}"
                c.execute(f"DROP TRIGGER IF EXISTS {name}")
                c.execute(
                    f"""CREATE TRIGGER {name}
                        BEFORE {action} ON {table}
                        BEGIN SELECT RAISE(ABORT,'production evidence is append-only'); END"""
                )


def _ensure_candidate(path: str | Path, candidate_id: str) -> None:
    migrate_strategy_db(path)
    c = connect(path)
    try:
        row = c.execute(
            "SELECT 1 FROM strategy_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(f"candidate not found: {candidate_id}")


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def record_parity_evidence(
    path: str | Path,
    candidate_id: str,
    historical: list[dict[str, Any]],
    live: list[dict[str, Any]],
    *,
    parity_evidence_id: str | None = None,
) -> dict[str, Any]:
    migrate_production_evidence_db(path)
    _ensure_candidate(path, candidate_id)
    result = compare_traces(historical, live)
    status = "PASS" if result.get("production_gate") == "PASS" else "FAIL"
    evidence_id = parity_evidence_id or ("parity-" + uuid.uuid4().hex[:16])
    h_hash = _hash(historical)
    l_hash = _hash(live)
    with tx(path) as c:
        if c.execute(
            "SELECT 1 FROM parity_evidence WHERE parity_evidence_id=?", (evidence_id,)
        ).fetchone():
            raise ValueError(f"parity evidence already exists: {evidence_id}")
        c.execute(
            "INSERT INTO parity_evidence VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                evidence_id,
                candidate_id,
                utcnow(),
                status,
                h_hash,
                l_hash,
                len(historical),
                len(live),
                int(result.get("diff_count") or 0),
                canonical_json(result),
            ),
        )
    return {
        "parity_evidence_id": evidence_id,
        "candidate_id": candidate_id,
        "status": status,
        "historical_trace_sha256": h_hash,
        "live_trace_sha256": l_hash,
        "result": result,
    }


def get_parity_evidence(path: str | Path, evidence_id: str) -> dict[str, Any]:
    migrate_production_evidence_db(path)
    c = connect(path)
    try:
        row = c.execute(
            "SELECT * FROM parity_evidence WHERE parity_evidence_id=?", (evidence_id,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(evidence_id)
    out = dict(row)
    out["result"] = json.loads(out["result_json"])
    return out


def record_paper_evidence(
    path: str | Path,
    candidate_id: str,
    *,
    source: str,
    artifact_sha256: str,
    trades: int,
    expectancy_r: float | None,
    profit_factor: float | None,
    max_drawdown_r: float | None,
    start_date: str | None = None,
    end_date: str | None = None,
    metrics: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    notes: str | None = None,
    paper_evidence_id: str | None = None,
) -> dict[str, Any]:
    """Record auditable paper-trading evidence and derive PASS/FAIL from policy.

    A caller cannot submit a naked PASS boolean. The record requires a source,
    artifact SHA-256 and numeric paper metrics. The policy result is immutable.
    """
    migrate_production_evidence_db(path)
    _ensure_candidate(path, candidate_id)
    source = str(source or "").strip()
    digest = str(artifact_sha256 or "").lower().strip()
    if not source:
        raise ValueError("paper evidence requires source")
    if not SHA256_RE.fullmatch(digest):
        raise ValueError("paper evidence artifact_sha256 must be 64 lowercase hex characters")
    merged = dict(DEFAULT_PAPER_POLICY)
    merged.update(dict(policy or {}))
    n = int(trades)
    checks = {
        "min_trades": n >= int(merged["min_trades"]),
        "expectancy": expectancy_r is not None and float(expectancy_r) > float(merged["min_expectancy_r"]),
        "profit_factor": profit_factor is not None and float(profit_factor) >= float(merged["min_profit_factor"]),
        "max_drawdown": max_drawdown_r is not None and float(max_drawdown_r) <= float(merged["max_drawdown_r"]),
    }
    status = "PASS" if all(checks.values()) else ("INSUFFICIENT" if not checks["min_trades"] else "FAIL")
    evidence_id = paper_evidence_id or ("paper-" + uuid.uuid4().hex[:16])
    full_metrics = {
        **dict(metrics or {}),
        "trades": n,
        "expectancy_r": expectancy_r,
        "profit_factor": profit_factor,
        "max_drawdown_r": max_drawdown_r,
        "checks": checks,
    }
    with tx(path) as c:
        if c.execute(
            "SELECT 1 FROM paper_evidence WHERE paper_evidence_id=?", (evidence_id,)
        ).fetchone():
            raise ValueError(f"paper evidence already exists: {evidence_id}")
        c.execute(
            "INSERT INTO paper_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                evidence_id,
                candidate_id,
                utcnow(),
                status,
                source,
                digest,
                start_date,
                end_date,
                n,
                expectancy_r,
                profit_factor,
                max_drawdown_r,
                canonical_json(merged),
                canonical_json(full_metrics),
                notes,
            ),
        )
    return {
        "paper_evidence_id": evidence_id,
        "candidate_id": candidate_id,
        "status": status,
        "source": source,
        "artifact_sha256": digest,
        "policy": merged,
        "metrics": full_metrics,
    }


def get_paper_evidence(path: str | Path, evidence_id: str) -> dict[str, Any]:
    migrate_production_evidence_db(path)
    c = connect(path)
    try:
        row = c.execute(
            "SELECT * FROM paper_evidence WHERE paper_evidence_id=?", (evidence_id,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(evidence_id)
    out = dict(row)
    out["policy"] = json.loads(out["policy_json"])
    out["metrics"] = json.loads(out["metrics_json"])
    return out


def list_evidence(path: str | Path, candidate_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    migrate_production_evidence_db(path)
    c = connect(path)
    try:
        if candidate_id:
            parity = [dict(r) for r in c.execute(
                "SELECT * FROM parity_evidence WHERE candidate_id=? ORDER BY created_at DESC", (candidate_id,)
            ).fetchall()]
            paper = [dict(r) for r in c.execute(
                "SELECT * FROM paper_evidence WHERE candidate_id=? ORDER BY created_at DESC", (candidate_id,)
            ).fetchall()]
        else:
            parity = [dict(r) for r in c.execute(
                "SELECT * FROM parity_evidence ORDER BY created_at DESC LIMIT 200"
            ).fetchall()]
            paper = [dict(r) for r in c.execute(
                "SELECT * FROM paper_evidence ORDER BY created_at DESC LIMIT 200"
            ).fetchall()]
    finally:
        c.close()
    return {"parity": parity, "paper": paper}


__all__ = [
    "record_parity_evidence",
    "record_paper_evidence",
    "get_parity_evidence",
    "get_paper_evidence",
    "list_evidence",
    "migrate_production_evidence_db",
]
