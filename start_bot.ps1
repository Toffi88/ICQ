# WoW Hybrid-Logic Bot Startskript
# Aktiviert die venv und startet den Bot

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $scriptPath "venv"
$botScript = Join-Path $scriptPath "wow_live_bot.py"

if (Test-Path $venvPath) {
    Write-Host "Aktiviere virtuelle Umgebung..." -ForegroundColor Green
    & "$venvPath\Scripts\Activate.ps1"
    
    Write-Host "Starte WoW Hybrid-Logic Bot..." -ForegroundColor Green
    Write-Host "Stelle sicher, dass World of Warcraft läuft!" -ForegroundColor Yellow
    Write-Host ""
    
    python "$botScript"
} else {
    Write-Host "Fehler: venv nicht gefunden!" -ForegroundColor Red
    Write-Host "Bitte führe zuerst die Installation durch." -ForegroundColor Red
    exit 1
}



