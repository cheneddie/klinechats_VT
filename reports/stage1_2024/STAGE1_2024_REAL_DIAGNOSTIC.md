# MTX 2024 第一階段真實資料診斷

## Evidence boundary
- Source: `MTX_2024(2).parquet`
- Raw rows: 50,862,751
- Product: MTX
- Outright rows: 50,862,689
- Spread/combo rows removed: 62
- Day-session front-contract 1m bars: 72,156
- Trading days: 241
- Session: 08:45–13:45 (last observed minute 13:44)
- Strict calendar front contract: 241/241 day-session days present
- This is a **2024 single-year diagnostic**, not OOS validation.

## Mechanical rules tested
### ORB
- Opening ranges: 5/15/30/60 min
- Signal: first 1m close outside opening range, before 11:30
- Entry: next minute open
- Stop: 0.5x or 1.0x OR width behind breakout level
- Target: 2R
- Exit: target / stop / 13:40

### Failed Breakout
- Level: OR15 high/low
- Excursion: >= max(2 points, 10% OR width)
- Reclaim windows: 1/3/5/10 minutes
- Entry: next minute open after reclaim
- Stop: failure extreme + 1 point
- Target: 1R
- Exit: target / stop / 13:40

### VWAP Mean Reversion
- Exact session trade VWAP and weighted sigma from raw trade price*volume
- Signals: z=1.5/2.0/2.5/3.0, 09:15–12:30
- Entry: next minute open
- Stop: (z+1)sigma from signal VWAP
- Target: frozen signal VWAP
- Require planned RR >= 1
- Exit: target / stop / 13:40

## Physical sequence QA
- 30 random entry bars checked against original Parquet physical `seq_first`: 30/30 exact match.
- 13 trades had same 1m stop+target ambiguity.
- Raw physical tick order was used to resolve all 13; 5 were target-first and 8 stop-first.

## Key results
| Strategy | Config | N | Gross Avg R | PF | 1pt friction Avg R | 2pt friction Avg R | Positive months |
|---|---|---:|---:|---:|---:|---:|---:|
| VWAP MR | Z2.5 / stop Z3.5 / target VWAP | 92 | +0.2149 | 1.3339 | +0.1236 | +0.0323 | 8/12 |
| Failed Breakout | OR15 / 3m reclaim / 1R | 215 | +0.0670 | 1.1441 | +0.0200 | -0.0271 | 5/12 |
| ORB | OR15 / 0.5OR stop / 2R | 237 | +0.0266 | 1.0415 | +0.0002 | -0.0262 | 7/12 |
| ORB | OR60 / 1OR stop / 2R | 196 | +0.0122 | 1.0431 | +0.0044 | -0.0034 | 5/12 |

### Bootstrap 95% CI (day/trade level; one trade/config/day by construction)
- VWAP Z2.5 gross AvgR 95% CI: **[-0.1394, +0.5867]**
- VWAP Z2.5 with 1pt friction: **[-0.2412, +0.5091]**
- Failed Breakout 3m gross: **[-0.0698, +0.2000]**
- Failed Breakout 3m with 1pt friction: **[-0.1159, +0.1523]**
- OR15 0.5OR gross: **[-0.1478, +0.2071]**

No tested baseline has a 95% interval entirely above zero in 2024.

## Practical-value gate
Average ATR14 at trade time was roughly 332–339 points.
- VWAP Z2.5 average trade PnL: +4.50 pts = ~1.92% ATR
- Failed Breakout 3m average trade PnL: +2.64 pts = ~1.46% ATR
- OR15 0.5OR average trade PnL: +3.82 pts = ~0.62% ATR

All three fail a production criterion requiring average per-trade point expectancy around >=10% ATR.

## Exploratory findings (NOT frozen strategy rules)
- VWAP Z2.5 long: N=50, gross AvgR +0.4483, 1pt net AvgR +0.3811.
- VWAP Z2.5 short: N=42, gross AvgR -0.0630, 1pt net AvgR -0.1830.
- VWAP Z2.5 is weak before 09:30 and after 11:30; positive descriptive results were concentrated 09:30–11:29.
- Failed Breakout 3m long/short were similar, but most signals before 09:30 had near-zero/negative 1pt net expectancy.

These are discovered on 2024 and therefore must be frozen and tested on another year before being treated as Edge.

## Current verdict
1. **Naked ORB:** reject as production candidate in current form.
2. **Failed Breakout:** structural hint only; friction removes most advantage. Keep for regime/volume/location enrichment, not live trading.
3. **VWAP MR Z2.5:** strongest 2024 candidate, but sample=92, CI crosses zero, H1/H2 strongly asymmetric, and average point expectancy is far below the 10% ATR practical gate. Keep as research candidate only.
4. Next valid step: freeze the causal rule family and test on independent 2025/2026 data; do not optimize further on 2024 before OOS.
