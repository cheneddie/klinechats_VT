# M5 Development 3 — Continuous Balance Measurement QA

> Branch: `research/poc-absorption-reversal-v1`  
> Development: **3 / Balance Outcome**  
> Verdict: **`M5_DEV3_BALANCE_MEASUREMENT_PASS`**  
> M5 milestone: **OPEN** — Dev4–Dev6 remain.

## Scope

Development 3 measures Balance continuously. It does **not** define a Balance threshold, a good/bad signal, P&L, win rate, PF, or predictive edge.

The engine consumes the frozen M4 events and the exact Dev2 physical future windows.

## Frozen measurement semantics

### Two path-efficiency scales

Raw physical-tick efficiency:

```text
abs(last_future_price - trigger_price)
--------------------------------------
sum(abs(changes over [trigger_price] + every future physical tick))
```

1-second efficiency:

```text
abs(last_1s_close - trigger_price)
----------------------------------
sum(abs(changes over [trigger_price] + last physical future tick in each wall-clock second))
```

Both are retained. Dev3 does not choose whichever looks better.

A path with future observations but zero total movement has `path_efficiency = null`, not zero. An event with zero future observations keeps all Balance path measures null.

### Two-sided activity

Per horizon:

- `up_excursion_atr`
- `down_excursion_atr`
- `future_range_atr`
- `two_sided_min_excursion_atr`
- `two_sided_total_excursion_atr`

### Time balance

`time_above_trigger`, `time_below_trigger`, and `time_at_trigger` are time-weighted physical states. The initial state is trigger price; after each future physical tick, its price remains the state until the next tick or deadline.

### Frozen reference levels

`high_retest_count` uses the causal M4 `rolling_high` known at `trigger_seq`.

`range_cross_count` uses frozen M4 `trigger_price` as its zero-center; exact touches are neutral and bridge between the last/next nonzero side.

Dev1/Dev2 core fingerprint is not reopened. Dev3 adds a separate reference manifest over:

```text
event_id + trigger_price + rolling_high
```

2024 two-day reference hash:

`3f4799d581564387af1a91699c960b84a51c31c9a1857c2f36d6c94015a01f24`

### Microstructure-count sensitivity

Raw physical retest/cross counts were found to inflate strongly with same-second transaction churn. Therefore Dev3 preserves both:

- `raw_tick_high_retest_count` / `raw_tick_range_cross_count`
- canonical `high_retest_count` / `range_cross_count` on the 1-second close path

This is a measurement-scale distinction, not threshold tuning.

## Real 2024 QA

M4 parity was re-established before measuring Balance:

```text
2024-08-15 + 2024-08-16 / day / strict 202408
217,670 physical ticks
15s 471 / 30s 237 / 1m 108 / 3m 36 / 5m 31 / 15m 16
Total = 899 frozen events
```

Deterministic Dev2 sample was reused:

```text
50 events × 8 horizons = 400 windows
400 / 400 independent raw-mask Balance audit PASS
0 mismatch
selected_event_ids_hash = d96bb64a56843e7198129a811c828968f3c5d31571e963ddaa15dbee15b5853d
```

A separate real night boundary audit covered 144,044 physical ticks and 1,756 frozen night events. Eight deterministic boundary events across five timeframes produced:

```text
8 × 8 horizons = 64 windows
64 / 64 PASS
0 mismatch
```

Two end-of-session events in the day sample have no future observation; they remain missing rather than being converted to zero movement.

## Descriptive distributions — not edge evidence

Each cell is `P10 / P25 / Median / P75 / P90` on the 899-event day QA sample; observed N is 897 per horizon because two events have no future observation.

| Horizon | Raw tick efficiency | 1s efficiency | Future range ATR | Two-sided min ATR | 1s high retests | 1s trigger crossings |
|---|---|---|---|---|---|---|
| 30s | .00392/.01269/.02748/.06329/.1200 | .02564/.06977/.1471/.2593/.3333 | .3478/.6512/.9825/1.400/1.901 | 0/.03079/.1628/.3182/.5369 | 0/0/0/1/2 | 0/0/1/3/4 |
| 1m | .00318/.00963/.01956/.04065/.08251 | .02284/.05263/.1064/.1818/.2558 | .4739/.9423/1.439/2.062/2.836 | 0/.07865/.2276/.4828/.7418 | 0/0/0/2/4 | 0/1/2/4/6 |
| 3m | .00208/.00444/.01009/.02165/.04070 | .01031/.02479/.05263/.09434/.1407 | .7912/1.704/2.531/3.465/4.592 | .03727/.1918/.4930/.8974/1.374 | 0/0/2/5/8 | 0/1/4/7/11 |
| 5m | .00136/.00370/.00844/.01710/.02866 | .00709/.01983/.04444/.07143/.1064 | 1.065/2.229/3.307/4.508/5.600 | .08203/.2513/.6731/1.167/1.806 | 0/0/3/7/11 | 1/2/5/10/14 |
| 15m | .000848/.00229/.00491/.00870/.01516 | .00539/.01188/.02429/.03983/.05948 | 1.815/3.881/5.448/7.447/10.105 | .1542/.4073/1.077/2.039/2.809 | 0/2/8/12/16 | 1/5/10/17/23.4 |
| 30m | .000570/.00134/.00287/.00515/.00917 | .00339/.00657/.01369/.02554/.03659 | 2.177/4.965/7.333/10.33/13.60 | .2657/.7636/1.647/2.716/3.843 | 0/4/11/18/25 | 3/7/15/27/40 |
| 60m | .000316/.000845/.00197/.00350/.00732 | .00183/.00421/.00932/.01592/.02276 | 3.076/5.554/8.727/12.51/16.11 | .3194/.8902/2.000/3.161/4.468 | 0/5/16/24/39 | 4/10/22/39/54 |
| session_end | .000219/.000422/.00208/.00435/.00962 | .000869/.00221/.00691/.01700/.03702 | 3.228/7.464/11.93/18.93/30.75 | .3676/.9754/2.416/4.151/5.831 | 0/7/30/70/88 | 5/13/43/75/99.4 |

Full machine-readable quantiles are committed in `M5_DEV3_BALANCE_DISTRIBUTION_2024_REAL_QA.json`.

## What can and cannot be concluded

Observed only:

- raw-tick efficiency is materially lower than 1-second efficiency at every horizon, consistent with microstructure churn;
- raw retest/cross counts are much larger than their 1-second counterparts;
- range and two-sided excursion naturally increase with horizon.

These are **measurement properties**, not evidence that Balance predicts reversal.

Forbidden at Dev3: selecting an efficiency cutoff, declaring Balance/Not-Balance, choosing a best horizon, or using these distributions to optimize a trading rule.

## Reproducibility package

- `server/poc_absorption/balance_outcomes.py`
- `tests/test_poc_absorption_balance_outcomes.py`
- `tools/poc_absorption/m5_balance_outcome_qa.py`
- `config/poc_absorption/m5_balance_outcome_v1.json`
- `reports/poc_absorption/M5_DEV3_BALANCE_REFERENCE_MANIFEST_2024_REAL_QA.json`
- `reports/poc_absorption/M5_DEV3_BALANCE_DISTRIBUTION_2024_REAL_QA.json`
- `reports/poc_absorption/M5_DEV3_FORMAL_QA_SUMMARY.json`

Development 4 must not begin until the exact branch head containing this package passes the full research CI.
