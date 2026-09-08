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
- P2 REAL MTX INTAKE / CAMPAIGN / PROVENANCE: **PASS (IMPLEMENTATION READINESS)**
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
10. **Real MTX Intake / Governance** — streaming Parquet source audit, exact SHA-256, physical timestamp-order validation, Real campaign registration/freeze policy, immutable intake provenance and D/V/H Real-vs-legacy consistency checks.

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

## P2 Real MTX Intake / campaign / provenance closeout

P2 now provides a fail-closed source-governance path for real MTX Parquet files before any file can be trusted as Discovery / Validation / Final Holdout evidence.

### Streaming source intake

Implemented in `server/v5/data_intake.py` with CLI wrapper `tools/real_mtx_intake.py`.

The intake scanner:

- opens a physical Parquet file through PyArrow;
- records exact file SHA-256;
- records Parquet schema, row count, row-group count and row-group totals;
- requires `datetime, product, expiry, price, volume, side`;
- scans in physical source order without sorting;
- rejects unparseable timestamps;
- rejects physical timestamp reversals instead of silently sorting them away;
- requires real MTX outright rows;
- rejects invalid MTX outright price / volume rows;
- requires day-session MTX outright presence;
- reports product / expiry / side distributions;
- reports timestamp-year distribution and expected-year share;
- reports same-second physical run density;
- reports day-session dominant/front contract summaries and roll changes;
- rejects synthetic-like source filenames by default.

`--allow-synthetic` exists only for explicit QA fixture usage and does not convert synthetic data into market evidence.

### Timestamp-resolution defect found and closed

P2 CI exposed a real Pandas/PyArrow compatibility defect: Parquet `timestamp(ms)`, `timestamp(us)` and `timestamp(ns)` can retain different pandas datetime resolutions, so treating raw `int64` values as nanoseconds can corrupt same-second grouping.

The implementation now normalizes with:

`DatetimeIndex(...).as_unit("ns").asi8`

Regression requires physically equivalent `timestamp(ms)`, `timestamp(us)` and `timestamp(ns)` fixtures to produce identical same-second statistics. This bug was fixed in the core implementation rather than hidden by changing test expectations.

### Real campaign policy

`server/v5/campaigns.py` adds `REAL_MTX_INTAKE_V1` governance.

A campaign created as a Real MTX campaign cannot be frozen unless every registered dataset contains a valid Real MTX intake record with:

- `status=PASS`;
- no failed intake checks;
- non-synthetic source identity;
- matching source file;
- matching dataset year;
- matching SHA-256;
- valid intake report hash;
- `source_class=REAL_MTX`;
- `dataset_evidence_policy=REAL_MTX_INTAKE_V1`.

A direct low-level `register_campaign_dataset()` call with a hand-entered SHA cannot bypass this at campaign freeze. Tampered intake JSON or report hash also prevents freeze.

After campaign freeze, existing SQLite triggers prevent INSERT / UPDATE / DELETE of `campaign_datasets`, preserving source evidence immutability even against direct SQL writes.

### Candidate / Gate Real provenance

`server/v5/real_mtx_provenance.py` verifies Candidate D/V/H source provenance.

Rules:

- a fully Real candidate requires Discovery, Validation and Final Holdout all to use `REAL_MTX_INTAKE_V1` campaigns;
- every role re-verifies dataset source class, intake policy, SHA, file, year and report hash;
- mixing Real and legacy campaign evidence is a hard provenance failure;
- purely synthetic/legacy engineering fixtures remain usable for software QA but are explicitly not Real MTX market evidence;
- Production Value audit carries a `REAL_MTX_INTAKE_PROVENANCE` check so the Real-source decision is frozen with Gate evidence.

This closes the path where a Real campaign might pass intake initially but later reach Gate with mismatched or mixed provenance.

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
- exact D/V/H BASE execution identity before deployment;
- Real MTX intake / campaign / provenance policy before real-data promotion.

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

Synthetic/browser/E2E/Intake work has exposed real defects that ordinary unit tests did not initially catch, including:

- V5 Trade Review chart using hard-coded V4 replay routes;
- Candidate Freeze selector state race;
- Candidate Evaluation job failure hidden behind successful submission UI;
- numeric execution identity canonicalization mismatch;
- spawned multiprocessing worker triggering false restart/orphan metadata;
- stale `error_text` surviving a later `SUCCEEDED` state;
- deployment path previously lacking the newly introduced Production Value guard at the lower-level function boundary;
- Pandas/PyArrow timestamp-resolution mismatch corrupting same-second source statistics.

These defects are why synthetic E2E and intake fixtures are retained as software verification despite having no market-edge value.

## Audited final P2 code-head verification

Audited P2 code head before documentation-only closeout:

`5a748ae525069e6fc5468ea5ff792c004009b9db`

GitHub Actions at that head:

- V5 Research CI run `34188426699`: **PASS**
- Browser Release QA run `34188426646`: **PASS**
- Real MTX Intake CI run `34188426622`: **PASS**
- Strategy Lab Feature QA run `34188426616`: **PASS**
- Strategy Lab CI run `34188426649`: **PASS**

The Strategy Lab run also confirms:

- Strategy Lab tests with dedicated P1 Production Value + P2 Intake/campaign/provenance regressions: PASS;
- P0 regression: PASS;
- public static build: PASS;
- synthetic MTX physical-Parquet E2E: PASS;
- strict Chrome feature QA: PASS;
- reproducibility manifest: PASS;
- runtime screenshot artifact upload: PASS.

At that code head, the branch was **205 commits ahead / 0 behind** `fabio-decision-gym-v4`, with merge base `5c12e8fe810184220d5bf15f215855f12b6030e8`.

## Engineering completion is not market-edge proof

This status means the research machine can now enforce the stated software/governance/economic-value/source-integrity rules. It does **not** establish that MR or BO is profitable on real MTX.

No real source dataset in the active runtime has yet completed the governed D/V/H lifecycle. No real Historical↔Live parity or Paper evidence has been supplied for a candidate. Therefore:

- MR real edge: **NOT PROVEN**;
- BO real edge: **NOT PROVEN**;
- production deployment of a real strategy: **NOT AUTHORIZED BY EVIDENCE**.

## Next real-data action

When the actual MTX Parquet files are available:

1. run `tools/real_mtx_intake.py` on each physical source file;
2. reject any source that fails schema, physical ordering, timestamp, MTX outright, price/volume, session, synthetic-source or expected-year checks;
3. preserve exact source SHA-256 and intake report hash;
4. create a `REAL_MTX_INTAKE_V1` research campaign;
5. register the real source through the governed Real MTX registration path and freeze the campaign;
6. run raw/contract/scanner/event-price sanity;
7. freeze Discovery and run formal backtests;
8. optimize Discovery only;
9. freeze candidate and explicit concentration policy;
10. run Validation with no retuning;
11. run Final Holdout with no retuning;
12. apply cost/latency/portfolio stress;
13. run P1 Production Value Audit (MR/BO reward floor + ATR >=10% + explicit month/year concentration limits) with Real MTX provenance attached;
14. only passing real evidence proceeds to parity and paper;
15. only the complete immutable evidence chain can pass Production Gate and create a deployment.

Synthetic data must never substitute for a missing real source file.

## Merge status

The branch remains **Draft / research-only** for integration review into `fabio-decision-gym-v4`. It must not be merged into `main` without explicit repository-owner approval.