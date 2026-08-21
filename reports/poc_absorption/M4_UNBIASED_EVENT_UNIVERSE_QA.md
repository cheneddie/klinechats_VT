# POC Absorption Reversal — M4 Unbiased Event Universe QA

> Branch: `research/poc-absorption-reversal-v1`  
> Event schema: `POC_PROBE_EVENT_V1`  
> Universe version: `HIGH_PRICE_PROBE_V1`  
> Universe schema: `POC_HIGH_PRICE_PROBE_UNIVERSE_V1`

## Closure status

**PENDING 2024 FULL-YEAR UNIVERSE DISTRIBUTION SANITY.**

The engine/tests/config/reproducible runner are frozen before the annual distribution scan. M4 must not be checked until branch-head CI passes and the annual universe/episode integrity report is complete without changing detector thresholds.

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

The flat feature columns are also retained for columnar research; `feature_snapshot` makes the selection/feature boundary explicit.

## Raw trigger + episode separation

Every causal probe stays in the raw store. `first_trigger_per_episode()` is only a derived research view. Episode clustering never selects a prettier trigger and cannot change event membership.

Rolling 24-bar context may continue across consecutive trading days for the same contract/session with no explicit data gap. Episode dependency **cannot** cross a trading day; contract roll or `DATA_GAP_BLACKOUT` also hard-reset continuity.

## Local evidence before commit

- M4 dedicated synthetic tests: **6/6 PASS**.
- Full M1–M4 local research chain previously reproduced as **24/24 PASS** before schema freeze; branch CI is the authoritative post-commit gate.
- M4 self-test: non-price mutation invariant PASS; frozen event schema PASS.
- Real 2024-08-15 + 2024-08-16 six-timeframe QA previously passed on 217,670 physical ticks; POC/TDP/high-zone/impact mutation did not change event/episode/trigger selection.

The two-day sample is engineering evidence only and is not used to tune detector thresholds.

## Required annual sanity before closure

2024 only, no outcomes and no threshold changes:

- valid/warm bars, raw triggers, episodes, first triggers;
- trigger/warm rate and episodes/trading-day;
- triggers/episode and episode-duration median/P90/P95/max;
- reset-reason distribution;
- month, time-of-day, contract, day/night splits;
- upper-80-only vs near-high-only vs both;
- episode trigger-count buckets and largest episode;
- zero episodes crossing trading day, contract, or `DATA_GAP_BLACKOUT`.

M4 does not claim predictive edge. M5 is forbidden from modifying the M4 event store.
