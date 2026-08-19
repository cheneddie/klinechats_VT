# Windows Multi-Year MTX Setup

This guide uses the intended local data directory:

```text
D:\tools\traderChatV1\data\parquet\Future
```

Expected files can include:

```text
MTX_2022.parquet
MTX_2023.parquet
MTX_2024.parquet
MTX_2025.parquet
MTX_2026.parquet
...
```

Raw Parquet stays on the local machine and is never committed to GitHub.

## 1. Install frontend

```powershell
cd D:\tools\klinechats_VT
npm install
```

## 2. Create Python environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-server.txt
```

## 3. Point the API to MTX data

The path below is already the application default, but setting it explicitly makes the environment obvious:

```powershell
$env:FABIO_DATA_ROOT="D:\tools\traderChatV1\data\parquet\Future"
```

Optional Event Store location:

```powershell
$env:FABIO_EVENT_DB="D:\tools\traderChatV1\data\fabio-events.sqlite3"
```

## 4. Start Local Data API

Terminal A:

```powershell
.\.venv\Scripts\Activate.ps1
python -m server.fabio_api
```

Expected API:

```text
http://127.0.0.1:8765/api
```

Health check in a browser:

```text
http://127.0.0.1:8765/api/health
```

## 5. Start Decision Gym

Terminal B:

```powershell
npm run dev
```

Open the Vite local URL. The lower-left API indicator should change from:

```text
Demo / 離線資料
```

to:

```text
Local Data API 已連線
```

## 6. Scan years

Open:

```text
Data / Scanner
```

Use **Strict — 日曆近月 / 因果（建議）**.

`dominant_volume` is intentionally non-causal because it needs the completed trading day's volume ranking. It is diagnostics-only.

Example API request:

```powershell
$body = @{
  years = @(2025)
  contract_mode = "strict"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8765/api/scan" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

Check progress:

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/api/scan/status"
```

## 7. Verify Node counts

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/api/nodes/stats"
```

The Decision Node Library uses these full SQLite counts, so node totals do not depend on how many cases the browser currently holds.

## 8. Query one node directly

Example: 2025 Clear Reclaim cases.

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/api/cases?node_id=MR_CLEAR_RECLAIM&year=2025&limit=100"
```

Use the UI to choose the same node and start 20 / 50 / 100-question deliberate practice.

## 9. Replay exact event

Given an `event_id` returned by the Case Browser:

```text
GET /api/replay/{event_id}
```

The API locates the original Parquet source and `_seq` window, preserves raw physical Tick order, and builds 1-second KLineChart bars only for that local window.

## 10. Data-integrity rules

Never change these rules:

1. `_seq` represents physical source row order.
2. Raw Tick rows must not be re-sorted.
3. Same-second trades keep Parquet physical order.
4. Only monthly outright `YYYYMM` contracts are eligible.
5. Different contracts must never share one Previous Value / Volume Profile.
6. `side` is Tick Direction proxy only; it is not Bid/Ask aggressor side.
7. Strict contract selection must remain causal.

## 11. Recommended first scan

Start with only 2025:

```text
MTX_2025.parquet
```

Validate:

- Dataset QA = PASS
- 236 day sessions expected for the supplied 2025 file
- contract changes agree with `reports/MTX_2025_CONTRACT_QA.md`
- Node Library has non-zero Auction / MR / BO / WAIT counts
- clicking a case opens the correct date and 1-second Replay window

Then add other years one at a time. This makes data or contract-rule problems much easier to isolate.
