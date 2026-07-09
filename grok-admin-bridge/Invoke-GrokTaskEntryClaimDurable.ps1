#Requires -Version 5.1
<#
.SYNOPSIS
  P0-S2/S3/S4：staged intake → 成熟胶水起 Temporal+Worker → RootIntentLoop live WF。
  薄绑 S 仓脚本；Grok 不当 Temporal owner。
#>
param(
    [string]$IntakeTaskId = "",
    [string]$ConfigPath = "",
    [switch]$SkipTemporalStart,
    [switch]$SkipWorkerStart,
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
$glue = [ordered]@{
    base_compose_start  = Join-Path $sRepo "scripts\Start-XinaoBaseCompose.ps1"
    base_compose_status = Join-Path $sRepo "scripts\Status-XinaoBaseCompose.ps1"
    temporal_status     = Join-Path $sRepo "scripts\Status-XinaoTemporalCodexWorker.ps1"
    root_intent_driver  = Join-Path $sRepo "scripts\hardmode\Invoke-CodexSRootIntentLoopDriver.ps1"
    dev_rescue_temporal = Join-Path $sRepo "scripts\start_temporal_dev_server.ps1"
    dev_rescue_worker   = Join-Path $sRepo "scripts\Start-XinaoTemporalCodexWorker.ps1"
}

foreach ($k in $glue.Keys) {
    if (-not (Test-Path -LiteralPath $glue[$k] -PathType Leaf)) {
        throw "Mature glue missing: $k -> $($glue[$k])"
    }
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
            carrier = "xinao-worker container"; integrated_bus_evidence = (Test-Path -LiteralPath $busWorkerEv)
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

# P0-S4 staged → live WF (RootIntentLoop mature entry)
$intent = [string]$intake.intent_one_liner
$materialRefs = @()
if ($intake.l0_intake.material_refs) { $materialRefs = @($intake.l0_intake.material_refs) }
$wp = [ordered]@{
    objective    = $intent
    task_entry_id = [string]$intake.task_id
    entry_kind   = [string]$intake.entry_kind
    source_kind  = "grok_task_entry_intake"
    intake_ref   = $latestPath
    acceptance   = if ($intake.l1_structured.acceptance) { @($intake.l1_structured.acceptance) } else { @() }
}
$wpFile = Join-Path $claimDir ("work_package_{0}.json" -f $intake.task_id)
$wp | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $wpFile -Encoding UTF8

$claimState = "claim_blocked"
$durableRef = ""
$wfId = ""
$runId = ""
$blockers = [System.Collections.Generic.List[string]]::new()

if (-not $temporalOk) { [void]$blockers.Add("TEMPORAL_7233_DOWN") }
if (-not $workerOk) { [void]$blockers.Add("TEMPORAL_WORKER_NOT_READY") }

if ($temporalOk) {
    try {
        $drv = & $glue.root_intent_driver `
            -RuntimeRoot $runtime `
            -RepoRoot $sRepo `
            -ForceInvoke `
            -RunLiveTemporal `
            -SkipLocalDriver `
            -WorkPackageJson $wpFile `
            -SourceRef @($materialRefs | Where-Object { $_ }) `
            -Quiet 2>&1 | Out-String
        $hookLatest = Join-Path $runtime "state\root_intent_loop_driver_hook\latest.json"
        $twLatest = Join-Path $runtime "state\temporal_codex_task_workflow\latest.json"
        if (Test-Path -LiteralPath $twLatest) {
            $tw = Get-Content $twLatest -Raw -Encoding UTF8 | ConvertFrom-Json
            $wfId = [string]$tw.workflow_id
            $runId = [string]$tw.workflow_run_id
            if ($tw.server_bound -eq $true -and $runId) {
                $claimState = "durable_claimed"
                $durableRef = $twLatest
                Add-Step "P0-S4_start_wf" "done" @{ workflow_id = $wfId; run_id = $runId }
            } else {
                $claimState = "claim_attempted_not_server_bound"
                if ($tw.named_blocker) { [void]$blockers.Add([string]$tw.named_blocker) }
                Add-Step "P0-S4_start_wf" "partial" @{ status = $tw.status }
            }
        } else {
            $claimState = "claim_attempted_no_temporal_evidence"
            [void]$blockers.Add("TEMPORAL_WORKFLOW_EVIDENCE_MISSING")
            Add-Step "P0-S4_start_wf" "failed"
        }
    } catch {
        $claimState = "claim_failed"
        [void]$blockers.Add($_.Exception.Message)
        Add-Step "P0-S4_start_wf" "failed" @{ error = $_.Exception.Message }
    }
}

# update intake latest claim fields
$intakeHash = @{}
$intake.PSObject.Properties | ForEach-Object { $intakeHash[$_.Name] = $_.Value }
$intakeHash.claim_state = $claimState
$intakeHash.durable_claim_at = (Get-Date).ToString("o")
$intakeHash.durable_evidence_ref = $durableRef
$intakeHash.temporal_workflow_id = $wfId
$intakeHash.temporal_workflow_run_id = $runId
$intakeHash.named_blockers = @($blockers)
$intakeHash.readback_three_cn = @(
    "①入口读到：$($intake.entry_kind) / $intent",
    "②durable认领证据：$(if ($durableRef) { $durableRef } else { '无（' + $claimState + '）' })",
    "③blocker：$(if ($blockers.Count) { ($blockers -join '；') } else { '无' })"
)
$intakeOut = [pscustomobject]$intakeHash
$json = $intakeOut | ConvertTo-Json -Depth 12
[System.IO.File]::WriteAllText($latestPath, $json, $utf8)
$claimRecord = Join-Path $claimDir ("claim_{0}.json" -f $intake.task_id)
[System.IO.File]::WriteAllText($claimRecord, $json, $utf8)

$report = [ordered]@{
    schema_version = "xinao.task_entry.durable_claim.v1"
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
    completion_claim_allowed = $false
}
$reportLatest = Join-Path $claimDir "latest.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportLatest -Encoding UTF8

if (-not $Quiet) { $report | ConvertTo-Json -Depth 8 }