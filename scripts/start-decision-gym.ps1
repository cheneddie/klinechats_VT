param(
  [string]$DataRoot = 'D:\tools\traderChatV1\data\parquet\Future',
  [string]$EventDb = 'D:\tools\traderChatV1\data\fabio-events.sqlite3',
  [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

Write-Host 'Fabio Decision Gym V2' -ForegroundColor Cyan
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
  if (-not (Test-Path 'node_modules')) {
    npm install
  }
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
Write-Host 'API: http://127.0.0.1:8765/api/health'
Write-Host 'Press Ctrl+C here to stop the frontend. Close the API window separately.'
npm run dev
