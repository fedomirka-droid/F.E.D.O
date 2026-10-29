<#
.SYNOPSIS
  Автозапуск F.E.D.O. Desktop при входе в систему (через Планировщик заданий).

.DESCRIPTION
  Регистрирует задачу FEDO-Desktop, которая запускает start-desktop.ps1 -Build.
  Ничего не меняет в системных службах. Удаление: -Uninstall.
#>
[CmdletBinding()]
param(
  [string]$TaskName = "FEDO-Desktop",
  [switch]$Uninstall,
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

if ($Uninstall) {
  schtasks /Query /TN $TaskName *> $null
  if ($LASTEXITCODE -eq 0) {
    schtasks /Delete /TN $TaskName /F | Out-Null
    Write-Host "Автозапуск $TaskName удалён." -ForegroundColor Green
  } else {
    Write-Host "Задача $TaskName не найдена." -ForegroundColor Yellow
  }
  return
}

$script = Join-Path $PSScriptRoot "start-desktop.ps1"
$action = "powershell.exe -NoLogo -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Build -Port $Port"
schtasks /Create /TN $TaskName /TR $action /SC ONLOGON /RL LIMITED /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Не удалось создать задачу планировщика" }
Write-Host "Автозапуск зарегистрирован: $TaskName" -ForegroundColor Green
Write-Host "Проверить: schtasks /Query /TN $TaskName"
Write-Host "Удалить:   .\install-autostart.ps1 -Uninstall"
