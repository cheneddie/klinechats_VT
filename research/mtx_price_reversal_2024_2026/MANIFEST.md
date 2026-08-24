# Artifact Manifest — 2026-08-24 Research Snapshot

## Source of truth

Raw MTX parquet files are intentionally not committed. They remain external immutable source datasets.

Large second-level caches used to derive causal features are deterministic/reconstructable and are not committed because they are repository-heavy intermediates:

- `causal_candidate_session_seconds.csv` (~144 MB)
- `causal_candidate_session_flow_seconds.csv` (~132 MB)
- row-group checkpoint directories used for raw extraction

Their integrity was validated by exact execution parity and flow/price key identity. The decision-relevant outputs and compact audit tables are committed.

## Canonical historical source already committed

- `data/PriceReversal_Trades_2024_2026.csv.gz` — continuous 3,655-trade baseline source used by prior diagnostics.
- `reports/backtest/*`
- `reports/regime/*`
- `reports/robustness/*`
- `reports/path/*`
- `reports/sanity/*`
- `reports/background_orderflow/*`
- `figures/*`

## Current frozen / primary snapshot artifacts

Under `reports/current/` and `data/current/`:

- Frozen Forward-OOS V1 specification / hashes
- 1,112-trade frozen candidate ledger
- ACCEL30 ledger
- R3-lite (`ACCEL30 + Repeat5/45`) ledger
- pre-state eligible-event ledger
- overlap/repeated-signal audit
- cost / quantile / HighVol / path robustness tables
- tail-risk diagnostics and sensitivity tables
- causal price/flow AUC and calibration tables
- threshold breach timing diagnostics
- risk-grade and forward-calibration outputs
- flow-gated FAIL180 bootstrap outputs

## Current status/plan documents

- `RESEARCH_STATUS.md`
- `reports/current/NEXT_PHASE_PLAN_2026-08-24.md`
- `reports/current/EVIDENCE_LEDGER_2026-08-24.md`
- `reports/current/FORWARD_GATES_2026-08-24.md`
- `reports/current/CATASTROPHE_WATCH_SPEC_2026-08-24.md`

## Reconstructable intermediates intentionally not duplicated in Git

The following are not new sources of truth and are intentionally excluded from the repository due to weight:

- ~144 MB candidate-session price-second cache
- ~132 MB candidate-session flow-second cache
- row-group checkpoint CSV directories
- other temporary extraction checkpoints

These can be rebuilt deterministically from the raw parquet files with the preserved physical-row-order contract. Their decision-relevant statistics and audit outputs are committed.

## Research discipline

1. Do not commit raw MTX source data.
2. Do not silently overwrite historical result tables after changing strategy rules.
3. Do not reopen `REJECTED — DO NOT RETUNE` parameter spaces on the inspected 2024–2026 sample.
4. A changed rule gets a new version and a new forward clock.
5. New valid OOS evidence must be strictly after `2026-08-14 13:44:59`.
