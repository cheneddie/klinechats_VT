# POC Absorption Reversal — M4 Unbiased Event Universe QA

> Branch: `research/poc-absorption-reversal-v1`  
> Event schema: `POC_PROBE_EVENT_V1`  
> Universe version: `HIGH_PRICE_PROBE_V1`  
> Universe schema: `POC_HIGH_PRICE_PROBE_UNIVERSE_V1`  
> Frozen config hash: `d7bf39afa32582bc06e00b2df9995b9cb9cc14670a6974834d80cf3d079016fb`

## Verdict

`REPRODUCIBLE UNBIASED EVENT UNIVERSE PASS`

M4's engineering semantics, anti-selection tests, schema/config freeze, two-day six-timeframe real-data QA, and 2024 full-year universe-distribution sanity are complete. The branch head containing the annual evidence passed the unchanged M1–M4 Research CI + M3/M4 self-tests. M4 makes **no predictive edge claim**. M5 is forbidden from changing M4 event membership.

## Price-only anti-circularity rule

Membership uses only causal completed-bar price state:

```text
lookback = 24 completed bars
upper zone = close >= rolling_low + 0.80 * rolling_range
near high = (rolling_high - close) / ATR <= 0.25
probe = warm AND (upper zone OR near high)
```

Trend slope, POC, POC divergence, TDP pressure, high-zone pressure, efficiency, and every future outcome are forbidden selection inputs.

## Frozen event contract

Every raw event carries at least:

```text
event_schema_version = POC_PROBE_EVENT_V1
universe_version = HIGH_PRICE_PROBE_V1
universe_schema_version = POC_HIGH_PRICE_PROBE_UNIVERSE_V1
universe_config_hash
feature_schema_version

event_id / episode_id / episode_trigger_number
contract / session / timeframe
trigger_seq / trigger_time / trigger_price / trigger_reason
bar_start_seq / bar_end_seq
rolling_high / rolling_low / atr / range_position / distance_high_atr
feature_snapshot
```

Raw triggers are never deleted. `first_trigger_per_episode()` is a derived research view only.

Rolling 24-bar context may continue across consecutive trading days for the same contract/session with no explicit data gap. Episode dependency cannot cross trading day, contract, or `DATA_GAP_BLACKOUT`.

## Engineering evidence

- M4 dedicated synthetic tests: **6/6 PASS**.
- Full M1–M4 research chain: **24 tests**.
- Non-price mutation gate: changing POC/TDP/high-zone/impact fields does not change `event_id`, `episode_id`, or `trigger_seq`.
- Future-price mutation gate: ticks after a cutoff cannot change already-existing prior events.
- Exact decision point: `trigger_seq/time/price` is the physical final tick of the completed trigger bar.
- Real 2024-08-15 + 2024-08-16 six-timeframe QA passed on 217,670 physical ticks.
- Timeout metadata bug was fixed without changing trigger membership: `MAX_EPISODE_SECONDS` closes at the frozen deadline rather than waiting for the next completed bar.
- Final annual-evidence branch head `30e2eb18b74e0dcf47690161b8faa79dde5456bc` passed `POC Absorption Research CI` run **#36 / 32539980836** with M1–M4 pytest, M3 self-test, and M4 self-test all SUCCESS.

## 2024 full-year universe sanity

Source scan:

```text
49 / 49 Parquet row groups
50,862,751 physical rows
strict-contract 15s base = 1,062,826 bars
241 observed regular day trading dates
```

No outcomes, P&L, MFE/MAE, structure-break labels, 2025, or 2026 data were used. The detector config/hash was not changed after observing annual distributions.

| TF | Valid bars | Warm bars | Raw triggers | Episodes | Trigger / warm |
|---|---:|---:|---:|---:|---:|
| 15s | 1,062,826 | 1,062,190 | 264,970 | 111,958 | 24.95% |
| 30s | 539,592 | 538,971 | 132,719 | 56,095 | 24.62% |
| 1m | 270,621 | 270,000 | 66,248 | 27,879 | 24.54% |
| 3m | 90,257 | 89,636 | 22,448 | 9,366 | 25.04% |
| 5m | 54,156 | 53,535 | 13,848 | 5,764 | 25.87% |
| 15m | 18,052 | 17,431 | 5,215 | 2,935 | 29.92% |

All six timeframes have:

```text
episodes crossing trading day = 0
episodes crossing contract = 0
episodes crossing DATA_GAP = 0
```

Continuity-boundary accounting is separate from market-episode termination and is identical across timeframes:

```text
CONTRACT_RESET = 24
DATA_GAP_RESET = 1
DATASET_END = 2
```

The annual scan also records month, time-of-day, contract, day/night session, trigger-reason, episode-duration, and trigger-count distributions.

Detailed evidence:

- `reports/poc_absorption/M4_2024_UNIVERSE_DISTRIBUTION.md`
- `reports/poc_absorption/M4_2024_UNIVERSE_DISTRIBUTION.json`

## Annual observations — not parameter changes

1. Trigger/warm-bar rate is broad by design: roughly 24.5–25.9% on 15s–5m and 29.92% on 15m.
2. `NEAR_HIGH_0_25ATR_ONLY = 0` on **all six timeframes** in 2024. The near-high branch adds no V1 membership outside upper-80%-range, but it still marks a stricter `BOTH` subset. This is an M6 ablation/redundancy question; V1 remains unchanged.
3. Short-timeframe episode long tails exist but are rare. Episodes with >10 triggers are ~0.27% on 15s, ~0.26% on 30s, ~0.27% on 1m, 0.096% on 3m, and zero on 5m/15m. M6 must therefore cluster inference by episode and trading day rather than treating raw triggers as IID.
4. 15m monthly trigger-rate dispersion is wider than shorter timeframes; it is documented, not tuned away.

## M5 firewall

After M4 closure the architecture is:

```text
M4 frozen probe_events   (READ ONLY)
          ↓ event_id join only
M5 probe_outcomes
```

The M5 Outcome Engine may not delete, re-rank, regenerate, or condition event membership using future price paths. Balance, reversal, MFE/MAE, structure-break and tradeability fields belong only in the separate outcome store.
