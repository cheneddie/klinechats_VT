# POC Absorption Reversal Research Plan v1

> Branch: `research/poc-absorption-reversal-v1`
>
> Goal: turn the visual note **「上升寬通道 → POC 失速/下移 → 高點買壓無法推價 → 震盪/反轉」** into a causal, reproducible, multi-year quantitative research pipeline that can be independently implemented and audited by other engineers.
>
> This is a research branch. **Do not merge to `main` until the signal survives multi-year validation, cost/latency stress, and event-level visual QA.**

---

## 0. Research question

We are not trying to prove that the visual pattern is correct. We are testing four nested hypotheses:

1. **Trend context exists**: price is in a broad rising channel / positive auction regime.
2. **POC migration weakens**: bar-level value no longer migrates upward with price, and may migrate below the prior bar POC.
3. **Buying-pressure efficiency collapses near highs**: large positive tick-direction pressure occurs near the high, but produces little upward price response.
4. **The combination predicts a state transition**: first high-level balance/chop, then possibly downside structural break / reversal.

The final production signal is allowed to be weaker, simpler, or materially different from the original visual note if the data show that some components are redundant or harmful.

---

# 1. Data inventory and hard constraints

## 1.1 Uploaded research files

The current three uploaded yearly Parquet files are:

| File | Physical rows | Approx size | Schema |
|---|---:|---:|---|
| `MTX_2024(5).parquet` | 50,862,751 | 166 MB | datetime, product, expiry, price, volume, side |
| `MTX_2025(6).parquet` | 39,416,621 | 140 MB | datetime, product, expiry, price, volume, side |
| `MTX_2026(5).parquet` | 36,158,882 | 132 MB | datetime, product, expiry, price, volume, side |
| **Total** | **126,438,254** | ~438 MB | same logical schema |

The Parquet metadata indicates second-level `datetime`. 2024/2025 store `volume` as float64; 2026 stores `volume` as int64. Normalize to numeric but do not change row order.

## 1.2 Non-negotiable data rules

These rules inherit the repository's existing MTX data-integrity contract and are mandatory:

1. Assign physical `_seq = 0..N-1` immediately after reading each Parquet file.
2. **Never re-sort ticks** by datetime, price, side, or any other field.
3. Same-second tick ordering is the source-provided physical order.
4. Filtering must preserve original `_seq`.
5. Use `product == MTX` and legal outright expiry only; exclude spreads/combos before any profile/state calculation.
6. Different expiries must never be mixed into the same profile.
7. `side` is treated only as **tick-direction proxy**, not true aggressor side, Bid/Ask delta, CVD, or footprint aggression.
8. All signal decisions must have an exact `decision_seq`, `decision_time`, `decision_price`, and causal feature snapshot.
9. Any bar/profile used at decision time must be formed only from ticks available up to that decision point.

## 1.3 Contract policy

Production research default: `strict` calendar front-month causal policy from the existing Contract Engine.

Required output per trading day:

```text
trading_date
candidate_contracts
selected_contract
selection_reason
roll_state
roll_blackout
rows_kept
rows_removed
```

Run `dominant_volume` only as a non-causal diagnostic comparison.

---

# 2. Naming and evidence boundary

Because `side` is not true aggressor classification, do **not** call the proposed feature “buy absorption” in production code yet.

Use these names:

- `TDP` = Tick Direction Pressure
- `PE` = Price Efficiency
- `HBP` = High-zone Buying Pressure proxy
- `HBE` = High-zone Buying Efficiency
- `HBA_PROXY` = High-zone Buying Absorption **Proxy**

Only richer Bid/Ask or MBO/TBBO data could justify naming it true order-flow absorption.

---

# 3. Overall architecture

```text
Raw yearly MTX Parquet
        ↓
Physical sequence / integrity QA
        ↓
Contract + session engine
        ↓
Causal bar builder (1s → 15s/30s/1m/3m/5m/15m)
        ↓
Causal per-bar Volume Profile
        ↓
Trend / broad-channel detector
        ↓
POC migration features
        ↓
High-zone pressure / efficiency features
        ↓
Candidate event detector
        ↓
Future outcome engine (physical tick sequence)
        ↓
Feature audit + ablation + threshold plateaus
        ↓
Walk-forward / OOS validation
        ↓
Cost + latency + execution stress
        ↓
Production candidate / reject
```

Detector and strategy must remain separate. The detector should save continuous raw features; strategy config applies thresholds later without rescanning raw ticks where possible.

---

# 4. Phase A — Data QA gate

No strategy work is allowed until this phase passes.

## A1. File QA

For each year output:

```text
physical_rows
schema
datetime_min/max
product_counts
expiry_counts
legal_outright_counts
spread_combo_counts
side_counts
price_min/max
volume_min/max
same_second_row_distribution
non_decreasing_datetime_rate
negative_or_zero_volume_count
null_count_by_column
```

Also verify 100 random same-second blocks visually/structurally to ensure physical order is retained after filtering.

## A2. Contract QA

For each trading date:

- all outright candidate contracts
- strict selected contract
- dominant-volume contract (diagnostic only)
- mismatch flag
- roll dates
- blackout dates

Acceptance criterion:

- no mixed-expiry profile ever created;
- every event stores contract id;
- roll transition behavior is explicitly test-covered.

## A3. Session QA

Separate:

- day session
- night session
- full trading day

Initial signal discovery should be run separately by session. Do not pool them until evidence shows pooling is harmless.

Deliverables:

```text
reports/poc_absorption/data_qa_2024.json
reports/poc_absorption/data_qa_2025.json
reports/poc_absorption/data_qa_2026.json
reports/poc_absorption/contract_qa.csv
```

---

# 5. Phase B — Causal bar + Volume Profile engine

The screenshot motivating the idea uses a 15-minute chart, but we should not assume 15m is the best signal horizon.

## B1. Required bar resolutions

Build causally:

```text
15s
30s
1m
3m
5m
15m
```

For each bar persist:

```text
bar_start_seq
bar_end_seq
open/high/low/close
volume
poc
vah
val
profile_width
price_range
atr_n
```

## B2. Per-bar POC

For each bar, calculate volume-at-price on actual traded prices of the active contract.

Store:

```text
bar_poc
poc_volume
poc_share = poc_volume / bar_volume
poc_rank_in_range = (poc-low)/(high-low)
```

Tie-breaking must be deterministic and documented. Suggested default: if multiple prices share max volume, choose the one nearest the bar VWAP; if still tied, choose nearest prior POC. Test alternative tie rules as sensitivity analysis, not as hidden optimization.

## B3. Developing POC

In addition to completed-bar POC, build `developing_poc(t)` within the current bar using only ticks up to each tick/second.

This permits testing whether signal quality improves when POC weakening is known before bar close.

---

# 6. Phase C — Quantify “rising broad channel”

Do not use one subjective trend line. Build multiple causal context features and let the data tell us which carry information.

## C1. Primary trend features

For lookbacks `L ∈ {6, 8, 12, 16, 24}` bars:

```text
ols_slope_close_L
ols_r2_close_L
slope_atr = slope / ATR
higher_high_ratio_L
higher_low_ratio_L
close_location_in_window
rolling_high_distance_atr
rolling_low_distance_atr
```

## C2. Broad-channel features

Quantify “wide channel” with:

```text
channel_width = rolling_high - rolling_low
channel_width_atr = channel_width / ATR
residual_std = std(close - regression_line)
residual_std_atr
swing_amplitude_atr
alternation_rate
```

A broad rising channel should have:

- positive normalized slope;
- adequate directional persistence;
- non-trivial width / residual variance.

But **do not hard-code final thresholds during feature extraction**.

## C3. Context labels for audit

Continuous features are source of truth; convenience labels may include:

```text
UP_TREND_TIGHT
UP_CHANNEL_BROAD
UP_ACCELERATING
UP_EXHAUSTING
BALANCE
DOWN_TREND
```

Labels must be versioned and derived from frozen config.

---

# 7. Phase D — Quantify POC slowdown / bearish divergence

The original visual note says:

> POC starts slowing and becomes lower than the previous candle's POC while price remains high.

Build the following features.

## D1. One-bar migration

```text
poc_delta_1 = poc[t] - poc[t-1]
price_delta_1 = close[t] - close[t-1]
high_delta_1 = high[t] - high[t-1]
```

Core divergence candidate:

```text
high_delta_1 >= 0
AND poc_delta_1 < 0
```

Do not treat this binary rule as the final strategy. It is only one feature.

## D2. Multi-bar POC velocity and acceleration

```text
poc_velocity_k = (poc[t] - poc[t-k]) / k
poc_velocity_atr_k = poc_velocity_k / ATR
poc_accel = velocity_short - velocity_long
```

Test `k = 2,3,4,6`.

## D3. Price-vs-value divergence

```text
price_slope_L
poc_slope_L
divergence_slope = price_slope_L - poc_slope_L
poc_price_corr_L
```

Important patterns:

```text
price_slope > 0 AND poc_slope ≈ 0
price_slope > 0 AND poc_slope < 0
new_price_high = true AND new_poc_high = false
```

## D4. POC stall duration

```text
bars_since_poc_high
poc_nonadvance_count
poc_lower_count_last_n
```

Hypothesis: repeated POC non-advance may be more useful than a single lower POC.

## D5. Normalization

Every price-distance feature must be available as:

```text
points
ATR units
bar range units
profile width units
```

This prevents a 2024/2026 volatility regime shift from breaking fixed-point thresholds.

---

# 8. Phase E — Quantify high-zone buying pressure without pretending it is true aggressor flow

The red circles in the visual note imply “large buying near highs but price does not advance.” With current data, implement only a tick-direction pressure proxy.

## E1. Tick-direction signed volume

Within a causal window:

```text
signed_volume = Σ(volume * side)
positive_volume = Σ(volume where side > 0)
negative_volume = Σ(volume where side < 0)
tdp_ratio = signed_volume / total_volume
positive_share = positive_volume / total_volume
```

Also calculate trade-count versions to reduce domination by a few large prints.

## E2. High-zone definition

For each bar/window define high zone at multiple fractions:

```text
high_zone_q ∈ {0.70, 0.80, 0.90}
threshold = low + q*(high-low)
```

Then:

```text
high_zone_positive_volume
high_zone_negative_volume
high_zone_tdp
high_zone_volume_share
```

Alternative structural high zone:

```text
price >= rolling_high - x*ATR
```

Test both.

## E3. Buying efficiency

The central idea should be expressed as **effort vs result**.

Candidate definitions:

```text
up_extension = max_future_price_within_window - pressure_start_price
buying_efficiency = up_extension / positive_volume
```

Because raw units are unstable, also use percentile/rank normalization:

```text
pressure_z
extension_atr
impact_per_1000_volume
impact_per_trade
```

## E4. Price-impact asymmetry

Measure how much positive pressure is needed to move price up versus how easily price falls afterward:

```text
up_impact = max_up_move / positive_volume
down_impact_after = max_down_move / positive_volume
impact_asymmetry = down_impact_after - up_impact
```

## E5. Absorption-proxy score

Do not start with one optimized formula. Save components first. A research-only composite may later be:

```text
HBA_PROXY_SCORE =
    z(high_zone_positive_volume)
  + z(high_zone_tdp)
  - z(up_extension_atr)
  - z(close_to_high_efficiency)
```

The formula must be derived/frozen only after discovery and then tested OOS.

---

# 9. Phase F — Candidate-event universe

Avoid circular selection. Build a **relaxed opportunity universe** first.

An event should exist when:

1. positive/broad-channel context is present at some minimum permissive threshold;
2. price is in the upper portion of the rolling channel / near a local high;
3. enough completed/causal bar data exist to calculate POC migration and pressure features.

Do **not** require POC divergence or absorption proxy to create the event. Those must remain explanatory variables so PASS/FAIL groups can be compared.

Event de-duplication:

- one structural high-region episode = one event;
- use deterministic episode id;
- prevent every small same-zone bar from becoming a new independent event.

Suggested episode reset conditions:

```text
price leaves high zone by >= X ATR
OR trend context resets
OR N bars/time elapsed
```

Keep X/N as detector config, not optimized outcome labels.

---

# 10. Phase G — Define outcomes before optimizing signals

This idea predicts **two-stage behavior**:

1. high-level balance / chop;
2. possible reversal.

Therefore do not use only a single “short profit” label.

## G1. Forward horizons

For each event decision point evaluate physical tick outcomes over:

```text
30 sec
60 sec
2 min
5 min
15 min
30 min
60 min
session end
```

For 15m-bar variants also test 1/2/4/8 bars, but outcome ordering still comes from physical ticks.

## G2. Balance/chop outcomes

Quantify “震盪” using:

```text
net_return
path_range
path_efficiency = abs(net_move) / total_path_distance
future_realized_vol
high_retest_count
range_cross_count
```

Possible label:

```text
BALANCE_TRANSITION = low path efficiency + elevated two-sided excursion
```

But report continuous metrics first.

## G3. Reversal outcomes

For an upside exhaustion candidate:

```text
MFE_short
MAE_short
future_low_distance
future_high_extension
break_recent_swing_low
break_channel_midline
break_channel_low
poc_followthrough_down
```

## G4. Time-to-event

Store:

```text
time_to_MFE_0.25ATR
time_to_MFE_0.5ATR
time_to_1R
time_to_structure_break
```

This reveals whether the pattern is actionable immediately or only after long balance.

---

# 11. Phase H — Signal sequencing and entry models

We should test at least three entry families.

## H1. Anticipatory entry

Enter short when:

```text
up-channel context
+ POC weakness
+ HBA proxy
```

Purpose: maximum early capture, likely higher false-positive rate.

## H2. Confirmation entry

Wait for one of:

```text
close below prior bar low
break micro swing low
reclaim failure after new high
POC continues lower
```

Purpose: test whether confirmation materially improves risk-adjusted expectancy.

## H3. Pullback-after-break entry

After downside structure break:

```text
first pullback into broken level / local POC / LVN region
```

Purpose: potentially lower adverse excursion and cleaner stop placement.

Each family must have separate event/entry fields. Do not backfill entry time after seeing future data.

---

# 12. Phase I — Risk and trade-value constraints

A statistically significant prediction is not automatically tradable.

For each entry model evaluate:

```text
MFE / MAE
MFE_R / MAE_R
1R / 1.5R / 2R / 3R hit rates
fixed target
trailing target
partial + runner
structure stop
time stop
```

Minimum practical-value questions:

- Is average realizable profit comfortably larger than friction?
- Is average gross move at least a meaningful fraction of current ATR?
- Does the signal survive next-tick and delayed-entry assumptions?
- Is the edge distributed across months and years rather than a tiny set of outliers?

Do not freeze numeric production gates until the empirical distributions are known.

---

# 13. Phase J — Feature audit

Every feature/node is classified as:

```text
CORE
OPTIONAL
REDUNDANT
HARMFUL
INSUFFICIENT
REGIME_DEPENDENT
```

For every candidate feature compare high/low or pass/fail groups on:

```text
N
future downside MFE
future upside MAE
balance metrics
structure-break probability
Avg R
PF
1R/2R/3R hit rates
big-winner retention
big-loser rejection
rejected positive-tail R
rejected negative-tail R
bootstrap 95% CI
month/year consistency
```

## J1. Ablation

Run:

```text
FULL
FULL - trend context
FULL - POC divergence
FULL - high-zone pressure
FULL - efficiency
FULL - confirmation
```

Also sequential contribution:

```text
Context
+ POC
+ Pressure
+ Efficiency
+ Confirmation
```

Report `ΔN`, `ΔEV`, `Δtail`, `Δdrawdown` at each step.

---

# 14. Phase K — Threshold research without overfitting

Do not optimize a giant parameter grid and pick the single maximum Sharpe/PF.

Use:

1. coarse discovery ranges;
2. monotonicity / dose-response plots;
3. parameter plateaus;
4. frozen candidate ranges;
5. OOS validation.

Examples:

```text
poc_delta_atr bins
poc_stall_count bins
high_zone_positive_volume percentile
buying_efficiency percentile
channel_width_atr bins
trend_slope_atr bins
```

Prefer a stable plateau over the top single bin.

---

# 15. Phase L — Three-year validation protocol

The three years must not all be used for optimization.

Recommended first protocol:

## Discovery

`2024`

- build features;
- discover whether the phenomenon exists;
- choose limited candidate definitions/ranges.

## Validation

`2025`

- no major threshold hunting;
- reject features whose effect disappears;
- refine only implementation bugs / clearly predeclared robustness ranges.

## Final OOS

`2026`

- freeze feature definitions and main thresholds before running;
- report untouched OOS performance.

If 2026 is incomplete-year data, explicitly report coverage and run month-matched sensitivity checks.

After first complete pass, add walk-forward analysis:

```text
2024 H1 → 2024 H2
2024 → 2025
2024+2025 → 2026
```

Never repeatedly tune on 2026 after seeing results and still call it OOS.

---

# 16. Phase M — Statistical robustness

Required:

## M1. Cluster bootstrap

Resample by trading day, not individual event, to account for within-day dependence.

Output:

```text
mean effect
95% CI
probability(effect > 0)
```

## M2. Multiple-testing awareness

There will be many resolutions, features, thresholds, and outcomes. Maintain a research registry of all tested variants.

Do not silently discard failed variants.

At minimum apply FDR awareness when ranking large feature families.

## M3. Placebo tests

Examples:

- shifted POC by nearby random prices;
- random high-zone windows within same regime;
- random event timestamps matched by session/time-of-day;
- permuted POC-delta sign within day;
- fake pressure windows with matched volume.

A real signal should beat plausible counterfactuals, not merely zero.

---

# 17. Phase N — Cost, latency, and execution stress

At minimum report:

```text
signal tick
next tick
+2 ticks
+5 ticks
+1 sec
+2 sec
```

Cost scenarios:

```text
0 pt
0.5 pt round-trip equivalent
1 pt
2 pt
higher adverse stress
```

If the signal only works at exact signal-tick fills, it is not production-ready.

Passive-limit fills must be labeled assumptions because the dataset lacks queue position / MBO.

---

# 18. Phase O — Regime map

The final question is not only “does it work?” but “where does it work?”

Slice by:

```text
year
month
day session / night session
time of day
ATR percentile
channel width percentile
trend slope percentile
volume percentile
upper-channel location percentile
POC divergence strength
pressure percentile
efficiency percentile
```

Especially test whether the signal is concentrated in:

- late-stage broad up channels;
- opening impulse exhaustion;
- midday balance;
- high-volatility trend days;
- low-volatility rotational days.

---

# 19. Event Store schema

Suggested table: `poc_absorption_events`

```text
event_id
source_file
year
trading_date
session
contract

context_start_seq
context_end_seq
anchor_seq
anchor_time
anchor_price
decision_seq
decision_time
decision_price

bar_resolution
trend_slope_atr
trend_r2
channel_width_atr
channel_position

bar_poc
prev_poc
poc_delta
poc_delta_atr
poc_slope
price_slope
poc_price_divergence
poc_stall_count

high_zone_q
high_zone_volume
high_zone_positive_volume
high_zone_negative_volume
high_zone_tdp
positive_share
up_extension_atr
buying_efficiency
impact_asymmetry

future_mfe_short
future_mae_short
future_balance_efficiency
future_structure_break
future_structure_break_seq
future_structure_break_time

scanner_version
feature_version
outcome_version
config_hash
git_commit
```

Keep continuous features even if a binary node is later derived.

---

# 20. Binary research nodes for Replay/Training

Once continuous features are validated, expose interpretable nodes:

```text
PAR_CTX_UP_CHANNEL
PAR_CTX_BROAD_CHANNEL
PAR_PRICE_NEAR_HIGH
PAR_POC_NON_ADVANCE
PAR_POC_LOWER
PAR_POC_DIVERGENCE
PAR_HIGH_ZONE_PRESSURE
PAR_LOW_UPSIDE_EFFICIENCY
PAR_ABSORPTION_PROXY
PAR_BALANCE_CONFIRM
PAR_STRUCTURE_BREAK
PAR_PULLBACK_ENTRY
```

`PAR` = POC Absorption Reversal.

Every `NO` must still have a causal decision point and reason code.

Example reason codes:

```text
NO_UP_CHANNEL
CHANNEL_TOO_TIGHT
NOT_NEAR_HIGH
POC_STILL_ADVANCING
PRESSURE_TOO_LOW
PRICE_RESPONSE_EFFICIENT
NO_BALANCE_TRANSITION
NO_STRUCTURE_BREAK
ENTRY_TOO_LATE
```

---

# 21. Visual QA requirements

Before trusting any aggregate statistics, sample at least:

```text
30 strong signal cases
30 weak signal cases
30 false positives
30 large winners
30 large losers
30 near-miss controls
```

For each, Replay must show:

- raw/aggregated candles;
- per-bar POC;
- POC migration line;
- high-zone band;
- positive/negative tick-direction pressure proxy;
- exact anchor/decision point;
- future hidden before reveal.

Reject the scanner immediately if:

- decision price does not exist in physical tick sequence;
- POC uses future ticks from the same incomplete bar;
- contract mismatch occurs;
- duplicate episode count is inflated;
- same-second row order is altered.

---

# 22. Engineering package layout

Recommended new files:

```text
server/poc_absorption/
  __init__.py
  data_qa.py
  bars.py
  profile.py
  context.py
  poc_features.py
  pressure_features.py
  events.py
  outcomes.py
  audit.py
  backtest.py
  report.py

config/poc_absorption/
  feature_v1.json
  detector_v1.json
  outcome_v1.json
  strategy_candidates_v1.json

tests/poc_absorption/
  test_physical_order.py
  test_contract_isolation.py
  test_causal_bar.py
  test_developing_poc.py
  test_poc_features.py
  test_pressure_proxy.py
  test_event_dedup.py
  test_outcome_ordering.py
  test_no_future_leak.py

scripts/
  run_poc_absorption_qa.py
  run_poc_absorption_scan.py
  run_poc_absorption_audit.py

reports/poc_absorption/
  README.md
```

Do not modify the existing Fabio scanner logic unless a shared utility is clearly generic and tests prove backward compatibility.

---

# 23. CLI requirements

Example:

```bash
python scripts/run_poc_absorption_qa.py \
  --data-root "D:/tools/traderChatV1/data/parquet/Future" \
  --years 2024 2025 2026

python scripts/run_poc_absorption_scan.py \
  --years 2024 \
  --contract-policy strict \
  --resolutions 30s 1m 3m 5m 15m \
  --config config/poc_absorption/detector_v1.json

python scripts/run_poc_absorption_audit.py \
  --discovery-year 2024 \
  --validation-year 2025 \
  --oos-year 2026
```

Long jobs must emit heartbeat:

```text
phase
current_year
current_date
done_days
total_days
rows_processed
rows_per_sec
events_found
elapsed
eta
last_progress_at
```

No black-box multi-hour process.

---

# 24. Required reports

For every full run produce:

```text
DATA_QA.md/json
CONTRACT_QA.csv
FEATURE_DISTRIBUTIONS.csv
EVENTS.parquet
EVENT_SANITY.md
DISCOVERY_2024.md
VALIDATION_2025.md
OOS_2026.md
ABLATION.csv
PLACEBO.csv
REGIME_MAP.csv
COST_LATENCY.csv
TRADE_MANAGEMENT.csv
FINAL_PRODUCTION_GATE.md
```

Also output raw event-level CSV/Parquet so every aggregate result can be reproduced.

---

# 25. Production gate

A signal is not promoted because it “looks right” or has a high win rate.

Minimum conditions to consider promotion:

1. event-level causal QA passes;
2. 2024 discovery effect exists with reasonable sample size;
3. 2025 validation keeps direction and practical magnitude;
4. frozen 2026 OOS remains positive;
5. effect is not dependent on one month or tiny event subset;
6. bootstrap uncertainty is acceptable;
7. placebo tests do not explain the edge;
8. cost/latency stress remains positive enough for execution;
9. parameter plateau exists instead of a single lucky threshold;
10. average realizable move is economically meaningful relative to ATR and friction;
11. no hidden use of true-aggressor terminology from the `side` proxy;
12. live implementation can reproduce historical causal state transitions tick-for-tick.

Possible final verdicts:

```text
PRODUCTION_CANDIDATE
RESEARCH_ONLY
REGIME_ONLY
INSUFFICIENT_SAMPLE
REJECT_NO_EDGE
REJECT_EXECUTION_FRAGILE
```

---

# 26. Implementation order for engineers

Do this in order. Do not skip ahead.

## Milestone 1 — Data contract
- [ ] Three-year schema QA
- [ ] Physical-order test
- [ ] Contract isolation test
- [ ] Session catalog

## Milestone 2 — Causal primitives
- [ ] Multi-resolution causal bars
- [ ] Per-bar Volume Profile / POC
- [ ] Developing POC
- [ ] ATR/profile normalization

## Milestone 3 — Continuous features
- [ ] Rising-channel context
- [ ] Broad-channel width
- [ ] POC migration / divergence
- [ ] High-zone pressure proxy
- [ ] Buying efficiency / impact asymmetry

## Milestone 4 — Unbiased events
- [ ] Relaxed high-zone opportunity universe
- [ ] Episode de-duplication
- [ ] Event Store
- [ ] Exact decision price/seq

## Milestone 5 — Outcomes
- [ ] Balance metrics
- [ ] Reversal metrics
- [ ] Physical-tick MFE/MAE
- [ ] Structure-break timing

## Milestone 6 — Discovery 2024
- [ ] Feature dose-response
- [ ] Threshold plateaus
- [ ] Ablation
- [ ] Placebo
- [ ] Visual sanity review

## Milestone 7 — Validation 2025
- [ ] Frozen feature definitions
- [ ] Month/regime consistency
- [ ] Execution candidates

## Milestone 8 — Final OOS 2026
- [ ] Frozen config
- [ ] No retuning before result publication
- [ ] OOS report

## Milestone 9 — Production stress
- [ ] Friction
- [ ] Latency
- [ ] Entry families
- [ ] Trade management
- [ ] Capture ratio/right tail

## Milestone 10 — UI/Replay integration
- [ ] Only after research feature semantics stabilize
- [ ] Node library
- [ ] Pattern wall
- [ ] Blind training cases

---

# 27. First hypotheses to test

Do not assume they will survive.

### H1 — POC non-advance alone

In rising/broad-channel context, `POC[t] <= POC[t-1]` predicts lower next-horizon returns / higher downside excursion.

### H2 — Price/POC divergence is stronger than raw lower POC

`price makes/holds new high while POC slope stalls/falls` carries more information than `poc_delta < 0` alone.

### H3 — Pressure without price response adds incremental edge

High-zone positive tick-direction pressure has little value alone, but **high pressure + low upside efficiency** predicts balance/reversal.

### H4 — Sequence matters

`up-channel → POC weakening → pressure inefficiency → structure break` outperforms unordered simultaneous thresholds.

### H5 — The first outcome is balance, not immediate reversal

The signal may primarily predict reduced trend efficiency / two-sided rotation, with profitable short entry requiring later confirmation.

### H6 — Confirmation improves execution quality

Waiting for micro-structure break reduces MAE enough to offset later entry.

### H7 — 15m is visually intuitive but not necessarily optimal

The same phenomenon may be strongest at 1m/3m/5m, while 15m is useful as context only.

---

# 28. Important interpretation rule

The project should be willing to conclude any of the following:

- POC weakening is real, pressure proxy adds nothing;
- pressure efficiency is useful, POC adds nothing;
- both matter only in certain volatility regimes;
- the pattern predicts chop but not reversal;
- it predicts reversal but execution is too slow/cost-sensitive;
- no robust edge exists.

A negative result is a valid research outcome. The objective is a **deployable advantage**, not confirmation of the screenshot narrative.

---

# 29. Branch policy

This branch is intentionally isolated:

```text
research/poc-absorption-reversal-v1
```

Rules:

- no merge to `main` during research;
- raw MTX Parquet files are never committed;
- every research result records `git_commit`, `config_hash`, and data-year coverage;
- failed hypotheses remain documented;
- any promoted production logic must be reimplemented through the shared causal market-state layer and parity-tested against historical replay.
