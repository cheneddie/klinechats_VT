# Fabio Decision Gym V2

## Product goal

Turn subjective Fabio-style Auction Market reading into a measurable training system. The platform must support:

- node-by-node deliberate practice,
- a list and exact locator for every binary decision point,
- large batches of the same decision node,
- full hide-future replay,
- exams, mistake review and spaced repetition,
- research statistics and strategy versioning,
- local multi-year MTX Parquet scanning without uploading raw Tick files.

## Information architecture

1. Dashboard
2. Binary Decision Tree
3. Decision Node Library
4. Practice Lab
5. Full Replay
6. Exam
7. Review / Spaced Repetition
8. Case Browser
9. Research
10. Settings
11. Data / Scanner

## Core separation

```text
Raw Tick
  -> Contract / Session Engine
  -> Market State Detector
  -> Raw Feature + Event Store
  -> Strategy Version
  -> Backtest / Research
  -> Replay / Human Training
```

The Detector describes what the market did. It does **not** decide profitability. Strategy versions consume detector features and produce qualification / execution decisions.

## Node Registry

All UI, training, exams and research use the same stable Node IDs in `src/v2/registry.js`.

Core MR nodes:

- `AUC_ATTEMPT`
- `MR_REJECTION`
- `MR_CLEAR_RECLAIM`
- `MR_RECLAIM_LEG`
- `MR_LVN`
- `MR_PULLBACK`
- `MR_ENTRY`

Core BO nodes:

- `AUC_ATTEMPT`
- `MR_REJECTION` = NO
- `BO_ACCEPTANCE`
- `BO_DISPLACEMENT`
- `BO_IMPULSE_LEG`
- `BO_LVN`
- `BO_PULLBACK`
- `BO_RESPONSE`
- `BO_ENTRY`

`WAIT_AMBIGUOUS` and `NO_TRADE` are first-class labels. The dataset must not teach that every chart contains a trade.

## Event Store

The Local API stores events in SQLite. Each event contains:

- date / contract / direction / strategy,
- exact source `_seq` locators,
- attempt / extreme / reclaim / turn / LVN / entry timestamps,
- Previous VAH / VAL / POC / Value Width,
- raw detector features,
- node outcomes,
- difficulty and result.

`node_instances` stores one row per `(event_id, node_id)`, allowing instant queries such as:

> Show all `MR_CLEAR_RECLAIM = YES` cases from 2025, short direction, difficulty 3.

## Multi-year local data

Default root:

```text
D:\tools\traderChatV1\data\parquet\Future
```

Files are discovered as:

```text
MTX_*.parquet
```

Run:

```bash
python -m pip install -r requirements-server.txt
python -m server.fabio_api
```

Then open the web app. It automatically switches from Demo fixtures to `http://127.0.0.1:8765/api`.

## Contract Engine

Annual Parquet files can contain several `YYYYMM` contracts on the same trading day. They must never be mixed into one Profile.

Supported selection modes:

- `dominant_volume`
- `front_month`
- `strict`

`strict` is recommended for research/training. When the active contract changes, the default one-day roll blackout prevents Previous Value from crossing contracts.

## Tick-order invariant

The physical row order is part of the market data.

- `_seq` is assigned from physical file order.
- The scanner never calls `sort_values()` on raw Tick rows.
- same-second prints keep their file order.
- filtering uses masks only.
- `side` is Tick Direction proxy only; it is not Bid/Ask aggressor side.

## Hide-future rule

A learner may only see bars available at that node's decision timestamp. Machine overlays and final outcome are hidden until answer/reveal.

## Training telemetry

Every answer stores:

- event ID,
- node ID,
- YES / NO,
- correctness,
- response time,
- confidence 1–5,
- training mode,
- timestamp.

The Dashboard derives node accuracy, reaction time and weakest skills from this history.

## Spaced repetition

Wrong answers are re-scheduled at approximately:

- 10 minutes
- 1 day
- 3 days
- 7 days
- 30 days

High-confidence mistakes are surfaced separately because they indicate a likely mental-model error rather than uncertainty.

## Evidence boundary

This is a decision-training and research platform, not an automatic live trading recommendation system. The uploaded MTX `side` field is not true aggressor classification. True Delta / CVD / Footprint validation requires Bid/Ask-classified trades, TBBO or MBO data.
