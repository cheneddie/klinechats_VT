# MTX Price Reversal V2 — Production Edge Validation & Risk Engine

This branch is the forward-validation successor to the frozen historical baseline in `research/mtx-price-reversal-2024-2026`.

## Goal

Convert the historical extreme-selloff reversal phenomenon into a causal, reproducible, risk-bounded, execution-aware MTX strategy that can only graduate through frozen forward OOS, paper parity and live gates.

## Non-negotiable invariants

1. Preserve raw Parquet physical row order. Equal-second ticks are never re-sorted.
2. `_seq` is assigned before filtering.
3. Only outright expiries matching `^\d{6}$` are eligible.
4. Vendor `volume` is two-sided; research one-sided volume is `volume/2`.
5. `side` is tick-direction data, not true bid/ask aggressor side.
6. Signal second must be complete before it is known.
7. Frozen baseline execution uses one additional second latency and first tradable print.
8. One position at a time; same-session flat.
9. Stop/target/trailing ordering must use physical tick sequence, never second OHLC ordering.
10. New OOS data may not be used to tune rules after its watermark begins.

## Frozen historical control

`30s price selloff / prior 3 completed contracts / lower 0.05% / LONG / +1s latency after complete-second confirmation / first tradable print / 300s same-session exit / one position / 2pt primary friction`.

Golden historical metrics:

- Trades: 3,655
- Net@2 total: +5,104 points
- PF: 1.059 (rounded)
- Net@2 expectancy: +1.396 points/trade
- Max DD: -3,086 points

## V2 development order

1. Governance + OOS lock
2. Zero-change modular migration + golden regression
3. Physical tick execution/risk engine
4. Causal regime engine
5. Risk lab (structural + catastrophic)
6. Post-entry path-state management research
7. Freeze production candidate
8. Forward OOS append-only runner
9. Cluster-aware inference
10. Historical/live parity
11. Paper trading
12. Limited live only after all gates pass

See `SPEC.md`, `HYPOTHESIS_REGISTRY.md`, and `RESEARCH_STATUS.md`.
