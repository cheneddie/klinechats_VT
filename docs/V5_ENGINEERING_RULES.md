# Fabio Decision Gym V5 Engineering Rules

## Non-negotiable truth boundaries

1. **Raw physical Parquet row order is the only market-order truth.** `_seq` is assigned before filtering. Raw ticks are never sorted by datetime, price, side, or volume.
2. `side` is a **tick-direction proxy**, never labelled true aggressor, bid/ask delta, CVD, or absorption.
3. MTX research uses outright six-digit expiry contracts only. Spread/combo rows are excluded. Contract choice must be causal; dominant full-day volume is diagnostic only.
4. Scanner/state logic answers only what was knowable at the time. Outcomes, PnL, and later path never modify structural labels.
5. Every `NO` node has a causal death point: `decision_seq`, `decision_time`, `decision_price`, and `reason_code`.
6. Research terminal anchors and strict strategy entries are different fields and different semantics.
7. Hide Future cuts physical ticks at node decision position **before** candle aggregation.
8. Event Store is rebuildable from Parquet. Human training data is stored in a separate non-rebuildable DB.
9. `research_run_id` result sets are immutable. A config/threshold change requires a new run with git/scanner/strategy/config/schema/outcome/audit/management versions.
10. Holdout governance is fixed: **2025 Discovery → 2024 Validation → 2026 Final Holdout**. Final Holdout is never used for threshold selection.

## Research gates

`Raw Integrity → Contract Integrity → Causal Event Truth → Event Sanity → Physical Outcomes → Reverse Audit → Sequential Contribution → Ablation → Evidence Registry → Training Truth → Certification → Production → Live parity`

A later gate is not allowed to make an earlier gate pass retroactively.

## Node classifications

Only: `CORE`, `OPTIONAL`, `STATE`, `REDUNDANT`, `HARMFUL`, `REGIME_DEPENDENT`, `INSUFFICIENT`.

High same-seq rate alone does not make a node redundant. Redundancy requires timing overlap **plus** negligible incremental edge **plus** harmless ablation and no material winner/loser handling improvement.

## Production boundary

Production eligibility is evidence, not philosophy. MR should support roughly 1R, BO roughly 2R, with meaningful points, costs/latency robustness, acceptable DD, preserved right tail, and Historical ↔ Live causal parity. The 18-node Concept Tree may legitimately shrink in the Production Tree.
