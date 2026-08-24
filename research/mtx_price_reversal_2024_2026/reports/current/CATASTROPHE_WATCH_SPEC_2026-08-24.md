# Catastrophe Watch — Monitoring Specification

Purpose: classify live risk state without silently changing the frozen trading strategy.

## Pre-entry context

Record:
- Entry Risk Grade
- 300s range / Prior14 range
- 60s range / 300s range
- activity density
- persistence / price-discovery density
- rolling flow percentile
- Day Stress Grade if available

## During-position alerts

Record, with event timestamps:
- ACCEL30 trigger status
- Repeat5/45 trigger status
- first -1x / -2x / -3x / -5x threshold breach time
- 120s watch state
- 180s watch state
- 240s watch state

## Descriptive state ladder

Historical 120-second tail5 rates:
- GREEN ~0.44%
- YELLOW ~1.06%
- ORANGE ~23.68%
- RED ~55.56%

Historical 180-second tail5 rates:
- GREEN ~0.15%
- YELLOW ~0.54%
- ORANGE ~25.0%
- RED ~55.6%

These rates are historical calibration references only. They must be recalibrated forward and must not be translated directly into stop orders.

## Required forward monitoring metrics

- state counts
- state transition matrix
- tail5 rate by state
- final Net by state
- MAE severity by state
- false-alert rate
- tail5 capture by 120/180/240 seconds
- year/month/day-night calibration drift

## Guardrail

A monitoring state cannot become a trading rule without a new version, new frozen specification and a new forward clock.
