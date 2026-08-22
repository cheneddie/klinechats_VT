# POC Absorption Reversal — M5 Development 1 Outcome Contract

> Branch: `research/poc-absorption-reversal-v1`  
> Development: **1 / M5 Outcome Contract**  
> Verdict: **`M5_DEV1_OUTCOME_CONTRACT_FIREWALL_PASS`**  
> M5 milestone status: **OPEN — Physical Tick Outcome Engine not started in this development**

## Scope

This development creates only the physical separation between the frozen M4 event store and the future M5 outcome store.

It deliberately computes **no** forward return, MFE, MAE, balance, structure break, first-touch, P&L, or strategy metric.

```text
M4 probe_events  READ ONLY
        ↓ event_id / one-to-one
M5 probe_outcomes
```

The outcome layer receives already-materialized events. It is not allowed to call M4 selection logic to re-create, delete, re-rank, or condition event membership.

## Problem found before implementation

M4 had a frozen event generator/schema and a completed 2024 universe-distribution report, but there was no explicit M5-side immutable event-store contract/fingerprint. Without this layer an outcome implementation could accidentally regenerate M4 events while reading future ticks, weakening the physical firewall.

Development 1 fixes that architectural gap without changing M4 code, thresholds, IDs, episodes, or the frozen universe config. Before Development 2, the contract was strengthened to freeze the causal M4 event-time `atr` as an immutable normalization input; this prevents M5 from recomputing ATR after reading future data.

## Frozen provenance

```text
outcome_contract_version = POC_M5_OUTCOME_CONTRACT_V1
outcome_schema_version   = POC_PROBE_OUTCOME_V1

event_schema_version    = POC_PROBE_EVENT_V1
universe_version        = HIGH_PRICE_PROBE_V1
universe_schema_version = POC_HIGH_PRICE_PROBE_UNIVERSE_V1
feature_schema_version  = POC_CONTINUOUS_FEATURES_V1
universe_config_hash    = d7bf39afa32582bc06e00b2df9995b9cb9cc14670a6974834d80cf3d079016fb
```

M5 rejects any event frame whose frozen M4/feature provenance drifts from these values.

## Immutable event columns

The M5 outcome store may copy but never change:

```text
event_schema_version
universe_version
universe_schema_version
universe_config_hash
feature_schema_version

event_id
episode_id
episode_trigger_number

dataset_id
contract
partition_id
session
timeframe

trigger_seq
trigger_time
trigger_price
atr
bar_start_seq
bar_end_seq
```

Additional hard gate:

```text
trigger_seq == bar_end_seq
```

so the exact physical M4 decision point cannot drift when outcomes are attached.

`atr` is also immutable and must be the causal M4 event-time ATR. M5 is forbidden from recomputing ATR for normalization; `MFE_ATR / MAE_ATR` in Development 2 must divide by this frozen value.

## Frozen future-window contract for later M5 developments

The horizons are declared now but **not calculated in Development 1**:

```text
30s
1m
3m
5m
15m
30m
60m
session_end
```

Future-path semantics are frozen as:

```text
future physical tick: _seq > trigger_seq
same session only
fixed deadline = min(trigger_time + requested horizon, session end)
include ticks with datetime <= deadline
first-touch order must use physical _seq, never candle High/Low
```

Session end is exclusive under the existing research contract:

```text
day   < 13:45:00
night < 05:00:00 following the 15:00 session anchor
```

Later outcome rows must retain truncation metadata (`requested_horizon_seconds`, `effective_horizon_seconds`, `truncated_by_session_end`, `future_tick_count`) so an event near session close cannot masquerade as a full 60-minute observation.

## CODE / TEST

Implemented:

- `server/poc_absorption/outcomes.py`
- `tests/test_poc_absorption_outcome_contract.py`
- `tools/poc_absorption/m5_outcome_contract_qa.py`
- `config/poc_absorption/m5_outcome_contract_v1.json`

Dedicated Development-1 tests: **10/10 PASS locally** after adding frozen event-time ATR integrity.

Tests explicitly reject:

- duplicate M4 `event_id`;
- duplicate M5 `event_id`;
- missing outcome rows;
- unknown/extra outcome rows;
- modified `trigger_seq/time/price` or other immutable fields;
- M4 universe-config provenance drift;
- M3 feature-schema provenance drift;
- `trigger_seq != bar_end_seq`;
- missing/nonpositive/nonfinite event-time ATR;
- mutated ATR in `probe_outcomes`;
- event-store order/fingerprint drift.

The QA runner self-test also verifies one-to-one count parity and identical before/after event-store fingerprints with `future_ticks_read=false` and `future_outcomes_calculated=false`.

## DATA / REPORT — real 2024 join-integrity QA

The contract was then tested against the existing M4 real-QA case only:

```text
MTX_2024
2024-08-15 + 2024-08-16
day session
strict contract = 202408
physical ticks = 217,670
```

Before testing M5, the materialized event sample had to reproduce the already-frozen M4 six-timeframe parity counts:

| TF | Bars | Raw triggers | Episodes |
|---|---:|---:|---:|
| 15s | 2,400 | 471 | 212 |
| 30s | 1,200 | 237 | 113 |
| 1m | 600 | 108 | 53 |
| 3m | 200 | 36 | 17 |
| 5m | 120 | 31 | 12 |
| 15m | 40 | 16 | 8 |

All six match the committed M4 real-data QA. Total frozen sample events: **899**.

### Join integrity

```text
events before                = 899
outcome skeleton rows         = 899
joined events                 = 899
unique event_id before        = 899
unique event_id outcomes      = 899
missing event_id              = 0
extra event_id                = 0
duplicated event_id           = 0
immutable field mismatches    = 0
event order preserved         = true
```

Frozen sample event-store fingerprint:

```text
762519dfcb98d1deef8ca61ed00c0a20d514301a500e663cf539405763cec728
```

The fingerprint is identical before and after the one-to-one M5 join.

Machine-readable evidence:

- `reports/poc_absorption/M5_OUTCOME_CONTRACT_JOIN_INTEGRITY_2024_REAL_QA.json`

## What this result means

Development 1 proves that M5 has a mechanically enforceable firewall against changing M4 membership/provenance while attaching outcomes.

It does **not** prove any trading edge and does **not** yet prove physical future-path correctness.

No future tick was consumed by the contract QA and no outcome value was calculated.

## Intentional storage boundary

A full-year 2024 `probe_events` data file is not committed to GitHub in this development. The repository freezes the schema/manifest/fingerprint rules; data-scale materialization remains an external research artifact. M5 production code must consume a materialized `probe_events` input and may not regenerate event membership internally.

Development 2 will use synthetic data plus a small materialized real-2024 event sample to implement physical-tick outcomes. The 2024 six-timeframe full outcome cube is reserved for Development 5, exactly as planned.

## Next decision

**Proceed to Development 2 only after branch-head CI passes this contract gate.**

Development 2 may add only the physical-tick path measures:

```text
forward_high / forward_low
short_MFE / short_MAE
MFE_ATR / MAE_ATR
time_to_MFE / time_to_MAE
```

using future ticks strictly `_seq > trigger_seq`, with a manual raw-Parquet audit of at least 50 real events.
