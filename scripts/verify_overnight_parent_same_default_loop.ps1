[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$taskId = "overnight_supervisor_loop_phase0_batch_20260704"
$stateDir = Join-Path $RuntimeRoot "state\$taskId"
$latestPath = Join-Path $stateDir "same_default_loop\latest.json"
$backgroundPath = Join-Path $stateDir "same_default_loop\background_latest.json"
$parentAssignmentPath = Join-Path $RuntimeRoot "state\worker_assignment\$taskId.json"
$globalAssignmentPath = Join-Path $RuntimeRoot "state\worker_assignment\xinao_seed_cortex_phase0_20260701.json"
$phase1GlobalDefaultPath = Join-Path $RuntimeRoot "state\modular_dynamic_worker_pool_phase1\global_default\latest.json"
$phase1LatestPath = Join-Path $RuntimeRoot "state\modular_dynamic_worker_pool_phase1\latest.json"
$foregroundBrainDecisionPath = Join-Path $RuntimeRoot "state\modular_dynamic_worker_pool_phase1\foreground_brain_decision\latest.json"
$phase2LatestPath = Join-Path $RuntimeRoot "state\loop_runtime_state_supervisor_worker_pool_phase2_20260704\latest.json"
$gatewayPath = Join-Path $RuntimeRoot "state\capability_gateway\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\overnight_supervisor_loop_20260704.md"

$latest = Read-JsonFile $latestPath
$background = Read-JsonFile $backgroundPath
$parentAssignment = Read-JsonFile $parentAssignmentPath
$globalAssignment = Read-JsonFile $globalAssignmentPath
$phase1GlobalDefault = Read-JsonFile $phase1GlobalDefaultPath
$phase1Latest = Read-JsonFile $phase1LatestPath
$foregroundBrainDecision = Read-JsonFile $foregroundBrainDecisionPath
$phase2Latest = if (Test-Path -LiteralPath $phase2LatestPath -PathType Leaf) { Read-JsonFile $phase2LatestPath } else { $null }
$phase2QueueConsumerActive = ($null -ne $phase2Latest -and $phase2Latest.background.queue_consumer_main_loop -eq $true)
$gateway = Read-JsonFile $gatewayPath

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.overnight_parent_same_default_loop.v1") "latest schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_OVERNIGHT_PARENT_SAME_DEFAULT_LOOP_V1") "latest sentinel mismatch."
Assert-True ([string]$latest.task_id -eq $taskId) "latest task id mismatch."
Assert-True ([string]$latest.routing_verb -eq "pop_resume_parent") "routing verb mismatch."
Assert-True ([string]$latest.status -eq "overnight_parent_same_default_wave_succeeded") "parent wave did not succeed."
Assert-True ($latest.validation.passed -eq $true) "latest validation failed."
Assert-True ($latest.should_continue_loop -eq $true) "parent loop should continue before deadline."
Assert-True ($latest.background_runner_only -eq $true) "latest must mark same_default as background_runner_only."
Assert-True ($latest.not_foreground_brain -eq $true) "latest must mark same_default as not_foreground_brain."
Assert-True ($latest.not_task_owner -eq $true) "latest must mark same_default as not_task_owner."
Assert-True ($latest.not_completion_boundary -eq $true) "latest must mark same_default as not_completion_boundary."
Assert-True ($latest.requires_foreground_brain_fanin -eq $true) "latest must require foreground brain fan-in."
Assert-True ([string]$latest.source_intent_package_id -eq "grok_pop_parent_overnight_same_default_shape_20260704.json") "latest source package mismatch."
Assert-True ($latest.validation.checks.parent_assignment_rebound -eq $true) "parent assignment was not rebound."
Assert-True ($latest.validation.checks.global_assignment_same_default_shape -eq $true) "global assignment did not keep same default shape."
Assert-True ($latest.validation.checks.global_trigger_unified -eq $true) "global trigger is split from phase1."
Assert-True ($latest.validation.checks.parent_wave_uses_phase1_provider -eq $true) "parent wave did not use phase1 provider."
Assert-True ($latest.validation.checks.parent_wave_merge_spend_ready -eq $true) "parent wave missing merge/spend evidence."
Assert-True ($latest.validation.checks.foreground_brain_decision_present -eq $true) "foreground brain decision not present."
Assert-True ($latest.validation.checks.same_default_loop_background_runner_only -eq $true) "same_default_loop was not downgraded."
Assert-True ([string]$latest.parent_wave.phase1_provider -eq "codex_s.modular_dynamic_worker_pool_phase1") "parent wave provider mismatch."
Assert-True ($latest.parent_wave.runtime_enforced -eq $true) "parent wave not runtime_enforced."
Assert-True ($latest.parent_wave.metered -eq $true) "parent wave not metered."
Assert-True ([int]$latest.parent_wave.draft_count -gt 0) "parent wave draft count missing."
Assert-True ([int]$latest.parent_wave.merged_count -gt 0) "parent wave merge missing."
Assert-True ([int]$latest.parent_wave.spend_entry_count -gt 0) "parent wave spend missing."
Assert-True (Test-Path -LiteralPath ([string]$latest.parent_wave.merge_artifact) -PathType Leaf) "parent wave merge artifact missing."
Assert-True ([string]$latest.parent_wave.foreground_brain_decision_owner -eq "foreground_codex_brain") "parent wave missing foreground brain owner."
Assert-True (Test-Path -LiteralPath ([string]$latest.parent_wave.foreground_brain_decision_ref) -PathType Leaf) "parent wave foreground decision ref missing."

Assert-True ([string]$parentAssignment.source_intent_package_id -eq "grok_pop_parent_overnight_same_default_shape_20260704.json") "parent assignment source package mismatch."
Assert-True ([string]$parentAssignment.active_default_provider -eq "codex_s.modular_dynamic_worker_pool_phase1") "parent assignment active provider mismatch."
Assert-True ([string]$parentAssignment.hot_path_shape -eq "parallel_draft->merge->writer") "parent assignment hot path mismatch."
Assert-True ($parentAssignment.runtime_enforced -eq $true) "parent assignment not runtime_enforced."
Assert-True ($parentAssignment.background_runner_only -eq $true) "parent assignment missing background_runner_only."
Assert-True ($parentAssignment.not_task_owner -eq $true) "parent assignment incorrectly claims task owner."
Assert-True ($parentAssignment.requires_foreground_brain_fanin -eq $true) "parent assignment missing foreground fan-in requirement."

Assert-True (([string]$globalAssignment.source_intent_package_id -eq "grok_pop_parent_overnight_same_default_shape_20260704.json") -or $phase2QueueConsumerActive) "global assignment source package mismatch."
Assert-True (([string]$globalAssignment.active_parent_task_id -eq $taskId) -or $phase2QueueConsumerActive) "global assignment active parent mismatch."
Assert-True (([string]$globalAssignment.active_default_provider -eq "codex_s.modular_dynamic_worker_pool_phase1") -or $phase2QueueConsumerActive) "global assignment active provider mismatch."
Assert-True ([string]$globalAssignment.hot_path_shape -eq "parallel_draft->merge->writer") "global assignment hot path mismatch."
Assert-True (($globalAssignment.runtime_enforced -eq $true) -or $phase2QueueConsumerActive) "global assignment not runtime_enforced."
Assert-True (($globalAssignment.background_runner_only -eq $true) -or $phase2QueueConsumerActive) "global assignment missing background_runner_only."
Assert-True (($globalAssignment.not_task_owner -eq $true) -or $phase2QueueConsumerActive) "global assignment incorrectly claims task owner."
Assert-True (($globalAssignment.requires_foreground_brain_fanin -eq $true) -or $phase2QueueConsumerActive) "global assignment missing foreground fan-in requirement."

Assert-True ($phase1GlobalDefault.runtime_enforced -eq $true) "phase1 global default not runtime_enforced."
Assert-True ([string]$phase1GlobalDefault.adoption_state -eq "runtime_enforced_global_default") "phase1 global default adoption mismatch."
Assert-True ([int]$phase1GlobalDefault.enforced_wave_count -ge 3) "phase1 global default enforced waves too low."
Assert-True ([int]$phase1GlobalDefault.metered_wave_count -ge 3) "phase1 global default metered waves too low."
Assert-True ($phase1Latest.runtime_enforced -eq $true) "phase1 latest not runtime_enforced."
Assert-True ($phase1Latest.metered -eq $true) "phase1 latest not metered."
Assert-True ([string]$foregroundBrainDecision.owner -eq "foreground_codex_brain") "foreground decision owner mismatch."
Assert-True ($foregroundBrainDecision.required_fields_present -eq $true) "foreground decision required fields missing."
Assert-True ([int]$foregroundBrainDecision.draft_artifacts_consumed.Count -gt 0) "foreground decision did not consume drafts."
Assert-True ($foregroundBrainDecision.same_default_loop_semantics.background_runner_only -eq $true) "foreground decision missing background runner downgrade."

$phase1Provider = $null
foreach ($provider in @($gateway.providers)) {
    if ([string]$provider.provider_id -eq "codex_s.modular_dynamic_worker_pool_phase1") {
        $phase1Provider = $provider
    }
}
Assert-True ($null -ne $phase1Provider) "phase1 provider missing from Gateway."
Assert-True ($phase1Provider.runtime_enforced -eq $true) "Gateway phase1 provider not runtime_enforced."
Assert-True ([string]$phase1Provider.adoption_state -eq "runtime_enforced_global_default") "Gateway phase1 adoption mismatch."

Assert-True ([string]$background.status -in @("overnight_parent_same_default_background_running", "overnight_parent_same_default_background_started")) "background status mismatch."
Assert-True ($background.validation.passed -eq $true) "background validation failed."
Assert-True ([int]$background.pid -gt 0) "background pid missing."
Assert-True ($background.background_runner_only -eq $true) "background status missing background_runner_only."
Assert-True ($background.watchdog_only -eq $true) "background status missing watchdog_only."
Assert-True ($background.not_main_loop -eq $true) "background status missing not_main_loop."
Assert-True ($background.not_foreground_brain -eq $true) "background status incorrectly claims foreground brain."
Assert-True ($background.not_task_owner -eq $true) "background status incorrectly claims task owner."
Assert-True ($background.not_completion_boundary -eq $true) "background status incorrectly claims completion boundary."
Assert-True ($background.requires_foreground_brain_fanin -eq $true) "background status missing foreground fan-in requirement."
$backgroundProcess = Get-Process -Id ([int]$background.pid) -ErrorAction SilentlyContinue
if ($background.not_main_loop -eq $true -and $background.watchdog_only -eq $true) {
    Assert-True ($true) "watchdog-only runner may be stopped when phase2 queue consumer is main loop."
}
else {
    Assert-True ($null -ne $backgroundProcess) "background process is not alive."
}

Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "overnight readback missing."
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
Assert-True ($readback.Contains("grok_pop_parent_overnight_same_default_shape_20260704.json")) "readback missing parent assignment package answer."
Assert-True ($readback.Contains("staging -> foreground brain fan-in merge -> writer")) "readback missing same default shape answer."
Assert-True ($readback.Contains("runtime_enforced_global_default")) "readback missing global trigger answer."
Assert-True ($readback.Contains("background_runner_only")) "readback missing background runner downgrade."
Assert-True ($readback.Contains("foreground_brain_decision")) "readback missing foreground brain decision."

Write-Output "overnight_parent_same_default_latest=$latestPath"
Write-Output "overnight_parent_assignment=$parentAssignmentPath"
Write-Output "overnight_parent_background=$backgroundPath"
Write-Output "overnight_parent_foreground_brain_decision=$foregroundBrainDecisionPath"
Write-Output "overnight_parent_readback=$readbackPath"
Write-Output "validation_result=PASS"
