# ============================================================
#  Fabio Decision Gym V2 - One-Click Launcher
#  單一視窗同時啟動 Local Data API (8765) + Vite 前端 (5173)
#  用法:  powershell -ExecutionPolicy Bypass -File scripts\start-decision-gym.ps1
#       或直接雙擊根目錄的 start.bat
#  Ctrl+C 會同時關閉 API 與前端
# ============================================================

param(
<<<<<<< HEAD
  [string]$DataRoot  = 'D:\tools\traderChatV1\data\parquet\Future',
  [string]$EventDb   = 'D:\tools\traderChatV1\data\fabio-events.sqlite3',
  [int]$ApiPort      = 8765,
  [int]$WebPort      = 5173,
=======
  [string]$DataRoot = 'D:\tools\traderChatV1\data\parquet\Future',
  [string]$EventDb = '',
  [int]$FrontendPort = 5173,
>>>>>>> d449789ac31d621de1f260ca8bd95c3df2bce632
  [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

<<<<<<< HEAD
# 確保中文輸出正確 (UTF-8)
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$OutputEncoding = [System.Text.Encoding]::UTF8
=======
if ([string]::IsNullOrWhiteSpace($EventDb)) {
  $EventDb = Join-Path $Repo 'fabio-events.sqlite3'
}

function Test-PortAvailable([int]$Port) {
  $listener = $null
  try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()
    return $true
  }
  catch {
    return $false
  }
  finally {
    if ($null -ne $listener) {
      try { $listener.Stop() } catch {}
    }
  }
}

function Resolve-FrontendPort([int]$StartPort) {
  $port = $StartPort
  $maxPort = [Math]::Min(65535, $StartPort + 100)
  while ($port -le $maxPort) {
    if (Test-PortAvailable $port) { return $port }
    Write-Host "Frontend port $port is already in use; trying $($port + 1)..." -ForegroundColor Yellow
    $port++
  }
  throw "No free frontend port found between $StartPort and $maxPort."
}

Write-Host 'Fabio Decision Gym V3' -ForegroundColor Cyan
Write-Host "Repo      : $Repo"
Write-Host "Data root : $DataRoot"
Write-Host "Event DB  : $EventDb"
>>>>>>> d449789ac31d621de1f260ca8bd95c3df2bce632

Write-Host ''
Write-Host '  Fabio Decision Gym V2 - One-Click Start' -ForegroundColor Cyan
Write-Host '  ========================================' -ForegroundColor Cyan
Write-Host "  Repo     : $Repo"
Write-Host "  DataRoot : $DataRoot"
Write-Host "  EventDb  : $EventDb"
Write-Host "  API port : $ApiPort   |  Web port : $WebPort"
Write-Host ''

# ---------- 1. 解析 Python (優先使用 .venv, 損壞自動重建) ----------
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$pyLauncher = (Get-Command py -ErrorAction SilentlyContinue)
$systemPy   = (Get-Command python -ErrorAction SilentlyContinue)

<<<<<<< HEAD
function New-Venv {
  if ($pyLauncher) { py -m venv .venv }
  elseif ($systemPy) { & $systemPy.Source -m venv .venv }
  else { throw '找不到 Python。請先安裝 Python 3.11+ 並加入 PATH。' }
=======
if (-not $SkipInstall) {
  & $Python -m pip install --upgrade pip
  & $Python -m pip install -r requirements-server.txt
}

$PixiSource = Join-Path $Repo 'node_modules\pixi.js\dist\pixi.min.js'
$ViteSource = Join-Path $Repo 'node_modules\vite\bin\vite.js'
$NeedNodeRepair = (-not (Test-Path $PixiSource)) -or (-not (Test-Path $ViteSource))

if ((-not $SkipInstall) -or $NeedNodeRepair) {
  if ($NeedNodeRepair) {
    Write-Host 'Frontend dependencies are incomplete; repairing node_modules...' -ForegroundColor Yellow
  }
  npm install --ignore-scripts
  if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
}

Write-Host 'Preparing PixiJS vendor bundle...' -ForegroundColor Yellow
npm run vendor:pixi
if ($LASTEXITCODE -ne 0) { throw 'PixiJS vendor generation failed.' }

$PixiVendor = Join-Path $Repo 'public\vendor\pixi-8.19.0.min.js'
if (-not (Test-Path $PixiVendor)) {
  throw "PixiJS vendor bundle was not created: $PixiVendor"
}
Write-Host 'PixiJS vendor: OK' -ForegroundColor Green

$ResolvedPort = Resolve-FrontendPort $FrontendPort
if ($ResolvedPort -ne $FrontendPort) {
  Write-Host "Requested frontend port $FrontendPort is occupied. Using $ResolvedPort instead." -ForegroundColor Yellow
>>>>>>> d449789ac31d621de1f260ca8bd95c3df2bce632
}

if (-not (Test-Path $Python)) {
  Write-Host '[Setup] 建立 Python 虛擬環境 .venv ...' -ForegroundColor Yellow
  New-Venv
} else {
  # 健康檢查: venv 存在但 pip 壞掉 -> 先原地修復 (ensurepip)，不行才重建
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  & $Python -m pip --version 2>&1 | Out-Null
  $pipOk = ($LASTEXITCODE -eq 0)
  if (-not $pipOk) {
    Write-Host '[Setup] .venv 缺少 pip，嘗試修復 ...' -ForegroundColor Yellow
    & $Python -m ensurepip --upgrade 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
      # ensurepip 失敗 -> 整個重建 (若被 VS Code 等程式占用會失敗)
      Write-Host '[Setup] 修復失敗，重新建立 .venv ...' -ForegroundColor Yellow
      try { Remove-Item -Recurse -Force '.venv' -ErrorAction Stop }
      catch {
        throw "無法重建 .venv: $_`n請關閉 VS Code / 終端機後重試 (有程式占用 .venv 檔案)。"
      }
      New-Venv
    }
    & $Python -m pip --version 2>&1 | Out-Null
    $pipOk = ($LASTEXITCODE -eq 0)
  }
  $ErrorActionPreference = $prevEAP
  if (-not $pipOk) { throw 'Python 虛擬環境修復失敗，請手動重建 .venv。' }
}
Write-Host "[Setup] Python : $Python"

# ---------- 2. 安裝相依套件 (可加 -SkipInstall 跳過) ----------
if (-not $SkipInstall) {
  Write-Host '[Setup] 安裝 Python 套件 ...' -ForegroundColor Yellow
  & $Python -m pip install --disable-pip-version-check -q -r requirements-server.txt
  if ($LASTEXITCODE -ne 0) { throw 'Python 套件安裝失敗，請檢查網路或 requirements-server.txt' }

<<<<<<< HEAD
  if (-not (Test-Path 'node_modules')) {
    Write-Host '[Setup] 安裝 npm 套件 (首次) ...' -ForegroundColor Yellow
    npm install
    if ($LASTEXITCODE -ne 0) { throw 'npm install 失敗' }
  }
} else {
  Write-Host '[Setup] 略過套件安裝 (-SkipInstall)' -ForegroundColor DarkGray
}

# ---------- 3. 檢查資料目錄 (不存在則回退 Demo fixtures, 只警告) ----------
if (Test-Path $DataRoot) {
  Write-Host "[Data ] 本地資料目錄: OK" -ForegroundColor Green
} else {
  Write-Host "[Data ] 警告: 找不到 $DataRoot" -ForegroundColor Yellow
  Write-Host "        前端將以 Demo fixture 運作 (圖表不會動態讀取本地 Parquet)" -ForegroundColor Yellow
}

# ---------- 4. 背景啟動 Local Data API ----------
Write-Host ''
Write-Host '[Start] 啟動 Local Data API ...' -ForegroundColor Green
$apiJob = Start-Job -ScriptBlock {
  param($py, $repo, $root, $db, $port)
  $env:FABIO_DATA_ROOT  = $root
  $env:FABIO_EVENT_DB   = $db
  $env:FABIO_API_PORT   = "$port"
  Set-Location $repo
  & $py -m server.fabio_api
} -ArgumentList $Python, $Repo, $DataRoot, $EventDb, $ApiPort

# ---------- 5. 等待 API health check ----------
$healthUrl = "http://127.0.0.1:$ApiPort/api/health"
$apiUp = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Milliseconds 500
  try {
    $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
    if ($resp.StatusCode -eq 200) { $apiUp = $true; break }
  } catch { }
}
if ($apiUp) {
  Write-Host "[API ] Online: $healthUrl" -ForegroundColor Green
} else {
  Write-Host "[API ] 警告: 尚未回應。可稍後檢查 API 輸出。" -ForegroundColor Yellow
  Receive-Job $apiJob -Keep | ForEach-Object { Write-Host "  $_" }
}

# ---------- 6. 開啟瀏覽器 + 前台執行 Vite ----------
$webUrl = "http://127.0.0.1:$WebPort"
Start-Sleep -Milliseconds 500
Start-Process $webUrl

Write-Host ''
Write-Host "[Web ] 開啟: $webUrl" -ForegroundColor Green
Write-Host '  按 Ctrl+C 可同時關閉前端與 API。' -ForegroundColor DarkGray
Write-Host ''
try {
  # 直接用 node 呼叫 vite (繞過 npm.cmd, 避免 PS5.1 的 cmd 參數轉遞 bug)
  & node "node_modules\vite\bin\vite.js" --host 0.0.0.0 --port $WebPort
} finally {
  # Ctrl+C / 結束時清理背景 API job
  Stop-Job $apiJob -ErrorAction SilentlyContinue
  Remove-Job $apiJob -Force -ErrorAction SilentlyContinue
  Write-Host ''
  Write-Host '[Done] 已停止 API 與前端。' -ForegroundColor Cyan
}
=======
Start-Sleep -Seconds 2
Write-Host 'Starting Vite frontend...' -ForegroundColor Green
Write-Host 'API      : http://127.0.0.1:8765/api/health'
Write-Host "Frontend : http://127.0.0.1:$ResolvedPort/" -ForegroundColor Cyan
Write-Host 'Press Ctrl+C here to stop the frontend. Close the API window separately.'
npm run dev -- --port $ResolvedPort --strictPort
>>>>>>> d449789ac31d621de1f260ca8bd95c3df2bce632
