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

$taskId = "p0_007_default_main_loop_trigger_bind"
$sourcePackageId = "current_p0_three_text_20260707"
$currentIndexPath = Join-Path $RuntimeRoot "state\current_333_run_index\latest.json"
$workerBriefQueuePath = Join-Path $RuntimeRoot "state\worker_brief_queue\latest.json"
$contractPath = Join-Path $RuntimeRoot "state\task_contract_router\latest.json"
$tickPath = Join-Path $RuntimeRoot "state\codex_s_main_execution_loop_tick\temporal_activity_latest.json"
$triggerPath = Join-Path $RuntimeRoot "state\default_main_loop_trigger_candidate\temporal_activity_latest.json"
$aaqPath = Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json"

$currentIndex = Read-JsonFile $currentIndexPath
$workerBriefQueue = Read-JsonFile $workerBriefQueuePath
$contract = Read-JsonFile $contractPath
$tick = Read-JsonFile $tickPath
$trigger = Read-JsonFile $triggerPath
$aaq = Read-JsonFile $aaqPath

if ([string]::IsNullOrWhiteSpace($WorkflowId)) {
    $WorkflowId = [string]$currentIndex.workflow_id
}
if ([string]::IsNullOrWhiteSpace($WorkflowRunId)) {
    $WorkflowRunId = [string]$currentIndex.workflow_run_id
}

Assert-True ([string]$workerBriefQueue.schema_version -eq "xinao.codex_s.worker_brief_queue.v1") "WorkerBriefQueue schema mismatch."
Assert-True ([string]$workerBriefQueue.status -eq "worker_brief_queue_ready") "WorkerBriefQueue not ready."
Assert-True ([string]$workerBriefQueue.source_package_id -eq $sourcePackageId) "WorkerBriefQueue source package mismatch."
Assert-True ([int]$workerBriefQueue.brief_count -ge 3) "WorkerBriefQueue brief count too low."
Assert-True ($workerBriefQueue.dispatch_ready -eq $true) "WorkerBriefQueue is not dispatch-ready."
Assert-True ($workerBriefQueue.next_frontier_default_outlet -eq $false) "WorkerBriefQueue defaults to next_frontier."
Assert-True ([string]$workerBriefQueue.workflow_id -eq $WorkflowId) "WorkerBriefQueue workflow_id mismatch."
Assert-True ([string]$workerBriefQueue.workflow_run_id -eq $WorkflowRunId) "WorkerBriefQueue workflow_run_id mismatch."

$p007Decisions = @(Get-AcceptedDecisionsForCandidate -RuntimeRoot $RuntimeRoot -CandidateId $taskId)
$currentRouterIsP007 = [string]$contract.contract_id -eq $taskId
Assert-True ($currentRouterIsP007 -or $p007Decisions.Count -ge 1) "P0-007 is neither current router contract nor accepted episode."
Assert-True ($aaq.accepted_for_next_frontier_only -eq $false) "AAQ is still next_frontier-only."

$tickP007 = $tick.p0_007_default_main_loop_trigger_bind
Assert-True ($null -ne $tickP007) "Main tick missing P0-007 binding section."
Assert-True ($tick.runtime_entrypoint_invocation.runtime_enforced -eq $true) "Main tick was not runtime_enforced by Temporal activity."
Assert-True ($tickP007.default_main_loop_trigger_runtime_enforced -eq $true) "Main tick did not mark default trigger runtime enforcement."
Assert-True ($tickP007.current_worker_brief_queue_consumed_by_temporal_main_tick -eq $true) "Main tick did not consume current WorkerBrief queue."
Assert-True ([int]$tick.current_worker_brief_queue.brief_count -ge 3) "Main tick WorkerBrief count too low."
Assert-True ($tick.current_worker_brief_queue.consumed_by_temporal_main_tick -eq $true) "Main tick WorkerBrief binding not consumed."
Assert-True ($tickP007.accepted_for_next_frontier_default_outlet -eq $false) "Main tick routed P0-007 to next_frontier."

$triggerP007 = $trigger.p0_007_default_main_loop_trigger_bind
Assert-True ($null -ne $triggerP007) "Default trigger missing P0-007 binding section."
Assert-True ($trigger.runtime_entrypoint_invocation.runtime_enforced -eq $true) "Default trigger activity was not runtime_enforced."
Assert-True ($triggerP007.default_main_loop_trigger_runtime_enforced -eq $true) "Default trigger did not runtime-enforce P0-007."
Assert-True ($triggerP007.trigger_installed -eq $true) "Default trigger did not install task-scoped trigger."
Assert-True ($triggerP007.root_loop_every_wave_enforced_by_workflow_branch -eq $true) "Default trigger not bound to workflow branch."
Assert-True ($triggerP007.current_worker_brief_queue_consumed_by_temporal_main_tick -eq $true) "Default trigger did not inherit WorkerBrief consumption."
Assert-True ($triggerP007.accepted_for_next_frontier_default_outlet -eq $false) "Default trigger routed P0-007 to next_frontier."

$accepted = @($p007Decisions | Where-Object { [string]$_.artifact_acceptance_decision -eq "accepted_for_binding" })
Assert-True ($accepted.Count -ge 1) "AAQ did not accept P0-007 as accepted_for_binding."

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
    Assert-True ($activityNames -contains "main_execution_loop_tick_activity") "Temporal history missing main_execution_loop_tick_activity."
    Assert-True ($activityNames -contains "default_main_loop_trigger_candidate_activity") "Temporal history missing default_main_loop_trigger_candidate_activity."
}

Write-Output "worker_brief_queue_latest=$workerBriefQueuePath"
Write-Output "main_execution_loop_tick_temporal_activity_latest=$tickPath"
Write-Output "default_main_loop_trigger_candidate_temporal_activity_latest=$triggerPath"
Write-Output "artifact_acceptance_queue_latest=$aaqPath"
Write-Output "SENTINEL:XINAO_P0_007_CURRENT_WORKER_BRIEF_DEFAULT_TRIGGER_READY"
