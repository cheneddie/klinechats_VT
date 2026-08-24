# M6 Dev10 — Trend / Broad Channel Contribution (2024)

Formal verdict: `M6_DEV10_TREND_BROAD_CHANNEL_NO_INCREMENTAL_SHORT_EDGE`.

The frozen HIGH_PRICE_PROBE universe is not re-filtered. Primary context uses 24 completed 1m bars. Rising is fixed causally as `slope_atr_24 > 0`; Broad is within-session channel-width-ATR rank >= 0.50. No outcome-derived context cutoff is optimized.

Hard geometry parity: event `channel_width_atr_24` equals the frozen M4 `(rolling_high - rolling_low)/ATR` exactly (max absolute difference 0).

The universe is already 89.31% Rising and 48.90% Rising+Broad, so the high-price probe embeds substantial trend context before Dev10.

Across 128 actually tested context hypotheses (L24 binary contrasts overall and within Low Efficiency, continuous slope/width/R²/residual-std ranks for L6/8/12/16/24, plus direct Broad-vs-Tight within Rising diagnostics), **zero** survives global BH q<=0.10; minimum global q is about 0.321.

Primary Rising+Broad vs other context has no reliable 15m/30m directional-probability increment, both in the full universe and the Low-Efficiency subset. Direct Broad-vs-Tight within Rising gives about -0.14 pp at 15m and -0.74 pp at 30m; monthly signs are unstable. There are unadjusted hints that stronger slope/high R² may worsen short MFE−MAE (trend continuation), but these do not survive multiplicity correction and are not promoted to HARMFUL.

Functional classification: `REDUNDANT_FOR_SHORT_DIRECTION_WITH_UNADJUSTED_TREND_CONTINUATION_HINT`.

No P&L/PF, threshold optimization, 2025 data or 2026 data was used.
