# POC Absorption Reversal — M3 Continuous Features QA

> Branch: `research/poc-absorption-reversal-v1`  
> Feature schema: `POC_CONTINUOUS_FEATURES_V1`  
> Engine: `server/poc_absorption/features.py`

## Verdict

**`REPRODUCIBLE CAUSAL FEATURE PASS`**

M3 validates causal feature semantics and reproducibility only. It does **not** claim strategy edge.

## Reproducibility evidence

The committed research chain contains:

- M1-specific tests: 3
- M2 causal-bar / developing-POC tests: 9
- M3 continuous-feature tests: 6
- Total: **18 tests**

M3 itself has **6 dedicated feature tests**; the earlier `18 tests PASS` refers to the complete M1+M2+M3 research chain.

Committed evidence:

- `tests/test_poc_absorption_features.py`
- `tools/poc_absorption/m3_feature_qa.py`
- `config/poc_absorption/m3_qa_cases_v1.json`
- `.github/workflows/poc-absorption-research-ci.yml`
- this report

## Feature families

V1 stores continuous components instead of a tuned composite signal:

- trend/channel: OLS slope, R², slope/ATR, HH/HL ratios, rolling high/low, channel width, residual dispersion, swing amplitude, alternation;
- POC migration: delta, velocity 2/3/4/6, velocity/ATR, acceleration, price-vs-POC slope divergence, non-advance/lower-POC/stall counts;
- TDP proxy pressure: signed/positive/negative/neutral volume and tick-count variants;
- high-zone pressure at q70/q80/q90;
- structural high zones based on completed rolling high minus ATR multiples;
- within-bar effort-vs-result components;
- backward-looking rolling normalizations.

No future outcome is used as an M3 predictor. `side` remains tick-direction proxy only; true-aggressor, CVD, footprint, or similar semantics are forbidden.

## Local real-data six-timeframe QA

Primary case:

```text
MTX 2025-08-21
strict contract = 202509
day session = 08:45–13:45
physical ticks = 77,884
```

| Timeframe | Bars | Feature columns | Prefix invariant | TDP volume partition | Bounds / evidence naming | L24 warm rows |
|---|---:|---:|---|---|---|---:|
| 15s | 1,199 | 226 | PASS | PASS | PASS | 1,176 |
| 30s | 600 | 226 | PASS | PASS | PASS | 577 |
| 1m | 300 | 226 | PASS | PASS | PASS | 277 |
| 3m | 100 | 226 | PASS | PASS | PASS | 77 |
| 5m | 60 | 226 | PASS | PASS | PASS | 37 |
| 15m | 20 | 226 | PASS | PASS | PASS | 0 |

A single day has only ~20 completed 15m bars, so a 24-bar lookback correctly remains in warm-up for the one-day 15m case.

## Cross-trading-day continuity QA

```text
2025-08-21 + 2025-08-22
contract = 202509
timeframe = 15m
physical ticks = 153,252
bars = 40
L24 warm rows = 17
structural high-zone warm rows = 17
```

Partition rule:

```text
same contract + same session + no DATA_GAP_BLACKOUT
→ long lookbacks may continue across consecutive valid trading days
```

Contract roll or explicit source-data blackout resets the partition.

### Slope semantics

`ols_slope_close_L` V1 is a **trading-bar-sequence slope**, not a wall-clock-normalized slope. The committed QA runner explicitly reports overnight-gap diagnostics. For the committed continuity case:

```text
overnight_gap_points = +11
overnight_gap_atr ≈ +0.343
slope_semantics = trading_bar_sequence_not_wall_clock_normalized
```

M6 should compare cross-day versus session-local alternatives instead of silently reinterpreting V1 slope semantics.

## Reproducible runner

The runner is shardable so long QA does not depend on one process surviving all timeframes:

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

The runner assigns absolute physical `_seq` before filtering, never sorts ticks, verifies strict calendar-front contract choice, checks causal feature invariants, and exits non-zero on failure.

## Branch-head GitHub CI evidence

Draft validation PR: **#23** — intentionally kept Draft / unmerged.  
Validated branch head: **`d9226087ce493130565c256cedc18e62f42b7493`**  
Workflow: **POC Absorption Research CI**  
Run: **#6 / `32498120978`**  
Job: **`96821291053`**  
Conclusion: **SUCCESS**

The GitHub runner checked out the PR merge generated from branch head `d9226087...`, installed CPython 3.13.15 and data dependencies, then executed the committed gates:

```text
.................. [100%]
18 passed in 0.87s
```

The committed M3 QA runner self-test then returned:

```text
schema_version: POC_M3_QA_SELF_TEST_V1
feature_schema_version: POC_CONTINUOUS_FEATURES_V1
ticks: 90
bars: 30
feature_columns: 226
warm_feature_rows: 7
structural_zone_rows: 7
prefix_invariant: true
pressure_volume_partition: true
bounded_shares_and_raw_tdp: true
forbidden_semantic_columns: []
row_count_parity: true
all_pass: true
```

The first CI attempt had failed before tests because `actions/setup-python` pip caching was not pointed at `requirements-data.txt`. That workflow-only issue was corrected with `cache-dependency-path: requirements-data.txt`; run #6 is the first completed branch-head CI that actually executed both pytest and the M3 QA self-test successfully.

## Acceptance gates

- Branch source parity with validated `features.py`: **PASS**
- Feature schema/version frozen: **PASS**
- Local M1+M2+M3 suite: **18/18 PASS**
- Local six-timeframe real-data QA: **PASS**
- Local committed-runner reproduction: **PASS**
- Committed M3 unit tests: **PASS**
- Committed real-data QA runner: **PASS**
- Committed exact QA case config: **PASS**
- Branch-head GitHub research CI: **PASS**

## Non-claims

M3 does **not** establish that POC slowdown, divergence, pressure, efficiency, or any combination predicts balance/reversal. Those are M4–M8 research questions. No threshold, HBA composite, PF, win rate, or production signal is selected here.
