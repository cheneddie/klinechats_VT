# MTX Price-Reversal Research 2024–2026

This branch is an **isolated research branch** for the MTX extreme-selloff / mean-reversion study. It is intentionally **not merged into `main`**.

## Frozen baseline strategy

- Instrument: MTX outright contracts only (`expiry` matches `^\d{6}$`)
- Preserve original physical row order; never re-sort equal-second ticks
- Signal: 30-second price selloff crossing the rolling lower 0.05% threshold
- Threshold: estimated from the immediately preceding 3 completed outright contract months only
- Direction: LONG only
- Signal confirmation: signal second must be complete
- Execution: +1 second latency after confirmation, first observed tradable print
- Position state: one position at a time
- Exit: fixed 300 seconds, first observed tradable print at/after target time
- Same-session exit only
- Main cost view: 2 points round-trip friction; stress tables include wider ranges

## Current research conclusion

The unconditional 300-second strategy shows a reproducible selloff-reversal phenomenon, but the executable edge is thin and heavily right-tail dependent. The strongest post-hoc interaction found in 2024–2026 is:

`09:00–10:30 × high causal volatility × extreme selloff`

That interaction is **not a validated production rule**. It is a post-hoc hypothesis that requires new forward OOS data.

The strategy is currently classified as:

**PAPER-TRADING / RESEARCH CANDIDATE — NOT LIVE APPROVED**

Key reasons:

- day-cluster bootstrap confidence interval crosses zero after realistic friction;
- large PnL concentration in a small number of trading days / market-event clusters;
- no production-grade structural/catastrophic stop is frozen;
- time × volatility interaction was discovered after inspecting 2024–2026;
- future forward OOS is required before promotion.

## Important verified findings

- No overlapping positions in the 3,655-trade continuous backtest; max concurrent exposure = 1 MTX.
- 2025/06 zero trades is legitimate: all sessions were present, but no 30-second selloff crossed the frozen -58 point threshold.
- 09:00–10:30 × high causal volatility showed materially better expectancy than the same time window outside high volatility.
- Right-tail concentration exists at trade, day, week, month and event-cluster levels.
- Winners typically experience early MAE and later MFE; tight fixed stops can easily cut off the strategy's right tail.
- 120–300 second holding horizons are materially more relevant than 15–60 second exits for overcoming transaction friction.

## Directory layout

- `engine/` — canonical research engine used for reproducible backtests
- `reports/` — aggregate summaries, robustness tests, regime tables, live-gate material
- `data/` — derived trade-level/path-level research outputs (no raw Parquet)
- `figures/` — equity, underwater, monthly and regime visualizations

## Raw data policy

Raw MTX Parquet files are **not committed** to GitHub. They remain external source-of-truth datasets. All committed derived files must be reproducible from those raw files and the canonical engine.

## Evidence discipline

Do not promote any post-hoc regime filter to production without a new holdout. In particular, do not rewrite the live strategy as `09:00–10:30 + high vol` using only the 2024–2026 sample.
