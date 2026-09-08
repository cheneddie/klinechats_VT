# Strategy Lab / Fabio Research — Goal Alignment Review

Date: 2026-09-08  
Repository: `cheneddie/klinechats_VT`  
Working branch: `research-integrity-p0`  
Integration base: `fabio-decision-gym-v4`  
`main` remains intentionally untouched.

## Final goal

The final goal is **not** a feature-rich Strategy Lab UI and is **not** green synthetic CI by itself. The goal is a research system that can determine, using real MTX data and immutable causal evidence, whether Fabio-style Mean Reversion (MR) and Breakout Retest (BO) strategies have enough durable, executable edge to justify production promotion.

The governed path remains:

`Raw / Contract Integrity → Frozen Discovery → Event Sanity → Optimization / Robust Plateau → Candidate Freeze → Validation → Final Holdout → Cost / Latency / Portfolio Stress → Historical↔Live Causal Parity → Paper Trading → Production Gate → Production Deployment → Live Deployment Health`

Final Holdout must never be used for tuning.

## User trading-value acceptance criteria

Production research must enforce more than `PF > 1`.

At minimum:

- OOS expectancy remains positive after costs.
- Profit Factor remains acceptable.
- Drawdown remains acceptable.
- Cost, latency and portfolio stress remain acceptable.
- MR reward structure can support approximately **1R**.
- BO reward structure can support approximately **2R**.
- Average realized trade value must be economically meaningful relative to contemporaneous volatility: **average realized NET points / frozen event-time ATR >= 10%**.
- Results must not be concentrated in one small month cluster.
- Results must not depend on one year carrying nearly all positive profitability.
- Historical and live causal state transitions / decision sequence / entry must agree before promotion.
- Paper/live evidence must be tied to the exact immutable deployment identity.

The ATR 10% floor is an explicit user requirement and is therefore a default Production Value threshold. Maximum acceptable month/year positive-profit concentration has **not** been specified; the system intentionally provides no invented default. Those two concentration limits must be explicitly frozen in Production Gate policy. Blank / missing concentration policy fails closed.

## Current alignment matrix

| Layer | Current status | Alignment with final goal |
|---|---|---|
| Raw physical `_seq` / causal truth | Implemented and regression-tested | **Aligned** |
| Four-state node truth / immutable research runs | Implemented | **Aligned** |
| Campaign dataset SHA-256 provenance | Implemented | **Aligned** |
| Formal Backtest / immutable Trade Ledger / digest | Implemented | **Aligned** |
| Execution cost / slippage / latency | Implemented | **Aligned** |
| Portfolio execution policy / overlap arbitration | Implemented | **Aligned** |
| Report EV / PF / DD / MFE / MAE / right-tail | Implemented | **Aligned** |
| Robust plateau optimizer / FDR / Final Holdout tuning denial | Implemented | **Aligned** |
| Discovery → Validation → Final Holdout order | Implemented | **Aligned** |
| BASE / SLIPPAGE / LATENCY / COMBINED stress | Implemented | **Aligned** |
| Candidate Evaluation background execution | Strict E2E requires terminal `SUCCEEDED`, real `evaluation_id`, clean audit metadata | **Aligned** |
| Historical↔Live parity evidence | Governed append-only evidence path | **Aligned, real evidence not yet supplied** |
| Paper evidence | Governed append-only evidence path | **Aligned, real evidence not yet supplied** |
| MR >= ~1R Production reward floor | Implemented | **Aligned** |
| BO >= ~2R Production reward floor | Implemented | **Aligned** |
| Average realized NET points / event-time ATR >= 10% | Implemented as Production Value hard gate | **Aligned** |
| Event-time ATR coverage | 100% required for D/V/H BASE ledgers; no gate-time recomputation/fallback | **Aligned** |
| Cross-month profit concentration | Implemented over pooled D/V/H BASE immutable ledgers; explicit policy required | **Aligned** |
| Single-year positive-profit dependency | Implemented over pooled D/V/H BASE immutable ledgers; explicit policy required | **Aligned** |
| Production Value Audit | Append-only + content-hash verified + keyed to Production Gate | **Aligned** |
| Production Deployment value guard | Enforced in API **and** `create_deployment_from_gate()` core | **Aligned** |
| Production Deployment identity / sticky health suspension | Implemented | **Aligned** |
| Real MTX Discovery / Validation / Holdout evidence | Not present in active runtime; current E2E evidence is synthetic | **Major remaining goal** |
| MR/BO production edge claim | Not proven | **Correctly blocked** |

## P0 course correction completed

The target review identified that UI / synthetic QA was becoming too prominent relative to the real objective. P0 was therefore limited to execution-truth blockers rather than further general UI polish.

P0 is now closed:

- Candidate Freeze refreshes backend state before exposing success and synchronizes Evaluation / Gate selectors.
- Feature QA no longer treats queue submission as success.
- Backtest, Optimization and Candidate Evaluation jobs must all finish `SUCCEEDED`.
- Candidate Evaluation must produce an `evaluation_id` with the expected role.
- A `SUCCEEDED` job carrying stale `error_text` is rejected by QA.
- Multiprocessing spawned workers cannot incorrectly run API restart orphan recovery.
- Only the main API process marks unfinished jobs `ORPHANED` after a true restart.

Synthetic Candidate Evaluation remaining `INSUFFICIENT` is expected and correct; small synthetic sample size must never be promoted to a PASS edge claim.

## P1 Production Value Gates completed

P1 implements the three trading-value gaps identified during the target review.

### 1. ATR-relative realized trade value

Production Value Audit reconstructs value evidence from immutable stores:

`candidate_evaluations → BASE backtest_trades → frozen research events`

ATR is read only from the frozen event snapshot. Supported provenance locations are event payload / event feature fields already present at event time. The Gate does **not** rebuild ATR from later prices and does not substitute stop distance, MFE or any other proxy when ATR is absent.

For every role (`DISCOVERY`, `VALIDATION`, `FINAL_HOLDOUT`):

- ATR coverage must be 100% for BASE trades.
- `avg_net_points_over_atr = mean(realized NET points / event-time ATR)`.
- default floor = **0.10**.
- winner-only ATR ratio is retained as diagnostic context but is not the Production pass criterion.

Because `net_points` already includes configured execution costs, the value gate is based on realized **NET** economics rather than gross favorable movement.

### 2. Month concentration

Month concentration is not evaluated independently inside each role. The Gate pools immutable D/V/H BASE trade ledgers, groups by actual trade month, and calculates:

`largest positive month net-R / total positive month net-R`

The maximum acceptable share has no guessed default. A valid explicit `0 < share <= 1` Production policy is mandatory.

### 3. Year dependency

Year dependency is also calculated only after pooling D/V/H BASE ledgers. The actual trade `year` is used; research role is never treated as a surrogate year.

Metric:

`largest positive year net-R / total positive year net-R`

Again, the maximum acceptable share must be explicitly frozen in policy. This avoids the invalid result where a one-year Discovery or Holdout run would be labeled “100% year-concentrated” simply because its role contains one year by design.

## Production Value Audit integrity

Each Production Gate receives an append-only companion `production_value_audits` record containing:

- candidate ID;
- policy and policy hash;
- D/V/H role ATR/value summaries;
- month concentration detail;
- year concentration detail;
- check list and failures;
- methodology;
- content hash.

Update/delete is blocked by database triggers. Deployment verifies that this record exists, is hash-valid and is passing.

A legacy or bypass-created Gate with `status='PASS'` but no passing Production Value Audit cannot create a deployment. This restriction is enforced both in the public deployment API and the lower-level `create_deployment_from_gate()` function, so a Python direct call cannot bypass it.

Synthetic deployment QA is still allowed only by creating an explicitly labeled `SYNTHETIC_UI_FIXTURE_ONLY` value-audit record. It remains non-market evidence.

## Code-head verification before documentation closeout

Audited P1 code head:

`8db68258eaa386f7f832ca02c67b17d79014764a`

GitHub Actions at that code head:

- V5 Research CI run `34186312737`: **PASS**
- Browser Release QA run `34186312604`: **PASS**
- Strategy Lab Feature QA run `34186312628`: **PASS**
- Strategy Lab CI run `34186312637`: **PASS**
- Strategy Lab tests, including Production Value / deployment regressions: **PASS**
- P0 regression: **PASS**
- Synthetic MTX Parquet E2E + runtime screenshots: **PASS**
- Reproducibility manifest: **PASS**

## Remaining decisive work: P2 real MTX evidence

The software path is now aligned with the stated production-value criteria, but the market question is still unanswered.

When real source files are available, the next phase is:

1. verify Parquet schema, source coverage, contract/expiry coverage, physical row order and exact SHA-256;
2. register/freeze campaign datasets;
3. freeze real Discovery (target governance mapping: 2025 only if the exact 2025 file is actually available and valid);
4. run scanner / event / entry-price sanity before trusting performance statistics;
5. optimize permitted parameters on Discovery only;
6. freeze candidate and policy;
7. run Validation (target mapping: 2024 only if valid file exists), with no retuning;
8. run Final Holdout (target mapping: 2026 only if valid file exists), with no retuning;
9. apply execution, cost, latency and portfolio stress;
10. evaluate MR ~1R / BO ~2R, ATR >=10%, and the explicitly frozen month/year concentration policy;
11. only then proceed to historical↔live parity and paper evidence;
12. only a fully passing immutable evidence chain may create a Production Gate / deployment.

No real Parquet file currently available in the active runtime may be silently replaced with synthetic data.

## Current verdict

**Architecture / research-governance alignment: PASS.**  
**P0 execution-truth blockers: CLOSED.**  
**P1 Production Value acceptance layer: IMPLEMENTED AND CODE-HEAD CI GREEN.**  
**Real MTX edge: NOT PROVEN.**

The next meaningful progress is real-data P2, not additional general UI expansion. Synthetic PASS remains software evidence only and must never become a market-edge claim.