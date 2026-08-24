# 2024 Untouched Holdout

The 2024 MTX file was supplied only after the 2025/2026 research and the next candidate were frozen. It was not used to choose parameters before this one-time test.

## Frozen price-only candidate

30-second price move, lower 0.05% threshold estimated from the previous 3 completed outright contract months, long only, complete-second confirmation, +1 second additional latency, first tradable print, fixed 300-second exit, same-session only.

2024 result:

- N = 1,179
- gross expectancy = +2.44 points/trade
- Net @ 2 point round-trip = +0.44
- top-1%-winner-removed gross = +0.47
- positive gross contract months = 6/9
- 2024 standalone contract-block Net @ 2 CI ~= [-1.67, +2.74]

Interpretation: directional holdout success, but insufficient statistical strength for live approval.

## Frozen tick-level aggressive proxy candidate

15-second proxy pressure, lower 0.1% threshold, 240-second hold, identical execution rules.

2024 result:

- N = 1,093
- gross = +0.88
- Net @ 2 = -1.12
- top-1%-winner-removed gross = -0.30

The proxy candidate failed the holdout.

## Raw TRSV

Original frozen raw TRSV 20s / lower 0.1% / 300s:

- gross = +1.07
- Net @ 2 = -0.93

Previously interesting Night and High-Intensity TRSV regime filters also failed 2024. They are not considered stable production regimes.
