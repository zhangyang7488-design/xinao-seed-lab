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

# --- mature glue (S 仓 · 禁止手搓平行 orchestrator) ---
$glue = [ordered]@{
    temporal_dev_server = Join-Path $sRepo "scripts\start_temporal_dev_server.ps1"
    temporal_worker     = Join-Path $sRepo "scripts\Start-XinaoTemporalCodexWorker.ps1"
    temporal_status     = Join-Path $sRepo "scripts\Status-XinaoTemporalCodexWorker.ps1"
    root_intent_driver  = Join-Path $sRepo "scripts\hardmode\Invoke-CodexSRootIntentLoopDriver.ps1"
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

# P0-S2 Temporal
$temporalOk = $false
if (-not $SkipTemporalStart) {
    try {
        $tOut = & $glue.temporal_dev_server -RuntimeRoot $runtime 2>&1 | Out-String
        $tEv = Join-Path $runtime "state\temporal_dev_server\latest.json"
        if (Test-Path -LiteralPath $tEv) {
            $tj = Get-Content $tEv -Raw -Encoding UTF8 | ConvertFrom-Json
            $temporalOk = ($tj.status -in @("running", "already_running"))
            Add-Step "P0-S2_temporal" $(if ($temporalOk) { "done" } else { "blocked" }) @{
                status = $tj.status; blocker = $tj.named_blocker
            }
        } else {
            Add-Step "P0-S2_temporal" "failed" @{ error = "no evidence json" }
        }
    } catch {
        Add-Step "P0-S2_temporal" "failed" @{ error = $_.Exception.Message }
    }
} else {
    $temporalOk = $true
    Add-Step "P0-S2_temporal" "skipped"
}

# P0-S3 Worker
$workerOk = $false
if ($temporalOk -and -not $SkipWorkerStart) {
    try {
        & $glue.temporal_worker -RepoRoot $sRepo -RuntimeRoot $runtime 2>&1 | Out-Null
        Start-Sleep -Seconds 5
        $wStatus = & $glue.temporal_status -RuntimeRoot $runtime 2>&1 | Out-String
        $wEv = Join-Path $runtime "state\temporal_codex_task_worker\status.json"
        if (Test-Path -LiteralPath $wEv) {
            $wj = Get-Content $wEv -Raw -Encoding UTF8 | ConvertFrom-Json
            $workerOk = ($wj.polling_worker_ready -eq $true -or $wj.process_alive -eq $true -or $wj.fresh_poller_count -gt 0)
            Add-Step "P0-S3_worker" $(if ($workerOk) { "done" } else { "partial" }) @{
                fresh_pollers = $wj.fresh_poller_count; process_alive = $wj.process_alive
            }
        } else {
            Add-Step "P0-S3_worker" "partial"
        }
    } catch {
        Add-Step "P0-S3_worker" "failed" @{ error = $_.Exception.Message }
    }
} elseif (-not $temporalOk) {
    Add-Step "P0-S3_worker" "blocked" @{ blocker = "TEMPORAL_7233_DOWN" }
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
        $srcArgs = @()
        foreach ($r in $materialRefs) { if ($r) { $srcArgs += @("-SourceRef", $r) } }
        $drv = & $glue.root_intent_driver `
            -RuntimeRoot $runtime `
            -RepoRoot $sRepo `
            -ForceInvoke `
            -RunLiveTemporal `
            -SkipLocalDriver `
            -WorkPackageJson $wpFile `
            @srcArgs `
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