# Strategy Lab V1 / Research Integrity V6 — Implementation Closeout

Date: 2026-09-07  
Repository: `cheneddie/klinechats_VT`  
Working branch: `research-integrity-p0`  
Integration target: `fabio-decision-gym-v4`  
`main` remains intentionally untouched.

## Status

- SOFTWARE IMPLEMENTATION: **PASS**
- RESEARCH INTEGRITY / GOVERNANCE PLUMBING: **PASS**
- SYNTHETIC PHYSICAL PARQUET END-TO-END: **PASS**
- REAL MTX MARKET EDGE: **NOT PROVEN / BLOCKED PENDING REAL DATA**
- MAIN BRANCH MERGE: **NOT PERFORMED**

This work adds a governed Strategy Research Workbench on top of the validated V4/V5 causal research stack. It does not replace the causal scanner/state engine and does not relax the project's raw physical `_seq`, contract, holdout, or provenance rules.

## Product surface completed

Strategy Lab now provides:

1. **Strategy Library**
   - immutable strategy identity/version/definition hash
   - MR / BO family metadata
   - parameter schema
   - explicit `requires_rescan` boundary

2. **Backtest Studio**
   - frozen research-run selection
   - execution-model configuration
   - physical tick fill simulation
   - commission / slippage / latency modeling
   - immutable backtest run and trade ledger

3. **Trade Review**
   - complete trade list
   - signal / entry / stop / target / exit
   - MFE / MAE / realized R
   - post-trade diagnostic reason
   - causal node timeline
   - KLineChart 10.0.2 + PixiJS replay reuse
   - V5 replay routing for Strategy Lab cases while preserving legacy V4 replay routing

4. **Report Center**
   - trades / wins / losses / win rate
   - gross and net expectancy
   - Profit Factor
   - average win / loss and payoff ratio
   - Max Drawdown and drawdown duration
   - consecutive-loss statistics
   - MFE / MAE / capture ratio
   - realized and opportunity right-tail rates (1R/2R/3R/5R)
   - trading-day cluster-bootstrap expectancy confidence interval
   - year / month / direction / family / exit / failure / time-bucket breakdowns

5. **Optimization Lab**
   - governed parameter search
   - detector/rescan parameters hard-blocked from snapshot reuse
   - robust parameter plateau selection instead of a single best point
   - multiple-hypothesis accounting metadata
   - Final Holdout excluded from tuning

6. **Candidate / Validation / Holdout flow**
   - immutable candidate freeze
   - enforced evaluation order: Discovery → Validation → Final Holdout
   - base / slippage / latency / combined-stress evaluation
   - append-only candidate evaluation records

7. **Production Gate**
   - no manual `PASS=true` shortcut
   - requires governed provenance
   - requires frozen campaign/research evidence and dataset identity consistency
   - MR production research target policy ≈ 1R minimum, BO ≈ 2R minimum
   - requires real stored Historical↔Live parity evidence
   - requires real stored paper-trading evidence
   - gate decisions are append-only

8. **Jobs / Heartbeat**
   - child-process isolation for long jobs
   - persisted heartbeat
   - hard timeout terminates the child process
   - user cancellation
   - server restart marks unfinished jobs `ORPHANED`
   - SQLite write-heavy jobs serialized to avoid lock races

9. **Monitoring**
   - governed post-deployment monitoring primitives for drift/performance review

## Research-integrity hardening included

The branch also carries the V5/P0 research-integrity hardening required by Strategy Lab:

- four-state node truth: `EVALUATED`, `NOT_REACHED`, `NOT_APPLICABLE`, `TERMINAL`
- frozen research runs are database-immutable and digest-verifiable
- trading-day cluster bootstrap
- BH-FDR adjusted node-edge inference
- campaign-specific dataset roles and SHA-256 pinning
- immutable `research_run_datasets`
- legacy Fabio governance retained only as backward-compatible mapping:
  - 2025 = Discovery
  - 2024 = Validation
  - 2026 = Final Holdout

## Reproducibility / deployment hardening

- exact Python runtime dependency pins
- Node 24 + pnpm 10.15.1 + frozen lockfile in Strategy Lab CI
- reproducibility manifest generation
- public static build contains UI/runtime assets only
- `reports/`, `docs/`, and `config/` are explicitly excluded from the public `dist`
- browser Strategy Lab contract QA included

## Synthetic MTX physical-Parquet integration proof

A deterministic synthetic fixture was added solely to prove that the complete software path actually executes against a real Parquet file.

**This fixture is SYNTHETIC DATA — NOT MARKET EDGE EVIDENCE. It must never be mixed with real MTX research campaigns or used to support a production strategy claim.**

Final fixture contract:

- file: `MTX_2025_SYNTHETIC.parquet`
- rows: **2,101**
- Parquet row groups: **5**
- schema: `datetime, product, expiry, price, volume, side`
- source SHA-256: `b7467b2e3144aaca0a851b553aad11900b30b76a408840b5943b75dab0a4df80`
- contract: `202509`
- physical replay `_seq`: **0..2100**, strictly increasing
- research run: `synthetic-mtx-discovery-v1`
- research digest: `57e3570d5484d3a23370f2b461365d9e4361aed48d52016aa237a75949ec3055`
- strategy: `MR_BROAD@V3`
- seeded events: **4**
- persisted backtest trades: **4**
- backtest run: `bt-synthetic-mtx-mr-v1`
- backtest digest: `d830db4669f4f8717dd6630e830cb452535590a7b79f217b866b894a475c173d`
- exit sequence: `TARGET, STOP, TIME, TARGET`

Synthetic backtest summary:

- trades: **4**
- wins / losses: **3 / 1**
- win rate: **75%**
- net total: **+0.432R**
- net expectancy: **+0.108R/trade**
- Profit Factor: **1.375**
- Max Drawdown: **1.152R**
- average MFE: **0.490R**
- average MAE: **0.270R**
- average capture ratio: **61.0%**

These numbers are intentionally generated from shaped synthetic prices and have **zero evidentiary value for real MTX edge**.

The optimizer was also executed against the synthetic fixture with three hypotheses:

- `target.r = 0.50`
- `target.r = 0.75`
- `target.r = 1.00`

Synthetic robust plateau result:

- range: **0.75R..1.00R**
- center: **0.875R**

Again, this proves optimizer execution and plateau persistence only; it does not identify a real-world optimal MTX parameter.

## Integration defect found by the synthetic run

The synthetic E2E test exposed a real application integration defect that unit tests had not surfaced:

- Strategy Lab Trade Review reused `FabioV4.chart`.
- The chart replay loader was hard-coded to `/v4/replay` and `/v4/training-replay`.
- A V5 Strategy Lab trade therefore loaded a valid persisted Trade Ledger row but failed chart replay with HTTP 404.

The replay loader was corrected so that:

- legacy V4 cases continue to use `/v4/replay` and `/v4/training-replay`;
- cases carrying `research_run_id` use `/v5/replay` and `/v5/training-replay`.

The populated final Trade Review browser run now confirms that V5 physical replay, K-line chart rendering, execution details and causal node timeline operate together.

## Final automated verification

Final audited implementation head before this documentation-only closeout commit:

`0cbd16e2e223cbd70029dfabebf182583f85c885`

GitHub Actions at that head:

- V5 Research CI run `34093942750`: **PASS**
- Browser release QA run `34093942768`: **PASS**
- Strategy Lab CI run `34093942754`: **PASS**
- Synthetic MTX Parquet end-to-end + populated runtime screenshots: **PASS**
- Reproducibility manifest: **PASS**

The Strategy Lab workflow verifies:

- Python module compilation
- JS syntax
- Strategy Lab unit/integration tests
- candidate / production-gate tests
- production provenance tests
- long-job/watchdog tests
- V5 research-integrity regression
- V5 layer regression
- public static build
- no research/config/report leakage to `dist`
- reproducibility manifest generation
- synthetic physical Parquet generation
- frozen research-run digest verification
- physical row-order / `_seq` verification
- persisted immutable backtest ledger verification
- stop / target / time exit-path verification
- optimization / plateau smoke test
- real V5 API startup
- real frontend startup
- populated Trade Review and Report Center browser QA
- eight-page Chrome runtime screenshots

## Important boundary: engineering complete ≠ market edge proven

This closeout means the **software architecture, governance path, physical Parquet replay, immutable ledger, optimizer and browser integration execute successfully**. It does **not** mean MR or BO has been proven production-profitable.

The synthetic fixture contains one deliberately shaped synthetic trading day. Cluster-bootstrap statistics from that fixture are therefore not inferential market evidence.

Real strategy approval still requires actual MTX evidence to pass the governed sequence:

`Raw/Contract Integrity → Frozen Discovery → Candidate Freeze → Validation → Final Holdout → Cost/Latency Stress → Historical↔Live Parity → Paper Trading → Production Gate`

No Final Holdout result may be used to tune parameters after candidate freeze. No Production Gate may infer PASS from the synthetic fixture.

## Next real-data action

Register actual MTX source files with exact SHA-256 under a frozen campaign, then run the causal scanner and sanity gate before any formal Discovery backtest. Only real frozen Discovery data may start the candidate research lifecycle.

## Merge status

The branch remains **Draft / research-only** for integration review into `fabio-decision-gym-v4`. It must not be merged into `main` without explicit repository-owner approval.
