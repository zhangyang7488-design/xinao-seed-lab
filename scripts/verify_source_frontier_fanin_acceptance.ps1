param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$AnchorPackageRoot = (Join-Path (Join-Path $env:USERPROFILE "Desktop") (([string]([char]0x65B0)) + ([string]([char]0x7CFB)) + ([string]([char]0x7EDF)))),
    [string]$WaveId = "source-frontier-fanin-acceptance-wave-block3"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $RepoRoot "services\agent_runtime\source_frontier_fanin_acceptance.py"
$testPath = Join-Path $RepoRoot "tests\seedcortex\test_source_frontier_fanin_acceptance.py"
$schemaPath = Join-Path $RepoRoot "contracts\schemas\codex_s_source_frontier_fanin_acceptance.v1.json"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "source_frontier_fanin_acceptance py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "source_frontier_fanin_acceptance pytest failed."

$output = python $modulePath `
    --repo-root $RepoRoot `
    --runtime-root $RuntimeRoot `
    --anchor-package-root $AnchorPackageRoot `
    --wave-id $WaveId
$generationExitCode = $LASTEXITCODE
if ($generationExitCode -ne 0) {
    $output | ForEach-Object { Write-Output $_ }
}
Assert-True ($generationExitCode -eq 0) "source_frontier_fanin_acceptance generation failed."
Assert-True (($output -join "`n").Contains("SENTINEL:XINAO_SOURCE_FRONTIER_FANIN_ACCEPTANCE_READY")) "source frontier sentinel missing."

$latestPath = Join-Path $RuntimeRoot "state\source_frontier_fanin_acceptance\latest.json"
$assignmentPath = Join-Path $RuntimeRoot "state\worker_assignment\wave3_20260702_absorption_slice_20260704.json"
$parentAssignmentLinkPath = Join-Path $RuntimeRoot "state\worker_assignment\xinao_seed_cortex_phase0_20260701.current_source_frontier_slice.json"
$fanInPath = Join-Path $RuntimeRoot "state\fan_in_acceptance_queue\latest.json"
$parallelFanInPath = Join-Path $RuntimeRoot "state\parallel_fan_in_acceptance\latest.json"
$aaqPath = Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json"
$sourceLedgerPath = Join-Path $RuntimeRoot "state\source_ledger\latest.json"
$nextFrontierPath = Join-Path $RuntimeRoot "state\next_frontier_machine_actions\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\source_frontier_fanin_acceptance_20260704.md"

foreach ($path in @($schemaPath, $latestPath, $assignmentPath, $parentAssignmentLinkPath, $fanInPath, $parallelFanInPath, $aaqPath, $sourceLedgerPath, $nextFrontierPath, $readbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing source frontier evidence: $path"
}

$payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$assignment = Get-Content -LiteralPath $assignmentPath -Raw -Encoding UTF8 | ConvertFrom-Json
$parentAssignmentLink = Get-Content -LiteralPath $parentAssignmentLinkPath -Raw -Encoding UTF8 | ConvertFrom-Json
$fanIn = Get-Content -LiteralPath $fanInPath -Raw -Encoding UTF8 | ConvertFrom-Json
$aaq = Get-Content -LiteralPath $aaqPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceLedger = Get-Content -LiteralPath $sourceLedgerPath -Raw -Encoding UTF8 | ConvertFrom-Json
$nextFrontier = Get-Content -LiteralPath $nextFrontierPath -Raw -Encoding UTF8 | ConvertFrom-Json
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

Assert-True ($payload.schema_version -eq "xinao.codex_s.source_frontier_fanin_acceptance.v1") "Payload schema mismatch."
Assert-True ($payload.status -eq "source_frontier_fanin_acceptance_ready") "Source frontier payload not ready."
Assert-True ($payload.adoption_state -eq "default_hot_path_ready") "Source frontier adoption boundary mismatch."
Assert-True ($payload.work_id -eq "xinao_seed_cortex_phase0_20260701") "work_id mismatch."
Assert-True ($payload.parent_task_id -eq "xinao_seed_cortex_phase0_20260701") "parent_task_id mismatch."
Assert-True ($payload.task_id -eq "wave3_20260702_absorption_slice_20260704") "slice task_id mismatch."
Assert-True ($payload.routing -eq "continue_same_task") "routing mismatch."
Assert-True ($payload.runtime_enforced -eq $false) "Source frontier overclaimed runtime_enforced."
Assert-True ($payload.trigger_installed -eq $false) "Source frontier installed trigger unexpectedly."
Assert-True ($payload.source_package.all_required_sources_read_full -eq $true) "Authority source package not read full."
Assert-True ($assignment.parent_task_id -eq "xinao_seed_cortex_phase0_20260701") "Worker assignment parent_task_id mismatch."
Assert-True ($assignment.task_id -eq "wave3_20260702_absorption_slice_20260704") "Worker assignment slice task_id mismatch."
Assert-True ($assignment.routing -eq "continue_same_task") "Worker assignment routing mismatch."
Assert-True ($assignment.not_provider_scheduler_main_task -eq $true) "ProviderScheduler is still marked as main task."
Assert-True ($assignment.while_driver -eq "event_backlog_frontier_driven") "While driver is not event/backlog/frontier driven."
Assert-True ($assignment.forbid_fixed_interval_main_loop -eq $true) "Fixed interval main loop not forbidden."
Assert-True ($assignment.no_side_queue_island.not_new_bypass_queue -eq $true) "FanIn was allowed as bypass queue."
Assert-True ($parentAssignmentLink.root_task_not_claimed_complete -eq $true) "Parent link can be read as root completion."
Assert-True ($assignment.assignment_dag.current_active_node_id -eq "fan_in_acceptance_queue_default_heart") "Worker assignment DAG not on FanIn heart."
Assert-True ($fanIn.object_type -eq "FanInAcceptanceQueue") "Fan-in object type mismatch."
Assert-True ($fanIn.fan_in_is_default_heart -eq $true) "FanInAcceptanceQueue not marked as default heart."
Assert-True ($fanIn.not_new_bypass_queue -eq $true) "FanInAcceptanceQueue became a bypass island."
Assert-True (($fanIn.connects_existing_chain -join "|").Contains("draft_staging")) "FanIn does not connect draft_staging."
Assert-True (($fanIn.connects_existing_chain -join "|").Contains("merge")) "FanIn does not connect merge."
Assert-True (($fanIn.connects_existing_chain -join "|").Contains("next_frontier")) "FanIn does not connect next_frontier."
Assert-True ([int]$fanIn.accepted_edge_count -ge 1) "FanInAcceptanceQueue accepted no edges."
Assert-True ($fanIn.artifact_acceptance_queue_required -eq $true) "Fan-in did not require AAQ."
Assert-True ($aaq.claim_card_requires_source_ledger -eq $true) "AAQ does not require SourceLedger."
Assert-True ([int]$aaq.accepted_artifact_count -ge 1) "AAQ accepted no artifacts."
Assert-True ($sourceLedger.global_ledger -eq $true) "SourceLedger not global."
Assert-True ([int]$sourceLedger.entry_count -ge [int]$aaq.claim_card_source_ledger_entry_count) "SourceLedger entry count below AAQ count."
$remainingBatchCount = @($nextFrontier.source_frontier_gap.remaining_batch_ids).Count
if ($nextFrontier.source_frontier_gap.source_package_gap_open -eq $true) {
    Assert-True ($nextFrontier.should_continue_loop -eq $true) "Open source gap did not continue loop."
    Assert-True ($nextFrontier.stop_allowed -eq $false) "Open source gap incorrectly allowed stop."
    Assert-True ($remainingBatchCount -gt 0) "Open source gap has no remaining batch ids."
} else {
    Assert-True ($nextFrontier.should_continue_loop -eq $false) "Closed source gap still continues this wave3 module."
    Assert-True ($nextFrontier.stop_allowed -eq $true) "Closed source gap did not allow task-scoped wave3 stop."
    Assert-True ($remainingBatchCount -eq 0) "Closed source gap still has remaining batch ids."
}
Assert-True ($nextFrontier.while_driver -eq "event_backlog_frontier_driven") "Next frontier while driver mismatch."
Assert-True ($nextFrontier.sleep_1800_main_loop_allowed -eq $false) "sleep-1800 allowed as main loop."
Assert-True ($nextFrontier.fixed_interval_runner_main_loop_allowed -eq $false) "fixed interval allowed as main loop."
Assert-True (($nextFrontier.source_frontier_gap.source_package_gap_open -is [bool]) -or ($nextFrontier.source_frontier_gap.source_package_gap_open -is [System.Boolean])) "Source package gap was not answered as a boolean."
Assert-True ($payload.default_hot_path_binding.fan_in_acceptance_queue_default_heart -eq $true) "Default hot path did not bind FanIn heart."
Assert-True ($payload.default_hot_path_binding.fan_in_acceptance_queue_not_bypass_island -eq $true) "Default hot path allowed FanIn bypass island."
Assert-True ($payload.default_hot_path_binding.connects_existing_draft_staging_merge_aaq_next_frontier -eq $true) "Default hot path does not connect existing staging/merge/AAQ/next frontier."
Assert-True ($payload.default_hot_path_binding.provider_scheduler_main_task -eq $false) "Default hot path still treats ProviderScheduler as main task."
Assert-True ($payload.default_hot_path_binding.sleep_1800_main_loop_allowed -eq $false) "Default hot path allowed sleep-1800."
Assert-True ($payload.validation.passed -eq $true) "Source frontier validation failed."
Assert-True ($readback.Contains("source-frontier-fanin-acceptance")) "Readback missing invoke answer."
Assert-True ($readback.Contains("while")) "Readback missing while answer."
Assert-True ($readback.Contains("source frontier / source package gap")) "Readback missing source gap answer."
Assert-True ($readback.Contains("event/backlog/frontier driven")) "Readback missing event/backlog/frontier while."
Assert-True ($readback.Contains("SENTINEL:XINAO_SOURCE_FRONTIER_FANIN_ACCEPTANCE_READY")) "Readback missing sentinel."

Write-Output "source_frontier_fanin_acceptance_latest=$latestPath"
Write-Output "worker_assignment_latest=$assignmentPath"
Write-Output "parent_assignment_link=$parentAssignmentLinkPath"
Write-Output "fan_in_acceptance_queue_latest=$fanInPath"
Write-Output "artifact_acceptance_queue_latest=$aaqPath"
Write-Output "readback_zh=$readbackPath"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_SOURCE_FRONTIER_FANIN_ACCEPTANCE_READY"
