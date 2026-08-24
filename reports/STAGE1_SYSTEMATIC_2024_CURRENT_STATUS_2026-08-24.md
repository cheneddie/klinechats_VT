# Stage 1 Systematic Futures Baselines — Current Status & Next Plan

**Date:** 2026-08-24  
**Branch:** `fabio-decision-gym-v4`  
**Research track:** systematic price/volume baselines (separate from the Fabio V4 node-validation campaign)  
**Evidence level:** 2024 single-year diagnostic + adversarial reassessment; **not OOS validation and not production approval**.

## 1. Executive state

Production-approved strategies: **0**.

Current Kill / Keep decision:

| Family | Decision | Meaning |
|---|---|---|
| Naked ORB | **KILL** | Stop optimizing as a standalone strategy |
| Failed Breakout price-only | **KILL as standalone** | Retain only as a market-state / feature label |
| Baseline VWAP Z2.5 mean reversion | **KILL as standalone** | Retain only as an OOS hypothesis source |
| Large-gap conditioned OR15 breakout | **PRIMARY FROZEN OOS CANDIDATE** | No more 2024 tuning; test unchanged on untouched year |
| Regime-filtered VWAP | **SECONDARY OOS-ONLY** | No more 2024 tuning; only independent-year falsification allowed |

The correct next action is **not more 2024 optimization**. The correct next action is to freeze the surviving hypotheses and test them unchanged on an untouched year.

## 2. Data QA actually completed

Source used in this Stage 1 run: `MTX_2024(2).parquet`.

Verified facts:

- raw rows: **50,862,751**
- product: MTX
- outright rows: **50,862,689**
- spread/combo rows removed: **62**
- day-session front-contract 1-minute bars: **72,156**
- trading days: **241**
- session: **08:45–13:45**, last observed minute 13:44
- strict calendar front contract present: **241 / 241** day-session days
- non-outright expiry strings such as spread/combo identifiers were observed in the real file and excluded
- raw Parquet physical ordering was preserved; no tick re-sort was used

Physical-entry verification:

- 30 random entry bars were traced back to original physical `seq_first`
- result: **30 / 30 exact match**
- 13 trades had same-1m stop/target ambiguity
- all 13 were re-resolved from physical tick order
- target-first: **5**
- stop-first: **8**

This is important because minute OHLC alone cannot determine path ordering when stop and target are both touched in the same bar.

## 3. Baseline rules tested

### 3.1 ORB

- Opening ranges: 5 / 15 / 30 / 60 minutes
- signal: first 1m close outside the opening range before 11:30
- entry: next 1m open
- stop: 0.5x or 1.0x opening-range width behind breakout level
- target: 2R
- exit: stop / target / 13:40

### 3.2 Failed Breakout

- level: OR15 high / low
- excursion: at least `max(2 points, 10% OR width)`
- reclaim windows: 1 / 3 / 5 / 10 minutes
- entry: next minute open after reclaim
- stop: failure extreme + 1 point
- target: 1R
- exit: stop / target / 13:40

### 3.3 VWAP Mean Reversion

- session trade VWAP and weighted sigma from raw trade price × volume
- tested signal thresholds: z = 1.5 / 2.0 / 2.5 / 3.0
- signal window: 09:15–12:30
- entry: next minute open
- stop: `(signal z + 1) sigma` from frozen signal VWAP
- target: frozen signal-time VWAP
- require planned RR >= 1
- exit: stop / target / 13:40

## 4. Baseline results after physical-path correction

| Strategy | Config | N | Gross Avg R | PF | 1pt Avg R | 2pt Avg R | Positive months |
|---|---|---:|---:|---:|---:|---:|---:|
| VWAP MR | Z2.5 / stop Z3.5 / target VWAP | 92 | +0.2149 | 1.3339 | +0.1236 | +0.0323 | 8/12 |
| Failed Breakout | OR15 / 3m reclaim / 1R | 215 | +0.0670 | 1.1441 | +0.0200 | -0.0271 | 5/12 |
| ORB | OR15 / 0.5OR stop / 2R | 237 | +0.0266 | 1.0415 | +0.0002 | -0.0262 | 7/12 |
| ORB | OR60 / 1OR stop / 2R | 196 | +0.0122 | 1.0431 | +0.0044 | -0.0034 | 5/12 |

The 1pt / 2pt figures are friction stress scenarios, not claims that actual all-in transaction cost equals exactly 1 or 2 points.

## 5. Why the three baseline families were killed

### 5.1 Naked ORB — KILL

Best naked baseline OR15 / 0.5OR / 2R:

- N = 237
- gross AvgR = +0.0266
- 1pt AvgR = +0.0002
- 2pt AvgR = -0.0262

Quarterly adaptive selection using the best prior-quarter ORB configuration produced **-0.0980R/trade at 1pt friction** on the following quarter.

Conclusion: the naked rule family does not show a robust standalone edge. No further 2024 micro-parameter tuning is allowed.

### 5.2 Failed Breakout price-only — KILL as standalone

Best 3m reclaim baseline:

- N = 215
- gross AvgR = +0.0670
- 1pt AvgR = +0.0200
- 2pt AvgR = -0.0271

Quarterly adaptive selection produced **-0.1116R/trade at 1pt friction** in subsequent quarters.

Regime rescue attempts (RVOL, gap, OR width, time, etc.) did not survive multiple-testing correction; 2pt reality-check p was approximately **0.74**.

Conclusion: Failed Breakout can remain a state/feature describing market behavior, but it is not a usable standalone entry system on this evidence.

### 5.3 Baseline VWAP Z2.5 — KILL as standalone

Baseline:

- N = 92
- gross AvgR = +0.2149
- 1pt AvgR = +0.1236
- 2pt AvgR = +0.0323

Adversarial findings:

- median trade = **-1R**
- maximum losing streak = **12**
- gross max drawdown ≈ **-16.7R**
- top 5 winners contributed approximately **99% of total gross R**
- quarterly adaptive parameter selection produced **-0.2307R/trade at 1pt friction** on following quarters
- broad selection-adjusted VWAP search: 2pt reality-check p ≈ **0.80**

Conclusion: the baseline result is too right-tail-dependent and unstable to remain a production candidate.

## 6. The one primary survivor: Large-Gap conditioned OR15 breakout

### Frozen causal rule

Define:

`gap_ratio = abs(session_open - previous_close) / prior_ATR14`

Trade only when today's `gap_ratio` is greater than the **rolling median of the prior 60 completed sessions' gap_ratio**. No current-day future information is used in this gate.

Frozen central candidate:

- market: MTX day session
- opening range: 08:45–08:59 (OR15)
- gate: large-gap condition above
- signal: first 1m close outside OR15 before 11:30
- entry: next 1m open
- stop: 1.0 × OR15 width behind breakout level
- target: 2R
- exit: stop / target / 13:40
- no further 2024 tuning permitted

### 2024 internal evidence

- N = **108**
- gross AvgR ≈ **+0.3030**
- 1pt AvgR ≈ **+0.2898**
- 2pt AvgR ≈ **+0.2765**
- gross PF ≈ **1.62**
- 2pt total ≈ **+29.87R**
- 2pt max DD ≈ **-10.0R**
- H1 2pt AvgR ≈ **+0.4545**
- H2 2pt AvgR ≈ **+0.1445**
- average 2pt-net points ≈ **+27.3 points/trade**
- average 2pt-net points / ATR ≈ **8.1%**

It still fails the project's practical production-value preference of roughly **>=10% ATR per trade**.

### Parameter plateau evidence

For OR15, stop = 1OR, target = 2R, with the gate defined using prior-60 rolling gap-ratio quantiles, 2pt AvgR remained positive across a broad threshold region:

| Rolling gap threshold | H1 2pt AvgR | H2 2pt AvgR |
|---|---:|---:|
| q40 | +0.396 | +0.053 |
| q50 | +0.454 | +0.144 |
| q60 | +0.239 | +0.103 |
| q70 | +0.271 | +0.213 |
| q80 | +0.274 | +0.304 |

This plateau is the strongest evidence found in Stage 1.

### Why it is still NOT validated

- Q1 and Q3 were negative; Q2 and Q4 were strongly positive
- H2 bootstrap confidence interval still crosses zero
- the hypothesis was found after searching many ORB/filter variants
- after approximately 130 searched ORB parameter/filter variants, 2pt selection-adjusted reality-check p ≈ **0.45**
- the 8.1% ATR practical-value result remains below the 10% target

Therefore status is strictly:

**PRIMARY FROZEN OOS CANDIDATE — NOT PRODUCTION-APPROVED.**

## 7. Secondary survivor: regime-filtered VWAP

Example discovered on 2024: Z2.5 with opening-drive opposed to the mean-reversion direction.

Descriptive 2024 metrics:

- N = 49
- gross AvgR ≈ +0.5461
- 1pt AvgR ≈ +0.4824
- 2pt AvgR ≈ +0.4187

However it is post-hoc, small-sample, and still right-tail dependent. The broader VWAP search family did not survive selection-adjusted testing.

Status:

**SECONDARY OOS-ONLY HYPOTHESIS.**

No additional 2024 tuning is permitted.

## 8. Statistical / practical gates already applied

The following checks were completed before the Kill / Keep decision:

1. physical-tick stop/target path resolution
2. friction stress at 0 / 1 / 2 points where reported
3. H1 vs H2 split
4. monthly and quarterly stability inspection
5. parameter-selection walk-forward test
6. right-tail / outlier concentration
7. maximum losing streak and drawdown inspection
8. bootstrap confidence intervals
9. one-factor causal regime-rescue tests
10. parameter-plateau search
11. multiple-testing / reality-check adjustment after searching variants
12. practical-value comparison of average PnL points versus ATR

## 9. Research governance from this point forward

### Locked / forbidden on 2024

Do not:

- optimize OR length further
- optimize gap q50 into arbitrary q53/q57-style thresholds
- stack multiple post-hoc filters to beautify 2024
- change stop/target after seeing 2024 OOS-like split behavior
- turn directional or time-of-day descriptive findings into claimed edge using the same 2024 sample
- lower the production-value gate merely because a candidate is close

### Allowed next work

Only:

1. serialize/freeze candidate definitions and hashes
2. run identical rules on untouched year(s)
3. compare OOS results to pre-declared pass/fail gates
4. if OOS passes, then promote to Stage 2 enrichment tests
5. if OOS fails, kill the family according to the rules below

## 10. Next phase plan

### Phase 2A — Frozen OOS falsification

Primary candidate:

`Large-Gap × OR15 × 1OR Stop × 2R Target`

Secondary candidate:

`VWAP Z2.5 + frozen regime condition`

Test on an untouched full year. The same rule must be applied with no re-optimization.

Required outputs:

- trades
- gross / 1pt / 2pt expectancy
- PF
- max DD
- losing streak
- monthly distribution
- H1/H2
- long/short split
- time-of-day split
- bootstrap 95% CI
- PnL-point / ATR capture
- concentration of top 5 / top 10 winners
- execution ambiguity count resolved from physical tick path

### Phase 2B — Pre-declared pass/fail gates

Primary candidate advances only if the untouched year shows, at minimum:

- gross and realistic-friction AvgR remain positive
- PF meaningfully above 1 (target research threshold: >1.2, not a production guarantee)
- no single month or tiny set of trades explains the majority of the year's result
- H1/H2 are not directionally contradictory
- physical-path QA passes
- average point expectancy materially improves toward the ~10% ATR practical-value target
- parameter logic remains causal and unchanged

Immediate kill conditions:

- 2pt AvgR <= 0
- result depends on one or two extreme winners
- strong negative OOS half-year without compensating broad consistency
- large deterioration caused by physically correct path resolution
- OOS success requires changing the frozen rule

### Phase 2C — Only after OOS pass: enrichment A/B

If and only if the primary frozen candidate survives OOS, compare:

- price/regime baseline
- + Volume Profile location
- + LVN/HVN/POC/VAH/VAL features
- + tick-direction proxy features (explicitly not true aggressor CVD)
- + true order-flow features only when true Bid/Ask/MBO-quality data exists

The goal is to quantify incremental edge rather than assume more microstructure features are better.

### Phase 2D — Multi-year / final holdout

After a successful independent-year test:

- freeze the promoted specification again
- test multiple years without pooling for optimization
- reserve a final holdout
- run cost/latency stress
- run concentration and right-tail audits
- only then consider paper/live parity testing

## 11. Relationship to Fabio Decision Gym V4

This Stage 1 systematic-baseline track is complementary to, but distinct from, the Fabio V4 research pipeline.

Fabio V4 studies causal Auction / Failed Auction / Accepted Breakout / Volume Profile / LVN decision nodes and their incremental value. Stage 1 asks a lower-level question first:

> Can simple price/volume/regime rules produce a reproducible edge before adding richer discretionary/microstructure structure?

Current answer from 2024:

- simple naked baselines: mostly **no**
- one causal regime-conditioned ORB hypothesis: **worth one untouched-year falsification test**
- no production-approved strategy yet

## 12. Repository evidence files

See `reports/stage1_2024/` for:

- `STAGE1_2024_REAL_DIAGNOSTIC.md`
- `STAGE1_2024_REASSESSMENT.md`
- `stage1_summary_2024_physical_resolved.csv`
- `stage1_trades_2024_physical_resolved.csv` (or its repository multipart compressed representation)
- `stage1_bootstrap_2024_physical_resolved.csv`
- `stage1_2024_reassessment_key_metrics.csv`
- `minute_qa_2024.json`
- `stage1_validation_2024.json`
- reproducibility scripts
- `MANIFEST.md`

Raw Parquet is intentionally not committed; it remains the source data outside GitHub.
