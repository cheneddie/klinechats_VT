# Execution Timing Errata — 2026 Last-Week Validation

## Finding

A raw-row cross-check of the uploaded `MTX_2026.parquet` identified an execution-timing error in the previously exported 2026 frozen-strategy trade file.

The 20-second TRSV signal is computed from the **complete signal second**. Therefore the signal for second `t` is not fully known until the data stream advances to `t+1`.

The previous backtest then labelled the trade as having `1s` entry latency, but its stored `entry_price` was actually the **last transaction price in second `t+1`**.

For the 23 frozen-strategy trades from 2026-08-10 through 2026-08-14:

- 23/23 old `entry_price` values exactly equal the last raw trade price in second `signal + 1s`.
- 7/23 old entry prices are outside the OHLC range of the signal second itself.
- Thus `signal_dt` must not be interpreted as entry time.
- More importantly, the previous implementation was one second too optimistic relative to the stated rule "1 second latency after the signal is confirmed".

## Correct executable convention

For a second-labelled signal at `t` covering `[t, t+1)`:

1. The signal is confirmed when the first row with timestamp `>= t+1` arrives.
2. A true additional 1-second latency means the earliest entry is the **first raw transaction at or after `t+2`**.
3. Preserve original raw-row order within the same second.
4. A 300-second holding period is measured from the actual corrected entry timestamp.
5. Exit at the **first raw transaction at or after `entry_time + 300s`**.

## Last-week impact

Using the corrected convention on the same 23 signals (2026-08-10 to 2026-08-14):

- Previous gross total: +134 points
- Corrected gross total: +128 points
- Previous gross mean: +5.826 points/trade
- Corrected gross mean: +5.565 points/trade
- Corrected total after a 2-point round-trip cost assumption: +82 points
- Corrected mean after 2-point cost: +3.565 points/trade

The sign of the last-week aggregate edge survives, but **all previously reported 2025/2026 performance metrics must be treated as provisional until fully rerun using corrected execution timing**.

## Research status

This is a correctness fix, not strategy retuning. Signal lookback, threshold, direction and holding-horizon hypotheses remain unchanged. Any future OOS report must store separately:

- `signal_start/end or signal_second`
- `signal_confirmed_time`
- `entry_time`
- `entry_seq_in_second`
- `entry_price`
- `exit_time`
- `exit_seq_in_second`
- `exit_price`

so that every reported fill can be traced back to raw transaction rows.
