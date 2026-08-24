# MTX 極端急跌反轉策略｜真實重跑與 Forward-OOS 凍結報告

**研究狀態：FROZEN FORWARD-OOS CANDIDATE — NOT LIVE APPROVED**  
**凍結日期：2026-08-22**  
**原始資料截止：2026-08-14 13:44:59（交易所本地時間）**  
**Frozen config SHA-256：`cf8b4555b3579be81ba44c27ecd7ddc1f8f5a0bcbfd0c7a5719bdc7e12cdbf16`**

## 1. 真實重跑與 QA

本次完全從三個原始 Parquet 重新解碼，保留 physical row order；`expiry` 逐列只保留 `^\d{6}$` 月契約；同秒 open/close 依真實 physical first/last print 建立。

- Raw rows：**126,438,254**
- MTX outright rows：**126,438,076**
- spread/combo 排除：**178**
- contracts：**32（202401–202608）**

Canonical baseline checksum：

- **3,655 trades**
- **Gross +12,414 points**
- **Net@2 +5,104 points**
- **PF@2 1.0590535694**
- 年度 N：2024 **1,189** / 2025 **1,057** / 2026 **1,409**
- 202506 threshold：**-58 points**

以上與既有 canonical research 完全一致。

## 2. Frozen Candidate 規則

- MTX outright only，Long only，max 1 MTX
- Signal-time gate：**09:00:00–10:30:00**、**20:30:00–22:30:00**
- Causal High Vol：同類 session 的前 14 個 completed session range 平均，對比此前 61 個同類 `prior14` 值的 80th percentile
- 30 秒 price change：`close[t] - close[t-30]`
- threshold：前 3 個 completed contract 的 signal distribution **Q0.05%**
- true downward crossing：`sig[t] <= threshold && sig[t-1] > threshold`
- signal second 必須完成；再 +1s latency，因此 earliest fill = `t+2`
- 第一個之後可成交 print 進場；固定持有 300 秒；同 session 第一個可成交 print 出場
- 主報告 round-trip friction = **2 points**
- **不加入 fixed stop**

HighVol operational definition 可精確重現原本 **09:00–10:30 × HighVol = 740 trades / Net@2 +6,021 / E +8.136486 / PF 1.320453**。

## 3. 真正 entry-gated candidate 結果

- **N = 1,112**
- **Gross = +10,650**
- **Net@2 = +8,426**
- **Expectancy = +7.5773 points/trade**
- **PF = 1.30649**
- **Win rate = 54.68%**
- Avg win = **59.08**；Avg loss = **-56.22**
- Median trade = **+7 points**
- Max win = **+449**；Max loss = **-589**
- Max drawdown = **-1,235 points**
- Max consecutive losses = **9**

年度：

| year | N | Net | E | PF | Win | MaxDD |
|---:|---:|---:|---:|---:|---:|---:|
| 2024 | 448 | 1118 | 2.4955 | 1.1315 | 0.5156 | -1171 |
| 2025 | 198 | 1365 | 6.8939 | 1.3352 | 0.5455 | -1235 |
| 2026 | 466 | 5943 | 12.7532 | 1.3984 | 0.5773 | -1176 |

2024+2025 合計仍為 **+2,483 points / E +3.844 / PF 1.197**。

日／夜窗口：

- DAY 09:00–10:30：746 / **+6,247** / E **8.374** / PF **1.324**
- NIGHT 20:30–22:30：366 / **+2,179** / E **5.954** / PF **1.266**

## 4. 成本壓力

| Cost | Net | E | PF | MaxDD |
|---:|---:|---:|---:|---:|
| 0 | 10650 | 9.5773 | 1.4016 | -1183 |
| 1 | 9538 | 8.5773 | 1.3532 | -1209 |
| 2 | 8426 | 7.5773 | 1.3065 | -1235 |
| 3 | 7314 | 6.5773 | 1.2613 | -1308 |
| 5 | 5090 | 4.5773 | 1.1753 | -1648 |
| 8 | 1754 | 1.5773 | 1.0572 | -2685 |

## 5. 集中度與 Bootstrap

- Best day：**+1105**，占總 PnL **13.1%**
- Top 3 days：**+2696**，占 **32.0%**
- Top 5 days：**+4034**，占 **47.9%**
- 移除 Top 5 days 後：**+4,392 / E +4.171 / PF 1.168**
- 移除 Top 10 days 後：**+2,059 / E +2.088 / PF 1.084**
- Top 1% trades 貢獻約總 PnL **49.4%**；移除後仍 **+4,265 / E +3.877 / PF 1.155**

Session-date cluster bootstrap（30,000 iterations, seed 20260822）：Net@2 expectancy 95% CI 約 **[+2.37,+12.95]**，`P(E>0)=99.81%`。

## 6. 路徑與持有時間

同一批 frozen entries：

- 15s E **-0.70**
- 30s **+0.68**
- 60s **-0.70**
- 90s **+1.00**
- 120s **+2.54**
- 180s **+4.74**
- 240s **+5.50**
- 300s **+7.58**

獲利單通常 early MAE、late MFE；緊停損與過早停利會破壞 right tail。

## 7. Fixed stop 真正重跑 position state

停損若提前出場就真的釋放 position，後續 signal 可重新進場。結論：**本 sample 中沒有任何測試過的 fixed stop 同時改善 PnL 與 drawdown。** 10–100點尤其破壞 edge；125–600點也未優於 no-stop。

## 8. 參數鄰域 robustness

- HighVol percentile 65%～95% 全部為正，80% 非單點甜蜜點。
- Signal quantile Q0.02%～Q0.20% 全部為正；越不極端時 trade數增加、每筆edge下降。
- Frozen day window 的 09:00–09:30、09:30–10:30 都正。
- Frozen night window 的 20:30–21:30、21:30–22:30 都正。
- 不擴張窗口，避免 post-hoc rule creep。

## 9. Forward OOS gate

原始 sample 截止 **2026-08-14 13:44:59**。任何之後從未被本研究看過的 MTX tick 才可算真正 OOS。

最少觀察：**6 calendar months 且 >=200 trades**。期間禁止改參數；任何改動重啟 OOS clock。

Promotion gates：

1. Net@2 expectancy > 0
2. PF@2 >= 1.10
3. Net@5 expectancy > 0
4. session-date cluster bootstrap 95% lower expectancy > 0
5. OOS max drawdown <= **2,470 points**
6. 當 OOS cumulative PnL >0 後，單一日貢獻 <25%

## 10. 最終研究判定

目前正確狀態：

> **FROZEN FORWARD-OOS CANDIDATE — PAPER TRADE / RESEARCH ONLY — NOT LIVE APPROVED**

下一次有效證據必須來自 **2026-08-14 13:44:59 之後的新 MTX tick**，按照 frozen config 原封不動執行。
