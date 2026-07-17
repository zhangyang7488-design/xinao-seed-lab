#Requires -Version 5.1
<#
.SYNOPSIS
  Temporal/Host thin trigger: schedule Grok WorkerPool on Windows Host only.
.DESCRIPTION
  Goal ⑤: Activity semantics = trigger Host pool. Grok processes run only on
  Windows Host (CREATE_NO_WINDOW). Never spawn grok inside Docker houtai-gongren,
  never read Desktop .lnk.

  Call chain:
    Temporal (or any host-side caller)
      -> Invoke-GrokHostWorkerPoolFromTemporal.ps1
      -> Invoke-CodexDispatchGrokWorkerPool.ps1
      -> Invoke-GrokWorkerPool.ps1
      -> N x Invoke-GrokComposer25Worker.ps1 (host)

  Alias entry: Invoke-GrokTemporalHostPoolTrigger.ps1 (same file body if copied).

.EXAMPLE
  .\Invoke-GrokHostWorkerPoolFromTemporal.ps1 -N 1 -Prompt "Reply only: TEMPORAL_HOST_POOL_OK" -Cwd E:\repo -Model grok-4.5 -SelectionPath D:\decision.json -MaxTurns 1 -SkipPauseGate
  .\Invoke-GrokHostWorkerPoolFromTemporal.ps1 -N 2 -PromptFile .\task.md -Cwd E:\repo -Model grok-4.5 -SelectionPath D:\decision.json
#>
param(
    [ValidateRange(1, 32)]
    [int]$N = 1,
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "",
    [string]$SelectionPath = "",
    [string]$MaxTurns = "auto",
    [int]$TimeoutSec = 600,
    [string]$GrokHome = "C:\Users\xx363\.grok-bg-workers",
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [string]$WorkflowId = "",
    [string]$RunId = "",
    [string]$ActivityName = "trigger_host_grok_worker_pool",
    [switch]$SkipPauseGate,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot

# Guard: must be Windows Host process (not container PID1 shape). Soft-fail open with marker.
$inContainerHint = $false
if (Test-Path -LiteralPath "/.dockerenv") { $inContainerHint = $true }
if ($env:XINAO_FORCE_HOST_POOL_IN_CONTAINER -ne "1") {
    if ($inContainerHint -or ($env:HOSTNAME -match "houtai-gongren|xinao-worker")) {
        throw "REFUSE_DOCKER_WORKER: Grok WorkerPool must run on Windows Host, not inside Docker (houtai-gongren). triggered_on=windows_host only."
    }
}

$dispatch = Join-Path $bridge "Invoke-CodexDispatchGrokWorkerPool.ps1"
if (-not (Test-Path -LiteralPath $dispatch)) {
    throw "MISSING_HOST_POOL: canonical dispatch wrapper unavailable: $dispatch"
}
$selectionHelper = Join-Path $bridge "GrokWorkerSelectionReceipt.ps1"
if (-not (Test-Path -LiteralPath $selectionHelper -PathType Leaf)) {
    throw "TEMPORAL_HOST_GROK_SELECTION_HELPER_MISSING: $selectionHelper"
}
. $selectionHelper
$selection = Read-GrokWorkerSelectionReceipt `
    -SelectionPath $SelectionPath `
    -Model $Model `
    -Cwd $Cwd `
    -RequiredPrefix "TEMPORAL_HOST_GROK"
$SelectionPath = [string]$selection.selection_path
$Model = [string]$selection.model_id
$Cwd = [string]$selection.cwd

$stateRoot = "D:\XINAO_RESEARCH_RUNTIME\state\temporal_host_grok_pool"
$poolLatestAdvisory = "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool\latest.json"
$codexDispatchRoot = "D:\XINAO_RESEARCH_RUNTIME\state\codex_dispatch_grok_worker_pool"
$codexDispatchLatestAdvisory = Join-Path $codexDispatchRoot "latest.json"
$zhDir = "D:\XINAO_RESEARCH_RUNTIME\readback\zh"
New-Item -ItemType Directory -Force -Path $stateRoot, $zhDir | Out-Null

$triggerId = "thgp_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$dispatchId = "cdx_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$poolId = "gwp_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$dispatchMetaPath = Join-Path $codexDispatchRoot ($dispatchId + ".json")
$poolSummaryPath = Join-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool" (
    $poolId + "\pool_summary.json"
)
$startedAt = (Get-Date).ToString("o")

# Hard policy: never touch Desktop .lnk (explicit deny)
$policy = [ordered]@{
    never_read_desktop_lnk = $true
    never_spawn_grok_in_docker = $true
    spawn_shape = "CREATE_NO_WINDOW on Windows Host"
    docker_worker_role_cn = "houtai-gongren = Temporal activity host for non-Grok work; not Grok CLI host"
}

$meta = [ordered]@{
    schema_version = "xinao.temporal_host_grok_pool.v1"
    sentinel = "SENTINEL:TEMPORAL_HOST_GROK_POOL"
    generated_at = $startedAt
    trigger_id = $triggerId
    dispatch_id = $dispatchId
    pool_id = $poolId
    triggered_on = "windows_host"
    not_docker_worker = $true
    activity_name = $ActivityName
    activity_semantics_cn = "Temporal Activity 语义=触发 Host 上的 Grok WorkerPool；Grok 进程只在 Host 跑"
    workflow_id = $WorkflowId
    run_id = $RunId
    temporal_address_hint = "127.0.0.1:7233"
    n = $N
    model = $Model
    selection_path = $SelectionPath
    selection_decision_sha256 = [string]$selection.decision_sha256
    selected_provider_id = [string]$selection.provider_id
    selected_profile_ref = [string]$selection.profile_ref
    selected_transport_id = [string]$selection.transport_id
    max_turns = $MaxTurns
    timeout_sec = $TimeoutSec
    cwd = $Cwd
    prompt_present = -not [string]::IsNullOrWhiteSpace($Prompt)
    prompt_file = $PromptFile
    json_schema_path = $JsonSchemaPath
    host_entry_ps1 = $MyInvocation.MyCommand.Path
    dispatch_ps1 = $dispatch
    pool_summary_path = $poolSummaryPath
    codex_dispatch_meta_path = $dispatchMetaPath
    pool_latest_advisory = $poolLatestAdvisory
    codex_dispatch_latest_advisory = $codexDispatchLatestAdvisory
    policy = $policy
    status = "starting"
    completion_claim_allowed = $false
}

function Write-TemporalHostPoolState {
    param($Obj)
    $json = ($Obj | ConvertTo-Json -Depth 10)
    $idPath = Join-Path $stateRoot ($Obj.trigger_id + ".json")
    [System.IO.File]::WriteAllText($idPath, $json, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $stateRoot "latest.json"), $json, $utf8)
}

Write-TemporalHostPoolState -Obj $meta

$args = @{
    N = $N
    Model = $Model
    SelectionPath = $SelectionPath
    ExpectedSelectionDecisionSha256 = [string]$selection.decision_sha256
    MaxTurns = $MaxTurns
    TimeoutSec = $TimeoutSec
    GrokHome = $GrokHome
    MinResultChars = $MinResultChars
    RequiredResultMarkers = @($RequiredResultMarkers)
    DispatchId = $dispatchId
    PoolId = $poolId
}
if ($RequireJsonObject) { $args.RequireJsonObject = $true }
if ($JsonSchemaPath) { $args.JsonSchemaPath = $JsonSchemaPath }
if ($Prompt) { $args.Prompt = $Prompt }
if ($PromptFile) { $args.PromptFile = $PromptFile }
$args.Cwd = $Cwd
if ($SkipPauseGate) { $args.SkipPauseGate = $true }
if ($Quiet) { $args.Quiet = $true }

if (-not $Quiet) {
    Write-Host "[temporal_host_grok_pool] trigger_id=$triggerId N=$N activity=$ActivityName host_only=true"
}

$code = 1
try {
    & $dispatch @args
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
} catch {
    $code = 1
    $meta.status = "failed"
    $meta.error = "$_"
    $meta.finished_at = (Get-Date).ToString("o")
    $meta.pool_exit_code = $code
    Write-TemporalHostPoolState -Obj $meta
    throw
}

$meta.finished_at = (Get-Date).ToString("o")
$meta.pool_exit_code = $code
$meta.status = if ($code -eq 0) { "pending_pool_acceptance" } else { "pool_nonzero_exit" }
$meta.pool_summary_path = $poolSummaryPath
$meta.codex_dispatch_meta_path = $dispatchMetaPath

# Bind this trigger to its exact dispatch and pool receipts. Shared latest files
# remain observation surfaces only and can never decide acceptance.
try {
    if (-not (Test-Path -LiteralPath $dispatchMetaPath -PathType Leaf)) {
        throw "TEMPORAL_HOST_EXACT_DISPATCH_RECEIPT_MISSING"
    }
    $dispatchReceipt = Get-Content -LiteralPath $dispatchMetaPath -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    if (
        [string]$dispatchReceipt.dispatch_id -ne $dispatchId -or
        [string]$dispatchReceipt.pool_id -ne $poolId -or
        [IO.Path]::GetFullPath([string]$dispatchReceipt.pool_summary_path) -ne [IO.Path]::GetFullPath($poolSummaryPath) -or
        -not [string]::Equals(
            [string]$dispatchReceipt.selection_decision_sha256,
            [string]$selection.decision_sha256,
            [StringComparison]::Ordinal
        )
    ) {
        throw "TEMPORAL_HOST_EXACT_DISPATCH_RECEIPT_ID_MISMATCH"
    }
    $meta.dispatch_receipt_sha256 = (
        Get-FileHash -LiteralPath $dispatchMetaPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (-not (Test-Path -LiteralPath $poolSummaryPath -PathType Leaf)) {
        throw "TEMPORAL_HOST_EXACT_POOL_SUMMARY_MISSING"
    }
    $poolSummarySha256 = (
        Get-FileHash -LiteralPath $poolSummaryPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ([string]$dispatchReceipt.pool_summary_sha256 -ne $poolSummarySha256) {
        throw "TEMPORAL_HOST_EXACT_POOL_SUMMARY_HASH_MISMATCH"
    }
    $pool = Get-Content -LiteralPath $poolSummaryPath -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    if ([string]$pool.pool_id -ne $poolId) {
        throw "TEMPORAL_HOST_EXACT_POOL_SUMMARY_ID_MISMATCH"
    }
        $meta.pool_summary_sha256 = $poolSummarySha256
        $meta.pool_all_ok = $pool.all_ok
        $meta.pool_ok_count = $pool.ok_count
        $meta.pool_fail_count = $pool.fail_count
        $meta.pool_acceptance_contract_ok = $pool.acceptance_contract_ok -eq $true
        if ($code -eq 0 -and $pool.all_ok -eq $true -and $pool.acceptance_contract_ok -eq $true) {
            $meta.status = "accepted"
        }
        elseif ($code -eq 0) {
            $code = 3
            $meta.pool_exit_code = $code
            $meta.status = "rejected_pool_acceptance"
        }
}
catch {
    $meta.exact_receipt_error = [string]$_.Exception.Message
    if ($code -eq 0) {
        $code = 3
        $meta.pool_exit_code = $code
        $meta.status = "rejected_exact_receipt"
    }
}

Write-TemporalHostPoolState -Obj $meta

$zhPath = Join-Path $zhDir "temporal_host_grok_pool_latest.md"
$zh = @"
# Temporal Host Grok Pool 触发 $triggerId

- **triggered_on:** windows_host
- **not_docker_worker:** true
- **activity:** $ActivityName
- **语义:** Activity 只调度 Host 上的 Grok WorkerPool；不在 Docker 跑 grok；不读桌面 .lnk
- n=$N exit=$code status=$($meta.status)
- pool_summary: $poolSummaryPath
- codex_dispatch_receipt: $dispatchMetaPath
- state: $stateRoot\latest.json
- workflow_id: $WorkflowId
- run_id: $RunId
- completion_claim_allowed: false
"@
[System.IO.File]::WriteAllText($zhPath, $zh, $utf8)

if (-not $Quiet) {
    Write-Host "[temporal_host_grok_pool] done status=$($meta.status) exit=$code state=$stateRoot\latest.json"
}

exit $code
