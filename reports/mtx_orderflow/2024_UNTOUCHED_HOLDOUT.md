# 2024 Untouched Holdout Result

The 2024 parquet contained 50,862,751 raw transaction rows and was kept out of parameter selection before the final holdout tests.

## Frozen tests

### Tick-level Aggressive Proxy — FAIL

Frozen rule: 15s / q=0.001 / LONG / 240s / +1s after confirmation.

- N = 1,093
- Gross = +0.88 point/trade
- Net @2pt = **-1.12**
- Gross after removing top 1% winners = -0.30

This invalidates the earlier second-level proxy interpretation.

### Raw TRSV — FAIL LIVE GATE

Frozen representative rule: 20s / q=0.001 / LONG / 300s.

- Gross = +1.07
- Net @2pt = **-0.93**
- Gross after removing top 1% winners = -0.26
- night-regime Net@2 about -3.47
- high-intensity-regime Net@2 about -1.01

### Price-only — SURVIVES AS PAPER-TRADING CANDIDATE

Frozen rule: 30s price selloff / q=0.0005 / LONG / 300s.

- N = 1,179
- Gross = **+2.44**
- Net @2pt = **+0.44**
- Gross after removing top 1% winners = +0.47
- 6/9 tested contracts gross-positive
- 2024 Net@2 contract-block CI approximately `[-1.67,+2.74]`

The direction of the effect replicated, but statistical margin after a conservative 2-point cost remains insufficient for live approval.

## Holdout decision

The holdout falsified the order-flow candidates and preserved only the price-reversal hypothesis. Because 2024 has now been observed, it must not be reused as the untouched final test for any newly optimized strategy generation.
