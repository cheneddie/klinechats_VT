# MTX Price Reversal V2 — Production Validation Specification

## Evidence boundary
All data at or before `2026-08-14 13:44:59 +08:00` is inspected historical research. It may be used for discovery/risk design but never presented as fresh OOS for a newly selected rule.

## Frozen baseline control
- MTX outright contracts only.
- Original physical row order preserved; `_seq` assigned before filters.
- 30-second price selloff crossing the lower 0.05% threshold.
- Threshold uses only the previous 3 completed outright contracts.
- LONG only.
- Complete-second signal confirmation.
- +1 second additional latency after confirmation.
- First tradable print for entry.
- One position at a time.
- Fixed 300-second same-session exit.
- Primary friction view: 2 points round trip.

## Physical execution semantics
### Trigger is not Fill
A physical print crossing a stop/target produces a `Trigger`. A software market order can only be formed after that print is observed. Historical execution records trigger seq/time/price, order reason, fill seq/time/price and trigger-to-fill slippage.

Primary stop execution model: **next physical print**. Trigger-print execution is diagnostic only. Delayed N-print stress is required.

### Independent risk layers
Structural risk answers "the reversal hypothesis failed." Catastrophic risk answers "absolute loss cannot exceed this safety boundary." They are never collapsed into an anonymous single stop. The earliest physical trigger resolves the exit but preserves its reason.

## Contract selection
Historical/Replay/Paper/Live must use the same causal contract-selection policy. Production uses a pre-frozen contract schedule with explicit tradable windows. Whole-day realized volume cannot decide the contract retrospectively. Missing or overlapping windows fail closed.

Required fields: active_contract, next_contract, window start/end, selection_reason.

## Live idempotency / reconciliation
Every signal ID is deterministic from strategy_version + contract + signal_seq. It must be atomically claimed before order creation. Restart/replay of a claimed signal is ignored.

On startup, reconnect and heartbeat, local position/open orders must reconcile with broker position/open orders. Any mismatch blocks new entries and raises a safety state.

## Online data / clock safety
Live adapter must monitor duplicate/out-of-order seq, exchange timestamp reversal, stale feed, invalid price, unexpected contract and clock/receive anomalies. Safety faults set `ALLOW_ENTRY = FALSE`.

## Strategy/system risk
Trade-level structural/catastrophic stops do not replace strategy-level limits. Candidate Freeze must specify max daily loss, trades/day, consecutive losses, slippage, position and open orders, plus disconnect/feed/state-mismatch kill behavior.

## Path-state research
Post-entry management features are causal: a 30-second state may use only prints through entry+30 seconds; a 60-second state only through entry+60. Historical labels may measure future incremental PnL but may not leak into features.

Management research asks `E[future incremental PnL | current state]`, not merely final winner/loser classification. Every rule must report saved loss, lost right-tail and net management value.

## Right-tail gate
Every risk/management candidate must report PF/expectancy/median, Max DD/worst trade, P95/P99, Top 1% and Top 5% winner retention, top day/event concentration, RiskEfficiency, day/event-cluster bootstrap, year/month stability, stop/exit-cause matrix and parameter plateau.

A candidate that improves DD by destroying the baseline right tail is HARMFUL.

## OOS governance
Monitoring checkpoints (e.g. 30/60 days) are information-only. Formal evaluation is allowed only after the predeclared evidence threshold (default 120 trading days AND 100 independent event clusters). An OOS failure reclassifies that sample as research; any revised rule gets a new version and new watermark.

## Lifecycle
RESEARCH → FROZEN → FORWARD_OOS → PAPER → SHADOW_LIVE → LIMITED_LIVE → PRODUCTION. Safety degradation can move a live strategy to DEGRADED/SUSPENDED. Illegal stage skipping is rejected.

## Limited Live prerequisites
No 1-MTX Limited Live until Data, Contract, Causality, Execution, Forward Edge, Cluster Robustness, Cost/Slippage, Bounded Risk, Replay/Paper/Live Parity and Operational Safety gates all pass.
