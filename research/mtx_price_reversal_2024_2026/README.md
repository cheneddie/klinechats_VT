# MTX Price-Reversal Research 2024–2026

This directory belongs to the isolated branch **`research/mtx-price-reversal-2024-2026`**. It is intentionally **not merged into `main`**.

## Current status — 2026-08-24

**FROZEN FORWARD-OOS CANDIDATE — PAPER TRADE / RESEARCH ONLY — NOT LIVE APPROVED**

The inspected raw sample ends at **2026-08-14 13:44:59 exchange-local**. Any genuine new evidence must be strictly after that timestamp.

Start here:

1. `RESEARCH_STATUS.md` — complete current findings and classification.
2. `reports/current/NEXT_PHASE_PLAN_2026-08-24.md` — next development/Forward-OOS program.
3. `reports/current/EVIDENCE_LEDGER_2026-08-24.md` — Control/Challenger/Shadow/Monitor/Rejected registry.
4. `reports/current/FORWARD_GATES_2026-08-24.md` — pre-registered promotion gates.
5. `reports/current/CATASTROPHE_WATCH_SPEC_2026-08-24.md` — monitoring-state specification.
6. `data/current/FROZEN_FORWARD_OOS_V1.json` — machine-readable frozen strategy specification.
7. `data/current/ARTIFACT_HASH_INDEX_2026-08-24_part*.csv` — SHA-256 provenance index covering the current research artifacts, raw sources and reconstructable caches.

## Source/execution parity

Re-run from raw MTX parquet source:

- raw rows: **126,438,254**
- outright rows: **126,438,076**
- excluded spread/combo: **178**
- 32 contract months, 202401–202608

Canonical continuous-baseline checksum reproduced exactly:

- **3,655 trades**
- Gross **+12,414**
- Net@2 **+5,104**
- PF **1.0590535694**

The frozen candidate was also joined to a fresh raw-tick causal price/order-flow rebuild. Entry first print, exit300 first print, gross300 and 30-second signal all matched **1,112/1,112**.

## Frozen Control V1

- MTX outright only
- LONG only
- signal windows **09:00–10:30** and **20:30–22:30**
- Causal HighVol
- 30-second price selloff
- previous 3 completed contracts, lower **Q0.05%** threshold
- complete signal second + 1 second latency; earliest fill `t+2`
- first afterwards tradable print
- max one position
- fixed 300-second same-session hold
- 2-point round-trip primary friction

Historical candidate result:

- **1,112 trades**
- Gross **+10,650**
- Net@2 **+8,426**
- E **+7.577 points/trade**
- PF **1.30649**
- Max DD **-1,235**
- 2024 **+1,118** / 2025 **+1,365** / 2026 **+5,943**

This is frozen. The 2024–2026 sample may not be reused as a fresh holdout.

## Registered forward tracks

### Control
**Frozen V1**

### Challenger A — ACCEL30
At +30 seconds, catastrophic adverse acceleration >=20% of Prior14 same-kind session range triggers an early risk exit; the position gate stays locked until the original +300-second horizon.

Historical: Net **+8,888**, PF **1.329**, max loss **-310** vs V1 **-589**. Only four historical triggers: rare-event evidence remains insufficient.

### Challenger B — R3-lite
**V1 + ACCEL30 + Repeat5/45**.

If the fifth additional qualifying Q0.05% true crossing occurs within 45 seconds and the tradable price remains <= original entry, exit but keep the original 300-second position lock.

Historical: Net **+9,539**, E **+8.58**, PF **1.364**, Max DD **-1,176**, max loss **-310**. Repeat intervention improved 15/19 historical activations across 14 dates.

### Shadow C
Flow-gated FAIL180 / R2 diagnostics. Compute forward, but do not promote without separate event evidence.

### Monitor only
- Entry Risk Grade
- Day Stress Grade
- Catastrophe Watch State Machine

These may be calibrated but must not silently alter execution.

## Explicitly rejected — DO NOT RETUNE on 2024–2026

- fixed-point stops
- 2x–4x threshold stops
- risk-gated threshold stops
- 60-second direct failure exits
- high-risk entry skip / delayed reclaim entry
- stress-adaptive hold horizon
- session/day kill switches
- Repeat re-anchor / immediate re-entry / add-on positions
- mid-stage repeat-density stop grids
- 3x-breach recovery exits

Reopening those grids on the inspected sample is data mining.

## Forward-OOS gates

Base V1 is not reviewed before **6 calendar months AND 200 genuine forward trades**. It then must retain positive Net@2, PF>=1.10, positive Net@5, positive day-cluster-bootstrap lower bound and acceptable drawdown.

Overlay validation is event-based, not trade-count based:

- Repeat5/45: do not review before **10 genuine forward activations**; provisional gate >=8/10 improvements plus positive aggregate delta and acceptable date concentration.
- ACCEL30: rare-event challenger; ordinary 200-trade sample is insufficient.
- Flow-gated FAIL180: >=10 forward activations and must add value on top of R3-lite.

Any rule change creates a new version and resets its forward clock.

## Directory layout

- `engine/` — deterministic canonical engine
- `reports/current/` — current status, plan, evidence ledger and forward specs
- `reports/backtest|regime|robustness|path|sanity/` — prior validated research outputs
- `data/current/` — frozen configs and compact current decision evidence
- `data/` — canonical historical derived data
- `figures/` — lightweight visualizations

## Raw-data / cache policy

Raw MTX parquet files are external immutable source data and are not committed. Large 132–144 MB candidate-session second caches are reconstructable intermediates, also not committed. Their SHA-256 hashes are recorded in `data/current/ARTIFACT_HASH_INDEX_2026-08-24_part*.csv`, and their decision-relevant parity/audit results are committed.

## Next phase

Build a deterministic `forward_evaluator.py`, freeze Control/Challenger/Shadow configs and code/source hashes, ingest only post-2026-08-14 data, and run all tracks side-by-side with no optimization. See `reports/current/NEXT_PHASE_PLAN_2026-08-24.md`.
