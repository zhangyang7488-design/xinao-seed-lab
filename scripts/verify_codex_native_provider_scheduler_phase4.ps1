param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON file: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Provider-ById {
    param(
        [object]$Registry,
        [string]$ProviderId
    )
    $provider = @($Registry.providers | Where-Object { [string]$_.provider_id -eq $ProviderId })[0]
    Assert-True ($null -ne $provider) "Provider missing: $ProviderId"
    return $provider
}

$taskId = "codex_native_provider_scheduler_phase4_20260704"
$stateDir = Join-Path $RuntimeRoot "state\$taskId"
$latestPath = Join-Path $stateDir "latest.json"
$providerRegistryPath = Join-Path $stateDir "provider_registry\latest.json"
$executorAdapterPath = Join-Path $stateDir "executor_adapter\latest.json"
$modelGatewayPath = Join-Path $stateDir "model_gateway\latest.json"
$modelGatewayConfigPath = Join-Path $stateDir "model_gateway\litellm_router.codex_native.yaml"
$schedulerDecisionPath = Join-Path $stateDir "scheduler_decision\latest.json"
$qwenPrepaidPolicyPath = Join-Path $stateDir "qwen_prepaid_policy\latest.json"
$qwenInvocationPath = Join-Path $stateDir "qwen_invocation\latest.json"
$providerInvocationPath = Join-Path $stateDir "provider_invocation\latest.json"
$draftStagingPath = Join-Path $stateDir "draft_staging\latest.json"
$mergeConsumerPath = Join-Path $stateDir "merge_consumer\latest.json"
$temporalActivityPath = Join-Path $stateDir "temporal_activity\latest.json"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.provider_scheduler\manifest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\$taskId.md"

$latest = Read-JsonFile $latestPath
$registry = Read-JsonFile $providerRegistryPath
$executor = Read-JsonFile $executorAdapterPath
$gateway = Read-JsonFile $modelGatewayPath
$decision = Read-JsonFile $schedulerDecisionPath
$qwenPolicy = Read-JsonFile $qwenPrepaidPolicyPath
$qwenInvocation = Read-JsonFile $qwenInvocationPath
$invocation = Read-JsonFile $providerInvocationPath
$staging = Read-JsonFile $draftStagingPath
$merge = Read-JsonFile $mergeConsumerPath
$temporalActivity = Read-JsonFile $temporalActivityPath
$manifest = Read-JsonFile $manifestPath
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
$readbackLower = $readback.ToLowerInvariant()

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.codex_native_provider_scheduler_phase4.v1") "latest schema mismatch."
Assert-True ([string]$registry.schema_version -eq "xinao.codex_s.codex_native_provider_scheduler_phase4.v1.provider_registry.v1") "registry schema mismatch."
Assert-True ([string]$latest.task_id -eq $taskId) "latest task_id mismatch."
Assert-True ($latest.codex_native_default_primary -eq $false) "Codex native bulk primary must be off in brain-only default mode."
Assert-True ($latest.codex_brain_only_default -eq $true) "Codex brain-only default flag missing."
Assert-True ($latest.codex_bulk_worker_default_paused -eq $true) "Codex bulk worker pause flag missing."
Assert-True ($latest.default_token_saving_worker_route -eq $true) "Default token-saving worker route missing."
Assert-True ($latest.dp_deepseek_aux_parallel_draft -eq $true) "Legacy DP auxiliary draft compat flag missing."
Assert-True ($latest.dp_deepseek_aux_parallel_draft_legacy_compat_only -eq $true) "DP legacy compat marker missing."
Assert-True ($latest.deepseek_bulk_staging_default -eq $true) "DeepSeek bulk staging default missing."
Assert-True ($latest.deepseek_v4_pro_hard_execution_default -eq $true) "DeepSeek V4 Pro hard execution default missing."
Assert-True ([double]$latest.deepseek_worker_share_target_min -eq 0.80) "DeepSeek worker share target missing."
Assert-True ([double]$latest.codex_supervisor_share_target_max -eq 0.20) "Codex supervisor share target missing."
Assert-True ([string]$latest.qwen_prepaid_cheap_worker_default_first_scope -eq "cheap_extract_classify_compress_only") "Qwen default-first scope is not limited."
Assert-True ($latest.completion_claim_allowed -eq $false) "Phase4 evidence cannot allow completion claim."
Assert-True ($latest.validation.passed -eq $true) "Validation did not pass."

$codexExec = Provider-ById $registry "codex_exec"
$codexSdk = Provider-ById $registry "codex_sdk"
$codexMcp = Provider-ById $registry "codex_mcp_agents"
$deepseek = Provider-ById $registry "deepseek_dp"
$deepseekPro = Provider-ById $registry "deepseek_v4_pro"
$qwenDashscope = Provider-ById $registry "qwen_dashscope"
$qwenCheap = Provider-ById $registry "qwen_prepaid_cheap_worker"
$qwenCode = Provider-ById $registry "qwen_code_diversity_worker"
$qwenQuality = Provider-ById $registry "qwen_quality_aux_worker"
$litellm = Provider-ById $registry "litellm_router"
$temporal = Provider-ById $registry "temporal_activity"

Assert-True ([string]$codexExec.default -eq "on_for_brain_acceptance") "codex_exec is not default brain acceptance."
Assert-True ([string]$codexExec.role -eq "brain_route_high_risk_final_acceptance_executor") "codex_exec role is not brain/final acceptance."
Assert-True ([string]$codexExec.status -eq "ready") "codex_exec is not ready."
Assert-True ([string]$codexSdk.status -eq "ready") "codex_sdk is not ready."
Assert-True ([string]$codexMcp.status -eq "ready") "codex_mcp_agents is not ready."
Assert-True ($deepseek.primary_bulk_staging_worker -eq $true) "DeepSeek Flash is not marked as bulk staging worker."
Assert-True ($deepseek.outputs_to_staging_only -eq $true) "DeepSeek Flash can write outside staging."
Assert-True ($deepseekPro.primary_hard_staging_worker -eq $true) "DeepSeek V4 Pro is not marked as hard staging worker."
Assert-True ($deepseekPro.deepseek_v4_pro_main_worker_eligible -eq $true) "DeepSeek V4 Pro main worker eligibility missing."
Assert-True ([string]$qwenDashscope.status -eq "ready") "Qwen DashScope account is not ready."
Assert-True ([string]$qwenCheap.status -eq "ready") "Qwen prepaid cheap worker is not ready."
Assert-True ([string]$qwenCheap.default -eq "on_first_for_cheap_work") "Qwen cheap worker default marker missing."
Assert-True ([string]$registry.qwen_prepaid_cheap_worker_default_first_scope -eq "cheap_extract_classify_compress_only") "Qwen cheap worker default-first scope is not limited."
Assert-True ($qwenCheap.outputs_to_staging_only -eq $true) "Qwen cheap worker is not staging-only."
Assert-True ($qwenCode.direct_repo_write_allowed -eq $false) "Qwen code diversity worker can write repo."
Assert-True ($qwenQuality.outputs_to_staging_only -eq $true) "Qwen quality worker is not staging-only."
Assert-True ([string]$litellm.status -eq "ready") "LiteLLM Router is not ready."
Assert-True ([string]$temporal.status -eq "ready") "Temporal activity provider is not ready."

foreach ($control in @("open", "close", "pause", "resume", "route", "fallback", "cooldown", "replace", "escalate_to_strong_worker", "downgrade_to_cheap_draft")) {
    Assert-True (@($registry.scheduler_controls) -contains $control) "Scheduler control missing: $control"
}

Assert-True ([string]$executor.status -eq "executor_adapter_ready") "ExecutorAdapter not ready."
Assert-True (@($executor.default_primary_executor_pool).Count -eq 0) "ExecutorAdapter default primary pool should be empty."
Assert-True (@($executor.codex_brain_pool) -contains "codex_exec") "ExecutorAdapter brain pool missing codex_exec."
Assert-True (@($executor.codex_brain_pool) -contains "codex_sdk") "ExecutorAdapter brain pool missing codex_sdk."
Assert-True (@($executor.default_staging_executor_pool) -contains "deepseek_dp") "ExecutorAdapter staging pool missing deepseek_dp."
Assert-True (@($executor.default_staging_executor_pool) -contains "deepseek_v4_pro") "ExecutorAdapter staging pool missing deepseek_v4_pro."
Assert-True ($executor.adapters.codex_exec.windows_no_window -eq $true) "codex_exec adapter is not no-window."
Assert-True ($executor.adapters.codex_exec.enabled -eq $true) "codex_exec adapter disabled."
Assert-True ($executor.adapters.codex_sdk.enabled -eq $true) "codex_sdk adapter disabled."
Assert-True ($executor.adapters.codex_mcp_agents.enabled -eq $true) "codex_mcp_agents adapter disabled."
Assert-True ($executor.adapters.deepseek_dp.outputs_to_staging_only -eq $true) "DP adapter is not staging-only."
Assert-True ($executor.adapters.qwen_prepaid_cheap_worker.outputs_to_staging_only -eq $true) "Qwen adapter is not staging-only."
Assert-True ($executor.adapters.qwen_prepaid_cheap_worker.direct_repo_write_allowed -eq $false) "Qwen adapter can write repo."

Assert-True ([string]$gateway.status -eq "model_gateway_ready") "ModelGateway not ready."
Assert-True (Test-Path -LiteralPath $modelGatewayConfigPath -PathType Leaf) "ModelGateway config missing."
Assert-True ((Get-Content -LiteralPath $modelGatewayConfigPath -Raw -Encoding UTF8).Contains("os.environ/OPENAI_API_KEY")) "ModelGateway config leaked or missed env var ref."
Assert-True ((Get-Content -LiteralPath $modelGatewayConfigPath -Raw -Encoding UTF8).Contains("os.environ/DASHSCOPE_API_KEY")) "ModelGateway config missing DashScope env var ref."
Assert-True ((Get-Content -LiteralPath $modelGatewayConfigPath -Raw -Encoding UTF8).Contains("qwen-prepaid-cheap-worker")) "ModelGateway config missing Qwen route."
Assert-True ((Get-Content -LiteralPath $modelGatewayConfigPath -Raw -Encoding UTF8).Contains("codex-brain-acceptance")) "ModelGateway config missing Codex brain route."
Assert-True (-not (Get-Content -LiteralPath $modelGatewayConfigPath -Raw -Encoding UTF8).Contains("codex-primary-engineering")) "ModelGateway still contains old Codex primary route."
Assert-True (@($gateway.router_controls) -contains "fallback") "ModelGateway fallback missing."
Assert-True (@($gateway.router_controls) -contains "cooldown") "ModelGateway cooldown missing."
foreach ($route in @($gateway.routes)) {
    if ([string]$route.route_id -ne "codex-brain-acceptance") {
        Assert-True ((@($route.providers) -notcontains "codex_exec") -and (@($route.providers) -notcontains "codex_sdk") -and (@($route.providers) -notcontains "codex_mcp_agents")) "ModelGateway has Codex in non-brain route: $($route.route_id)"
    }
}

Assert-True (@($decision.active_primary_executor_pool).Count -eq 0) "Codex primary executor pool must be empty in brain-only default mode."
Assert-True (@($decision.active_codex_brain_pool) -contains "codex_exec") "codex_exec not in active brain pool."
Assert-True (@($decision.active_codex_brain_pool) -contains "codex_sdk") "codex_sdk not in active brain pool."
Assert-True (@($decision.active_prepaid_cheap_pool) -contains "qwen_prepaid_cheap_worker") "Qwen cheap worker not in active prepaid cheap pool."
Assert-True ([string]$decision.route_policy.draft_extraction_classify_eval[0] -eq "qwen_prepaid_cheap_worker") "Qwen is not first for cheap extraction/classify/eval."
Assert-True ([string]$decision.route_policy.cheap_parallel_draft[0] -eq "deepseek_dp") "DeepSeek DP is not first for bulk cheap parallel draft."
Assert-True ([string]$decision.route_policy.engineering_patch_or_test[0] -eq "deepseek_v4_pro") "DeepSeek V4 Pro is not first for engineering candidate work."
Assert-True ([string]$decision.route_policy.complex_audit_contradiction_key_plan_review[0] -eq "deepseek_v4_pro") "DeepSeek V4 Pro is not first for complex audit/plan/review."
Assert-True ([double]$decision.codex_brain_only_budget.target_deepseek_worker_share_min -eq 0.80) "DeepSeek worker share target mismatch."
foreach ($routeName in @("engineering_patch_or_test", "long_running_thread", "specialist_tool_delegate", "draft_extraction_classify_eval", "cheap_parallel_draft", "code_candidate_diversity", "complex_audit_contradiction_key_plan_review", "source_family_research")) {
    $route = @($decision.route_policy.$routeName)
    Assert-True (($route -notcontains "codex_exec") -and ($route -notcontains "codex_sdk") -and ($route -notcontains "codex_mcp_agents")) "Codex appears in non-brain route: $routeName"
}
Assert-True (@($decision.route_policy.codex_brain_decision) -contains "codex_exec") "Codex brain decision route missing codex_exec."
Assert-True (@($decision.route_policy.high_risk_patch_or_repo_mutation) -contains "codex_exec") "High-risk repo mutation route missing Codex."
Assert-True (@($decision.route_policy.final_merge_artifact_acceptance) -contains "codex_exec") "Final acceptance route missing Codex."
Assert-True ($decision.dynamic_width_policy.no_fixed_target_width -eq $true) "Dynamic width still looks fixed."
Assert-True ($decision.dp_not_unique_default_primary -eq $true) "DP default-primary guard missing."
Assert-True ($decision.codex_native_execution_default_primary -eq $false) "Codex native bulk execution default guard should be false."
Assert-True ($decision.codex_brain_only_default -eq $true) "Codex brain-only decision flag missing."
Assert-True ($decision.codex_bulk_worker_default_paused -eq $true) "Codex bulk worker was not paused."
Assert-True ([double]$decision.codex_brain_only_budget.target_codex_share_min -eq 0.10) "Codex min target share mismatch."
Assert-True ([double]$decision.codex_brain_only_budget.target_codex_share_max -eq 0.20) "Codex max target share mismatch."

Assert-True ([string]$qwenPolicy.status -eq "qwen_prepaid_policy_ready") "Qwen prepaid policy is not ready."
Assert-True ($qwenPolicy.outputs_to_staging_only -eq $true) "Qwen prepaid policy is not staging-only."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$qwenPolicy.secret_status.api_key_source_label)) "Qwen key source label missing."
Assert-True ([int]$staging.staged_count -ge 5) "staged_count too low."
Assert-True ([int]$merge.merged_count -ge 1) "merged_count missing."
Assert-True (Test-Path -LiteralPath ([string]$merge.merge_artifact) -PathType Leaf) "merge artifact missing."
Assert-True ([string]$manifest.status -eq "registered") "Capability manifest not registered."
Assert-True (@($manifest.capability_kinds) -contains "provider_scheduler") "Capability manifest missing provider_scheduler."

Assert-True ([string]$temporalActivity.activity -eq "codex_native_provider_scheduler_phase4") "Temporal activity evidence has wrong activity."
Assert-True ([string]$temporalActivity.status -eq "activity_gate_checked") "Temporal activity did not gate-check."
Assert-True ($temporalActivity.validation_passed -eq $true) "Temporal activity validation did not pass."
Assert-True ($temporalActivity.codex_native_default_primary -eq $false) "Temporal activity still marks Codex native primary."
Assert-True ($temporalActivity.codex_brain_only_default -eq $true) "Temporal activity missing Codex brain-only default."
Assert-True ($temporalActivity.codex_bulk_worker_default_paused -eq $true) "Temporal activity missing Codex bulk worker pause."
Assert-True ($temporalActivity.default_token_saving_worker_route -eq $true) "Temporal activity missing token-saving route."
Assert-True ([string]$temporalActivity.temporal.activity_name -eq "codex_native_provider_scheduler_phase4_activity") "Temporal activity name missing."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$temporalActivity.temporal.workflow_id)) "Temporal workflow_id missing."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$temporalActivity.temporal.workflow_run_id)) "Temporal workflow_run_id missing."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$temporalActivity.temporal.task_queue)) "Temporal task_queue missing."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$temporalActivity.temporal.worker_identity)) "Temporal worker_identity missing."

Assert-True (-not [string]::IsNullOrWhiteSpace([string]$invocation.status)) "Provider invocation status missing."
Assert-True (($invocation.codex_exec.succeeded -eq $true) -or (-not [string]::IsNullOrWhiteSpace([string]$invocation.codex_exec.named_blocker))) "codex_exec canary has neither success nor named blocker."
Assert-True (($qwenInvocation.succeeded -eq $true) -or (-not [string]::IsNullOrWhiteSpace([string]$qwenInvocation.named_blocker))) "Qwen canary has neither success nor named blocker."
Assert-True ([string]$qwenInvocation.api_key_source_label -ne "") "Qwen canary key source label missing."

foreach ($needle in @("invoke", "codex exec", "openai_codex", "agents", "deepseek", "qwen", "dashscope", "codex_brain")) {
    Assert-True ($readbackLower.Contains($needle.ToLowerInvariant())) "readback missing $needle."
}

Write-Output "phase4_latest=$latestPath"
Write-Output "provider_registry=$providerRegistryPath"
Write-Output "executor_adapter=$executorAdapterPath"
Write-Output "model_gateway=$modelGatewayPath"
Write-Output "scheduler_decision=$schedulerDecisionPath"
Write-Output "qwen_prepaid_policy=$qwenPrepaidPolicyPath"
Write-Output "qwen_invocation=$qwenInvocationPath"
Write-Output "provider_invocation=$providerInvocationPath"
Write-Output "draft_staging=$draftStagingPath"
Write-Output "merge_consumer=$mergeConsumerPath"
Write-Output "temporal_activity=$temporalActivityPath"
Write-Output "capability_manifest=$manifestPath"
Write-Output "readback=$readbackPath"
Write-Output "codex_native_provider_scheduler_phase4=PASS"
