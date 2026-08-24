# MTX Order-Flow / Price-Reversal Research — Final Corrected Report

## Executive decision

After correcting data decoding, execution timing, crossing semantics, session boundaries, cache duplication, and the aggressor proxy definition, the evidence does **not** support a live MTX order-flow strategy from the supplied transaction files.

The surviving phenomenon is a price-only mean-reversion effect after very extreme short-horizon selloffs. It survives an untouched 2024 directional test, but not the conservative live gates at a 2-point round-trip cost.

Final status:

- Second-level aggressive proxy: INVALIDATED
- Tick-level aggressive proxy: REJECT
- Raw TRSV: REJECT FOR LIVE
- TRSV Night / High-Intensity regimes: REJECT
- Price-only 30s / lower 0.05% / 300s: PAPER-TRADING CANDIDATE
- Live approval: NO

## Data semantics

Raw files: MTX 2024, 2025, 2026 transaction parquet.

Required invariants:

- preserve original physical row order;
- same-second rows are never re-sorted;
- outright expiry only: ^\d{6}$;
- vendor volume is two-sided, so one-sided research volume = volume / 2;
- side behaves as tick-price direction, not exchange aggressor side;
- signed volume from side is called TRSV, never true OFI;
- the paper's L1 OFI cannot be reconstructed without bid/ask price and size.

## Corrected execution model

A signal labelled at second t uses data through the complete second t. It cannot be known before that second closes. With a one-second additional latency, entry search starts at t+2 and uses the first real observed trade print. Exit uses the first real observed trade print at/after entry_time + holding_seconds and is not allowed to cross a session boundary.

The first full rolling window of a session is not a crossing. A valid event requires the previous signal value to be above the threshold and the current complete-second value to cross below it.

## Price-only final candidate

Frozen before opening 2024:

- 30-second price move
- lower 0.05% training quantile
- previous 3 completed outright contract months only
- sell shock -> LONG
- complete-second confirmation
- one additional second latency
- first tradable print entry
- one position at a time
- fixed 300-second exit
- same-session exit

### Untouched 2024

N = 1,179
Gross expectancy = +2.44 pt/trade
Net @ 2 pt = +0.44 pt/trade
Gross after removing top 1% winners = +0.47 pt/trade
Gross-positive contract months = 6 / 9

### 2025

N = 854
Gross expectancy = +2.97
Net @ 2 pt = +0.97
Gross after removing top 1% winners = -0.57
Gross-positive contract months = 6 / 9

### 2026 (through supplied data)

N = 1,410
Gross expectancy = +4.86
Net @ 2 pt = +2.86
Gross after removing top 1% winners = +0.72
Gross-positive contract months = 7 / 8

Combined N = 3,443
Combined gross expectancy ~= +3.56 pt/trade
Combined net @ 2 pt ~= +1.56 pt/trade
Combined gross-positive contract blocks = 19 / 26

## Contract-block bootstrap

Combined 2024-2026, resampling complete contract blocks:

- Gross 95% CI ~= [+1.82, +6.30]
- Net @ 1 point 95% CI ~= [+0.82, +5.30]
- Net @ 2 points 95% CI ~= [-0.18, +4.30]
- Net @ 3 points 95% CI ~= [-1.18, +3.30]

The conservative 2-point live-cost gate therefore does not pass.

## Latency

Price candidate Net @ 2 point expectancy:

2024: latency 0 +0.47, 1 +0.44, 2 +0.34, 5 -0.07, 10 -0.04.
2025: latency 0 +1.17, 1 +0.97, 2 +1.16, 5 +0.74, 10 +0.39.
2026: latency 0 +2.77, 1 +2.86, 2 +2.58, 5 +3.43, 10 +2.37.

2024 shows that practical execution delay is still material.

## Raw TRSV

Frozen raw TRSV 20s / lower 0.1% / 300s:

- 2024 gross +1.07, Net @ 2 = -0.93
- 2025 gross +2.45, Net @ 2 = +0.45
- 2026 gross +2.87, Net @ 2 = +0.87

Combined 26 contract-block Net @ 2 CI crosses zero.

Removing top 1% winners makes gross expectancy negative in all three years. Raw TRSV is therefore not a live candidate.

### Regime failure

Previously interesting 2025/2026 regimes failed 2024:

- Night TRSV 2024 Net @ 2 ~= -3.47, CI fully negative.
- High-intensity TRSV 2024 Net @ 2 ~= -1.01.

These filters are not stable enough for production.

## Aggressive proxy invalidation

The earlier second-level aggressive proxy used the final direction of a whole second to sign the second's aggregate volume. That is not a correct reconstruction when price changes multiple times inside the second.

The corrected tick-level proxy is:

- if raw side != 0: direction = side;
- if raw side == 0: carry previous non-zero tick direction;
- carry is restricted to the same contract/session and resets at a new session;
- tick_proxy = direction * (volume/2);
- aggregate only after calculating the proxy trade by trade.

Frozen 15s / lower 0.1% / 240s results:

- 2024: N 1,093, gross +0.88, Net @ 2 -1.12, top-1%-removed gross -0.30
- 2025: N 1,459, gross +1.42, Net @ 2 -0.58, top-1%-removed gross +0.13
- 2026: N 969, gross -2.26, Net @ 2 -4.26, top-1%-removed gross -5.19

A 48-cell local plateau test covering lookbacks 10/15/20/30s, lower quantiles 0.05/0.1/0.2%, and holdings 180/240/300/450s produced 0 / 48 cells with Net @ 2 > 0 in both 2025 and 2026.

Conclusion: the earlier second-level result was aggregation bias and is invalid for strategy use.

## Why this is scientifically useful

The original research question was whether a paper-inspired order-flow imbalance concept could produce a deployable MTX advantage. Falsification is a valid result.

The supplied transaction data do not contain true L1 OFI. After controlling for execution and proxy problems, the evidence supports a more modest statement:

Extreme short-term downside price dislocations are followed by a multi-minute mean-reversion tendency in these MTX samples.

There is insufficient evidence that trade-size weighting, raw TRSV, or reconstructed aggressor pressure supplies a stable independent alpha.

## Live-gate decision

PASS:
- raw data order semantics understood;
- execution timing corrected;
- same-session execution;
- 2024 untouched holdout was directionally positive for price-only candidate;
- mean expectancy positive in 2024, 2025 and 2026 at 2-point stress;
- no isolated single-point parameter dependency was required to explain the price phenomenon.

FAIL / PENDING:
- Net @ 2 contract-block bootstrap CI > 0: FAIL;
- 2024 standalone Net @ 2 statistical strength: FAIL;
- wide latency margin in 2024: FAIL;
- exact real broker all-in cost: PENDING;
- new truly unseen data after model refinement: PENDING.

Final decision: PAPER-TRADING CANDIDATE ONLY.

## Next-generation hypothesis

Do not continue optimizing the same 2024-2026 sample. The next version should test volatility-normalized price dislocation, because the absolute-point shock threshold varies substantially with the market price/volatility regime. Any such normalized variant must be frozen before another holdout is opened.
