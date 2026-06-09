$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Fill TELEGRAM_BOT_TOKEN and GROQ_API_KEY, then run this script again."
    exit 1
}

New-Item -ItemType Directory -Path "logs" -Force | Out-Null

$python = (Get-Command python -ErrorAction Stop).Source
$psi = [System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $python
$psi.Arguments = "bot.py"
$psi.WorkingDirectory = $PSScriptRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true

$process = [System.Diagnostics.Process]::Start($psi)
$process.Id | Set-Content -Path "logs\bot.pid"

Write-Host "Bot started in background. PID: $($process.Id)"
Write-Host "Logs: $PSScriptRoot\logs\bot.log"
