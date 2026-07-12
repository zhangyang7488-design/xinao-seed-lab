#Requires -Version 5.1
<#
.SYNOPSIS
  Explicit bootstrap/fallback entry: dispatch bounded Grok headless workers.
.DESCRIPTION
  Use only when the user explicitly requests a direct Grok batch, or when the
  canonical Temporal + houtai-gongren + LangGraph route is unavailable.
  Thin wrapper over Invoke-GrokWorkerPool.ps1 (CREATE_NO_WINDOW); never durable truth.
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
    [int]$MaxTurns = 8,
    [int]$TimeoutSec = 600,
    [string]$GrokHome = "C:\Users\xx363\.grok-4.5-lane",
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
$dispatchId = "cdx_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$utf8 = New-Object System.Text.UTF8Encoding $false

$dispatchMeta = [ordered]@{
    schema_version = "xinao.codex_dispatch_grok_worker_pool.v1"
    sentinel = "SENTINEL:CODEX_DISPATCH_GROK_WORKER_POOL"
    generated_at = (Get-Date).ToString("o")
    dispatch_id = $dispatchId
    role_cn = "explicit bootstrap/fallback -> bounded Grok headless worker pool"
    canonical_default_cn = "Temporal + Docker houtai-gongren + worker-internal LangGraph + dynamic Grok"
    not_default_cn = @(
        "codex_to_grok visible typeahead inject",
        "Docker integrated_bus Desktop .lnk"
    )
    n = $N
    model = $Model
    cwd = if ($Cwd) { $Cwd } else { (Get-Location).Path }
    pool_script = $pool
    completion_claim_allowed = $false
}
[System.IO.File]::WriteAllText(
    (Join-Path $metaDir ($dispatchId + ".json")),
    ($dispatchMeta | ConvertTo-Json -Depth 6),
    $utf8
)
Copy-Item (Join-Path $metaDir ($dispatchId + ".json")) (Join-Path $metaDir "latest.json") -Force

$args = @{
    N = $N
    Model = $Model
    MaxTurns = $MaxTurns
    TimeoutSec = $TimeoutSec
    GrokHome = $GrokHome
}
if ($Prompt) { $args.Prompt = $Prompt }
if ($PromptFile) { $args.PromptFile = $PromptFile }
if ($Cwd) { $args.Cwd = $Cwd }
if ($SkipPauseGate) { $args.SkipPauseGate = $true }
if ($Quiet) { $args.Quiet = $true }

& $pool @args
$code = $LASTEXITCODE

$dispatchMeta.finished_at = (Get-Date).ToString("o")
$dispatchMeta.pool_exit_code = $code
$dispatchMeta.pool_latest = "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool\latest.json"
[System.IO.File]::WriteAllText(
    (Join-Path $metaDir "latest.json"),
    ($dispatchMeta | ConvertTo-Json -Depth 6),
    $utf8
)

exit $code
