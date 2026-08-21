from __future__ import annotations

from fastapi import HTTPException

from .v4_execution_stress import execution_stress_summary
from .v4_multiyear import (
    compute_strict_outcomes,
    migrate_multiyear_schema,
    multi_year_edge_map,
    production_gate,
    right_tail_summary,
    strict_trade_summary,
)


def _years(text: str | None):
    if not text:
        return None
    try:
        return [int(x.strip()) for x in text.split(",") if x.strip()]
    except ValueError as exc:
        raise HTTPException(400, "years must be comma-separated integers") from exc


def install_multiyear(base):
    app = base.app
    con = base.connect(base.DB)
    try:
        migrate_multiyear_schema(con)
    finally:
        con.close()

    @app.post("/api/v4/research/strict-outcomes/run")
    def strict_outcomes_run(years: str | None = None, max_after_days: int = 1):
        ys = _years(years)
        count = compute_strict_outcomes(
            base.DB,
            base.ROOT,
            ys,
            max(0, min(3, int(max_after_days))),
        )
        return {"ok": True, "computed": count, "years": ys, "basis": "actual strict ENTRY physical _seq"}

    @app.get("/api/v4/research/strict-summary")
    def strict_summary(years: str | None = None):
        con = base.connect(base.DB)
        try:
            return strict_trade_summary(con, _years(years))
        finally:
            con.close()

    @app.get("/api/v4/research/right-tail")
    def right_tail(years: str | None = None):
        con = base.connect(base.DB)
        try:
            return right_tail_summary(con, _years(years))
        finally:
            con.close()

    @app.get("/api/v4/research/multi-year-edge")
    def multiyear_edge(years: str | None = None):
        con = base.connect(base.DB)
        try:
            return multi_year_edge_map(con, _years(years))
        finally:
            con.close()

    @app.get("/api/v4/research/execution-stress")
    def execution_stress(years: str | None = None):
        con = base.connect(base.DB)
        try:
            return execution_stress_summary(con, _years(years))
        finally:
            con.close()

    @app.get("/api/v4/research/production-gate")
    def live_gate(years: str | None = None):
        con = base.connect(base.DB)
        try:
            return production_gate(con, _years(years))
        finally:
            con.close()

    return app


__all__ = ["install_multiyear"]
