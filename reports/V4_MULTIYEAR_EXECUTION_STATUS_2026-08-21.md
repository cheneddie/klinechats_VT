# Fabio Decision Gym V4 — 2024–2026 Multi-Year Execution Status

Date: 2026-08-21  
Branch: `fabio-decision-gym-v4`  
PR: #21  
Status: research branch only — **do not merge to `main` without explicit approval**

## 1. Source evidence now available

The project source layer now contains a corrected MTX 2024–2026 research report documenting these raw files:

| Year | Raw transaction rows | Coverage |
|---|---:|---|
| 2024 | 50,862,751 | full year |
| 2025 | 39,416,621 | full year |
| 2026 | 36,158,882 | through 2026-08-14 |

Documented raw columns:

- `datetime`
- `product`
- `expiry`
- `price`
- `volume`
- `side`

Documented immutable data semantics:

1. preserve physical Parquet row order;
2. never re-sort equal-second transactions;
3. keep MTX outright contracts only (`^\d{6}$`), remove spreads;
4. vendor volume is two-sided and normalized research volume is `volume / 2`;
5. `side` is tick-price direction, not true exchange aggressor;
6. different expiry contracts must never be joined into a return path.

These data facts are shared input semantics only.  Strategy conclusions from the separate short-horizon/order-flow report are **not** imported as Fabio V4 evidence.

## 2. Runtime boundary

At this update, the current ChatGPT execution runtime / searchable File Library does not expose the three raw Parquet file bodies as executable files.  Searches return the corrected research report and derived CSV artifacts, but not `MTX_2024.parquet`, `MTX_2025.parquet`, or `MTX_2026.parquet` as mountable raw files.

Therefore no Fabio V4 2024–2026 scanner result, edge table or performance result is fabricated from another research stream.

## 3. Important research correction: relaxed opportunity != actual strict trade

V4 reverse-node research intentionally uses a relaxed terminal opportunity universe.  This is necessary to evaluate gates without circular selection.

That research anchor cannot be reused as actual strategy execution performance.

Especially for BO:

- research terminal anchor: Pullback opportunity;
- strict strategy entry: only after `BO_RESPONSE` causally confirms.

The branch now persists a separate `strict_trade_outcomes` table built from actual `events.result='ENTRY'` and actual strict `entry_seq`.

This prevents optimistic BO performance from being measured at an earlier research-only price.

## 4. Multi-year Edge Map

`server/v4_multiyear.py` now creates a cross-year Node map from the relaxed opportunity universe.

A Node is not classified from a pooled average alone.

Per year it records:

- N / Pass / Fail;
- Δ control Avg R;
- big-loss rejection;
- ≥2R winner rejection;
- ≥3R winner rejection;
- rejected signed Total R;
- same-seq parent redundancy.

Conservative classification rules:

- fewer than two sufficient years (`n >= 50`) → `INSUFFICIENT`;
- material mixed-sign yearly effect → `REGIME_DEPENDENT`;
- high same-seq redundancy plus negligible incremental R → `REDUNDANT`;
- materially negative incremental R → `HARMFUL`;
- consistent positive multi-year contribution with loser rejection and right-tail retention → `CORE`;
- otherwise → `OPTIONAL`.

This prevents a strong year from hiding a harmful regime in another year.

## 5. Strict strategy diagnostics

Actual strict-entry results are reported separately by year and combined.

For MR the practical management basis is `fixed_1R`.

For BO the practical management basis is `fixed_2R`.

Reported metrics include:

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

Right-tail results are explicitly split between relaxed research opportunities and actual strict entries.

## 6. Execution stress

`server/v4_execution_stress.py` now computes objective cost and concentration stress from actual strict entries.

Round-trip cost grid:

- 0 points;
- 1 point;
- 2 points;
- 3 points.

For every cost level:

- Avg Net R;
- Total Net R;
- Win Rate;
- Profit Factor;
- Max Drawdown R.

It also reports:

- monthly Total R;
- yearly Total R;
- positive/negative period counts;
- largest positive-period share.

Latency is intentionally marked `PENDING_FROZEN_SPEC`.  The source requirements demand latency robustness but do not yet freeze:

- the delay-second grid;
- delayed-fill rule;
- how the original structural stop behaves after a delayed fill;
- session crossing behavior.

No favorable latency model is invented.

## 7. Complete source / contract funnel

The scanner now persists `dataset_integrity` with:

- source rows;
- MTX rows;
- outright rows;
- spread rows removed;
- outright contracts found;
- source-order QA.

It also persists `contract_selection_audit` per trading date:

- candidate contracts;
- candidate raw volume;
- normalized `volume/2`;
- selected contract;
- selected volume;
- roll state;
- ambiguity state;
- causal flag;
- selection mode;
- selection reason.

`scan_summary.json` therefore covers the complete requested funnel:

source rows → MTX rows → outright rows → spread removed → contracts found → active contracts → trading days → roll days → Auction attempts → MR / BO / WAIT → terminal opportunities → strict entries.

## 8. Clean rebuild rule

A formal diagnostic no longer layers a new scan over potentially stale events.

Default behavior:

1. preserve raw Parquet;
2. preserve `training_attempts` and research history;
3. delete selected-year rebuildable Events / Nodes / relaxed outcomes / strict outcomes / source audit / contract audit;
4. rescan the selected years from raw Parquet.

This prevents stale Events from an older scanner generation from surviving into new multi-year statistics.

## 9. Canonical multi-year run

Once the three raw Parquet files are physically available under one execution root, the canonical command is:

```bash
python tools/run_v4_diagnostic.py \
  --root <PARQUET_ROOT> \
  --db <FABIO_EVENT_DB> \
  --year 2024 \
  --year 2025 \
  --year 2026 \
  --out <RESULT_DIR>
```

The run is gated in this order:

1. clean selected-year rebuildable state;
2. raw source-order / source-funnel QA;
3. causal contract-selection audit;
4. V4.1 release scanner;
5. physical Event Sanity Gate;
6. relaxed terminal physical outcomes;
7. Reverse Node Audit;
8. Sequential Gate Contribution;
9. Ablation;
10. Trade Management / Capture;
11. actual strict-entry physical outcomes;
12. strict strategy summary;
13. right-tail summary;
14. multi-year Edge Map;
15. Production Gate.

The execution-stress API additionally exposes 0/1/2/3-point cost and concentration stress while latency policy remains frozen-spec pending.

## 10. Required output artifacts

Canonical runner outputs include:

- `provenance.json`
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
- `production_gate.json`
- `final_summary.json`

Execution stress is also exposed by:

```text
GET /api/v4/research/execution-stress
```

## 11. Production boundary

Even after 2024–2026 is computed, `live_approved` remains false by default.

A production claim still requires explicit resolution of:

- representative ATR timeframe/reference for the “average profit >= ~10% ATR” gate;
- accepted round-trip cost threshold;
- frozen latency model and latency robustness;
- maximum acceptable drawdown;
- maximum month/year concentration;
- paper/live causal parity.

The correct output is therefore evidence and gate status, not an automatic claim that a historical positive average is deployable alpha.
