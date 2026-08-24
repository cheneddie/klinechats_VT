# M6 Dev8 — POC Dose Response

## Verdict

`POC_WEAK_SHORT_HORIZON_SIGNAL_NOT_MULTIPLICITY_ROBUST`

Dev8 answers the plan question directly: **single-bar lower POC / migration / velocity / slope-divergence do not show robust incremental directional information in 2024. Repeated lower-POC persistence (6/12-bar `poc_lower_count`) is materially more promising, but only at the 15-minute horizon and it does not survive the final global multiple-testing correction across all tested horizons.**

## Frozen population parity

- source physical rows: 50,862,751
- strict-selected: 50,862,621
- 1m completed bars: 270,621
- M4 raw triggers: 66,248
- first-trigger episodes: 27,879 (day 7,238 / night 20,641)
- comparable 30m episodes: 26,521

All counts exactly reproduce the frozen M4/M5 chain before any POC inference.

## 30m primary result

23 continuous POC features across migration / velocity / divergence / stall: no family meets the predeclared cluster-CI + decile monotonicity + session-consistency + BH-FDR rule. `poc_delta_1` itself points weakly in the opposite direction and does not survive FDR. Binary `high_delta>=0 AND poc_delta<0` also has no directional evidence.

## 5m / 15m sensitivity

5m has no coherent family-level result. At 15m, `poc_lower_count_6` and `poc_lower_count_12` form a coherent stall-persistence family: about +4 percentage points in the rank slope of `P(MFE_short > MAE_short)`, day/night same direction, and 12/12 leave-one-month-out slopes positive. Controls for recent price-down persistence, close slope, channel geometry, ATR and session do not explain it. Fixed tail cuts show broad support rather than a tiny extreme spike.

However, the apparent within-15m BH q≈0.059 is **not the final multiplicity result**. Once every primary test actually examined is included (23 features × 3 horizons × 2 outcomes = 138), the key probability tests have global q≈0.178 and no positive test has global q<=0.10. Therefore the 15m result remains an exploratory watchlist, not an Edge claim.

## Structure-break caution

POC stall appears strongly related to channel-midline / micro-swing breaks in univariate plots. That relationship collapses after controlling the frozen reference distance and causal channel geometry. These structure metrics must not be used to claim POC predictive value.

## Decision

- Do **not** promote POC to CORE.
- Do **not** choose a POC threshold in Dev8.
- Preserve `poc_lower_count_6/12` as an exploratory short-horizon watchlist feature for later ablation/placebo only.
- Proceed to Dev9 Pressure × Efficiency 2D Edge Map; 2025/2026 remain untouched.
