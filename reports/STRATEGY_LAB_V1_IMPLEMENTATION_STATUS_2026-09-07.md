# Strategy Lab V1 Implementation Status — 2026-09-07

## Scope and branch

- Repository: `cheneddie/klinechats_VT`
- Working branch: `research-integrity-p0`
- Integration target: `fabio-decision-gym-v4`
- `main` is intentionally untouched.
- At the audited head before this closeout document, the branch was **76 commits ahead / 0 behind** `fabio-decision-gym-v4`.

This work adds a governed **Strategy Research Workbench** on top of the validated V4/V5 causal research stack. It does not replace the causal scanner/state engine and does not relax the project's raw physical `_seq`, contract, holdout, or provenance rules.

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
   - MR target policy ≈ 1R minimum, BO ≈ 2R minimum
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

## Automated verification at audited head

Audited head: `f240f20b78f64acff541b29678a97622b1aed93c`

GitHub Actions status at that head:

- `research`: **PASS**
- `strategy-lab`: **PASS**

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

Earlier browser-release QA for the Strategy Lab/browser integration also passed.

## Important boundary: engineering complete ≠ market edge proven

This closeout means the **software architecture and governance path are implemented and automated tests are green**. It does **not** mean MR or BO has been proven production-profitable.

Real strategy approval still requires actual MTX evidence to pass the governed sequence:

`Raw/Contract Integrity → Frozen Discovery → Candidate Freeze → Validation → Final Holdout → Cost/Latency Stress → Historical↔Live Parity → Paper Trading → Production Gate`

No Final Holdout result may be used to tune parameters after candidate freeze.

## Merge status

This branch is ready for **Draft PR review into `fabio-decision-gym-v4`**. It must remain draft/research-only until the repository owner explicitly approves integration. It must not be merged into `main` as part of this implementation closeout.
