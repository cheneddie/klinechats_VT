# ============================================================
#  Fabio Decision Gym V4 - One-Click Launcher
#  單一視窗同時啟動 V4 Local Data API (8765) + Vite 前端 (5173)
#  用法: powershell -ExecutionPolicy Bypass -File scripts\start-decision-gym.ps1
#       或直接雙擊根目錄的 start.bat
#  Ctrl+C 會同時關閉 API 與前端
# ============================================================

param(
  [string]$DataRoot  = 'D:\tools\traderChatV1\data\parquet\Future',
  [string]$EventDb   = '',
  [int]$ApiPort      = 8765,
  [int]$WebPort      = 5173,
  [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$OutputEncoding = [System.Text.Encoding]::UTF8

# Event Store 是可由 Parquet 重建的衍生資料；預設跟專案放在一起。
if ([string]::IsNullOrWhiteSpace($EventDb)) {
  $EventDb = Join-Path $Repo 'fabio-events.sqlite3'
}

function Test-PortAvailable([int]$Port) {
  $listener = $null
  try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start(); return $true
  } catch { return $false }
  finally { if ($null -ne $listener) { try { $listener.Stop() } catch {} } }
}
function Resolve-FrontendPort([int]$StartPort) {
  $port = $StartPort; $maxPort = [Math]::Min(65535, $StartPort + 100)
  while ($port -le $maxPort) {
    if (Test-PortAvailable $port) { return $port }
    Write-Host "Frontend port $port is already in use; trying $($port + 1)..." -ForegroundColor Yellow
    $port++
  }
  throw "No free frontend port found between $StartPort and $maxPort."
}

Write-Host ''
Write-Host '  Fabio Decision Gym V4 - Causal Research + Deliberate Practice' -ForegroundColor Cyan
Write-Host '  ==============================================================' -ForegroundColor Cyan
Write-Host "  Repo     : $Repo"
Write-Host "  DataRoot : $DataRoot"
Write-Host "  EventDb  : $EventDb"
Write-Host "  API port : $ApiPort   |  Web port : $WebPort"
Write-Host ''

# ---------- 1. Python venv ----------
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$pyLauncher = (Get-Command py -ErrorAction SilentlyContinue)
$systemPy   = (Get-Command python -ErrorAction SilentlyContinue)
function New-Venv {
  if ($pyLauncher) { py -m venv .venv }
  elseif ($systemPy) { & $systemPy.Source -m venv .venv }
  else { throw '找不到 Python。請先安裝 Python 3.11+ 並加入 PATH。' }
}
if (-not (Test-Path $Python)) {
  Write-Host '[Setup] 建立 Python 虛擬環境 .venv ...' -ForegroundColor Yellow
  New-Venv
} else {
  $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  & $Python -m pip --version 2>&1 | Out-Null; $pipOk = ($LASTEXITCODE -eq 0)
  if (-not $pipOk) {
    Write-Host '[Setup] .venv 缺少 pip，嘗試修復 ...' -ForegroundColor Yellow
    & $Python -m ensurepip --upgrade 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
      Write-Host '[Setup] 修復失敗，重新建立 .venv ...' -ForegroundColor Yellow
      try { Remove-Item -Recurse -Force '.venv' -ErrorAction Stop }
      catch { throw "無法重建 .venv: $_`n請關閉 VS Code / 終端機後重試。" }
      New-Venv
    }
    & $Python -m pip --version 2>&1 | Out-Null; $pipOk = ($LASTEXITCODE -eq 0)
  }
  $ErrorActionPreference = $prevEAP
  if (-not $pipOk) { throw 'Python 虛擬環境修復失敗，請手動重建 .venv。' }
}
Write-Host "[Setup] Python : $Python"

# ---------- 2. Dependencies ----------
if (-not $SkipInstall) {
  Write-Host '[Setup] 安裝 Python 套件 ...' -ForegroundColor Yellow
  & $Python -m pip install --disable-pip-version-check -q -r requirements-server.txt
  if ($LASTEXITCODE -ne 0) { throw 'Python 套件安裝失敗。' }
}
$PixiSource = Join-Path $Repo 'node_modules\pixi.js\dist\pixi.min.js'
$ViteSource = Join-Path $Repo 'node_modules\vite\bin\vite.js'
$NeedNodeRepair = (-not (Test-Path $PixiSource)) -or (-not (Test-Path $ViteSource))
if ((-not $SkipInstall) -or $NeedNodeRepair) {
  if ($NeedNodeRepair) { Write-Host '[Setup] 前端依賴不完整，修復 node_modules ...' -ForegroundColor Yellow }
  if (Test-Path (Join-Path $Repo 'pnpm-lock.yaml')) { pnpm install --ignore-scripts --no-frozen-lockfile }
  else { npm install --ignore-scripts }
  if ($LASTEXITCODE -ne 0) { throw '前端套件安裝失敗。' }
}
Write-Host '[Setup] 產生 PixiJS vendor bundle ...' -ForegroundColor Yellow
npm run vendor:pixi
if ($LASTEXITCODE -ne 0) { throw 'PixiJS vendor generation failed.' }
$PixiVendor = Join-Path $Repo 'public\vendor\pixi-8.19.0.min.js'
if (-not (Test-Path $PixiVendor)) { throw "PixiJS vendor bundle 未產生: $PixiVendor" }
Write-Host '[Setup] PixiJS vendor: OK' -ForegroundColor Green

# ---------- 3. Data ----------
if (Test-Path $DataRoot) { Write-Host '[Data ] 本地資料目錄: OK' -ForegroundColor Green }
else {
  Write-Host "[Data ] 警告: 找不到 $DataRoot" -ForegroundColor Yellow
  Write-Host '        前端可進 Demo，但 Scanner / V4 Audit 無法使用。' -ForegroundColor Yellow
}

# ---------- 4. V4 API ----------
Write-Host ''
Write-Host '[Start] 啟動 Fabio V4 Local Data API ...' -ForegroundColor Green
$apiJob = Start-Job -ScriptBlock {
  param($py,$repo,$root,$db,$port)
  $env:FABIO_DATA_ROOT=$root; $env:FABIO_EVENT_DB=$db; $env:FABIO_API_PORT="$port"
  Set-Location $repo
  & $py -m server.fabio_api_v4
} -ArgumentList $Python,$Repo,$DataRoot,$EventDb,$ApiPort

$healthUrl = "http://127.0.0.1:$ApiPort/api/v4/health"
$apiUp = $false
for ($i=0;$i -lt 40;$i++) {
  Start-Sleep -Milliseconds 500
  try {
    $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
    if ($resp.StatusCode -eq 200 -and $resp.Content -match '4\.1\.0') { $apiUp=$true; break }
  } catch {}
}
if ($apiUp) { Write-Host "[API ] V4.1 Online: $healthUrl" -ForegroundColor Green }
else {
  Write-Host '[API ] V4 API 尚未回應。最近輸出：' -ForegroundColor Red
  Receive-Job $apiJob -Keep | ForEach-Object { Write-Host "  $_" }
  throw 'V4 Local API startup failed. 請先修正上方 Python 錯誤。'
}

# ---------- 5. Frontend ----------
$ResolvedPort = Resolve-FrontendPort $WebPort
if ($ResolvedPort -ne $WebPort) { Write-Host "[Web ] port $WebPort 被占用，改用 $ResolvedPort" -ForegroundColor Yellow }
$webUrl = "http://127.0.0.1:$ResolvedPort"
Start-Sleep -Milliseconds 300
Start-Process $webUrl
Write-Host ''
Write-Host "[Web ] 開啟: $webUrl" -ForegroundColor Green
Write-Host '  V4 Replay: 前後交易日 / 多週期 / physical-tick management' -ForegroundColor DarkGray
Write-Host '  按 Ctrl+C 可同時關閉前端與 API。' -ForegroundColor DarkGray
Write-Host ''
try {
  & node 'node_modules\vite\bin\vite.js' --host 0.0.0.0 --port $ResolvedPort --strictPort
} finally {
  Stop-Job $apiJob -ErrorAction SilentlyContinue
  Remove-Job $apiJob -Force -ErrorAction SilentlyContinue
  Write-Host ''
  Write-Host '[Done] 已停止 V4 API 與前端。' -ForegroundColor Cyan
}
