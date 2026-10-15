# Run from PowerShell 7. No system-wide environment changes.
$ErrorActionPreference = 'Stop'
$sceRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $sceRoot
try {
    $scePython = Join-Path $sceRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $scePython)) { throw 'Create the project virtual environment first; see README.md.' }
    & $scePython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Automated tests failed.' }
    & $scePython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Package dependency check failed.' }
    & $scePython -m sce --version
    if ($LASTEXITCODE -ne 0) { throw 'CLI check failed.' }
    & $scePython scripts/run_experiments.py
    if ($LASTEXITCODE -ne 0) { throw 'Controlled experiments failed.' }
} finally {
    Pop-Location
}
