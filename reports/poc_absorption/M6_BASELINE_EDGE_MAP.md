# M6 Development 7 — HIGH_PRICE_PROBE_V1 Universe Baseline

## Verdict

**Engineering / research-cycle verdict:** `M6_DEV7_UNIVERSE_BASELINE_PASS`

**Directional control result:** `NO_STABLE_SHORT_DIRECTIONAL_ASYMMETRY_AT_30M`

This is the required control group before POC/TDP/efficiency feature discovery. It is **not** `REJECT_NO_EDGE`, and it does not claim that high-price location has no causal effect versus a non-high market sample. It says only that, *inside the frozen HIGH_PRICE_PROBE_V1 universe*, the 2024 primary 1m first-trigger episodes do not show a stable short-side MFE-over-MAE advantage at 30 minutes.

No POC, TDP, pressure, efficiency predictor threshold, P&L, PF, or best-horizon optimization is used in Dev7.

## Frozen analysis firewall

Primary inference was declared before the baseline run:

- year: **2024 discovery only**;
- event view: **1m first trigger per episode**;
- nominal 30m analyses require actual same-contract observation `>=1740s`;
- primary inference: **trading-day cluster bootstrap 95% CI**;
- episode-resample bootstrap is sensitivity only;
- 2025 / 2026 remain untouched;
- all tested analysis IDs are recorded in `M6_DEV7_TEST_REGISTRY.csv`.

See `config/poc_absorption/m6_analysis_firewall_v1.json`.

## Primary 1m control group

Frozen 1m source:

```text
raw HIGH_PRICE_PROBE triggers     66,248
first-trigger episodes            27,879
actual-comparable 30m episodes    26,521
unique trading dates                 241
```

Primary 30m outcomes:

| Metric | Result |
|---|---:|
| Median short MFE | 2.301 ATR |
| Median short MAE | 2.333 ATR |
| Median paired MFE−MAE | 0.000 ATR |
| Mean paired MFE−MAE | +0.009 ATR |
| P(MFE > MAE) | 49.26% |
| 30m structure-break rate | 55.54% |
| Median raw MFE | 15 points |
| Median raw MAE | 16 points |

The pooled trading-day-cluster 95% intervals are:

```text
mean(MFE−MAE) ATR     [-0.111, +0.133]
P(MFE > MAE)          [48.14%, 50.40%]
30m structure break   [54.46%, 56.69%]
```

Both directional nulls are inside their trading-day-cluster intervals. Therefore there is no stable evidence that HIGH_PRICE_PROBE_V1 alone provides a short-direction excursion advantage.

## Day / night

Day full-30m episodes: **6,646**.

```text
mean MFE−MAE = -0.189 ATR
P(MFE > MAE) = 49.71%
trading-day cluster CI mean asymmetry = [-0.440, +0.074]
trading-day cluster CI P(MFE>MAE)     = [47.18%, 52.33%]
```

Night full-30m episodes: **19,875**.

```text
mean MFE−MAE = +0.075 ATR
P(MFE > MAE) = 49.10%
trading-day cluster CI mean asymmetry = [-0.074, +0.226]
trading-day cluster CI P(MFE>MAE)     = [47.72%, 50.48%]
```

Neither session produces a cluster-robust directional short baseline.

## Why clustering changes the answer

On day events, an episode-level resample can make mean MFE−MAE look significantly negative, but the trading-day-cluster interval crosses zero. This is direct evidence that treating many same-day events as IID can create false confidence. M6 will therefore use trading-day clustering as the primary inferential unit.

## Monthly stability

The sign does not persist month-to-month:

```text
day:   mean asymmetry positive 4 months / negative 8 months
night: mean asymmetry positive 7 months / negative 5 months
```

The day monthly mean ranges from about **-1.264 ATR to +0.490 ATR**; night ranges from about **-0.255 ATR to +0.394 ATR**. This variability is documented, not tuned away.

## Balance / structure baseline

The same control group has:

```text
5m median 1-second path efficiency       0.0573
5m median two-sided min excursion        0.412 ATR
30m structure-break rate                 55.54%
```

The 55% break rate must **not** be called a directional Edge: the paired favorable/adverse excursions remain neutral, and Dev7 does not include a non-high-location causal control. It is simply the frozen reference rate that later feature-conditioned groups must beat incrementally.

## Six-timeframe descriptive sensitivity

Using the already-frozen Dev5 first-trigger aggregate, the marginal 30m median MFE-minus-MAE differences are small across all six timeframes:

```text
15s   +0.040 ATR
30s   +0.055 ATR
1m    -0.016 ATR
3m    -0.047 ATR
5m    -0.052 ATR
15m   -0.024 ATR
```

These are marginal-median sensitivities, not paired inference. The formal primary inference remains 1m because Dev5 froze it as the discovery clock.

## What Dev7 adds

1. A real 2024 high-price control baseline before feature conditioning.
2. A frozen M6 analysis firewall separating Primary / Secondary / Exploratory work.
3. Trading-day cluster bootstrap as the primary CI method.
4. A complete test registry so later reports cannot silently omit unattractive comparisons.

## What the result changes next

Because the high-price universe itself is approximately directionally neutral, Dev8 POC features must show **incremental dose-response** relative to this baseline. A single attractive threshold is insufficient.

Dev8 is allowed to proceed only with 2024 and must test the predeclared POC families by decile/quantile. A `NO EDGE` result is an acceptable completion result.
