# Fabio Decision Gym V2 — Final Release QA

## Release status

**PASS — V2 product, scanner foundation, deliberate-practice workflow and browser runtime have passed the current release gates on `main`.**

Final screenshot phase: `decision-gym-v2-final-5`

Final screenshot commit: `2f63f5eb66a68a14904bd7e9a308237cf7f04e88`

The release is built around KLineChart **10.0.2** and a local multi-year MTX Event Store architecture.

## Product acceptance

The browser acceptance suite opened the actual product and validated these areas:

1. Dashboard
2. Binary Decision Tree
3. Decision Node Library
4. Decision Node Detail / Pattern Wall
5. Single-node Practice Lab
6. Full Replay
7. Exam
8. Mistake / Spaced-Repetition Review
9. Case Browser
10. Research
11. Settings
12. Data / Scanner

Final browser report:

- dashboard skill cards: **12**
- main navigation entries: **11**
- Decision Node cards: **18**
- Pattern Wall filters: **3** (`ALL / YES / NO`)
- Pattern Wall sizes: **3** (`24 / 48 / 96`)
- one-click drill sizes: **3** (`20 / 50 / 100`)
- practice KLineChart canvases: **10**
- YES / NO answer controls: **2**
- browser runtime errors: **0**

The GitHub runner has no access to the user's Windows Local Data API, so one `127.0.0.1:8765` offline probe is expected and is treated as an explicit offline/demo state, not a runtime failure.

## Deliberate-practice acceptance

### Decision Node Registry

All training surfaces share stable Node IDs from `src/v2/registry.js`. This prevents Replay, Exam, Research and Practice from silently using different semantic definitions.

Core skills include:

- Auction Attempt
- Extreme
- Rejection
- Clear Reclaim
- Reclaim Leg
- MR LVN
- MR Pullback
- MR Entry
- Acceptance
- Displacement
- Impulse Leg
- BO LVN
- BO Pullback
- Response
- BO Entry
- WAIT / NO TRADE

### Node Library

Each Node can expose:

- total case count
- YES count
- NO count
- trained / untrained count
- personal accuracy
- average reaction time
- exact event locator
- same-node practice entry

When the Local API is online, authoritative totals come from SQLite `/api/nodes/stats`, not from the browser's initial case sample.

### Pattern Lab

Node detail includes:

- ALL / YES / NO filtering
- 24 / 48 / 96-image Pattern Wall
- shuffle
- 20 / 50 / 100-question one-click drills
- click-to-Replay exact event
- two-case side-by-side Compare mode when at least two cases are available

The bundled demo fixture contains only one Clear Reclaim case, so final headless QA correctly reports one tile and does not open Compare. Multi-year Event Store data is the intended source for high-volume galleries.

### Training telemetry

Stored locally per decision:

- Node
- answer
- correct / incorrect
- reaction time
- confidence 1–5
- mode
- case ID

Wrong answers create spaced-repetition reviews:

`10 min -> 1 day -> 3 days -> 7 days -> 30 days`

High-confidence errors are separately visible because they indicate a likely mental-model error rather than simple uncertainty.

## Scanner / data architecture acceptance

### Production path

```text
MTX_*.parquet
  -> physical _seq
  -> outright/product filter
  -> causal Contract Engine
  -> trading-day session
  -> Previous Value
  -> Auction State Machine
  -> raw structural features
  -> MR / BO / WAIT nodes
  -> SQLite Event Store
  -> node_instances index
  -> Local API
  -> Node Library / Practice / Replay
```

### Data-order invariant

Raw Tick rows are never sorted by datetime, price or side.

The synthetic Parquet E2E test deliberately writes multiple different prices inside the same second and across row-group boundaries. It confirms that one-second Replay bars preserve:

- physical first trade as Open
- physical last trade as Close
- original `_seq` range
- same-second source order

### Event Store E2E

The E2E suite also writes a synthetic event and verifies that separate binary decisions are persisted and indexed in `node_instances` for direct Node queries.

## Contract Engine acceptance

Production imports `server.causal_engine`, which binds the scanner to the causal policy in `server/contracts.py`.

In `strict` mode:

- the current monthly contract remains front through the third-Wednesday expiry date
- the following trading date rolls to the next valid monthly outright contract
- completed-day volume rank is not used
- if a valid forward contract is unavailable after expiry, that date is skipped rather than falling back to an expired contract

`dominant_volume` remains available only as an explicitly non-causal research diagnostic.

### Real supplied 2025 validation

The supplied `MTX_2025.parquet` was inspected in the development environment using an order-preserving reader.

Results:

- raw physical rows: **39,416,621**
- day-session trading dates: **236**
- day-session dates containing multiple monthly outright contracts: **0**
- strict calendar-front selector vs actual day-session contract: **236 / 236 matches**
- mismatches: **0**
- observed contract switches: **12**

See `reports/MTX_2025_CONTRACT_QA.md`.

## Automated release gates

The final QA workflow passed:

- npm install
- **18 JavaScript tests**
- deterministic production build
- Python server/scanner compilation
- causal MTX contract-policy tests
- synthetic Parquet Replay E2E
- SQLite Event Store E2E
- KLineChart **10.0.2** pin/vendor verification
- Playwright Chromium runtime QA

A temporary QA-only pull request was used to expose inspectable workflow logs. It was closed without merge after both CI and Stage Screenshot workflows passed.

## Windows multi-year operation

Default data root:

```text
D:\tools\traderChatV1\data\parquet\Future
```

Use:

```powershell
.\scripts\start-decision-gym.ps1
```

or follow `docs/WINDOWS_MULTI_YEAR_SETUP.md`.

Recommended first production scan is **2025 only**. Confirm Data QA / Node counts / Replay locators first, then add the remaining years one at a time.

## Evidence boundary

This release establishes that the **software architecture and current structural detector pipeline are executable and internally consistent**. It does not claim that every automatically generated event is a perfect human/Fabio label.

Important boundaries:

1. The full Windows directory containing every historical year is not mounted in the GitHub runner or this sandbox, so a complete scan of all user-local years must run on the user's Windows machine.
2. `MTX_2025.parquet` was used for real contract-selection validation, but the complete V2 Event Store for every 2025 Auction/MR/BO node has not been materialized inside GitHub because raw Parquet stays local.
3. `side` remains a Tick Direction proxy, not true Bid/Ask aggressor classification.
4. True Footprint / Delta / CVD / queue analysis requires Bid/Ask-classified trades, TBBO or MBO.
5. Breakout-Retest OOS evidence is still materially smaller than Mean-Reversion evidence; the platform keeps MR and BO strategy versions separate for this reason.
6. Machine Node labels are training/research baselines. Human-vs-machine disagreement should be stored and studied rather than automatically treated as human error.

## Release decision

**Fabio Decision Gym V2 is ready for local multi-year data population and real deliberate-practice use.**

The next meaningful step is no longer another UI rewrite. It is to run the Local Scanner on `MTX_2025.parquet`, inspect the resulting Node distributions and random samples, calibrate machine-label quality, then add the other historical years progressively.
