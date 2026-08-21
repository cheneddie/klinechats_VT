from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .v4_audit_final import reverse_node_audit
from .v4_research_release import (
    enrich_reverse_audit,
    event_sanity_check,
    management_capture_summary,
    migrate_release_schema,
    provenance_manifest,
    sequential_gate_contribution,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _years(text: str | None):
    if not text:
        return None
    try:
        return [int(x.strip()) for x in text.split(",") if x.strip()]
    except ValueError as exc:
        raise HTTPException(400, "years must be comma-separated integers") from exc


class TrainingAttempt(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    node_id: str = Field(min_length=1, max_length=100)
    human_answer: bool | None = None
    correct: bool | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)
    reaction_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    mode: str | None = Field(default=None, max_length=50)
    difficulty: int | None = Field(default=None, ge=1, le=5)


def install_research_release(base):
    """Install V4 release research-governance endpoints onto the existing app."""
    app = base.app
    con = base.connect(base.DB)
    try:
        migrate_release_schema(con)
    finally:
        con.close()

    @app.get("/api/v4/research/provenance")
    def research_provenance():
        con = base.connect(base.DB)
        try:
            migrate_release_schema(con)
            schema_version = int(con.execute("PRAGMA user_version").fetchone()[0])
            meta = {
                r["key"]: r["value"]
                for r in con.execute("SELECT key,value FROM schema_meta ORDER BY key").fetchall()
            }
            return {**provenance_manifest(), "sqlite_user_version": schema_version, "schema_meta": meta}
        finally:
            con.close()

    @app.post("/api/v4/sanity/run")
    def sanity_run(years: str | None = None, physical: bool = False):
        ys = _years(years)
        con = base.connect(base.DB)
        try:
            result = event_sanity_check(
                con,
                root=base.ROOT if physical else None,
                years=ys,
                require_physical=physical,
            )
            return result
        finally:
            con.close()

    @app.get("/api/v4/sanity/latest")
    def sanity_latest():
        con = base.connect(base.DB)
        try:
            migrate_release_schema(con)
            row = con.execute(
                "SELECT * FROM event_sanity_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return {"run_id": None}
            d = dict(row)
            for src, dst in (("years_json", "years"), ("funnel_json", "funnel"), ("details_json", "details")):
                try:
                    d[dst] = json.loads(d.pop(src) or "{}")
                except Exception:
                    d[dst] = {}
            d["ok"] = bool(d.get("ok"))
            d["physical"] = bool(d.get("physical"))
            return d
        finally:
            con.close()

    @app.post("/api/v4/audit/reverse-release")
    def reverse_release(years: str | None = None):
        ys = _years(years)
        audit = reverse_node_audit(base.DB, ys)
        con = base.connect(base.DB)
        try:
            return enrich_reverse_audit(con, audit, ys)
        finally:
            con.close()

    @app.get("/api/v4/audit/sequential")
    def audit_sequential(years: str | None = None):
        con = base.connect(base.DB)
        try:
            return {"years": _years(years), "items": sequential_gate_contribution(con, _years(years))}
        finally:
            con.close()

    @app.get("/api/v4/management/capture")
    def management_capture(strategy: str | None = None):
        if strategy and strategy not in {"MR", "BO"}:
            raise HTTPException(400, "strategy must be MR or BO")
        con = base.connect(base.DB)
        try:
            return management_capture_summary(con, strategy)
        finally:
            con.close()

    @app.post("/api/v4/training/attempt")
    def training_attempt(item: TrainingAttempt):
        con = base.connect(base.DB)
        try:
            migrate_release_schema(con)
            if not con.execute("SELECT 1 FROM events WHERE event_id=?", (item.event_id,)).fetchone():
                raise HTTPException(404, "event not found")
            if not con.execute(
                "SELECT 1 FROM node_instances WHERE event_id=? AND node_id=?",
                (item.event_id, item.node_id),
            ).fetchone():
                raise HTTPException(404, "node not found in event")
            attempt_id = "attempt-" + uuid.uuid4().hex
            con.execute(
                """INSERT INTO training_attempts(
                attempt_id,event_id,node_id,human_answer,correct,confidence,reaction_ms,mode,difficulty,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    attempt_id,
                    item.event_id,
                    item.node_id,
                    None if item.human_answer is None else int(item.human_answer),
                    None if item.correct is None else int(item.correct),
                    item.confidence,
                    item.reaction_ms,
                    item.mode,
                    item.difficulty,
                    _utcnow(),
                ),
            )
            con.commit()
            return {"ok": True, "attempt_id": attempt_id}
        finally:
            con.close()

    @app.get("/api/v4/training/history")
    def training_history(node_id: str | None = None, limit: int = 200):
        con = base.connect(base.DB)
        try:
            migrate_release_schema(con)
            sql = "SELECT * FROM training_attempts"
            args = []
            if node_id:
                sql += " WHERE node_id=?"
                args.append(node_id)
            sql += " ORDER BY created_at DESC LIMIT ?"
            args.append(max(1, min(5000, int(limit))))
            items = [dict(r) for r in con.execute(sql, args).fetchall()]
            for x in items:
                if x.get("human_answer") is not None:
                    x["human_answer"] = bool(x["human_answer"])
                if x.get("correct") is not None:
                    x["correct"] = bool(x["correct"])
            return {"items": items}
        finally:
            con.close()

    return app


__all__ = ["install_research_release", "TrainingAttempt"]
