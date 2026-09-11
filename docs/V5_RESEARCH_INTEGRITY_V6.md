# V5 Research Integrity V6 — P0 Closeout Contract

> Branch: `research-integrity-p0`  
> Base: `fabio-decision-gym-v4`  
> Scope: repair research truth boundaries before Strategy Lab / parameter optimization.

## Why V6 exists

V5 already had the correct causal philosophy, but several guarantees were only conventions rather than enforceable data contracts. V6 closes the gap before a generic backtest/optimization layer is allowed to reuse the evidence store.

## 1. Four-state node persistence

`event_nodes` now persists causal reachability explicitly:

| state | answer | decision assertion | resolution | blocker |
|---|---|---|---|---|
| `EVALUATED` | `0/1` | required | mirrors decision when needed | optional |
| `NOT_REACHED` | `NULL` | forbidden | required | required |
| `NOT_APPLICABLE` | `NULL` | forbidden | required | optional |
| `TERMINAL` | `NULL` | forbidden | required | optional |

A V5 legacy schema migration rebuilds the old `answer INTEGER NOT NULL` table into the nullable V6 schema without changing existing legacy YES/NO rows. Legacy V4 snapshots infer downstream `NOT_REACHED` states after the first strict-chain failure; G2-native `evaluation_status` is preserved when present.

## 2. G3 universe

Reverse Node Audit, sequential contribution, evidence counts, and Training Truth use only causally evaluated nodes. Non-evaluated states are lineage, not negative examples.

Persisted edge rows declare:

- `evaluation_universe = EVALUATED_ONLY`
- `bootstrap_unit = TRADING_DAY`
- `p_value`
- `q_value`
- cluster count / bootstrap repetitions

## 3. Statistical inference

Node-edge confidence intervals use trading-day cluster bootstrap. All node-edge p-values inside a run enter one BH-FDR family. This prevents same-day event dependence and large node search families from being treated as independent evidence.

The heuristic node classifier is now subordinate to sample support + clustered CI + FDR. Discovery may generate an `OPTIONAL` hypothesis; statistical `CORE` promotion requires validation/holdout-level evidence and cannot be created by raw Discovery significance alone.

## 4. Immutable research runs

Freezing computes a canonical SHA-256 over:

- normalized research-run metadata
- events
- event nodes
- physical outcomes
- node-edge results
- sequential results
- ablation results
- evidence registry
- pinned run datasets

Database triggers then reject canonical INSERT/UPDATE/DELETE operations for that `research_run_id`. A stored digest can be re-verified later. Training attempts remain outside the research digest because they are human-learning records rather than market evidence.

## 5. Campaign-specific governance

The legacy Fabio mapping remains compatible:

`2025 Discovery → 2024 Validation → 2026 Final Holdout`

Generic strategies instead create a `research_campaign`, register source datasets with SHA-256 identities and explicit roles, and pin the chosen dataset records into every research run. Campaign freeze prevents later dataset mutation.

This lets ORB, VWAP, POC, Fabio MR/BO, or future strategy families use different Discovery / Validation / Holdout years without weakening provenance.

## 6. Ablation warning

Once reachability is explicit, deleting an upstream failed gate does not reveal the unobserved decisions of downstream `NOT_REACHED` nodes. V6 therefore labels ordinary ablation as `counterfactual_reconstruction=false`. True removed-gate ablation must come from a relaxed opportunity universe or causal branch re-evaluation.

## 7. Required acceptance gates

P0 is complete only when CI proves:

1. V5 Python syntax passes.
2. Existing V5 research/training/certification integration remains green.
3. V6 four-state migration passes.
4. `NOT_REACHED` rows are excluded from G3 edge universes.
5. cluster bootstrap and BH-FDR contracts pass.
6. frozen-run database writes fail closed and digest verification passes.
7. custom campaign year roles and SHA provenance work while legacy Fabio governance remains intact.
8. V4 causal regression tests remain green.

No merge to `main` is authorized by this document.
