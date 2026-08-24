# FABIO_REAL_EVIDENCE_V1_20260821

This directory is the auditable real-data evidence campaign for the Fabio Decision Gym research branch.

Start with [`FULL_REPORT_20260821.md`](FULL_REPORT_20260821.md). The completed G2 causal closeout evidence is under [`g2_causal_signal_truth/`](g2_causal_signal_truth/).

For the exact project state at the current checkpoint, read:

- [`CURRENT_STATUS_20260824.md`](CURRENT_STATUS_20260824.md) — detailed current state, permanent facts, G2 results, forbidden work and measured execution times.
- [`NEXT_PHASE_PLAN.md`](NEXT_PHASE_PLAN.md) — ordered release/G3/Validation/Holdout plan.
- [`RELEASE_CHECKPOINT_20260824.json`](RELEASE_CHECKPOINT_20260824.json) — machine-readable checkpoint state.

## Gate snapshot

- G0 Software Integrity: **PASS**
- G1 Raw Data Truth: **PASS for the supplied 2024/2025 sources**
- G2 Causal Signal Truth: **PASS — research evidence** — 223/223 eligible 2025 Discovery sessions completed; physical truth, reachability, lineage, causal ordering and targeted QA all passed
- G2 GitHub release gate: **IN PROGRESS at this checkpoint** — current progress/source/evidence/status are committed; final repository-tree verification and required workflow closeout remain
- G3 Statistical Edge Truth: **HARD BLOCK / NOT STARTED** — no G2 funnel count is an edge/PF claim
- 2024 strategy validation: **not opened**
- 2026 final holdout: **sealed**
- Production: **blocked**

## Permanent source facts

- 2024 is Validation Reserved. The source is missing the expected regular session **2024-12-27**, so Previous Value must reset before 2024-12-30.
- 2025 is **Partial-Year Discovery**, not a full calendar year: 236 observed sessions from 2025-01-02 through 2025-12-19; G2 has 223 eligible scanner sessions after the first observed session and 12 frozen roll-blackout sessions are excluded.
- 2026 remains sealed. Only source/footer/schema/hash metadata has been inspected; no strategy event, outcome, PnL, threshold or edge has been inspected.

## G2 closeout

G2 introduced explicit node reachability semantics: `EVALUATED`, `NOT_REACHED`, `NOT_APPLICABLE`, and `TERMINAL`. G3 node comparisons are hard-restricted to `EVALUATED` instances. A preregistered causal-ordering amendment repaired BO strict entries that previously occurred before required causal gates had completed; the amendment was frozen before future-path outcomes or PF inspection.

The final G2 run contains **33,046 events**, **395,684 node instances**, **0 physical mismatches**, **0 causal-ordering violations**, and **245 targeted-QA cases with 0 systematic defects**. Strict entries are MR=4 and BO=132. The largest conditional conversion collapse is at `MR_LVN` (179 reached → 5 YES) and `BO_LVN` (14,051 reached → 387 YES). These are causal/funnel findings only, not statistical-edge conclusions.

## Research boundary

At this checkpoint the following remain intentionally uncomputed/unaccepted: MFE, MAE, PF, trading-day bootstrap, BH-FDR, node edge classification, volatility-scale selection, regime-threshold selection, 2024 confirmatory strategy validation and every 2026 strategy result.

Raw Parquet files are intentionally not committed to GitHub. Exact source identity and the deterministic G2 event identity are recorded in `MANIFEST.json` and the G2 evidence artifacts.
