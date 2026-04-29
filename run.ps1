$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Virtual environment Python not found at $python"
    exit 1
}

& $python -m n8ngd
