from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from .storage import connect, tx, utcnow
from .strategy_registry import content_hash
from .strategy_storage import migrate_strategy_db

ROLES = ("DISCOVERY", "VALIDATION", "FINAL_HOLDOUT")
DEFAULT_PRODUCTION_VALUE_POLICY: dict[str, Any] = {
    # User-defined trading-value floor: average realized NET points must be at
    # least 10% of the ATR that was already known at the event/entry time.
    "min_avg_net_points_over_atr": 0.10,
    # Deliberately unset. These concentration limits are research-governance
    # decisions and must be explicitly frozen in the Production Gate policy.
    "max_positive_month_profit_share": None,
    "max_positive_year_profit_share": None,
}


def _json(value: Any, default=None):
    if value is None:
        return default
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return default


def _finite_positive(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) and out > 0 else None


def event_time_atr(event_payload_json: Any, event_features_json: Any = None) -> tuple[float | None, str | None]:
    """Read ATR only from the immutable event snapshot.

    No price-series fallback is allowed here. Recomputing ATR at gate time would
    silently create a second indicator implementation and could introduce lookahead.
    V5 snapshot stores the complete source event in events.payload_json, so a source
    event-level ``atr`` survives the V4 -> V5 freeze unchanged.
    """
    payload = _json(event_payload_json, {}) or {}
    features = _json(event_features_json, {}) or {}

    candidates: list[tuple[str, Any]] = [
        ("event_payload.atr", payload.get("atr")),
        ("event_payload.event_atr", payload.get("event_atr")),
        ("event_payload.atr_event_time", payload.get("atr_event_time")),
        ("event_features.atr", features.get("atr")),
    ]

    # Snapshot payload is the original event row. If the original event kept ATR
    # inside its serialized feature set, preserve that provenance too.
    nested_features = _json(payload.get("features_json"), {}) or {}
    candidates.append(("event_payload.features_json.atr", nested_features.get("atr")))

    for source, raw in candidates:
        atr = _finite_positive(raw)
        if atr is not None:
            return atr, source
    return None, None


def _candidate_base_rows(event_db: str | Path, candidate_id: str) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    migrate_strategy_db(event_db)
    c = connect(event_db)
    try:
        evaluations = {
            str(r["role"]): dict(r)
            for r in c.execute(
                "SELECT * FROM candidate_evaluations WHERE candidate_id=?",
                (candidate_id,),
            ).fetchall()
        }
        by_role: dict[str, list[dict[str, Any]]] = {}
        combined: list[dict[str, Any]] = []
        for role in ROLES:
            evaluation = evaluations.get(role)
            if not evaluation:
                by_role[role] = []
                continue
            research_run_id = str(evaluation["research_run_id"])
            backtest_run_id = str(evaluation["backtest_run_id"])
            rows = [
                dict(r)
                for r in c.execute(
                    """SELECT
                         bt.trade_id,bt.event_id,bt.trading_date,bt.year,bt.month,
                         bt.net_points,bt.net_r,
                         e.payload_json AS event_payload_json,
                         e.features_json AS event_features_json
                       FROM backtest_trades bt
                       JOIN events e
                         ON e.research_run_id=? AND e.event_id=bt.event_id
                       WHERE bt.backtest_run_id=?
                       ORDER BY bt.trading_date,bt.signal_seq,bt.trade_id""",
                    (research_run_id, backtest_run_id),
                ).fetchall()
            ]
            for row in rows:
                row["role"] = role
                row["research_run_id"] = research_run_id
                row["backtest_run_id"] = backtest_run_id
                atr, source = event_time_atr(
                    row.get("event_payload_json"), row.get("event_features_json")
                )
                row["event_time_atr"] = atr
                row["event_time_atr_source"] = source
                if atr is not None and row.get("net_points") is not None:
                    row["net_points_over_atr"] = float(row["net_points"]) / atr
                else:
                    row["net_points_over_atr"] = None
            by_role[role] = rows
            combined.extend(rows)
    finally:
        c.close()
    return by_role, combined


def _role_value_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    valid = [x for x in rows if x.get("net_points_over_atr") is not None]
    ratios = [float(x["net_points_over_atr"]) for x in valid]
    winner_ratios = [
        float(x["net_points_over_atr"])
        for x in valid
        if float(x.get("net_points") or 0.0) > 0
    ]
    return {
        "trades": n,
        "atr_valid_trades": len(valid),
        "atr_coverage_rate": (len(valid) / n) if n else 0.0,
        "avg_net_points_over_atr": mean(ratios) if ratios else None,
        "avg_winner_net_points_over_atr": mean(winner_ratios) if winner_ratios else None,
        "net_points": sum(float(x.get("net_points") or 0.0) for x in rows),
        "net_r": sum(float(x.get("net_r") or 0.0) for x in rows),
        "atr_sources": sorted({str(x.get("event_time_atr_source")) for x in valid}),
    }


def _positive_profit_concentration(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        if key == "year":
            value = row.get("year")
            if value is None:
                value = str(row.get("trading_date") or "")[:4] or None
        elif key == "month":
            value = row.get("month") or (str(row.get("trading_date") or "")[:7] or None)
        else:
            value = row.get(key)
        if value is None:
            continue
        totals[str(value)] += float(row.get("net_r") or 0.0)

    positive = {k: v for k, v in totals.items() if v > 0.0}
    positive_total = sum(positive.values())
    if positive:
        largest_group, largest_value = max(positive.items(), key=lambda item: item[1])
        largest_share = largest_value / positive_total if positive_total > 0 else None
    else:
        largest_group = None
        largest_value = None
        largest_share = None
    return {
        "groups": dict(sorted(totals.items())),
        "group_count": len(totals),
        "profitable_group_count": len(positive),
        "net_total_r": sum(totals.values()),
        "positive_total_r": positive_total,
        "largest_positive_group": largest_group,
        "largest_positive_group_r": largest_value,
        "largest_positive_profit_share": largest_share,
    }


def _valid_share_limit(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) and 0.0 < out <= 1.0 else None


def audit_candidate_production_value(
    event_db: str | Path,
    candidate_id: str,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(DEFAULT_PRODUCTION_VALUE_POLICY)
    merged.update(dict(policy or {}))
    by_role, combined = _candidate_base_rows(event_db, candidate_id)
    checks: list[dict[str, Any]] = []
    roles: dict[str, Any] = {}

    def add(name: str, passed: bool, actual: Any = None, threshold: Any = None, details: Any = None):
        checks.append({
            "name": name,
            "passed": bool(passed),
            "actual": actual,
            "threshold": threshold,
            "details": details,
        })

    min_atr_value = float(merged.get("min_avg_net_points_over_atr", 0.10))
    for role in ROLES:
        summary = _role_value_summary(by_role.get(role) or [])
        roles[role] = summary
        add(
            f"{role}_ATR_COVERAGE",
            summary["trades"] > 0 and summary["atr_coverage_rate"] == 1.0,
            summary["atr_coverage_rate"],
            1.0,
            {"trades": summary["trades"], "atr_valid_trades": summary["atr_valid_trades"]},
        )
        value = summary["avg_net_points_over_atr"]
        add(
            f"{role}_AVG_NET_POINTS_OVER_ATR",
            value is not None and float(value) >= min_atr_value,
            value,
            f">= {min_atr_value}",
            {"winner_only": summary["avg_winner_net_points_over_atr"]},
        )

    month = _positive_profit_concentration(combined, "month")
    year = _positive_profit_concentration(combined, "year")
    month_limit = _valid_share_limit(merged.get("max_positive_month_profit_share"))
    year_limit = _valid_share_limit(merged.get("max_positive_year_profit_share"))

    add(
        "MONTH_CONCENTRATION_POLICY",
        month_limit is not None,
        merged.get("max_positive_month_profit_share"),
        "explicit 0 < share <= 1",
    )
    add(
        "YEAR_CONCENTRATION_POLICY",
        year_limit is not None,
        merged.get("max_positive_year_profit_share"),
        "explicit 0 < share <= 1",
    )
    month_share = month.get("largest_positive_profit_share")
    year_share = year.get("largest_positive_profit_share")
    add(
        "MONTH_PROFIT_CONCENTRATION",
        month_limit is not None and month_share is not None and float(month_share) <= month_limit,
        month_share,
        month_limit,
        month,
    )
    add(
        "YEAR_PROFIT_CONCENTRATION",
        year_limit is not None and year_share is not None and float(year_share) <= year_limit,
        year_share,
        year_limit,
        year,
    )

    passed = bool(checks) and all(x["passed"] for x in checks)
    audit = {
        "candidate_id": candidate_id,
        "passed": passed,
        "policy": merged,
        "policy_hash": content_hash(merged),
        "roles": roles,
        "month_concentration": month,
        "year_concentration": year,
        "checks": checks,
        "failed_checks": [x["name"] for x in checks if not x["passed"]],
        "methodology": {
            "atr": "immutable event-time ATR from frozen research event payload/features only; no gate-time recomputation",
            "atr_value": "mean(realized NET points / event-time ATR) over BASE trades; costs are already included in net_points",
            "concentration": "largest positive month/year net-R contribution divided by total positive month/year net-R contributions, aggregated across D/V/H BASE immutable ledgers",
            "roles": "year/month concentration is computed after pooling Discovery, Validation and Final Holdout BASE trades; role itself is never treated as a year",
        },
    }
    audit["audit_hash"] = content_hash(audit)
    return audit


def _migrate_value_audits(event_db: str | Path) -> None:
    migrate_strategy_db(event_db)
    with tx(event_db) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS production_value_audits(
              production_gate_id TEXT PRIMARY KEY,
              candidate_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              audit_hash TEXT NOT NULL,
              passed INTEGER NOT NULL,
              audit_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_production_value_audit_candidate
              ON production_value_audits(candidate_id,created_at);
            DROP TRIGGER IF EXISTS protect_production_value_audits_update;
            CREATE TRIGGER protect_production_value_audits_update
              BEFORE UPDATE ON production_value_audits
              BEGIN SELECT RAISE(ABORT,'production value audit is append-only'); END;
            DROP TRIGGER IF EXISTS protect_production_value_audits_delete;
            CREATE TRIGGER protect_production_value_audits_delete
              BEFORE DELETE ON production_value_audits
              BEGIN SELECT RAISE(ABORT,'production value audit is append-only'); END;
            """
        )


def record_production_value_audit(
    event_db: str | Path,
    production_gate_id: str,
    candidate_id: str,
    audit: dict[str, Any],
) -> dict[str, Any]:
    _migrate_value_audits(event_db)
    frozen = dict(audit)
    expected_hash = str(frozen.get("audit_hash") or content_hash({k: v for k, v in frozen.items() if k != "audit_hash"}))
    with tx(event_db) as c:
        c.execute(
            """INSERT INTO production_value_audits(
                 production_gate_id,candidate_id,created_at,audit_hash,passed,audit_json
               ) VALUES(?,?,?,?,?,?)""",
            (
                production_gate_id,
                candidate_id,
                utcnow(),
                expected_hash,
                int(bool(frozen.get("passed"))),
                json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
    return get_production_value_audit(event_db, production_gate_id)


def get_production_value_audit(event_db: str | Path, production_gate_id: str) -> dict[str, Any]:
    _migrate_value_audits(event_db)
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT * FROM production_value_audits WHERE production_gate_id=?",
            (production_gate_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(f"production value audit not found: {production_gate_id}")
    out = dict(row)
    audit = _json(out.get("audit_json"), {}) or {}
    actual_hash = content_hash({k: v for k, v in audit.items() if k != "audit_hash"})
    stored_payload_hash = str(audit.get("audit_hash") or "")
    out["audit"] = audit
    out["hash_valid"] = (
        str(out.get("audit_hash") or "") == stored_payload_hash == actual_hash
    )
    out["passed"] = bool(out.get("passed")) and bool(audit.get("passed"))
    return out


def require_passing_production_value_audit(event_db: str | Path, production_gate_id: str) -> dict[str, Any]:
    out = get_production_value_audit(event_db, production_gate_id)
    if not out.get("hash_valid"):
        raise RuntimeError("production value audit hash verification failed")
    if not out.get("passed"):
        raise RuntimeError("production deployment requires a passing production value audit")
    return out


__all__ = [
    "DEFAULT_PRODUCTION_VALUE_POLICY",
    "event_time_atr",
    "audit_candidate_production_value",
    "record_production_value_audit",
    "get_production_value_audit",
    "require_passing_production_value_audit",
]
