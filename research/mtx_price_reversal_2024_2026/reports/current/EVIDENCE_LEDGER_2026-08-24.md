# Evidence Ledger — MTX Reversal Research

Legend:
- `CONTROL` = frozen base comparison
- `CHALLENGER` = registered forward candidate
- `SHADOW` = calculate but do not promote without new evidence
- `MONITOR` = risk context only; must not alter execution
- `REJECTED` = tested on inspected sample; do not retune

| Research line | Status | Causal | Cross-year direction | Neighborhood/platform | Cluster evidence | Execution/capital benefit | Current action |
|---|---|---:|---:|---:|---:|---:|---|
| Frozen V1 09:00–10:30 + 20:30–22:30 + Causal HighVol | CONTROL | Yes | Yes | Yes | Base CI positive on selected candidate | Yes | Forward OOS only |
| ACCEL30 | CHALLENGER A | Yes | Historical total improves; only 4 triggers | 20%+ region sensible, tiny N | Insufficient rare-event sample | Strong max-loss reduction | Forward rare-event validation |
| ACCEL30 + Repeat5/45 | CHALLENGER B | Yes | Yes historical delta | Small local platform | Incremental date-cluster CI positive | Improves PnL/Ulcer | Preferred challenger |
| Flow-gated FAIL180 | SHADOW C | Yes | Historical non-negative delta in chosen rolling gate | Some local support | Positive vs ACCEL; not robust vs R3-lite | Limited | Observe only |
| R2 FAIL180 unrestricted | SHADOW | Yes | Parameter neighborhood exists | Yes locally | Incremental CI vs ACCEL crosses zero | Strong ES compression | Observe only |
| Entry Risk Grade | MONITOR | Yes | Ranking consistent | Not a trading parameter | Tail risk ratio significant | Entry skip hurts PnL | Monitor/calibrate only |
| Day Stress Grade | MONITOR | Yes | Ranking consistent | 40/60/100 lookbacks similar | Tail-day concentration strong | Halting hurts equity | Monitor only |
| Catastrophe Watch State Machine | MONITOR | Yes | Descriptive consistency | State thresholds are risk labels | Tail capture high | Auto-exit not established | Alert/forensics only |
| Fixed-point stop | REJECTED | Yes | Poor | No useful region | N/A | Damages edge | DO NOT RETUNE |
| 2x–4x threshold stop | REJECTED | Yes | Fails cross-year | No viable platform | N/A | Ideal-fill upper bound still fails | DO NOT RETUNE |
| 60s failure exit | REJECTED | Yes | 2025 fails | No | N/A | Kills late V-turn winners | DO NOT RETUNE |
| Risk-grade entry skip | REJECTED | Yes | Not stable as strategy | N/A | N/A | Material PnL loss | DO NOT RETUNE |
| High-risk delayed/reclaim entry | REJECTED | Yes | Underperforms | N/A | N/A | Confirmation cost too high | DO NOT RETUNE |
| Stress-adaptive holding | REJECTED | Yes | LOYO fails | No | N/A | 2025 failure | DO NOT RETUNE |
| Session kill switch | REJECTED | Yes | Negative total | N/A | N/A | Removes positive post-tail edge | DO NOT RETUNE |
| Extreme-day halt | REJECTED | Yes | Negative total | N/A | N/A | R3 +9539 -> +6740 | DO NOT RETUNE |
| Repeat re-anchor/reset | REJECTED | Yes | Not stable | No | N/A | Longer exposure / worse tails | DO NOT RETUNE |
| Immediate re-entry after Repeat exit | REJECTED | Yes | Worse | N/A | N/A | Re-enters same shock cluster | DO NOT RETUNE |
| Repeat add-on positions | REJECTED | Diagnostic only | N/A | N/A | N/A | Up to 19 concurrent MTX | Violates risk contract |
