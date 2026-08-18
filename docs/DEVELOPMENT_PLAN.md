# Fabio Binary Decision Replay Trainer — Development Plan

## Goal
Build a replay trainer that converts Fabio-style Auction Market reasoning into a sequence of observable YES/NO decisions. The application is a training tool, not an auto-trading system.

## Technology
- KLineChart **10.0.2** (pinned and vendored)
- Vanilla JavaScript + Vite development server
- deterministic static production build
- KLineChart V10 `setDataLoader` replay model
- KLineChart custom overlays for Auction / Extreme / Causal Leg / LVN / Entry
- LocalStorage for learner history
- Playwright on GitHub Actions for runtime screenshot QA
- Python data pipeline for Parquet → replay fixtures

## Phase 1 — Replay MVP ✅
- KLineChart V10 chart
- real MTX fixture
- play / pause / step / speed / timeline
- previous VAH / POC / VAL
- binary YES / NO coach
- MR / BO / WAIT question paths
- Traditional Chinese locale registered explicitly
- zero-error runtime screenshot

Screenshot: `screenshots/phase1-final.png`

## Phase 2 — Structural Hide-Future ✅
- 1-second replay around the key MTX case
- exact decision-node future hiding
- progressive Auction / Extreme / Clear Reclaim / Causal Leg / LVN overlays
- decision branch display: WAIT / MR 回家 / BO 搬家
- reaction timing and decision log
- glossary at every node
- exam-safe progressive data reveal

Screenshot: `screenshots/phase2-final.png`

## Phase 3 — Training System ✅
- Practice mode
- Exam mode (no immediate answer reveal)
- Mistake review mode
- confidence score 1–5
- LocalStorage history
- total decisions / accuracy / response time / weakest node
- recent mistakes
- keyboard shortcuts Y / N / Space / arrows / R

Screenshot: `screenshots/phase3-final.png`

## Phase 4 — Production Completion ✅
- reproducible MTX Parquet pipeline
- explicit source-order invariants
- uploaded-file QA report
- unit tests and CI build
- full architecture / decision / data-integrity documentation
- responsive/accessibility polish
- training-history JSON export
- in-app DATA INTEGRITY VERIFIED panel
- final full MR execution runtime QA

Screenshots:
- `screenshots/phase4-final.png`
- `screenshots/phase4-final-data.png`

Final Phase 4 runtime result:
- KLineChart V10: loaded
- 1-second MTX replay: loaded
- five MR decisions completed
- final branch: EXECUTE LONG
- Extreme: 44797 @ 09:19:55
- LVN: 44884
- Entry: 44883 @ 09:20:33
- source rows displayed: 2,115,188
- data integrity status: VERIFIED
- runtime errors: 0
- unit tests / production build / KLineChart pin check: passed

## Acceptance rule for every phase
A phase is not accepted just because a screenshot exists. It must:
1. run with the official KLineChart V10 bundle,
2. use real supplied MTX-derived fixture data,
3. produce a Playwright screenshot,
4. have zero browser runtime errors,
5. preserve the hide-future rules,
6. pass the relevant automated checks.
