# Strategy Lab V1 / Research Integrity V6 — Implementation Closeout + P1 Production Value Addendum

Date: 2026-09-08  
Repository: `cheneddie/klinechats_VT`  
Working branch: `research-integrity-p0`  
Integration target: `fabio-decision-gym-v4`  
`main` remains intentionally untouched.

## Status

- SOFTWARE IMPLEMENTATION / STRATEGY LAB: **PASS**
- RESEARCH INTEGRITY / GOVERNANCE PLUMBING: **PASS**
- SYNTHETIC PHYSICAL PARQUET END-TO-END: **PASS**
- P0 EXECUTION-TRUTH / FEATURE QA: **PASS**
- P1 PRODUCTION VALUE GATES: **PASS (IMPLEMENTATION)**
- REAL MTX MARKET EDGE: **NOT PROVEN / BLOCKED PENDING REAL DATA**
- MAIN BRANCH MERGE: **NOT PERFORMED**

The branch provides a governed Strategy Research Workbench on top of the validated V4/V5 causal research stack. It does not replace the causal scanner/state engine and does not relax raw physical `_seq`, contract, holdout, dataset provenance, immutable execution identity, or evidence requirements.

## Product / research surface

Strategy Lab includes:

1. **Strategy Library** — immutable strategy ID/version/hash, MR/BO metadata, parameter schema, `requires_rescan` boundary.
2. **Backtest Studio** — frozen research-run selection, physical tick execution, commission/slippage/latency, portfolio policy, immutable ledger and digest.
3. **Trade Review** — signal/entry/stop/target/exit, MFE/MAE/R, causal node timeline, V5 replay with KLineChart/PixiJS.
4. **Report Center** — EV/PF/DD/win rate/payoff/MFE/MAE/capture/right-tail, trading-day cluster bootstrap, year/month/direction/family/exit/time slices.
5. **Optimization Lab** — execution-only governed search, rescan parameters blocked, robust plateau, hypothesis accounting, Final Holdout tuning denial.
6. **Candidate flow** — immutable freeze, Discovery → Validation → Final Holdout ordering, BASE/SLIPPAGE/LATENCY/COMBINED scenarios, append-only evaluation records.
7. **Production Evidence / Gate** — provenance, exact D/V/H identity, MR/BO reward floor, stress, Historical↔Live parity, Paper evidence, Production Value Audit, append-only decisions.
8. **Jobs / Heartbeat** — process isolation, persisted heartbeat, hard timeout, cancellation, restart orphan handling, strict terminal audit metadata.
9. **Production Deployment / Monitoring** — immutable deployment identity, execution observations, health snapshots, sticky suspension and explicit resume controls.

## P0 execution-truth closeout

The goal-alignment review showed that queue submission and browser success were not sufficient proof that long research jobs actually completed. P0 therefore tightened executable truth rather than adding general UI polish.

Completed hardening:

- Candidate Freeze refreshes backend candidate registry before displaying success.
- Newly frozen candidate is synchronously available to Evaluation and Gate selectors.
- Strict Feature QA requires Backtest, Optimization and Candidate Evaluation jobs to be terminal `SUCCEEDED`.
- Candidate Evaluation must contain a real `evaluation_id` and the expected role.
- `SUCCEEDED` with stale `error_text` is a QA failure.
- Multiprocessing spawned workers cannot run restart orphan recovery against live parent-process jobs.
- Successful jobs clear stale error metadata.
- Restart recovery remains available to the API main process and marks genuinely unfinished jobs `ORPHANED`.

Synthetic Candidate Evaluation remains `INSUFFICIENT` when sample size is insufficient. That is expected research behavior, not a failure to be hidden.

## P1 Production Value layer

The target review identified three missing economic-value conditions that were not previously formal Production Gate requirements:

1. realized points relative to contemporaneous ATR;
2. excessive month profit concentration;
3. excessive dependence on one year.

These are now implemented in `server/v5/production_value.py` and enforced by the public Production Gate wrapper.

### Immutable evidence reconstruction

Production Value Audit does not recompute indicators from market data at Gate time. It joins immutable evidence:

`candidate_evaluations → BASE backtest_trades → frozen research events`

The BASE backtest ID is the immutable `candidate_evaluations.backtest_run_id`. ATR is read only from the event snapshot already frozen by research generation. No future bars, post-trade MFE, stop distance or alternate ATR implementation is permitted as a fallback.

### ATR gate

For each of `DISCOVERY`, `VALIDATION`, `FINAL_HOLDOUT`:

- BASE trades must have **100% valid event-time ATR coverage**;
- ATR must be finite and > 0;
- `avg_net_points_over_atr = mean(realized NET points / event-time ATR)`;
- default minimum = **0.10**;
- average winner ratio is reported as diagnostic context only.

The numerator is `net_points`, so configured commission/slippage is already reflected in the economic-value test.

### Month / year concentration

D/V/H BASE ledgers are pooled before concentration is calculated. This avoids the invalid method of labeling a one-year research role as 100% year-dependent simply because that role contains only one year.

Metrics:

- `largest positive month net-R / total positive month net-R`;
- `largest positive year net-R / total positive year net-R`.

The system intentionally has **no guessed default** for the maximum acceptable month/year share. Both must be explicitly supplied as a valid `0 < share <= 1` Production Gate policy. Missing policy is a hard FAIL.

The Strategy Lab Gate UI now exposes:

- `Min avg NET points / ATR` (default 0.10);
- `Max positive month profit share` (blank / required);
- `Max positive year profit share` (blank / required).

### Append-only Production Value Audit

Each Gate receives a companion `production_value_audits` record keyed by `production_gate_id` and containing:

- candidate ID;
- policy + policy hash;
- D/V/H ATR/value summaries;
- month/year concentration details;
- full check list / failed checks;
- methodology;
- audit content hash.

Database triggers reject UPDATE and DELETE. Deployment requires the audit to exist, be hash-valid and be passing.

### Deployment bypass closed

The guard exists in two layers:

1. public deployment API calls `require_passing_production_value_audit()`;
2. lower-level `create_deployment_from_gate()` calls the same guard itself.

Therefore a legacy/bypass `production_gates.status='PASS'` row without P1 evidence cannot create a deployment even through a direct Python call.

Regression coverage explicitly checks that a direct deployment call missing value audit is rejected before gate context is considered.

Synthetic deployment lifecycle QA creates an explicit `SYNTHETIC_UI_FIXTURE_ONLY` audit so the fixture exercises the same core guard instead of bypassing it. That synthetic declaration is strictly UI/lifecycle plumbing and is not market evidence.

## Research-integrity hardening retained

- four-state node truth: `EVALUATED`, `NOT_REACHED`, `NOT_APPLICABLE`, `TERMINAL`;
- frozen research runs database-immutable and digest-verifiable;
- physical source row order / `_seq` truth;
- same-second original row ordering;
- campaign dataset SHA-256 pinning;
- immutable `research_run_datasets`;
- trading-day cluster bootstrap;
- BH-FDR adjusted node-edge inference;
- causal vs ex-post diagnostics separated;
- Final Holdout tuning denial;
- portfolio execution policy and overlap arbitration;
- exact D/V/H BASE execution identity before deployment.

Legacy governance mapping is retained only as the intended research plan and must be used only when the exact real files actually exist and pass integrity checks:

- 2025 → Discovery
- 2024 → Validation
- 2026 → Final Holdout

## Synthetic MTX physical-Parquet integration proof

The deterministic synthetic fixture proves software execution against a real Parquet file only.

**SYNTHETIC DATA — NOT MARKET EDGE EVIDENCE.**

Fixture contract:

- file: `MTX_2025_SYNTHETIC.parquet`
- rows: **2,101**
- row groups: **5**
- schema: `datetime, product, expiry, price, volume, side`
- source SHA-256: `b7467b2e3144aaca0a851b553aad11900b30b76a408840b5943b75dab0a4df80`
- contract: `202509`
- physical replay `_seq`: `0..2100`, strictly increasing
- research run: `synthetic-mtx-discovery-v1`
- strategy: `MR_BROAD@V3`
- seeded events: **4**
- persisted trades: **4**
- backtest run: `bt-synthetic-mtx-mr-v1`
- exits: `TARGET, STOP, TIME, TARGET`

Synthetic summary remains approximately:

- trades: 4
- wins/losses: 3/1
- win rate: 75%
- net total: +0.432R
- net expectancy: +0.108R/trade
- PF: 1.375
- Max DD: 1.152R
- average MFE: 0.490R
- average MAE: 0.270R
- average capture: 61.0%

These shaped numbers have **zero evidentiary value** for real MTX profitability.

The synthetic optimizer continues to exercise three target hypotheses (`0.50R`, `0.75R`, `1.00R`) and a persisted robustness plateau. It proves optimizer/runtime integration only.

## Important integration defects found and fixed through E2E

Synthetic/browser E2E work has exposed real defects that ordinary unit tests did not initially catch, including:

- V5 Trade Review chart using hard-coded V4 replay routes;
- Candidate Freeze selector state race;
- Candidate Evaluation job failure hidden behind successful submission UI;
- numeric execution identity canonicalization mismatch;
- spawned multiprocessing worker triggering false restart/orphan metadata;
- stale `error_text` surviving a later `SUCCEEDED` state;
- deployment path previously lacking the newly introduced Production Value guard at the lower-level function boundary.

These defects are why synthetic E2E is retained as software verification despite having no market-edge value.

## Audited P1 code-head verification

Audited code head before documentation-only closeout:

`8db68258eaa386f7f832ca02c67b17d79014764a`

GitHub Actions at that head:

- V5 Research CI run `34186312737`: **PASS**
- Browser Release QA run `34186312604`: **PASS**
- Strategy Lab Feature QA run `34186312628`: **PASS**
- Strategy Lab CI run `34186312637`: **PASS**

The Strategy Lab run also confirms:

- Strategy Lab tests including P1 Production Value and deployment regressions: PASS;
- P0 regression: PASS;
- public static build: PASS;
- synthetic MTX physical-Parquet E2E: PASS;
- synthetic deployment/lifecycle fixture under the core value-audit guard: PASS;
- reproducibility manifest: PASS;
- runtime screenshot artifact upload: PASS.

## Engineering completion is not market-edge proof

This status means the research machine can now enforce the stated software/governance/economic-value rules. It does **not** establish that MR or BO is profitable on real MTX.

No real source dataset in the active runtime has yet completed the governed D/V/H lifecycle. No real Historical↔Live parity or Paper evidence has been supplied for a candidate. Therefore:

- MR real edge: **NOT PROVEN**;
- BO real edge: **NOT PROVEN**;
- production deployment of a real strategy: **NOT AUTHORIZED BY EVIDENCE**.

## Next real-data action — P2

When the actual MTX Parquet files are available:

1. inspect schema, row count, date coverage, contract/expiry coverage and duplicate/impossible timestamps;
2. compute exact source SHA-256;
3. verify physical row ordering assumptions;
4. register and freeze campaign datasets;
5. run raw/contract/scanner/event-price sanity;
6. freeze Discovery and run formal backtests;
7. optimize Discovery only;
8. freeze candidate and explicit concentration policy;
9. run Validation with no retuning;
10. run Final Holdout with no retuning;
11. apply cost/latency/portfolio stress;
12. run P1 Production Value Audit (MR/BO reward floor + ATR >=10% + explicit month/year concentration limits);
13. only passing real evidence proceeds to parity and paper;
14. only the complete immutable evidence chain can pass Production Gate and create a deployment.

Synthetic data must never substitute for a missing real source file.

## Merge status

The branch remains **Draft / research-only** for integration review into `fabio-decision-gym-v4`. It must not be merged into `main` without explicit repository-owner approval.