# MTX 2025 × arXiv:2505.17388 — Phase 1 Data Audit

Status: **completed initial full-file structural audit; alpha claims intentionally not made yet**.

## 1. Dataset summary

Uploaded parquet structural audit:

| Item | Result |
|---|---:|
| Total rows | 39,416,621 |
| Parquet row groups | 38 |
| Columns | datetime, product, expiry, price, volume, side |
| Product | MTX |
| Earliest timestamp | 2024-12-31 15:00:00 |
| Latest timestamp | 2025-12-19 13:44:59 |
| Outright rows (`expiry=YYYYMM`) | 39,416,516 |
| Calendar-spread / non-outright rows | 105 |
| Outright price range | 17,015–28,699 |
| Volume range | 2–6,218 |
| GCD of observed volume values | 2 |
| Timestamp backwards transitions | 0 |
| Adjacent rows with identical second timestamp | 31,047,171 (78.77%) |

The file is sufficiently large for robust regime, tail-shock, event-time and walk-forward research, but the semantics of `side` and `volume` materially constrain what may be called “order flow”.

## 2. Calendar-spread contamination found and isolated

Low/negative prices initially looked like bad ticks, but inspection showed they belong to spread expiries rather than outright MTX contracts. Examples:

- `202501W4/202502`: 9 rows, prices around 36–41
- `202502W4/202503`: 16 rows, prices around -7 to -15
- `202504W4/202505`: 36 rows
- `202505W4/202506`: 1 row
- `202506W4/202507`: 10 rows
- `202507W5/202508`: 1 row
- `202508W4/202509`: 20 rows
- `202511W4/202512`: 11 rows, prices around -33 to -22
- `202512W4/202601`: 1 row, price 42

**Decision:** do not delete these by arbitrary price thresholds. Exclude them from outright-return research by contract semantics (`expiry` must match `^\d{6}$`) and retain them in audit output.

## 3. Critical finding: `side` is tick-price direction, not independent aggressor side

Across sampled row groups spanning the year, for adjacent rows belonging to the same outright contract:

```text
side == sign(price_t - price_{t-1})
```

matched **100%**.

Sampled adjacent same-contract pairs: approximately 4.81 million.

Observed mapping:

- price rises → `side = +1`
- price unchanged → `side = 0`
- price falls → `side = -1`

Therefore `side` must not be described as exchange-confirmed aggressive buyer/seller direction unless independent vendor documentation proves otherwise.

### Consequence for the paper replication

The paper’s true L1 OFI requires best bid/ask price and size. This dataset does not contain those fields.

A volume-weighted use of `side` in this file produces:

```text
TRSV_t = side_t × volume_t
```

which this project names **Tick-Rule Signed Volume (TRSV)**.

TRSV can be a useful transaction-flow proxy, but it is mechanically tied to current price movement. Any predictive test must therefore use strictly future, non-overlapping price responses and matched/null controls to avoid mistaking contemporaneous price motion for order-flow alpha.

## 4. Full-file `side` distribution

| Side | Rows | Share |
|---:|---:|---:|
| -1 | 11,025,973 | 27.97% |
| 0 | 17,396,367 | 44.13% |
| +1 | 10,994,281 | 27.89% |

For outright rows with non-zero `side`, the mean sign is approximately -0.00144, close to directionally balanced over the full sample.

## 5. Diagnostic event-time pattern

When zero-price-change rows are removed and the non-zero `side` sequence is treated strictly as **price-direction states**, not buyer/seller flow, the preliminary same-direction probabilities are:

| Event lag | Same-direction probability |
|---:|---:|
| 1 | 26.75% |
| 2 | 57.79% |
| 5 | 49.21% |
| 10 | 50.10% |
| 20 | 50.02% |
| 50 | 50.02% |
| 100 | 49.99% |
| 200 | 50.02% |
| 500 | 50.02% |

This is **not** the persistent aggressor-flow memory described in the paper. It shows strong one-step alternation and a two-step echo in transaction-price direction, then rapidly approaches 50%.

That finding is useful because it falsifies a naive interpretation of the supplied `side` as ordinary buy/sell order-flow persistence.

## 6. Volume-unit warning

All observed volume values have a GCD of 2, with minimum 2. This strongly suggests the vendor/source may be representing matched volume in a doubled or two-sided convention.

Until source semantics are independently verified:

- normalized volume ratios are acceptable because a common multiplier cancels;
- absolute “contracts” and “price impact per contract” must be labelled provisional;
- do not divide by two silently in research code.

## 7. What can now be validated responsibly

### High-confidence with this dataset

- transaction price-direction memory
- TRSV proxy memory
- event-time vs clock-time decay
- signed-volume shock response
- shock-strength × horizon surfaces
- MFE / MAE after proxy shocks
- continuation/failure states
- intraday and volatility regimes
- executable non-overlapping position logic
- walk-forward stability
- 0/1/2/3-tick cost sensitivity

### Cannot be directly validated from this file

- true L1 OFI
- best-bid/best-ask depth
- queue position
- exact spread at each trade
- exact aggressor side unless separately documented
- sub-second timing inside records sharing the same second

## 8. Immediate next tests

The next research phase will deliberately compare three different objects rather than conflating them:

1. **PriceDirection**: `sign(Δprice)`
2. **TRSV proxy**: `sign(Δprice) × volume`
3. **Price-independent controls**: volume, trade intensity, time-of-day, volatility and lagged price state

Primary test:

```text
TRSV shock at t
        ↓
strictly future return / MFE / MAE
        ↓
matched control with similar momentum, volatility, time-of-day and trade intensity
```

Only incremental forward response beyond the matched price-state control will be treated as candidate flow information.

## 9. Research decision after Phase 1

**Do not attempt to reproduce the paper's OFI regression literally with this dataset.** That would produce a misleading result.

Proceed instead with a falsification-oriented proxy study:

```text
Tick-rule signed-volume state
→ shock definition
→ incremental future response
→ alpha decay
→ regime dependence
→ transaction-cost robustness
→ walk-forward strategy candidate
```

If that proxy fails after controls, the conclusion is that this file cannot validate the paper’s order-flow alpha. If it survives, the result is a potentially useful MTX transaction-flow strategy hypothesis, but still distinct from true L1 OFI.
