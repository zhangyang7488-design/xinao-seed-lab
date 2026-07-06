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

$landingPath = Join-Path $RuntimeRoot "state\333_sleep_watch_p0_landing\latest.json"
$currentIndexPath = Join-Path $RuntimeRoot "state\current_333_run_index\latest.json"
$toolRegistryPath = Join-Path $RuntimeRoot "agent_runtime\tools\registry\tool_registry.json"
$capabilityPipelinePath = Join-Path $RuntimeRoot "state\capability_absorption_pipeline\latest.json"
$taskBoundPath = Join-Path $RuntimeRoot "state\task_bound_evidence\xinao_seed_cortex_phase0_20260701\assignment_dag\333_sleep_watch_p0_landing.latest.json"
$taskBoundJsonlPath = Join-Path $RuntimeRoot "state\task_bound_evidence\xinao_seed_cortex_phase0_20260701\assignment_dag\333_sleep_watch_p0_landing.jsonl"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\333_sleep_watch_p0_landing.md"

$landing = Read-JsonFile $landingPath
$current = Read-JsonFile $currentIndexPath
$registry = Read-JsonFile $toolRegistryPath
$pipeline = Read-JsonFile $capabilityPipelinePath
$taskBound = Read-JsonFile $taskBoundPath

Assert-True ([string]$landing.schema_version -eq "xinao.codex_s.333_sleep_watch_p0_landing.v1") "landing schema mismatch."
Assert-True ([string]$landing.sentinel -eq "SENTINEL:XINAO_333_SLEEP_WATCH_P0_LANDING") "landing sentinel mismatch."
Assert-True ([string]$landing.task_id -eq "xinao_seed_cortex_phase0_20260701") "task_id mismatch."
Assert-True ([string]$landing.node_id -eq "333_sleep_watch_p0_landing") "node_id mismatch."
Assert-True ($landing.completion_claim_allowed -eq $false) "completion claim is allowed."
Assert-True ($landing.not_user_completion -eq $true) "not_user_completion missing."
Assert-True ($landing.not_execution_controller -eq $true) "not_execution_controller missing."
Assert-True ($landing.source_package.source_package_rebound -eq $true) "source package not rebound."
Assert-True ($landing.source_package.five_text_files_read -eq $true) "five source text files were not read."
Assert-True ([int]$landing.source_package.file_count -eq 5) "source file count mismatch."
Assert-True ($landing.source_package.max_mature_component_ref.read_in_full -eq $true) "max mature component memo was not read."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$landing.source_package.max_mature_component_resolution.resolved_path)) "max mature component resolution missing."
Assert-True ($landing.validation.checks.max_mature_component_read -eq $true) "landing validation missing max mature component read check."

Assert-True ([string]$current.schema_version -eq "xinao.codex_s.333_sleep_watch_p0_landing.v1.current_run_index.v1") "current index schema mismatch."
Assert-True ([string]$current.workflow_id -eq [string]$landing.workflow_id) "current index workflow mismatch."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$current.workflow_run_id)) "current index run_id missing."
$reconciled = $current.reconciliation.reconciled -eq $true
$hasBlocker = -not [string]::IsNullOrWhiteSpace([string]$current.reconciliation.named_blocker)
Assert-True ($reconciled -or $hasBlocker) "current index neither reconciled nor named-blocked."
Assert-True ([int]$current.worker_dispatch_ledger.succeeded_count -ge 1) "ledger succeeded count missing."
Assert-True ([int]$current.artifact_acceptance_queue.unique_accepted_artifact_count -ge 1) "AAQ unique acceptance missing."

$ids = @($registry.provider_ids)
foreach ($required in @(
    "codex_s.direct_worker_lane",
    "qwen_prepaid_cheap_worker",
    "legacy.deepseek_dp_sidecar",
    "codex_s.capability_gateway",
    "mcp.xinao_runtime.tools",
    "d_runtime.capability_manifests"
)) {
    Assert-True ($ids -contains $required) "ToolRegistry missing $required."
}
Assert-True ($registry.validation.checks.five_layer_fields_present -eq $true) "ToolRegistry five-layer fields missing."
Assert-True ([int]$registry.d_runtime_manifest_count -gt 0) "D runtime capability manifests not exposed."
Assert-True ($registry.ucp_dispatch_exposed -eq $false) "UCP dispatch was exposed."

$realness = $landing.provider_realness_gate
Assert-True ([string]$realness.status -eq "provider_realness_gate_ready") "provider realness gate not ready."
Assert-True ($realness.validation.checks.critical_lanes_model_invoked -eq $true) "critical lanes did not all invoke models."
Assert-True ($realness.validation.checks.critical_lanes_not_local_stub -eq $true) "critical lanes include local stub."
Assert-True ($realness.validation.checks.local_stub_fixture_rejected -eq $true) "local_stub fixture was not rejected."
Assert-True ($realness.validation.checks.model_false_fixture_rejected -eq $true) "model false fixture was not rejected."

$width = $landing.dynamic_width_evidence
Assert-True ($width.validation.checks.configured_width_present -eq $true) "configured width missing."
Assert-True ($width.validation.checks.requested_width_present -eq $true) "requested width missing."
Assert-True ($width.validation.checks.dispatched_width_present -eq $true) "dispatched width missing."
Assert-True ($width.validation.checks.completed_width_present -eq $true) "completed width missing."
Assert-True ($width.validation.checks.accepted_count_present -eq $true) "accepted width/count missing."
Assert-True ($width.validation.checks.static_bootstrap_cases_named -eq $true) "static/bootstrap cases not named."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$width.case_classification)) "width case classification missing."

Assert-True ([string]$pipeline.schema_version -eq "xinao.codex_s.333_sleep_watch_p0_landing.v1.capability_absorption_pipeline.v1") "pipeline schema mismatch."
Assert-True ([int]$pipeline.candidate_count -gt 0) "pipeline candidate count missing."
Assert-True ($pipeline.report_only_inventory -eq $false) "pipeline is report-only inventory."
Assert-True ($pipeline.validation.checks.candidate_smoke_policy_thinbind_333_aaq_states_present -eq $true) "pipeline stage states missing."
Assert-True ($pipeline.validation.checks.external_mature_map_present -eq $true) "external mature map missing."

Assert-True ([string]$taskBound.schema_version -eq "xinao.codex_s.333_sleep_watch_p0_landing.v1.task_bound_jsonl_evidence.v1") "task-bound evidence schema mismatch."
Assert-True ([string]$taskBound.status -eq "assignment_dag_node_evidence_written") "task-bound evidence not written."
Assert-True ([string]$taskBound.task_id -eq "xinao_seed_cortex_phase0_20260701") "task-bound task id mismatch."
Assert-True ([string]$taskBound.node_id -eq "333_sleep_watch_p0_landing") "task-bound node mismatch."
Assert-True ([string]$taskBound.workflow_id -eq [string]$landing.workflow_id) "task-bound workflow mismatch."
Assert-True ([string]$taskBound.workflow_run_id -eq [string]$current.workflow_run_id) "task-bound run mismatch."
Assert-True ($taskBound.validation.passed -eq $true) "task-bound validation did not pass."
Assert-True (Test-Path -LiteralPath $taskBoundJsonlPath -PathType Leaf) "task-bound JSONL missing."
$lastTaskBoundLine = Get-Content -LiteralPath $taskBoundJsonlPath -Tail 1 -Encoding UTF8
$lastTaskBound = $lastTaskBoundLine | ConvertFrom-Json
Assert-True ([string]$lastTaskBound.task_id -eq "xinao_seed_cortex_phase0_20260701") "task-bound JSONL task id mismatch."
Assert-True ([string]$lastTaskBound.node_id -eq "333_sleep_watch_p0_landing") "task-bound JSONL node mismatch."
Assert-True ([string]$lastTaskBound.workflow_id -eq [string]$landing.workflow_id) "task-bound JSONL workflow mismatch."
Assert-True ($lastTaskBound.completion_claim_allowed -eq $false) "task-bound JSONL allows completion."
Assert-True ($landing.validation.checks.task_bound_jsonl_evidence_ready -eq $true) "landing validation missing task-bound JSONL check."
Assert-True ($landing.validation.checks.default_mainline_consumes_current_index_and_tool_registry -eq $true) "landing validation missing default mainline consumption check."
Assert-True ($landing.default_mainline_hardened -eq $true) "default mainline was not hardened."
Assert-True ([string]::IsNullOrWhiteSpace([string]$landing.missing_binding)) "default mainline missing_binding should be empty after hardening."
Assert-True ($landing.default_mainline_binding.hardened -eq $true) "default mainline binding not hardened."
Assert-True ($landing.default_mainline_binding.current_333_run_index_consumed_by_default_trigger -eq $true) "default trigger did not consume current_333_run_index."
Assert-True ($landing.default_mainline_binding.tool_registry_consumed_by_default_trigger -eq $true) "default trigger did not consume ToolRegistry."

Assert-True ($landing.validation.passed -eq $true) "landing validation did not pass."
Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "readback missing."

Write-Output "333_sleep_watch_p0_landing_latest=$landingPath"
Write-Output "current_333_run_index_latest=$currentIndexPath"
Write-Output "tool_registry=$toolRegistryPath"
Write-Output "capability_absorption_pipeline=$capabilityPipelinePath"
Write-Output "task_bound_jsonl=$taskBoundJsonlPath"
Write-Output "validation_result=ok"
