# RWS Research Bot — starts web server & opens browser
Set-Location $PSScriptRoot

Start-Process "http://127.0.0.1:7842"
python scripts\rws_web.py
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Failed to start. Run: pip install -r requirements.txt"
    Read-Host "Press Enter to close"
}