from __future__ import annotations

import json
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .diagnostics import causal_diagnostic, infer_regime, post_trade_diagnostic
from .execution import ExecutionModel, simulate_physical_trade
from .portfolio import PortfolioPolicy, arbitrate_trades
from .reporting import build_full_report
from .storage import connect, migrate_event_db, tx, utcnow
from .strategy_registry import StrategyDefinition, canonical_json, content_hash
from .strategy_storage import (
    freeze_backtest_run,
    migrate_strategy_db,
    register_execution_model,
    register_strategy,
)


class RescanRequired(RuntimeError):
    def __init__(self, parameters: list[str]):
        self.parameters = list(parameters)
        super().__init__(
            "parameter change requires causal scanner recomputation: " + ", ".join(self.parameters)
        )


class PhysicalPathLoader:
    """Cache full physical trading windows by source/contract/day.

    The cache never sorts rows. Every returned frame is sliced by `_seq` from the
    already-physical V4 replay reader.
    """

    def __init__(self, data_root: str | Path, max_after_days: int = 1):
        self.data_root = Path(data_root)
        self.max_after_days = int(max_after_days)
        self._cache: dict[tuple[str, str, str, int], pd.DataFrame] = {}

    def __call__(self, event: dict[str, Any], start_seq: int) -> pd.DataFrame:
        from server.v4_replay_final import read_tick_path

        key = (
            str(event.get("source_file") or ""),
            str(event.get("contract") or ""),
            str(event.get("trading_date") or "")[:10],
            self.max_after_days,
        )
        frame = self._cache.get(key)
        if frame is None:
            # start_seq=0 asks the validated V4 reader for the complete physical
            # window. Per-event slicing below cannot introduce future reordering.
            frame = read_tick_path(self.data_root, event, 0, self.max_after_days)
            self._cache[key] = frame
        if frame is None or frame.empty:
            return pd.DataFrame()
        return frame.loc[frame["_seq"].astype("int64") >= int(start_seq)].reset_index(drop=True)


def _load_research_run(event_db: str | Path, research_run_id: str) -> dict[str, Any]:
    migrate_event_db(event_db)
    c = connect(event_db)
    try:
        row = c.execute(
            "SELECT * FROM research_runs WHERE research_run_id=?", (research_run_id,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(f"research run not found: {research_run_id}")
    return dict(row)


def _load_candidates(
    event_db: str | Path,
    research_run_id: str,
    strategy_family: str,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    c = connect(event_db)
    try:
        events = [
            dict(r)
            for r in c.execute(
                """SELECT * FROM events
                   WHERE research_run_id=? AND strategy=?
                     AND entry_seq IS NOT NULL AND entry_price IS NOT NULL
                   ORDER BY source_file,trading_date,attempt_start_seq,event_id""",
                (research_run_id, strategy_family),
            ).fetchall()
        ]
        if not events:
            return [], {}
        event_ids = {e["event_id"] for e in events}
        nodes = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM event_nodes WHERE research_run_id=? ORDER BY event_id,resolution_seq,node_id",
                (research_run_id,),
            ).fetchall()
            if r["event_id"] in event_ids
        ]
    finally:
        c.close()
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n in nodes:
        by_event[str(n["event_id"])].append(n)
    return events, by_event


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(event.get("payload_json") or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _resolved_trade_levels(
    event: dict[str, Any],
    strategy: StrategyDefinition,
    overrides: dict[str, Any],
) -> tuple[float, float, int | None, dict[str, Any]]:
    direction = str(event.get("direction"))
    entry = float(event["entry_price"])
    stop = float(event["stop"])
    target = float(event["target"])
    resolved = strategy.resolved_config(overrides)
    notes: dict[str, Any] = {}

    if "stop.points" in overrides:
        points = float(overrides["stop.points"])
        raw = _payload(event)
        lvn = raw.get("lvn")
        if lvn is not None and str((resolved.get("stop") or {}).get("type")) == "lvn_buffer":
            lvn = float(lvn)
            stop = lvn - points if direction == "long" else lvn + points
            notes["stop_basis"] = "LVN_BUFFER"
        else:
            stop = entry - points if direction == "long" else entry + points
            notes["stop_basis"] = "ENTRY_DISTANCE_FALLBACK"

    risk = abs(entry - stop)
    if risk <= 0:
        raise ValueError("resolved stop produces zero risk")
    if "target.r" in overrides:
        rr = float(overrides["target.r"])
        target = entry + rr * risk if direction == "long" else entry - rr * risk
        notes["target_basis"] = "OVERRIDE_R"

    time_stop = resolved.get("time_stop_seconds")
    time_stop = int(time_stop) if time_stop is not None else None
    return stop, target, time_stop, notes


def evaluate_backtest(
    event_db: str | Path,
    data_root: str | Path,
    research_run_id: str,
    strategy: StrategyDefinition,
    *,
    overrides: dict[str, Any] | None = None,
    execution_model: ExecutionModel | dict[str, Any] | None = None,
    portfolio_policy: PortfolioPolicy | dict[str, Any] | None = None,
    path_loader: Callable[[dict[str, Any], int], pd.DataFrame] | None = None,
    require_frozen_research: bool = True,
    bootstrap_reps: int = 2000,
) -> dict[str, Any]:
    migrate_event_db(event_db)
    run = _load_research_run(event_db, research_run_id)
    if require_frozen_research and not bool(run.get("frozen")):
        raise RuntimeError("formal backtest requires a frozen research_run_id")

    clean_overrides = strategy.validate_overrides(overrides)
    rescan = strategy.rescan_parameters(clean_overrides)
    if rescan:
        raise RescanRequired(rescan)

    model = execution_model if isinstance(execution_model, ExecutionModel) else ExecutionModel.from_dict(execution_model)
    policy_explicit = portfolio_policy is not None
    portfolio = portfolio_policy if isinstance(portfolio_policy, PortfolioPolicy) else PortfolioPolicy.from_dict(portfolio_policy)
    portfolio.validate()
    loader = path_loader or PhysicalPathLoader(data_root)
    events, nodes_by_event = _load_candidates(event_db, research_run_id, strategy.family)
    trades: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for event in events:
        nodes = nodes_by_event.get(str(event["event_id"]), [])
        causal = causal_diagnostic(event, nodes, strategy.node_chain)
        if not causal["causal_valid"]:
            skipped.append({
                "event_id": event["event_id"],
                "reason": causal["causal_reason"],
                "first_failed_node": causal["first_failed_node"],
            })
            continue
        try:
            stop, target, time_stop, level_notes = _resolved_trade_levels(
                event, strategy, clean_overrides
            )
            signal_seq = int(event["entry_seq"])
            path = loader(event, signal_seq)
            result = simulate_physical_trade(
                path,
                direction=str(event["direction"]),
                signal_seq=signal_seq,
                signal_price=float(event["entry_price"]),
                stop_price=stop,
                target_price=target,
                model=model,
                time_stop_seconds=time_stop,
                force_flat_time=portfolio.force_flat_time,
            )
        except Exception as exc:
            skipped.append({"event_id": event["event_id"], "reason": f"EXECUTION_ERROR:{exc}"})
            continue

        month = str(event.get("trading_date") or "")[:7]
        trade = {
            "trade_id": f"{event['event_id']}:{result['entry_seq']}",
            "event_id": event["event_id"],
            "trading_date": event.get("trading_date"),
            "year": event.get("year"),
            "month": month,
            "strategy_family": strategy.family,
            "direction": event.get("direction"),
            "signal_seq": signal_seq,
            "signal_time": event.get("entry_time"),
            "signal_price": event.get("entry_price"),
            **{k: result[k] for k in (
                "entry_seq", "entry_time", "entry_price", "stop_price", "target_price",
                "exit_seq", "exit_time", "exit_price", "exit_reason", "risk_points",
                "mfe_points", "mae_points", "mfe_r", "mae_r", "gross_points",
                "net_points", "gross_r", "net_r", "capture_ratio", "commission_points",
                "slippage_points", "latency_ms", "holding_seconds",
            )},
            "causal_valid": True,
            "causal_reason": causal["causal_reason"],
            "first_failed_node": causal["first_failed_node"],
            "regime": infer_regime(event),
            "payload": {
                "source_file": event.get("source_file"),
                "contract": event.get("contract"),
                "execution": result.get("execution_model"),
                "level_resolution": level_notes,
                "parameter_overrides": clean_overrides,
            },
        }
        post = post_trade_diagnostic(trade)
        trade["post_trade_reason"] = post["post_trade_reason"]
        trade["payload"]["post_trade_diagnostic"] = post
        trades.append(trade)

    trades, portfolio_skips = arbitrate_trades(trades, portfolio)
    skipped.extend(portfolio_skips)
    report = build_full_report(trades, bootstrap_reps=bootstrap_reps)
    report["summary"]["candidate_events"] = len(events)
    report["summary"]["executed_trades"] = len(trades)
    report["summary"]["skipped_events"] = len(skipped)
    report["summary"]["portfolio_skipped_events"] = len(portfolio_skips)
    report["summary"]["position_net_points"] = float(sum(
        float(t.get("net_points") or 0.0) * float(t.get("quantity") or 1.0) for t in trades
    ))
    report["portfolio_policy"] = portfolio.to_dict()
    report["portfolio_policy_hash"] = content_hash(portfolio.to_dict())
    report["portfolio_skips"] = portfolio_skips
    return {
        "research_run": run,
        "strategy": strategy.to_dict(),
        "parameters": clean_overrides,
        "execution_model": model.to_dict(),
        "portfolio_policy": portfolio.to_dict(),
        "portfolio_policy_hash": report["portfolio_policy_hash"],
        "portfolio_policy_explicit": policy_explicit,
        "trades": trades,
        "skipped": skipped,
        "report": report,
        "mode": "PHYSICAL_TICK",
    }


def _insert_report_metrics(c, backtest_run_id: str, report: dict[str, Any]) -> None:
    rows = []
    for key, value in (report.get("summary") or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            rows.append((backtest_run_id, key, "ALL", "ALL", float(value), "{}"))
    for item in report.get("slices") or []:
        sk = str(item.get("slice_key") or "UNKNOWN")
        sv = str(item.get("slice_value") or "UNKNOWN")
        for key, value in (item.get("metrics") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                rows.append((backtest_run_id, key, sk, sv, float(value), "{}"))
    if "portfolio_policy" in report:
        rows.append((
            backtest_run_id,
            "portfolio_policy_audit",
            "AUDIT",
            str(report.get("portfolio_policy_hash") or "UNKNOWN"),
            float((report.get("summary") or {}).get("portfolio_skipped_events") or 0),
            canonical_json({
                "policy": report.get("portfolio_policy") or {},
                "policy_hash": report.get("portfolio_policy_hash"),
                "skips": report.get("portfolio_skips") or [],
            }),
        ))
    if rows:
        c.executemany(
            "INSERT OR REPLACE INTO backtest_metrics VALUES(?,?,?,?,?,?)",
            rows,
        )


def persist_backtest(
    event_db: str | Path,
    evaluated: dict[str, Any],
    *,
    backtest_run_id: str | None = None,
    code_commit: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    migrate_strategy_db(event_db)
    strategy = StrategyDefinition(
        strategy_id=evaluated["strategy"]["strategy_id"],
        version=evaluated["strategy"]["version"],
        name=evaluated["strategy"]["name"],
        family=evaluated["strategy"]["family"],
        description=evaluated["strategy"].get("description") or "",
        schema_version=int(evaluated["strategy"]["schema_version"]),
        node_chain=tuple(evaluated["strategy"]["node_chain"]),
        parameters=tuple(),
        definition=evaluated["strategy"]["definition"],
        source_path=evaluated["strategy"].get("source_path"),
        definition_hash=evaluated["strategy"]["definition_hash"],
    )
    # Registration uses immutable hashes; the original parameter schema remains in
    # evaluated['strategy'] and the strategy definition JSON.
    register_strategy(event_db, strategy)
    execution = dict(evaluated["execution_model"])
    exec_id = str(execution.get("execution_model_id") or "PHYSICAL_MARKET")
    exec_ver = str(execution.get("version") or "V1")
    execution_definition: dict[str, Any] = execution
    if bool(evaluated.get("portfolio_policy_explicit")):
        policy = dict(evaluated.get("portfolio_policy") or {})
        policy_hash = str(evaluated.get("portfolio_policy_hash") or content_hash(policy))
        exec_ver = f"{exec_ver}-PF-{policy_hash[:8]}"
        execution_definition = {
            "execution_model": execution,
            "portfolio_policy": policy,
            "portfolio_policy_hash": policy_hash,
        }
    exec_row = register_execution_model(event_db, exec_id, exec_ver, execution_definition)
    research = evaluated["research_run"]
    backtest_run_id = backtest_run_id or ("bt-" + uuid.uuid4().hex[:16])
    params = dict(evaluated.get("parameters") or {})
    params_hash = content_hash(params)
    with tx(event_db) as c:
        if c.execute(
            "SELECT 1 FROM backtest_runs WHERE backtest_run_id=?", (backtest_run_id,)
        ).fetchone():
            raise ValueError(f"immutable backtest_run_id already exists: {backtest_run_id}")
        c.execute(
            """INSERT INTO backtest_runs(
              backtest_run_id,research_run_id,campaign_id,strategy_key,strategy_hash,
              parameters_json,parameters_hash,execution_model_id,execution_model_version,
              execution_hash,code_commit,data_digest,mode,status,created_at,notes
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?,?)""",
            (
                backtest_run_id,
                research["research_run_id"],
                research.get("campaign_id"),
                evaluated["strategy"]["strategy_key"],
                evaluated["strategy"]["definition_hash"],
                canonical_json(params),
                params_hash,
                exec_id,
                exec_ver,
                exec_row["definition_hash"],
                code_commit,
                research.get("frozen_digest"),
                evaluated.get("mode") or "PHYSICAL_TICK",
                utcnow(),
                notes,
            ),
        )
        trade_rows = []
        for t in evaluated.get("trades") or []:
            trade_rows.append((
                backtest_run_id,
                t["trade_id"], t["event_id"], t.get("trading_date"), t.get("year"), t.get("month"),
                t.get("strategy_family"), t.get("direction"), t.get("signal_seq"), t.get("signal_time"),
                t.get("signal_price"), t.get("entry_seq"), t.get("entry_time"), t.get("entry_price"),
                t.get("stop_price"), t.get("target_price"), t.get("exit_seq"), t.get("exit_time"),
                t.get("exit_price"), t.get("exit_reason"), t.get("risk_points"), t.get("mfe_points"),
                t.get("mae_points"), t.get("mfe_r"), t.get("mae_r"), t.get("gross_points"),
                t.get("net_points"), t.get("gross_r"), t.get("net_r"), t.get("capture_ratio"),
                t.get("commission_points"), t.get("slippage_points"), t.get("latency_ms"),
                t.get("holding_seconds"), int(bool(t.get("causal_valid"))), t.get("causal_reason"),
                t.get("first_failed_node"), t.get("post_trade_reason"),
                canonical_json(t.get("regime") or {}), canonical_json(t.get("payload") or {}),
            ))
        if trade_rows:
            c.executemany(
                "INSERT INTO backtest_trades VALUES(" + ",".join(["?"] * 40) + ")",
                trade_rows,
            )
        _insert_report_metrics(c, backtest_run_id, evaluated["report"])
    digest = freeze_backtest_run(event_db, backtest_run_id)
    return {
        "backtest_run_id": backtest_run_id,
        "frozen": True,
        "digest": digest,
        "trades": len(evaluated.get("trades") or []),
        "skipped": len(evaluated.get("skipped") or []),
        "portfolio_policy": evaluated.get("portfolio_policy") or {},
        "portfolio_policy_hash": evaluated.get("portfolio_policy_hash"),
        "report": evaluated["report"],
    }


def run_backtest(
    event_db: str | Path,
    data_root: str | Path,
    research_run_id: str,
    strategy: StrategyDefinition,
    **kwargs,
) -> dict[str, Any]:
    persist_keys = {"backtest_run_id", "code_commit", "notes"}
    persist_args = {k: kwargs.pop(k) for k in list(kwargs) if k in persist_keys}
    evaluated = evaluate_backtest(
        event_db,
        data_root,
        research_run_id,
        strategy,
        **kwargs,
    )
    return persist_backtest(event_db, evaluated, **persist_args)
