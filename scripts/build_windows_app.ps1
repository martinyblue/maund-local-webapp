$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (!(Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "[MAUND] Creating local virtual environment..."
  py -3 -m venv .venv
}

if (!(Test-Path ".venv\Scripts\pyinstaller.exe")) {
  Write-Host "[MAUND] Installing required packages..."
  .venv\Scripts\pip.exe install -r requirements.txt
}

.venv\Scripts\python.exe -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name maund-local-webapp `
  --add-data "maund_local_app;maund_local_app" `
  maund_local_webapp_launcher.py
