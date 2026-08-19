# Fabio Decision Gym V2 — Final QA

## Release target

`main` already contains the V2 application. This report PR exists only to run a final GitHub Actions validation against the completed product and then preserve the acceptance evidence in `main`.

## Browser runtime acceptance

Source: `screenshots/decision-gym-v2-final-3.json`

- page title: `Fabio Decision Gym V2`
- Dashboard Skill cards: **12**
- main navigation pages: **11**
- Decision Node cards: **18**
- Practice node exercised: **MR-02 Clear Reclaim**
- KLineChart canvases in Practice: **10**
- YES / NO controls: **2**
- interactive answer: **correct**
- GitHub runner Local API state: expected offline (Windows Parquet server is optional/local)
- unexpected browser/runtime errors: **0**

Screenshots:

- `screenshots/decision-gym-v2-final-3-dashboard.png`
- `screenshots/decision-gym-v2-final-3-nodes.png`
- `screenshots/decision-gym-v2-final-3-practice.png`

## Product acceptance

### Decision training

- Stable Decision Node Registry
- MR / BO / WAIT tree
- Node counts and YES / NO distribution
- exact Event ID locator
- Pattern Gallery
- single-node deliberate practice
- confidence score and reaction time
- hide-future answering
- full Replay / reveal structure / reveal trade
- exam mode
- mistake review
- high-confidence mistakes
- spaced repetition
- JSON history export
- Human-vs-Machine research view

### Multi-year local data

Default local root:

```text
D:\tools\traderChatV1\data\parquet\Future
```

The Local API discovers `MTX_*.parquet`, creates a SQLite Event Store and exposes Node/Case/Replay queries. Raw Parquet files stay local and are not committed to GitHub.

### Contract correctness

Production scanning imports `server.causal_engine`.

- `strict` / `front_month`: causal calendar front contract
- third-Wednesday expiry logic
- one-contract-per-profile
- roll blackout before strategy events resume
- `dominant_volume`: explicitly non-causal diagnostic mode only

### Tick-order correctness

- `_seq` = physical Parquet row order
- no raw Tick `sort_values()`
- same-second prints preserve physical order
- filters are masks
- `side` remains Tick Direction proxy only; never called true Bid/Ask aggression

### Scanner scope

The event engine automatically detects and indexes:

- Context / Previous Value
- Auction Attempt and near-miss negative examples
- Extreme
- Rejection / Clear Reclaim
- Acceptance / Displacement
- Causal Reclaim Leg / Impulse Leg
- Valley LVN
- First Pullback
- BO Response
- MR / BO Entry candidates
- WAIT / NO_TRADE

Raw detector features and binary Node outcomes are both stored.

## Evidence boundary

The platform is a subjective trading decision-training and research environment, not a guarantee of profitability or an automatic order-routing system. True Footprint / Delta / CVD / absorption research still requires Bid/Ask-classified trades, TBBO or MBO.

## CI acceptance criteria

This PR is accepted only if GitHub Actions passes:

1. `npm install`
2. `npm test`
3. deterministic static `npm run build`
4. Python syntax compilation for causal contract/scanner/API modules
5. Decision Gym V2 file checks
6. vendored/pinned KLineChart **10.0.2** verification
