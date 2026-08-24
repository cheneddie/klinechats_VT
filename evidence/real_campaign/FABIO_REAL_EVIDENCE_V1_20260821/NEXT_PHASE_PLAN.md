# Fabio Evidence Campaign — Next Phase Plan

> Applies after the current G2 progress checkpoint.  
> G3 remains hard-blocked until the G2 GitHub release gate is verified clean.

## Phase A — Finish the G2 GitHub release gate

1. Verify the official research branch contains every current G2 source/report/checkpoint artifact expected by this checkpoint.
2. Verify `MANIFEST.json`, `README.md`, `FULL_REPORT_20260821.md`, `CURRENT_STATUS_20260824.md` and this plan agree on gate status.
3. Verify the G2 closeout source and policies are present:
   - `server/g2_closeout.py`
   - `tools/run_g2_closeout.py`
   - `tools/run_g2_shard.py`
   - `tools/audit_g2_closeout.py`
   - `tools/build_g2_evidence.py`
   - `config/research/g2_node_reachability_v1.json`
   - `config/research/g2_causal_ordering_amendment_001.json`
   - `tests/test_g2_closeout_semantics.py`
4. Re-run the required GitHub workflow suite on the official research-branch checkpoint.
5. Required release decision:
   - all required checks green → G2 GitHub release gate PASS;
   - any failed check → stay in G2 release remediation; do not start G3.

## Phase B — Freeze the concrete G3 hypothesis registry

Before outcome-family inference, create explicit Primary vs Exploratory hypotheses.

Primary family must answer whether each reached node contributes incremental information. Primary tests alone enter the core BH-FDR family.

Exploratory splits may include time-of-day, direction, month, volatility/regime context or other stratification, but cannot be promoted to confirmed edge without independent validation.

## Phase C — 2025 Relaxed Physical Outcomes

Purpose: create a common physical future-path outcome universe for broad terminal opportunities, not to optimize PF.

Rules:

- preserve physical `_seq` order;
- use only post-decision physical ticks;
- same-tick fill is forbidden;
- session boundary rules remain frozen;
- no 2024/2026 data use.

Outputs must support node YES vs direct NO comparison on a common causal universe.

## Phase D — 2025 Strict Physical Outcomes

Compute outcomes only for actual causal strict entries after the G2 repair semantics.

Primary strategy targets remain:

- MR: approximately 1R research target.
- BO: approximately 2R research target.

PF is an output metric, not the center of the research decision.

## Phase E — 18-Node Evidence Matrix

For every node, compare only:

`EVALUATED YES` vs `EVALUATED direct NO`.

Required outputs include sample sizes, Avg/Median ΔR, 2R-retention where applicable, loser rejection, clustered confidence intervals and classification eligibility.

Allowed final node labels:

- CORE
- OPTIONAL
- STATE
- REDUNDANT
- HARMFUL
- REGIME_DEPENDENT
- INSUFFICIENT

## Phase F — Reverse Audit → Sequential Contribution → Ablation

Run in this order:

1. Reverse Node Audit
2. Sequential Contribution
3. Ablation

Do not infer redundancy from same-seq overlap alone.

## Phase G — Statistical inference

- Resampling unit: **trading_date**
- Bootstrap repetitions: **10,000**
- Confidence interval: **95%**
- Secondary robustness: calendar week
- Multiple-testing control: **BH-FDR q=0.10** for preregistered Primary families
- Low-sample nodes: `INSUFFICIENT`, not forced significance

## Phase H — Discovery-only policy selection and freeze

Using **2025 only**, select and freeze:

- `VOLATILITY_VALUE_SCALE_V1`
- causal regime thresholds/labels
- forced-flat policy
- cooldown policy
- duplicate-suppression policy
- strict MR/BO target rules
- outcome horizon definitions
- bootstrap/FDR policy identities

Then create:

`DISCOVERY_FREEZE_MANIFEST.json`

The manifest must include Git commit and hashes for scanner, node registry, strategy config, coverage/contract/session policies and all selected management policies.

## Phase I — Open 2024 confirmatory Validation

Only after the Discovery freeze is complete:

1. Load the frozen package.
2. Run 2024 without parameter invention or tuning.
3. Respect the permanent 2024 coverage reset at 2024-12-27/12-30.
4. Compare direction/sign stability, clustered evidence and drawdown constraints.
5. A node that changes sign materially between Discovery and Validation may become `REGIME_DEPENDENT` or fail.

## Phase J — 2026 Final Holdout remains sealed

Do not inspect 2026 strategy signals/outcomes until the frozen candidate has passed the allowed pre-holdout gates and an intentional holdout reveal is recorded.

Schema compatibility work may use metadata/synthetic/transformed fixtures only.

## Production remains blocked after G3

Even a statistically positive G3/G4 result is not production approval. Production still requires:

- execution/cost/latency robustness;
- risk constraints;
- historical/live parity;
- Shadow trading;
- Paper trading;
- drift monitoring;
- promotion governance.

## Immediate next commit after this checkpoint

The immediate next engineering/research commit should be **G2 release verification/remediation only**. No new UI/product features and no G3 outcome code should be accepted into the research flow until the G2 GitHub release gate is clean.
