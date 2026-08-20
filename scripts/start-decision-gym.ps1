param(
  [string]$DataRoot = 'D:\tools\traderChatV1\data\parquet\Future',
  [string]$EventDb = '',
  [int]$FrontendPort = 5173,
  [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

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

if (-not (Test-Path $DataRoot)) {
  throw "MTX data directory not found: $DataRoot"
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
  Write-Host 'Creating Python virtual environment...' -ForegroundColor Yellow
  py -m venv .venv
}

$Python = Join-Path $Repo '.venv\Scripts\python.exe'

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
}

$apiCmd = @"
`$env:FABIO_DATA_ROOT='$DataRoot'
`$env:FABIO_EVENT_DB='$EventDb'
Set-Location '$Repo'
& '$Python' -m server.fabio_api
"@

Write-Host 'Starting Local Data API in a new PowerShell window...' -ForegroundColor Green
Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-Command',$apiCmd

Start-Sleep -Seconds 2
Write-Host 'Starting Vite frontend...' -ForegroundColor Green
Write-Host 'API      : http://127.0.0.1:8765/api/health'
Write-Host "Frontend : http://127.0.0.1:$ResolvedPort/" -ForegroundColor Cyan
Write-Host 'Press Ctrl+C here to stop the frontend. Close the API window separately.'
npm run dev -- --port $ResolvedPort --strictPort
