# Strategy Lab / Fabio Research — Goal Alignment Review

Date: 2026-09-08  
Repository: `cheneddie/klinechats_VT`  
Working branch: `research-integrity-p0`  
Integration base: `fabio-decision-gym-v4`  
`main` remains intentionally untouched.

## Final goal

The final goal is not UI completion, synthetic profitability or a green engineering demo. The goal is to determine, from **real MTX data and immutable causal evidence**, whether Fabio-style Mean Reversion (MR) and Breakout Retest (BO) strategies have enough durable, executable edge to move toward production.

Governed sequence:

`Raw / Contract Integrity → Real MTX Intake → Frozen Discovery → Event Sanity → Optimization / Robust Plateau → Candidate Freeze → Validation → Final Holdout → Cost / Latency / Portfolio Stress → Production Value Audit → Historical↔Live Causal Parity → Paper Trading → Production Gate → Production Deployment → Live Health`

Final Holdout must never be used for tuning.

## Acceptance criteria

The research decision requires more than `PF > 1`:

- OOS expectancy remains positive after costs.
- Profit Factor remains acceptable.
- Drawdown remains acceptable.
- Cost / latency / portfolio stress remains viable.
- MR can support approximately **1R** production reward structure.
- BO can support approximately **2R** production reward structure.
- Average realized NET trade points should be at least **10% of contemporaneous event-time ATR**.
- ATR must come from the frozen causal event, not be recomputed at the Gate.
- Profit must not be excessively concentrated in one small month cluster.
- Profit must not depend on one year carrying nearly all positive contribution.
- Historical and live causal state transitions / decision sequence / entry must agree before promotion.
- Paper/live execution evidence must tie to the exact immutable deployment identity.
- A real campaign must prove its source files through `REAL_MTX_INTAKE_V1` before it can freeze.

Month/year concentration limits remain intentionally unset until explicitly frozen by research policy; they are not silently invented by software.

## Current alignment matrix

| Layer | Current status | Alignment |
|---|---|---|
| Raw physical `_seq` / causal truth | Implemented + regression-tested | **Aligned** |
| Four-state node truth / immutable research runs | Implemented | **Aligned** |
| Campaign dataset SHA-256 provenance | Implemented | **Aligned** |
| Real MTX Intake V1 | Implemented + dedicated CI | **Aligned** |
| Synthetic source rejection from Real campaign | Implemented / fail-closed | **Aligned** |
| Real campaign freeze requires intake evidence | Implemented | **Aligned** |
| Frozen campaign dataset DB immutability | Implemented | **Aligned** |
| Real D/V/H provenance / mixed legacy rejection | Implemented | **Aligned** |
| Formal Backtest / Trade Ledger / digest | Implemented | **Aligned** |
| Execution cost / slippage / latency | Implemented | **Aligned** |
| Portfolio overlap arbitration | Implemented | **Aligned** |
| EV / PF / DD / MFE / MAE / right-tail report | Implemented | **Aligned** |
| Robust plateau / FDR / Final Holdout tuning denial | Implemented | **Aligned** |
| Discovery → Validation → Final Holdout order | Implemented | **Aligned** |
| BASE / SLIPPAGE / LATENCY / COMBINED stress | Implemented | **Aligned** |
| MR ≈1R / BO ≈2R production reward floor | Implemented | **Aligned** |
| Average NET points / event-time ATR ≥10% | Implemented | **Aligned** |
| Month concentration gate | Implemented; threshold explicit | **Aligned** |
| Year profit-dependency gate | Implemented; threshold explicit | **Aligned** |
| Historical↔Live parity evidence | Implemented | **Aligned; real evidence absent** |
| Paper evidence / Production Gate | Implemented | **Aligned; real evidence absent** |
| Production Deployment identity / sticky health | Implemented | **Aligned** |
| Real MTX Discovery / Validation / Holdout evidence | Raw files unavailable in current runtime | **Major remaining objective** |
| MR/BO production edge claim | Not proven | **Correctly blocked** |

## P0 status — CLOSED

Execution truth blockers have been closed. Browser Feature QA requires terminal `SUCCEEDED` jobs and real result identities rather than accepting a queued click as success. Candidate Evaluation, job lifecycle, worker orphan handling and browser acceptance remain regression-tested.

## P1 status — CLOSED

Production Value Gates are formalized:

- event-time ATR only from frozen event snapshot;
- 100% ATR coverage per D/V/H role;
- default `avg NET points / ATR >= 0.10`;
- D/V/H BASE ledgers pooled for month/year concentration;
- month/year limits must be explicitly frozen;
- append-only hash-verified Production Value Audit;
- direct deployment cannot bypass the audit.

## P2 source-intake status — READY

P2 source-intake/governance plumbing is now implemented.

### Streaming physical-source audit

`server/v5/data_intake.py` + `tools/real_mtx_intake.py` verify:

- physical SHA-256;
- Parquet readability, row count, row groups and schema;
- required production columns;
- complete datetime parsing;
- physical timestamp ordering without sorting;
- MTX outright presence;
- finite positive price / nonnegative volume;
- day-session outright presence;
- expected-year presence;
- product / expiry / side distributions;
- same-second physical density;
- day-session dominant/front contract table and roll diagnostics.

Synthetic-like filenames are rejected by default. `--allow-synthetic` exists only for QA.

### Timestamp resolution bug closed

CI exposed that Pandas/PyArrow may preserve Parquet timestamp resolution (`ms`, `us`, `ns`) in integer datetime access. The final implementation normalizes with:

`DatetimeIndex(...).as_unit("ns").asi8`

Regression writes equivalent `timestamp(ms)`, `timestamp(us)` and `timestamp(ns)` fixtures and requires identical source-order statistics.

### Real campaign governance

A Real campaign declares:

- `source_class = REAL_MTX`
- `dataset_evidence_policy = REAL_MTX_INTAKE_V1`

It cannot freeze unless every dataset retains a valid passing intake report whose SHA/file/year/report-hash matches the campaign record.

A manually inserted SHA-only dataset therefore cannot masquerade as Real MTX evidence.

For Candidate provenance, if any D/V/H role declares Real MTX, all roles must be Real MTX governed. Real/legacy mixing fails with `MIXED_REAL_AND_LEGACY_CAMPAIGN`.

The public Production Gate freezes this as `REAL_MTX_INTAKE_PROVENANCE` inside the append-only Production Value Audit.

## Current blocker is data, not architecture

There is no real `MTX_2024.parquet`, `MTX_2025.parquet` or `MTX_2026.parquet` in the active runtime of this conversation. Only synthetic Parquet fixtures are currently available.

Old textual records of previous real-data runs are not substitutes for the physical source files. They cannot establish a new SHA-256, schema, row ordering or immutable campaign in this runtime.

Therefore no new real-market result is claimed.

## Next real-data execution

When the exact physical files become available:

1. run Real MTX Intake on each source;
2. inspect SHA/schema/coverage/contracts/physical ordering;
3. create/freeze a `REAL_MTX_INTAKE_V1` campaign;
4. run causal scanner and Event Sanity;
5. freeze Discovery;
6. run formal MR/BO Discovery backtests;
7. optimize Discovery only;
8. freeze Candidate and concentration limits;
9. run Validation without retuning;
10. run Final Holdout without retuning;
11. apply cost / latency / portfolio stress;
12. evaluate MR/BO reward, ATR 10% and month/year concentration;
13. run real parity and paper evidence;
14. only then Production Gate / Deployment.

Intended legacy Fabio role mapping remains:

`2025 Discovery → 2024 Validation → 2026 Final Holdout`

but it will be used only when those exact physical source files are actually present and pass intake.

## Verified code head before this documentation update

`5a748ae525069e6fc5468ea5ff792c004009b9db`

At that code head:

- **205 commits ahead** of `fabio-decision-gym-v4`
- **0 commits behind**
- V5 Research CI `34188426699`: PASS
- Browser Release QA `34188426646`: PASS
- Real MTX Intake CI `34188426622`: PASS
- Strategy Lab Feature QA `34188426616`: PASS
- Strategy Lab CI `34188426649`: PASS

## Verdict

**The research/governance machine is now ready to accept real MTX source files without weakening causal or production-value controls.**

What remains is the decisive part: run the complete lifecycle on real physical MTX datasets and accept the possibility that MR, BO, both, or neither will satisfy the production criteria.

Synthetic PASS remains engineering evidence only and must never be promoted into a market-edge claim.
