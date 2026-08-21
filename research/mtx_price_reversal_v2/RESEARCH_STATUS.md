# Research Status

## Historical baseline

Frozen at commit `2cbaf76971b8ba1a8cac0ac38e23a860d7f64e61`.

## Current evidence

- Extreme-selloff reversal phenomenon exists historically.
- Unconditional 300s strategy is positive but thin after 2pt friction.
- 09:00–10:30 × causal high-vol is the strongest post-hoc regime interaction found so far.
- Right-tail/day/event concentration is material.
- Day-cluster bootstrap for the unconditional strategy crosses zero.
- No position-overlap bug: max concurrent position = 1.
- Tight stops are dangerous because large winners often experience early MAE and late MFE.

## Current production status

**NOT LIVE APPROVED.**

## Work allowed on this branch

- Engine modularization and exact regression.
- Physical tick stop/target/trailing implementation.
- Causal risk/management research on historical data, clearly labeled discovery.
- Freeze candidate before viewing new forward OOS.
- Append-only forward OOS and paper/live parity.

## Work not allowed

- Silent rule changes after OOS starts.
- Rebranding post-hoc H1/H2 as validated.
- Treating 3,655 trades as 3,655 independent samples.
- Using second OHLC to decide same-second stop-vs-target order.
