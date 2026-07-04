param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$AnchorPackageRoot = (Join-Path (Join-Path $env:USERPROFILE "Desktop") (([string]([char]0x65B0)) + ([string]([char]0x7CFB)) + ([string]([char]0x7EDF)))),
    [string]$WaveId = "wave-block4-20260701-source-family"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $RepoRoot "services\agent_runtime\source_family_wave_scheduler.py"
$testPath = Join-Path $RepoRoot "tests\seedcortex\test_source_family_wave_scheduler.py"
$schemaPath = Join-Path $RepoRoot "contracts\schemas\codex_s_source_family_wave_scheduler.v1.json"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "source_family_wave_scheduler py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "source_family_wave_scheduler pytest failed."

$output = python $modulePath `
    --repo-root $RepoRoot `
    --runtime-root $RuntimeRoot `
    --anchor-package-root $AnchorPackageRoot `
    --wave-id $WaveId
$generationExitCode = $LASTEXITCODE
if ($generationExitCode -ne 0) {
    $output | ForEach-Object { Write-Output $_ }
}
Assert-True ($generationExitCode -eq 0) "source_family_wave_scheduler generation failed."
Assert-True (($output -join "`n").Contains("SENTINEL:XINAO_SOURCE_FAMILY_WAVE_SCHEDULER_READY")) "source family sentinel missing."

$latestPath = Join-Path $RuntimeRoot "state\source_family_wave_scheduler\latest.json"
$planPath = Join-Path $RuntimeRoot "state\source_family_wave_plan\latest.json"
$claimPath = Join-Path $RuntimeRoot "state\claim_card_staging_queue\latest.json"
$fanInPath = Join-Path $RuntimeRoot "state\fan_in_acceptance_queue\latest.json"
$aaqPath = Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json"
$sourceLedgerPath = Join-Path $RuntimeRoot "state\source_ledger\latest.json"
$nextFrontierPath = Join-Path $RuntimeRoot "state\next_frontier_machine_actions\latest.json"
$hygienePath = Join-Path $RuntimeRoot "state\background_window_hygiene\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\wave_block4_20260701_frontier_20260704.md"

foreach ($path in @($schemaPath, $latestPath, $planPath, $claimPath, $fanInPath, $aaqPath, $sourceLedgerPath, $nextFrontierPath, $hygienePath, $readbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing source family evidence: $path"
}

$payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$claim = Get-Content -LiteralPath $claimPath -Raw -Encoding UTF8 | ConvertFrom-Json
$fanIn = Get-Content -LiteralPath $fanInPath -Raw -Encoding UTF8 | ConvertFrom-Json
$aaq = Get-Content -LiteralPath $aaqPath -Raw -Encoding UTF8 | ConvertFrom-Json
$nextFrontier = Get-Content -LiteralPath $nextFrontierPath -Raw -Encoding UTF8 | ConvertFrom-Json
$hygiene = Get-Content -LiteralPath $hygienePath -Raw -Encoding UTF8 | ConvertFrom-Json
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

Assert-True ($payload.schema_version -eq "xinao.codex_s.source_family_wave_scheduler.v1") "Payload schema mismatch."
Assert-True ($payload.status -eq "source_family_wave_scheduler_ready") "Source family scheduler not ready."
Assert-True ($payload.work_id -eq "xinao_seed_cortex_phase0_20260701") "work_id mismatch."
Assert-True ($payload.parent_task_id -eq "xinao_seed_cortex_phase0_20260701") "parent_task_id mismatch."
Assert-True ($payload.task_id -eq "wave4_20260701_frontier_source_family_20260704") "task_id mismatch."
Assert-True ($payload.routing -eq "continue_same_task") "routing mismatch."
Assert-True ($payload.dynamic_width.target_width -ne 20) "target_width still looks fixed at 20."
Assert-True ([int]$payload.dynamic_width.actual_dispatched_width -ge 5) "actual dispatched source family width too low."
Assert-True ([int]$claim.non_local_source_family_count -ge 4) "source family coverage too low."
Assert-True ($fanIn.object_type -eq "FanInAcceptanceQueue") "FanIn object mismatch."
Assert-True ($fanIn.fan_in_is_default_heart -eq $true) "FanIn is not default heart."
Assert-True ([int]$fanIn.accepted_edge_count -ge 5) "FanIn accepted too few edges."
Assert-True ([int]$aaq.accepted_artifact_count -ge 5) "AAQ accepted too few artifacts."
Assert-True ($nextFrontier.should_continue_loop -eq $true) "Next frontier did not continue loop."
Assert-True ($nextFrontier.stop_allowed -eq $false) "Next frontier allowed stop."
Assert-True ($nextFrontier.next_frontier[0].action -eq "enter_wave5_phase0_reusable_kernel") "Next frontier did not point to block5."
Assert-True ($hygiene.s_temporal_worker_started_by_hidden_script -eq $true) "Hidden Temporal worker contract missing."
Assert-True ($hygiene.legacy_clean_runtime_processes_reference_only -eq $true) "Legacy CLEAN processes not marked reference-only."
Assert-True ($payload.completion_claim_allowed -eq $false) "Completion claim was allowed."
Assert-True ($payload.validation.passed -eq $true) "Source family scheduler validation failed."
Assert-True ($readback.Contains("source-family")) "Readback missing source-family answer."
Assert-True ($nextFrontier.next_frontier[0].action -eq "enter_wave5_phase0_reusable_kernel") "Readback/evidence missing next machine action."
Assert-True ($readback.Contains("SENTINEL:XINAO_SOURCE_FAMILY_WAVE_SCHEDULER_READY")) "Readback missing sentinel."

Write-Output "source_family_wave_scheduler_latest=$latestPath"
Write-Output "source_family_wave_plan_latest=$planPath"
Write-Output "claim_card_staging_queue_latest=$claimPath"
Write-Output "fan_in_acceptance_queue_latest=$fanInPath"
Write-Output "artifact_acceptance_queue_latest=$aaqPath"
Write-Output "readback_zh=$readbackPath"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_SOURCE_FAMILY_WAVE_SCHEDULER_READY"
