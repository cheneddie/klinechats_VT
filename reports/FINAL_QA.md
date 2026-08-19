# Fabio Binary Decision Replay Trainer — Final QA

## Status
**PASS — Phase 1 through Phase 4 completed.**

The final application has been run with the official vendored KLineChart **10.0.2** bundle in Chromium via GitHub Actions / Playwright.

## Final runtime acceptance
Source: `screenshots/phase4-final.json`

- title: Fabio 二元決策 Replay 訓練器
- chart engine badge: KLineChart V10
- KLineChart canvas count: 10
- replay: 2026-08-11 · 1秒 Replay
- decision count: 5
- final strategy state: **EXECUTE LONG**
- Extreme: **44797 @ 09:19:55**
- LVN: **44884**
- Entry: **44883 @ 09:20:33**
- training mode: 練習
- cumulative decisions in fresh browser run: 5
- accuracy: 100%
- Data Integrity status: **VERIFIED**
- source rows displayed: **2,115,188**
- history export control: present
- browser runtime errors: **0**

Screenshots:
- `screenshots/phase4-final.png`
- `screenshots/phase4-final-data.png`

## CI acceptance
The production CI job completed successfully with all of these steps green:
1. checkout
2. Node 22 setup
3. npm install
4. `npm test`
5. `npm run build`
6. vendored KLineChart V10.0.2 verification

Automated tests cover:
- trainer accuracy / speed / weakest-node summary
- confidence calibration
- random-case strategy/exclusion behavior
- replay fixture source-order contract
- 1-second `firstSeq / lastSeq` monotonic physical progression
- KLineChart exact version pin and vendored file existence

## Uploaded Parquet QA
Source: `reports/MTX_2027_DATA_QA.json`

- uploaded filename: `MTX_2027.parquet`
- actual time range: 2026-07-31 15:00:00 → 2026-08-14 13:44:59
- rows: 2,115,188
- product: MTX
- expiry: 202608
- spread-like expiry: none
- timestamp physical order: non-decreasing
- observed time resolution: 1 second
- same-second source row order: must be preserved
- side values: -1 / 0 / +1
- `side == sign(price[t] - price[t-1])`: 100%
- therefore `side` is not true Bid/Ask aggressor information

## Hide-Future acceptance
Phase 2 interactive QA walked through four MR nodes before the screenshot and verified:
- one-second replay active,
- decisionCount = 4,
- branch = MR 回家,
- Extreme revealed only after the corresponding decision,
- LVN revealed only after the Location node,
- zero runtime errors.

Exam-mode Phase 3 QA verified that a decision is stored while the immediate answer/structure stays hidden.

## Product features accepted
- Replay controls
- Previous VAH / POC / VAL
- MR / BO / WAIT state model
- custom KLineChart Fabio overlays
- progressive structural reveal
- Practice / Exam / Mistake Review modes
- confidence score
- response timing
- persistent browser history
- weakest-node analytics
- keyboard controls
- JSON history export
- in-app Data Integrity panel
- responsive/accessibility polish
- deterministic static production build
- reproducible Parquet fixture builder

## Known evidence boundary
This product is a subjective-decision training environment, not a live auto-trading engine.

The short 2026 dataset bundled for UI testing is not a new full out-of-sample proof of strategy profitability. The true Bid/Ask aggressor / Footprint / CVD layer also remains untested because the uploaded `side` field is only Tick Direction. A future microstructure phase requires Bid/Ask-classified trades, TBBO or MBO.

## Release decision
The branch `fabio-replay-v1` is ready for code review. It should not be merged to `main` until the owner reviews the UI, rule wording and training-case assumptions.
