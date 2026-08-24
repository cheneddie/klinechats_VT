# G2 Causal Signal Truth Closeout — 2025 Partial-Year Discovery

Gate: **PASS**

## Scope

This report closes G2 only. No MFE/MAE, PF, bootstrap/FDR, node-edge classification, 2024 strategy validation, or 2026 strategy signal/outcome was used.

## Full migration regression

- Observed sessions: **236**
- Eligible sessions: **223**
- Completed sessions: **223**
- Failed sessions: **0**
- Unexpected regression violations: **0**
- Expected preregistered BO causal-entry repairs: **28**
- Deterministic aggregate event hash: `872168c2acaea1e32b51b29c995dc97993fc9e3e39d52493fb187871266c87ac`

## Logical / physical / causal audit

- Node instances: **395,684**
- Resolution trace completeness: **100%**
- Evaluated decision completeness: **100%**
- Required anchor completeness: **100%**
- NOT_REACHED blocker completeness: **100%**
- Parent reachability violations: **0**
- Blocker ancestor violations: **0**
- Blocker cycles: **0**
- Causal ordering violations: **0**
- Physical unique `_seq` requested/resolved: **106,087 / 106,087**
- Missing/time/price/product/contract/session/source mismatches: **0**

## Reachability-aware Funnel

Total scanner events: **33,046**. Strict entries: **MR 4 / BO 132**.

### MR

| Node | Reached | YES | Direct NO | NOT_REACHED | Conditional pass |
|---|---:|---:|---:|---:|---:|
| AUC_ATTEMPT | 16,461 | 16,461 | 0 | 0 | 100.00% |
| MR_REJECTION | 16,461 | 941 | 15,520 | 0 | 5.72% |
| MR_CLEAR_RECLAIM | 941 | 179 | 762 | 15,520 | 19.02% |
| MR_RECLAIM_LEG | 179 | 179 | 0 | 16,282 | 100.00% |
| MR_LVN | 179 | 5 | 174 | 16,282 | **2.79%** |
| MR_PULLBACK | 5 | 4 | 1 | 16,456 | 80.00% |
| MR_ENTRY | 4 | 4 | 0 | 16,457 | 100.00% |

### BO

| Node | Reached | YES | Direct NO | NOT_REACHED | Conditional pass |
|---|---:|---:|---:|---:|---:|
| AUC_ATTEMPT | 16,461 | 16,461 | 0 | 0 | 100.00% |
| BO_DISPLACEMENT | 16,461 | 14,384 | 2,077 | 0 | 87.38% |
| BO_ACCEPTANCE | 14,384 | 14,379 | 5 | 2,077 | 99.97% |
| BO_IMPULSE_LEG | 14,379 | 14,051 | 328 | 2,082 | 97.72% |
| BO_LVN | 14,051 | 387 | 13,664 | 2,410 | **2.75%** |
| BO_PULLBACK | 387 | 292 | 95 | 16,074 | 75.45% |
| BO_RESPONSE | 292 | 244 | 48 | 16,169 | 83.56% |
| BO_ENTRY | 244 | 132 | 112 | 16,217 | 54.10% |

The main G2 conversion collapse is therefore LVN on both branches. This does **not** establish that LVN has or lacks Edge; G3 must test that on the `EVALUATED` universe.

## Targeted QA

- Cases reviewed: **245**
- Systematic defects: **0**
- Roll/closure boundary cases are included.
- Sample shortfalls are recorded explicitly: MR_ENTRY YES requested 20 / available 4; MR_ENTRY direct-NO requested 20 / available 0.
- Future-path extremes (MFE/MAE) were intentionally not used because G2 forbids them before causal-truth closeout.

## Gate decision

`G2_CAUSAL_SIGNAL_TRUTH = PASS`.

The next permitted stage is G3 on 2025 Discovery only, beginning with relaxed physical outcomes. 2024 remains Reserved and 2026 remains Sealed.
