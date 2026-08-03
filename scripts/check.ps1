$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$toolsRoot = Join-Path $backendRoot ".venv\Scripts"

function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Quality check failed with exit code $LASTEXITCODE."
    }
}

Invoke-Checked { & (Join-Path $toolsRoot "pytest.exe") $backendRoot }
Invoke-Checked { & (Join-Path $toolsRoot "ruff.exe") check (Join-Path $backendRoot "app") (Join-Path $backendRoot "tests") (Join-Path $backendRoot "scripts") }
Invoke-Checked { & (Join-Path $toolsRoot "ruff.exe") format --check (Join-Path $backendRoot "app") (Join-Path $backendRoot "tests") (Join-Path $backendRoot "scripts") }

Push-Location $projectRoot
try {
    Invoke-Checked { npm run build }
}
finally {
    Pop-Location
}

Write-Host "All checks passed."
