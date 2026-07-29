@echo off
cd /d "%~dp0"
echo Starting RWS Research Genie Web App...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_BOT.ps1"
if errorlevel 1 (
    echo.
    echo Failed to start. Run: pip install -r requirements.txt
    pause
)