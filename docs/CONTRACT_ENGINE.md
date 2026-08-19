# MTX Contract Engine

## Why this exists

Annual MTX Parquet files can contain several monthly outright contracts on the same trading date. Those contracts must never be mixed into one Volume Profile or Auction state.

## Production default: `strict`

`strict` uses the calendar front month rather than the completed day's volume ranking.

- current `YYYYMM` remains the front contract through its third-Wednesday expiration date;
- after that date, the next available monthly contract becomes front;
- only one outright contract is admitted to a daily profile;
- a contract change starts a roll blackout (default one trading day), so a new contract is not compared against the previous contract's Value Area;
- the expiry-day profile remains the expiring contract only, preventing 13:30+ next-month prints from being mixed with it.

This makes contract selection compatible with future live use: the scanner does not need to know the day's final volume before deciding which contract it is observing.

## `front_month`

Uses the same calendar front-month selector. It is retained as an explicit mode for experiments/configuration clarity.

## `dominant_volume`

Uses the completed trading day's total volume ranking.

This is **non-causal** because the ranking is not known at 08:45. It is retained only for diagnostics and historical comparisons. It must not be used to claim live-causal strategy performance.

The UI labels this mode as diagnostic / non-causal and defaults to `strict`.

## Outright filtering

Only expiry strings matching:

```text
^\d{6}$
```

are eligible monthly outright contracts. Spread/combo identifiers are excluded before profile/event construction.

## Physical order invariant

Contract filtering is a boolean mask over raw Parquet rows. It does not reorder rows. `_seq` remains the physical file-row sequence and same-second prints keep that order.
