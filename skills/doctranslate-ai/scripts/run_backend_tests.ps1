$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir "..\..\..")
$backendDir = Join-Path $projectRoot "backend"

Set-Location $backendDir
python -m pytest
