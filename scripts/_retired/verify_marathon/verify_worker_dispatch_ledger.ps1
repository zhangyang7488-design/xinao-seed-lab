param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$WorkflowId = "",
    [string]$WorkflowRunId = "",
    [switch]$SkipTemporalHistory
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON file: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-AcceptedDecisionsForCandidate {
    param([string]$RuntimeRoot, [string]$CandidateId)
    $paths = @()
    $latest = Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json"
    if (Test-Path -LiteralPath $latest -PathType Leaf) {
        $paths += $latest
    }
    $episodesRoot = Join-Path $RuntimeRoot "runs\episodes"
    if (Test-Path -LiteralPath $episodesRoot -PathType Container) {
        $paths += @(Get-ChildItem -LiteralPath $episodesRoot -Recurse -Filter artifact_acceptance.json -File | ForEach-Object { $_.FullName })
    }
    $matches = @()
    foreach ($path in $paths) {
        $payload = Read-JsonFile $path
        foreach ($decision in @($payload.decisions)) {
            if ([string]$decision.candidate_id -eq $CandidateId -and [string]$decision.status -eq "accepted") {
                $matches += $decision
            }
        }
    }
    return @($matches)
}

function Get-TemporalActivityTypeNames {
    param($Events)
    $names = @()
    foreach ($event in @($Events)) {
        $attrs = $event.activityTaskScheduledEventAttributes
        if ($null -eq $attrs) { continue }
        $typeName = [string]$attrs.activityType.name
        if (-not [string]::IsNullOrWhiteSpace($typeName)) {
            $names += $typeName
        }
    }
    return @($names)
}

$taskId = "p0_008_worker_dispatch_real_receipt"
$sourcePackageId = "current_p0_three_text_20260707"
$currentIndexPath = Join-Path $RuntimeRoot "state\current_333_run_index\latest.json"
$workerBriefQueuePath = Join-Path $RuntimeRoot "state\worker_brief_queue\latest.json"
$dispatchPlanPath = Join-Path $RuntimeRoot "state\worker_brief_dispatch_plan\latest.json"
$ledgerPath = Join-Path $RuntimeRoot "state\worker_dispatch_ledger\latest.json"
$ledgerActivityPath = Join-Path $RuntimeRoot "state\worker_dispatch_ledger\temporal_activity_latest.json"
$contractPath = Join-Path $RuntimeRoot "state\task_contract_router\latest.json"
$aaqPath = Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json"

$currentIndex = Read-JsonFile $currentIndexPath
$workerBriefQueue = Read-JsonFile $workerBriefQueuePath
$dispatchPlan = Read-JsonFile $dispatchPlanPath
$ledger = Read-JsonFile $ledgerPath
$ledgerActivity = Read-JsonFile $ledgerActivityPath
$contract = Read-JsonFile $contractPath
$aaq = Read-JsonFile $aaqPath

if ([string]::IsNullOrWhiteSpace($WorkflowId)) {
    $WorkflowId = [string]$currentIndex.workflow_id
}
if ([string]::IsNullOrWhiteSpace($WorkflowRunId)) {
    $WorkflowRunId = [string]$currentIndex.workflow_run_id
}

Assert-True ([string]$workerBriefQueue.status -eq "worker_brief_queue_ready") "WorkerBriefQueue not ready."
Assert-True ([string]$workerBriefQueue.source_package_id -eq $sourcePackageId) "WorkerBriefQueue source package mismatch."
Assert-True ([int]$workerBriefQueue.brief_count -ge 3) "WorkerBriefQueue brief count too low."
Assert-True ($workerBriefQueue.dispatch_ready -eq $true) "WorkerBriefQueue is not dispatch-ready."
Assert-True ($workerBriefQueue.next_frontier_default_outlet -eq $false) "WorkerBriefQueue defaults to next_frontier."

Assert-True ([string]$dispatchPlan.contract_id -eq $taskId) "Dispatch plan is not P0-008."
Assert-True ([string]$dispatchPlan.status -eq "worker_brief_dispatch_plan_ready") "Dispatch plan not ready."
Assert-True ($dispatchPlan.validation.passed -eq $true) "Dispatch plan validation failed."
Assert-True ([int]$dispatchPlan.planned_worker_count -eq [int]$workerBriefQueue.brief_count) "Dispatch plan count does not match WorkerBriefQueue."
Assert-True ($dispatchPlan.dp_lane_assigned -eq $true) "Dispatch plan did not assign a DP lane."

$p008 = $ledger.p0_008_worker_dispatch_real_receipt
Assert-True ($null -ne $p008) "Ledger missing P0-008 receipt summary."
Assert-True ($ledger.validation.passed -eq $true) "Worker dispatch ledger validation failed."
Assert-True ($p008.worker_dispatch_real_receipt_ready -eq $true) "Worker dispatch real receipt is not ready."
Assert-True ([int]$p008.required_brief_count -eq [int]$workerBriefQueue.brief_count) "Required brief count mismatch."
Assert-True ([int]$p008.receipt_count -eq [int]$workerBriefQueue.brief_count) "Receipt count mismatch."
Assert-True ([int]$p008.succeeded_receipt_count -eq [int]$workerBriefQueue.brief_count) "Succeeded receipt count mismatch."
Assert-True ([int]$p008.dp_receipt_count -ge 1) "No DP receipt."
Assert-True ([int]$p008.phase1_receipt_count -eq 0) "Phase1 receipt was accepted."
Assert-True ([int]$p008.synthetic_succeeded_by_driver_count -eq 0) "Synthetic succeeded receipt was accepted."
Assert-True ([int]$ledger.summary.spawned_external_agent_count -eq [int]$workerBriefQueue.brief_count) "Spawned/receipt count does not match WorkerBriefQueue."
Assert-True ([int]$ledger.succeeded_count -eq [int]$workerBriefQueue.brief_count) "Ledger succeeded count mismatch."
Assert-True ($ledger.machine_loop.auto_dispatch_performed -eq $true) "Ledger did not mark task-scoped auto dispatch."
Assert-True ([string]$ledger.source_kind -eq "worker_dispatch_ledger_poll") "Ledger source_kind is not poll."

$briefIds = @($workerBriefQueue.briefs | ForEach-Object { [string]$_.worker_brief_id })
$pollEntries = @($ledger.poll_entries | Where-Object { $briefIds -contains [string]$_.worker_brief_id })
Assert-True ($pollEntries.Count -eq $briefIds.Count) "Poll entries do not cover every WorkerBrief."
foreach ($entry in $pollEntries) {
    Assert-True ([string]$entry.poll_status -eq "succeeded") "WorkerBrief receipt did not succeed: $($entry.worker_brief_id)"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$entry.actual_provider_id)) "Receipt missing actual_provider_id."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$entry.source_ledger_entry_id)) "Receipt missing source_ledger_entry_id."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$entry.source_ref)) "Receipt missing source_ref."
    Assert-True ($entry.synthetic_succeeded_by_driver -eq $false) "Receipt is synthetic."
    Assert-True ([string]$entry.transport_pattern_ref -ne "modular_dynamic_worker_pool_phase1") "Receipt came from phase1 pool."
}

$activityP008 = $ledgerActivity.p0_008_worker_dispatch_real_receipt
Assert-True ($null -ne $activityP008) "Temporal ledger activity missing P0-008 summary."
Assert-True ($ledgerActivity.worker_dispatch_real_receipt_ready -eq $true) "Temporal ledger activity did not expose ready=true."
Assert-True ([int]$ledgerActivity.actual_worker_result_count -eq [int]$workerBriefQueue.brief_count) "Temporal ledger activity worker result count mismatch."

$p008Decisions = @(Get-AcceptedDecisionsForCandidate -RuntimeRoot $RuntimeRoot -CandidateId $taskId)
$currentRouterIsP008 = [string]$contract.contract_id -eq $taskId
Assert-True ($currentRouterIsP008 -or $p008Decisions.Count -ge 1) "P0-008 is neither current router contract nor accepted episode."
$accepted = @($p008Decisions | Where-Object { [string]$_.artifact_acceptance_decision -eq "accepted_for_binding" })
Assert-True ($currentRouterIsP008 -or $accepted.Count -ge 1) "AAQ did not accept P0-008 as accepted_for_binding."
Assert-True ($accepted.Count -ge 1) "AAQ accepted episode for P0-008 is missing."

if (-not $SkipTemporalHistory) {
    Assert-True (-not [string]::IsNullOrWhiteSpace($WorkflowId)) "WorkflowId missing for Temporal history verification."
    Assert-True (-not [string]::IsNullOrWhiteSpace($WorkflowRunId)) "WorkflowRunId missing for Temporal history verification."
    $historyText = temporal workflow show --address 127.0.0.1:7233 --workflow-id $WorkflowId --run-id $WorkflowRunId --output json
    Assert-True ($LASTEXITCODE -eq 0) "Temporal workflow history read failed."
    $history = $historyText | ConvertFrom-Json
    $events = @()
    if ($null -ne $history.history.events) {
        $events = @($history.history.events)
    } elseif ($null -ne $history.events) {
        $events = @($history.events)
    }
    Assert-True ($events.Count -gt 0) "Temporal history returned no events."
    $activityNames = @(Get-TemporalActivityTypeNames $events)
    Assert-True ($activityNames -contains "worker_brief_dispatch_plan_activity") "Temporal history missing worker_brief_dispatch_plan_activity."
    Assert-True (($activityNames | Where-Object { $_ -eq "codex_worker_turn_activity" }).Count -ge [int]$workerBriefQueue.brief_count) "Temporal history has too few codex_worker_turn_activity events."
    Assert-True ($activityNames -contains "worker_dispatch_ledger_activity") "Temporal history missing worker_dispatch_ledger_activity."
}

Write-Output "worker_brief_dispatch_plan_latest=$dispatchPlanPath"
Write-Output "worker_dispatch_ledger_latest=$ledgerPath"
Write-Output "worker_dispatch_ledger_temporal_activity_latest=$ledgerActivityPath"
Write-Output "artifact_acceptance_queue_latest=$aaqPath"
Write-Output "SENTINEL:XINAO_P0_008_WORKER_DISPATCH_REAL_RECEIPT_READY"
