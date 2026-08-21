# Fabio Decision Gym V4

以 **KLineChart 10.0.2** 製作的 MTX 主觀交易刻意練習與策略研究平台，把 Fabio-style Auction Market / Volume Profile 思路拆成可定位、可統計、可大量反覆練習的 YES / NO 微技能。

> 最終目標不是「看一筆完整交易」，而是可以指定 **某一個二元節點**（例如 Clear Reclaim、Causal Leg、LVN、Acceptance），立刻看到該節點有多少案例、YES/NO 各多少、精準定位到原始日期與事件，並連續練 20 / 50 / 100 題建立圖像辨識經驗；研究端則必須反向驗證每個 Gate 是否真的保留右尾、排除左尾，而不是把主觀規則直接當優勢。

## V4 目前研究狀態

研究分支：`fabio-decision-gym-v4`  
PR：`#21`  
狀態：**Draft / research only，未經明確批准不得 merge `main`。**

V4 現在將兩種 evidence 分開：

```text
Relaxed Terminal Opportunity
    → Reverse Node Audit / Gate research

Actual Strict ENTRY physical _seq
    → strategy performance / right tail / cost stress / production gate
```

尤其 BO 的研究 terminal anchor 可以在 Pullback，但真正 strict entry 必須等 `BO_RESPONSE` 因果確認；兩者不可共用同一筆績效。

### 2024–2026 驗證治理

目前固定研究角色：

```text
2025 = Discovery
2024 = Validation
2026 = Final Holdout（目前來源覆蓋至 2026-08-14）
```

設定檔：`config/research/v4_validation_plan.json`

Runner 預設會阻止把 Final Holdout 和 development years 偷偷 pooled 在一起。若在 production candidate freeze 後明確揭露 holdout，才可使用 `--allow-holdout-reveal` 產生事後描述性 all-years report；該 pooled report 不得再拿來調參。

### Canonical Diagnostic Runner

```bash
python tools/run_v4_diagnostic.py \
  --root <PARQUET_ROOT> \
  --db <FABIO_EVENT_DB> \
  --year 2025 \
  --out <RESULT_DIR>
```

正式流程：

```text
clean selected-year derived state
→ source-order / source-funnel QA
→ causal contract-selection audit
→ V4 release scanner
→ physical Event Sanity Gate
→ relaxed physical outcomes
→ Reverse Node Audit
→ Sequential Gate Contribution
→ Ablation
→ Management / Capture
→ actual strict-entry physical outcomes
→ right tail
→ Multi-Year Edge Map
→ monthly / direction / intraday / structure strata
→ 0/1/2/3pt execution-cost stress
→ Production Gate
```

Canonical outputs 包含：

- `scan_summary.json`
- `event_sanity.json`
- `reverse_audit.json` / `.csv`
- `sequential_gate_contribution.json`
- `ablation.json`
- `management_capture.json`
- `strict_trade_summary.json`
- `right_tail.json`
- `multi_year_edge_map.json`
- `stratified_edge.json`
- `execution_stress.json`
- `production_gate.json`
- `final_summary.json`

詳細狀態：`reports/V4_MULTIYEAR_EXECUTION_STATUS_2026-08-21.md`

## 主要頁面

1. **Dashboard** — Skill Map、弱點、待複習、今日建議
2. **二元決策樹** — MR / BO / WAIT 可點擊決策地圖
3. **Decision Node Library** — 每個 Node 的總數、YES/NO、已練/未練、正確率
4. **Practice Lab** — 單一 Node 大量刻意練習
5. **Full Replay** — 精準定位案例，Hide Future / Reveal Structure / Reveal Trade
6. **Exam** — 不立即揭露答案的混合市場考試
7. **Review** — 錯題、高信心錯題、Spaced Repetition
8. **Case Browser** — 年份 / 策略 / Node / YES-NO / 方向 / 難度篩選與定位
9. **Research** — Node Distribution、Reverse Audit、Ablation、Management、Evidence Boundary
10. **Settings** — Training Parameters 與 Strategy Version 分離
11. **Data / Scanner** — 多年份 MTX Parquet、Contract Engine、Event Store 掃描

## KLineChart

- 版本固定：**10.0.2**
- 原始 vendor：`public/vendor/klinecharts-10.0.2.min.js`
- KLineChart 只負責視覺化；市場結構標籤來自 Scanner / Event Store
- 本地案例若沒有內建 fixture，圖表會透過 Local API 依 Event `_seq` 定位原 Parquet，動態讀附近 Tick 並聚合指定 timeframe

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

### 啟動 V4 Local Data API

```bash
python -m pip install -r requirements-server.txt
python -m server.fabio_api_v4
```

API 預設：

```text
http://127.0.0.1:8765/api
```

若資料不在預設路徑，可設定：

```powershell
$env:FABIO_DATA_ROOT="D:\tools\traderChatV1\data\parquet\Future"
$env:FABIO_EVENT_DB="D:\tools\traderChatV1\fabio-events.sqlite3"
python -m server.fabio_api_v4
```

`FABIO_EVENT_DB` 可指向專案旁的資料檔；原始 Parquet 仍是 source of truth，Events/Outcomes 可重建，`training_attempts` 則屬人工資料，需備份。

## 啟動網站

```bash
npm install
npm run dev
```

### Test / Build

```bash
npm test
npm run build
```

## Multi-year Scanner

Scanner 流程：

```text
MTX_*.parquet
  → physical `_seq` before filtering
  → Dataset Catalog / Source-order QA
  → MTX + outright-only filter (preserve row order)
  → causal Contract Engine
  → active outright contract only
  → Previous Value
  → Auction Attempt
  → MR / BO research branches
  → Reclaim / Impulse Leg
  → LVN
  → Pullback / Response
  → relaxed terminal opportunity + strict entry state
  → SQLite Event Store / node_instances
```

### Contract Engine

全年 Parquet 可能同一天同時包含多個 `YYYYMM` 合約。**不同合約不能混在同一個 Profile 或交易 path。**

研究預設：

- `strict` — causal calendar front-month；換月後預設 1 日 blackout
- `dominant_volume` — 研究比較用，不作為正式 causal baseline
- `front_month` — legacy option

價差 / combo 只要不是單純 `^\d{6}$` outright expiry 就不進 Contract Engine。

Scanner 額外持久化：

- `dataset_integrity` — source/MTX/outright/spread removed/contracts/source-order QA
- `contract_selection_audit` — 每日 candidate contracts、raw volume、`volume/2`、selected contract、roll、causal、reason

## Data Integrity：不可破壞的規則

1. 物理檔案列順序先建立 `_seq`。
2. **Raw Tick 不重新 sort。**
3. 同一秒內的成交順序永遠使用 Parquet 原始列順序。
4. 篩選 product / contract / spread 只能用 mask 保留原順序。
5. MTX 只保留 outright `^\d{6}$`；spread/combo 排除。
6. Vendor `volume` 為雙邊量；研究解讀的 normalized volume 為 `volume / 2`。
7. `side` 只視為 Tick Direction proxy，**不是 Bid/Ask aggressor side**。
8. 不同 expiry 不串成同一交易 path。
9. Event Store 保存 raw features + node decisions，而不是只保存最後 `YES/NO`。

## Decision Node Registry

所有頁面共用固定 Node ID，避免 Replay、Exam、Research 各自定義不同規則。

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
BO_DISPLACEMENT
BO_ACCEPTANCE
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

V4 Training History 可寫入 SQLite `training_attempts`，避免只依賴瀏覽器 LocalStorage。

## Strategy / Research Versioning

策略設定：

- `config/strategies/MR_BROAD_V3.json`
- `config/strategies/BO_RETEST_V2.json`

研究結果同時記錄：

- scanner version
- strategy versions
- config hash
- visual schema
- contract policy
- audit/outcome/management versions
- git commit
- research run ID

Strategy Parameters 與 Training Parameters 分開。

## V4 Research APIs

```text
GET  /api/v4/health
GET  /api/v4/replay/{event_id}
GET  /api/v4/node-meta/{event_id}
GET  /api/v4/training-replay/{event_id}
POST /api/v4/audit/run
GET  /api/v4/audit/latest
GET  /api/v4/audit/ablation
GET  /api/v4/research/provenance
POST /api/v4/sanity/run
GET  /api/v4/sanity/latest
GET  /api/v4/research/management-capture
POST /api/v4/research/strict-outcomes/run
GET  /api/v4/research/strict-summary
GET  /api/v4/research/right-tail
GET  /api/v4/research/multi-year-edge
GET  /api/v4/research/stratified-edge
GET  /api/v4/research/execution-stress
GET  /api/v4/research/production-gate
POST /api/v4/training/attempt
GET  /api/v4/training/history
```

## Architecture

```text
Raw MTX Tick
      ↓
Physical _seq / Data Integrity
      ↓
Causal Contract / Session Engine
      ↓
Auction / Market Structure Detector
      ↓
Raw Features + Event Store
      ↓
Decision Node Registry
      ├── Node Library / Practice / Replay
      ├── Relaxed Opportunity Reverse Audit
      └── Strict Entry Outcome / Production Gate
```

同一套 causal detector 與 Event Store 未來也可以接 Live Monitor，避免「回測一套、Replay 一套、實盤又一套」。

## 主要 V4 檔案

```text
server/v4_final_engine.py          relaxed research universe / causal nodes
server/v4_release_engine.py        strict BO entry after Response
server/v4_audit_final.py           physical opportunity outcomes / reverse audit / ablation
server/v4_research_release.py      research governance / Event Sanity / sequential contribution
server/v4_multiyear.py             strict outcomes / right tail / multi-year edge / production gate
server/v4_stratified.py            month / direction / intraday / structure strata
server/v4_execution_stress.py      strict-entry cost / concentration stress
server/v4_replay_final.py          physical multi-day / multi-timeframe replay
server/fabio_api_v4.py             V4 FastAPI entrypoint
tools/run_v4_diagnostic.py         canonical governed diagnostic runner
config/research/v4_validation_plan.json
```

## Evidence boundary

這是交易**訓練/研究平台**，不是保證獲利的自動下單系統。

Synthetic QA 只能證明軟體語意；不能當策略績效。Single-Year Diagnostic 也不能自動叫 OOS。即使 2024/2025/2026 全部計算完成，Production Gate 仍需成本、延遲、ATR、Drawdown、Concentration 與 Historical ↔ Live Causal Parity 等條件。

目前 MTX `side` 已知是 Tick Direction proxy，不是真正 Bid/Ask aggressor，因此真正 Fabio Footprint / Delta / CVD / Absorption / Aggression layer 仍需要 Bid/Ask classified trades、TBBO 或 MBO。

## Branch / PR

- branch: `fabio-decision-gym-v4`
- PR: `#21`
- policy: 保持 Draft / 獨立審查；未經明確確認不 merge `main`。
