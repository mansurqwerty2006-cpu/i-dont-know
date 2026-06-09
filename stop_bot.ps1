$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$pidFile = "logs\bot.pid"
if (-not (Test-Path $pidFile)) {
    Write-Host "No logs\bot.pid file found. The bot may already be stopped."
    exit 0
}

$botPid = (Get-Content $pidFile -Raw).Trim()
if (-not $botPid) {
    Write-Host "logs\bot.pid is empty."
    exit 0
}

$process = Get-Process -Id ([int]$botPid) -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id ([int]$botPid) -Force
    Write-Host "Bot stopped. PID: $botPid"
} else {
    Write-Host "No running process found for PID: $botPid"
}

Remove-Item $pidFile -Force
