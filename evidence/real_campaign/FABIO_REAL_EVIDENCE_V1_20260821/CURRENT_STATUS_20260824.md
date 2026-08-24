# Fabio Evidence Campaign — Current Status Checkpoint

> Checkpoint time: 2026-08-24 18:36 +08:00  
> Repository: `cheneddie/klinechats_VT`  
> Research branch: `fabio-decision-gym-v4`  
> Campaign: `FABIO_REAL_EVIDENCE_V1_20260821`

## Executive status

This checkpoint persists all currently available G2 closeout progress and release source. It is a **research-progress checkpoint**, not a claim that the GitHub release gate or G3 has completed.

| Gate | Status | Meaning |
|---|---|---|
| G0 Software Integrity | PASS | Prior frozen methodology/research platform baseline passed the required workflow suite. |
| G1 Raw Data Truth | PASS | 2024/2025 source identity, contract policy, physical-order truth and exchange-calendar coverage are frozen. |
| G2 Causal Signal Truth | PASS — research evidence | Fresh 2025 closeout completed 223/223 eligible sessions with zero unexpected regression violations; trace, lineage, physical truth, ordering and targeted QA passed. |
| G2 GitHub release gate | IN PROGRESS | This checkpoint uploads all currently persisted release source/reports/status. Final release-tree verification and full CI closeout remain to be completed. |
| G3 Statistical Edge Truth | HARD BLOCK / NOT STARTED | No PF, MFE/MAE, bootstrap, FDR or node-edge conclusion is authorized by this checkpoint. |
| 2024 Validation | RESERVED | May not be used to tune rules before Discovery freeze. |
| 2026 Final Holdout | SEALED | No strategy signals/outcomes/edge have been inspected. |
| Production | BLOCKED | G3+, Validation, execution/risk, parity, Shadow and Paper gates remain outstanding. |

## Permanent source facts

### 2024 Validation Reserved

- Source SHA-256: `6f76ecde2c6d9c13fe5381ffe0798fe05668a7d1e8abe85c7b0125581d5eb25c`
- Frozen coverage fact: expected regular session **2024-12-27** is absent.
- Consequence: Previous Value must reset before **2024-12-30**.
- 2024 remains forbidden for rule/threshold selection at this stage.

### 2025 Partial-Year Discovery

- Source file: `MTX_2025(5).parquet`
- Source SHA-256: `774b6f62b1e1a30ec159c7402b6967045ea3d99b59bfb16aeb0e0462a7a15156`
- Observed source window: **2025-01-02 through 2025-12-19**
- Observed regular sessions: **236**
- G2 eligible sessions: **223**
- Exclusions: first observed session + 12 frozen roll-blackout sessions
- This source must never be labelled “full-year 2025”.

### 2026 Final Holdout

- Source SHA-256: `304f7d4e531374c3d4776f0c4d0e93e135dbd96c8b74956e9eb629fadbc957d6`
- Status: **SEALED**
- Only source/footer/schema/hash metadata has been inspected.

## G2 semantic model now frozen for this closeout

Node evaluation states:

- `EVALUATED`: the node was causally reached and answered YES/NO.
- `NOT_REACHED`: an upstream strict prerequisite failed first; answer is null and blocker lineage is required.
- `NOT_APPLICABLE`: the node does not belong to the current branch; answer is null.
- `TERMINAL`: decision flow terminates; excluded from G3 node-edge attribution.

G3 node comparisons are hard-restricted to the **`EVALUATED` universe**.

## G2 causal repairs

`G2_CAUSAL_ORDERING_AMENDMENT_001` is frozen before future-path outcome/PF inspection.

It repairs only BO strict entries whose legacy entry decision occurred before all required strict-chain gates had causally completed. The repair recomputes entry price/risk/extension/outside-state/quality/stop/target at the causal eligibility tick. Any other strategy semantic difference remains a regression failure.

## Final fresh 2025 G2 closeout result

- Observed sessions: **236**
- Eligible sessions: **223**
- Completed sessions: **223/223**
- Failed sessions: **0**
- Unexpected regression violations: **0**
- Expected preregistered BO causal-entry repairs: **28**
- Scanner events: **33,046**
- Node instances: **395,684**
- Deterministic event aggregate SHA-256: `872168c2acaea1e32b51b29c995dc97993fc9e3e39d52493fb187871266c87ac`

### Logical / lineage / physical / ordering gates

- Resolution trace completeness: **100%**
- Evaluated decision completeness: **100%**
- Required anchor completeness: **100%**
- NOT_REACHED blocker completeness: **100%**
- Parent reachability violations: **0**
- Blocker ancestor violations: **0**
- Blocker cycles: **0**
- Causal ordering violations: **0**
- Physical unique `_seq` requested/resolved: **106,087 / 106,087**
- Missing seq: **0**
- Time mismatch: **0**
- Price mismatch: **0**
- Product mismatch: **0**
- Contract mismatch: **0**
- Session mismatch: **0**
- Source mismatch: **0**

### Targeted QA

- Final selected causal QA cases: **245**
- Systematic defects: **0**
- Sample shortfalls remain explicit; no artificial cases were created to hit quotas.

## Reachability-aware funnel

Strict entries:

- MR: **4**
- BO: **132**

Largest conditional conversion collapses:

- `MR_LVN`: 179 reached → 5 YES / 174 direct NO = **2.79%** pass rate.
- `BO_LVN`: 14,051 reached → 387 YES / 13,664 direct NO = **2.75%** pass rate.

These are **causal/funnel findings only**. They do not establish profitability or edge.

## Research calculations explicitly NOT performed yet

The following remain uncomputed/unaccepted at this checkpoint:

- MFE
- MAE
- PF
- 1R/2R future-path strategy outcome conclusions
- trading-day bootstrap
- BH-FDR
- node edge classification
- representative volatility-scale selection
- causal regime threshold selection
- forced-flat selection
- cooldown selection
- 2024 confirmatory strategy validation
- 2026 strategy results

## Execution-time record from the closeout work

- Frozen V4 + G2 focused regression tests: **2.83 seconds** in the measured fresh run.
- Fresh 223-session two-shard causal scan: shard 0 **612.3 s**, shard 1 **622.6 s**; wall time governed by slower shard = **10m 22.6s**.
- Full G2 audit: **18 s**.
- Boundary-QA amendment re-audit: **17 s**.
- Fail-closed evidence packaging: **2 s**.

Earlier exploratory/restart cycles are research history, not release evidence; the final accepted identities are the fresh complete run and the gate results above.

## Current GitHub release state

The current-progress checkpoint includes the G2 closeout source, frozen policy/amendment, regression tests and audit/builder source, plus the currently persisted G2 and campaign reports. The official release still requires a final repository-tree/file-presence verification and required workflow closeout after this checkpoint commit.

No G3 work is authorized until that release gate is clean.
