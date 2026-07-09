#Requires -Version 5.1
<#
.SYNOPSIS
  P0-S2/S3/S4：staged intake → XINAO_Base Compose → SDK claim_durable（无 ps1 orchestrator）。
  薄绑 S 仓；Grok 不当 Temporal owner。
#>
param(
    [string]$IntakeTaskId = "",
    [string]$ConfigPath = "",
    [switch]$SkipTemporalStart,
    [switch]$SkipWorkerStart,
    [switch]$AutoWaveClosure,
    [int]$WaveWaitSeconds = 60,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8

$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $ConfigPath
$sRepo = [string]$config.repo_root
$stateRoot = Join-Path $runtime "state\task_entry"
$claimDir = Join-Path $stateRoot "durable_claim"
New-Item -ItemType Directory -Force -Path $claimDir | Out-Null

# --- mature glue (S 仓 · 黄金路径 Compose；旧 ps1 仅 dev_rescue) ---
$composeFile = Join-Path $sRepo "docker-compose.yml"
$claimModule = "services.agent_runtime.task_entry_claim"
$glue = [ordered]@{
    compose_file        = $composeFile
    base_compose_start  = Join-Path $sRepo "scripts\Start-XinaoBaseCompose.ps1"
    base_compose_status = Join-Path $sRepo "scripts\Status-XinaoBaseCompose.ps1"
    claim_durable_sdk   = $claimModule
    temporal_status     = Join-Path $sRepo "scripts\Status-XinaoTemporalCodexWorker.ps1"
    dev_rescue_temporal = Join-Path $sRepo "scripts\start_temporal_dev_server.ps1"
    dev_rescue_worker   = Join-Path $sRepo "scripts\Start-XinaoTemporalCodexWorker.ps1"
}

foreach ($k in @("base_compose_start", "base_compose_status", "compose_file")) {
    if (-not (Test-Path -LiteralPath $glue[$k])) {
        throw "Mature glue missing: $k -> $($glue[$k])"
    }
}

function Invoke-TaskEntryClaimSdk {
    param([string]$TaskId, [string]$Runtime, [string]$Repo)
    $cn = & (Join-Path $bridge "Invoke-GrokResolveComposeNames.ps1") -ConfigPath $ConfigPath
    $workerCtn = [string]$cn.worker_container
    $temporalHost = "naijiu-shiwu:7233"
    $workerUp = $false
    try {
        $names = docker ps --format "{{.Names}}" 2>&1 | Out-String
        foreach ($slug in @($cn.worker.slug_set)) {
            if ($slug -and ($names -match [regex]::Escape($slug))) { $workerUp = $true; break }
        }
    } catch { }
    if ($workerUp) {
        $raw = (docker exec $workerCtn python -m $claimModule --task-id $TaskId --address $temporalHost 2>$null | Out-String)
        if (-not $raw.Trim()) {
            $raw = (docker exec $workerCtn python -m $claimModule --task-id $TaskId --address $temporalHost 2>&1 | Out-String)
        }
        return (Extract-ClaimJsonLine $raw)
    }
    $py = Join-Path $Repo ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $py)) { throw "SDK claim requires $workerCtn ($($cn.worker_display_cn)) container or S .venv" }
    $hostRaw = (& $py -m $claimModule --task-id $TaskId --runtime-root $Runtime --repo-root $Repo --address 127.0.0.1:7233 2>&1 | Out-String)
    return (Extract-ClaimJsonLine $hostRaw)
}

function Extract-ClaimJsonLine([string]$Raw) {
    if (-not $Raw) { return "" }
    $lines = $Raw -split "`r?`n" | Where-Object { $_.Trim().StartsWith("{") -and $_.Trim().EndsWith("}") }
    if ($lines.Count -gt 0) { return ($lines[-1]).Trim() }
    return $Raw
}

# --- load staged intake ---
$latestPath = Join-Path $stateRoot "latest.json"
if (-not (Test-Path -LiteralPath $latestPath)) {
    throw "No staged intake. Run Invoke-GrokTaskEntry.ps1 first."
}
$intake = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($IntakeTaskId -and $intake.task_id -ne $IntakeTaskId) {
    $candidate = Join-Path $stateRoot "intake\$IntakeTaskId.json"
    if (Test-Path -LiteralPath $candidate) {
        $intake = Get-Content -LiteralPath $candidate -Raw -Encoding UTF8 | ConvertFrom-Json
    }
}

$steps = [System.Collections.Generic.List[object]]::new()
function Add-Step([string]$Id, [string]$Status, [hashtable]$Extra = @{}) {
    $s = [ordered]@{ id = $Id; status = $Status; at = (Get-Date).ToString("o") }
    foreach ($k in $Extra.Keys) { $s[$k] = $Extra[$k] }
    $steps.Add([pscustomobject]$s) | Out-Null
}

# P0-S2 Base Compose（Temporal + Worker 容器 · 脊柱不变）
$temporalOk = $false
$workerOk = $false
if (-not $SkipTemporalStart) {
    try {
        $composeArgs = @{ RuntimeRoot = $runtime; RepoRoot = $sRepo }
        if (-not $SkipWorkerStart) { $composeArgs.Build = $true }
        $null = & $glue.base_compose_start @composeArgs 2>&1 | Out-String
        $cEv = Join-Path $runtime "state\xinao_base_compose\latest.json"
        if (Test-Path -LiteralPath $cEv) {
            $cj = Get-Content $cEv -Raw -Encoding UTF8 | ConvertFrom-Json
            $temporalOk = ($cj.status -eq "running" -or $cj.temporal_ok -eq $true)
            Add-Step "P0-S2_base_compose" $(if ($temporalOk) { "done" } else { "blocked" }) @{
                compose_status = $cj.status; blocker = $cj.named_blocker; golden_path = $cj.golden_path
            }
        } else {
            Add-Step "P0-S2_base_compose" "failed" @{ error = "no compose evidence json" }
        }
    } catch {
        Add-Step "P0-S2_base_compose" "failed" @{ error = $_.Exception.Message }
    }
} else {
    $temporalOk = [bool](Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue).TcpTestSucceeded
    Add-Step "P0-S2_base_compose" "skipped" @{ temporal_7233 = $temporalOk }
}

# P0-S3 Worker（Compose 容器证据 + task-queue poller）
if ($temporalOk -and -not $SkipWorkerStart) {
    try {
        Start-Sleep -Seconds 15
        $statusJson = & $glue.base_compose_status -RuntimeRoot $runtime -RepoRoot $sRepo 2>&1 | Out-String
        $busWorkerEv = Join-Path $runtime "state\integrated_bus_worker_daemon\latest.json"
        if ($statusJson) {
            try {
                $sj = $statusJson | ConvertFrom-Json
                $workerOk = ($sj.worker_daemon_ok -eq $true -or $sj.worker_ready -eq $true)
            } catch { }
        }
        if (-not $workerOk -and (Test-Path -LiteralPath $busWorkerEv)) {
            $bj = Get-Content $busWorkerEv -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($bj.status -eq "polling" -and $bj.binding_count -gt 0) { $workerOk = $true }
        }
        if (-not $workerOk) {
            $wStatus = & $glue.temporal_status -RuntimeRoot $runtime 2>&1 | Out-String
            if ($wStatus) {
                try {
                    $wj = $wStatus | ConvertFrom-Json
                    $workerOk = ($wj.polling_worker_ready -eq $true -or $wj.fresh_poller_count -gt 0)
                } catch { }
            }
        }
        Add-Step "P0-S3_worker" $(if ($workerOk) { "done" } else { "partial" }) @{
            carrier = "houtai-gongren（后台工人）"; integrated_bus_evidence = (Test-Path -LiteralPath $busWorkerEv)
        }
    } catch {
        Add-Step "P0-S3_worker" "failed" @{ error = $_.Exception.Message }
    }
} elseif (-not $temporalOk) {
    Add-Step "P0-S3_worker" "blocked" @{ blocker = "TEMPORAL_7233_DOWN" }
} elseif ($SkipWorkerStart) {
    $workerOk = $true
    Add-Step "P0-S3_worker" "skipped"
}

# P0-S4 staged → live WF (Temporal SDK · task_entry_claim)
$intent = [string]$intake.intent_one_liner
$claimState = "claim_blocked"
$durableRef = ""
$wfId = ""
$runId = ""
$blockers = [System.Collections.Generic.List[string]]::new()
$wpFile = ""

if (-not $temporalOk) { [void]$blockers.Add("TEMPORAL_7233_DOWN") }
if (-not $workerOk) { [void]$blockers.Add("TEMPORAL_WORKER_NOT_READY") }

if ($temporalOk -and $workerOk) {
    try {
        $claimOut = Invoke-TaskEntryClaimSdk -TaskId ([string]$intake.task_id) -Runtime $runtime -Repo $sRepo
        $claimJson = $null
        try { $claimJson = $claimOut | ConvertFrom-Json } catch { }
        if ($claimJson) {
            $claimState = [string]$claimJson.claim_state
            $durableRef = [string]$claimJson.durable_evidence_ref
            $wfId = [string]$claimJson.temporal_workflow_id
            $runId = [string]$claimJson.temporal_workflow_run_id
            $wpFile = [string]$claimJson.work_package_ref
            if ($claimJson.named_blockers) { foreach ($b in @($claimJson.named_blockers)) { [void]$blockers.Add([string]$b) } }
            Add-Step "P0-S4_sdk_claim" $(if ($claimState -eq "durable_claimed") { "done" } else { "partial" }) @{
                carrier = "task_entry_claim"; workflow_id = $wfId; run_id = $runId
            }
        } else {
            $claimState = "claim_failed"
            [void]$blockers.Add("CLAIM_SDK_NO_JSON")
            Add-Step "P0-S4_sdk_claim" "failed" @{ raw = $claimOut.Substring(0, [Math]::Min(500, $claimOut.Length)) }
        }
    } catch {
        $claimState = "claim_failed"
        [void]$blockers.Add($_.Exception.Message)
        Add-Step "P0-S4_sdk_claim" "failed" @{ error = $_.Exception.Message }
    }
} elseif (-not $temporalOk -or -not $workerOk) {
    Add-Step "P0-S4_sdk_claim" "blocked" @{ blockers = @($blockers) }
}

# reload intake after SDK wrote claim fields
if (Test-Path -LiteralPath $latestPath) {
    $intake = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $claimState = [string]$intake.claim_state
    $durableRef = [string]$intake.durable_evidence_ref
    $wfId = [string]$intake.temporal_workflow_id
    $runId = [string]$intake.temporal_workflow_run_id
    if ($intake.named_blockers) { $blockers = [System.Collections.Generic.List[string]]::new(); foreach ($b in @($intake.named_blockers)) { [void]$blockers.Add([string]$b) } }
}

$report = [ordered]@{
    schema_version = "xinao.task_entry.durable_claim.v2"
    generated_at   = (Get-Date).ToString("o")
    intake_task_id = $intake.task_id
    claim_state    = $claimState
    mature_glue    = $glue
    steps          = $steps
    durable_evidence_ref = $durableRef
    temporal_workflow_id = $wfId
    temporal_workflow_run_id = $runId
    named_blockers = @($blockers)
    work_package_ref = $wpFile
    stack_version  = "XINAO_Base_V2_unified"
    completion_claim_allowed = $false
}
$reportLatest = Join-Path $claimDir "latest.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportLatest -Encoding UTF8

if ($AutoWaveClosure -and $claimState -eq "durable_claimed") {
    $cont = Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1"
    $gap = Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1"
    if (Test-Path -LiteralPath $cont) {
        & $cont -WaitSeconds $WaveWaitSeconds -ConfigPath $ConfigPath -Quiet | Out-Null
    }
    if (Test-Path -LiteralPath $gap) {
        & $gap -ConfigPath $ConfigPath -Quiet | Out-Null
    }
}

if (-not $Quiet) { $report | ConvertTo-Json -Depth 8 }