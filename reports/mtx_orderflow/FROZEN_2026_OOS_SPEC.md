# Frozen 2026 Untouched-OOS Specification

This file freezes the primary validation rule **before examining 2026 strategy performance**. The 2026 parquet was opened only for schema/decoder verification; no strategy result was inspected before this specification was committed.

## Data rules

- Keep original parquet row order.
- Exclude all non-outright expiry values; only `^\d{6}$` is eligible.
- Vendor `volume` is doubled two-sided volume; divide by 2 before research calculations.
- `side` is tick-rule price direction (`sign(price_t-price_{t-1})`), not independent aggressor side.
- Primary signal is therefore **Tick-Rule Signed Volume (TRSV)**, never called true OFI/TI.
- Per second: use the last observed trade price; sum TRSV, volume, trades and direction counts.
- Do not join different expiry contracts into one return path.
- Split sessions when the same-contract clock gap exceeds 1800 seconds.
- Within a session, missing seconds have zero flow and forward-filled last price for signal construction; execution is only allowed on an observed-trade second.

## Primary frozen candidate

Purpose: test whether the 2025-discovered sell-flow reversal survives a completely untouched 2026 sample.

- Direction: sell shock -> LONG only.
- Signal lookback: 20 seconds.
- Signal: rolling 20-second raw TRSV sum.
- Shock threshold: lower 0.1 percentile (`q=0.001`).
- Online threshold estimation: use the immediately preceding 3 **completed outright contract months** only. No 2026 future data may enter its own threshold.
- Event definition: first crossing from above the threshold to `TRSV20 <= threshold`.
- No repeated entry while the signal remains continuously below threshold.
- Entry latency: first observed-trade second at or after signal time + 1 second.
- Position state: one long position at a time; ignore new signals while holding.
- Primary holding time: 300 seconds from entry.
- Exit: first observed-trade second at or after entry + 300 seconds.
- Return unit: index points.

## Prespecified secondary endpoint

- Same rule, holding time 180 seconds.
- This is a robustness endpoint only; 2026 results must not be used to choose between 180 and 300 seconds and then relabel the winner as the primary result.

## Cost reporting

Report every result at explicit round-trip cost assumptions of:

- 0 point
- 1 point
- 2 points
- 3 points

The dataset lacks bid/ask and queue position, so these are execution-cost sensitivity scenarios, not claims of exact realized slippage.

## 2025 reference before freeze

Rolling 3-contract walk-forward tests using the exact primary signal construction, one-position state and 1-second delayed execution produced for `L=20, q=0.001`:

- 180s: N=1,349, gross mean ~= +2.001 points, net at 1 point ~= +1.001, net at 2 points ~= +0.001.
- 300s: N=1,294, gross mean ~= +2.228 points, net at 1 point ~= +1.228, net at 2 points ~= +0.228.

A price-only 20-second downside-shock baseline at `q=0.001` produced approximately:

- 180s: gross mean ~= +1.269 points.
- 300s: gross mean ~= +1.923 points.

Therefore the apparent incremental contribution of TRSV over a simple short-term price-reversal baseline is modest and must be challenged with matched controls, volume-shuffle/null tests and regime analysis.

## OOS pass / fail framework

The primary 2026 result is not considered deployable merely because gross mean > 0.

Required evidence layers:

1. Primary 300s rule gross expectancy > 0 OOS.
2. Net expectancy after 1-point round-trip cost > 0.
3. Stronger evidence if net expectancy after 2-point cost > 0.
4. Contract-month stability: result must not be explained by only one exceptional month.
5. Tail-dependence test: remove the largest 1% winning trades and re-evaluate expectancy.
6. Bootstrap / contract-block uncertainty interval.
7. Price-only baseline and matched-control comparison.
8. Volume-shuffle / null test: breaking the association between tick direction and trade-size information should materially weaken any claimed volume-specific edge.
9. Regime stability and explicit failure conditions.
10. Full executable equity-curve metrics with one position state.

Failure of the untouched 2026 primary rule is a genuine failure of this frozen candidate. 2026 may later be used for a new research generation, but that new generation must not be described as untouched validation of the 2025 rule.
