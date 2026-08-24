# POC Absorption Reversal — M2 Causal Bars + Developing POC QA

> Branch: `research/poc-absorption-reversal-v1`
> Engine: `server/poc_absorption/bars.py`

## Verdict

**M2 = PASS** on synthetic causality tests and representative real MTX sessions.

The engine consumes physical `_seq` in source order, never sorts ticks, anchors buckets to session starts, computes completed exact-price Volume Profiles once per closed bar, and maintains developing POC incrementally.

## Required resolutions

`15s`, `30s`, `1m`, `3m`, `5m`, `15m`.

## Deterministic POC tie rule

1. Maximum volume-at-price candidates only.
2. Choose the candidate nearest current bar VWAP.
3. If still tied, choose nearest previous completed-bar POC.
4. If still tied, choose the lower price.

Alternative tie rules are reserved for later sensitivity analysis; they are not optimized here.

## Synthetic tests

- 12 tests PASS.
- Same-second physical order determines open/close.
- Session-relative 3m bucketing starts at 08:45 rather than arbitrary resample origin.
- POC tie-breaking is deterministic.
- Tick developing POC at a prefix equals the same prefix observed within a longer sequence.
- End-of-second snapshot uses the final physical tick in that second.
- Non-increasing `_seq` is rejected rather than silently sorted.
- ATR uses completed bars only.
- Night session anchoring remains stable across midnight.

## Real-data representative QA

- Day sessions tested: **12**
- Day-session physical ticks tested: **983,433**
- Cross-midnight night-session ticks tested: **194,152**
- Developing-POC future-mutation checks: **36**

| Timeframe | Completed bars checked | Volume conservation | Seq non-overlap | POC max-volume candidate |
|---|---:|---|---|---|
| 15s | 17,560 | PASS | PASS | PASS |
| 30s | 8,790 | PASS | PASS | PASS |
| 1m | 4,395 | PASS | PASS | PASS |
| 3m | 1,465 | PASS | PASS | PASS |
| 5m | 879 | PASS | PASS | PASS |
| 15m | 293 | PASS | PASS | PASS |

Representative day sessions intentionally include contract-roll boundaries and special-calendar boundaries:

`2024-01-17`, `2024-01-18`, `2024-12-26`, `2024-12-30`, `2025-03-19`, `2025-03-20`, `2025-08-20`, `2025-08-21`, `2026-02-11`, `2026-02-23`, `2026-07-09`, `2026-07-13`

The real night QA uses `2026-07-08 15:00 → 2026-07-09 05:00`, crossing midnight without resetting the session anchor.

## Developing POC causality

For each selected 1m/3m/15m bar, a physical decision prefix was evaluated, then all later test ticks were deliberately mutated by a huge price/volume shock. The developing POC snapshot at the decision `_seq` was required to remain unchanged.

- Prefix/full parity: **36/36 PASS**
- Future-mutation invariance: **36/36 PASS**
- Cross-midnight future-mutation invariance: **PASS**

## Performance design correction discovered during QA

An initial diagnostic implementation recomputed the entire profile (including VAH/VAL) on every tick snapshot. That preserves causality but is unnecessarily expensive for 15m bars. The production research implementation now:

- updates `volume_by_price` incrementally;
- maintains `max_price_volume` + tied max-volume candidates incrementally;
- computes developing POC from that small candidate set;
- computes full POC/VAH/VAL/profile width only once at completed-bar close;
- exposes `BarAccumulator` for streaming/live use;
- keeps `build_developing_poc()` as a bounded replay/research helper rather than an unbounded whole-year materializer.

## M2 carry-forward invariants

1. Input `_seq` must be strictly increasing; the engine never fixes bad order by sorting.
2. Datetime may be equal across many ticks but may never move backward.
3. Bars are session-anchored, not generic wall-clock resamples detached from trading sessions.
4. Completed-bar POC/profile uses only ticks through `bar_end_seq`.
5. Developing POC at `decision_seq` uses only ticks `<= decision_seq`.
6. Second snapshots mean end-of-second causal state after the last physical tick observed in that second.
7. Full developing VAH/VAL is intentionally not recalculated each tick; M2 only requires developing POC.

## Acceptance

- Causal OHLCV: **PASS**
- Six required resolutions: **PASS**
- Completed POC/VAH/VAL/profile: **PASS**
- Deterministic POC tie rule: **PASS**
- ATR on completed bars: **PASS**
- Developing POC tick mode: **PASS**
- Developing POC end-of-second mode: **PASS**
- Day-session real data: **PASS**
- Cross-midnight night-session real data: **PASS**
- Future mutation / hide-future: **PASS**

**Next gate: M3 continuous channel / POC migration / pressure / efficiency features.**
