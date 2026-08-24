# M6 2024 Discovery — Current Status and Next Plan

> Branch: `research/poc-absorption-reversal-v1`  
> Scope: 2024 discovery only. 2025 validation and 2026 final OOS remain untouched.  
> Main branch: untouched. Draft PR #23 remains unmerged.

## 1. Current formal state

Completed engineering/research gates:

- M1 Data / Contract / Session QA — PASS_WITH_EXPLICIT_DATA_GAP
- M2 Causal multi-resolution bars + completed/developing POC — PASS
- M3 Continuous causal predictor store — REPRODUCIBLE CAUSAL FEATURE PASS
- M4 Unbiased price-only event universe — REPRODUCIBLE UNBIASED EVENT UNIVERSE PASS
- M5 Dev1–Dev6 physical-tick multi-horizon outcomes + event replay sanity — REPRODUCIBLE PHYSICAL-TICK OUTCOME CUBE PASS
- M6 Dev7 Universe Baseline — NO_STABLE_SHORT_DIRECTIONAL_ASYMMETRY_AT_30M
- M6 Dev8 POC Dose Response — POC_WEAK_SHORT_HORIZON_SIGNAL_NOT_MULTIPLICITY_ROBUST
- M6 Dev9 Pressure × Efficiency — M6_DEV9_ORIGINAL_BUYING_ABSORPTION_INTERACTION_NOT_SUPPORTED
- M6 Dev10 Trend / Broad Channel Contribution — M6_DEV10_TREND_BROAD_CHANNEL_NO_INCREMENTAL_SHORT_EDGE

M6 is **not complete**. Dev11 ablation and Dev12 placebo/cluster bootstrap remain mandatory before M6 can be closed.

## 2. Frozen 2024 research population

All M6 inference continues from the frozen HIGH_PRICE_PROBE_V1 universe; no feature is allowed to redefine event membership.

- source physical rows: 50,862,751
- strict-selected rows: 50,862,621
- completed 1m bars: 270,621
- 1m raw M4 triggers: 66,248
- 1m first-trigger episodes: 27,879
  - day: 7,238
  - night: 20,641
- comparable 30m episodes: 26,521
- primary inference unit: trading-day clustered, not raw-trigger IID

2025 and 2026 have not been used for M6 discovery.

## 3. What we know now

### 3.1 Universe baseline

The high-price opportunity universe itself is almost directionally neutral at 30m:

- median short MFE: ~2.301 ATR
- median short MAE: ~2.333 ATR
- mean MFE−MAE: ~+0.009 ATR
- P(MFE > MAE): ~49.26%
- trading-day clustered confidence intervals cross the directional null

Therefore later features must show incremental information; they cannot claim credit for a natural high-price mean-reversion effect.

### 3.2 POC contribution

Single lower POC, POC migration, velocity and price-vs-POC divergence do not produce a multiplicity-robust directional edge.

Repeated `poc_lower_count_6/12` is the only meaningful watchlist result: at 15m it shows a coherent ~+4 percentage-point directional-probability rank slope, day/night same direction and leave-one-month-out stability. But after correcting all actually tested primary hypotheses (23 features × 3 horizons × 2 outcomes = 138), key global q values are ~0.178, so the result is not promoted to CORE.

Current POC classification:

- single-bar POC weakness: REDUNDANT / NON-PREDICTIVE for short direction
- repeated lower-POC persistence: OPTIONAL WATCHLIST only
- apparent POC stall → structure-break relation: largely channel/reference-distance confounded

### 3.3 Pressure × Efficiency contribution

The predeclared 2×2 test directly asked whether D = High Pressure + Low Efficiency is materially better than B = Low Pressure + Low Efficiency.

Primary D−B:

- 5m path efficiency is lower in D, but the effect disappears after controlling total activity/tick count/range/session/zone composition
- 15m P(MFE>MAE): only about +0.55 percentage points
- 30m P(MFE>MAE): only about +0.56 percentage points
- no reliable directional increment

Raw q80 high-zone positive volume is strongly correlated with total activity (volume ~0.842; tick count ~0.809). Positive, negative and total-volume negative controls show the same activity × low-efficiency interaction. Directional composition proxies (`high_zone_tdp`, `high_zone_positive_share`) do not restore the short thesis; positive share is even associated with a lower 30m midline-break rate in the low-efficiency subset.

Current Dev9 functional classification:

- buy-direction pressure: REDUNDANT_OR_CONTRADICTORY_FOR_SHORT_DIRECTION
- raw pressure magnitude: ACTIVITY_REGIME_ONLY
- price efficiency: STATE_PERSISTENCE_NOT_DIRECTIONAL_EDGE
- pressure × efficiency: NOT_BUY_SIDE_SPECIFIC_ACTIVITY_X_EFFICIENCY_INTERACTION

Interpretation: the original red-circle “large buying absorbed near the high” story is not supported by 2024 tick-direction-proxy evidence. What remains is a non-directional high-activity × low-efficiency regime effect.

### 3.4 Trend / broad-channel contribution

Dev10 kept the frozen universe unchanged and tested whether rising/broad context adds short-direction information.

Predeclared primary context:

- Rising: `slope_atr_24 > 0`
- Broad: within-session `channel_width_atr_24` rank >= 0.50

Hard parity: event `channel_width_atr_24` equals frozen M4 `(rolling_high - rolling_low) / ATR` exactly.

Observed population:

- Rising: ~89.31% of events
- Rising + Broad: ~48.90%

Across 128 actually tested context hypotheses, zero survives global BH q<=0.10; minimum global q is ~0.321. Rising+Broad does not reliably improve 15m/30m directional probability, including inside the Low-Efficiency subset. Direct Broad-vs-Tight within Rising is approximately -0.14 pp at 15m and -0.74 pp at 30m, with unstable monthly signs.

Current context classification:

`REDUNDANT_FOR_SHORT_DIRECTION_WITH_UNADJUSTED_TREND_CONTINUATION_HINT`

The unadjusted trend-continuation hints are retained as diagnostics only; they are not promoted to HARMFUL because they do not survive the multiplicity firewall.

## 4. Current component classification before Dev11

| Component | Current classification | Reason |
|---|---|---|
| HIGH_PRICE_PROBE universe | CONTROL / OPPORTUNITY UNIVERSE | approximately neutral short direction |
| Single-bar POC weakness | REDUNDANT | no robust incremental direction |
| Repeated lower-POC persistence | OPTIONAL WATCHLIST | 15m hint, fails global FDR |
| Buy-direction pressure proxy | REDUNDANT / CONTRADICTORY | no incremental short value |
| Raw pressure magnitude | REGIME_ONLY | explained by market activity |
| Price efficiency collapse | STATE / OPTIONAL | state persistence, not reliable direction |
| Pressure × efficiency | REGIME interaction only | not buy-side specific |
| Rising / broad channel | REDUNDANT for short direction | 128-test global FDR finds no increment |

These classifications are **provisional until Dev11 ablation and Dev12 placebo/cluster bootstrap**.

## 5. What has explicitly NOT been done

- no P&L or profit factor optimization in M6
- no commission/slippage/latency tuning
- no best threshold search for POC, pressure, efficiency or channel width
- no use of 2025 to rescue weak 2024 findings
- no use of 2026
- no merge to main
- no production signal claim

## 6. Next phase — Development 11: Sequential Contribution / Ablation

Objective: determine whether any component adds unique information after the preceding components are present, and classify every component as CORE / OPTIONAL / REDUNDANT / HARMFUL / REGIME_ONLY / INSUFFICIENT.

Frozen sequence to evaluate:

1. Baseline
2. Baseline + Context
3. + POC
4. + Pressure
5. + Efficiency

For each step report at minimum:

- ΔN / sample retention
- ΔMFE
- ΔMAE
- ΔP(MFE>MAE)
- Δ5m balance/path efficiency
- Δtwo-sided excursion
- Δstructure/reversal measurements with geometry controls
- day/night consistency
- monthly consistency
- trading-day cluster uncertainty

Then perform leave-one-component-out ablation:

- FULL − Context
- FULL − POC
- FULL − Pressure
- FULL − Efficiency

Important Dev11 rule: there is currently no evidence-based reason to force all components into a composite. The ablation must be able to conclude that the simplest surviving model is only an opportunity universe plus a state variable, or even that no directional feature survives.

Dev11 deliverables:

- `M6_DEV11_SEQUENTIAL_ABLATION.md`
- `M6_DEV11_COMPONENT_CLASSIFICATION.csv`
- `M6_DEV11_TEST_REGISTRY.csv`
- formal QA JSON + frozen config + CODE/TEST/QA runner

## 7. Next phase — Development 12: Placebo + Cluster Bootstrap

Objective: actively try to falsify whatever survives Dev11.

Required placebo families from the frozen plan:

- nearby fake POC
- shifted timing
- random high-zone event
- randomized pressure window

Additional negative controls already motivated by Dev8–Dev10:

- replace buy-side proxy with matched negative/total activity
- matched channel geometry placebo
- matched activity-regime placebo
- shuffled efficiency within session/trading-day-safe blocks where causality is preserved for the placebo design

Bootstrap/inference must not treat raw triggers as IID. At minimum:

- cluster by episode
- cluster by trading day

For every surviving feature/component report:

- real effect vs placebo distribution
- episode-cluster CI
- trading-day-cluster CI
- monthly concentration
- day/night concentration
- multiple-testing registry / global FDR sensitivity

Dev12 deliverables:

- `M6_DEV12_PLACEBO_CLUSTER_BOOTSTRAP.md`
- placebo registry and distributions
- cluster inference summary
- final M6 component classification
- M6 close/no-close verdict

## 8. M6 close gate

Only after Dev11 + Dev12 may M6 be checked complete.

Possible M6 outcomes include:

- a frozen 2024 candidate worth one-shot 2025 validation
- `REGIME_ONLY`
- `RESEARCH_ONLY`
- `REJECT_NO_EDGE`

If a candidate survives, **freeze its feature definitions and thresholds before opening 2025**. Once 2025 is inspected for validation, it can no longer be treated as untouched.

## 9. Later roadmap after M6

- M7 / Development 13: one-shot 2025 validation with frozen candidate; no retuning
- M8 / Development 14: one-shot 2026 partial-year final OOS; no post-result candidate changes
- M9 / Development 15: entry-family test (anticipatory / confirmation / break+pullback)
- M9 / Development 16: cost, latency (+1s/+2s/+5s), slippage and trade-management plateau stress
- M10: Replay / Pattern Wall integration only after research semantics stabilize

## 10. Current evidence boundary

At this point there is **no production candidate**. The original visual hypothesis has been progressively weakened:

`rising broad channel → POC stalls/falls → high-zone buying pressure fails to extend price → balance → downside reversal`

Current 2024 evidence instead supports the more conservative description:

`high-price opportunity universe + occasional state-persistence effects`, while POC, buy-side pressure and broad-channel context have not demonstrated multiplicity-robust incremental short-direction information.

That is the state Dev11 must now attempt to simplify or falsify further.
