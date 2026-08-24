# M6 Dev9 — Pressure × Efficiency 2D Edge Map (2024)

## Formal verdict

`M6_DEV9_ORIGINAL_BUYING_ABSORPTION_INTERACTION_NOT_SUPPORTED`

Dev9 asks whether the visual red-circle idea — high buying-pressure proxy with low price efficiency — adds information beyond low efficiency alone. It does **not** support promoting the buying-pressure proxy to a directional short signal.

## Reproducibility gates

- source physical rows: 50,862,751
- strict-selected rows: 50,862,621
- 1m bars: 270,621
- M4 raw triggers / first-trigger episodes: 66,248 / 27,879
- day / night episodes: 7,238 / 20,641
- comparable 30m events: 26,521
- Dev7 baseline independently reproduced before Dev9 inference.

## Predeclared 2×2 map

A = low pressure + high efficiency; B = low pressure + low efficiency; C = high pressure + high efficiency; D = high pressure + low efficiency. The key incremental contrast is **D − B**. Pressure is q80 high-zone positive-volume magnitude; efficiency is impact per 1,000 positive-volume; both are split by within-session percentile median.

Primary D−B results:

- 5m 1-second path efficiency: -0.012511
- 5m two-sided excursion: +0.014757 ATR
- 15m P(MFE>MAE): +0.553 pp
- 30m P(MFE>MAE): +0.559 pp

The apparent low future path-efficiency in D does **not** become a reliable short-direction probability advantage.

## Activity confound

q80 high-zone positive volume correlates 0.842 with total bar volume and 0.809 with tick count. After causal activity/range/session/zone-composition controls, the q80 future path-efficiency coefficient is -0.00089 with CI crossing zero.

When pressure is normalized by total activity, the sign reverses: q80 concentration coefficient +0.00476 and q90 +0.00808. Thus the raw magnitude effect is primarily an **activity regime** effect, not evidence of directional buying absorption.

## Negative controls / evidence boundary

The continuous activity × low-efficiency interaction is present for positive volume, negative volume and total volume. Therefore it is not buy-side specific. Directional proxies (`high_zone_tdp`, `high_zone_positive_share`) do not produce a robust positive short effect; q80 positive-share is associated with about -3.10 pp 30m midline-break probability in the low-efficiency subset.

## Functional classification

- buy-direction pressure: `REDUNDANT_OR_CONTRADICTORY_FOR_SHORT_DIRECTION`
- raw pressure magnitude: `ACTIVITY_REGIME_ONLY`
- price efficiency: `STATE_PERSISTENCE_NOT_DIRECTIONAL_EDGE`
- pressure × efficiency: `NOT_BUY_SIDE_SPECIFIC_ACTIVITY_X_EFFICIENCY_INTERACTION`

No P&L, PF, execution model, optimized cutoff, 2025 data or 2026 data was used. Dev9 closes a hypothesis; it does **not** create a production short signal.
