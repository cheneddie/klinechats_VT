# Fabio Decision Gym V2

以 **KLineChart 10.0.2** 製作的 MTX 主觀交易刻意練習平台，把 Fabio-style Auction Market / Volume Profile 思路拆成可定位、可統計、可大量反覆練習的 YES / NO 微技能。

> 最終目標不是「看一筆完整交易」，而是可以指定 **某一個二元節點**（例如 Clear Reclaim、Causal Leg、LVN、Acceptance），立刻看到該節點有多少案例、YES/NO 各多少、精準定位到原始日期與事件，並連續練 20 / 50 / 100 題建立圖像辨識經驗。

## V2 主要頁面

1. **Dashboard** — Skill Map、弱點、待複習、今日建議
2. **二元決策樹** — MR / BO / WAIT 可點擊決策地圖
3. **Decision Node Library** — 每個 Node 的總數、YES/NO、已練/未練、正確率
4. **Practice Lab** — 單一 Node 大量刻意練習
5. **Full Replay** — 精準定位案例，Hide Future / Reveal Structure / Reveal Trade
6. **Exam** — 不立即揭露答案的混合市場考試
7. **Review** — 錯題、高信心錯題、Spaced Repetition
8. **Case Browser** — 年份 / 策略 / Node / YES-NO / 方向 / 難度篩選與定位
9. **Research** — Node Distribution、Human vs Machine、Evidence Boundary
10. **Settings** — Training Parameters 與 Strategy Version 分離
11. **Data / Scanner** — 多年份 MTX Parquet、Contract Engine、Event Store 掃描

## KLineChart

- 版本固定：**10.0.2**
- 原始 vendor：`public/vendor/klinecharts-10.0.2.min.js`
- KLineChart 只負責視覺化；市場結構標籤來自 Scanner / Event Store
- 2025、2024 等本地案例若沒有內建 fixture，圖表會透過 Local API 依 Event `_seq` 定位原 Parquet，動態讀附近 Tick 並聚合 1 秒 Bars

## 本地多年資料

預設目錄：

```text
D:\tools\traderChatV1\data\parquet\Future
```

可放：

```text
MTX_2022.parquet
MTX_2023.parquet
MTX_2024.parquet
MTX_2025.parquet
MTX_2026.parquet
...
```

**原始 Parquet 不需要、也不應上傳 GitHub。**

### 啟動 Local Data API

```bash
python -m pip install -r requirements-server.txt
python -m server.fabio_api
```

API 預設：

```text
http://127.0.0.1:8765/api
```

前端會自動偵測；API Online 後由 Demo fixture 切換為本機 Event Store。

若資料不在預設路徑，可設定：

```powershell
$env:FABIO_DATA_ROOT="D:\tools\traderChatV1\data\parquet\Future"
python -m server.fabio_api
```

## 啟動網站

```bash
npm install
npm run dev
```

開啟 Vite 顯示的本機網址即可。

### Test / Build

```bash
npm test
npm run build
```

## Multi-year Scanner

前端 `Data / Scanner` 頁可以送出掃描任務，也可直接呼叫 API。

Scanner 流程：

```text
MTX_*.parquet
  -> Dataset Catalog / QA
  -> daily contract volume
  -> Contract Engine
  -> active outright contract only
  -> Previous Value
  -> Auction Attempt
  -> Rejection / Acceptance / WAIT
  -> Reclaim Leg / Impulse Leg
  -> Leg Volume Profile
  -> LVN
  -> Pullback / Response
  -> Entry candidate
  -> SQLite Event Store
  -> node_instances index
```

### Contract Engine

全年 Parquet 可能同一天同時包含多個 `YYYYMM` 合約。**不同合約不能混在同一個 Profile。**

支援：

- `strict` — 建議研究/訓練使用；換月後預設 1 日 blackout
- `dominant_volume`
- `front_month`

價差 / combo 只要不是單純 `^\d{6}$` outright expiry 就不進 Contract Engine。

## Data Integrity：不可破壞的規則

1. 物理檔案列順序先建立 `_seq`。
2. **Raw Tick 不重新 sort。**
3. 同一秒內的成交順序永遠使用 Parquet 原始列順序。
4. 篩選 product / contract / spread 只能用 mask 保留原順序。
5. `side` 只視為 Tick Direction proxy，**不是 Bid/Ask aggressor side**。
6. Event Store 保存 raw features + node decisions，而不是只保存最後 `YES/NO`。

## Decision Node Registry

所有頁面共用 `src/v2/registry.js` 的固定 Node ID，避免 Replay、Exam、Research 各自定義不同規則。

### MR · 回家

```text
CTX_VALUE
AUC_ATTEMPT
MR_REJECTION
MR_CLEAR_RECLAIM
MR_RECLAIM_LEG
MR_LVN
MR_PULLBACK
MR_ENTRY
```

### BO · 搬家

```text
CTX_VALUE
AUC_ATTEMPT
MR_REJECTION = NO
BO_ACCEPTANCE
BO_DISPLACEMENT
BO_IMPULSE_LEG
BO_LVN
BO_PULLBACK
BO_RESPONSE
BO_ENTRY
```

### NO TRADE

```text
WAIT_AMBIGUOUS
NO_TRADE
```

`WAIT` 是正式市場狀態，不是「不知道答案」。

## Node Library / Case Locator

SQLite `node_instances` 對 `(event_id, node_id)` 建索引，因此可以直接查：

```text
MR_CLEAR_RECLAIM
Year = 2025
Answer = YES
Direction = short
Difficulty = 3
```

再從結果點「定位」，KLineChart 直接跳到該事件。

Node 數量使用 `/api/nodes/stats` 從 SQLite 全庫統計，不受前端只載入前幾千筆案例的限制。

## Practice Lab

每次只練一個決策問題：

- YES / NO
- 信心 1–5
- 反應時間
- Hide Future
- 回答後才 Reveal Machine Structure
- Y / N 快捷鍵

錯題會進 Spaced Repetition：

```text
10分鐘 → 1天 → 3天 → 7天 → 30天
```

高信心（4–5）錯題另外分類，因為它比較像 Mental Model 錯誤，而不是單純不確定。

## Strategy Versioning

範例：

- `config/strategies/MR_BROAD_V3.json`
- `config/strategies/BO_RETEST_V2.json`

Strategy Parameters 與 Training Parameters 分開。

MR Broad V3 目前只是已凍結的研究/訓練 baseline，不代表市場永恆參數；Breakout Retest 的 OOS 證據目前比 MR 弱，因此獨立版本管理。

## Local API

主要 endpoints：

```text
GET  /api/health
GET  /api/datasets
GET  /api/nodes/stats
GET  /api/cases
GET  /api/cases/{event_id}
GET  /api/replay/{event_id}
GET  /api/research/summary
GET  /api/scan/status
POST /api/scan
```

## Architecture

```text
Raw MTX Tick
      ↓
Contract / Session Engine
      ↓
Market State Detector
      ↓
Raw Features + Event Store
      ↓
Decision Node Registry
      ├── Node Library
      ├── Practice Lab
      ├── Case Browser
      ├── Exam
      ├── Research
      └── KLineChart Replay
```

同一套 Detector 與 Event Store 未來也可以接 Live Monitor，避免「回測一套、Replay 一套、實盤又一套」。

## 主要檔案

```text
src/v2/registry.js       Stable Decision Node Registry
src/v2/store.js          Cases / telemetry / spaced repetition / API lazy loading
src/v2/chart.js          KLineChart + Local Replay API
src/v2/app.js            11-page Decision Gym SPA
src/v2/lazy.js           node-specific lazy hydration
src/v2/styles.css        UI / RWD
server/scanner.py        multi-year Contract + Auction/Event Scanner
server/fabio_api.py      local FastAPI / SQLite Event Store
config/strategies/       versioned strategy parameters
```

完整設計：[`docs/DECISION_GYM_V2.md`](docs/DECISION_GYM_V2.md)

## Evidence boundary

這是交易**訓練/研究平台**，不是保證獲利的自動下單系統。

規劃與驗收條件：[`docs/DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md)

最終 QA：[`reports/FINAL_QA.md`](reports/FINAL_QA.md)

## Branch / PR
完整開發版：`fabio-replay-v1`

PR 保持獨立審查，不會在未經確認的情況下自動合併到 `main`。

目前 MTX `side` 已知是 Tick Direction proxy，不是真正 Bid/Ask aggressor，因此真正 Fabio Footprint / Delta / CVD / Absorption / Aggression layer 仍需要 Bid/Ask classified trades、TBBO 或 MBO。
