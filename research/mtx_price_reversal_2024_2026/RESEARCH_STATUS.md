# Research Status — MTX Extreme Selloff Reversal

**As of:** 2026-08-24  
**Branch:** `research/mtx-price-reversal-2024-2026`  
**Deployment status:** **NOT LIVE APPROVED**  
**Research state:** **Frozen Forward-OOS Candidate + registered challengers + monitor-only risk models**

## 1. Source-of-truth and execution parity

Raw source datasets remain external immutable MTX parquet files. The research engine preserves parquet physical row order, excludes spread/non-six-digit expiries, constructs deterministic second bars, and executes at the first tradable print after complete-second confirmation plus one second latency.

Full raw audit re-run:

- Raw rows: **126,438,254**
- Outright monthly rows: **126,438,076**
- Excluded spread/combo rows: **178**
- Contract months: **32** (`202401` through `202608`)

Canonical baseline parity was re-run from raw ticks and matched exactly:

- Trades: **3,655**
- Gross PnL: **+12,414 points**
- Net@2: **+5,104 points**
- PF@2: **1.0590535694**
- Annual trade counts: **1,189 / 1,057 / 1,409** for 2024/2025/2026
- 202506 price threshold: **-58 points**

All later causal price/flow research was joined back to the same execution path. Entry first print, 300-second exit first print, gross300 and 30-second signal value achieved **1,112/1,112 exact parity** for the frozen candidate.

## 2. Frozen Forward-OOS V1 candidate

Frozen execution specification:

- MTX outright monthly contracts only
- Long only
- Signal windows: **09:00–10:30** and **20:30–22:30**
- Causal HighVol regime
- 30-second price change
- Threshold from previous three completed contracts, **Q0.05%**
- True downward crossing
- Signal second must complete
- Additional **+1 second latency**
- Entry at first afterward tradable print
- Maximum **1 MTX** position
- Hold **300 seconds**
- Exit first observed print at/after target, same session only
- Main friction assumption: **2 points round trip**

Re-run result:

- Trades: **1,112**
- Gross: **+10,650**
- Net@2: **+8,426**
- Expectancy: **+7.577 points/trade**
- PF: **1.30649**
- Win rate: **54.68%**
- Max realized drawdown: **-1,235 points**
- 2024: **+1,118**
- 2025: **+1,365**
- 2026: **+5,943**

The rule is frozen for forward evaluation. Historical 2024–2026 results may not be reused as fresh OOS evidence.

## 3. Cost, robustness and path findings

The frozen candidate remains positive across nearby signal/high-volatility parameter neighborhoods and under elevated round-trip cost.

Selected cost stress:

- Cost 2: **+8,426**, E **+7.58**, PF **1.306**
- Cost 5: **+5,090**, E **+4.58**, PF **1.175**
- Cost 8: **+1,754** on V1; R3-lite remains **+2,867**

Holding-path structure:

- 15s E: **-0.70**
- 30s: **+0.68**
- 60s: **-0.70**
- 120s: **+2.54**
- 180s: **+4.74**
- 240s: **+5.50**
- 300s: **+7.58**

Winners tend to realize MFE late. Naive tight fixed stops destroy right-tail winners.

## 4. Tail-risk investigation

The original no-fixed-stop candidate had a maximum loss of **-589 points**, approximately 10x the average loss. The worst trade was a distinct catastrophe path rather than a normal loss-scale extension.

### ACCEL30 — registered Challenger A

Catastrophic acceleration condition:

- At 30 seconds after entry, if mark-to-market loss is at least **20% of Prior14 same-session average range**, classify the reversal hypothesis as immediate catastrophic acceleration.
- Early exit is allowed, but the position gate remains locked until the original entry+300s horizon so the overlay cannot create additional trades.

Historical result:

- V1 Net@2: **+8,426**
- ACCEL30: **+8,888**
- PF: **1.329**
- Max loss: **-310** vs V1 **-589**
- Trigger count: **4** over only **2 dates**

ACCEL30 is mechanistically attractive but statistically rare. It remains a forward challenger, not a validated production rule.

### Repeat5/45 — registered Challenger B with ACCEL30

During a live position, repeated qualifying Q0.05% true crossings are common. A dense early cluster is informative for failure of the first entry:

- If the **5th additional qualifying extreme-selloff crossing** occurs within **45 seconds** of the original entry, and the latency-adjusted tradable price is still at/below original entry price, exit the original position.
- Keep the position gate locked until original entry+300s.

Historical combined result (`V1 + ACCEL30 + Repeat5/45`, called **R3-lite**):

- Net@2: **+9,539**
- Expectancy: **+8.58**
- PF: **1.364**
- Max loss: **-310**
- Repeat trigger count: **19** across **14 dates**
- 15 of 19 Repeat interventions improved the original trade
- Historical sign-test one-sided p ~ **0.0096**
- Date-cluster bootstrap incremental 95% CI vs ACCEL30: approximately **[+47, +1,424]**

R3-lite is the preferred historical challenger because it improves expectancy and equity quality without adding position size.

### Flow-gated FAIL180 — Shadow only

Causal order-flow reconstruction identified a strong pre-entry risk variable: prior 300-second transaction density relative to the size of the extreme selloff (`trades_300 / |signal move|`). It ranks severe MAE consistently across years.

A rolling-last-100 same-kind-signal percentile gate (approximately >=60%) used to activate a 180-second reversal-failure exit produced:

- 14 FAIL180 activations on 14 dates
- +317 points incremental vs ACCEL30
- Date-cluster bootstrap incremental 95% CI approximately **[+31, +651]**

However, after adding it on top of R3-lite, incremental historical value fell to approximately **+181 points** and the cluster CI crossed zero. Therefore this remains **Shadow only**.

## 5. Repeated-signal structure

From 4,019 pre-state qualifying events:

- Actual executed trades under max-one-position: **1,112**
- Signals blocked because a position already existed: **2,907**
- Trades with at least one additional signal during the 300-second holding window: **798 / 1,112 (71.76%)**

Blocked signals, if treated independently for diagnostic purposes, still showed positive reversal expectancy. Therefore repeated signals are not globally “bad”; dense early repeats specifically indicate that the original first entry may have been premature within a larger shock cluster.

Add-on trading was rejected because concurrency would rise to as many as **19 MTX** positions, violating the one-position risk contract.

## 6. Causal price and order-flow risk research

Raw ticks were rebuilt into candidate-session second bars with full parity:

- Price second bars: **2,576,361**
- Flow second bars: **2,576,361**
- Exact one-to-one `(contract, session, second)` key match
- `buy_vol + sell_vol + neutral_vol == total volume` for every second

Important signal-time causal risk indicators:

1. `range_300 / Prior14 range`
2. low `range_60 / range_300`
3. transaction activity density over 180–300 seconds
4. `trades_300 / |extreme-selloff points|` persistence / price-discovery density

The persistence variable showed strong severe-MAE ranking consistency across 2024–2026, but high-risk trades also contain large right-tail winners. These indicators are **risk context**, not entry filters.

## 7. Entry Risk Grade — Monitor only

A fully causal, equal-weight risk grade uses rolling historical percentiles of pre-entry price and activity stress.

For evaluable trades, `MAE >= 5x threshold` rate rose approximately:

- Low: **0.53%**
- Normal: **1.08%**
- Elevated: **1.39%**
- High: **2.34%**
- Extreme: **13.11%**

Extreme represented only ~5.65% of scored trades yet captured ~38% of the deepest tail events. Cluster bootstrap estimated Extreme catastrophe risk at roughly 10x the rest.

Directly skipping Extreme/Elevated trades reduced total strategy PnL materially. Therefore Entry Risk Grade is permanently **Monitor only** unless a new pre-registered study is launched.

## 8. Day Stress Grade — Monitor only

Using only the first 30 minutes after a day's first qualifying signal, causal shock-density/cooling features predict whether the rest of the day will contain a deep tail event.

Last-60-active-day walk-forward grade:

- Extreme Day Stress: **29 days**
- Tail5-day rate: **31.0%**
- Captured approximately **75%** of evaluable tail5 days
- Yearwise AUC remained directionally consistent

However Extreme days were also highly profitable on average. Halting new trades after an Extreme classification reduced R3-lite from **+9,539 to +6,740** and worsened max drawdown. Day Stress is therefore **Monitor only**.

## 9. Catastrophe Watch State Machine — Monitor only

The research supports a monitoring state, not an automatic stop translation.

At 120 seconds:

- GREEN: tail5 rate ~**0.44%**
- YELLOW: ~**1.06%**
- ORANGE: ~**23.68%**
- RED: ~**55.56%**

At 180 seconds:

- GREEN: ~**0.15%**
- YELLOW: ~**0.54%**
- ORANGE: ~**25.0%**
- RED: ~**55.6%**

`-3x threshold` is a powerful danger marker, especially when reached early, but direct 2x–4x threshold stops failed cross-year tests, including optimistic perfect-fill upper-bound tests. The state machine is for monitoring/alerting and forensic evaluation, not a new automatic exit.

## 10. Capital-risk findings

Historical realized equity:

- V1: Net **+8,426**, Max DD **-1,235**, Ulcer ~**495.7**
- ACCEL30: **+8,888**, DD **-1,176**, Ulcer ~**425.0**
- R3-lite: **+9,539**, DD **-1,176**, Ulcer ~**398.1**

Intratrade MAE inclusive of 2-point friction:

- V1 P95: ~**179**, P99: ~**281.6**, worst ~**608**
- ACCEL30 P95: ~**176.4**, P99: ~**276.8**, worst ~**419**
- R3-lite P95: ~**171**, P99: ~**276.8**, worst ~**419**

The deepest historical high-water-mark-to-intratrade-low capital trough remained around **-1,392 points**, showing that account risk is not equivalent to maximum closed-trade loss.

Day-cluster Monte Carlo / bootstrap indicates R3-lite reduces drawdown-tail probability but does not eliminate it. With intratrade MAE and 2-point cost, approximate probability of the starting equity falling below:

- -1,000: **12.0%**
- -1,500: **3.59%**
- -2,000: **1.13%**
- -2,500: **0.35%**
- -3,000: **0.09%**

At 5-point friction, capital requirements deteriorate materially.

## 11. Explicitly rejected research lines — DO NOT RETUNE

The following were tested and should not be reopened on the inspected 2024–2026 sample:

- Fixed point stops
- 2x–4x threshold first-touch/direct stops
- Risk-gated threshold stops
- 60-second direct failure exits
- High-risk entry skip
- High-risk delayed/reclaim entry
- Stress-adaptive shorter holding horizon
- Session kill switch
- Extreme-Day halt
- Repeat re-anchor / repeated 300-second reset
- Immediate re-entry after Repeat exit
- Repeat-signal add-on positions
- Mid-stage repeat-density stop grids
- 3x-breach recovery exits

Re-searching these parameter spaces on the same inspected sample would be data mining.

## 12. Forward evidence gates

Base and overlays must be evaluated separately.

### Frozen V1 base gate

At minimum:

- >= **6 months** and >= **200 forward trades**
- Net@2 > 0
- PF >= 1.10
- Net remains positive under 5-point round-trip friction
- Cluster-bootstrap 95% lower bound > 0
- Drawdown remains within the pre-registered risk envelope
- No parameter changes during the evaluation window

### Repeat5/45 gate

Because historical trigger rate is ~1.71%, 200 trades are insufficient. Promotion review requires at least **10 genuine forward Repeat triggers**. A provisional evidence threshold is:

- >= **8/10** interventions improve the corresponding unmodified V1/ACCEL path
- aggregate forward delta > 0
- no single date contributes >50% of total forward improvement
- exact 5/45 rule remains unchanged

### ACCEL30 gate

Historical trigger rate is only ~0.36%; it cannot graduate on the base 200-trade rule. Until a meaningful number of genuine catastrophic acceleration events has accumulated, ACCEL30 remains a rare-event challenger. For 5 forward triggers, 5/5 improvement would be required for a very strong initial review; for 8 triggers, roughly >=7/8.

### Flow-gated FAIL180 gate

Must accumulate at least 10 forward activations and demonstrate positive incremental value **on top of R3-lite**, not merely versus ACCEL30 alone.

### Monitor-only models

Entry Risk Grade, Day Stress Grade and Catastrophe Watch may be calibrated and monitored, but may not silently become entry/exit rules.

## 13. Current recommendation

- **Control:** Frozen V1
- **Challenger A:** V1 + ACCEL30
- **Challenger B:** V1 + ACCEL30 + Repeat5/45 (R3-lite)
- **Shadow C:** Flow-gated FAIL180 / R2 diagnostics
- **Monitor only:** Entry Risk Grade, Day Stress Grade, Catastrophe Watch

No version is live approved. The next valid evidence must come from data strictly after the inspected source endpoint (**2026-08-14 13:44:59**).
