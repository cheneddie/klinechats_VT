# MTX Repeat-Shock Further Research — Real Results

## Core finding
Repeated extreme-selloff signals are not simply bad signals. The 2,907 blocked overlapping signals are positive as independent 300-second entries (E=8.97, PF=1.316). The information is instead that the **first entry becomes too early when the same shock keeps re-triggering**.

## Causal 45-second diagnostic
Trades with 5+ additional true crossings within the first 45 seconds are negative in every calendar year. The low-complexity risk condition chosen for research is: fifth additional qualifying crossing occurs within 45 seconds AND executable price is still <= original entry.

That condition occurs 19 times. Base outcome on those trades: E=-60.42; exiting at the fifth repeat: E=-26.16; incremental improvement=651 points. Improvement is positive in all three years.

## Strategy comparison (Net@2)
- BASE V1: 8426, E 7.58, PF 1.306, MaxLoss -589, MaxDD -1235
- ACCEL30: 8888, E 7.99, PF 1.329, MaxLoss -310, MaxDD -1176
- R2 ACCEL30+FAIL180: 9213, E 8.29, PF 1.347, MaxLoss -297, MaxDD -1134
- R3-lite ACCEL30+REPEAT5/45: 9539, E 8.58, PF 1.364, MaxLoss -310, MaxDD -1176
- R3-full R2+REPEAT5/45: 9707, E 8.73, PF 1.375, MaxLoss -297, MaxDD -1091

## Validation discipline
R3 is post-hoc and must not replace Frozen Forward-OOS V1. Date-cluster bootstrap of incremental R3-lite vs ACCEL30 has 95% interval [47, 1424] points, but this does not remove selection bias. Pseudo leave-one-year-out among only the adjacent low-complexity 4/30 and 5/45 rules gives positive held-out increment in 2024, 2025, and 2026; this is robustness evidence, not true OOS.

## Re-entry / timer reset
Immediate re-entry after a repeat-shock exit is harmful versus locking the strategy until the original 300-second endpoint. Resetting every repeated signal's 300-second timer improves average E/PF but creates up to ~90-minute holds and worsens MaxLoss, so it is rejected as a tail-risk solution.

## Practical conclusion
Keep Frozen V1 unchanged. Forward-test three parallel tracks: Control V1, Challenger A = ACCEL30, Challenger B = ACCEL30 + REPEAT5/45 with lock until original 300-second end. Keep R2/R3-full shadow-only because they add more post-hoc rules.
