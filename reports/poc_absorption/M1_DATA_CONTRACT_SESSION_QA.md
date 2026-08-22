# POC Absorption Reversal — M1 Data / Contract / Session QA

> Branch: `research/poc-absorption-reversal-v1`
> Generated from the current uploaded MTX yearly Parquet files on 2026-08-21.

## Verdict

**M1 = PASS_WITH_EXPLICIT_DATA_GAP**.

The physical-order, schema, outright-filter, session, and strict-contract gates pass for all three files. One source-data gap is real and must be carried forward as a blackout: **2024-12-27 regular day session is missing from the 2024 file**, although TAIFEX records show that date was a trading day. Do not synthesize or forward-fill it.

For 2026, the initially apparent missing dates `2026-02-12`, `2026-02-13`, and `2026-07-10` are **not data gaps**: TAIFEX officially had no regular trading on those dates (Lunar New Year pre-holiday closure for Feb 12–13; Typhoon Bavi closure on Jul 10).

## Core file QA

| Year | Physical rows | Physical datetime range | Backward datetime edges | Nulls | Negative volume | Non-outright rows | Outright price range |
|---|---:|---|---:|---:|---:|---:|---|
| 2024 | 50,862,751 | 2023-12-29T15:00:00 → 2024-12-31T13:44:59 | 0 | 0 | 0 | 62 | 17,159–24,449 |
| 2025 | 39,416,621 | 2024-12-31T15:00:00 → 2025-12-19T13:44:59 | 0 | 0 | 0 | 105 | 17,015–28,699 |
| 2026 | 36,158,882 | 2025-12-30T15:00:00 → 2026-08-14T13:44:59 | 0 | 0 | 0 | 11 | 28,782–49,239 |

**Important:** raw `price_min` is not a valid futures-price QA statistic before expiry filtering. The extreme low raw prices in 2024/2025 are spread/combo prices. After `expiry =~ ^\d{6}$`, outright price ranges are normal.

## Same-second physical-order QA

| Year | Equal-datetime physical edges | Runs with ≥2 rows | p99 same-second run length | Max run length | Random blocks checked | Result |
|---|---:|---:|---:|---:|---:|---|
| 2024 | 41,522,864 | 6,355,919 | 45 | 2343 | 100 | PASS |
| 2025 | 31,047,171 | 5,470,616 | 37 | 1127 | 100 | PASS |
| 2026 | 29,743,926 | 4,634,869 | 41 | 874 | 100 | PASS |

All 300 sampled same-second blocks preserve raw contiguous `_seq`; applying the MTX + outright filter preserves the original subsequence order. This supports the hard rule: **assign `_seq` before filtering and never sort same-second ticks.**

## `side` evidence boundary QA

A six-row-group sample per year was compared against `sign(price[t] - price[t-1])` within the same outright expiry, preserving physical order.

| Year | Compared rows | Exact matches | Match rate |
|---|---:|---:|---:|
| 2024 | 6,291,436 | 6,291,436 | 100.000000% |
| 2025 | 5,862,169 | 5,862,169 | 100.000000% |
| 2026 | 6,291,449 | 6,291,449 | 100.000000% |

This strongly confirms that `side` behaves as a **tick-direction proxy** in these files. It must not be renamed to true aggressor side, Bid/Ask delta, CVD, or footprint absorption.

## Session QA

| Year | MTX outright day rows (08:45–13:45) | MTX outright night rows (15:00–05:00) | Other-time rows (all product) |
|---|---:|---:|---:|
| 2024 | 27,016,535 | 23,846,154 | 0 |
| 2025 | 19,861,188 | 19,555,328 | 0 |
| 2026 | 16,896,161 | 19,262,710 | 0 |

The files contain only MTX rows. All physical rows fall in the regular day or after-hours windows used by the existing project.

## Contract QA (day session)

| Year/file scope | Day-session dates in file | strict vs dominant mismatch | strict roll count |
|---|---:|---:|---:|
| 2024 | 241 | 0 | 12 |
| 2025 | 236 | 0 | 12 |
| 2026 | 149 | 0 | 7 |

Across all observed day-session dates, the causal calendar-front selector and completed-day dominant-volume selector chose the same contract. This is diagnostic evidence only; production research remains on **strict causal calendar-front** selection.

### Strict roll dates

- **2024:** 2024-01-18, 2024-02-22, 2024-03-21, 2024-04-18, 2024-05-16, 2024-06-20, 2024-07-18, 2024-08-22, 2024-09-19, 2024-10-17, 2024-11-21, 2024-12-19
- **2025:** 2025-01-16, 2025-02-20, 2025-03-20, 2025-04-17, 2025-05-22, 2025-06-19, 2025-07-17, 2025-08-21, 2025-09-18, 2025-10-16, 2025-11-20, 2025-12-18
- **2026:** 2026-01-22, 2026-02-23, 2026-03-19, 2026-04-16, 2026-05-21, 2026-06-18, 2026-07-16

## Calendar coverage

| Year | Expected regular day sessions through file end | Observed in same calendar year | Missing expected dates | Verified special no-trade dates |
|---|---:|---:|---|---|
| 2024 | 242 | 241 | 2024-12-27 | — |
| 2025 | 236 | 236 | — | — |
| 2026 | 148 | 148 | — | 2026-02-12\|2026-02-13\|2026-07-10 |

### 2024-12-27 source gap

- The 2024 Parquet has **no 08:45–13:45 rows on 2024-12-27**.
- It does contain `2024-12-27 15:00:00–23:59:59` after-hours rows, which belong to the next trading-date attribution context.
- TAIFEX historical records show exchange activity on 2024-12-27. Therefore the absent regular MTX day session is treated as a **source extraction gap**, not an exchange holiday.
- Research rule: `2024-12-27 = DATA_GAP_BLACKOUT`. Any feature requiring the prior regular session must also carry a context-gap flag rather than silently using 2024-12-26.

### 2026 calendar corrections

- TAIFEX states **2026-02-11 was the final trading day before Lunar New Year; 2026-02-12 and 2026-02-13 had no trading**, with the 2/11 after-hours session continuing to 2/12 05:00.
- TAIFEX officially closed the market on **2026-07-10** due to Typhoon Bavi.
- These dates must be encoded as no-trade/closure metadata before any calendar completeness assertion.

## Non-outright contamination evidence

| Year | Non-outright rows | Example expiry family | Raw min price | Outright min price |
|---|---:|---|---:|---:|
| 2024 | 62 | `202401W5/202402` | -42 | 17,159 |
| 2025 | 105 | `202501W4/202502` | -272 | 17,015 |
| 2026 | 11 | `202601W4/202602` | 110 | 28,782 |

This is direct evidence that spread/combination rows **must be removed before any POC, VAH/VAL, channel, ATR, or price-efficiency calculation**.

## M1 carry-forward invariants

1. `_seq` is physical row number and is created before any filter.
2. Never re-sort raw ticks.
3. `product == MTX` and `expiry =~ ^\d{6}$` before profiles/features.
4. Strict causal front-month contract is the production research selector.
5. Day and night sessions remain separate during discovery.
6. `side` is `TDP` / tick-direction proxy only.
7. `2024-12-27` is a hard source-data blackout; do not impute.
8. 2026 special closures (02-12, 02-13, 07-10) are calendar closures, not missing data.

## M1 acceptance status

- Physical row integrity: **PASS**
- Same-second order preservation: **PASS**
- Outright isolation: **PASS**
- Strict contract selection: **PASS**
- Session classification: **PASS**
- Calendar completeness: **PASS WITH ONE EXPLICIT SOURCE GAP (2024-12-27)**
- Evidence boundary for `side`: **PASS as tick-direction proxy; true aggressor semantics rejected**

**Next gate: M2 causal multi-resolution bars + completed/developing POC.**
