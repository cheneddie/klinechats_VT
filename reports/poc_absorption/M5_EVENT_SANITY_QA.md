# M5 Development 6 — Event Sanity Gate

> **Purpose:** close M5 only after deterministic raw replay plus manual visual inspection. This is an outcome-integrity gate, not an Edge test.

## Verdict

`M5_DEV6_EVENT_SANITY_PASS` is supported by the committed evidence package **only after the exact branch-head Research CI passes**.

No P&L, PF, strategy threshold, best horizon, 2025/2026 data, or Edge claim is introduced here.

## Frozen V5 sanity sample

- Source universe: 2024 **1m first-trigger-per-episode** view: **27,879 episodes** / 66,248 raw 1m triggers.
- Exact sample: **125 unique events**, 25 per category.
- Sample ID SHA-256: `5da7207d36f42601301bbf94173597e2816b9cfb6c61f9c110f5667ec986328d`.
- Per category: 6 day + 19 night, one event per trading date, max 3 events per month.
- Every selected event requires actual same-contract observation span >= 1,740 seconds (29m), not merely theoretical session time.

Categories:

- `strong_mfe`: descending 30m short MFE / frozen ATR.
- `strong_mae`: descending 30m short MAE / frozen ATR.
- `high_balance`: high 5m two-sided excursion + low 5m 1-second path efficiency.
- `structure_reversal`: earliest **trigger-relative** structure-break delay.
- `no_reaction`: joint-low same-session percentile of raw-point and ATR-normalized 30m reaction.

## Why V1–V4 were rejected before closure

1. **V1:** structure examples clustered on one date and no-reaction included horizon-truncated cases.
2. **V2:** `break_second_approx` was an absolute Unix timestamp but was mistakenly ranked as if it were a delay. This selected the earliest calendar dates. Correct metric is `break_second_approx - trigger_sec`.
3. **V3:** theoretical session time did not guarantee same-contract observation. This exposed weekend trading-date attribution and expiry-day front-contract stop cases.
4. **V4:** path-focused plots showed ATR-only no-reaction selection could include 50–99 raw-point moves in very-high-ATR regimes.
5. **V5:** accepted after all four issues were removed.

## Raw physical replay

- **125 / 125 PASS; 0 mismatch.**
- Trigger `_seq`, timestamp and price matched raw Parquet exactly.
- 30m last physical seq is rebuilt from raw timestamp deadline rather than trusting the stored window end.
- Future low/high preserve first physical `_seq` on ties.
- MFE/MAE match the selected outcome store.
- 5m balance efficiency and two-sided excursion are rebuilt independently from raw ticks via 1-second close/high/low.
- First structure-break seq/time/price and simultaneous reference identity are rebuilt from raw physical ticks.
- All V5 samples have actual observation span >= 29m.

## Manual visual review

- Five path-focused contact sheets × 25 events = **125 panels reviewed**.
- **0 visual mismatches.**
- Distant frozen references are not allowed to flatten the plot scale; offscreen references are annotated as point distance instead.
- Strong MFE paths show visible favorable downside excursions; strong MAE paths show adverse upside excursions.
- High-balance is judged on the first 5m measurement; later 30m trending is not treated as a contradiction.
- Structure-reversal break markers visibly cross a frozen eligible reference at/after trigger.
- V5 no-reaction cases are narrow on both raw-point and ATR-normalized scales.

## ATR normalization confound check

- Full 1m first-trigger population ATR median: **7.00 points**.
- Spearman `ATR vs reaction_ATR`: **-0.207**.
- Spearman `ATR vs raw reaction points`: **0.724**.
- Therefore ATR normalization has a real denominator effect, but it does not explain away the strong-MFE/MAE samples: their raw-point reaction ranks remain near the top of the same-session population.
- V5 no-reaction uses both scales specifically so a high ATR denominator cannot by itself create a quiet-event label.

## Category summary

| sanity_category    |   N |   unique_dates |   day |   night |   atr_median |   mfe_points_median |   mfe_atr_median |   mae_points_median |   mae_atr_median |   balance_eff_5m_median |   two_sided_5m_atr_median |   break_30m_rate |   observed_span_min |
|:-------------------|----:|---------------:|------:|--------:|-------------:|--------------------:|-----------------:|--------------------:|-----------------:|------------------------:|--------------------------:|-----------------:|--------------------:|
| high_balance       |  25 |             25 |     6 |      19 |       4.0000 |             14.0000 |           3.0000 |             10.0000 |           3.1644 |                  0.0000 |                    1.5000 |           0.7200 |           1788.0000 |
| no_reaction        |  25 |             25 |     6 |      19 |       3.8571 |              4.0000 |           1.1098 |              4.0000 |           1.0980 |                  0.0400 |                    0.4828 |           0.0000 |           1760.0000 |
| strong_mae         |  25 |             25 |     6 |      19 |       4.7857 |              7.0000 |           1.7500 |            119.0000 |          24.1111 |                  0.1045 |                    0.3590 |           0.4800 |           1795.0000 |
| strong_mfe         |  25 |             25 |     6 |      19 |       4.2857 |            127.0000 |          26.4444 |              2.0000 |           0.4375 |                  0.0968 |                    0.2979 |           1.0000 |           1765.0000 |
| structure_reversal |  25 |             25 |     6 |      19 |       7.7143 |             29.0000 |           3.8182 |             22.0000 |           3.5660 |                  0.0526 |                    0.3684 |           1.0000 |           1798.0000 |

## Acceptance

- deterministic sample integrity: **PASS**
- same-contract observation eligibility: **PASS**
- raw physical replay: **PASS**
- 5m balance rebuild: **PASS**
- structure-break physical ordering: **PASS**
- manual 125-panel review: **PASS**
- strategy/P&L semantics introduced: **NO**

When the exact Dev6 branch-head CI is green, M5 may close with:

# `REPRODUCIBLE PHYSICAL-TICK OUTCOME CUBE PASS`
