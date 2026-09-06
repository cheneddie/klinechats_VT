# Fabio Decision Gym V5 Engineering Rules

## Non-negotiable truth boundaries

1. **Raw physical Parquet row order is the only market-order truth.** `_seq` is assigned before filtering. Raw ticks are never sorted by datetime, price, side, or volume.
2. `side` is a **tick-direction proxy**, never labelled true aggressor, bid/ask delta, CVD, or absorption.
3. MTX research uses outright six-digit expiry contracts only. Spread/combo rows are excluded. Contract choice must be causal; dominant full-day volume is diagnostic only.
4. Scanner/state logic answers only what was knowable at the time. Outcomes, PnL, and later path never modify structural labels.
5. Every causally evaluated `NO` node has a death point: `decision_seq`, `decision_time`, `decision_price`, and `reason_code`.
6. Research terminal anchors and strict strategy entries are different fields and different semantics.
7. Hide Future cuts physical ticks at node decision position **before** candle aggregation.
8. Event Store is rebuildable from Parquet. Human training data is stored in a separate non-rebuildable DB.
9. `research_run_id` result sets are immutable. A config/threshold change requires a new run with git/scanner/strategy/config/schema/outcome/audit/management versions.
10. The legacy Fabio campaign remains **2025 Discovery → 2024 Validation → 2026 Final Holdout**. New strategies must declare their own Research Campaign and pin dataset SHA-256 identities before use. A Final Holdout is never used for threshold selection.

## P0 Research Integrity V6

### Four-state node truth

Every persisted node has exactly one `evaluation_state`:

- `EVALUATED`: the node was causally reached. `answer` must be `YES/NO` (`1/0`) and the decision point is asserted.
- `NOT_REACHED`: an upstream blocking node failed first. `answer` is `NULL`; no node decision/anchor may be asserted; blocker lineage and causal resolution are preserved.
- `NOT_APPLICABLE`: the node does not belong to the active branch. `answer` is `NULL`; no decision assertion is allowed.
- `TERMINAL`: decision flow has terminated. `answer` is `NULL`; the terminal resolution is preserved separately.

**G3 inference is hard-restricted to `evaluation_state='EVALUATED'`.** `NOT_REACHED`, `NOT_APPLICABLE`, and `TERMINAL` must never be coerced to `NO`.

### Frozen research means database-immutable

Freezing a run now:

1. calculates a canonical SHA-256 digest across run metadata and canonical research tables;
2. stores `frozen_at` and `frozen_digest`;
3. activates database triggers that reject INSERT/UPDATE/DELETE against canonical rows for the frozen run;
4. permits later verification by recomputing the digest.

A frozen run is not a UI flag. If outcomes, audit logic, thresholds, code, config, or dataset identity changes, create a new `research_run_id`.

### Inference contract

Node-edge uncertainty is estimated with **trading-day cluster bootstrap**, not IID event/trade bootstrap. Events from a sampled trading day travel together.

All node-edge hypothesis p-values in one research run are adjusted together with **Benjamini-Hochberg FDR**. Persist both `p_value` and `q_value`; production-facing promotion may not use an unadjusted p-value as its sole significance criterion.

### Campaign and dataset provenance

Research year roles are campaign-specific. A campaign registers immutable dataset identities with:

- `dataset_id`
- role (`DISCOVERY`, `VALIDATION`, `FINAL_HOLDOUT`)
- year
- source filename
- SHA-256
- optional observed time coverage / metadata

Every campaign-backed research run pins the selected dataset rows into `research_run_datasets`, so later campaign changes cannot rewrite the run's provenance. Freezing a campaign prevents dataset mutation.

The fixed 2025/2024/2026 mapping remains only as backward-compatible Fabio governance when no `campaign_id` is supplied.

## Research gates

`Raw Integrity → Contract Integrity → Causal Event Truth → Event Sanity → Physical Outcomes → Reverse Audit → Sequential Contribution → Ablation → Evidence Registry → Training Truth → Certification → Production → Live parity`

A later gate is not allowed to make an earlier gate pass retroactively.

## Node classifications

Only: `CORE`, `OPTIONAL`, `STATE`, `REDUNDANT`, `HARMFUL`, `REGIME_DEPENDENT`, `INSUFFICIENT`.

High same-seq rate alone does not make a node redundant. Redundancy requires timing overlap **plus** negligible incremental edge **plus** harmless ablation and no material winner/loser handling improvement.

A `CORE` promotion from node-edge inference additionally requires adequate YES/NO sample support, trading-day-cluster confidence bounds, and BH-FDR-adjusted evidence. Discovery runs may generate hypotheses but do not promote a statistical edge directly to production truth.

## Ablation boundary

With four-state reachability, removing a blocking gate does **not** magically make its `NOT_REACHED` descendants observed. V6's ordinary ablation table is therefore labelled `counterfactual_reconstruction=false` and uses only actually evaluated downstream observations. True counterfactual ablation requires a relaxed opportunity universe or causal re-evaluation of the removed-gate branch.

## Training boundary

Only `EVALUATED` nodes may enter Training Truth. `NOT_REACHED`, `NOT_APPLICABLE`, and `TERMINAL` are causal lineage states, not negative training examples.

## Production boundary

Production eligibility is evidence, not philosophy. MR should support roughly 1R, BO roughly 2R, with meaningful points, costs/latency robustness, acceptable DD, preserved right tail, and Historical ↔ Live causal parity. The 18-node Concept Tree may legitimately shrink in the Production Tree.
