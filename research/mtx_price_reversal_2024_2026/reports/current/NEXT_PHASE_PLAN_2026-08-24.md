# Next Phase Plan — MTX Forward OOS Program

**Plan date:** 2026-08-24  
**Applies after inspected data endpoint:** `2026-08-14 13:44:59`

## Objective

Stop optimizing the inspected 2024–2026 sample. Convert the research into a deterministic forward evaluator that runs Control, registered Challengers, Shadow rules and Monitor-only states side-by-side without changing any frozen rule after seeing new outcomes.

## Phase F0 — Repository freeze and provenance

1. Freeze V1 configuration and rule hash.
2. Freeze ACCEL30 and Repeat5/45 challenger specifications.
3. Freeze Flow-gated FAIL180 as Shadow-only.
4. Record the raw-data endpoint and all artifact hashes.
5. Mark rejected research lines as `DO NOT RETUNE`.
6. Ensure forward reports identify software commit SHA, config hash, source-data time range and run timestamp.

**Exit criterion:** every forward result is reproducible from code + configuration + source-data identity.

## Phase F1 — Forward evaluator implementation

Build one deterministic evaluator that, for every new MTX source file:

1. Performs raw data QA.
2. Reconstructs seconds while preserving physical row order.
3. Computes previous-three-contract Q0.05 threshold causally.
4. Computes Causal HighVol without future sessions.
5. Produces Frozen V1 entries/exits.
6. Produces ACCEL30 overlay result without reopening the position gate.
7. Produces Repeat5/45 overlay result without add-on positions or early re-entry.
8. Runs Flow-gated FAIL180 only as Shadow.
9. Emits Entry Risk Grade / Day Stress / Catastrophe Watch states only as monitor fields.
10. Produces execution, cost and capital-risk diagnostics.

**Non-negotiable:** no parameter optimization in the forward evaluator.

## Phase F2 — Automatic forward report after each data increment

Required report sections:

### Base performance

- Forward trades
- Gross / Net@2 / Net@5
- PF
- Expectancy
- Win rate
- Max DD
- Ulcer Index
- Daily/monthly PnL
- day-cluster bootstrap CI

### Overlay evidence

For ACCEL30 / Repeat5-45 / Flow-gated FAIL180:

- activation count
- activation dates
- original outcome vs overlay outcome
- improvement/worsening count
- aggregate delta
- largest-date contribution
- Bayesian posterior of intervention-success rate
- forward sign-test (descriptive only)

### Tail and capital risk

- Max closed loss
- MAE P95/P99/max
- Worst 1/2.5/5% Expected Shortfall
- high-water-mark-to-intratrade-low trough
- cost 2/3/5/8 stress
- start-buffer stress

### Monitoring calibration

- Entry Risk Grade event counts and realized tail rates
- Day Stress Grade calibration
- Catastrophe Watch state transition counts
- tail5 capture / false-alarm rates

## Phase F3 — Promotion gates

### Base V1

Do not review before both:

- >=6 calendar months
- >=200 genuine forward trades

Then require all frozen gates in `RESEARCH_STATUS.md`.

### Repeat5/45 Challenger B

Do not review before >=10 genuine forward activations.

Initial promotion-review condition:

- >=8/10 improve the unmodified comparison path
- total delta >0
- date concentration acceptable
- no rule change

If fewer than 10 activations occur, continue collecting forward evidence; do not backfill with historical events.

### ACCEL30 Challenger A

Treat as rare-event insurance hypothesis. Do not infer validation from trade count alone. Review only after meaningful genuine forward activations. Preserve exact 20% Prior14 / 30-second rule.

### Flow-gated FAIL180 Shadow C

Requires >=10 forward activations and must demonstrate incremental benefit beyond Challenger B.

## Phase F4 — Failure / rollback rules

Immediate research downgrade if any of the following occurs:

1. Forward execution parity breaks.
2. Any rule requires future information or data not available at decision time.
3. New implementation changes equal-second trade order.
4. V1 fails base forward gates after minimum sample is reached.
5. Challenger improvement is driven by one isolated date/event.
6. Realistic friction pushes forward expectancy negative.
7. Capital-risk metrics materially exceed frozen risk envelope.

Do not rescue a failing rule by changing thresholds on the same forward sample. A changed rule becomes a new version with a new forward clock.

## Phase F5 — Live-approval prerequisites

No live approval before:

1. Base forward gate passes.
2. Execution has been paper-traded using the same first-print / latency contract.
3. Cost/slippage assumptions are verified against paper execution logs.
4. Risk overlays have sufficient event-specific forward evidence.
5. Capital buffer is chosen from forward intratrade risk, not only historical max closed loss.
6. Operational kill conditions for missing/late/bad data are implemented independently of trading stop logic.
7. A final immutable live spec is reviewed and hash-frozen.

## Deliverables for next development cycle

1. `forward_evaluator.py`
2. immutable forward config files for Control/Challengers/Shadow
3. raw-source QA report
4. forward trade ledger
5. overlay intervention ledger
6. monitor-state ledger
7. capital-risk report
8. reproducibility manifest with config/code/source hashes
9. machine-readable promotion-gate status

## Current priority order

1. Build forward evaluator and parity tests.
2. Ingest only post-2026-08-14 data.
3. Run Control / A / B / Shadow simultaneously.
4. Do not modify frozen thresholds.
5. Accumulate Repeat and ACCEL event evidence separately from base trade evidence.
6. Review only when pre-registered minimum samples are reached.
