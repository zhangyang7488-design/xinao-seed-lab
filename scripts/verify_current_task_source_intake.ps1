param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
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
    return $matches
}

$taskId = "p0_006_current_three_text_source_intake"
$sourcePackageId = "current_p0_three_text_20260707"
$latestPath = Join-Path $RuntimeRoot "state\current_task_source_intake\latest.json"
$sourceLedgerPath = Join-Path $RuntimeRoot "state\source_ledger\latest.json"
$workerBriefQueuePath = Join-Path $RuntimeRoot "state\worker_brief_queue\latest.json"
$compatWorkerBriefQueuePath = Join-Path $RuntimeRoot "state\worker_brief\latest.json"
$contractPath = Join-Path $RuntimeRoot "state\task_contract_router\latest.json"
$aaqPath = Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\current_task_source_intake_20260707.md"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.current_task_source_intake\manifest.json"

$latest = Read-JsonFile $latestPath
$sourceLedger = Read-JsonFile $sourceLedgerPath
$workerBriefQueue = Read-JsonFile $workerBriefQueuePath
$compatWorkerBriefQueue = Read-JsonFile $compatWorkerBriefQueuePath
$contract = Read-JsonFile $contractPath
$aaq = Read-JsonFile $aaqPath
$manifest = Read-JsonFile $manifestPath
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.current_task_source_intake.v1") "Intake schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_CURRENT_TASK_SOURCE_INTAKE_READY") "Intake sentinel mismatch."
Assert-True ([string]$latest.task_id -eq $taskId) "Intake task_id mismatch."
Assert-True ([string]$latest.status -eq "current_task_source_intake_ready") "Intake status is not ready."
Assert-True ([string]$latest.source_package_id -eq $sourcePackageId) "Source package id mismatch."
Assert-True ($latest.validation.passed -eq $true) "Intake validation did not pass."
Assert-True ($latest.validation.checks.all_package_refs_read_full -eq $true) "Package refs were not read in full."
Assert-True ($latest.validation.checks.source_entries_written -eq $true) "Source entries were not written."
Assert-True ($latest.validation.checks.worker_brief_queue_ready -eq $true) "WorkerBrief queue not ready."
Assert-True ($latest.validation.checks.briefs_bind_source_entries -eq $true) "Briefs are not source-bound."
Assert-True ($latest.validation.checks.frontier_not_default_exit -eq $true) "Intake defaulted to frontier."
Assert-True ($latest.completion_claim_allowed -eq $false) "Intake allowed completion claim."

Assert-True ([string]$sourceLedger.schema_version -eq "xinao.seedcortex.source_ledger.v1") "SourceLedger schema mismatch."
Assert-True ([string]$sourceLedger.status -eq "source_ledger_ready") "SourceLedger not ready."
Assert-True ([int]$sourceLedger.entry_count -ge 3) "SourceLedger entry count too low."
Assert-True ($sourceLedger.global_ledger -eq $true) "SourceLedger is not global."
Assert-True ($sourceLedger.private_ledger -eq $false) "SourceLedger is private."
Assert-True ($sourceLedger.completion_claim_allowed -eq $false) "SourceLedger allowed completion."
$sourceText = $sourceLedger | ConvertTo-Json -Depth 20 -Compress
Assert-True ($sourceText.Contains($sourcePackageId)) "SourceLedger missing current package id."

Assert-True ([string]$workerBriefQueue.schema_version -eq "xinao.codex_s.worker_brief_queue.v1") "WorkerBriefQueue schema mismatch."
Assert-True ([string]$workerBriefQueue.status -eq "worker_brief_queue_ready") "WorkerBriefQueue not ready."
Assert-True ([string]$workerBriefQueue.source_package_id -eq $sourcePackageId) "WorkerBriefQueue source package mismatch."
Assert-True ([int]$workerBriefQueue.brief_count -eq [int]$sourceLedger.entry_count) "Brief count must match source entries."
Assert-True ($workerBriefQueue.dispatch_ready -eq $true) "WorkerBriefQueue not dispatch ready."
Assert-True ($workerBriefQueue.next_frontier_default_outlet -eq $false) "WorkerBriefQueue defaults to frontier."
Assert-True ($workerBriefQueue.completion_claim_allowed -eq $false) "WorkerBriefQueue allowed completion."
Assert-True ([int]$compatWorkerBriefQueue.brief_count -eq [int]$workerBriefQueue.brief_count) "Compat worker brief queue mismatch."

foreach ($brief in @($workerBriefQueue.briefs)) {
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$brief.source_ledger_entry_id)) "Brief missing source ledger entry id."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$brief.source_ref)) "Brief missing source ref."
    Assert-True (@($brief.provider_candidates).Count -ge 1) "Brief missing provider candidates."
    Assert-True ($brief.worker_output_must_enter_staging -eq $true) "Brief can skip staging."
    Assert-True ($brief.completion_claim_allowed -eq $false) "Brief allowed completion."
}

$p006Decisions = @(Get-AcceptedDecisionsForCandidate -RuntimeRoot $RuntimeRoot -CandidateId $taskId)
$currentRouterIsP006 = [string]$contract.contract_id -eq $taskId
Assert-True ($currentRouterIsP006 -or $p006Decisions.Count -ge 1) "P0-006 is neither current router contract nor accepted episode."
Assert-True ([string]$contract.status -eq "execution_contract_ready") "Router latest not execution_contract_ready."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$contract.contract_id)) "Router contract_id missing."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$contract.workflow_run_id)) "Router workflow_run_id missing."

$p006Decision = @($p006Decisions | Select-Object -First 1)
Assert-True ($null -ne $p006Decision) "AAQ did not accept P0-006."
Assert-True ([string]$p006Decision.artifact_acceptance_decision -eq "accepted_for_delivery") "P0-006 was not accepted_for_delivery."
Assert-True ($aaq.accepted_for_next_frontier_only -eq $false) "AAQ is still next_frontier-only."
Assert-True (([int]$aaq.accepted_for_delivery_count -ge 1) -or ($p006Decisions.Count -ge 1)) "AAQ delivery acceptance missing."

Assert-True ([string]$manifest.provider_id -eq "codex_s.current_task_source_intake") "Manifest provider mismatch."
Assert-True ([string]$manifest.status -eq "registered") "Manifest not registered."
$invokeSection = -join @([char]0x73B0, [char]0x5728, [char]0x80FD, [char]0x20, [char]0x69, [char]0x6E, [char]0x76, [char]0x6F, [char]0x6B, [char]0x65, [char]0x20, [char]0x4EC0, [char]0x4E48)
Assert-True ($readback.Contains($invokeSection)) "Readback missing invoke section."

Write-Output "current_task_source_intake_latest=$latestPath"
Write-Output "source_ledger_latest=$sourceLedgerPath"
Write-Output "worker_brief_queue_latest=$workerBriefQueuePath"
Write-Output "artifact_acceptance_queue_latest=$aaqPath"
Write-Output "readback=$readbackPath"
Write-Output "SENTINEL:XINAO_CURRENT_TASK_SOURCE_INTAKE_READY"
