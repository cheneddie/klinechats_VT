# MTX Tail-Risk Diagnostic — 2024–2026 in-sample research

## Status
This report is a **post-hoc tail-risk investigation** on the same 2024–2026 sample used to discover the strategy. The frozen Forward-OOS V1 remains unchanged. Any overlay below requires forward A/B validation.

## Baseline tail problem
- N: 1,112
- Net@2: +8,426 points
- Expectancy: +7.577 points/trade
- PF: 1.306
- Average losing trade: -56.22 points
- Max loss: -589 points
- Max loss / |average loss|: 10.48x
- Max DD: -1235 points

The -589 point trade is not ordinary loss-scale noise. It is a distinct failure path: 2025-04-07 22:18:26, threshold -34, entry 19170; MTM at 15/30/60/120/180/240s = -189/-221/-299/-459/-399/-532; final gross -587, net -589. MFE was 0 and MAE -606. Prior14 same-kind session range was 327.86, so the trade was already -67.4% of that causal range after 30 seconds.

## Failure modes
1. **Catastrophic acceleration:** no rebound, rapid adverse extension immediately after entry.
2. **Failed reversal / second leg:** some small early rebound, but the price never establishes recovery and later resumes the selloff.
3. **Late collapse after valid rebound:** dangerous to stop mechanically; some trades recover early and only fail late. This is why a fixed point stop damages winners.

## Overlay A — ACCEL_30 only
Rule: at the first tradable print at/after entry+30s, exit if `gross_30 <= -0.20 × Prior14 same-kind session average range`. After exit, keep the position slot locked until the original entry+300s horizon.

- Triggers: 4 / 1,112 trades
- Net@2: +8,888 vs +8,426
- E: +7.993
- PF: 1.329
- Max loss: -310 (baseline -589)
- Max DD: -1176
- Max loss / |avg loss|: 5.61x

The -589 catastrophe becomes -223 net. This simple breaker is the lowest-complexity risk hypothesis.

## Overlay B — R2 two-stage invalidation
Stage 1 is ACCEL_30. If it did not fire, at 180s exit only when:
- sampled MTM at 15/30/60/90/120/180s never reclaimed entry (all <= 0);
- `gross_180 <= -0.75 × |Q0.05 threshold|`; and
- recovery from 120→180s is no more than `+0.25 × |threshold|`.
After any early exit, remain locked out until original entry+300s.

- Net@2: +9,213
- E: +8.285
- PF: 1.347
- Win rate: 54.23%
- Avg loss: -53.72
- Max loss: -297
- Max DD: -1134
- Max loss / |avg loss|: 5.53x

R2 reduces the number of <=-300 trades from 2 to 0 and <=-500 trades from 1 to 0 in this sample, while all three years remain profitable. However, R2 fires much more often and is therefore more exposed to post-hoc overfitting than ACCEL_30.

## Research recommendation
Do **not** replace Frozen V1 based on this sample. Forward paper-test three arms with identical entries and no parameter changes:
1. Control: Frozen V1, 300s hold.
2. Primary challenger: V1 + ACCEL_30 only.
3. Shadow challenger: V1 + R2.

If only one risk overlay is allowed for forward testing, prefer **ACCEL_30** first: it has only four historical triggers, specifically targets catastrophic acceleration, halves the historical max-loss magnitude from -589 to about -310 overall (and turns the -589 event itself into -223), and adds much less model complexity.
