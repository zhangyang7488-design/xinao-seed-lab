$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = "D:\XINAO_RESEARCH_RUNTIME"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $repoRoot "services\agent_runtime\pre_pass_audit_loop.py"
$testPath = Join-Path $repoRoot "tests\seedcortex\test_pre_pass_audit_loop.py"
$schemaPath = Join-Path $repoRoot "contracts\schemas\codex_s_pre_pass_audit_loop.v1.json"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "pre_pass_audit_loop py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "pre_pass_audit_loop pytest failed."

$waveId = "pre-pass-audit-loop-verify-20260704"
$output = python $modulePath `
    --repo-root $repoRoot `
    --runtime-root $runtimeRoot `
    --task-id "pre_pass_audit_loop_20260704" `
    --wave-id $waveId
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    $output | ForEach-Object { Write-Output $_ }
}
Assert-True ($exitCode -eq 0) "pre_pass_audit_loop generation failed."
$text = $output -join "`n"
Assert-True ($text.Contains("SENTINEL:XINAO_CODEX_S_PRE_PASS_AUDIT_LOOP_V1")) "Pre-PASS sentinel missing."

$latestPath = Join-Path $runtimeRoot "state\pre_pass_audit_loop\latest.json"
$candidatePath = Join-Path $runtimeRoot "state\pre_pass_audit_loop\candidate_snapshot_latest.json"
$laneRegistryPath = Join-Path $runtimeRoot "state\pre_pass_audit_loop\audit_lane_registry_latest.json"
$fanInPath = Join-Path $runtimeRoot "state\pre_pass_audit_loop\audit_fan_in_latest.json"
$repairPlanPath = Join-Path $runtimeRoot "state\pre_pass_audit_loop\repair_plan_latest.json"
$reauditPath = Join-Path $runtimeRoot "state\pre_pass_audit_loop\reaudit_latest.json"
$readbackPath = Join-Path $runtimeRoot "readback\zh\pre_pass_audit_loop_$waveId.md"

foreach ($path in @($schemaPath, $latestPath, $candidatePath, $laneRegistryPath, $fanInPath, $reauditPath, $readbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing Pre-PASS evidence: $path"
}

$payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($payload.schema_version -eq "xinao.codex_s.pre_pass_audit_loop.v1") "schema mismatch."
Assert-True ($payload.sentinel -eq "SENTINEL:XINAO_CODEX_S_PRE_PASS_AUDIT_LOOP_V1") "sentinel mismatch."
Assert-True ($payload.status -eq "pre_pass_audit_loop_ready") "Pre-PASS not ready."
Assert-True ($payload.candidate_snapshot.candidate_kind -eq "before_final_or_pass") "CandidateSnapshot kind mismatch."
Assert-True ([int]$payload.audit_lane_registry.lane_count -ge 8) "audit lane count missing."
foreach ($laneId in @("hotpath_lane","runtime_lane","provider_lane","source_gap_lane","fanin_lane","completion_boundary_lane","readback_lane","history_lane")) {
    Assert-True (@($payload.audit_lane_registry.lanes | Where-Object { $_.lane_id -eq $laneId }).Count -eq 1) "Missing audit lane: $laneId"
}
Assert-True ($payload.audit_fan_in.final_allowed -eq $false -or $payload.audit_fan_in.decision -eq "all_pass_final_allowed") "fan-in final_allowed mismatch."
if ([int]$payload.audit_fan_in.fixable_count -gt 0) {
    Assert-True (
        ($payload.pre_pass_payload.decision -eq "dispatch_repair_plan") -or
        ($payload.pre_pass_payload.decision -eq "named_blocker")
    ) "FIXABLE did not produce repair dispatch or named blocker."
    if ($payload.pre_pass_payload.decision -eq "dispatch_repair_plan") {
        Assert-True ($payload.pre_pass_payload.continue_main_loop -eq $true) "FIXABLE did not keep main loop alive."
    } else {
        Assert-True (-not [string]::IsNullOrWhiteSpace([string]$payload.pre_pass_payload.named_blocker)) "named_blocker decision missing blocker."
        Assert-True ($payload.pre_pass_payload.continue_main_loop -eq $false) "named_blocker decision should stop automatic repair loop."
    }
    Assert-True (Test-Path -LiteralPath $repairPlanPath -PathType Leaf) "FIXABLE repair plan missing."
    Assert-True ($payload.repair_plan.dispatch_to -eq "root_intent_loop_driver") "RepairPlan dispatch_to mismatch."
}
Assert-True ($payload.completion_claim_allowed -eq $false) "Pre-PASS allowed completion claim."
Assert-True ($payload.not_old_segment_audit -eq $true) "Pre-PASS became old segment audit."
Assert-True ($payload.not_completion_gate -eq $true) "Pre-PASS became completion gate."
Assert-True ($payload.not_execution_controller -eq $true) "Pre-PASS became execution controller."
Assert-True ($payload.validation.passed -eq $true) "Pre-PASS validation failed."

$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
Assert-True ($readback.Contains("Pre-PASS Audit Loop")) "readback missing title."
Assert-True ($readback.Contains("RepairPlan")) "readback missing RepairPlan wording."
Assert-True ($readback.Contains("SENTINEL:XINAO_CODEX_S_PRE_PASS_AUDIT_LOOP_V1")) "readback missing sentinel."

Write-Output "pre_pass_audit_loop_latest=$latestPath"
Write-Output "pre_pass_audit_loop_candidate_snapshot=$candidatePath"
Write-Output "pre_pass_audit_loop_audit_lane_registry=$laneRegistryPath"
Write-Output "pre_pass_audit_loop_fan_in=$fanInPath"
Write-Output "pre_pass_audit_loop_repair_plan=$repairPlanPath"
Write-Output "pre_pass_audit_loop_readback=$readbackPath"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_CODEX_S_PRE_PASS_AUDIT_LOOP_V1"
