# MTX Price Reversal V2 — Research / Production Status

## Branch role
This branch is the Production Edge Validation Pipeline. Historical 2024–2026 conclusions remain frozen in `research/mtx-price-reversal-2024-2026` at commit `2cbaf76971b8ba1a8cac0ac38e23a860d7f64e61`.

**New forward OOS is still LOCKED. No post-watermark data has been consumed for rule selection.**

## OOS watermark
`2026-08-14T13:44:59+08:00`

## Completed

### Phase 0 — Governance
- OOS lock and hypothesis registry.
- H1/H2 time/time×volatility ideas explicitly post-hoc.
- OOS failure policy: failed OOS becomes discovery data; revised rules require a new version and watermark.
- Formal evaluation checkpoint separated from information-only monitoring.

### Phase 1 — Zero-change migration
- 3,655-trade historical golden regression reproduced exactly.
- Golden truth: Net@2 +5,104, E=1.3964432284541723, PF=1.059 rounded, MaxDD=-3,086.

### Phase 2A — Physical trigger engine
- Stop/target ordering uses immutable physical `_seq`.
- Trigger is a separate object from Fill.

### Phase 2B — Causal fill engine
- Primary historical risk fill: next physical print after trigger.
- Diagnostic upper bound: trigger print.
- Adverse stress: N physical prints after trigger.
- Trigger→fill slippage is explicit.

### Phase 2C — Independent risk layers
- Structural and catastrophic risk remain independent.
- Earliest physical trigger wins while exit reason remains explicit.

### Production safety scaffold
- Frozen-schedule ContractSelectionEngine; missing/ambiguous coverage fails closed.
- Persistent SQLite state and deterministic signal IDs for restart/idempotency.
- Broker/local position+orders reconciliation; mismatch blocks new entries.
- Online feed checks for duplicate/out-of-order/timestamp reversal/stale feed/unexpected contract.
- Strategy-level risk limits and entry guard.
- Clock/latency observation scaffold.
- Promotion/demotion lifecycle and drift primitives.
- Run manifests include source size+SHA256, environment versions and random seed.
- Reproducibility lock file added.

### Phase 4/5 research primitives
- Right-tail retention and RiskEfficiency metrics implemented.
- Stop-cause matrix implemented.
- 15/30/60-second causal PathState feature engine implemented.
- Counterfactual EXIT-now vs CONTINUE-to-300s accounting implemented.
- Baseline right-tail and path-state discovery artifacts committed.

## Validation before upload
- Local unit tests: **28/28 PASS**.
- Golden regression: **PASS**.

## Still intentionally NOT frozen
- Structural stop candidate.
- Catastrophic stop boundary.
- Daily/system numeric risk limits.
- Path-state KEEP/EXIT rule.
- Production candidate.

These require a physical-tick Risk Lab on already-inspected historical data before Freeze.

## Important reporting fix
Right-tail day concentration now stores both `entry_calendar_day` and `session_key_day`. Night-session boundary semantics can otherwise produce different best-day labels; future statistical gates must declare the clustering calendar explicitly.

## Forward OOS gate
Do not consume post-watermark data for rule selection until:
1. one structural stop is frozen;
2. one catastrophic stop is frozen;
3. one management rule (or explicit no-management control) is frozen;
4. physical tick fill stress is completed;
5. right-tail survival report is complete;
6. forward contract/session schedule is frozen;
7. red-team/fault-injection tests pass.

Status: **NOT LIVE APPROVED / OOS NOT YET OPENED**.
