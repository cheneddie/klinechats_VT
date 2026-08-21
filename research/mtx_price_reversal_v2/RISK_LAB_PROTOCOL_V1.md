# RISK_LAB_PROTOCOL_V1 — FROZEN BEFORE PHYSICAL-TICK RESULTS

Status: **FROZEN HISTORICAL DISCOVERY PROTOCOL**

This protocol governs all 2024–2026 physical-tick risk discovery. It is frozen before inspecting any stop-grid result. The inspected 2024–2026 sample remains historical discovery only and can never become forward OOS.

## 1. Historical research population
- Source: supplied MTX raw Parquet for 2024, 2025, 2026 through the existing historical watermark.
- Preserve original physical row order. `_seq` is assigned before filtering.
- Outright contract only; trade contract must match each baseline trade.
- Baseline population: the frozen 3,655 one-position-at-a-time trades.
- Baseline strategy rules are unchanged.

## 2. Execution semantics
Primary stop execution: `NEXT_PHYSICAL_PRINT` strictly after the physical trigger `_seq`.

Diagnostics / stress:
- trigger print: diagnostic upper bound only; never used for candidate selection.
- delayed physical print N=2, 3, 5 after trigger.
- +1 second: secondary adverse stress, first matching physical print at/after trigger_time + 1 second.

Every stop result must retain trigger and fill separately: trigger_seq/time/price, fill_seq/time/price, reason, slippage.

Primary friction: 2.0 points round trip.
Adverse friction: 3.0 points round trip.

## 3. Causal volatility scale
`PriorCausalVol` = mean range of the previous 14 completed sessions of the same session kind. No current-session future information may enter the scale.

## 4. Structural-stop families — predeclared
### S1 Signal Extreme + causal-vol buffer
`stop = signal_low_30s - b * PriorCausalVol`
where `signal_low_30s` is the minimum physical price in the completed signal window `[signal_ts-30s, signal_ts]`.

Predeclared buffers:
`b = [0.00, 0.025, 0.05, 0.075, 0.10, 0.15]`

### S2 Entry causal-volatility stop
`stop = entry_price - k * PriorCausalVol`

Predeclared k:
`k = [0.05, 0.075, 0.10, 0.125, 0.15, 0.20]`

### S3 Re-break / continuation failure
Reference level: `signal_low_30s - 0.025 * PriorCausalVol`.
Trigger only after `p` consecutive matching physical prints at/below the reference level.

Predeclared persistence:
`p = [1, 3, 5]`

No additional S3 depth or bounce parameter may be introduced in V1 after viewing results.

Structural-only stage runs without a performance-active catastrophic stop.

## 5. Catastrophic-stop family — predeclared
Catastrophic stop is independent from Structural and is evaluated alone first.

Fixed absolute maximum-loss boundaries from entry:
`C = [150, 200, 250, 300, 400, 500] points`

Purpose: bound historical single-trade loss with minimal strategy/tail damage. It is NOT required to improve expectancy.

## 6. Combined stage
Combined Structural + Catastrophic is run only after Structural-only and Catastrophic-only reports are locked.
At most 2 Structural plateau representatives and 2 Catastrophic plateau representatives may enter combined comparison. No new parameter values may be created in the combined stage.

## 7. Mandatory metrics for every candidate
- Trades
- PF, expectancy, median
- Net@2 and Net@3 total / expectancy
- Max DD, worst trade
- StopTriggered%
- StructuralStop% / CatastrophicStop% / TimeExit%
- Median / P95 / worst stop execution slippage
- PnL removed from baseline losers (SavedLoss)
- PnL removed from baseline winners (LostTail)
- RiskEfficiency = SavedLoss / LostTail
- baseline >=P95 winner PnL retention
- baseline >=P99 winner PnL retention
- baseline Top-1% / Top-5% winner retention
- baseline Top-5 session-key-day PnL retention
- baseline Top event-cluster PnL retention
- yearly and monthly tables
- day-cluster bootstrap CI
- event-cluster bootstrap CI
- N=2/3/5 print stress

## 8. Cluster definitions
Primary day cluster: `session_key` start date, not entry calendar date.
Secondary reporting may also show entry-calendar day but cannot replace the primary cluster definition.

Event cluster V1 is frozen from the baseline 300s strategy: within the same session, a subsequent baseline entry belongs to the previous event cluster when it occurs <=300 seconds after the previous baseline exit. Candidate stop timing must NOT redefine cluster membership.

Bootstrap seed: `20260821`.
Bootstrap repetitions: 5000 for final shortlisted candidates; 2000 is allowed for grid diagnostics.

## 9. Structural selection gates
A Structural candidate is not eligible because it has the best PF. It must satisfy all:
1. parameter plateau: candidate belongs to >=3 consecutive predeclared parameter values in the same family with Total Net@2 > 0;
2. cross-year direction: all three calendar-year Net@2 expectancies >= 0;
3. execution robustness: Total Net@2 > 0 under delayed N=3-print fill;
4. right-tail survival: P95 retention >=70%, P99 retention >=70%, Top-5-day retention >=70%, Top-event retention >=70%;
5. RiskEfficiency >=1.0 when LostTail > 0;
6. day-cluster CI lower bound must not deteriorate by more than 0.5 pt/trade versus the frozen baseline day-cluster lower bound;
7. no isolated one-parameter spike is eligible.

If no Structural candidate passes, the correct V1 result is `NO STRUCTURAL STOP SELECTED`.

## 10. Catastrophic selection gates
Catastrophic is judged as safety, not alpha. A candidate must satisfy:
1. plateau: >=3 consecutive predeclared boundaries with Total Net@2 > 0;
2. total Net@2 PnL retention >=95% of baseline;
3. P95/P99 winner retention >=90%;
4. Top-5-day and Top-event retention >=90%;
5. historical worst-trade absolute loss reduced by >=40%;
6. trigger rate <=5%;
7. Total Net@2 remains >0 under delayed N=3-print fill.

If no candidate passes, report `NO CATASTROPHIC BOUNDARY SELECTED` and keep Production Candidate blocked.

## 11. Historical Candidate Tournament
Maximum four diagnostic rows:
1. BASELINE_300
2. EARLY_HIGHVOL_300 (post-hoc control only)
3. EARLY_HIGHVOL + selected RISK
4. EARLY_HIGHVOL + selected RISK + selected MANAGEMENT

Tournament columns must include Delta E, Delta DD, Delta Worst, right-tail retention, cluster robustness, execution stress and a complexity score. Historical PF is not the primary ranking criterion.

At most 3 non-baseline candidates may be carried into any pre-OOS freeze discussion.

## 12. OOS prohibition
No row later than `2026-08-14 13:44:59+08:00` may be inspected during Risk Lab selection.
Forward OOS remains locked until Risk Lab, right-tail survival, management selection, candidate freeze and red-team tests are complete.
