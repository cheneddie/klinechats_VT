# M5 Development 2 — Exact Physical-Tick Outcome QA

> Branch: `research/poc-absorption-reversal-v1`  
> Development: **2 / Physical Tick Outcome Engine**  
> Formal verdict target: **`M5_DEV2_EXACT_PHYSICAL_OUTCOME_PASS`**  
> M5 milestone: **OPEN** — Dev3–Dev6 not completed.

## Scope

Development 2 measures future physical-tick path outcomes only. It does not define Balance, reversal structure, first-touch threshold labels, P&L, or trading edge.

Frozen path contract:

```text
future tick = physical _seq > trigger_seq
same session only
fixed deadline = min(trigger_time + requested horizon, session end)
first/equal extrema tie = earliest physical _seq
ATR normalization = frozen M4 event-time ATR
```

Horizon set remains frozen at `30s / 1m / 3m / 5m / 15m / 30m / 60m / session_end`.

## Outcome evidence coordinates

Every horizon keeps enough coordinates to return to raw transactions rather than only persisting an MFE/MAE number:

```text
requested_horizon_seconds
effective_horizon_seconds
deadline_time
truncated_by_session_end
future_tick_count
window_start_seq / window_end_seq
forward_high / forward_high_seq / forward_high_time
forward_low  / forward_low_seq  / forward_low_time
short_mfe / mfe_seq / mfe_time / mfe_atr
short_mae / mae_seq / mae_time / mae_atr
time_to_mfe_seconds / time_to_mae_seconds
```

If there is no future observation, path fields remain missing rather than being changed to zero. If an observed path has zero favorable/adverse excursion, the excursion itself is `0` but its extrema-hit coordinate is null. A same-second tick with larger physical `_seq` is a valid future tick and may therefore produce a zero-second time-to-extreme.

## Deterministic 50-event audit

Sampling is frozen as `M5_DEV2_AUDIT_SAMPLE_V1`:

```text
per timeframe
→ SHA256(event_id)
→ ascending stable order
→ take fixed N
```

There is no manual selection and no RNG seed.

Counts:

| TF | N |
|---|---:|
| 15s | 10 |
| 30s | 10 |
| 1m | 10 |
| 3m | 8 |
| 5m | 6 |
| 15m | 6 |
| **Total** | **50** |

Candidate-ID hash:

`b051e4fc4593bfa1fbd49196915d02d5d7529113f32617d46c832610dacbca19`

Selected-ID hash:

`d96bb64a56843e7198129a811c828968f3c5d31571e963ddaa15dbee15b5853d`

The complete selected event IDs are frozen in `M5_DEV2_AUDIT_SAMPLE_PROVENANCE.json`.

### Day real-data result

Source:

```text
MTX_2024
2024-08-15 + 2024-08-16
strict 202408
day
217,670 physical ticks
899 frozen M4 events
```

M4 raw trigger parity before attaching outcomes:

```text
15s 471
30s 237
1m  108
3m   36
5m   31
15m  16
```

Independent brute-force raw-mask audit:

```text
50 events × 8 horizons = 400 windows
400 / 400 PASS
mismatches = 0
```

The audit implementation does not reuse the production range-extrema query result. It independently filters raw physical ticks by `_seq`, deadline, and session, then finds the first physical occurrence of forward high/low.

M4 immutable fingerprint is unchanged:

`762519dfcb98d1deef8ca61ed00c0a20d514301a500e663cf539405763cec728`

## Real night cross-midnight QA

A separate real night partition was required before closure:

```text
trading date = 2024-08-16
physical window = 2024-08-15 15:00 <= t < 2024-08-16 05:00
strict contract = 202408
physical ticks = 144,044
frozen events = 1,756
```

Deterministic boundary sample:

```text
8 events
4 timeframes
6 events near midnight whose forward horizon crosses 00:00
2 events near 05:00 session end
64 horizon windows
64 / 64 PASS
mismatches = 0
```

This closes the important real-data boundary not covered by the earlier day-only Dev2 audit.

## Scalability problem found and fixed

The first correct implementation repeated array slicing + `argmax/argmin` for every event × horizon. A representative larger run exposed unacceptable scaling risk for the 2024 universe (`505,448` raw events × `8` horizons).

The engine was therefore changed **before Dev2 closure** to:

```text
session partition
→ index physical price path once per session
→ vectorized segment-tree RMQ for extrema
→ batched horizon range queries
→ earliest physical position on equal-price ties
```

The optimization did not change semantics: the 400 day windows and 64 real-night windows remained exact against independent brute-force raw-tick audits.

### Performance benchmark

`M5_DEV2_PERF_BENCH_V1` uses 10,000 deterministic replicated frozen events over the real two-day day-session tick density. It is an engineering benchmark only, not a research inference.

```text
physical ticks        217,670
benchmark events       10,000
outcome windows        80,000
wall time              0.417591 s
events/sec             23,946.86
windows/sec           191,574.89
process peak RSS       ~275,024 KB
```

Measured internal timings:

```text
extrema index build    0.011598 s
range queries          0.069757 s
output finalize        0.088064 s
```

Using measured engine rates only, the conservative 2024 reference (`50,862,751` physical rows / `505,448` events / `4,043,584` windows) extrapolates to about `10.69 s` of engine work.

This **is not a full-year runtime claim**. It explicitly excludes Parquet I/O, M4 event materialization, serialization, checkpointing, and later Dev3/Dev4 measures.

Engineering performance verdict:

`FULL_YEAR_SCALE_FEASIBLE`

## Reproducible code/test/report package

Development 2 adds:

- `server/poc_absorption/physical_outcomes.py`
- `tests/test_poc_absorption_physical_outcomes.py`
- `tools/poc_absorption/m5_physical_outcome_qa.py`
- `config/poc_absorption/m5_physical_outcome_v1.json`
- `reports/poc_absorption/M5_DEV2_AUDIT_SAMPLE_PROVENANCE.json`
- `reports/poc_absorption/M5_DEV2_REAL_NIGHT_QA.json`
- `reports/poc_absorption/M5_DEV2_PERFORMANCE_BENCHMARK.json`
- `reports/poc_absorption/M5_DEV2_FORMAL_QA_SUMMARY.json`
- this report

The QA runner regenerates the detailed 400-row day ledger and 64-row night ledger from the raw Parquet deterministically. Those row-level outputs are runtime evidence rather than hand-authored repository data; the selected IDs/hashes, rules, summary and generator are committed.

Dedicated Dev2 tests cover strict future `_seq`, same-second later ticks, exact deadline inclusion, session truncation, cross-midnight night semantics, first-physical-seq extrema ties, zero excursion vs missing observation, frozen ATR normalization, trigger coordinate parity, refusal to sort nonmonotonic data, multiple events sharing a trigger seq, multi-day session-local indexing and invalid horizon rejection.

## Interpretation boundary

This development proves physical future-path measurement correctness and engineering scalability. It does **not** prove that the POC hypothesis has predictive edge.

Forbidden conclusions at this stage include win rate, PF, optimal feature threshold, best timeframe, or any claim that Balance/Reversal works.

Development 3 remains not started until the exact branch-head CI containing this full package passes.
