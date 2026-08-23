# M5 Development 5 — 2024 Full Outcome Cube

> Verdict candidate: `M5_DEV5_2024_FULL_OUTCOME_CUBE_PASS`  
> Formal closure requires exact branch-head Research CI.  
> M5 remains OPEN because Development 6 Event Sanity is still required.

## Scope

2024 only. Six frozen event timeframes are measured from the Dev1–Dev4 physical-tick outcome store. No P&L, PF, threshold tuning, best-horizon optimization, 2025, or 2026 data is used.

## Integrity

- source physical rows: **50,862,751**
- strict selected rows: **50,862,621**; removed **130**
- outcome fragments: **482**
- outcome rows / unique event_id: **505,448 / 505,448**
- fragment schema mismatches: **0**
- duplicate event_id: **0**
- 2024-12-27 remains a day-session `DATA_GAP_BLACKOUT`; night continuity follows frozen M4 annual semantics.

Frozen M4 annual parity is exact:

| TF | Events | Episodes |
|---|---:|---:|
| 15s | 264,970 | 111,958 |
| 30s | 132,719 | 56,095 |
| 1m | 66,248 | 27,879 |
| 3m | 22,448 | 9,366 |
| 5m | 13,848 | 5,764 |
| 15m | 5,215 | 2,935 |

## Independent raw audit

`M5_DEV5_FULL_YEAR_AUDIT_V1`: 60 seedless SHA256-selected events (5 per TF × session) plus 12 deterministic zero-future/session-boundary cases. **72 events × 8 horizons = 576 windows; 576/576 PASS, 0 mismatch.**

Candidate event-set hash: `b94b39f18cc202ea3628b8f412868616566e255dbeeda78d35b07972b88c7aa5`  
Selected 60-event hash: `94a85a0898cfa3666743a737530d55dc69c65b459b2e1a4b4e9156bafd4b9df4`

## First-trigger / episode view

| TF | N | 30s MFE ATR | 5m MFE ATR | 30m MFE ATR | 30m MAE ATR | Break 5m | Break 30m | Session-end break |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 15s | 111,958 | .622 | 2.131 | 5.040 | 5.000 | 48.9% | 75.7% | 89.3% |
| 30s | 56,095 | .412 | 1.431 | 3.402 | 3.347 | 35.0% | 67.1% | 85.6% |
| 1m | 27,879 | .284 | .949 | 2.278 | 2.294 | 20.9% | 55.2% | 80.1% |
| 3m | 9,366 | .149 | .510 | 1.226 | 1.273 | 6.2% | 32.1% | 67.4% |
| 5m | 5,764 | .117 | .378 | .915 | .968 | 3.4% | 21.9% | 59.1% |
| 15m | 2,935 | .064 | .200 | .457 | .480 | 1.6% | 7.1% | 37.6% |

## Research-value interpretation — not an edge claim

Primary discovery clock: **1m**. Companion/robustness clock: **30s**. Microstructure-sensitivity clock: **15s**.

1m retains 27,879 first-trigger episodes and non-degenerate structure-break outcomes, making it a practical central scale for M6 dose-response/ablation. 30s keeps 56,095 episodes and stronger short-horizon movement, so it remains a companion scale. 15s has the largest sample and strongest short-horizon movement but also the greatest raw-trigger dependence and microstructure sensitivity, so it is not automatically declared best.

This is not a profitability ranking. Dev5 selects no trading threshold, P&L rule, PF target, or best horizon.

## Reproducibility

- `server/poc_absorption/full_outcome_cube.py`
- `tests/test_poc_absorption_full_outcome_cube.py`
- `tools/poc_absorption/m5_full_outcome_cube_qa.py`
- `config/poc_absorption/m5_full_outcome_cube_v1.json`
- `reports/poc_absorption/M5_DEV5_2024_FULL_OUTCOME_CUBE.csv`
- `reports/poc_absorption/M5_DEV5_2024_SESSION_SPLIT_FIRST_TRIGGER.csv`
- `reports/poc_absorption/M5_DEV5_FORMAL_QA_SUMMARY.json`

Development 6 must not begin until the exact branch head containing this package passes Research CI.
