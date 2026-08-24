# MTX 2024 Stage 1 Reassessment — Kill / Keep Review

## Scope
This reassessment reuses the verified 2024 physical-sequence backtest results and adds adversarial checks rather than optimizing for prettier curves.

Checks added:
1. outlier / right-tail concentration
2. H1 vs H2 stability
3. quarter-to-quarter adaptive walk-forward selection
4. causal one-factor regime rescue (ATR, opening-range width, gap magnitude, opening drive, RVOL, directional alignment, time)
5. parameter-plateau test for the best rescue hypothesis
6. multiple-testing / reality-check bootstrap after searching many variants
7. friction and practical-value (PnL points vs ATR) gate

## Final decisions

### 1. Naked ORB — KILL as standalone strategy
Baseline OR15/0.5OR/2R: 237 trades, gross +0.0266R, 1pt +0.0002R, 2pt -0.0262R.
Quarterly adaptive selection of the best prior-quarter ORB configuration produced -0.0980R/trade at 1pt friction on the following quarter.
No naked ORB configuration is production-worthy.

### 2. Failed Breakout — KILL as standalone price-only strategy
Best baseline 3m reclaim: 215 trades, gross +0.0670R, 1pt +0.0200R, 2pt -0.0271R.
Quarterly adaptive selection produced -0.1116R/trade at 1pt friction in subsequent quarters.
Regime rescue (RVOL, gap, OR width, time, etc.) did not survive multiple-testing correction (2pt reality-check p≈0.74).
May remain a market-state / feature label, not a standalone entry system.

### 3. Baseline VWAP Z2.5 MR — KILL as standalone production candidate
92 trades, gross +0.2149R, 1pt +0.1236R, 2pt +0.0323R.
But median trade = -1R, maximum losing streak = 12, gross max drawdown ≈ -16.7R, and the top 5 winners contributed ≈99% of total gross R.
Quarterly adaptive parameter selection produced -0.2307R/trade at 1pt friction in following quarters.
After broad parameter/filter search, 2pt reality-check p≈0.80.
Keep only as an OOS hypothesis source, not a usable strategy.

### 4. Large-gap conditioned OR15 breakout — KEEP ONLY AS FROZEN OOS CANDIDATE
Causal gap condition:
abs(session open - previous close) / prior ATR14 > rolling 60-session median of the same ratio, using prior sessions only.

Central frozen candidate:
- OR = first 15 minutes (08:45–08:59)
- first 1m close outside OR before 11:30
- entry next 1m open
- stop = 1.0 × OR width behind breakout level
- target = 2R
- exit = stop / target / 13:40
- large-gap condition as above

2024 internal results:
- N=108
- gross AvgR ≈ +0.3030
- 1pt AvgR ≈ +0.2898
- 2pt AvgR ≈ +0.2765
- gross PF ≈ 1.62
- 2pt total ≈ +29.87R
- 2pt max DD ≈ -10.0R
- H1 2pt AvgR ≈ +0.4545
- H2 2pt AvgR ≈ +0.1445
- average net2 points ≈ +27.3 pts/trade
- net2 points / average ATR ≈ 8.1% (still below the 10% production-value gate)

Robustness plateau (2pt AvgR) for OR15 stop=1OR, gap threshold based on prior-60 rolling quantile:
- q40: H1 +0.396, H2 +0.053
- q50: H1 +0.454, H2 +0.144
- q60: H1 +0.239, H2 +0.103
- q70: H1 +0.271, H2 +0.213
- q80: H1 +0.274, H2 +0.304

This plateau is the strongest evidence found in Stage 1. However:
- Q1 and Q3 were negative while Q2 and Q4 were strongly positive.
- H2 bootstrap CI still crosses zero.
- after accounting for all ~130 ORB parameter/filter variants searched, 2pt reality-check p≈0.45.
Therefore it is NOT validated; it only earns a frozen OOS test on another year.

### 5. VWAP regime rescues — SECONDARY OOS HYPOTHESES ONLY
Examples such as Z2.5 with opening-drive-opposed or low-ATR regime looked materially better in 2024, but samples are small and/or right-tail dependent, and selection-adjusted tests remain weak (2pt reality-check p≈0.80 across the broader VWAP search family).
Do not spend more 2024 optimization budget here.

## Bottom line
Production-approved strategies: **0**.
Standalone families to stop optimizing on 2024: **Naked ORB, Failed Breakout, baseline VWAP MR**.
Primary frozen OOS candidate: **Large-gap conditioned OR15 breakout**.
Secondary OOS-only hypothesis: **regime-filtered VWAP MR**.

The correct next test is an untouched year (2025/2026). No more 2024 tuning should be allowed before that test.
