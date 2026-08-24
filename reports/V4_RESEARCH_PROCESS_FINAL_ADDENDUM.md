# Fabio Decision Gym V4 — Research Process Final Addendum

Date: 2026-08-21  
Branch: `fabio-decision-gym-v4`  
Status: research branch only — **do not merge to `main` without explicit approval**

## 1. Evidence boundary

This branch separates three evidence classes:

1. **Synthetic QA** — software/causality validation only.
2. **Single-Year Diagnostic** — real-data diagnostic evidence, not final OOS validation.
3. **Multi-Year Frozen OOS** — required before a production edge claim.

No synthetic result may be presented as strategy profitability.

## 2. Immutable market-data rules

- Raw Parquet physical row order is the source ordering and must never be re-sorted.
- `_seq` is assigned before product/contract/session filtering.
- Same-second trades retain original physical ordering; timestamp is not a tie-breaker.
- Outright expiries must not be mixed when constructing Value/Profile/LVN features.
- `side` is a tick-direction proxy unless true aggressor/Bid/Ask data exists.
- Hide-future replay cuts raw physical ticks before timeframe aggregation.

## 3. Research universe

Strict strategy gates are audited inside the relaxed terminal-opportunity universe. This avoids circular selection: a gate cannot be evaluated only on cases that already passed that gate.

The research terminal entry is an outcome-comparison anchor. It is not automatically a live/strict strategy entry.

For BO specifically:

- terminal research entry: Pullback opportunity anchor;
- strict strategy entry: at/after directional Response confirmation.

## 4. Every FALSE node is causally located

Every negative node label must persist:

- `decision_seq`
- `decision_time`
- `decision_price`
- `reason_code`

The question is not merely “why did it fail?” but “what was the earliest physical market row at which the failure became knowable?”

## 5. Node interpretation

Nodes are not all expected to be standalone profitable filters.

- **State Node** — describes causal market state.
- **Edge Gate** — should separate later outcomes.
- **Execution Gate** — should improve MAE, risk efficiency, fill/execution quality, or realized R.

Final production classification vocabulary:

- `CORE`
- `OPTIONAL`
- `REDUNDANT`
- `HARMFUL`
- `INSUFFICIENT`
- `REGIME_DEPENDENT`

High same-decision-seq rate alone is not enough to mark a node redundant. Redundancy should also consider incremental EV, right-tail retention, loser rejection and ablation/sequential contribution.

## 6. Formal Event Sanity Gate

Statistical audit is downstream of Event Sanity, never the other way around.

Automatic checks include:

- strict entry requires strict-chain pass;
- stop is on the valid side of entry;
- BO strict entry requires Response and uses Response decision row;
- terminal research entry never occurs after strict entry;
- node reason codes exist;
- every FALSE node has causal decision location;
- anchor never occurs after decision;
- optional physical verification maps persisted decision/entry prices back to exact Parquet `_seq` rows.

Manual Replay requirement after automatic PASS:

- 20 MR YES
- 20 MR NO
- 20 BO YES
- 20 BO NO
- 20 WAIT / near-miss

A failed Event Sanity Gate blocks interpretation of Reverse Audit, Ablation and Management results.

## 7. Funnel sanity

Research must report the complete opportunity funnel, not only final trades:

Trading days → Auction attempts → MR candidates → BO candidates → WAIT/near-miss → relaxed terminal opportunities → strict entries.

This separates detector recall from strategy selectivity. Low strict-entry count is not automatically a detector bug, but an implausibly narrow upstream funnel is a scanner QA signal.

## 8. Reverse Node Edge Audit

Each gate should report at least:

- Universe / Pass / Fail N
- 1R / 2R / 3R rates
- Avg MFE / MAE
- control-management Avg R / Total R
- bootstrap uncertainty
- big-winner retention
- big-loser rejection
- same-seq parent rate
- cross-period consistency

### Opportunity cost

Rejected cases must also report signed R:

- `rejected_total_r`
- `rejected_positive_tail_r`
- `rejected_negative_tail_r`

A gate that rejects more losing trades by count may still be harmful if it removes a larger profitable right tail.

## 9. Sequential contribution and ablation

Single-node metrics are insufficient because gates interact.

Two complementary tests are required:

1. **Ablation** — FULL chain vs FULL minus one gate.
2. **Sequential contribution** — add gates in actual causal order and measure incremental ΔN, ΔAvgR and ΔTotalR.

The final production tree is a research result; it does not have to preserve all original conceptual nodes.

## 10. Trade Management extraction

Entry edge and profit extraction are separate hypotheses.

Management research must examine right-tail retention and favorable capture, not only PF/win rate.

`Favorable Capture Ratio = max(realized_R, 0) / MFE_R`, when `MFE_R > 0`.

Trailing parameters should be evaluated as a plateau, not by selecting a single best value from many trials.

Intraday-only, full-session and overnight management should be reported separately when the holding horizon crosses session boundaries.

## 11. Production value targets

These are research acceptance targets, not claims that current V4 has already met them:

- MR should have practical reward capacity around **1R**.
- BO should have practical reward capacity around **2R**.
- Average realized profit points should ideally be at least about **10% of representative ATR**.
- Cost and latency adjusted expectancy should remain positive.
- Performance should not be supported by one month/year only.
- Uncertainty interval and drawdown must remain acceptable.

Historical → live promotion additionally requires identical causal state transitions on identical tick sequences (Historical/Live Causal Parity).

## 12. Versioning / provenance

Research results are now associated with:

- scanner version
- MR/BO strategy versions
- strategy config hash
- visual schema version
- contract-policy version
- audit version
- outcome version
- management version
- git commit
- unique research `run_id`

SQLite uses explicit schema versioning and `schema_meta`.

The derived Event Store remains rebuildable from raw Parquet. Human `training_attempts` are not rebuildable from market data and therefore need separate backup discipline.

## 13. QA observability

Final QA now includes a network watchdog that persists `network-errors.json` with:

- request method
- URL
- HTTP status/status text
- request failure reason
- timestamp

The correct response to a hidden 404/fallback pattern is to fix the product flow, not whitelist the error.

## 14. Gated diagnostic runner

`tools/run_v4_diagnostic.py` is the canonical research runner.

Order:

1. Observable V4.1 scanner
2. Persist `scan_summary.json`
3. **Physical Event Sanity Gate**
4. Physical-tick outcomes
5. Reverse Audit + opportunity cost
6. Sequential Gate Contribution
7. Ablation
8. Trade Management Capture
9. Versioned final summary

Outputs:

- `provenance.json`
- `progress.json`
- `scan_summary.json`
- `event_sanity.json`
- `reverse_audit.json`
- `reverse_audit.csv`
- `sequential_gate_contribution.json`
- `ablation.json`
- `management_capture.json`
- `final_summary.json`

The runner refuses to continue into statistical interpretation when the automatic Event Sanity Gate fails.

## 15. Current real-data status

The previously documented 2025 Contract QA evidence remains:

- raw rows: 39,416,621
- day-session trading days: 236
- days with >1 outright month in day session: 0
- strict calendar-front match: 236 / 236
- mismatches: 0
- roll switches: 12

This supports the strict calendar-front policy on the 2025 sample only; it does not establish the same result for other years.

At the time of this update, the current execution runtime does **not** contain `MTX_2025.parquet`, and local Python does not have `pyarrow`. Therefore the 39M-row 2025 Reverse Edge Audit has not been fabricated or replaced with synthetic data. The branch now contains the gated runner and research governance needed to execute it as soon as the real Parquet is available in an appropriate runtime.

## 16. Promotion rule

Do not call a node/strategy production-ready from a single-year result. A production candidate still requires multi-year frozen validation, cost/latency robustness, and live-parity/paper-trading evidence.
