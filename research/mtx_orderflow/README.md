# MTX 2025 Order-Flow / Price-Response Research

Research branch for validating the hypotheses in arXiv:2505.17388 against the uploaded MTX 2025 transaction data.

## Important data semantics

The uploaded file has columns:

- `datetime`
- `product`
- `expiry`
- `price`
- `volume`
- `side`

Phase-1 audit found that `side` is **not an independent aggressor-side label**. In sampled row groups across the year:

```text
side == sign(price_t - price_{t-1})
```

matched 100% for adjacent rows of the same outright contract. Therefore this project calls volume signed with this field **Tick-Rule Signed Volume (TRSV)**, not true Trade Imbalance (TI) and not L1 Order Flow Imbalance (OFI).

The paper's L1 OFI cannot be reproduced exactly without best bid/ask price and size. The data can still validate price-direction persistence, signed-volume state, shock/response decay, event-time vs clock-time decay, regime dependence, MFE/MAE, cost sensitivity and executable position logic.

## Research rules

1. Preserve original parquet row order. Never re-sort equal-second records by price, side or volume.
2. Only `expiry` matching `^\d{6}$` is an outright contract. Calendar-spread records such as `202501W4/202502` are audited separately and excluded from outright price-return calculations.
3. Never call TRSV `OFI` or true aggressor TI.
4. Never use random train/test splits for overlapping forward returns.
5. Thresholds and normalization parameters must be estimated on train data only.
6. Report gross results and 0/1/2/3-tick cost sensitivity separately.
7. Do not call aggregate overlapping forward returns a strategy PnL.
8. A candidate is acceptable only if it survives walk-forward OOS, parameter perturbation and regime splits.

## Planned phases

### Phase 1 — Data integrity and semantics

- schema / row count / time range
- outright vs spread-expiry separation
- monotonic timestamp check while preserving row sequence
- `side` semantic validation
- volume-unit audit
- contract-roll boundaries

### Phase 2 — Memory and null models

Study both clock time and event time:

- direction ACF / transition probabilities
- TRSV ACF
- run-length / switching statistics
- single exponential vs double exponential vs power-law decay
- shuffled and block-shuffled null tests

### Phase 3 — Shock discovery and response surface

Candidate signals include:

- rolling TRSV
- normalized signed volume
- direction-count imbalance
- run length
- flow acceleration
- trade intensity

For each signal, produce `lookback × shock-strength × forecast-horizon` surfaces in seconds and event counts.

### Phase 4 — Trading-path validation

For non-overlapping shock episodes report:

- N
- mean / median forward move
- directional hit rate
- MFE / MAE
- first-hit target/stop probability
- peak impact time
- alpha half-life
- zero-crossing / reversal time

### Phase 5 — Continuation vs absorption proxy

Without L1 depth, absorption cannot be observed directly. We can only study a transaction-data proxy:

```text
FlowEfficiency = price_move / abs(signed_volume)
```

Strong signed flow with weak/negative price response is treated as a **candidate absorption/failure state**, not proof of passive-book absorption.

### Phase 6 — Regimes

Rolling regime features:

- realized volatility
- trade intensity
- direction-memory score
- flow efficiency
- day/night session
- time of day
- roll proximity

### Phase 7 — Executable backtest

Use one explicit position state, no independent overlapping pseudo-trades. Compare:

- fixed holding time
- signal-decay exit
- opposite-flow exit
- dynamic holding time
- target/stop combinations

Because bid/ask is unavailable, use explicit 0/1/2/3-tick round-trip cost scenarios instead of pretending to know exact queue/slippage.

### Phase 8 — Walk-forward falsification

- chronological walk-forward
- purge/embargo overlapping labels
- parameter plateau tests
- remove-best-month test
- remove-top-1%-trade test
- day/night split
- volatility/intensity split
- contract-month split

## Reproduction

The normal project environment already declares `numpy`, `pandas`, and `pyarrow` in `requirements-data.txt`.

Run:

```bash
python research/mtx_orderflow/phase1_audit.py /path/to/MTX_2025.parquet --out reports/mtx_orderflow
```

Phase-1 writes JSON/CSV audit artifacts and is intentionally conservative: it identifies what the data **can** prove before any alpha fitting is attempted.
