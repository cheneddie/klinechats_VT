# MTX 2024–2026 Order-Flow / Price-Response Research

This branch is a standalone research branch. It is **not intended to merge into `main`**.

The project began by testing ideas from arXiv:2505.17388 against MTX transaction data. The final corrected conclusion is that the available transaction-only data do **not** support a live-deployable independent order-flow alpha. The only surviving hypothesis is an extreme short-term **price** selloff followed by multi-minute mean reversion.

## Final status

| Candidate | Status |
|---|---|
| True L1 OFI | Cannot reproduce with current data |
| Second-level Aggressive Proxy | **INVALIDATED** by aggregation bias |
| Tick-level Aggressive Proxy | **REJECT** |
| Raw TRSV | **REJECT FOR LIVE** |
| TRSV Night / High-Intensity regimes | **REJECT** after 2024 holdout |
| Price 30s / lower 0.05% / Long / 300s | **PAPER-TRADING CANDIDATE** |

The price-only candidate is **not live approved** because its Net@2 contract-block 95% confidence interval still includes zero and the untouched 2024 sample weakens when execution latency exceeds roughly 2 seconds.

See:

- `reports/mtx_orderflow/FINAL_RESEARCH_REPORT.md`
- `reports/mtx_orderflow/2024_UNTOUCHED_HOLDOUT.md`
- `reports/mtx_orderflow/FINAL_SUMMARY.csv`
- `reports/mtx_orderflow/LIVE_GATE_SCORECARD.csv`

## Critical data semantics

Raw columns:

- `datetime`
- `product`
- `expiry`
- `price`
- `volume`
- `side`

Rules:

1. Preserve original parquet row order. Never re-sort same-second trades.
2. Keep only outright expiry strings matching `^\d{6}$`; remove calendar spreads.
3. Vendor volume is doubled two-sided volume; divide by 2.
4. `side` is tick-price direction, not an independent exchange aggressor flag.
5. Never call TRSV true OFI/TI.
6. Never join different expiry contracts into one return path.
7. A complete-second signal becomes knowable only after that second ends.
8. Entry uses the **first real print** after confirmation + latency, never the second close.
9. Fixed-time exits must remain in the same session.
10. Thresholds use only previous completed contracts.

## Corrected Tick-level Aggressive Proxy

For every trade:

```text
if side_i != 0:
    direction_i = side_i
else:
    direction_i = previous non-zero direction in the same contract/session

proxy_i = direction_i * (volume_i / 2)
```

Direction carry resets at every new session. The proxy is built trade-by-trade **before** aggregating to seconds.

This corrected proxy rejected the earlier second-level result.

## Canonical reproduction engine

Use:

`research/mtx_orderflow/final_engine.py`

Build deterministic second caches:

```bash
python research/mtx_orderflow/final_engine.py build-cache /data/MTX_2024.parquet data/mtx_sec_2024
python research/mtx_orderflow/final_engine.py build-cache /data/MTX_2025.parquet data/mtx_sec_2025
python research/mtx_orderflow/final_engine.py build-cache /data/MTX_2026.parquet data/mtx_sec_2026
```

Run the surviving paper-trading candidate:

```bash
python research/mtx_orderflow/final_engine.py backtest data/mtx_sec_2024 \
  --spec price,30,0.0005,300,1,2 \
  --out reports/mtx_orderflow/price_2024.csv
```

Run the rejected Tick-level Aggressive Proxy for reproducibility:

```bash
python research/mtx_orderflow/final_engine.py backtest data/mtx_sec_2024 \
  --spec tick_aggr,15,0.001,240,1,2 \
  --out reports/mtx_orderflow/tick_aggr_2024.csv
```

`requirements-data.txt` already declares `numpy`, `pandas`, and `pyarrow`.

## Research integrity notes

Several bugs were found and corrected during the project: execution-time indexing, too-early signal availability, a temporary Parquet page-decoding implementation, non-idempotent cache append logic, session-first-window pseudo-crossings, and second-level aggressor aggregation bias. Earlier figures affected by these issues are retained only as research history; the final report is authoritative.

Do not optimize a new generation on 2024–2026 and then call those years untouched. Any volatility-normalized or otherwise redesigned strategy must be validated prospectively on new data.
