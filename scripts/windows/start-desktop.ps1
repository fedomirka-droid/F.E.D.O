<#
.SYNOPSIS
  Запуск F.E.D.O. Desktop без установщика (из исходников).

.DESCRIPTION
  1) создаёт .venv, если его нет, и ставит зависимости;
  2) поднимает локальный backend на 127.0.0.1:8765 (данные — %APPDATA%\FEDO);
  3) собирает/запускает UI (Vite dev) либо открывает собранный dist;
  4) останавливает backend по Ctrl+C.

  Ничего не пишет вне каталога проекта и %APPDATA%\FEDO.
#>
[CmdletBinding()]
param(
  [switch]$Build,                       # собрать UI в dist вместо dev-сервера
  [string]$HubUrl = $env:FEDO_HUB_URL,   # необязательно: подключить HUB
  [string]$DeviceToken = $env:FEDO_SYNC_DEVICE_TOKEN,
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$dataDir = Join-Path $env:APPDATA "FEDO"
$venv = Join-Path $repo ".venv"
$python = Join-Path $venv "Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
Write-Host "F.E.D.O. Desktop" -ForegroundColor DarkYellow
Write-Host "  репозиторий: $repo"
Write-Host "  данные:      $dataDir"

if (-not (Test-Path $python)) {
  Write-Host "Создаю виртуальное окружение .venv ..." -ForegroundColor Yellow
  python -m venv $venv
  & $python -m pip install --upgrade pip | Out-Null
  & $python -m pip install -r (Join-Path $repo "requirements-ecosystem.txt")
}

$env:FEDO_DATA_DIR = $dataDir
$env:FEDO_ROLE = "desktop"
if ($HubUrl) { $env:FEDO_HUB_URL = $HubUrl }
if ($DeviceToken) { $env:FEDO_SYNC_DEVICE_TOKEN = $DeviceToken }

Write-Host "Запускаю backend на http://127.0.0.1:$Port ..." -ForegroundColor Yellow
$backend = Start-Process -FilePath $python `
  -ArgumentList "-m", "ecosystem.backend", "--role", "desktop", "--port", "$Port" `
  -WorkingDirectory $repo -PassThru -NoNewWindow

# ждём health
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 500
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
    if ($health.status -eq "ok") { $ready = $true; break }
  } catch { }
}
if (-not $ready) {
  Write-Host "Backend не поднялся. Смотри $dataDir\logs" -ForegroundColor Red
  if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
  exit 1
}
Write-Host "Backend готов: role=$($health.role) core=$($health.core)" -ForegroundColor Green

$ui = Join-Path $repo "desktop"
if (-not (Test-Path (Join-Path $ui "node_modules"))) {
  Push-Location $ui; npm install; Pop-Location
}
try {
  Push-Location $ui
  if ($Build) {
    npm run build
    Write-Host "UI собран в desktop\dist — открывай http://127.0.0.1:$Port" -ForegroundColor Green
    Start-Process "http://127.0.0.1:$Port"
    Read-Host "Enter — остановить backend"
  } else {
    Write-Host "UI: http://localhost:5173 (Ctrl+C — остановить)" -ForegroundColor Green
    npm run dev
  }
} finally {
  Pop-Location
  if (-not $backend.HasExited) {
    Write-Host "Останавливаю backend ..." -ForegroundColor Yellow
    Stop-Process -Id $backend.Id -Force
  }
}
