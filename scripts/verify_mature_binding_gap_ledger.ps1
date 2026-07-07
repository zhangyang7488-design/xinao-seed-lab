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

$taskId = "p0_005_mature_binding_gap_ledger"
$latestPath = Join-Path $RuntimeRoot "state\mature_binding_gap_ledger\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\mature_binding_gap_ledger_20260707.md"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.mature_binding_gap_ledger\manifest.json"
$contractPath = Join-Path $RuntimeRoot "state\task_contract_router\latest.json"
$aaqPath = Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json"

$latest = Read-JsonFile $latestPath
$manifest = Read-JsonFile $manifestPath
$contract = Read-JsonFile $contractPath
$aaq = Read-JsonFile $aaqPath
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.mature_binding_gap_ledger.v1") "Ledger schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_MATURE_BINDING_GAP_LEDGER_READY") "Ledger sentinel mismatch."
Assert-True ([string]$latest.task_id -eq $taskId) "Ledger task_id mismatch."
Assert-True ([string]$latest.status -eq "mature_binding_gap_ledger_ready") "Ledger status is not ready."
Assert-True ($latest.validation.passed -eq $true) "Ledger validation did not pass."
Assert-True ($latest.validation.checks.all_existing_state_dirs_classified -eq $true) "Not all state dirs were classified."
Assert-True ($latest.validation.checks.required_categories_present -eq $true) "Category set missing."
Assert-True ($latest.validation.checks.critical_gaps_identified -eq $true) "Critical gaps were not identified."
Assert-True ($latest.validation.checks.lying_layers_identified -eq $true) "Lying layers were not identified."
Assert-True ($latest.validation.checks.p0_004a_provider_lane_index_bound -eq $true) "P0-004a bound evidence missing."
Assert-True ($latest.validation.checks.p0_005_contract_ready -eq $true) "P0-005 contract not ready."
Assert-True ($latest.validation.checks.task_package_router_selected_p0_005 -eq $true) "Task package router did not select P0-005."
Assert-True ($latest.completion_claim_allowed -eq $false) "Ledger allowed completion claim."
Assert-True ($latest.not_execution_controller -eq $true) "Ledger is incorrectly marked controller."
Assert-True ([int]$latest.state_directory_count -ge [int]$latest.preexisting_state_directory_count) "State count regressed."
Assert-True ([int]$latest.classified_state_count -eq [int]$latest.state_directory_count) "classified_state_count mismatch."

foreach ($category in @("bound", "installed_not_bound", "not_applicable", "P1_deferred")) {
    Assert-True ($null -ne $latest.category_counts.$category) "Missing category count: $category"
}

$lyingIds = @($latest.lying_layers | ForEach-Object { [string]$_.state_id })
$workerDispatchClass = @($latest.classifications | Where-Object { [string]$_.state_id -eq "worker_dispatch_ledger" } | Select-Object -First 1)
$workerDispatchBound = $null -ne $workerDispatchClass -and [string]$workerDispatchClass.category -eq "bound"
if ($workerDispatchBound) {
    Assert-True ($workerDispatchClass.evidence.p0_008_real_receipt_ready -eq $true) "Worker dispatch ledger is bound without P0-008 real receipt evidence."
    Assert-True (-not ($lyingIds -contains "worker_dispatch_ledger")) "Bound worker_dispatch_ledger is still listed as lying."
} else {
    Assert-True ($lyingIds -contains "worker_dispatch_ledger") "Missing lying layer: worker_dispatch_ledger"
}
foreach ($stateId in @("root_intent_loop_driver", "codex_333_stateful_continuity_router", "source_ledger")) {
    if ($stateId -eq "source_ledger") {
        $sourceClass = @($latest.classifications | Where-Object { [string]$_.state_id -eq "source_ledger" } | Select-Object -First 1)
        if ($null -ne $sourceClass -and [string]$sourceClass.category -eq "installed_not_bound") {
            Assert-True ($lyingIds -contains $stateId) "Missing lying layer: $stateId"
        }
    } else {
        Assert-True ($lyingIds -contains $stateId) "Missing lying layer: $stateId"
    }
}

$criticalIds = @($latest.critical_gaps | ForEach-Object { [string]$_.state_id })
$defaultTriggerClass = @($latest.classifications | Where-Object { [string]$_.state_id -eq "default_main_loop_trigger_candidate" } | Select-Object -First 1)
$defaultTriggerBound = $null -ne $defaultTriggerClass -and [string]$defaultTriggerClass.category -eq "bound"
if (-not $defaultTriggerBound) {
    Assert-True ($criticalIds -contains "default_main_loop_trigger_candidate") "Missing critical gap: default_main_loop_trigger_candidate"
}
if ($workerDispatchBound) {
    Assert-True (-not ($criticalIds -contains "worker_dispatch_ledger")) "Bound worker_dispatch_ledger is still a critical gap."
} else {
    Assert-True ($criticalIds -contains "worker_dispatch_ledger") "Missing critical gap: worker_dispatch_ledger"
}

$p005Decisions = @(Get-AcceptedDecisionsForCandidate -RuntimeRoot $RuntimeRoot -CandidateId $taskId)
$currentRouterIsP005 = [string]$latest.task_contract_router.contract_id -eq $taskId
Assert-True ($currentRouterIsP005 -or $p005Decisions.Count -ge 1) "P0-005 is neither current router contract nor accepted episode."
Assert-True ([string]$contract.status -eq "execution_contract_ready") "Router latest not execution_contract_ready."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$contract.contract_id)) "Router latest contract_id missing."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$contract.workflow_run_id)) "Router contract workflow_run_id missing."
Assert-True ([string]$manifest.provider_id -eq "codex_s.mature_binding_gap_ledger") "Manifest provider mismatch."
Assert-True ([string]$manifest.status -eq "registered") "Manifest not registered."

$p005Decision = @($p005Decisions | Select-Object -First 1)
Assert-True ($null -ne $p005Decision) "AAQ did not accept P0-005."
Assert-True ([string]$p005Decision.artifact_acceptance_decision -eq "accepted_for_delivery") "P0-005 was not accepted_for_delivery."
Assert-True ($aaq.accepted_for_next_frontier_only -eq $false) "AAQ is still next_frontier-only."
Assert-True (([int]$aaq.accepted_for_delivery_count -ge 1) -or ($p005Decisions.Count -ge 1)) "AAQ delivery acceptance count missing."

$lyingSection = -join @([char]0x54EA, [char]0x5C42, [char]0x5728, [char]0x6492, [char]0x8C0E)
$nextActionSection = -join @([char]0x4E0B, [char]0x4E00, [char]0x673A, [char]0x5668, [char]0x52A8, [char]0x4F5C)
Assert-True ($readback.Contains($lyingSection)) "Readback missing lying-layer section."
Assert-True ($readback.Contains($nextActionSection)) "Readback missing next-machine-action section."

Write-Output "mature_binding_gap_ledger_latest=$latestPath"
Write-Output "task_contract_router_latest=$contractPath"
Write-Output "artifact_acceptance_queue_latest=$aaqPath"
Write-Output "readback=$readbackPath"
Write-Output "SENTINEL:XINAO_MATURE_BINDING_GAP_LEDGER_READY"
