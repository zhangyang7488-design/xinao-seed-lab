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
  .\Invoke-GrokHostWorkerPoolFromTemporal.ps1 -N 1 -Prompt "Reply only: TEMPORAL_HOST_POOL_OK" -MaxTurns 1 -SkipPauseGate
  .\Invoke-GrokHostWorkerPoolFromTemporal.ps1 -N 2 -PromptFile .\task.md -Cwd E:\repo
#>
param(
    [ValidateRange(1, 32)]
    [int]$N = 1,
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

$stateRoot = "D:\XINAO_RESEARCH_RUNTIME\state\temporal_host_grok_pool"
$poolLatest = "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool\latest.json"
$codexDispatchLatest = "D:\XINAO_RESEARCH_RUNTIME\state\codex_dispatch_grok_worker_pool\latest.json"
$zhDir = "D:\XINAO_RESEARCH_RUNTIME\readback\zh"
New-Item -ItemType Directory -Force -Path $stateRoot, $zhDir | Out-Null

$triggerId = "thgp_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
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
    triggered_on = "windows_host"
    not_docker_worker = $true
    activity_name = $ActivityName
    activity_semantics_cn = "Temporal Activity 语义=触发 Host 上的 Grok WorkerPool；Grok 进程只在 Host 跑"
    workflow_id = $WorkflowId
    run_id = $RunId
    temporal_address_hint = "127.0.0.1:7233"
    n = $N
    model = $Model
    max_turns = $MaxTurns
    timeout_sec = $TimeoutSec
    cwd = if ($Cwd) { $Cwd } else { (Get-Location).Path }
    prompt_present = -not [string]::IsNullOrWhiteSpace($Prompt)
    prompt_file = $PromptFile
    host_entry_ps1 = $MyInvocation.MyCommand.Path
    dispatch_ps1 = $dispatch
    pool_latest = $poolLatest
    codex_dispatch_latest = $codexDispatchLatest
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
    MaxTurns = $MaxTurns
    TimeoutSec = $TimeoutSec
    GrokHome = $GrokHome
    MinResultChars = $MinResultChars
    RequiredResultMarkers = @($RequiredResultMarkers)
}
if ($RequireJsonObject) { $args.RequireJsonObject = $true }
if ($Prompt) { $args.Prompt = $Prompt }
if ($PromptFile) { $args.PromptFile = $PromptFile }
if ($Cwd) { $args.Cwd = $Cwd }
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
$meta.pool_latest = $poolLatest
$meta.codex_dispatch_latest = $codexDispatchLatest

# Attach pool snapshot refs if present
if (Test-Path -LiteralPath $poolLatest) {
    try {
        $pool = Get-Content -LiteralPath $poolLatest -Raw -Encoding UTF8 | ConvertFrom-Json
        $meta.pool_id = $pool.pool_id
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
    } catch { }
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
- pool_latest: $poolLatest
- codex_dispatch_latest: $codexDispatchLatest
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
