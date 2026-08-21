# Fabio Decision Gym V4 — 2024–2026 Research Execution Status

Date: 2026-08-21  
Branch: `fabio-decision-gym-v4`  
PR: #21  
Status: research branch only — **do not merge to `main` without explicit approval**

## 1. Source evidence available

The project source layer documents these MTX raw datasets:

| Year | Raw transaction rows | Coverage | Fabio role |
|---|---:|---|---|
| 2025 | 39,416,621 | full year | Discovery / Single-Year Diagnostic |
| 2024 | 50,862,751 | full year | External Validation |
| 2026 | 36,158,882 | through 2026-08-14 | Final Holdout (YTD/partial-year) |

Documented raw columns:

- `datetime`
- `product`
- `expiry`
- `price`
- `volume`
- `side`

Immutable data semantics:

1. preserve physical Parquet row order;
2. never re-sort equal-second transactions;
3. keep MTX outright contracts only (`^\d{6}$`), remove spreads;
4. vendor volume is two-sided and normalized research volume is `volume / 2`;
5. `side` is tick-price direction, not true exchange aggressor;
6. different expiry contracts must never be joined into one return path.

These shared data facts do **not** import strategy conclusions from the separate order-flow research stream into Fabio V4.

## 2. Current execution boundary

The current ChatGPT execution runtime / searchable File Library exposes source reports and derived artifacts, but still does not expose `MTX_2024.parquet`, `MTX_2025.parquet`, or `MTX_2026.parquet` as mountable raw file bodies.

Therefore no Fabio V4 scanner, edge or strict-trade result is fabricated from another research stream. The branch is prepared to run the canonical pipeline as soon as the raw files are physically available to the runtime/local deployment.

## 3. Validation governance — do not pool all years before holdout reveal

`config/research/v4_validation_plan.json` freezes the current research roles:

```text
2025 = Discovery
2024 = Validation
2026 = Final Holdout (YTD through documented source coverage)
```

Why:

- V4 development and the original Single-Year Diagnostic were already centered on 2025, so 2025 cannot honestly be called untouched OOS.
- 2024 can test the frozen 2025-developed generation without immediately consuming 2026.
- 2026 is reserved for one-time final holdout evaluation after the candidate rules are frozen.

The diagnostic runner refuses a pooled development+holdout request by default. `--allow-holdout-reveal` exists only for an intentional post-freeze reveal; using it means 2026 has been opened for that generation.

Any material scanner/node/parameter change after inspecting 2026 Fabio results creates a new strategy generation, and 2026 is no longer final OOS for that new generation.

## 4. Relaxed research opportunity != actual strict trade

Reverse-node research intentionally uses a relaxed terminal-opportunity universe to avoid circular gate selection.

That anchor is not actual strategy execution performance.

Especially for BO:

```text
Research anchor = Pullback opportunity
Strict entry    = after BO_RESPONSE causal confirmation
```

The branch persists a separate `strict_trade_outcomes` table from actual `events.result='ENTRY'` and actual strict physical `entry_seq`.

Node/gate research therefore uses relaxed outcomes; production diagnostics use strict outcomes.

## 5. Complete source / contract audit

The scanner persists `dataset_integrity`:

- source rows;
- MTX rows;
- outright rows;
- spread rows removed;
- outright contracts found;
- source-order QA.

It also persists `contract_selection_audit` by trading date:

- candidate contracts;
- candidate raw volume;
- normalized `volume/2`;
- selected contract;
- selected volume;
- roll / ambiguity state;
- causal flag;
- selection mode and reason.

`scan_summary.json` covers the required funnel:

```text
source rows
→ MTX rows
→ outright rows
→ spread removed
→ contracts found
→ active contracts
→ trading days
→ roll days
→ Auction attempts
→ MR / BO / WAIT-invalid
→ terminal opportunities
→ strict entries
```

## 6. Clean rebuild rule

A canonical fresh diagnostic no longer layers a new scanner generation on stale SQLite events.

Default behavior:

1. raw Parquet remains untouched;
2. human `training_attempts` and research history remain preserved;
3. selected-year rebuildable Events / Nodes / relaxed outcomes / strict outcomes / source audit / contract audit are deleted;
4. selected years are rescanned from raw Parquet.

This prevents events from an older scanner generation surviving into new statistics.

## 7. Multi-Year Edge Map

`server/v4_multiyear.py` creates a cross-year Node map from the relaxed research universe.

Per year it records:

- N / Pass / Fail;
- Δ control Avg R;
- big-loss rejection;
- ≥2R winner rejection;
- ≥3R winner rejection;
- rejected signed Total R;
- same-seq parent redundancy.

Conservative classifications:

- fewer than two sufficient years (`n >= 50`) → `INSUFFICIENT`;
- material mixed-sign yearly effect → `REGIME_DEPENDENT`;
- high same-seq redundancy + negligible incremental R → `REDUNDANT`;
- materially negative incremental R → `HARMFUL`;
- consistent positive contribution with loser rejection and right-tail retention → `CORE`;
- otherwise → `OPTIONAL`.

Before final holdout reveal, production-node selection should use **2025 + 2024 only**.

## 8. Strict strategy diagnostics

Actual strict-entry results are reported by year and combined.

Practical management bases:

```text
MR = fixed_1R
BO = fixed_2R
```

Reported metrics:

- N;
- Avg / Median / Total R;
- Win Rate;
- Profit Factor;
- Max Drawdown R;
- practical target hit rate;
- 1R / 2R / 3R / 5R hit rates;
- Avg / Median MFE R;
- P90 / P95 / Max MFE R;
- Avg winner points.

Right-tail evidence is explicitly split into relaxed research opportunities versus actual strict entries.

## 9. Stratified Edge Report

`server/v4_stratified.py` prevents pooled averages from hiding concentration.

Strict strategy results are segmented by:

- month;
- direction;
- intraday detection window:
  - 08:45–09:00
  - 09:00–09:30
  - 09:30–10:30
  - 10:30–11:30
  - 11:30–13:45
- auction side;
- Value Width quartile;
- excursion quartile;
- LVN depth quartile.

Each segment includes N, Avg R, Total R, PF, Win Rate, MFE, MAE and 1R/2R/3R/5R rates.

Node research also gets monthly consistency: per-month N / Pass / Fail / Δ control Avg R and sign consistency.

The current event schema does not yet persist a frozen causal volatility/trend/range regime, so those are reported as unavailable instead of inferred after seeing outcomes. Current V4 signal detection is day session only; no night-detection result is invented.

## 10. Execution stress

`server/v4_execution_stress.py` runs objective strict-entry round-trip cost stress at:

```text
0 / 1 / 2 / 3 points
```

For each cost level:

- Avg Net R;
- Total Net R;
- Win Rate;
- Profit Factor;
- Max Drawdown R.

It also reports monthly/yearly concentration and the largest positive-period share.

Latency remains `PENDING_FROZEN_SPEC` until these rules are frozen:

- delay-second grid;
- delayed-fill rule;
- structural-stop behavior after delayed fill;
- session-crossing behavior.

No favorable latency assumption is invented.

## 11. Canonical role-separated execution

### Stage A — Discovery: 2025

```bash
python tools/run_v4_diagnostic.py \
  --root <PARQUET_ROOT> \
  --db <FABIO_EVENT_DB> \
  --year 2025 \
  --out <RESULT_ROOT>/2025-discovery
```

Review Event Sanity, manual replay samples, Reverse Audit, Sequential Contribution, Ablation, strict performance, right tail, strata and execution stress. Fix scanner/event bugs before proceeding.

### Stage B — Validation: 2024

After the candidate generation is frozen enough to validate:

```bash
python tools/run_v4_diagnostic.py \
  --root <PARQUET_ROOT> \
  --db <FABIO_EVENT_DB> \
  --year 2024 \
  --out <RESULT_ROOT>/2024-validation
```

Then a descriptive development Edge Map may be created from **2024+2025 only** using the already-built event DB (`--skip-scan`) or APIs. Do not add 2026 yet.

### Stage C — Freeze candidate

Freeze:

- scanner generation;
- Node set;
- strategy parameters;
- execution assumptions that are actually specified;
- production candidate definition.

### Stage D — Final Holdout: 2026

Only after Stage C:

```bash
python tools/run_v4_diagnostic.py \
  --root <PARQUET_ROOT> \
  --db <FABIO_EVENT_DB> \
  --year 2026 \
  --out <RESULT_ROOT>/2026-final-holdout
```

This opens the current 2026 Fabio holdout. Coverage is partial-year/YTD according to the documented source.

### Stage E — post-holdout descriptive all-years report

After intentional reveal, an all-years report may be generated with the explicit override:

```bash
python tools/run_v4_diagnostic.py \
  --root <PARQUET_ROOT> \
  --db <FABIO_EVENT_DB> \
  --year 2024 --year 2025 --year 2026 \
  --skip-scan \
  --allow-holdout-reveal \
  --out <RESULT_ROOT>/post-holdout-all-years
```

That pooled output is descriptive evidence, **not** a new parameter-optimization dataset.

## 12. Canonical runner outputs

- `provenance.json`
- `validation_plan.json`
- `progress.json`
- `rebuild_cleanup.json`
- `scan_summary.json`
- `event_sanity.json`
- `reverse_audit.json`
- `reverse_audit.csv`
- `sequential_gate_contribution.json`
- `ablation.json`
- `management_capture.json`
- `strict_trade_summary.json`
- `right_tail.json`
- `multi_year_edge_map.json`
- `stratified_edge.json`
- `execution_stress.json`
- `production_gate.json`
- `final_summary.json`

Research API also exposes strict summary, right tail, Multi-Year Edge Map, stratified edge, execution stress and production-gate views.

## 13. Production boundary

Even with positive historical results, `live_approved` remains false by default.

A live claim still requires explicit resolution of:

- representative ATR timeframe/reference for the “average profit >= ~10% ATR” gate;
- accepted round-trip cost threshold;
- frozen latency model + latency robustness;
- maximum acceptable drawdown;
- maximum month/year concentration;
- Historical ↔ Live causal parity;
- signal opportunity versus execution opportunity versus actual-fill assumptions.

The correct output is evidence and Gate status—not an automatic claim that a positive historical average is deployable alpha.
