# M4 — 2024 Full-Year HIGH_PRICE_PROBE_V1 Universe Distribution

> Research scope: **universe-description only**. No forward outcomes, MFE/MAE, structure-break labels, P&L, threshold optimization, 2025, or 2026 were used.

## Frozen provenance

- Event schema: `POC_PROBE_EVENT_V1`
- Universe: `HIGH_PRICE_PROBE_V1`
- Universe schema: `POC_HIGH_PRICE_PROBE_UNIVERSE_V1`
- Feature schema: `POC_CONTINUOUS_FEATURES_V1`
- Detector config hash: `d7bf39afa32582bc06e00b2df9995b9cb9cc14670a6974834d80cf3d079016fb`
- Source scan: **49/49 Parquet row groups, 50,862,751 physical rows**
- Strict-contract 15s base: **1,062,826 bars** = 288,457 day + 774,369 night
- Observed regular day trading dates: **241** (`2024-01-02` to `2024-12-31`), with `2024-12-27` retained as explicit `DATA_GAP_BLACKOUT`.
- Night-session reporting dates are mapped to the next observed exchange trading date, not naïve calendar `+1 day`.

The detector configuration was frozen before this annual scan and was not changed after any distribution result was observed.

## Six-timeframe consolidated distribution

| TF | Valid bars | Warm bars | Raw triggers | Episodes | Trigger / warm | Episodes / 241 days |
|---|---:|---:|---:|---:|---:|---:|
| 15s | 1,062,826 | 1,062,190 | 264,970 | 111,958 | 24.95% | 464.56 |
| 30s | 539,592 | 538,971 | 132,719 | 56,095 | 24.62% | 232.76 |
| 1m | 270,621 | 270,000 | 66,248 | 27,879 | 24.54% | 115.68 |
| 3m | 90,257 | 89,636 | 22,448 | 9,366 | 25.04% | 38.86 |
| 5m | 54,156 | 53,535 | 13,848 | 5,764 | 25.87% | 23.92 |
| 15m | 18,052 | 17,431 | 5,215 | 2,935 | 29.92% | 12.18 |

The relaxed universe is intentionally broad. Trigger/warm-bar rate is about 24.5–25.9% from 15s through 5m and 29.92% at 15m. This is descriptive, not an optimization target.

## Episode integrity

| TF | Triggers/episode median | P90 | P95 | Max | Duration median | P90 | P95 | Max | >10-trigger episodes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 15s | 2 | 5 | 6 | 22 | 16s | 60s | 75s | 358s | 302 |
| 30s | 2 | 5 | 6 | 19 | 31s | 120s | 150s | 540s | 147 |
| 1m | 2 | 5 | 6 | 16 | 62s | 240s | 300s | 900s | 76 |
| 3m | 2 | 5 | 6 | 11 | 182s | 720s | 900s | 1800s | 9 |
| 5m | 2 | 5 | 6 | 7 | 302s | 1200s | 1514s | 1800s | 0 |
| 15m | 2 | 3 | 3 | 3 | 902s | 1800s | 1800s | 1800s | 0 |

Short-timeframe long tails exist but are rare: >10-trigger episodes are 0.27% at 15s, 0.26% at 30s, 0.27% at 1m, 0.096% at 3m, and zero at 5m/15m. Therefore future inference must cluster by episode and trading day; raw triggers are not treated as IID observations.

### Episode trigger-count buckets

| TF | 1 | 2–5 | 6–10 | >10 |
|---|---:|---:|---:|---:|
| 15s | 44,297 | 61,359 | 6,000 | 302 |
| 30s | 21,885 | 31,195 | 2,868 | 147 |
| 1m | 10,837 | 15,532 | 1,434 | 76 |
| 3m | 3,569 | 5,239 | 549 | 9 |
| 5m | 2,192 | 3,169 | 403 | 0 |
| 15m | 1,048 | 1,887 | 0 | 0 |

### Episode end reasons

| TF | PRICE_EXIT_ATR | MAX_EPISODE_SECONDS | TRADING_DAY_RESET | CONTRACT_RESET | DATA_GAP_RESET | DATASET_END |
|---|---:|---:|---:|---:|---:|---:|
| 15s | 111,860 | 0 | 96 | 2 | 0 | 0 |
| 30s | 55,992 | 0 | 101 | 2 | 0 | 0 |
| 1m | 27,789 | 0 | 89 | 1 | 0 | 0 |
| 3m | 9,254 | 28 | 84 | 0 | 0 | 0 |
| 5m | 5,421 | 255 | 87 | 1 | 0 | 0 |
| 15m | 1,596 | 1,243 | 93 | 3 | 0 | 0 |

Partition boundaries are tracked separately from market-episode termination. For every timeframe the continuity partitions contain **24 CONTRACT_RESET + 1 DATA_GAP_RESET + 2 DATASET_END** boundaries. These are not re-labeled as price-based episode exits.

### Hard integrity gates

| TF | Cross trading day | Cross contract | Cross DATA_GAP |
|---|---:|---:|---:|
| 15s | 0 | 0 | 0 |
| 30s | 0 | 0 | 0 |
| 1m | 0 | 0 | 0 |
| 3m | 0 | 0 | 0 |
| 5m | 0 | 0 | 0 |
| 15m | 0 | 0 | 0 |

All six timeframes pass the hard episode-boundary integrity gate.

## Trigger-reason distribution

| TF | UPPER_80_RANGE_ONLY | BOTH | NEAR_HIGH_0_25ATR_ONLY | BOTH share |
|---|---:|---:|---:|---:|
| 15s | 194,119 | 70,851 | 0 | 26.74% |
| 30s | 101,178 | 31,541 | 0 | 23.77% |
| 1m | 51,757 | 14,491 | 0 | 21.87% |
| 3m | 17,893 | 4,555 | 0 | 20.29% |
| 5m | 10,963 | 2,885 | 0 | 20.83% |
| 15m | 4,164 | 1,051 | 0 | 20.15% |

**Observation only:** `NEAR_HIGH_0_25ATR_ONLY = 0` on every timeframe in 2024. Thus the `near high <= 0.25 ATR` branch adds no extra V1 membership beyond upper-80%-range; it only marks a stricter `BOTH` subset. This does **not** authorize changing V1. Redundancy/incremental information belongs to M6 ablation/dose-response research.

## Session split

| TF | Session | Valid | Warm | Triggers | Episodes | Trigger/warm |
|---|---|---:|---:|---:|---:|---:|
| 15s | day | 288,457 | 288,120 | 69,245 | 28,894 | 24.03% |
| 15s | night | 774,369 | 774,070 | 195,725 | 83,064 | 25.29% |
| 30s | day | 144,240 | 143,918 | 34,944 | 14,296 | 24.28% |
| 30s | night | 395,352 | 395,053 | 97,775 | 41,799 | 24.75% |
| 1m | day | 72,120 | 71,798 | 17,583 | 7,238 | 24.49% |
| 1m | night | 198,501 | 198,202 | 48,665 | 20,641 | 24.55% |
| 3m | day | 24,040 | 23,718 | 6,005 | 2,480 | 25.32% |
| 3m | night | 66,217 | 65,918 | 16,443 | 6,886 | 24.94% |
| 5m | day | 14,424 | 14,102 | 3,671 | 1,526 | 26.03% |
| 5m | night | 39,732 | 39,433 | 10,177 | 4,238 | 25.81% |
| 15m | day | 4,808 | 4,486 | 1,378 | 806 | 30.72% |
| 15m | night | 13,244 | 12,945 | 3,837 | 2,129 | 29.64% |

## Monthly trigger-rate sanity

Rates below are raw triggers / warm bars; no month was selected, excluded, or weighted after inspection.

| Month | 15s | 30s | 1m | 3m | 5m | 15m |
|---|---:|---:|---:|---:|---:|---:|
| 2024-01 | 25.70% | 24.67% | 24.07% | 23.94% | 25.16% | 26.83% |
| 2024-02 | 27.06% | 26.86% | 26.68% | 25.58% | 27.58% | 31.46% |
| 2024-03 | 26.62% | 25.83% | 25.75% | 26.62% | 27.36% | 30.73% |
| 2024-04 | 25.53% | 24.95% | 24.48% | 25.88% | 26.05% | 30.82% |
| 2024-05 | 26.14% | 25.77% | 26.28% | 26.94% | 27.27% | 31.47% |
| 2024-06 | 26.24% | 26.39% | 27.02% | 27.77% | 28.44% | 36.44% |
| 2024-07 | 24.59% | 24.59% | 24.88% | 25.25% | 25.48% | 30.80% |
| 2024-08 | 23.42% | 23.37% | 23.21% | 23.19% | 24.66% | 32.10% |
| 2024-09 | 23.79% | 23.53% | 23.60% | 24.81% | 26.00% | 26.88% |
| 2024-10 | 23.72% | 23.42% | 23.22% | 23.59% | 24.34% | 26.82% |
| 2024-11 | 23.38% | 23.32% | 22.98% | 22.79% | 22.52% | 24.45% |
| 2024-12 | 24.00% | 23.66% | 23.14% | 24.48% | 26.25% | 30.80% |

Monthly ranges are: 15s 23.38–27.06%, 30s 23.32–26.86%, 1m 22.98–27.02%, 3m 22.79–27.77%, 5m 22.52–28.44%, and 15m 24.45–36.44%. The higher 15m dispersion is recorded, not tuned away.

## Time-of-day trigger-rate sanity

| Time | 15s | 30s | 1m | 3m | 5m | 15m |
|---|---:|---:|---:|---:|---:|---:|
| 00:00-02:00 | 26.05% | 26.21% | 26.35% | 26.64% | 26.02% | 26.44% |
| 02:00-05:00 | 25.35% | 24.35% | 24.36% | 24.79% | 25.89% | 27.10% |
| 08:45-09:30 | 27.29% | 28.91% | 30.99% | 32.92% | 33.19% | 34.74% |
| 09:30-10:30 | 24.81% | 25.65% | 25.67% | 27.32% | 27.83% | 29.85% |
| 10:30-11:30 | 23.77% | 24.01% | 24.91% | 26.89% | 27.03% | 31.06% |
| 11:30-12:30 | 22.65% | 21.72% | 21.25% | 20.35% | 22.72% | 30.51% |
| 12:30-13:45 | 22.78% | 22.70% | 21.99% | 22.15% | 22.46% | 29.03% |
| 15:00-18:00 | 25.89% | 25.71% | 25.71% | 28.29% | 31.02% | 36.61% |
| 18:00-21:00 | 25.19% | 24.61% | 24.06% | 23.17% | 23.63% | 33.22% |
| 21:00-24:00 | 24.21% | 23.34% | 22.85% | 22.42% | 22.64% | 24.07% |

Time-of-day differences describe where price spends time in the causal upper-range universe. They are not evidence of reversal edge and are not used to change event selection.

## Contract distribution — raw triggers

| Contract | 15s | 30s | 1m | 3m | 5m | 15m |
|---|---:|---:|---:|---:|---:|---:|
| 202401 | 12,940 | 6,253 | 3,001 | 940 | 537 | 140 |
| 202402 | 20,672 | 10,443 | 5,170 | 1,693 | 1,152 | 472 |
| 202403 | 22,765 | 11,410 | 5,772 | 2,000 | 1,220 | 454 |
| 202404 | 20,170 | 10,005 | 4,869 | 1,694 | 1,036 | 351 |
| 202405 | 22,157 | 11,058 | 5,701 | 2,017 | 1,192 | 484 |
| 202406 | 27,921 | 14,211 | 7,291 | 2,459 | 1,558 | 638 |
| 202407 | 22,491 | 11,361 | 5,742 | 1,999 | 1,180 | 471 |
| 202408 | 23,691 | 11,897 | 5,872 | 1,901 | 1,172 | 481 |
| 202409 | 19,470 | 9,576 | 4,721 | 1,519 | 923 | 321 |
| 202410 | 18,900 | 9,513 | 4,818 | 1,773 | 1,140 | 412 |
| 202411 | 24,463 | 12,183 | 6,046 | 1,996 | 1,198 | 432 |
| 202412 | 21,119 | 10,765 | 5,272 | 1,746 | 1,101 | 426 |
| 202501 | 8,211 | 4,044 | 1,973 | 711 | 439 | 133 |

The machine-readable companion JSON stores valid/warm bars, raw triggers, episodes, and trigger rates for every month, time-of-day bin, contract, and session—not only the counts shown in this Markdown summary.

## M4 research interpretation

1. **Universe breadth is deliberate.** HIGH_PRICE_PROBE_V1 is an opportunity universe, not a signal.
2. **No circular selection was introduced.** POC/TDP/high-zone/efficiency remain attached explanatory variables and never decide event membership.
3. **No annual-result tuning occurred.** The detector hash remained unchanged throughout the 2024 distribution scan.
4. **Episode dependence is controlled but not erased.** All raw probes remain; first-trigger-per-episode is a derived view, and M6 must use clustered inference.
5. **The 0 near-high-only result is a future ablation question, not a reason to rewrite V1.**
6. **M4 makes no predictive/trading claim.** Outcome generation begins only in M5 after this universe is frozen read-only.

## Closure verdict

`REPRODUCIBLE UNBIASED EVENT UNIVERSE PASS`

M4 is eligible to close once the branch head containing this annual evidence passes the unchanged M1–M4 research CI + M3/M4 self-tests. After closure, M5 must treat the M4 event universe as read-only and join outcomes by `event_id`; M5 may not delete, re-rank, or regenerate events based on future paths.
