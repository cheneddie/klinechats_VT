# Strategy Lab / Fabio Research — Goal Alignment Review

Date: 2026-09-08  
Repository: `cheneddie/klinechats_VT`  
Working branch: `research-integrity-p0`  
Integration base: `fabio-decision-gym-v4`  
`main` remains intentionally untouched.

## Final goal

The final goal is **not** to merely complete a Strategy Lab UI or obtain green synthetic CI. The goal is to build a research system that can determine, using real MTX data and immutable causal evidence, whether Fabio-style Mean Reversion (MR) and Breakout Retest (BO) strategies have sufficient edge to move toward production.

The governed production research sequence remains:

`Raw / Contract Integrity → Frozen Discovery → Event Sanity → Optimization / Robust Plateau → Candidate Freeze → Validation → Final Holdout → Cost / Latency Stress → Historical↔Live Causal Parity → Paper Trading → Production Gate → Production Deployment → Live Deployment Health`

Final Holdout must never be used for tuning.

## User trading-value acceptance criteria

The production research decision must eventually enforce more than `PF > 1`.

At minimum:

- OOS expectancy remains positive after costs.
- Profit Factor remains acceptable.
- Drawdown remains acceptable.
- Cost and latency stress remain positive.
- MR reward structure can support approximately **1R**.
- BO reward structure can support approximately **2R**.
- Average realized trade points should be economically meaningful relative to market movement, with a target around **10% of contemporaneous ATR**.
- Results must not be concentrated in one small month cluster.
- Results must not depend on a single year carrying nearly all profitability.
- Historical and live causal state transitions / decision sequence / entry must agree before live promotion.
- Paper/live execution evidence must be tied to the exact immutable deployment identity.

Concrete thresholds beyond the already stated MR/BO reward floors should be frozen only after real Discovery evidence is available; they must not be tuned on Final Holdout.

## Current alignment matrix

| Layer | Current status | Alignment with final goal |
|---|---|---|
| Raw physical `_seq` / causal truth | Implemented and regression-tested | **Aligned** |
| Four-state node truth / immutable research runs | Implemented | **Aligned** |
| Campaign dataset SHA-256 provenance | Implemented | **Aligned** |
| Formal Backtest / Trade Ledger / digest | Implemented | **Aligned** |
| Execution cost / slippage / latency | Implemented | **Aligned** |
| Portfolio execution policy / overlap arbitration | Implemented | **Aligned** |
| Report EV / PF / DD / MFE / MAE / right-tail | Implemented | **Aligned** |
| Robust plateau optimizer / FDR / Final Holdout tuning denial | Implemented | **Aligned** |
| Discovery → Validation → Final Holdout order | Implemented | **Aligned** |
| BASE / SLIPPAGE / LATENCY / COMBINED stress | Implemented | **Aligned** |
| Historical↔Live parity evidence | Implemented as governed evidence path | **Aligned, real evidence not yet supplied** |
| Paper evidence / Production Gate | Implemented | **Aligned, real evidence not yet supplied** |
| Production Deployment identity / sticky health suspension | Implemented | **Aligned** |
| MR ≥ ~1R production reward floor | Implemented in Production Gate | **Aligned** |
| BO ≥ ~2R production reward floor | Implemented in Production Gate | **Aligned** |
| Average realized points ≥ ~10% ATR | **Not yet implemented as a formal report/gate check** | **Gap** |
| Cross-month concentration / diversification gate | Breakdown exists, but no formal concentration check | **Gap** |
| Single-year profit dependency gate | Year breakdown exists, but no formal dependency check | **Gap** |
| Real MTX Discovery / Validation / Holdout evidence | Not present in current runtime; current E2E evidence is synthetic | **Major remaining goal** |
| MR/BO production edge claim | Not proven | **Correctly blocked** |

## Important course correction

The architecture and synthetic E2E work are necessary, but they are **means**, not the objective.

Recent browser QA has been valuable because it caught real integration defects, including immutable identity mismatches and route races. However, after the current Candidate Evaluation execution blocker is closed, priority must shift away from adding general UI polish and toward the real MTX validation chain.

UI improvements should only receive priority when they block auditability, reproducibility, or actual research execution.

## Immediate blockers before real-data research

1. Candidate Evaluation background job must truly finish `SUCCEEDED`; queue submission alone is insufficient.
2. Feature QA must fail if Candidate Evaluation job status is anything other than `SUCCEEDED` or if no `evaluation_id` is produced.
3. ExecutionModel identity must remain stable across JS/Python numeric serialization (`0`, `0.0`, numeric strings).
4. The three missing production-value checks must be designed and tested:
   - ATR-relative realized points,
   - month concentration,
   - year dependency.
5. Actual MTX Parquet files must be available and registered with exact SHA-256 before any real-edge conclusion.

## Priority reset

### P0 — close execution truth blockers

- Make Candidate Evaluation complete successfully under Chrome feature QA.
- Strengthen Feature QA so terminal job failure cannot be hidden behind a successful UI submission.
- Keep all four core CI workflows green.

### P1 — complete production-value acceptance criteria

- Add ATR-relative trade value metrics using causal/event-time ATR only.
- Add month concentration metrics/checks.
- Add year profit dependency metrics/checks.
- Add regression tests and expose the checks in candidate/gate evidence.

### P2 — real MTX evidence

When real files are available:

1. verify source coverage and SHA-256;
2. verify contract policy / physical row order;
3. freeze 2025 Discovery;
4. run Event Sanity before trusting statistics;
5. optimize only Discovery execution parameters / permitted research search spaces;
6. freeze candidate;
7. run 2024 Validation without retuning;
8. run 2026 Final Holdout without retuning;
9. apply cost / latency / portfolio stress;
10. evaluate the MR ~1R / BO ~2R / ATR-value / concentration criteria;
11. only then proceed to parity, paper and Production Gate.

## Current verdict

**The current implementation is directionally consistent with the final goal, but the project is not at the final goal yet.**

The research/governance machine is substantially built. The remaining decisive work is to:

- close the Candidate Evaluation runtime blocker,
- formalize the missing trading-value gates,
- and run the complete lifecycle on real MTX datasets.

Synthetic PASS must never be promoted into a real market-edge claim.
