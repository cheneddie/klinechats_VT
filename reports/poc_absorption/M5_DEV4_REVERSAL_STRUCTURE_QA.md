# M5 Development 4 — Frozen Structure / Reversal Outcome QA

## Verdict

`M5_DEV4_FROZEN_STRUCTURE_REVERSAL_PASS`

Development 4 freezes downside structure references **before** future-path measurement and records physical-sequence break / new-high / reversal-delay outcomes. It does **not** define a trading signal, threshold, P&L, preferred horizon, or 2025/2026 validation result. M5 remains open after this development.

## Frozen input boundary

```text
M4 probe_events (READ ONLY)
        + completed bars available by trigger_seq
        ↓
Dev4 reversal_reference_store (frozen by event_id)
        + physical ticks strictly after trigger_seq
        ↓
Dev4 reversal outcomes
```

M4 membership, event IDs, decision coordinates, and event-time ATR are unchanged.

## Frozen references

Schema: `POC_M5_REVERSAL_REFERENCE_V1`

Micro-swing algorithm: `STRICT_CONFIRMED_PIVOT_LOW_R2_WITHIN_LAST24_V1`

Channel references are the already-causal M4 24-bar price-only state:

```text
channel_high = M4.rolling_high
channel_low  = M4.rolling_low
channel_midline = (channel_high + channel_low) / 2
```

Micro swing low is the latest strict pivot low inside the latest 24 completed bars including the trigger bar. Radius is two completed bars left + two right; the candidate low must be strictly below all four neighbors; the complete five-bar pivot window must already be completed by the event trigger. No fallback is permitted. The continuity partition is the same contract + same session + no DATA_GAP semantics used by M3/M4, so a completed-bar lookback may span consecutive trading days.

A reference already broken at the trigger is not allowed to produce a later fake “new” break. For example:

```text
micro_swing_break_eligible = reference exists AND trigger_price >= micro_swing_low
```

## Physical outcome semantics

- Downside break = first future physical tick with `price < frozen_reference`.
- Equality is not a break.
- New high = first future physical tick with `price > frozen channel_high`.
- Equality is not a new high.
- First-hit ordering uses physical `_seq`, never candle High/Low.
- Same-second later physical ticks remain valid and may have zero-second delay.
- If one physical tick breaks multiple references, `first_structure_break_references` stores every simultaneously broken reference in canonical order; no arbitrary winner is selected.
- `future_tick_count == 0` means Dev4 outcomes are null, not false.
- An observed path with no break means break=false.

Reversal-delay evidence includes first break seq/time/price, pre-break peak seq/time/price, trigger→peak, peak→break, trigger→break, adverse extension in points and frozen event-time ATR units, and whether a frozen-channel new high occurred before the first structure break.

Forward slope/R² is descriptive only and uses 1-second closes with OLS x-axis = sequence index.

## Real 2024 day QA

2024-08-15 + 2024-08-16, strict `202408`, day session:

```text
physical ticks = 217,670
M4 events      = 899
M4 parity      = 471 / 237 / 108 / 36 / 31 / 16
```

The reconstruction reproduces the frozen Dev2/Dev3 event provenance:

```text
candidate_event_ids_hash = b051e4fc4593bfa1fbd49196915d02d5d7529113f32617d46c832610dacbca19
selected_event_ids_hash  = d96bb64a56843e7198129a811c828968f3c5d31571e963ddaa15dbee15b5853d
```

Final day reference manifest:

```text
events                                 899
channel_midline_break_eligible         899
channel_low_break_eligible             899
micro_swing_reference_available        876
micro_swing_reference_missing           23
micro_swing_break_eligible             873
micro_swing_already_broken_at_trigger    3
reference hash = 2dd1bd9e49d676a7e2de8ddc7129f9728e5c4c04738b844730e630748235cec7
```

Correctness reuses the deterministic Dev2 50-event sample:

```text
50 events × 8 horizons = 400 windows
400 / 400 independent pandas/raw-mask audit PASS
mismatches = 0
```

The independent audit does not call the production Dev4 measurement helper and also checks simultaneous-break identity.

## Real night-boundary QA

2024-08-15 15:00 → 2024-08-16 05:00, strict `202408`:

```text
physical ticks = 144,044
M4 events      = 1,756
8 boundary events × 8 horizons = 64 windows
64 / 64 independent audit PASS
mismatches = 0
```

Final night reference manifest:

```text
micro_swing_reference_available 1,579
micro_swing_reference_missing     177
micro_swing_break_eligible      1,577
already broken at trigger           2
reference hash = 71655faa96eb33e17986ed9f0b3d1a28d3a3eb4f5b69e696c6fa9296cb3bc183
```

## Descriptive distribution sanity — not edge

The 899-event day sample does not show an obviously broken definition such as near-100% immediate breaks.

| Horizon | Any break | Midline | Micro swing | Channel low | Median first-break time |
|---|---:|---:|---:|---:|---:|
| 30s | 5.80% | 4.24% | 2.18% | 0.00% | 17s |
| 1m | 13.71% | 10.59% | 6.09% | 0.11% | 35s |
| 3m | 34.56% | 28.65% | 19.98% | 5.46% | 77.5s |
| 5m | 43.14% | 37.35% | 29.39% | 10.93% | 98s |
| 15m | 63.77% | 57.97% | 49.14% | 26.20% | 167s |
| 30m | 79.04% | 73.80% | 63.15% | 39.58% | 245s |
| 60m | 81.05% | 75.81% | 71.64% | 49.83% | 262s |
| session_end | 87.74% | 82.50% | 82.43% | 69.01% | 313s |

These are outcome distributions only. No M3 predictor stratification, threshold selection, placebo, or OOS test occurs in Dev4.

## 15m zero-break sanity case

The two-day sample has 16 15m triggers, all on 2024-08-16 from 09:44:59 through 13:44:59. The 13:44:59 event has zero future ticks and is correctly null. The earlier 15 events have real future observations but no frozen-reference break and no new high.

Frozen channel:

```text
channel_high = 22445
channel_midline = 22139.5
channel_low = 21834
```

For the first 09:44:59 event, the remaining session has 59,990 future ticks with `future_min=22284` and `future_max=22438`. Thus the session never went below the midline and never exceeded the frozen channel high. The zero-break/new-high result is legitimate, not a window slicing defect.

## Firewall

Dev4 does not define a reversal signal, choose a best reference/horizon, calculate P&L/PF/win rate, touch 2025 validation, open 2026 OOS, or merge to `main`.

Next is the predeclared physical first-hit / tradeability measurement layer. M5 remains unchecked until Dev1–Dev6 and the full event/outcome sanity gate are complete.
