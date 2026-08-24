# G2 Causal Signal Truth — 2025 Partial-Year Discovery

Status: **PASS**. Authoritative gate file: `g2_audit_gate.json`.

This bundle closes causal-signal truth only. It contains no MFE/MAE, PF, bootstrap/FDR, node-edge classification, 2024 strategy validation, or 2026 strategy outcomes.

Reachability semantics are frozen as `EVALUATED`, `NOT_REACHED`, `NOT_APPLICABLE`, and `TERMINAL`. G3 node-edge comparisons must use the `EVALUATED` universe only.

The source is `MTX_2025(5).parquet`, SHA-256 `774b6f62b1e1a30ec159c7402b6967045ea3d99b59bfb16aeb0e0462a7a15156`, covering 236 observed sessions from 2025-01-02 through 2025-12-19; 223 sessions are G2 scanner-eligible after excluding the first observed session and 12 frozen roll-blackout sessions.

Full migration regression completed 223/223 sessions with 0 unexpected violations and 28 preregistered BO causal-entry repairs. Physical truth resolved 106,087 unique physical `_seq` values with 0 missing/time/price/product/contract/session/source mismatches. Targeted QA reviewed 245 cases with 0 systematic defects.

The strongest G2 conversion collapse is `MR_LVN` (179 reached → 5 YES, 2.79%) and `BO_LVN` (14,051 reached → 387 YES, 2.75%). This is a structural/causal finding only, not an Edge claim.
