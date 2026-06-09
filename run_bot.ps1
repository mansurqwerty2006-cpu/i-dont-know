$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Fill TELEGRAM_BOT_TOKEN and GROQ_API_KEY, then run this script again."
    exit 1
}

python bot.py
