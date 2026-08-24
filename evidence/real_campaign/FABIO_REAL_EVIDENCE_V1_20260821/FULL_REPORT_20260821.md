# Fabio Real Evidence Campaign — G0/G1/G2 Complete Evidence Report

> Campaign: `FABIO_REAL_EVIDENCE_V1_20260821`  
> Repository: `cheneddie/klinechats_VT`  
> Research branch: `fabio-decision-gym-v4`  
> Baseline methodology commit: `53dbd9450922cfd24385e9f98b116d0d912e21e5`  
> Current boundary: **G2 complete; G3 not started; 2024 strategy validation reserved; 2026 final holdout sealed.**

## 1. Executive conclusion

The Evidence Campaign is complete through **G2 Causal Signal Truth**. G0 established software integrity, G1 established raw-source / contract / calendar truth, and G2 established that scanner events and node states are causally traceable to physical MTX rows with explicit reachability semantics.

G2 closes with **223/223 eligible 2025 Discovery sessions**, **33,046 events**, **395,684 node instances**, **0 unexpected migration violations**, **0 physical truth mismatches**, **0 causal-ordering violations**, and **245 targeted-QA cases with 0 systematic defects**. The only strategy-semantic differences from the frozen legacy scanner are **28 preregistered BO strict-entry causal repairs** required to prevent strict entries from occurring before required causal gates had completed.

No MFE/MAE, PF, bootstrap/FDR, node-edge classification, 2024 confirmatory strategy result, or 2026 strategy signal/outcome was used to obtain this G2 PASS.

## 2. Frozen year roles

| Year | Role | Status |
|---|---|---|
| 2025 | Partial-Year Discovery | G0/G1/G2 complete; G3 not started |
| 2024 | Validation Reserved | G1 source QA only; strategy validation not opened |
| 2026 | Final Holdout | SEALED; no strategy signals/outcomes inspected |

## 3. G0 — Software Integrity

The baseline methodology release previously passed the eight repository workflows: CI, Browser release QA, V4 CI, V4 Final QA Watchdog, V5 Research CI, V5 Training CI, V5 Final Watchdog, and Stage screenshot. The present G2 release must pass the same release checks before GitHub closeout is final.

## 4. G1 — Raw Data Truth

### 2024 Validation source

- `MTX_2024(4).parquet`
- bytes: **173,260,633**
- SHA-256: `6f76ecde2c6d9c13fe5381ffe0798fe05668a7d1e8abe85c7b0125581d5eb25c`
- physical rows: **50,862,751**
- observed regular sessions: **241** vs frozen expected **242**

Permanent fact: **2024-12-27 is an expected regular TAIFEX session but is absent from the source.** Previous Value from 2024-12-26 must therefore reset before 2024-12-30.

### 2025 Discovery source

- `MTX_2025(5).parquet`
- bytes: **146,569,961**
- SHA-256: `774b6f62b1e1a30ec159c7402b6967045ea3d99b59bfb16aeb0e0462a7a15156`
- physical MTX rows: **39,416,621**
- six-digit outright rows: **39,416,516**
- day-session rows: **19,861,188**
- observed regular sessions: **236**
- source window: **2025-01-02 through 2025-12-19**

The correct permanent label is **2025 PARTIAL-YEAR DISCOVERY**, never “full-year 2025”.

Physical Parquet row order remains market-sequence truth. Immutable `_seq` is assigned before filtering. Same-second rows are not re-sorted by datetime/price/side. `side` remains a tick-direction proxy only, not true aggressor classification, bid/ask delta or CVD.

## 5. Coverage / contract governance

Active coverage policy is `TAIFEX_SESSION_CALENDAR_V2` with frozen calendar `TAIFEX_REGULAR_SESSION_V1_20260821`. Official closures do not create profile-chain resets; a missing expected regular session does.

Contract selection remains causal calendar-front MTX outright selection. Completed-day dominant-volume ranking is diagnostic only.

## 6. G2 Reachability semantics

G2 separates four states:

- `EVALUATED` — node was reached and answered YES/NO;
- `NOT_REACHED` — an upstream strict prerequisite failed first;
- `NOT_APPLICABLE` — node does not belong to the current branch;
- `TERMINAL` — decision flow ends here.

Every `NOT_REACHED` node carries blocker lineage to the first truly `EVALUATED / NO` ancestor. G3 node-edge comparisons are hard-restricted to the `EVALUATED` universe, preventing upstream effects from being repeatedly attributed to downstream nodes.

## 7. G2 causal-ordering repair

G2 auditing found a genuine legacy BO lookahead defect: some strict entries were timestamped before required causal gates had formally completed. It also found that legacy `anchor_price` mixed structural reference levels with physical tick prices.

`G2_CAUSAL_ORDERING_AMENDMENT_001` was frozen before any future-outcome/PF inspection. It requires physical `anchor_*` to resolve to raw ticks, separates structural `reference_price`, separates observation from formal decision/resolution, and delays BO strict entry until all required gates are causally complete. Only explicitly tagged BO_ENTRY repairs may change strict-entry semantics.

Final migration contained **28 expected repairs** and **0 unexpected semantic differences**.

## 8. Session Eligibility / Migration

Observed sessions: **236**. Eligible sessions: **223**. Excluded: **13** = first observed session + 12 frozen roll-blackout sessions. Unknown exclusion reasons: **0**.

Full migration regression:

- completed **223/223**
- failed **0**
- unexpected violations **0**
- expected causal-entry repairs **28**
- deterministic event aggregate SHA-256: `872168c2acaea1e32b51b29c995dc97993fc9e3e39d52493fb187871266c87ac`
- relaxed terminal-universe differences: **0**

## 9. Logical Trace / Blocker Lineage

Total node instances: **395,684**. Resolution, EVALUATED decision, required anchor, and NOT_REACHED blocker completeness are all **100%**. Parent reachability violations, blocker-ancestor violations, and blocker cycles are **0**.

## 10. Single-pass Physical Truth

All persisted anchor/decision/resolution/strict-entry/terminal-entry physical claims were resolved against the raw 2025 Parquet.

- unique `_seq` requested: **106,087**
- unique `_seq` resolved: **106,087**
- missing seq: **0**
- time mismatch: **0**
- price mismatch: **0**
- product mismatch: **0**
- contract mismatch: **0**
- session mismatch: **0**
- source mismatch: **0**

Physical Truth: **PASS**.

## 11. Causal Ordering

Final ordering violations: **0**. Strict entries do not precede required strict-chain decisions. Causal Ordering: **PASS**.

## 12. Reachability-aware Funnel

The scanner produced **33,046 events** from **16,585 unique auction attempts**. Strict entries are **MR=4** and **BO=132**.

### MR

| Node | Reached | YES | Direct NO | NOT_REACHED | Conditional pass |
|---|---:|---:|---:|---:|---:|
| MR_REJECTION | 16,461 | 941 | 15,520 | 0 | 5.72% |
| MR_CLEAR_RECLAIM | 941 | 179 | 762 | 15,520 | 19.02% |
| MR_RECLAIM_LEG | 179 | 179 | 0 | 16,282 | 100.00% |
| MR_LVN | 179 | 5 | 174 | 16,282 | **2.79%** |
| MR_PULLBACK | 5 | 4 | 1 | 16,456 | 80.00% |
| MR_ENTRY | 4 | 4 | 0 | 16,457 | 100.00% |

### BO

| Node | Reached | YES | Direct NO | NOT_REACHED | Conditional pass |
|---|---:|---:|---:|---:|---:|
| BO_DISPLACEMENT | 16,461 | 14,384 | 2,077 | 0 | 87.38% |
| BO_ACCEPTANCE | 14,384 | 14,379 | 5 | 2,077 | 99.97% |
| BO_IMPULSE_LEG | 14,379 | 14,051 | 328 | 2,082 | 97.72% |
| BO_LVN | 14,051 | 387 | 13,664 | 2,410 | **2.75%** |
| BO_PULLBACK | 387 | 292 | 95 | 16,074 | 75.45% |
| BO_RESPONSE | 292 | 244 | 48 | 16,169 | 83.56% |
| BO_ENTRY | 244 | 132 | 112 | 16,217 | 54.10% |

The strongest post-reach conversion collapse is LVN on both branches. This is a G2 structural/causal finding only; it does not establish positive or negative Edge.

## 13. Targeted QA

Targeted QA reviewed **245** cases and found **0 systematic defects**. Roll-day and long official-closure boundary cases are included. Sample shortfalls are explicitly preserved: MR_ENTRY YES requested 20 / available 4; MR_ENTRY direct-NO requested 20 / available 0. Future-path MFE/MAE extremes were intentionally excluded from G2.

## 14. Gate decision

`G2_CAUSAL_SIGNAL_TRUTH = PASS` because Session Eligibility, Migration Regression, Strategy Semantics, Relaxed Universe, Blocker Lineage, Logical Trace, Physical Truth, Causal Ordering, and Targeted QA all pass.

At gate close, MFE/MAE/PF/bootstrap/FDR/statistical edge are **not computed**. G2 PASS is therefore independent of profitability.

## 15. Next permitted sequence

After this G2 GitHub release is CI-clean, the next permitted stage is **G3 Discovery on 2025 only**: freeze Primary/Exploratory hypotheses, compute relaxed physical outcomes, strict physical outcomes, 18-Node Evidence Matrix, Reverse Audit, Sequential Contribution, Ablation, trading-day bootstrap 10,000, BH-FDR q=0.10, then freeze volatility/regime/forced-flat/cooldown rules before opening 2024 Validation.

2024 may not be used for tuning. 2026 remains sealed.

## 16. Production status

**BLOCKED.** G2 establishes causal and physical truth only; it does not establish tradable edge or production readiness.
