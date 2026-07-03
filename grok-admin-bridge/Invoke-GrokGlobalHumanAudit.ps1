[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [string]$ChecklistPath = "",
    [string]$RuntimeRoot = "D:\XINAO_CLEAN_RUNTIME",
    [int]$GitStatusMaxLines = 40
)

$ErrorActionPreference = "Stop"
$GrokBridgeRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
if (-not $ConfigPath) { $ConfigPath = Join-Path $GrokBridgeRoot "bridge.config.json" }
if (-not $ChecklistPath) { $ChecklistPath = Join-Path $GrokBridgeRoot "global_human_audit_checklist.json" }
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function Read-JsonFile {
    param([string]$Path, $Default = $null)
    if (-not (Test-Path -LiteralPath $Path)) { return $Default }
    try {
        $utf8 = [System.Text.UTF8Encoding]::new($false)
        $raw = [System.IO.File]::ReadAllText($Path, $utf8)
        return ($raw | ConvertFrom-Json)
    }
    catch { return $Default }
}

function Get-GitSummary {
    param([string]$RepoPath, [int]$MaxLines = 40)
    if (-not (Test-Path -LiteralPath $RepoPath)) {
        return @{ path = $RepoPath; exists = $false; dirty = $null; status_short = @(); branch = ""; ahead_behind = "" }
    }
    Push-Location $RepoPath
    try {
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $branch = ""
        try { $branch = (git rev-parse --abbrev-ref HEAD 2>$null).Trim() } catch {}
        $short = @(git status --short 2>$null | Select-Object -First $MaxLines)
        $ErrorActionPreference = $prevEap
        $dirty = ($short.Count -gt 0)
        $ahead = ""
        try {
            $prevEap2 = $ErrorActionPreference
            $ErrorActionPreference = "SilentlyContinue"
            $upstream = (git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null).Trim()
            if ($upstream) {
                $counts = (git rev-list --left-right --count "HEAD...$upstream" 2>$null) -split "\s+"
                if ($counts.Count -ge 2) { $ahead = "ahead=$($counts[0]) behind=$($counts[1])" }
            }
            $ErrorActionPreference = $prevEap2
        } catch {}
        return @{
            path = $RepoPath
            exists = $true
            dirty = $dirty
            dirty_file_count = $short.Count
            status_short = $short
            branch = $branch
            ahead_behind = $ahead
        }
    }
    finally { Pop-Location }
}

$config = Read-JsonFile -Path $ConfigPath
$checklist = Read-JsonFile -Path $ChecklistPath
$now = Get-Date

# Bridge / ingress / CodexA panel
$bridgeStatus = $null
try {
    $statusScript = Join-Path $GrokBridgeRoot "Get-GrokLocalCapabilityStatus.ps1"
    if (Test-Path -LiteralPath $statusScript) {
        $raw = & $statusScript | Out-String
        $bridgeStatus = $raw | ConvertFrom-Json
    }
} catch {}

$panelState = $null
try {
    if ($config.ingress_base_url) {
        $rb = Invoke-WebRequest -Uri ($config.ingress_base_url.TrimEnd('/') + "/codex-a/panel-readback") -UseBasicParsing -TimeoutSec 15
        $panel = $rb.Content | ConvertFrom-Json
        $panelState = $panel.state
    }
} catch {}

# Intent admission
$intentEpisode = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\xinao-intent-admission\episodes\current_intent_episode.json")
$intentAdmitted = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\xinao-intent-admission\state\current_intent_state.admitted.json")

# Projection
$projectionRadar = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\project_projection_radar\latest.json")
$projectionOps = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\project_projection_ops\latest.json")

# Transaction boundary / execution model memory
$txBoundary = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\codex_default_transaction_boundary\latest.json")

# Exhaustive handroll/mature scan anchors (always-on on any audit lane)
$exhaustiveContractPath = Join-Path $GrokBridgeRoot "grok_exhaustive_handroll_mature_audit.v1.json"
$exhaustiveContract = Read-JsonFile -Path $exhaustiveContractPath
$dispositionMatrix = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\global_object_disposition_matrix\latest.json")
$defaultWorkBinding = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\default_work_binding\latest.json")
$focusedPatchQueue = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\focused_patch_queue\latest.json")
$windowReproContractPath = Join-Path $GrokBridgeRoot "grok_window_reproducibility_self_lock_audit.v1.json"
$windowReproContract = Read-JsonFile -Path $windowReproContractPath
$l0Convergence = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\l0_global_convergence\latest.json")

$handrollPathHints = @(
    "pump", "typeahead", "visible-inject", "visible_inject", "ack_worker", "handroll",
    "anti_handroll", "ucp_dispatch", "mcp_spawn", "latest.json", ".vbs", "action_write",
    "clean_ingress", "19142", "default_work_binding", "auto_exec_ack"
)
$dispositionHandrollSample = @()
if ($dispositionMatrix -and $dispositionMatrix.rows) {
    foreach ($row in $dispositionMatrix.rows) {
        $p = [string]$row.path
        if (-not $p) { continue }
        $pl = $p.ToLowerInvariant()
        $hit = $false
        foreach ($hint in $handrollPathHints) {
            if ($pl.Contains($hint)) { $hit = $true; break }
        }
        if (-not $hit) { continue }
        $dispositionHandrollSample += [ordered]@{
            path = $p
            scope = $row.scope
            disposition = $row.disposition
            current_role = $row.current_role
            mature_replacement = $row.mature_replacement
            risk_flags = @($row.risk_flags)
        }
        if ($dispositionHandrollSample.Count -ge 24) { break }
    }
}

# Git surfaces
# Grok workspace: read bridge evidence only — never suggest Codex writes here (anti self-lock)
$grokWorkspace = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace"
$repos = @(
    @{ path = $config.repo_root; role = "codex_b_nianhua_observe_only"; codex_may_touch = $true }
    @{ path = "C:\Users\xx363\CodexWorkspaces\A"; role = "codex_a_observe_only"; codex_may_touch = $true }
    @{ path = $grokWorkspace; role = "grok_isolated_entry"; codex_may_touch = $false }
)
$gitSummaries = @($repos | ForEach-Object {
    $s = Get-GitSummary -RepoPath $_.path -MaxLines $GitStatusMaxLines
    $s.role = $_.role
    $s.codex_may_touch = $_.codex_may_touch
    [pscustomobject]$s
})

# Heuristic signals for Grok (not verdict — Grok translates to human Chinese)
$signals = [System.Collections.Generic.List[string]]::new()

if ($panelState) {
    if ($panelState.turn_status -eq "RUNNING") { $signals.Add("codex_a_turn_running") }
    if ($panelState.turn_status -eq "COMPLETED" -and $panelState.last_event_at) {
        $last = [datetime]::Parse($panelState.last_event_at)
        if (($now - $last).TotalHours -gt 2) { $signals.Add("codex_a_idle_completed_turn") }
    }
}

# Git dirty / unpushed = deferred_cleanup hints only — NOT mainline alerts (user correction)
$cleanupHints = [System.Collections.Generic.List[string]]::new()
foreach ($g in $gitSummaries) {
    if ($g.codex_may_touch -eq $false) {
        if ($g.exists -and $g.dirty) { $cleanupHints.Add("grok_local_only_not_codex_scope:$($g.path)") }
        continue
    }
    if ($g.exists -and $g.dirty) { $cleanupHints.Add("deferred_cleanup_dirty:$($g.path)") }
    if ($g.exists -and $g.ahead_behind -match "ahead=[1-9]") { $cleanupHints.Add("deferred_cleanup_unpushed:$($g.path)") }
}

if ($projectionRadar) {
    $st = [string]$projectionRadar.status
    if ($st -and $st -ne "projection_scoped_verified") { $signals.Add("projection_not_verified:$st") }
}
if ($projectionOps) {
    $ops = [string]$projectionOps.status
    if ($ops -match "stale|blocked") { $signals.Add("projection_ops_$ops") }
}

if ($intentEpisode -and $intentAdmitted) {
    $ep = [string]$intentEpisode.intent_id
    $ad = [string]$intentAdmitted.current_intent_id
    if ($ep -and $ad -and $ep -ne $ad) { $signals.Add("intent_id_mismatch") }
}

$audit = [ordered]@{
    schema_version = "xinao.grok_global_human_audit.evidence.v1"
    generated_at = $now.ToString("o")
    audit_role = "grok_global_human_side_audit"
    not_user_completion = $true
    not_completion_decision = $true
    not_execution_controller = $true
    checklist_ref = $ChecklistPath
    sole_migration_ref = if ($config.sole_migration_architecture_ref) { $config.sole_migration_architecture_ref } else { "grok-admin-bridge/sole_migration_architecture.v1.json" }
    division_ref = "grok-admin-bridge/grok_parallel_audit_division.v1.json"
    exhaustive_handroll_mature_ref = "grok-admin-bridge/grok_exhaustive_handroll_mature_audit.v1.json"
    exhaustive_handroll_mature_always_on = $true
    global_upgrade_lens_ref = "C:\Users\xx363\Desktop\全局升维.txt"
    window_reproducibility_self_lock_ref = "grok-admin-bridge/grok_window_reproducibility_self_lock_audit.v1.json"
    audit_scope_cn = "尘埃到宇宙：源码/组件/胶水/架构/本地/远端/投影/叙事；不写当前问题也默认全扫"
    window_reproducibility_always_on = $true
    progress_question_cn = if ($config.sole_mission_cn) { "用户跟 Grok 说一句话，中间还有哪一段手搓仍在 default 路径？" } else { "" }
    current_intent_id = if ($intentAdmitted.current_intent_id) { $intentAdmitted.current_intent_id } else { $intentEpisode.intent_id }
    trigger_note_cn = "用户开关触发；Grok 必须将本证据翻译为中文人话四段式结论，不得把原始 JSON 当最终回复"
    codex_a_panel = @{
        turn_status = if ($panelState) { $panelState.turn_status } else { "unknown" }
        active_turn_id = if ($panelState) { $panelState.active_turn_id } else { "" }
        last_event_at = if ($panelState) { $panelState.last_event_at } else { "" }
        named_blocker = if ($panelState) { $panelState.named_blocker } else { "" }
    }
    bridge_capability = @{
        ingress_ok = if ($bridgeStatus.ingress_health.ok) { $bridgeStatus.ingress_health.ok } else { $null }
        codex_a_ready = if ($bridgeStatus.codex_a_panel.ok) { $bridgeStatus.codex_a_panel.ok } else { $null }
    }
    intent_admission = @{
        episode_intent_id = if ($intentEpisode.intent_id) { $intentEpisode.intent_id } else { "" }
        admitted_intent_id = if ($intentAdmitted.current_intent_id) { $intentAdmitted.current_intent_id } else { "" }
        admitted_object_count = if ($intentAdmitted.admitted_object_count) { $intentAdmitted.admitted_object_count } else { 0 }
    }
    projection = @{
        radar_status = if ($projectionRadar.status) { $projectionRadar.status } else { "missing" }
        ops_status = if ($projectionOps.status) { $projectionOps.status } else { "missing" }
    }
    execution_model_memory = @{
        codex_a_brain_only = $true
        forbid_default_handroll = $true
        grok_side_audit_only = $true
        tx_boundary_status = if ($txBoundary.status) { $txBoundary.status } else { "unknown" }
    }
    exhaustive_handroll_mature = @{
        contract_ref = $exhaustiveContractPath
        north_star_cn = if ($exhaustiveContract.north_star_cn) { $exhaustiveContract.north_star_cn } else { "" }
        progress_question_cn = if ($exhaustiveContract.progress_question_cn) { $exhaustiveContract.progress_question_cn } else { "" }
        scan_layers = @($exhaustiveContract.scan_layers)
        verdict_axes = @($exhaustiveContract.verdict_axes)
        handroll_redlines_default = @($exhaustiveContract.handroll_redlines_default)
        global_upgrade_intent_cn = if ($exhaustiveContract.global_upgrade_intent_cn) { $exhaustiveContract.global_upgrade_intent_cn } else { "" }
        fake_upgrade_redlines_cn = @($exhaustiveContract.fake_upgrade_redlines_cn)
        parallel_audit_note_cn = if ($exhaustiveContract.parallel_audit_note_cn) { $exhaustiveContract.parallel_audit_note_cn } else { "" }
    }
    disposition_matrix_hint = @{
        path = Join-Path $RuntimeRoot "state\global_object_disposition_matrix\latest.json"
        exists = [bool]$dispositionMatrix
        status = if ($dispositionMatrix.status) { $dispositionMatrix.status } else { "missing" }
        object_count = if ($dispositionMatrix.coverage.object_count) { $dispositionMatrix.coverage.object_count } else { 0 }
        default_handroll_candidate_sample = @($dispositionHandrollSample)
        audit_use_cn = "穷举：对照 disposition+mature_replacement+default_work_binding.live；matrix ready 不等于用户完成"
    }
    default_work_binding_hint = @{
        path = Join-Path $RuntimeRoot "state\default_work_binding\latest.json"
        exists = [bool]$defaultWorkBinding
        status = if ($defaultWorkBinding.status) { $defaultWorkBinding.status } else { "missing" }
        live = if ($defaultWorkBinding.live) { $defaultWorkBinding.live } elseif ($defaultWorkBinding.binding) { $defaultWorkBinding.binding } else { $null }
        named_blockers = @($defaultWorkBinding.named_blockers)
    }
    focused_patch_queue_hint = @{
        path = Join-Path $RuntimeRoot "state\focused_patch_queue\latest.json"
        exists = [bool]$focusedPatchQueue
        status = if ($focusedPatchQueue.status) { $focusedPatchQueue.status } else { "missing" }
    }
    window_reproducibility_self_lock = @{
        contract_ref = $windowReproContractPath
        north_star_cn = if ($windowReproContract.north_star_cn) { $windowReproContract.north_star_cn } else { "" }
        reproduce_via_cn = @($windowReproContract.reproduce_via_cn)
        not_reproduce_via_cn = @($windowReproContract.not_reproduce_via_cn)
        self_lock_redlines_cn = @($windowReproContract.self_lock_redlines_cn)
        audit_questions_cn = @($windowReproContract.audit_questions_cn)
        l0_convergence_hint = @{
            path = Join-Path $RuntimeRoot "state\l0_global_convergence\latest.json"
            exists = [bool]$l0Convergence
            status = if ($l0Convergence.status) { $l0Convergence.status } else { "missing" }
            hot_path_count = if ($l0Convergence.hot_path_count) { $l0Convergence.hot_path_count } else { $null }
        }
    }
    git_surfaces = $gitSummaries
    git_repo_tier = "opportunistic_cleanup_at_wrap_up_not_mainline"
    deferred_cleanup_hints = @($cleanupHints)
    heuristic_signals = @($signals)
    grok_must_answer_cn = @(
        "还在做原始目标吗？"
        "A 是在分工还是在手搓？"
        "尘埃到宇宙：源码/组件/胶水/架构/本地/远端/投影——真升维还是假升维？手搓还在 default 吗？"
        "有没有功能级改一处坏一处（不是 Git 脏）？"
        "旁支清理有没有被升级成主对象、打断主线？"
        "全局升维在推进吗？还是只加墙/叙事、default 仍手搓？"
        "用户不用懂英文技术能继续吗？"
        "弄完后下窗能默认复现吗？还是在逼全局盘点、hook自锁、重跑canary？"
    )
    grok_must_not_elevate_cn = @(
        "不得把 Git/仓库脏放进 Top3 纠偏"
        "仓库/GitHub 仅收尾顺手清理或用户点名时提及"
        "不得建议 CodexA 修改 Grok isolated 工作区"
        "不得把多工作区不一致升级成跨区联动修复"
    )
    grok_isolation_boundary = @{
        grok_workspace = $grokWorkspace
        codex_must_not_touch_grok = $true
        delivery_direction = "grok_to_codexa_one_way_only"
        anti_self_lock = $true
    }
    output_contract_cn = @{
        sections = @("一句话状态", "你现在真实在哪", "最该立刻纠偏的1-3件事", "建议下一步")
        verdict_options = @("在正路上", "有点偏", "明显跑偏")
        max_corrections = 3
    }
}

$stateDir = Join-Path $RuntimeRoot "state\grok_global_human_audit"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$latestPath = Join-Path $stateDir "latest.json"
$audit | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latestPath -Encoding UTF8

$audit | ConvertTo-Json -Depth 12