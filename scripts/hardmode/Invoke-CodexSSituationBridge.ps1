[CmdletBinding()]
param(
    [string]$Workspace = "C:\Users\xx363\Desktop\Codex_Admin_Isolated\workspace",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$TaskId = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function Write-JsonAtomic {
    param(
        [string]$Path,
        [object]$Value,
        [int]$Depth = 12
    )
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $tmp = "$Path.$PID.tmp"
    ($Value | ConvertTo-Json -Depth $Depth) + [Environment]::NewLine | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Write-TextAtomic {
    param(
        [string]$Path,
        [string]$Value
    )
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $tmp = "$Path.$PID.tmp"
    $Value + [Environment]::NewLine | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Convert-OutputLines {
    param([object[]]$Items)
    $lines = @()
    foreach ($item in @($Items)) {
        if ($null -eq $item) { continue }
        $text = [string]$item
        if (-not [string]::IsNullOrWhiteSpace($text)) {
            $lines += $text
        }
    }
    return @($lines)
}

function New-UnicodeString {
    param([int[]]$Codepoints)
    return -join ($Codepoints | ForEach-Object { [string]([char]$_) })
}

$bridgeRoot = Join-Path $Workspace "codex-admin-bridge"
$situationScript = Join-Path $bridgeRoot "Get-CodexSituation.ps1"
$preferenceScript = Join-Path $bridgeRoot "Update-CodexSPreferenceRecall.ps1"
$objectRegistryScript = Join-Path $bridgeRoot "Update-CodexSIntentFunctionalObjects.ps1"
$windowContextScript = Join-Path $RepoRoot "services\agent_runtime\codex_s_window_context_contract.py"
$grokBridgeRoot = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge"
$stateDir = Join-Path $RuntimeRoot "state\codex_s_situation_bridge"
$latestPath = Join-Path $stateDir "latest.json"
$windowContextContractPath = Join-Path $RuntimeRoot "state\codex_s_window_context_contract\latest.json"
$metaObjectRouterStatePath = Join-Path $RuntimeRoot "state\codex_s_meta_object_router\latest.json"
$defaultHotpathAutoDpScript = Join-Path $RepoRoot "services\agent_runtime\codex_s_default_hotpath_auto_dp.py"
$defaultHotpathAutoDpStatePath = Join-Path $RuntimeRoot "state\codex_s_default_hotpath_auto_dp\latest.json"
$rootIntent333StatePath = Join-Path $RuntimeRoot "state\codex_s_333_global_isomorphism\latest.json"
$rootIntent333ReadbackPath = Join-Path $RuntimeRoot "readback\zh\codex_s_333_global_isomorphism_20260703.md"
$routeAnchor333Path = Join-Path $grokBridgeRoot "xinao_route_anchor_333.v1.json"
$defaultTriggerCandidateStatePath = Join-Path $RuntimeRoot "state\default_main_loop_trigger_candidate\latest.json"
$taskScopedTriggerEnforcementPath = Join-Path $RuntimeRoot "state\root_intent_loop_driver\default_trigger_enforcement_latest.json"
$taskScopedTriggerEnforcementReadbackPath = Join-Path $RuntimeRoot "readback\zh\codex_s_333_loop_width_nextwave_20260703.md"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

$newSystemDirName = New-UnicodeString @(0x65B0, 0x7CFB, 0x7EDF)
$authorityRoot = Join-Path "C:\Users\xx363\Desktop" $newSystemDirName
$taskPackageManifestPath = Join-Path $authorityRoot "TASK_PACKAGE.json"
$rootIntent333UserAnchorPath = Join-Path $authorityRoot "XINAO_333_固定锚点.txt"
$rootIntentRefPath = Join-Path $authorityRoot "根意图分工.txt"
$taskPackageResources = @()
if (Test-Path -LiteralPath $taskPackageManifestPath) {
    try {
        $taskPackageJson = Get-Content -Raw -LiteralPath $taskPackageManifestPath | ConvertFrom-Json
        if ($null -ne $taskPackageJson.resources) {
            foreach ($resource in @($taskPackageJson.resources)) {
                if ($resource.read -eq "reference_only" -or $resource.reference_only -eq $true -or $resource.exclude -eq $true) {
                    continue
                }
                if ($resource.path) {
                    $taskPackageResources += (Join-Path $authorityRoot ([string]$resource.path))
                }
            }
        }
    } catch {
        $taskPackageResources = @()
    }
}
if ($taskPackageResources.Count -eq 0) {
    $taskPackageResources = @($taskPackageManifestPath)
}

$rootIntent333Binds = @(
    "CODEX_S_L0.md first boot paragraph"
    "SessionStart situation bridge"
    "contracts/codex-s-workspace-boundary.v1.json"
    "D:\XINAO_RESEARCH_RUNTIME\specs\max_benefit_dynamic_loop_authority_20260702.v1.md"
    $authorityRoot
    $taskPackageManifestPath
    $rootIntent333UserAnchorPath
    $rootIntentRefPath
    $taskPackageResources
)
$rootIntent333ForbiddenDefaults = @(
    "closure_one_wave_pass_report_readback_as_stop"
    "loop_owner_split_from_width_owner"
    "width_1_global_cap_without_named_blocker"
    "codex_subagent_as_dp_bulk_replacement"
    "provider_probe_as_main_task_progress"
    "legacy_5d33_hot_path_owner"
)
$rootIntent333DiskTruthRefs = @(
    (Join-Path $RuntimeRoot "state\root_intent_loop_driver\latest.json")
    (Join-Path $RuntimeRoot "state\worker_dispatch_ledger\latest.json")
    (Join-Path $RuntimeRoot "agent_runtime\relay\dp\latest.json")
)
$rootIntent333GlobalFive = [ordered]@{
    roles = "user_to_grok_preserve_supervise_to_execution_brain_dispatch_to_durable_owner_continue_to_mature_workers_execute_dp_is_worker_pool"
    loop_owner = "RootIntentLoop while: restore -> dispatch -> poll -> fan_in -> acceptance -> zh_readback -> next_wave"
    width_owner = "frontier_portfolio + mature_router_provider_concurrency + dp_model_modes decide width; target healthy 20 and high 50 by headroom"
    memory = "durable runtime records plus task-bound disk evidence; chat, PASS, latest, and reports are not completion"
    intent = "isomorphic_expand_only; forbid shrink, object swap, and micro-wave as main chain"
}
$rootIntent333CurrentExtensionBinding = [ordered]@{
    task_package_manifest = $taskPackageManifestPath
    task_package_resources = @($taskPackageResources)
    authority_read_order = "legacy_fallback_only_when_no_task_package_manifest"
    authority_primary = "task_package_entrypoint_or_first_resource"
    authority_execution = "task_package_resources"
    work_id = "xinao_seed_cortex_phase0_20260701"
    route_profile = "seed_cortex_phase0"
    execution_surface = "Codex S @ E:\XINAO_RESEARCH_WORKSPACES\S"
    evidence_root = $RuntimeRoot
    loop_semantics = "RootIntentLoop 20260702 section 0"
    width_semantics = "max-benefit dynamic parallelism 20260702 section 1"
    unique_authority_entry_root = $authorityRoot
}
$rootIntent333Payload = [ordered]@{
    schema_version = "xinao.codex_s.333_global_isomorphism.v1"
    status = "codex_s_333_global_isomorphism_ready"
    task_id = $TaskId
    generated_at = (Get-Date).ToString("o")
    semantic_id = "333"
    semantic_kind = "global_isomorphism_command"
    role = "global_isomorphism_command_current_new_system_extension_binding"
    meaning_cn = "333 是新系统全局同构口令：角色、循环 owner、宽度 owner、记忆、意图五条同一形状；当前扩展绑定当前任务包 manifest/resources、work_id、Codex S 和 D 盘证据。旧读序和旧总稿只在没有当前任务包 manifest 时作为 legacy fallback/reference。333 不是用户完成裁决者，也不是 5d33 控制面；但它约束执行形状，禁止一轮 closure/PASS/报告/readback 当停点、禁止 loop 与 width 各飞、禁止 provider_probe bulk 冒充成熟 DP 进展。"
    anchor_refs = [ordered]@{
        user_anchor = $rootIntent333UserAnchorPath
        machine_anchor = $routeAnchor333Path
        root_intent_ref = $rootIntentRefPath
        unique_authority_entry_root = $authorityRoot
        task_package_manifest = $taskPackageManifestPath
        task_package_resources = @($taskPackageResources)
    }
    trigger_runtime_refs = [ordered]@{
        default_main_loop_trigger_candidate_ref = $defaultTriggerCandidateStatePath
        default_main_loop_trigger_candidate_is_candidate_view = $true
        task_scoped_trigger_enforcement_ref = $taskScopedTriggerEnforcementPath
        task_scoped_trigger_enforcement_readback_zh = $taskScopedTriggerEnforcementReadbackPath
        task_scoped_trigger_enforcement_scope = "seed_cortex_root_intent_loop_driver"
        task_scoped_trigger_enforcement_not_user_completion = $true
    }
    binds = @($rootIntent333Binds)
    not_narrow_startup_tag = $true
    current_new_system_extension_bound = $true
    unique_authority_entry_root = $authorityRoot
    unique_authority_entry_enforced = $true
    old_desktop_root_authority_fallback_allowed = $false
    isomorphism_axes = @("roles", "root_intent_loop_owner", "width_owner", "memory", "intent")
    global_isomorphism_five = $rootIntent333GlobalFive
    current_extension_binding = $rootIntent333CurrentExtensionBinding
    loop_owner_collected = "root_intent_loop"
    width_owner_collected = "frontier_width_scheduler"
    loop_width_same_scheduler_topology_required = $true
    root_intent_loop_required = $true
    frontier_width_scheduler_required = $true
    dp_model_modes_bulk_required = $true
    chinese_readback_required = $true
    one_wave_closure_stop_allowed = $false
    pass_report_readback_stop_allowed = $false
    provider_probe_bulk_progress_allowed = $false
    grok_package_rank0_when_present = $true
    legacy_5d33_role = "metaphor_reference_only"
    legacy_5d33_owner_allowed = $false
    completion_claim_allowed = $false
    not_task_completion_owner = $true
    not_user_completion = $true
    not_completion_decision = $true
    forbidden_defaults = @($rootIntent333ForbiddenDefaults)
    disk_truth_read_before_dispatch = @($rootIntent333DiskTruthRefs)
    adoption_state = "session_start_global_isomorphism_ready"
    missing_to_runtime_enforced = @(
        "Default main-loop trigger and width scheduler must be welded into the same runtime-enforced topology before claiming 333 hot-path runtime enforcement."
        "Concrete tasks must still prove real invoke, fan-in, accepted artifact/evidence, and Chinese readback; 333 correction is not user completion."
    )
    evidence_refs = [ordered]@{
        l0 = Join-Path $RepoRoot "CODEX_S_L0.md"
        session_start_bridge = Join-Path $RepoRoot "scripts\hardmode\Invoke-CodexSSituationBridge.ps1"
        contract_island = Join-Path $RepoRoot "contracts\codex-s-workspace-boundary.v1.json"
        spec_mirror = Join-Path $RuntimeRoot "specs\max_benefit_dynamic_loop_authority_20260702.v1.md"
        user_anchor = $rootIntent333UserAnchorPath
        root_intent = $rootIntentRefPath
        machine_anchor = $routeAnchor333Path
    }
    readback_refs = [ordered]@{
        runtime_readback_zh = $rootIntent333ReadbackPath
    }
    sentinel = "SENTINEL:XINAO_CODEX_S_333_GLOBAL_ISOMORPHISM_READY"
}
Write-JsonAtomic -Path $rootIntent333StatePath -Value $rootIntent333Payload -Depth 12
$rootIntent333Readback = @"
# Codex S 333 全局同构 readback

SENTINEL:XINAO_CODEX_S_333_GLOBAL_ISOMORPHISM_READY

- 333 已纠偏：它不是窄开机小条款，而是新系统扩展绑定的全局同构口令。
- 唯一权威入口：$($taskPackageManifestPath)；333 锚点、根意图和当前任务资源从 task package 解析，不再把旧读序/旧总稿当当前入口。
- 333 收编五条同构：角色同构、循环 owner、宽度 owner、记忆同构、意图同构。
- 当前扩展绑定：TASK_PACKAGE manifest/resources、work_id xinao_seed_cortex_phase0_20260701、Codex S、D:\XINAO_RESEARCH_RUNTIME。
- loop owner：RootIntentLoop while 未停，恢复 -> 派活 -> poll -> fan-in -> acceptance -> 中文锚定 -> 下一波。
- width owner：frontier + mature router/provider headroom + DP model modes 同一拓扑每波动态决定宽度；临时压测值只写 capacity observation，不写成永久默认。
- 禁止：一轮 PASS/closure/报告/readback/window_end 当停点；loop 与 width 各飞；provider_probe bulk 冒充成熟 DP 进展；5d33 抢 333 owner。
- 333 不是用户完成裁决者，也不是旧 5d33 控制面；但它约束默认执行形状。
- bridge ref：$($rootIntent333StatePath)
- anchor ref：$($rootIntent333UserAnchorPath)
- root intent ref：$($rootIntentRefPath)
- default trigger candidate ref：$($defaultTriggerCandidateStatePath)
- task-scoped trigger enforcement ref：$($taskScopedTriggerEnforcementPath)
- task-scoped trigger enforcement readback：$($taskScopedTriggerEnforcementReadbackPath)
- machine mirror：$($routeAnchor333Path)
- 当前 task_id：$($TaskId)

当前磁盘事实边界：
- RootIntentLoop driver latest 是 trigger、DP、fan-in、ArtifactAcceptance、ContinuityEnvelope 的当前磁盘事实入口。
- DP bulk 必须从 root_intent_loop_driver.latest 的 dp_port_poll / default_trigger_enforcement 读取；provider_probe 不可冒充 bulk progress。
- worker_dispatch_ledger 顶层若仍是 verifier_ready_but_not_hooked，只能按 root driver DP poll scope 说 hot path hooked。
- default_main_loop_trigger_candidate 保持候选视图；任务级 trigger enforced 由 root_intent_loop_driver/default_trigger_enforcement_latest.json 承载。

还缺什么才能进下一状态：
- 每一波都要确认 default main-loop trigger 与 width scheduler 焊进同一 runtime-enforced 拓扑。
- 具体任务仍要真实 invoke、fan-in、accepted artifact/evidence、中文 readback；333 纠偏本身不是用户完成。
"@
Write-TextAtomic -Path $rootIntent333ReadbackPath -Value $rootIntent333Readback

$rootIntent333BridgeSummary = [ordered]@{
    semantic_id = "333"
    state_ref = $rootIntent333StatePath
    readback_ref = $rootIntent333ReadbackPath
    user_anchor_ref = $rootIntent333UserAnchorPath
    root_intent_ref = $rootIntentRefPath
    machine_anchor_ref = $routeAnchor333Path
    semantic_kind = "global_isomorphism_command"
    role = "global_isomorphism_command_current_new_system_extension_binding"
    meaning_cn = $rootIntent333Payload.meaning_cn
    not_narrow_startup_tag = $true
    current_new_system_extension_bound = $true
    unique_authority_entry_root = $authorityRoot
    unique_authority_entry_enforced = $true
    old_desktop_root_authority_fallback_allowed = $false
    trigger_runtime_refs = [ordered]@{
        default_main_loop_trigger_candidate_ref = $defaultTriggerCandidateStatePath
        default_main_loop_trigger_candidate_is_candidate_view = $true
        task_scoped_trigger_enforcement_ref = $taskScopedTriggerEnforcementPath
        task_scoped_trigger_enforcement_readback_zh = $taskScopedTriggerEnforcementReadbackPath
        task_scoped_trigger_enforcement_scope = "seed_cortex_root_intent_loop_driver"
        task_scoped_trigger_enforcement_not_user_completion = $true
    }
    isomorphism_axes = @("roles", "root_intent_loop_owner", "width_owner", "memory", "intent")
    global_isomorphism_five = $rootIntent333GlobalFive
    current_extension_binding = $rootIntent333CurrentExtensionBinding
    loop_owner_collected = "root_intent_loop"
    width_owner_collected = "frontier_width_scheduler"
    loop_width_same_scheduler_topology_required = $true
    one_wave_closure_stop_allowed = $false
    pass_report_readback_stop_allowed = $false
    provider_probe_bulk_progress_allowed = $false
    legacy_5d33_role = "metaphor_reference_only"
    legacy_5d33_owner_allowed = $false
    not_task_completion_owner = $true
    not_user_completion = $true
    not_completion_decision = $true
    completion_claim_allowed = $false
    missing_to_runtime_enforced = @(
        "Concrete waves must prove task-scoped trigger enforcement, real invoke, fan-in, accepted artifact/evidence, and Chinese readback."
        "333 session-start state is not global user completion and not a standalone runtime controller."
    )
    forbidden_defaults = @($rootIntent333ForbiddenDefaults)
}

$results = @()
$status = "ready"
$namedBlockers = @()

if (Test-Path -LiteralPath $preferenceScript -PathType Leaf) {
    try {
        $out = @(& $preferenceScript -Workspace $Workspace -RuntimeRoot $RuntimeRoot 2>&1)
        $results += [ordered]@{ step = "preference_recall"; status = "ok"; output = @(Convert-OutputLines -Items $out) }
    }
    catch {
        $status = "degraded"
        $namedBlockers += "CODEX_S_PREFERENCE_RECALL_REFRESH_FAILED"
        $results += [ordered]@{ step = "preference_recall"; status = "failed"; error = $_.Exception.Message }
    }
}
else {
    $status = "degraded"
    $namedBlockers += "CODEX_S_PREFERENCE_RECALL_SCRIPT_MISSING"
}

if (Test-Path -LiteralPath $objectRegistryScript -PathType Leaf) {
    try {
        $out = @(& $objectRegistryScript -Workspace $Workspace -RuntimeRoot $RuntimeRoot 2>&1)
        $results += [ordered]@{ step = "intent_functional_objects"; status = "ok"; output = @(Convert-OutputLines -Items $out) }
    }
    catch {
        $status = "degraded"
        $namedBlockers += "CODEX_S_INTENT_FUNCTIONAL_OBJECTS_REFRESH_FAILED"
        $results += [ordered]@{ step = "intent_functional_objects"; status = "failed"; error = $_.Exception.Message }
    }
}
else {
    $status = "degraded"
    $namedBlockers += "CODEX_S_INTENT_FUNCTIONAL_OBJECTS_SCRIPT_MISSING"
}

if (Test-Path -LiteralPath $situationScript -PathType Leaf) {
    try {
        $out = @(& $situationScript -RuntimeRoot $RuntimeRoot -RepoRoot $RepoRoot -Workspace $Workspace -CodexSLauncher "C:\Users\xx363\Desktop\OPEN CODEX S HARDMODE.lnk" -LegacyCodexALauncher "C:\Users\xx363\Desktop\OPEN CODEX A HARDMODE.lnk" 2>&1)
        $results += [ordered]@{ step = "situation_refresh"; status = "ok"; output = @(Convert-OutputLines -Items $out) }
    }
    catch {
        $status = "degraded"
        $namedBlockers += "CODEX_S_SITUATION_REFRESH_FAILED"
        $results += [ordered]@{ step = "situation_refresh"; status = "failed"; error = $_.Exception.Message }
    }
}
else {
    $status = "degraded"
    $namedBlockers += "CODEX_S_SITUATION_SCRIPT_MISSING"
}

$payload = [ordered]@{
    schema_version = "xinao.codex_s_situation_bridge.v1"
    status = $status
    generated_at = (Get-Date).ToString("o")
    workspace = $Workspace
    repo_root = $RepoRoot
    runtime_root = $RuntimeRoot
    preference_recall_ref = Join-Path $Workspace "agent-tools\codex_s_operator_preference_recall.json"
    intent_functional_objects_ref = Join-Path $Workspace "agent-tools\codex_s_intent_functional_objects.json"
    situation_ref = Join-Path $Workspace "agent-tools\current_situation_for_codex.json"
    mature_capability_catalog_ref = Join-Path $Workspace "agent-tools\mature_capability_catalog.json"
    window_context_contract_ref = $windowContextContractPath
    meta_object_router_ref = $metaObjectRouterStatePath
    root_intent_333_ref = $rootIntent333StatePath
    root_intent_333_readback_ref = $rootIntent333ReadbackPath
    root_intent_333_user_anchor_ref = $rootIntent333UserAnchorPath
    root_intent_333_machine_anchor_ref = $routeAnchor333Path
    root_intent_333 = $rootIntent333BridgeSummary
    authority_read_order_ref = [ordered]@{
        path = $authorityReadOrderPath
        exists = (Test-Path -LiteralPath $authorityReadOrderPath -PathType Leaf)
        role = "current two-file Seed Cortex S human authority read order"
    }
    authority_text_refs = @($authorityTextPaths | ForEach-Object {
        [ordered]@{
            path = $_
            exists = (Test-Path -LiteralPath $_ -PathType Leaf)
            role = "current Seed Cortex S two-file authority text"
        }
    })
    codex_s_contract_ref = Join-Path $RepoRoot "contracts\codex-s-workspace-boundary.v1.json"
    codex_s_l0_ref = Join-Path $RepoRoot "CODEX_S_L0.md"
    fail_open = $true
    blocks_session = $false
    blocks_tools = $false
    blocks_delivery = $false
    named_blockers = @($namedBlockers)
    results = @($results)
    not_source_of_truth = $true
    not_user_completion = $true
    not_completion_decision = $true
    not_execution_controller = $true
    sentinel = $(if ($status -eq "ready") { "SENTINEL:XINAO_CODEX_S_SITUATION_BRIDGE_READY" } else { "SENTINEL:XINAO_CODEX_S_SITUATION_BRIDGE_DEGRADED" })
}

Write-JsonAtomic -Path $latestPath -Value $payload -Depth 12

if (Test-Path -LiteralPath $windowContextScript -PathType Leaf) {
    try {
        $out = @(python $windowContextScript `
            --runtime-root $RuntimeRoot `
            --repo-root $RepoRoot `
            --workspace $Workspace `
            --grok-bridge-root $grokBridgeRoot 2>&1)
        $results += [ordered]@{ step = "window_context_contract_and_meta_router"; status = "ok"; output = @(Convert-OutputLines -Items $out) }
        if (-not (Test-Path -LiteralPath $metaObjectRouterStatePath -PathType Leaf)) {
            $status = "degraded"
            $namedBlockers += "CODEX_S_META_OBJECT_ROUTER_STATE_MISSING_AFTER_REFRESH"
        }
    }
    catch {
        $status = "degraded"
        $namedBlockers += "CODEX_S_WINDOW_CONTEXT_CONTRACT_REFRESH_FAILED"
        $results += [ordered]@{ step = "window_context_contract_and_meta_router"; status = "failed"; error = $_.Exception.Message }
    }
}
else {
    $status = "degraded"
    $namedBlockers += "CODEX_S_WINDOW_CONTEXT_CONTRACT_SCRIPT_MISSING"
}

if (Test-Path -LiteralPath $defaultHotpathAutoDpScript -PathType Leaf) {
    try {
        $pythonArgs = @(
            $defaultHotpathAutoDpScript,
            "--runtime-root", $RuntimeRoot,
            "--repo-root", $RepoRoot,
            "--invoked-by", "scripts/hardmode/Invoke-CodexSSituationBridge.ps1",
            "--runtime-enforced-scope", "s_session_start_situation_bridge_default_hotpath_auto_dp"
        )
        if (-not [string]::IsNullOrWhiteSpace($TaskId)) {
            $pythonArgs += @("--task-id", $TaskId)
        }
        $out = @(python @pythonArgs 2>&1)
        if ($LASTEXITCODE -ne 0) {
            $status = "degraded"
            $namedBlockers += "CODEX_S_DEFAULT_HOTPATH_AUTO_DP_FAILED"
            $results += [ordered]@{ step = "default_hotpath_auto_dp"; status = "failed"; exit_code = $LASTEXITCODE; output = @(Convert-OutputLines -Items $out) }
        }
        else {
            $defaultHotpathAutoDpOutputLines = @(Convert-OutputLines -Items $out)
            $results += [ordered]@{
                step = "default_hotpath_auto_dp"
                status = "ok"
                state_ref = $defaultHotpathAutoDpStatePath
                runtime_enforced_scope = "s_session_start_situation_bridge_default_hotpath_auto_dp"
                raw_stdout_embedded = $false
                output_line_count = $defaultHotpathAutoDpOutputLines.Count
            }
        }
    }
    catch {
        $status = "degraded"
        $namedBlockers += "CODEX_S_DEFAULT_HOTPATH_AUTO_DP_FAILED_OPEN"
        $results += [ordered]@{ step = "default_hotpath_auto_dp"; status = "failed"; error = $_.Exception.Message }
    }
}
else {
    $status = "degraded"
    $namedBlockers += "CODEX_S_DEFAULT_HOTPATH_AUTO_DP_SCRIPT_MISSING"
}

$payload["status"] = $status
$payload["named_blockers"] = @($namedBlockers)
$payload["results"] = @($results)
$payload["window_context_contract_ref"] = $windowContextContractPath
$payload["meta_object_router_ref"] = $metaObjectRouterStatePath
$payload["root_intent_333_ref"] = $rootIntent333StatePath
$payload["root_intent_333_readback_ref"] = $rootIntent333ReadbackPath
$payload["root_intent_333_user_anchor_ref"] = $rootIntent333UserAnchorPath
$payload["root_intent_333_machine_anchor_ref"] = $routeAnchor333Path
$payload["root_intent_333"] = $rootIntent333BridgeSummary
$payload["default_hotpath_auto_dp_ref"] = $defaultHotpathAutoDpStatePath
$payload["sentinel"] = $(if ($status -eq "ready") { "SENTINEL:XINAO_CODEX_S_SITUATION_BRIDGE_READY" } else { "SENTINEL:XINAO_CODEX_S_SITUATION_BRIDGE_DEGRADED" })
Write-JsonAtomic -Path $latestPath -Value $payload -Depth 12

if (-not $Quiet) {
    Write-Output "CODEX S SITUATION BRIDGE"
    Write-Output "status = $status"
    Write-Output "preference_recall_ref = $($payload.preference_recall_ref)"
    Write-Output "intent_functional_objects_ref = $($payload.intent_functional_objects_ref)"
    Write-Output "situation_ref = $($payload.situation_ref)"
    Write-Output "window_context_contract_ref = $($payload.window_context_contract_ref)"
    Write-Output "meta_object_router_ref = $($payload.meta_object_router_ref)"
    Write-Output "root_intent_333_ref = $($payload.root_intent_333_ref)"
    Write-Output "root_intent_333_readback_ref = $($payload.root_intent_333_readback_ref)"
    Write-Output "state_ref = $latestPath"
    Write-Output $payload.sentinel
}

exit 0
