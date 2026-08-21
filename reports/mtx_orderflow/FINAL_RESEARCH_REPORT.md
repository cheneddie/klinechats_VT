# MTX 2024–2026 Order-Flow / Short-Horizon Reversal Research — Final Corrected Report

## Executive conclusion

This research began as a validation of the order-flow ideas in arXiv:2505.17388. After correcting data semantics, execution timing, Parquet decoding, cache idempotency, signal-crossing rules and tick-level proxy construction, the evidence does **not** support a deployable MTX order-flow alpha from the available transaction-only data.

The strongest surviving hypothesis is instead:

> **Extreme short-term price selloff -> multi-minute mean reversion.**

The prespecified price-only candidate is:

- signal: 30-second price change
- threshold: rolling previous-3-contract lower 0.05% tail
- event: true crossing from above to at/below threshold
- direction: LONG only
- signal availability: only after the signal second is complete
- latency: one additional second after confirmation
- entry: first observed trade at/after the executable time
- holding: 300 seconds
- exit: first observed trade at/after entry+300s, in the same session only
- cost stress: 0/1/2/3 index points round trip

It passed directional replication in the untouched 2024 holdout, but it does **not** pass the conservative live gate at a 2-point round-trip cost because the contract-block confidence interval still includes zero. Final status: **PAPER-TRADING CANDIDATE — NOT LIVE APPROVED**.

---

## 1. Data semantics and corrections

### Raw files

- 2024: 50,862,751 transaction rows, 49 parquet row groups
- 2025: 39,416,621 transaction rows
- 2026: 36,158,882 transaction rows through 2026-08-14

Columns: `datetime`, `product`, `expiry`, `price`, `volume`, `side`.

### Hard data rules

1. Preserve original parquet row order. Same-second rows are never resorted.
2. Keep only outright expiry values matching `^\d{6}$`; calendar spreads are excluded.
3. Vendor volume is doubled two-sided volume; research volume is `volume/2`.
4. `side` equals tick-price direction, not an independent exchange aggressor flag.
5. Different expiry contracts are never joined into a return path.
6. Day/night session boundaries are explicit; fixed-time positions never exit across a session break.

### Bugs found and corrected during research

The following earlier results were invalidated or downgraded after audit:

- execution used the last price of the next second instead of the first executable print;
- a complete-second signal was treated as knowable too early;
- an in-house Parquet reader incorrectly inferred compression from page sizes;
- interrupted cache construction could append duplicate intermediate rows;
- the first completed lookback window of a session could be incorrectly treated as a threshold crossing;
- a second-level "Aggressive Proxy" signed all volume in a second using a single direction and created an artificial edge.

All final conclusions below use the corrected interpretation and execution model.

---

## 2. Tick-level Aggressive Proxy: rejected

The corrected proxy is computed trade by trade:

```text
if side_i != 0: direction_i = side_i
else:           direction_i = last non-zero direction in same contract/session
proxy_i = direction_i * (volume_i / 2)
```

The carry state resets at a new session. Only after trade-level construction is the proxy aggregated to seconds.

Frozen candidate tested on the corrected proxy:

- lookback 15s
- lower-tail q=0.001
- sell shock -> LONG
- +1s latency after complete-second confirmation
- 240s fixed hold

| Year | N | Gross/Trade | Net @2pt | Gross after removing top 1% winners |
|---|---:|---:|---:|---:|
| 2024 untouched | 1,093 | +0.88 | **-1.12** | -0.30 |
| 2025 | 1,459 | +1.42 | **-0.58** | +0.13 |
| 2026 | 969 | **-2.26** | **-4.26** | -5.19 |

A 48-cell local robustness grid was also checked:

- lookback: 10/15/20/30s
- tail: 0.05/0.10/0.20%
- hold: 180/240/300/450s

Number of cells with positive Net@2 in **both 2025 and 2026**:

```text
0 / 48
```

**Decision: REJECT.**

The previously attractive second-level Aggressive Proxy is classified as **INVALIDATED BY AGGREGATION BIAS**.

---

## 3. Raw TRSV: gross effect exists, live case rejected

Raw tick-rule signed volume:

```text
TRSV_i = side_i * (volume_i / 2)
```

Representative frozen rule: 20s / lower 0.1% / LONG / 300s.

| Year | Gross/Trade | Net @2pt | Gross after removing top 1% winners |
|---|---:|---:|---:|
| 2024 untouched | +1.07 | **-0.93** | -0.26 |
| 2025 | +2.45 | +0.45 | -0.15 |
| 2026 | +2.87 | +0.87 | -0.69 |

Across all 26 evaluated contract blocks, combined Net@2 was approximately +0.18 point/trade, while the contract-block 95% interval was approximately:

```text
[-0.83, +1.22]
```

Additional falsification:

- the previously attractive night-session filter failed in 2024: Net@2 about **-3.47**;
- the high-intensity filter failed in 2024: Net@2 about **-1.01**;
- matched-control incremental TRSV effect was positive in 2025 but slightly negative in 2026;
- volume-shuffle tests did not show stable cross-year dependence on the original volume-size assignment.

**Decision: REJECT FOR LIVE.**

TRSV can still be a research/event descriptor, but current evidence does not justify calling it an independent deployable order-flow alpha.

---

## 4. Price-only candidate: the only surviving paper-trading hypothesis

Prespecified before opening the 2024 holdout:

```text
30-second price change
lower-tail q = 0.0005 (0.05%)
true downward crossing
LONG
1s latency after signal confirmation
first executable print
fixed 300s hold
same-session exit only
```

### Year results

| Year | N | Gross/Trade | Net @2pt | Gross excluding top 1% winners | Positive contracts |
|---|---:|---:|---:|---:|---:|
| **2024 untouched** | 1,179 | **+2.44** | **+0.44** | +0.47 | 6/9 |
| 2025 | 854 | **+2.97** | **+0.97** | -0.57 | 6/9 |
| 2026 | 1,410 | **+4.86** | **+2.86** | +0.72 | 7/8 |
| **Combined** | **3,443** | **+3.56** | **+1.56** | — | **19/26** |

Combined average cost sensitivity:

- Net @1pt: +2.56 points/trade
- Net @2pt: +1.56
- Net @3pt: +0.56

### Contract-block bootstrap

Approximate 95% confidence intervals:

| Metric | Mean | 95% block CI |
|---|---:|---:|
| Gross | +3.56 | **[+1.82, +6.30]** |
| Net @1pt | +2.56 | **[+0.82, +5.30]** |
| Net @2pt | +1.56 | **[-0.18, +4.30]** |
| Net @3pt | +0.56 | **[-1.18, +3.30]** |

The untouched 2024 block by itself had Net@2 roughly +0.44, but its contract-block confidence interval still included zero (approximately `[-1.67, +2.74]`).

### Latency robustness

Net@2 by additional latency after complete-second confirmation:

| Latency | 2024 | 2025 | 2026 |
|---:|---:|---:|---:|
| 0s | +0.47 | +1.17 | +2.77 |
| 1s | **+0.44** | **+0.97** | **+2.86** |
| 2s | +0.34 | +1.16 | +2.58 |
| 5s | -0.07 | +0.74 | +3.43 |
| 10s | -0.04 | +0.39 | +2.37 |

The 2024 holdout therefore indicates that the edge may require execution within roughly 0–2 seconds after confirmation.

### Interpretation

The absolute point threshold varies materially with market volatility across years. This suggests that a future generation should study volatility-normalized selloffs such as:

```text
Z = 30s price change / rolling volatility
```

However, 2024 has now been opened. Any volatility-normalized redesign is a **new strategy generation** and must be validated on future untouched data; 2024 may not be reused as its final holdout.

**Decision: PAPER-TRADING CANDIDATE, NOT LIVE APPROVED.**

---

## 5. What was learned about the paper hypothesis

The available MTX data cannot reproduce true L1 OFI because it lacks bid/ask prices, sizes, depth, queue state and quote updates. The trade-side field is itself derived from transaction-price direction.

After falsification tests, the strongest reproducible market structure is not:

```text
Order Flow Imbalance -> independent future-price alpha
```

but rather:

```text
Extreme short-term selloff -> multi-minute mean reversion
```

Order-flow-like variables can correlate with this state, but their independent incremental information was not stable enough across years to pass the live standard.

---

## 6. Final live-gate decision

### Rejected / invalidated

- true OFI replication: unavailable with current data
- second-level Aggressive Proxy: **INVALIDATED**
- tick-level Aggressive Proxy: **REJECT**
- Raw TRSV as live alpha: **REJECT**
- TRSV night-only regime: **REJECT**
- TRSV high-intensity regime: **REJECT**

### Surviving candidate

- Price 30s / 0.05% selloff / LONG / 300s: **PAPER-TRADING CANDIDATE**

### Why it is not live-approved

1. Net@2 contract-block 95% CI still includes zero.
2. 2024 latency robustness weakens after ~2 seconds.
3. 2025 remains dependent on a small portion of the positive tail.
4. The absolute-point threshold is structurally volatility-dependent.
5. Real bid/ask, queue position and exact slippage are unavailable.

---

## 7. Recommended next operational step

Do **not** optimize this generation further on 2024–2026.

For paper trading, freeze:

```text
Price lookback       30s
Tail                 previous-3-contract 0.05%
Side                 LONG only
Signal               true downward crossing
Confirmation         after complete signal second
Latency assumption   +1s
Entry                first real print thereafter
Hold                 300s
Exit                 first real print >= entry+300s, same session
Cost dashboard       1 / 2 / 3 points
```

Collect new trades prospectively. The next live decision should be made on data that was not available during this research.

---

## 8. Reproduction

`research/mtx_orderflow/final_engine.py` is the canonical deterministic pipeline.

Example:

```bash
python research/mtx_orderflow/final_engine.py build-cache MTX_2024.parquet data/mtx_sec_2024
python research/mtx_orderflow/final_engine.py build-cache MTX_2025.parquet data/mtx_sec_2025
python research/mtx_orderflow/final_engine.py build-cache MTX_2026.parquet data/mtx_sec_2026

# surviving price candidate
python research/mtx_orderflow/final_engine.py backtest data/mtx_sec_2024 \
  --spec price,30,0.0005,300,1,2 \
  --out reports/mtx_orderflow/price_2024.csv

# tick-level proxy falsification candidate
python research/mtx_orderflow/final_engine.py backtest data/mtx_sec_2024 \
  --spec tick_aggr,15,0.001,240,1,2 \
  --out reports/mtx_orderflow/tick_aggr_2024.csv
```

Raw parquet files and generated second-level caches are intentionally not committed.
