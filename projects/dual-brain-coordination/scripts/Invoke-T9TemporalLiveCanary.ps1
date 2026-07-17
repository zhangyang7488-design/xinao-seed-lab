#Requires -Version 7.2
<#
.SYNOPSIS
  T9 Temporal LIVE canary (G2): gated pytest + temporalio bypass evidence.

.DESCRIPTION
  Sets XINAO_TEMPORAL_LIVE_E2E=1 and runs scripts/_t9_temporal_live_evidence.py.
  Does not modify client.py / policy.py / service.py.
  Does not docker-compose up or recreate Temporal.

.PARAMETER ProjectRoot
  dual-brain-coordination repo root

.PARAMETER EvidenceOut
  Optional override for evidence JSON path (script has default under saturation/G2)
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$EvidenceOut = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-PythonExe {
    param([string]$Root)
    $candidates = @(
        (Join-Path $Root '.venv\Scripts\python.exe'),
        (Join-Path $Root 'venv\Scripts\python.exe')
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c -PathType Leaf) { return $c }
    }
    throw 'PYTHON_NOT_FOUND: project .venv missing'
}

$py = Get-PythonExe -Root $ProjectRoot
$script = Join-Path $ProjectRoot 'scripts\_t9_temporal_live_evidence.py'
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "MISSING: $script"
}

$env:XINAO_TEMPORAL_LIVE_E2E = '1'
$env:XINAO_TEMPORAL_ENABLED = '1'
$env:XINAO_TEMPORAL_MOCK = '0'
$env:XINAO_TEMPORAL_LIVE = '1'
if (-not $env:XINAO_TEMPORAL_ADDRESS) { $env:XINAO_TEMPORAL_ADDRESS = '127.0.0.1:7233' }
if (-not $env:XINAO_TEMPORAL_NAMESPACE) { $env:XINAO_TEMPORAL_NAMESPACE = 'default' }
if (-not $env:XINAO_TEMPORAL_TASK_QUEUE) { $env:XINAO_TEMPORAL_TASK_QUEUE = 'xinao-dualbrain-promoted-v1' }

Write-Host "==> T9 Temporal LIVE canary (G2)" -ForegroundColor Cyan
Write-Host "    python=$py"
Write-Host "    script=$script"
Write-Host "    LIVE_E2E=$($env:XINAO_TEMPORAL_LIVE_E2E) ADDRESS=$($env:XINAO_TEMPORAL_ADDRESS)"

& $py $script
$code = $LASTEXITCODE
if ($EvidenceOut -and (Test-Path -LiteralPath (
        'D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712\saturation\G2_temporal_live\T9_temporal_live_canary.json'
    ))) {
    $src = 'D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712\saturation\G2_temporal_live\T9_temporal_live_canary.json'
    $destDir = Split-Path -Parent $EvidenceOut
    if ($destDir -and -not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Copy-Item -LiteralPath $src -Destination $EvidenceOut -Force
    Write-Host "    copied evidence -> $EvidenceOut"
}

Write-Host ("==> exit {0}" -f $code)
exit $code
