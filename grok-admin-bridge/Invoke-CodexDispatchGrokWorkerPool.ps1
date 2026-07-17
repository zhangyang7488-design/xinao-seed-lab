#Requires -Version 5.1
<#
.SYNOPSIS
  Explicit bootstrap/fallback entry: dispatch bounded Grok headless workers.
.DESCRIPTION
  Use when a bounded direct Grok batch has positive net benefit for parallel
  work, diagnosis, or evidence, including canonical-route fallback. Thin
  wrapper over Invoke-GrokWorkerPool.ps1; never durable truth.
.EXAMPLE
  .\Invoke-CodexDispatchGrokWorkerPool.ps1 -N 4 -Prompt "Implement X; write evidence"
  .\Invoke-CodexDispatchGrokWorkerPool.ps1 -N 2 -PromptFile .\task.md -Cwd E:\repo
#>
param(
    [ValidateRange(1, 32)]
    [int]$N = 2,
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "grok-composer-2.5-fast",
    [string]$MaxTurns = "auto",
    [int]$TimeoutSec = 600,
    [string]$GrokHome = "C:\Users\xx363\.grok-bg-workers",
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [string]$DispatchId = "",
    [string]$PoolId = "",
    [switch]$SkipPauseGate,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$pool = Join-Path $bridge "Invoke-GrokWorkerPool.ps1"
if (-not (Test-Path -LiteralPath $pool)) {
    throw "MISSING_FALLBACK_PATH: $pool — install/copy Invoke-GrokWorkerPool.ps1"
}

$metaDir = "D:\XINAO_RESEARCH_RUNTIME\state\codex_dispatch_grok_worker_pool"
New-Item -ItemType Directory -Force -Path $metaDir | Out-Null
$dispatchId = if ([string]::IsNullOrWhiteSpace($DispatchId)) {
    "cdx_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
} else {
    $DispatchId
}
if ($dispatchId -notmatch '^cdx_[0-9]{8}T[0-9]{6}_[0-9a-f]{8}$') {
    throw "CODEX_GROK_DISPATCH_ID_INVALID: $dispatchId"
}
$poolId = if ([string]::IsNullOrWhiteSpace($PoolId)) {
    "gwp_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
} else {
    $PoolId
}
if ($poolId -notmatch '^gwp_[0-9]{8}T[0-9]{6}_[0-9a-f]{8}$') {
    throw "CODEX_GROK_POOL_ID_INVALID: $poolId"
}
$utf8 = New-Object System.Text.UTF8Encoding $false
$dispatchMetaPath = Join-Path $metaDir ($dispatchId + ".json")
$poolSummaryPath = Join-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool" (
    $poolId + "\pool_summary.json"
)
if (Test-Path -LiteralPath $dispatchMetaPath) {
    throw "CODEX_GROK_DISPATCH_ID_ALREADY_EXISTS: $dispatchId"
}

$dispatchMeta = [ordered]@{
    schema_version = "xinao.codex_dispatch_grok_worker_pool.v1"
    sentinel = "SENTINEL:CODEX_DISPATCH_GROK_WORKER_POOL"
    generated_at = (Get-Date).ToString("o")
    dispatch_id = $dispatchId
    pool_id = $poolId
    pool_summary_path = $poolSummaryPath
    role_cn = "dynamic positive-benefit bounded Grok headless worker pool"
    canonical_default_cn = "Temporal + Docker houtai-gongren + worker-internal LangGraph + dynamic Grok"
    not_default_cn = @(
        "codex_to_grok visible typeahead inject",
        "Docker integrated_bus Desktop .lnk"
    )
    n = $N
    model = $Model
    json_schema_path = $JsonSchemaPath
    cwd = if ($Cwd) { $Cwd } else { (Get-Location).Path }
    pool_script = $pool
    completion_claim_allowed = $false
}
[System.IO.File]::WriteAllText(
    $dispatchMetaPath,
    ($dispatchMeta | ConvertTo-Json -Depth 6),
    $utf8
)
Copy-Item $dispatchMetaPath (Join-Path $metaDir "latest.json") -Force

$args = @{
    N = $N
    Model = $Model
    MaxTurns = $MaxTurns
    TimeoutSec = $TimeoutSec
    GrokHome = $GrokHome
    MinResultChars = $MinResultChars
    RequiredResultMarkers = @($RequiredResultMarkers)
    PoolId = $poolId
}
if ($RequireJsonObject) { $args.RequireJsonObject = $true }
if ($JsonSchemaPath) { $args.JsonSchemaPath = $JsonSchemaPath }
if ($Prompt) { $args.Prompt = $Prompt }
if ($PromptFile) { $args.PromptFile = $PromptFile }
if ($Cwd) { $args.Cwd = $Cwd }
if ($SkipPauseGate) { $args.SkipPauseGate = $true }
if ($Quiet) { $args.Quiet = $true }

& $pool @args
$code = $LASTEXITCODE

$dispatchMeta.finished_at = (Get-Date).ToString("o")
$dispatchMeta.pool_exit_code = $code
$dispatchMeta.pool_summary_path = $poolSummaryPath
$dispatchMeta.pool_summary_exists = Test-Path -LiteralPath $poolSummaryPath -PathType Leaf
if ($dispatchMeta.pool_summary_exists) {
    try {
        $poolSummary = Get-Content -LiteralPath $poolSummaryPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
        if ([string]$poolSummary.pool_id -ne $poolId) {
            throw "CODEX_GROK_POOL_SUMMARY_ID_MISMATCH"
        }
        $dispatchMeta.pool_summary_sha256 = (
            Get-FileHash -LiteralPath $poolSummaryPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        $dispatchMeta.pool_all_ok = $poolSummary.all_ok -eq $true
        $dispatchMeta.pool_acceptance_contract_ok = $poolSummary.acceptance_contract_ok -eq $true
    }
    catch {
        if ($code -eq 0) { $code = 4 }
        $dispatchMeta.pool_exit_code = $code
        $dispatchMeta.pool_summary_error = [string]$_.Exception.Message
    }
}
elseif ($code -eq 0) {
    $code = 4
    $dispatchMeta.pool_exit_code = $code
    $dispatchMeta.pool_summary_error = "CODEX_GROK_POOL_SUMMARY_MISSING"
}
$dispatchMeta.status = if (
    $code -eq 0 -and
    $dispatchMeta.pool_all_ok -eq $true -and
    $dispatchMeta.pool_acceptance_contract_ok -eq $true
) { "accepted" } else { "rejected" }
[System.IO.File]::WriteAllText(
    $dispatchMetaPath,
    ($dispatchMeta | ConvertTo-Json -Depth 6),
    $utf8
)
Copy-Item $dispatchMetaPath (Join-Path $metaDir "latest.json") -Force

exit $code
