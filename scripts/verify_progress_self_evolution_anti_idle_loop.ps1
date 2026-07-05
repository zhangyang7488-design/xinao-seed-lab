[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
if ([string]::IsNullOrWhiteSpace($Python)) {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $Python = $venvPython
    } else {
        $Python = "python"
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$srcRoot = Join-Path $RepoRoot "src"
$oldPythonPath = [string]$env:PYTHONPATH
$oldPythonIoEncoding = [string]$env:PYTHONIOENCODING
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
    "$srcRoot;$RepoRoot"
} else {
    "$srcRoot;$RepoRoot;$oldPythonPath"
}
$env:PYTHONIOENCODING = "utf-8"

$modules = @(
    "services\agent_runtime\progress_self_evolution.py",
    "services\agent_runtime\external_research_strategy_mutation_bridge.py",
    "services\agent_runtime\source_frontier_workerbrief_bridge.py",
    "services\agent_runtime\source_frontier_workerpool_closure.py",
    "services\agent_runtime\allocation_plan.py",
    "services\agent_runtime\codex_native_provider_scheduler_phase4.py",
    "services\agent_runtime\codex_s_durable_default_chain_supervisor.py",
    "services\agent_runtime\pre_pass_audit_loop.py",
    "services\agent_runtime\codex_s_main_execution_loop_tick.py",
    "services\agent_runtime\scheduler_invocation_packet.py"
) | ForEach-Object { Join-Path $RepoRoot $_ }

& $Python -m py_compile @modules
Assert-True ($LASTEXITCODE -eq 0) "py_compile failed."

& $Python -m pytest -q `
    tests\seedcortex\test_progress_self_evolution.py `
    tests\seedcortex\test_external_research_strategy_mutation_bridge.py `
    tests\seedcortex\test_source_frontier_workerbrief_bridge.py `
    tests\seedcortex\test_source_frontier_workerpool_closure.py `
    tests\seedcortex\test_allocation_plan.py `
    tests\seedcortex\test_codex_native_provider_scheduler_phase4.py `
    tests\seedcortex\test_pre_pass_audit_loop.py `
    tests\seedcortex\test_codex_s_durable_default_chain_supervisor.py `
    tests\seedcortex\test_codex_s_main_execution_loop_tick.py
Assert-True ($LASTEXITCODE -eq 0) "pytest failed."

$digest = "verify-progress-self-evolution-source-digest-20260705"
$feedbackRef = Join-Path $RuntimeRoot "state\source_frontier_durable_consumer\latest.json"

$firstOutput = & $Python -m services.agent_runtime.progress_self_evolution `
    --runtime-root $RuntimeRoot `
    --wave-id "progress-self-evolution-anti-idle-20260705-wave-01" `
    --source-digest $digest `
    --source-theme-id "verify.empty_frontier_noop" `
    --source-frontier-empty `
    --feedback-source-ref $feedbackRef `
    --no-progress-reason "verify_empty_frontier_noop"
Assert-True ($LASTEXITCODE -eq 0) "first progress invoke failed."
$first = ($firstOutput -join [Environment]::NewLine) | ConvertFrom-Json

$secondOutput = & $Python -m services.agent_runtime.progress_self_evolution `
    --runtime-root $RuntimeRoot `
    --wave-id "progress-self-evolution-anti-idle-20260705-wave-02" `
    --source-digest $digest `
    --source-theme-id "verify.empty_frontier_noop" `
    --source-frontier-empty `
    --feedback-source-ref $feedbackRef `
    --no-progress-reason "verify_empty_frontier_noop"
Assert-True ($LASTEXITCODE -eq 0) "second progress invoke failed."
$second = ($secondOutput -join [Environment]::NewLine) | ConvertFrom-Json

Assert-True ($first.progress_ledger.no_progress_count -ge 1) "first no_progress_count missing."
Assert-True ($second.reflection_record.can_influence_scheduler -eq $true) "reflection did not bind feedback."
Assert-True ($second.strategy_mutation.active -eq $true) "strategy mutation not active."
Assert-True ($second.strategy_mutation.scheduler_consumption_required -eq $true) "scheduler consumption not required."

$bridgeOutput = & $Python -m services.agent_runtime.external_research_strategy_mutation_bridge `
    --runtime-root $RuntimeRoot `
    --repo-root $RepoRoot `
    --wave-id "external-research-strategy-mutation-bridge-verify-20260705"
Assert-True ($LASTEXITCODE -eq 0) "external research strategy mutation bridge invoke failed."
$bridge = ($bridgeOutput -join [Environment]::NewLine) | ConvertFrom-Json
Assert-True ($bridge.external_mature_discovery_decision.external_mature_discovery_required -eq $true) "external mature discovery was not required."
Assert-True ($bridge.external_mature_discovery_decision.codex_reflection_subagent_dispatch_required -eq $true) "reflection Codex subagent dispatch was not required."
Assert-True ($bridge.external_mature_discovery_decision.required_codex_subagent_count -eq 2) "reflection Codex subagent count was not 2."
Assert-True ($bridge.source_ledger.entry_count -gt 0) "external mature SourceLedger entries missing."
Assert-True ($bridge.claim_cards.claim_card_count -gt 0) "external mature ClaimCards missing."
Assert-True ($bridge.reflection_subagent_dispatch.dispatched_subagent_count -eq 2) "reflection subagent dispatch count was not 2."
Assert-True ($bridge.reflection_subagent_dispatch.scheduler_spawned_lane_count -eq 2) "scheduler spawned lane count was not 2."
Assert-True ($bridge.reflection_subagent_dispatch.validation.passed -eq $true) "reflection subagent dispatch validation failed."
Assert-True ($bridge.reflection_worker_dispatch_ledger.summary.subagent_entry_count -eq 2) "reflection worker dispatch ledger did not record two subagents."
Assert-True ($bridge.strategy_mutation_candidate.reflection_contrast_refs.Count -gt 0) "reflection contrast refs missing."
Assert-True ($bridge.strategy_mutation_candidate.worker_dispatch_ledger_refs.Count -gt 0) "worker dispatch ledger refs missing from mutation candidate."
Assert-True ($bridge.strategy_mutation.active -eq $true) "external mature mutation not active."

$mainTickOutput = & $Python -m xinao_seedlab.cli.__main__ `
    --runtime-root $RuntimeRoot `
    --repo-root $RepoRoot `
    main-execution-loop-tick `
    --wave-id "progress-self-evolution-main-tick-consume-20260705" `
    --codex-subagent "codex_reflection_local_search:local_reflection_search" `
    --codex-subagent "codex_reflection_external_search:external_mature_reflection_search"
Assert-True ($LASTEXITCODE -eq 0) "main execution loop tick invoke failed."
$mainTick = ($mainTickOutput -join [Environment]::NewLine) | ConvertFrom-Json
Assert-True ($mainTick.external_mature_strategy_mutation_bridge.validation.passed -eq $true) "main tick external bridge validation failed."
Assert-True ($mainTick.external_mature_strategy_mutation_bridge.strategy_mutation.active -eq $true) "main tick did not keep external mature mutation active."
Assert-True ($mainTick.allocation_plan.strategy_mutation_consumption.strategy_mutation_consumed -eq $true) "AllocationPlan did not consume external mature mutation in main tick."

$strategyLatest = Join-Path $RuntimeRoot "state\strategy_mutation\latest.json"
Assert-True (Test-Path -LiteralPath $strategyLatest -PathType Leaf) "strategy mutation latest missing."

Write-Output "progress_ledger_latest=$($second.output_paths.progress_latest)"
Write-Output "reflection_record_latest=$($second.output_paths.reflection_latest)"
Write-Output "strategy_mutation_latest=$strategyLatest"
Write-Output "external_mature_bridge_latest=$($bridge.output_paths.latest)"
Write-Output "external_mature_source_ledger=$($bridge.output_paths.source_ledger_wave)"
Write-Output "external_mature_claim_cards=$($bridge.output_paths.claim_cards_wave)"
Write-Output "reflection_subagent_dispatch=$($bridge.output_paths.reflection_subagent_dispatch_wave)"
Write-Output "reflection_worker_dispatch_ledger=$($bridge.output_paths.reflection_worker_dispatch_ledger_wave)"
Write-Output "reflection_contrast=$($bridge.output_paths.reflection_contrast_wave)"
Write-Output "main_tick_latest=$($mainTick.output_paths.runtime_latest)"
Write-Output "main_tick_allocation_plan=$($mainTick.allocation_plan.output_paths.latest)"
Write-Output "strategy_mutation_status=$($second.strategy_mutation.status)"
Write-Output "strategy_mutation_next_mode=$($bridge.strategy_mutation.next_mode)"
Write-Output "validation_result=PROGRESS_SELF_EVOLUTION_ANTI_IDLE_READY"
Write-Output "SENTINEL:XINAO_PROGRESS_SELF_EVOLUTION_V1"
