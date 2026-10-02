param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
& $Python (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
