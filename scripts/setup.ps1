$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$pythonPath = Join-Path $backendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonPath)) {
    python -m venv (Join-Path $backendRoot ".venv")
}

& $pythonPath -m pip install -e "$backendRoot[dev]"

$environmentPath = Join-Path $backendRoot ".env"
if (-not (Test-Path $environmentPath)) {
    Copy-Item (Join-Path $backendRoot ".env.example") $environmentPath
}

Push-Location $projectRoot
try {
    npm install
}
finally {
    Pop-Location
}

Write-Host "Setup complete. Configure optional provider keys in backend/.env."
