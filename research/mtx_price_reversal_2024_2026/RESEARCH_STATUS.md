# Research Status — MTX Extreme Selloff Reversal

## Status

**NOT LIVE APPROVED**

The baseline price-reversal signal exists, but the current executable strategy remains too fragile for live deployment without further forward validation and risk-rule design.

## Baseline continuous backtest (2024–2026)

- Trades: 3,655
- Net@2 total: +5,104 points
- Net@2 expectancy: +1.40 points/trade
- PF: 1.059
- Daily annualized Sharpe: 0.838
- Daily annualized Sortino: 1.252
- Max drawdown: -3,086 points
- Recovery factor: 1.654
- Max consecutive losing trades: 8
- Time in market: ~2.83%
- Max concurrent positions: 1

## Important structural findings

### 1. Time-of-day interaction

`09:00–10:30` produced +6,054 points over 1,188 trades, while all other periods combined lost -950 points. However, further decomposition showed that the effect is strongly conditional on causal volatility.

### 2. Time × volatility interaction

Using only past completed sessions to define volatility percentile:

- `09:00–10:30 × High Vol`: 740 trades, PF ~1.32, expectancy ~+8.14 points
- same time window outside High Vol: near flat, PF ~1.00, expectancy near zero

This is a **post-hoc hypothesis**, not a frozen production rule.

### 3. Right-tail concentration

- Top 1% of trades contributes more than total strategy PnL.
- Top 5 trading days contribute ~85% of total PnL.
- Event clusters also explain a large fraction of PnL.
- Day-cluster bootstrap Net@2 expectancy CI crosses zero.

### 4. Path behavior

- Final winners often show early MAE, then reach MFE late in the 300-second window.
- Final losers often show a small early bounce before deteriorating.
- Top 1% winners can have large early adverse excursion, so naive tight stops are dangerous.

### 5. 2025/06 zero-trade sanity check

The zero-trade month is valid. Data coverage and scanner eligibility were present; the most extreme 30-second decline did not cross the frozen threshold.

## Next research gates

1. New forward OOS for the post-hoc `09:00–10:30 × High Vol` hypothesis.
2. Define a causal structural stop and an independent catastrophic risk stop.
3. Re-test right-tail retention after any stop/trailing rule.
4. Continue day/event-cluster inference rather than treating 3,655 trades as fully independent observations.
5. Maintain one-position-at-a-time execution and exact first-tradable-print logic.
