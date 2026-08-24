# Forward-OOS Evidence Gates

These gates are pre-registered as of 2026-08-24. Changing a trading rule resets its forward clock.

## Base V1

Minimum observation:
- 6 calendar months
- 200 genuine forward trades

Promotion review requires:
- Net@2 > 0
- PF >= 1.10
- Net@5 > 0
- day-cluster bootstrap 95% lower bound > 0
- drawdown within frozen risk envelope
- exact execution parity and no future leakage

## Challenger A — ACCEL30

Exact rule remains 30-second adverse loss >=20% Prior14 same-session range.

Because the historical trigger rate is only ~0.36%, normal trade count is not a valid validation sample. Event-based evidence is required.

Illustrative minimum evidence review:
- 5 forward triggers: require 5/5 improvement for a strong first review
- 8 forward triggers: require at least 7/8 improvement for a strong review
- aggregate delta must be positive
- no parameter changes

ACCEL30 remains a rare-catastrophe protection hypothesis until genuine forward events accumulate.

## Challenger B — ACCEL30 + Repeat5/45

Exact Repeat rule:
- 5th additional qualifying Q0.05 true crossing
- within 45 seconds of original entry
- tradable price after required latency remains <= original entry
- overlay exit does not unlock new entry until original entry+300 seconds

Do not review before 10 forward Repeat activations.

Provisional promotion review:
- >=8/10 interventions improve corresponding unmodified path
- aggregate forward delta >0
- no single date contributes >50% of delta
- no rule changes

## Shadow C — Flow-gated FAIL180

Do not review before 10 forward activations.

Must demonstrate incremental benefit on top of Challenger B, not only versus ACCEL30.

## Monitor-only models

Entry Risk Grade, Day Stress Grade and Catastrophe Watch:
- track calibration
- track tail capture
- track false alarm rate
- never alter orders unless a separate new pre-registered study/version is created
