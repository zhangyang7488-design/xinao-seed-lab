[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "",
    [string]$TaskId = "productivity_mode_v2_codex_surfaces_20260703",
    [string]$WaveId = "productivity-mode-v2-verify-20260703",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$repoRoot = if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    (Get-Location).Path
}
else {
    $RepoRoot
}
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = "$repoRoot\src;$repoRoot"

try {
    Push-Location $repoRoot
    $landingPath = Join-Path $repoRoot "contracts\productivity-mode-landing.v1.json"
    Assert-True (Test-Path -LiteralPath $landingPath -PathType Leaf) "productivity landing map missing: $landingPath"
    $landing = Get-Content -LiteralPath $landingPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$landing.schema_version -eq "xinao.productivity_mode_landing.v1") "landing schema_version mismatch."
    Assert-True ([string]$landing.landed.service -eq "SeedCortexService.productivity_mode_v2_wave") "landing service mismatch."
    Assert-True ([string]$landing.landed.verifier -eq "scripts/verify_productivity_mode_v2.ps1") "landing verifier mismatch."
    Assert-True ([string]$landing.landed.cli -like "*productivity-mode-v2-wave*") "landing cli mismatch."

    $output = & $Python -m xinao_seedlab.cli.__main__ --runtime-root $RuntimeRoot --repo-root $repoRoot productivity-mode-v2-wave --task-id $TaskId --wave-id $WaveId 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $output | Write-Output
    }
    Assert-True ($exitCode -eq 0) "productivity-mode-v2-wave CLI failed."

    $latest = Join-Path $RuntimeRoot "state\meta_rsi_wave\latest.json"
    Assert-True (Test-Path -LiteralPath $latest -PathType Leaf) "MetaRsiWave latest missing: $latest"
    $payload = Get-Content -LiteralPath $latest -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$payload.schema_version -eq "xinao.meta_rsi_wave.v1") "schema_version mismatch."
    Assert-True ([string]$payload.task_id -eq $TaskId) "task_id mismatch."
    Assert-True ([string]$payload.wave_id -eq $WaveId) "wave_id mismatch."
    Assert-True ([string]$payload.mode -eq "productivity_v2") "mode mismatch."
    Assert-True ([string]$payload.adoption_state -eq "candidate_registered") "adoption_state must stay candidate_registered."
    Assert-True ($payload.runtime_enforced -eq $false) "runtime_enforced must be false."
    Assert-True ($payload.completion_claim_allowed -eq $false) "completion_claim_allowed must be false."
    Assert-True ($payload.validation.passed -eq $true) "validation did not pass."
    Assert-True ($payload.validation.checks.worker_assignment_present -eq $true) "worker_assignment_present validation missing."
    Assert-True ($payload.validation.checks.baseline_had_code_diff -eq $true) "baseline_had_code_diff validation missing."
    Assert-True ($payload.validation.checks.baseline_had_invoke -eq $true) "baseline_had_invoke validation missing."
    Assert-True (@($payload.lanes).Count -ge 6) "expected at least 6 lanes."
    Assert-True ([int]$payload.fan_in.accepted_result_count -ge 1) "expected accepted fan-in result."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$payload.can_invoke_now.cli)) "missing can_invoke_now.cli."

    $assignmentPath = [string]$payload.output_paths.worker_assignment
    Assert-True (Test-Path -LiteralPath $assignmentPath -PathType Leaf) "WORKER_ASSIGNMENT missing: $assignmentPath"
    $assignment = Get-Content -LiteralPath $assignmentPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$assignment.schema_version -eq "xinao.productivity_mode_v2.worker_assignment.v1") "WORKER_ASSIGNMENT schema mismatch."
    Assert-True ([string]$assignment.task_id -eq $TaskId) "WORKER_ASSIGNMENT task_id mismatch."
    Assert-True ([string]$assignment.wave_id -eq $WaveId) "WORKER_ASSIGNMENT wave_id mismatch."
    Assert-True ([string]$assignment.scope_level_target -eq "L3") "WORKER_ASSIGNMENT scope mismatch."
    Assert-True ($assignment.completion_claim_allowed -eq $false) "WORKER_ASSIGNMENT completion_claim_allowed must be false."

    $baselinePath = [string]$payload.output_paths.productivity_baseline_latest
    Assert-True (Test-Path -LiteralPath $baselinePath -PathType Leaf) "Productivity baseline missing: $baselinePath"
    $baseline = Get-Content -LiteralPath $baselinePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$baseline.schema_version -eq "xinao.codex_productivity_baseline.v1") "baseline schema mismatch."
    Assert-True ([string]$baseline.task_id -eq $TaskId) "baseline task_id mismatch."
    Assert-True ([string]$baseline.wave_id -eq $WaveId) "baseline wave_id mismatch."
    Assert-True ($baseline.had_code_diff -eq $true) "baseline had_code_diff must be true."
    Assert-True ($baseline.had_invoke -eq $true) "baseline had_invoke must be true."
    Assert-True ($baseline.not_user_completion -eq $true) "baseline not_user_completion must be true."

    $readback = [string]$payload.output_paths.runtime_readback_zh
    Assert-True (Test-Path -LiteralPath $readback -PathType Leaf) "readback missing: $readback"
    $readbackText = Get-Content -LiteralPath $readback -Raw -Encoding UTF8
    Assert-True ($readbackText.Contains("invoke")) "readback missing invoke section."
    Assert-True ($readbackText.Contains("candidate_registered")) "readback missing adoption state."

    $triggerWaveId = "$WaveId-default-trigger"
    $triggerOutput = & $Python -m xinao_seedlab.cli.__main__ --runtime-root $RuntimeRoot --repo-root $repoRoot default-main-loop-trigger-candidate --task-id $TaskId --wave-id $triggerWaveId 2>&1
    $triggerExitCode = $LASTEXITCODE
    if ($triggerExitCode -ne 0) {
        $triggerOutput | Write-Output
    }
    Assert-True ($triggerExitCode -eq 0) "default-main-loop-trigger-candidate CLI failed."
    $triggerPayload = ($triggerOutput -join [Environment]::NewLine) | ConvertFrom-Json
    Assert-True ($triggerPayload.validation.passed -eq $true) "default trigger validation did not pass."
    Assert-True ($triggerPayload.productivity_mode_v2_wave.invoked -eq $true) "default trigger did not invoke productivity v2 wave."
    Assert-True ([string]$triggerPayload.productivity_mode_v2_wave.adoption_state -eq "candidate_registered") "productivity v2 wave adoption state mismatch."
    Assert-True ($triggerPayload.productivity_mode_v2_wave.runtime_enforced -eq $false) "productivity v2 meta wave must remain runtime_enforced=false."
    Assert-True ($triggerPayload.productivity_mode_v2_trigger_binding.runtime_enforced -eq $true) "productivity trigger binding must be runtime_enforced for service invocation."
    Assert-True ([string]$triggerPayload.productivity_mode_v2_trigger_binding.runtime_enforced_scope -eq "default_main_loop_trigger_candidate_service_invocation_only") "productivity trigger binding scope mismatch."
    Assert-True ($triggerPayload.validation.checks.productivity_v2_meta_wave_not_overpromoted -eq $true) "default trigger overpromoted productivity MetaRsiWave."
    $bindingPath = [string]$triggerPayload.productivity_mode_v2_trigger_binding.evidence_refs.binding_latest
    Assert-True (Test-Path -LiteralPath $bindingPath -PathType Leaf) "productivity trigger binding missing: $bindingPath"

    Write-Output "productivity_mode_v2_latest=$latest"
    Write-Output "productivity_mode_v2_worker_assignment=$assignmentPath"
    Write-Output "productivity_mode_v2_baseline=$baselinePath"
    Write-Output "productivity_mode_v2_trigger_binding=$bindingPath"
    Write-Output "productivity_mode_v2_readback_zh=$readback"
    Write-Output "productivity_mode_v2_cli=$($payload.can_invoke_now.cli)"
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    Pop-Location
}
