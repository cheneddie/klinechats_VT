# Phase 0 / Phase 1 Status

## Completed

- New V2 OOS branch created from frozen historical baseline commit.
- OOS watermark locked at 2026-08-14 13:44:59 +08:00.
- H0/H1/H2 registry created; H1/H2 explicitly post-hoc.
- Baseline strategy config frozen as control.
- Monolithic engine split into data/session/cache/signal/regime/execution/risk/management/oos/metrics modules.
- Physical tick stop/target ordering primitives implemented using `_seq`.
- Shared live-state/parity scaffolding added.
- Golden baseline manifest added.

## Local validation before commit

- Unit tests: 7/7 PASS.
- Golden regression against the committed 3,655-trade historical output: PASS.
- Reproduced: Trades=3655, Net@2=5104, Expectancy=1.3964432284541723, PF=1.059 rounded, MaxDD=-3086.

## Not completed / intentionally blocked

- Structural stop is not frozen.
- Catastrophic stop is not frozen.
- Path-state management is not frozen.
- Production candidate config remains NOT_FROZEN.
- No new forward OOS has been consumed on this branch.
- Paper/live parity cannot graduate without a frozen candidate and live/paper feed.

These are research/product gates, not missing historical backtest parameters.
