# Fabio Decision Gym V5 Implementation Status

## Engineering scope

V5 Research → Training Layer is implemented on top of V4 without merging `main`.

Implemented: Node Registry, immutable research runs, dual SQLite lifecycle, raw integrity audit, sanity gate, physical outcomes, strict-vs-terminal entry separation, reverse audit with opportunity cost, sequential contribution, ablation, Evidence Registry, Training Truth Set, Hard Negatives, Matched Pairs, persistent attempts/mastery/mistakes/spaced repetition, certification isolation, human review/dispute state, V5 API, V5 causal replay endpoints, Historical↔Live parity harness, 8-page frontend, KLineChart/Pixi causal replay reuse, and V5 CI/watchdog.

## Strategy Lab V1

The V5 layer now also contains a governed Strategy Research Workbench covering:

- Strategy Library / immutable strategy versions
- Backtest Studio
- physical execution simulator
- immutable Trade Ledger
- KLineChart/Pixi Trade Review
- full expectancy / PF / DD / MFE / MAE / right-tail reports
- robust parameter plateau optimization
- candidate freeze
- enforced Discovery → Validation → Final Holdout evaluation
- execution-cost / slippage / latency stress
- append-only Production Gate decisions
- durable long-job heartbeat / timeout / cancellation / orphan recovery
- stored production evidence for Historical↔Live parity and paper trading
- reproducibility manifest and public-build research-data exclusion

Full closeout and current verification status:

`reports/STRATEGY_LAB_V1_IMPLEMENTATION_STATUS_2026-09-07.md`

## Automated verification

Current Strategy Lab closeout head is derived from audited head `f240f20b78f64acff541b29678a97622b1aed93c`, where GitHub Actions reported:

- `research`: PASS
- `strategy-lab`: PASS

Strategy Lab CI includes module compilation, JS syntax checks, Strategy Lab tests, candidate/production provenance tests, long-job/watchdog tests, V5 research-integrity regressions, V5 layer regression, static build checks, research/config/report leakage checks, and reproducibility-manifest generation.

Browser integration QA also passed on the Strategy Lab/browser integration lineage.

## Evidence boundary

Software completion is not market-edge validation. Synthetic/integration tests validate implementation only.

Production strategy approval remains blocked until real data passes the governed sequence:

`Raw/Contract Integrity → Frozen Discovery → Candidate Freeze → Validation → Final Holdout → Cost/Latency Stress → Historical↔Live parity → Paper Trading → Production Gate`

The legacy Fabio campaign retains the repository governance mapping `2025 Discovery → 2024 Validation → 2026 Final Holdout`. New strategies should use campaign-specific dataset SHA-256 pins. Final Holdout data must never be used for parameter tuning.

## Merge boundary

`research-integrity-p0` remains research-only and targets `fabio-decision-gym-v4` for Draft PR review. No implementation closeout in this branch authorizes merging to `main`.
