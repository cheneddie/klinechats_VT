# POC Absorption Reversal — M3 Continuous Features QA

> Branch: `research/poc-absorption-reversal-v1`  
> Feature schema: `POC_CONTINUOUS_FEATURES_V1`  
> Engine: `server/poc_absorption/features.py`

## Verdict

**M3 is eligible for `REPRODUCIBLE CAUSAL FEATURE PASS` only after the committed branch-head CI passes.**

This report records the completed local synthetic + real-data evidence and the exact committed runner required to reproduce it. It does **not** claim strategy edge; M3 only validates causal feature semantics.

## Evidence-chain clarification

The previously reported `18 tests PASS` means the full research chain:

- M1-specific tests: 3
- M2 causal-bar/developing-POC tests: 9
- M3 continuous-feature tests: 6
- Total: **18**

M3 itself has **6 dedicated unit tests**, not 18.

## M3 feature families

V1 stores continuous components rather than a tuned composite signal:

- trend/channel: rolling OLS slope, R², slope/ATR, HH/HL ratios, rolling high/low, channel width, residual dispersion, swing amplitude, alternation;
- POC migration: one-bar delta, velocity 2/3/4/6, velocity/ATR, acceleration, price-vs-POC slope divergence, stall/non-advance/lower-POC counts;
- TDP proxy pressure: signed/positive/negative/neutral volume and tick-count variants;
- high-zone pressure at q70/q80/q90;
- structural high zones based on completed rolling high minus ATR multiples;
- within-bar effort-vs-result components such as impact per positive volume/tick and net advance per positive volume;
- backward-looking rolling normalizations.

No future outcome is used as an M3 predictor. `side` remains tick-direction proxy only; true-aggressor/CVD/footprint semantics are forbidden by QA.

## Dedicated M3 tests

`tests/test_poc_absorption_features.py` checks:

1. completed-feature prefix invariance;
2. positive trend/POC velocity on rising synthetic bars;
3. TDP pressure math and evidence-boundary naming;
4. later-bar mutation cannot change an earlier pressure bar;
5. pressure joins use exact physical bar `_seq` boundaries;
6. structural high-zone features use completed rolling high + ATR only.

The full M1+M2+M3 research suite was run locally from the validated source and produced:

```text
18 passed
```

## Real-data six-timeframe QA

Primary committed QA case:

```text
MTX 2025-08-21
strict contract = 202509
day session = 08:45–13:45
physical ticks = 77,884
```

| Timeframe | Bars | Feature columns | Prefix invariant | TDP volume partition | Bounds/evidence naming | L24 warm rows |
|---|---:|---:|---|---|---|---:|
| 15s | 1,199 | 226 | PASS | PASS | PASS | 1,176 |
| 30s | 600 | 226 | PASS | PASS | PASS | 577 |
| 1m | 300 | 226 | PASS | PASS | PASS | 277 |
| 3m | 100 | 226 | PASS | PASS | PASS | 77 |
| 5m | 60 | 226 | PASS | PASS | PASS | 37 |
| 15m | 20 | 226 | PASS | PASS | PASS | 0 |

A single day has only ~20 completed 15m bars, so a 24-bar lookback correctly remains in warm-up for that one-day case.

## 15m cross-trading-day continuity QA

Second committed QA case:

```text
2025-08-21 + 2025-08-22
contract = 202509
timeframe = 15m
physical ticks = 153,252
bars = 40
L24 warm rows = 17
structural high-zone warm rows = 17
```

This confirms the V1 partition rule:

```text
same contract + same session + no DATA_GAP_BLACKOUT
→ longer lookbacks may continue across consecutive trading days
```

A contract roll or explicit source-data blackout must reset the partition.

### Important slope semantics

`ols_slope_close_L` in V1 is explicitly a **trading-bar-sequence slope**, not a wall-clock-normalized slope. The overnight interval between prior close and next open therefore counts as one next bar step in the regression sequence.

The committed QA runner reports:

- cross-trading-day boundaries;
- `overnight_gap_points`;
- `overnight_gap_atr`;
- `slope_semantics = trading_bar_sequence_not_wall_clock_normalized`.

For the committed continuity case, the measured opening gap is **+11 points = +0.343 ATR** using the prior completed 15m ATR. M6 discovery should compare cross-day and session-local alternatives rather than silently reinterpret the V1 slope.

## Reproducible real-data runner

Exact cases are versioned in:

```text
config/poc_absorption/m3_qa_cases_v1.json
```

The runner is shardable so long QA does not depend on one process surviving every timeframe:

```bash
for tf in 15s 30s 1m 3m 5m 15m; do
  python tools/poc_absorption/m3_feature_qa.py \
    --parquet /path/to/MTX_2025.parquet \
    --cases config/poc_absorption/m3_qa_cases_v1.json \
    --timeframe "$tf" --skip-continuity \
    --output "/tmp/m3_${tf}.json"
done

python tools/poc_absorption/m3_feature_qa.py \
  --parquet /path/to/MTX_2025.parquet \
  --cases config/poc_absorption/m3_qa_cases_v1.json \
  --continuity-only \
  --output /tmp/m3_continuity.json
```

The runner assigns `_seq` from absolute Parquet physical row offsets **before filtering**, never sorts ticks, verifies strict calendar-front contract choice, checks six-timeframe causal features, verifies two-day 15m continuity, and exits non-zero on failure.

CI exercises the same QA code path without private market data using:

```bash
python tools/poc_absorption/m3_feature_qa.py --self-test
```

## Acceptance gates

- Branch source parity with validated `features.py`: **PASS**
- Feature schema/version frozen: **PASS (`POC_CONTINUOUS_FEATURES_V1`)**
- Local M1+M2+M3 suite: **18/18 PASS**
- Local six-timeframe real-data QA: **PASS**
- Local committed-runner reproduction: **PASS**
- Committed M3 unit tests: **PASS / present**
- Committed real-data QA runner: **PASS / present**
- Committed exact QA case config: **PASS / present**
- Committed M3 report: **this file**
- Branch-head research CI: **must pass before Issue #22 M3 is checked**

## Non-claims

M3 does **not** establish that POC slowdown, divergence, pressure, efficiency, or any combination predicts balance/reversal. Those are M4–M8 questions. No threshold, HBA composite, PF, win rate, or production signal is selected here.
