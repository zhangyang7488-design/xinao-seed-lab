$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = "D:\XINAO_RESEARCH_RUNTIME"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $repoRoot "services\agent_runtime\allocation_plan.py"
$testPath = Join-Path $repoRoot "tests\seedcortex\test_allocation_plan.py"
$schemaPath = Join-Path $repoRoot "contracts\schemas\codex_s_allocation_plan.v1.json"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "AllocationPlan py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "AllocationPlan pytest failed."

$waveId = "allocation-plan-verify-20260704"
$output = python $modulePath `
    --repo-root $repoRoot `
    --runtime-root $runtimeRoot `
    --task-id "allocation_plan_20260704" `
    --wave-id $waveId
$generationExitCode = $LASTEXITCODE
if ($generationExitCode -ne 0) {
    $output | ForEach-Object { Write-Output $_ }
}
Assert-True ($generationExitCode -eq 0) "AllocationPlan generation failed."
$text = $output -join "`n"
Assert-True ($text.Contains("SENTINEL:XINAO_CODEX_S_ALLOCATION_PLAN_V1")) "AllocationPlan sentinel missing."

$latestPath = Join-Path $runtimeRoot "state\allocation_plan\latest.json"
$briefPath = Join-Path $runtimeRoot "state\allocation_plan\worker_brief_queue_latest.json"
$lanesPath = Join-Path $runtimeRoot "state\allocation_plan\lane_allocations_latest.json"
$attemptsPath = Join-Path $runtimeRoot "state\allocation_plan\dispatch_attempts_latest.json"
$repairPath = Join-Path $runtimeRoot "state\allocation_plan\repair_plan_latest.json"
$readbackPath = Join-Path $runtimeRoot "readback\zh\allocation_plan_$waveId.md"

foreach ($path in @($schemaPath, $latestPath, $briefPath, $lanesPath, $attemptsPath, $repairPath, $readbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing AllocationPlan evidence: $path"
}

$payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($payload.schema_version -eq "xinao.codex_s.allocation_plan.v1") "Schema mismatch."
Assert-True ($payload.sentinel -eq "SENTINEL:XINAO_CODEX_S_ALLOCATION_PLAN_V1") "Payload sentinel mismatch."
Assert-True ($payload.status -eq "allocation_plan_ready") "AllocationPlan not ready."
Assert-True ($payload.not_task_route_decision_enum -eq $true) "AllocationPlan regressed into TaskRouteDecision."
Assert-True ($payload.same_task_multi_lane_allocation -eq $true) "Same-task multi-lane allocation missing."
Assert-True ($payload.target_width_source -eq "derived_from_runtime_feedback_inputs") "Width source is not derived."
Assert-True ($payload.fixed_target_width_used -eq $false) "Fixed target width was used."
Assert-True ($payload.fixed_20_or_50_used -eq $false) "Fixed 20/50 width marker leaked."
Assert-True (@($payload.lane_allocations).Count -ge 3) "Lane allocation count too low."
$laneClasses = @($payload.lane_allocations | ForEach-Object { $_.lane_class })
Assert-True ($laneClasses -contains "cheap_draft") "cheap_draft lane missing."
Assert-True (($laneClasses -contains "eval") -or ($laneClasses -contains "audit")) "eval/audit lane missing."
Assert-True (($laneClasses -contains "merge_accept") -or ($laneClasses -contains "ci_verify")) "merge/verify lane missing."
Assert-True ([int]$payload.worker_brief_queue.brief_count -eq @($payload.lane_allocations).Count) "WorkerBriefQueue count mismatch."
Assert-True ([int]$payload.dispatch_attempts.dispatch_attempt_count -eq @($payload.lane_allocations).Count) "Dispatch attempts count mismatch."
Assert-True ($payload.dispatch_attempts.report_substitute_allowed -eq $false) "Dispatch failure can be replaced by report."
Assert-True ($payload.repair_plan.dispatch_to -eq "root_intent_loop_driver") "RepairPlan dispatch target mismatch."
Assert-True ($payload.repair_plan.temporal_consumable -eq $true) "RepairPlan is not Temporal-consumable."
Assert-True ($payload.stop_allowed.derived_only -eq $true) "stop_allowed is not derived."
Assert-True ($payload.next_allocation_advice.report_substitute_allowed -eq $false) "Next advice allowed report substitute."
Assert-True ($payload.validation.passed -eq $true) "AllocationPlan validation failed."
Assert-True ($payload.validation.checks.width_derived_from_feedback -eq $true) "Width derivation validation failed."
Assert-True ($payload.completion_claim_allowed -eq $false) "Completion claim allowed."
Assert-True ($payload.not_execution_controller -eq $true) "AllocationPlan became execution controller."

$readbackText = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
Assert-True ($readbackText.Contains("SENTINEL:XINAO_CODEX_S_ALLOCATION_PLAN_V1")) "Readback missing sentinel."
Assert-True ($readbackText.Contains("fixed_20_or_50_used: False")) "Readback missing fixed width marker."
Assert-True ($readbackText.Contains("report_substitute_allowed=false")) "Readback missing report substitute boundary."

Write-Output "allocation_plan_latest=$latestPath"
Write-Output "allocation_plan_worker_brief_queue=$briefPath"
Write-Output "allocation_plan_lane_allocations=$lanesPath"
Write-Output "allocation_plan_dispatch_attempts=$attemptsPath"
Write-Output "allocation_plan_repair_plan=$repairPath"
Write-Output "allocation_plan_readback=$readbackPath"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_CODEX_S_ALLOCATION_PLAN_V1"
