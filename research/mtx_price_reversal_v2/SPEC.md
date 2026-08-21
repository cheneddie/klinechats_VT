# MTX Price Reversal V2 Specification

## Baseline causal signal

- Instrument: MTX outright only.
- Direction: LONG only.
- Signal feature: `close_t - close_{t-30s}` on complete seconds.
- Threshold: lower 0.05% quantile estimated only from the previous 3 completed outright contracts.
- Trigger: first true crossing from above threshold to `<= threshold`.
- Confirmation: complete signal second `t` becomes known at `t+1`.
- Frozen extra latency: 1 second.
- Entry: first physical tradable print at/after `t+2`.
- Position state: one MTX maximum.
- Baseline exit: first tradable print at/after entry + 300 seconds, same session only.

## Regime hypotheses

`09:00–10:30` and `HighVolCausalPct80` are post-hoc historical hypotheses, not validated production filters.

## Risk architecture

Two independent layers are mandatory before live approval:

1. Structural stop: market behavior that falsifies the reversal thesis.
2. Catastrophic stop: unconditional maximum-loss boundary independent of strategy logic.

All stop/trailing/target trigger ordering and fills are resolved from raw physical tick sequence.

## OOS rules

The historical watermark is stored in `OOS_LOCK.json`. A rule change caused by inspecting data after that watermark creates a new strategy version and a new OOS start. Historical data can be used for implementation regression and risk design research, but not relabeled as OOS.

## Live gates

- G0 Data: zero causal/sequence violations.
- G1 Execution: physical tick fills verified.
- G2 Edge: forward OOS Net@2 > 0.
- G3 Statistical: day-cluster 95% CI lower bound > 0.
- G4 Cost: adverse 3pt friction not negative.
- G5 Risk: structural + catastrophic limits defined and tested.
- G6 Parity: historical replay / paper / live decisions identical for the same ticks.
