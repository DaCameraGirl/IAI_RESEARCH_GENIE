# RWS Research Bot — starts web server
Set-Location $PSScriptRoot

python scripts\rws_web.py
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Failed to start. Run: pip install -r requirements.txt"
    Read-Host "Press Enter to close"
}