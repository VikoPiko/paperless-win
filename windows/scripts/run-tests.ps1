#Requires -Version 7
<#
.SYNOPSIS
  Run the backend test suite on Windows with the fork's skip list applied.

.DESCRIPTION
  Loads the dev tools (.tools\env.ps1, written by bootstrap-dev.ps1), enables the
  paperless_win pytest plugin (skips from windows\skipped_tests.toml) and runs pytest
  from src\ in a clean environment (no spike or PAPERLESS_* variables leak in).
  Extra arguments are passed to pytest, e.g.  -k consumer  or  documents/tests/test_api_status.py

  Writes JUnit XML to .spike\junit-windows.xml (override with -Junit). Summarise it with
  windows\scripts\summarize_failures.py.
#>
param(
    [string]$Junit = '',
    [Parameter(ValueFromRemainingArguments = $true)] [string[]]$PytestArgs
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
. "$root\.tools\env.ps1"
if (-not $Junit) {
    New-Item -ItemType Directory -Force "$root\.spike" | Out-Null
    $Junit = "$root\.spike\junit-windows.xml"
}
Get-ChildItem Env: | Where-Object { $_.Name -like 'PAPERLESS_*' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = 'src'
$env:PYTEST_ADDOPTS = '-p paperless_win.pytest_plugin'
Set-Location "$root\src"
& "$root\.venv\Scripts\python.exe" -m pytest -q -p no:randomly -n auto -p no:sugar --no-cov "--junitxml=$Junit" @PytestArgs
exit $LASTEXITCODE
