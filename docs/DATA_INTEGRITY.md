# MTX Data Integrity Contract

This file records the non-negotiable rules for the supplied MTX Tick data.

## Uploaded source used for development
File name: `MTX_2027.parquet`

Actual file contents verified in the development environment:
- rows: **2,115,188**
- datetime: **2026-07-31 15:00:00 → 2026-08-14 13:44:59**
- product: **MTX only**
- expiry: **202608 only**
- spread-like expiries: **none in this file**
- price range: 42,090 → 46,573
- volume range: 2 → 1,136
- `side` values: -1 / 0 / +1
- physical timestamps are non-decreasing
- observed clock resolution: seconds

Machine-readable report: `reports/MTX_2027_DATA_QA.json`

## Rule 1 — Never re-sort Tick rows
The clock is only second-resolution, but rows within the same second already carry the true trade sequence supplied by the source.

Immediately after reading the Parquet file the pipeline assigns:

```python
_seq = 0, 1, 2, 3, ...
```

No `sort_values(datetime)`, `sort_values(price)`, or `sort_values(side)` is allowed afterward.

Filtering must use a boolean mask. Surviving rows remain in the original physical sequence.

## Rule 2 — Product / contract / spread filtering happens before research
For mixed files:
1. require the intended product (`MTX`),
2. require a legal outright expiry (default regex `^\d{6}$`),
3. reject spread/combination expiries such as values containing `/`,
4. keep the original `_seq` order after filtering.

Do not remove spreads by looking at “strange prices”; identify them by instrument/expiry metadata.

## Rule 3 — Do not back-adjust profile prices
Volume Profile / VAH / VAL / POC / LVN are price-by-volume structures. Back-adjusting prices across contracts can manufacture price levels that never traded. Profiles should be calculated on the actual selected contract segment.

## Rule 4 — `side` is NOT true Order Flow Delta
Development QA proved:

```text
side == sign(price[t] - price[t-1])
```

with 100% match on this uploaded file.

Therefore `side` is a **Tick Direction proxy**. It must not be labeled:
- Bid/Ask aggressor side,
- true Delta,
- true CVD,
- Footprint aggression.

True Fabio Footprint/CVD work requires Bid/Ask-classified trades or richer TBBO/MBO data.

## Rule 5 — Aggregation must preserve physical first/last trades
For one-second or one-minute bars:
- Open = first physical trade in the bucket
- Close = last physical trade in the bucket
- High / Low = extrema inside the bucket
- Volume = sum inside the bucket
- persist `firstSeq` and `lastSeq`

The production pipeline intentionally uses `groupby(..., sort=False)` and never sorts the Tick rows.

## Rule 6 — Hide Future
A replay question can only display bars up to the information time of that decision node. Structural labels (Extreme, Clear Reclaim, Causal Leg, LVN, Entry) are revealed only after the learner has passed the corresponding node. Exam mode suppresses structural labels until the case is completed.

## Evidence boundary
The bundled 2026 fixture is used to test and train the UI mechanics. The statistically validated V3/V4 performance discussed in the research came from the earlier 2025 MTX study. Do not treat the small 2026 trainer fixture as a new independent performance validation.
