# Strategy Lab V1 Architecture

Status: **Research product layer — software implementation does not imply market-edge validation**

Strategy Lab extends the validated V4/V5 causal research stack. It does not replace the physical tick truth, contract engine, causal Market State Engine, Event Store, Replay, or Decision Gym.

## Product goal

Strategy Lab answers three practical research questions:

1. **What did a strategy actually do historically?** Every trade is linked back to the causal event, node timeline and physical `_seq` path, so a researcher can review signal/entry/stop/target/exit/MFE/MAE instead of reading only an aggregate PnL number.
2. **Which parameters are robust rather than merely lucky?** Optimization is constrained to parameters that do not alter the causal event universe, records the complete hypothesis search, applies multiple-testing control, and selects a parameter plateau rather than one isolated best point.
3. **Is a candidate ready to leave research?** Candidate parameters are frozen, then evaluated in Discovery → Validation → Final Holdout order with cost/latency stress, immutable dataset provenance, Historical ↔ Live parity evidence and paper-trading evidence.

## End-to-end architecture

```text
Raw MTX Parquet (physical row order)
        |
        v
Data Integrity / Contract / Session Engine
        |
        v
Shared causal Market State Engine (V4)
        |
        +--------------------+
        |                    |
        v                    v
Feature / Event Store     Causal Replay
        |
        v
Research Snapshot V6
4-state node truth + frozen digest + dataset SHA pins
        |
        v
Strategy Registry
immutable strategy_id + version + definition hash
        |
        v
Strategy Evaluator
rescan boundary enforcement
        |
        v
Execution Engine
physical _seq + fill/slippage/commission/latency/time-stop
        |
        v
Immutable Trade Ledger
        |
  +-----+------+----------------+
  |            |                |
  v            v                v
Review      Diagnostics       Full Report
KLineChart  causal/ex-post    EV/PF/DD/MFE/MAE/right-tail
  |                             |
  +-------------+---------------+
                v
        Optimization Lab
        BH-FDR + search ledger
        robust parameter plateau
                |
                v
        Frozen Candidate
                |
      Discovery Evaluation
                |
      Validation Evaluation
                |
      Final Holdout Evaluation
                |
        4 execution scenarios
  BASE / SLIPPAGE / LATENCY / COMBINED
                |
                v
    Production Provenance Gate
 frozen campaign + frozen run digest + exact dataset SHA
                |
        +-------+-------+
        |               |
        v               v
Historical↔Live      Paper Trading
Parity Evidence      Evidence
append-only          append-only
        |               |
        +-------+-------+
                v
        Production Gate
                |
                v
        Degradation Monitor
NORMAL / WATCH / DEGRADED / SUSPEND
```

## 1. Truth boundary

The original V4/V5 truth contract remains non-negotiable:

- Parquet physical row order is market-order truth.
- `_seq` is created before filtering and is never reconstructed by sorting timestamps.
- Same-second ticks preserve source physical order.
- Replay Hide Future removes future physical rows before any candle aggregation.
- MTX research uses outright six-digit expiry contracts and causal contract selection.
- `side` remains a Tick Rule proxy and must not be presented as true Bid/Ask aggressor flow.
- Outcomes never rewrite structural labels.

Strategy Lab consumes this truth; it does not invent a second scanner.

## 2. Research Snapshot V6

Every node persists one state:

- `EVALUATED` — node was causally reached; answer is YES/NO.
- `NOT_REACHED` — upstream blocker stopped the branch; answer is NULL.
- `NOT_APPLICABLE` — inactive branch; answer is NULL.
- `TERMINAL` — flow terminated; answer is NULL.

G3 node-edge inference is restricted to `EVALUATED` rows. A frozen `research_run_id` has a canonical SHA-256 digest and database triggers that reject mutation of canonical rows.

## 3. Campaign / dataset provenance

A research campaign owns its own Discovery / Validation / Final Holdout mapping. The old Fabio 2025 → 2024 → 2026 mapping remains a legacy fallback only.

A production-capable candidate must trace every evaluated role to:

- one frozen `research_campaigns` record;
- frozen `research_run_id` with a valid digest;
- `research_run_datasets` pins;
- exact source filename / role / year / SHA-256 equality with the frozen campaign dataset registry.

Diagnostic legacy runs can still be inspected, but they cannot pass the production boundary.

## 4. Strategy Registry and rescan boundary

A strategy definition is immutable by `(strategy_id, version)` and content hash. Parameters declare scope and whether they require re-scanning causal market structure.

Examples:

- detector / structural threshold such as LVN construction depth → `requires_rescan=true`;
- target R, stop buffer, time stop → normally `requires_rescan=false` when they operate only after a frozen causal signal.

Changing a rescan parameter on an existing research snapshot raises `RescanRequired`; the optimizer is not allowed to silently reuse stale events.

## 5. Execution Engine

All strategies share one execution contract. Supported assumptions are explicit and hashed:

- signal-tick or next-tick fill timing;
- entry and exit slippage;
- commission expressed in points per side;
- latency;
- stop / target / time stop;
- physical `_seq` path validation.

The Trade Ledger records signal, actual simulated entry, stop, target, exit, MFE, MAE, gross/net points and R, costs, holding time, causal validity, first failed node and post-trade diagnostic.

A losing trade is not automatically a strategy failure. `VALID_LOSS` remains a legitimate statistical outcome.

## 6. Diagnostics

Diagnostics are deliberately split:

- **Causal diagnosis** — facts available at decision time; may be used to evaluate live eligibility.
- **Post-trade diagnosis** — ex-post outcome attribution such as no follow-through, stop too tight, target too far or cost sensitivity; research only unless independently converted into a causal feature in a new run.

This prevents hindsight labels from leaking back into signal quality.

## 7. Full report

The report center persists both aggregate metrics and slices. Core metrics include:

- trades / win rate;
- gross and net total R;
- gross and net expectancy R;
- expectancy cross-check: `win_rate * avg_win + loss_rate * avg_loss`;
- profit factor and explicit unbounded/no-loss state;
- payoff ratio;
- Max Drawdown and drawdown duration;
- maximum consecutive losses;
- points per trade and cost per trade;
- MFE / MAE in points and R;
- capture ratio;
- realized and MFE right-tail retention at 1R / 2R / 3R / 5R;
- percentiles;
- worst trade / trading day / month;
- trading-day-cluster bootstrap expectancy CI and p-value.

Slices include year, month, direction, strategy family, exit reason, post-trade reason and 30-minute time buckets. Additional regime fields can be added only when they originate from causal event features.

## 8. Optimization

Final Holdout is programmatically sealed from parameter optimization.

Every optimization run records:

- declared search space;
- actual hypotheses tested;
- every parameter trial and parameter hash;
- objective and acceptance gates;
- EV / PF / DD / trade count / p-value;
- BH-FDR q-value;
- rejection reason;
- immutable optimization digest.

The primary selection object is a **Robust Parameter Plateau**, not a single best trial. A plateau summarizes the top admissible neighborhood and its parameter ranges. Detector parameters requiring re-scan are hard-blocked.

## 9. Candidate lifecycle

A parameter set can be frozen as a candidate. The parameter hash never changes afterward.

Candidate evaluation order is enforced:

```text
Discovery PASS
    -> Validation allowed
Validation PASS
    -> Final Holdout allowed
Final Holdout PASS
    -> research part of Production Gate may proceed
```

Each role is re-evaluated under:

- BASE
- SLIPPAGE stress
- LATENCY stress
- COMBINED stress

Each scenario creates its own immutable backtest and digest.

## 10. Production evidence

The Production Gate does **not** accept manually asserted `true/false` flags for live parity or paper trading.

### Historical ↔ Live parity

The supplied historical and live causal traces are compared field-by-field. Evidence is persisted append-only with:

- candidate ID;
- historical/live trace SHA-256;
- row counts;
- diff count;
- complete parity result.

Only a non-empty, identical trace receives PASS.

### Paper trading

Paper evidence must identify its source and a 64-character SHA-256 artifact digest. PASS is derived from persisted numeric metrics and policy; a caller cannot submit a naked PASS.

Default software policy currently requires at least 30 paper trades, positive expectancy, PF ≥ 1 and Max DD ≤ 12R. These thresholds are governance defaults, not proof of universal profitability.

## 11. Production Gate

Default gate additionally requires:

- all three candidate roles PASS;
- exact frozen campaign / run / dataset provenance;
- every stored backtest digest verifies;
- MR target ≥ 1R or BO target ≥ 2R;
- Final Holdout COMBINED stress expectancy > 0;
- persisted passing parity evidence;
- persisted passing paper evidence.

The current historical MR/BO training baselines are therefore expected to remain blocked if they do not satisfy these requirements. Software completion must never be presented as market-edge validation.

## 12. Long-running jobs

Backtest, optimization and candidate evaluation can run through the durable Job Supervisor:

- SQLite-backed job state;
- QUEUED / RUNNING / SUCCEEDED / FAILED / TIMED_OUT / CANCELLED / ORPHANED;
- child-process isolation;
- heartbeat every five seconds;
- hard process termination on timeout;
- explicit cancellation;
- unfinished jobs are marked ORPHANED after server restart;
- write-heavy jobs are serialized because the research store is SQLite.

Production Gate itself remains synchronous and evidence-governed; it is not accepted as a generic background job.

## 13. Frontend

`strategy-lab.html` provides eight areas:

1. Strategy Library
2. Backtest Studio
3. Trade Review
4. Report Center
5. Optimization Lab
6. Compare Lab
7. Candidate / Gate
8. Jobs / Heartbeat

Trade Review reuses the existing KLineChart 10.0.2 + PixiJS 8.19.0 causal visualization stack. No second chart/replay implementation is introduced.

## 14. Public deployment boundary

The static build publishes UI/runtime assets only. `reports/`, `docs/`, and `config/` are intentionally excluded from `dist/` so internal research evidence and configuration are not bundled as public application assets.

## 15. Reproducibility

The runtime is pinned in CI and `tools/repro_manifest.py` records:

- Git commit;
- Python/runtime platform;
- exact core Python package versions;
- SHA-256 of runtime dependency files, node registry and strategy configs;
- manifest SHA-256.

The manifest accompanies Strategy Lab CI diagnostics.

## 16. Completion definition

Strategy Lab software is complete only when:

- P0 truth and regression tests remain green;
- Strategy Lab backend tests remain green;
- production provenance and evidence tests remain green;
- browser contract remains green;
- public build passes leakage checks;
- reproducibility manifest is emitted;
- no `main` merge occurs without explicit approval.

Market-edge validation is a separate research result and can legitimately remain **BLOCKED / INSUFFICIENT** after the software itself is complete.
