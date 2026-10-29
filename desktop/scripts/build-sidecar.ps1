# Сборка sidecar-бинарника backend для Tauri (Windows 11, PowerShell).
# Требования: Python 3.11+, создан .venv, установлен pyinstaller.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

Write-Host "[1/3] Зависимости backend" -ForegroundColor Cyan
python -m pip install -r requirements-ecosystem.txt pyinstaller

Write-Host "[2/3] Сборка fedo-backend.exe (PyInstaller)" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean --onefile `
  --name fedo-backend `
  --paths . `
  --collect-submodules ecosystem `
  --add-data "ecosystem/backend/migrations;ecosystem/backend/migrations" `
  --add-data "ecosystem/backend/alembic.ini;ecosystem/backend" `
  --add-data "core;core" --add-data "ai;ai" --add-data "config.py;." `
  desktop/scripts/sidecar_entry.py

Write-Host "[3/3] Копирование в desktop/src-tauri/binaries" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "desktop/src-tauri/binaries" | Out-Null
Copy-Item -Force "dist/fedo-backend.exe" "desktop/src-tauri/binaries/fedo-backend.exe"
Write-Host "Готово: desktop/src-tauri/binaries/fedo-backend.exe" -ForegroundColor Green
