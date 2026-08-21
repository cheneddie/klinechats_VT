# Artifact Manifest

## Source of truth

Raw MTX parquet files are intentionally not committed. They remain external immutable source datasets. The canonical engine reconstructs deterministic second-level research caches while preserving original physical row order.

## Committed primary derived data

- `data/PriceReversal_Trades_2024_2026.csv.gz` — complete 3,655-trade continuous backtest detail used by the final diagnostics.
- `reports/backtest/*` — strategy metrics, monthly PnL, cost stress and data coverage.
- `reports/regime/*` — time-of-day, causal-volatility and interaction analysis.
- `reports/robustness/*` — concurrency, clustered right-tail, day bootstrap, daily/weekly/monthly concentration.
- `reports/path/*` — 15–300s path summaries and extrema-timing summaries.
- `reports/sanity/*` — 2025/06 zero-trade funnel proof.
- `reports/background_orderflow/*` — previous OFI/TRSV/aggressive-proxy falsification record.
- `figures/*` — lightweight GitHub-previewable SVG figures.

## Reconstructable intermediates not duplicated in Git

The full per-trade horizon matrix and full per-trade MFE/MAE extrema-timing tables are deterministic intermediates derived from the primary trade file plus the second-level cache. Their complete statistical content used for decisions is committed in `reports/path/`. They are not duplicated as multi-megabyte text files because that would add repository weight without adding a new source of truth.

## Research discipline

Do not silently overwrite historical result tables after changing strategy rules. New hypotheses should use a new version or branch and should not reuse the inspected 2024–2026 sample as a fresh holdout.
