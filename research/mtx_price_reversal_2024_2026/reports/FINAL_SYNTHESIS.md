# MTX 2024–2026 Extreme-Selloff Reversal — Final Synthesis

## Frozen baseline

30-second extreme downside price move crossing the rolling lower 0.05% threshold trained only on the previous 3 completed outright contracts; long only; complete-second confirmation; one additional second latency; first tradable print; one position at a time; fixed 300-second same-session exit. Primary stress view uses 2 points round-trip friction.

## Continuous strategy backtest

Across 2024–2026 supplied data:

- Trades: 3,655
- Net@2 total: +5,104 points
- PF: 1.059
- Net@2 expectancy: +1.396 points/trade
- Daily annualized Sharpe: 0.838
- Daily annualized Sortino: 1.252
- Max DD: -3,086 points
- Recovery factor: 1.654
- Max consecutive losses: 8
- Max concurrent positions: 1
- Time in market: ~2.83%

The unconditional strategy is therefore positive but thin after friction.

## Key discovery 1 — the edge is not uniformly intraday

The 09:00–10:30 window generated +6,054 Net@2 points across 1,188 trades, while all other periods combined lost -950 points. However, a causal-volatility interaction shows that time alone is not the whole explanation.

Using only past completed sessions to define volatility percentile:

- `09:00–10:30 × high causal volatility`: N=740, PF≈1.320, expectancy≈+8.136 pt/trade, PnL≈+6,021.
- `09:00–10:30 × not high volatility`: N=448, PF≈1.004, expectancy≈+0.074, PnL≈+33.
- high volatility outside 09:00–10:30: positive in aggregate but much weaker and not stable by year.

Interpretation: the strongest hypothesis is an interaction among extreme selloff, early-day auction state and high volatility. This is post-hoc and requires new forward OOS.

## Key discovery 2 — no exposure stacking bug

Concurrency audit found 0 overlapping trades and maximum concurrent exposure of 1 MTX. The large trade count is therefore not created by simultaneous stacking. Event clustering still exists because many new entries occur shortly after the prior 300-second trade exits.

## Key discovery 3 — right-tail/event concentration is material

- Best trading day: +978 points.
- Top 3 days: +2,801 points (~54.9% of total PnL).
- Top 5 days: +4,343 points (~85.1%).
- Best week: +1,435 points.
- Best month: +1,681 points.
- At a 300-second post-exit clustering rule, top 5 event clusters contribute ~71.5% of total PnL.
- Day-cluster bootstrap 95% CI for Net@2 expectancy is approximately [-0.90, +3.78], crossing zero.

Removing a single best day or best month does not immediately kill the strategy, but effective independent sample size is far smaller than 3,655 trades.

## Key discovery 4 — the reversal is slow

Combined average PnL by horizon before friction:

- 15s: +0.65
- 30s: +1.80
- 60s: +0.94
- 90s: +1.63
- 120s: +2.53
- 180s: +2.73
- 240s: +2.53
- 300s: +3.40

After 2-point friction, 15–90 seconds are not enough on average. The strategy needs roughly 120 seconds or more to overcome friction in this sample.

Path timing is asymmetric:

- final winners: median time-to-MAE ≈27s; median time-to-MFE ≈234s;
- final losers: median time-to-MFE ≈39s; median time-to-MAE ≈228s;
- top 1% winners: median time-to-MAE ≈6s; median time-to-MFE ≈288s.

This strongly warns against naive tight fixed stops: important winners often move adversely immediately after entry before producing their large favorable tail late in the holding window.

## Key discovery 5 — 2025/06 zero trades is valid

All 42 June sessions were present and eligible. The frozen threshold was roughly -58 points over 30 seconds, while the month's most extreme 30-second decline was only -51. Therefore there were zero threshold crossings and zero trades; this is not a data or scanner failure.

## Live decision

**NOT LIVE APPROVED.**

Reasons:

1. after-friction PF is only ~1.06 for the unconditional baseline;
2. day-cluster bootstrap confidence interval crosses zero;
3. PnL is concentrated in a small number of high-value market days / event clusters;
4. there is no frozen structural stop plus independent catastrophic stop;
5. the strongest `09:00–10:30 × high-vol` result is post-hoc and cannot be promoted using the already-inspected sample;
6. any stop/trailing design must prove it retains the strategy's late right tail.

## Next valid research step

Freeze a next-generation hypothesis before obtaining new data. The highest-value candidates are:

- entry-side regime classification: high-volatility early-session reversal state;
- post-entry 30–60 second path state as a causal classifier of emerging right-tail winners versus deteriorating losers;
- structural invalidation and catastrophic risk limits designed from market logic rather than arbitrary tight point stops.

Any such version requires genuinely new forward OOS before it can be considered for live deployment.
