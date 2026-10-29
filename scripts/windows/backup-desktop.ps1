<#
.SYNOPSIS
  Резервная копия локальной базы Desktop (SQLite) + ротация.

.DESCRIPTION
  Копирует fedo.db, secret.key (если есть) и preferences в %APPDATA%\FEDO\backups.
  Для консистентности использует sqlite3 .backup, если он доступен, иначе
  обычное копирование с предварительной остановкой backend (рекомендуется).
#>
[CmdletBinding()]
param(
  [string]$DataDir = (Join-Path $env:APPDATA "FEDO"),
  [int]$Keep = 14
)

$ErrorActionPreference = "Stop"
$db = Join-Path $DataDir "fedo.db"
if (-not (Test-Path $db)) {
  Write-Host "База не найдена: $db" -ForegroundColor Yellow
  exit 0
}

$backupDir = Join-Path $DataDir "backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $backupDir "fedo-$stamp.db"

$sqlite = Get-Command sqlite3 -ErrorAction SilentlyContinue
if ($sqlite) {
  & sqlite3 $db ".backup '$target'"
} else {
  Copy-Item $db $target
}
Write-Host "Копия базы: $target" -ForegroundColor Green

$key = Join-Path $DataDir "secret.key"
if (Test-Path $key) {
  Copy-Item $key (Join-Path $backupDir "secret-$stamp.key")
  Write-Host "Ключ шифрования сохранён рядом (храни отдельно от базы!)" -ForegroundColor Yellow
}

Get-ChildItem $backupDir -Filter "fedo-*.db" | Sort-Object LastWriteTime -Descending |
  Select-Object -Skip $Keep | ForEach-Object {
    Write-Host "Удаляю старую копию $($_.Name)"
    Remove-Item $_.FullName -Force
  }
