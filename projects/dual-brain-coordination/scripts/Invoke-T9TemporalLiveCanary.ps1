#Requires -Version 7.2
<#
.SYNOPSIS
  Promoted-task Temporal live canary: gated pytest + temporalio evidence.

.DESCRIPTION
  Sets XINAO_TEMPORAL_LIVE_E2E=1 and runs scripts/_t9_temporal_live_evidence.py.
  Does not modify client.py / policy.py / service.py.
  Does not docker-compose up or recreate Temporal.

.PARAMETER ProjectRoot
  dual-brain-coordination repo root

.PARAMETER EvidenceOut
  Optional override for the generic evidence JSON path.
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

Write-Host "==> Promoted-task Temporal live canary" -ForegroundColor Cyan
Write-Host "    python=$py"
Write-Host "    script=$script"
Write-Host "    LIVE_E2E=$($env:XINAO_TEMPORAL_LIVE_E2E) ADDRESS=$($env:XINAO_TEMPORAL_ADDRESS)"

$previousEvidenceOut = $env:XINAO_DUAL_BRAIN_EVIDENCE_OUT
try {
    if ($EvidenceOut) {
        $env:XINAO_DUAL_BRAIN_EVIDENCE_OUT = $EvidenceOut
    }
    & $py $script
    $code = $LASTEXITCODE
}
finally {
    if ($null -eq $previousEvidenceOut) {
        Remove-Item Env:XINAO_DUAL_BRAIN_EVIDENCE_OUT -ErrorAction SilentlyContinue
    }
    else {
        $env:XINAO_DUAL_BRAIN_EVIDENCE_OUT = $previousEvidenceOut
    }
}

Write-Host ("==> exit {0}" -f $code)
exit $code
