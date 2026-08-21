# Fabio Decision Gym V5 Architecture

V5 extends the validated V4 scanner/replay stack; it does not replace it.

```text
Raw Parquet -> V4 shared causal scanner/state engine -> immutable V5 research snapshot
  -> Event Sanity Gate -> physical outcomes -> reverse/sequential/ablation
  -> Evidence Registry -> Training Truth Set -> Pattern/Compare/Tree drills
  -> persistent mastery -> never-seen Certification -> Production/Live gates
```

## Storage

- `FABIO_V5_EVENT_DB` (default `~/.fabio-decision-gym/fabio-events.sqlite3`): rebuildable research data.
- `FABIO_V5_TRAINING_DB` (default `~/.fabio-decision-gym/fabio-training.sqlite3`): human attempts, labels, reviews, mastery, mistakes, spaced repetition, certification.

## API server

Run:

```bash
python -m server.fabio_api_v5
```

V5 is installed on the same FastAPI app as V4, so existing V4 replay/research endpoints remain available.

## Main V5 API groups

- Data: `/api/v5/data/integrity`, `/api/v5/contracts`
- Events/replay: `/api/v5/events`, `/api/v5/replay/{event_id}`, `/api/v5/training/replay/{event_id}`
- Research: `/api/v5/research/scan|sanity|outcomes|reverse-audit|sequential|ablation|evidence|freeze`
- Training: `/api/v5/training/nodes|build|cases|matched-pairs|attempt|tree-attempt|mastery|mistakes|review`
- Certification: `/api/v5/certification/start|answer|{id}/next|{id}/finish`

## Frontend

Open `v5.html`. The 8 product areas are Research Dashboard, Node Explorer, Pattern Wall, Compare Lab, Single Node Drill, Decision Tree Drill, Exam / Certification, and My Performance.

The chart stack remains **KLineChart 10.0.2 + PixiJS 8.19.0**. Training replay uses server-side physical-tick cutoff before timeframe aggregation.
