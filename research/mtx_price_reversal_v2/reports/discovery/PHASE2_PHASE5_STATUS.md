# Phase 2–5 Implementation Status

## Completed engineering
- Trigger and Fill are separate causal objects.
- Same-second event priority is resolved by physical `_seq`.
- Next-print and delayed-print adverse execution models exist.
- Structural and catastrophic risk are independent and auditable.
- Right-tail retention, RiskEfficiency and stop-cause reporting primitives exist.
- 15/30/60s PathState features enforce causal horizon boundaries.
- Counterfactual management accounting separates Saved Loss from Lost Tail.
- Production scaffold includes frozen contract schedule selection, persistent restart state, duplicate-signal prevention, broker reconciliation, feed integrity, strategy risk guard, lifecycle/drift and manifest/environment hashes.

## Validation before upload
- Local unit tests: **28/28 PASS**.
- Historical golden regression: **PASS** (3,655 trades / Net@2 +5,104 / E 1.3964432284541723 / PF 1.059 rounded / MaxDD -3,086).

## Baseline right-tail benchmark
See `RIGHT_TAIL_BASELINE.json`. Both entry-calendar-day and session-key-day concentration are stored explicitly because night-session boundaries can otherwise produce inconsistent best-day reports.

## Discovery-only path observations
`PATH_STATE_DISCOVERY.csv` measures future incremental PnL conditional on simple 30s/60s states. It is diagnostic only and MUST NOT be copied directly into a production rule without a frozen pre-OOS selection step.

`PATH_COUNTERFACTUAL_CONTROL.csv` shows that naively exiting every trade at 30s or 60s is worse than continuing to the frozen 300s baseline: about -1.60 and -2.46 points/trade of management value respectively.

## Remaining blocker before Candidate Freeze
Structural/catastrophic stop candidates must be replayed against **raw physical ticks**, not 1-second OHLC. The current ChatGPT runtime used for this implementation did not have `pyarrow`, so a 2024–2026 physical-stop grid was deliberately not fabricated from second bars. The V2 engine and `requirements.lock` are prepared for running this Risk Lab in the project environment with raw Parquet.

Until that physical Risk Lab and right-tail survival comparison are completed, `production_candidate_v1.yaml` remains NOT_FROZEN and forward OOS remains locked.
