#Requires -Version 5.1
<#
.SYNOPSIS
  本机状态感知中间件：打包 Intent 对照所需的 Facts 快照（非安全扫描）。
  授权形状：禁止清单制（deny_list_not_allow_list）— 默认可读尽读；只跳过 deny 项。
  禁止白名单思维收窄「只能看这几个目录」。
.EXAMPLE
  .\Get-GrokLocalStateSense.ps1
  .\Get-GrokLocalStateSense.ps1 -Deep  # 含 PolicyScan 摘要
#>
param(
    [switch]$Deep,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$stateOut = Join-Path $runtime "state\local_state_sense"
$latestPath = Join-Path $stateOut "latest.json"
New-Item -ItemType Directory -Force -Path $stateOut | Out-Null

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 18), $utf8)
}

function Test-TcpPort([int]$Port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $iar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(400)
        if ($ok -and $c.Connected) { $c.Close(); return $true }
        $c.Close(); return $false
    } catch { return $false }
}

function Read-JsonSafe([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}

function Get-FileAgeMinutes([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return [math]::Round(((Get-Date) - (Get-Item -LiteralPath $Path).LastWriteTime).TotalMinutes, 1)
}

# --- deny_list only（禁止清单，不是白名单）---
# 默认可感知：凡可读路径/进程/容器/证据均可纳入；下列为硬跳过或不可把原文塞进聊天。
$denyList = [ordered]@{
    schema = "xinao.state_sense_deny_list.v1"
    principle_cn = "deny_list_not_allow_list — 默认可读尽读；禁止用白名单收窄能力面"
    hard_skip_path_globs = @(
        "**/.git/objects/**",
        "**/node_modules/**",
        "**/.venv/**",
        "**/__pycache__/**",
        "**/*.pyc"
    )
    hard_skip_reason_cn = "体量/噪声排除（性能），不是权限白名单收窄"
    never_emit_raw_to_chat = @(
        "reveal_raw_secret_to_chat_or_repo",
        "**/.env",
        "**/*secret*",
        "**/*credential*",
        "**/id_rsa",
        "**/*.pem",
        "**/AppData/**/Cookies*"
    )
    never_as_goal = @("Trivy", "Grype", "OSV", "Gitleaks", "TruffleHog")
    hard_stop_actions = @(
        "payment_or_billing_commit",
        "2fa_sms_phone_otp",
        "real_name_legal_identity_confirm",
        "irreversible_cloud_delete_without_explicit",
        "self_lock_grok_ingress",
        "delete_desktop_without_explicit"
    )
    ref = "grok_rollback_domain_max_auth.v1.json deny_list_hard_only"
}

function Test-DeniedPath([string]$Path) {
    $p = $Path.ToLowerInvariant()
    foreach ($g in @(
        "\node_modules\", "\.venv\", "\__pycache__\", "\.git\objects\"
    )) {
        if ($p.Contains($g)) { return $true }
    }
    return $false
}

# --- roots：声明锚点 + 动态扩扫（非白名单闭合集）---
$rootCandidates = [System.Collections.Generic.List[object]]::new()
function Add-RootCand([string]$Id, [string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    [void]$rootCandidates.Add([ordered]@{ id = $Id; path = $Path })
}
Add-RootCand "S" "E:\XINAO_RESEARCH_WORKSPACES\S"
Add-RootCand "scan_stack" "E:\XINAO_EXTERNAL_MATURE\scan-stack"
Add-RootCand "external_mature" "E:\XINAO_EXTERNAL_MATURE"
Add-RootCand "workspaces" "E:\XINAO_RESEARCH_WORKSPACES"
Add-RootCand "island_bridge" $bridge
Add-RootCand "island_ws" (Split-Path $bridge -Parent)
Add-RootCand "admin_bridge" "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge"
Add-RootCand "admin_ws" "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace"
Add-RootCand "runtime" $runtime
Add-RootCand "clean_runtime" "D:\XINAO_CLEAN_RUNTIME"
Add-RootCand "glue_constitution" "C:\Users\xx363\Desktop\工具胶水宪法"
Add-RootCand "grok_home" "C:\Users\xx363\.grok"
Add-RootCand "grok_lane" "C:\Users\xx363\.grok-4.5-lane"
# 动态：D:\ state 子目录凡存在均可感知（禁止清单外）
$stateRoot = Join-Path $runtime "state"
if (Test-Path $stateRoot) {
    Get-ChildItem $stateRoot -Directory -ErrorAction SilentlyContinue | Select-Object -First 80 | ForEach-Object {
        Add-RootCand ("state_" + $_.Name) $_.FullName
    }
}
# 动态：E: 顶层 XINAO_*
if (Test-Path "E:\") {
    Get-ChildItem "E:\" -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'XINAO|AI' } | ForEach-Object {
        Add-RootCand ("E_" + $_.Name) $_.FullName
    }
}

$roots = @($rootCandidates | ForEach-Object {
    $ex = Test-Path -LiteralPath $_.path
    [ordered]@{
        id = $_.id
        path = $_.path
        exists = $ex
        denied = if ($ex) { Test-DeniedPath $_.path } else { $false }
        note_cn = "存在即可感知；denied 仅性能噪声路径"
    }
})

# --- docker ---
$docker = [ordered]@{ daemon_ok = $false; containers = @(); error = $null }
try {
    $ps = docker ps --format "{{.Names}}|{{.Status}}|{{.Ports}}" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $docker.daemon_ok = $true
        $docker.containers = @($ps | Where-Object { $_ } | ForEach-Object {
            $p = "$_" -split '\|', 3
            [ordered]@{ name = $p[0]; status = $p[1]; ports = $p[2] }
        })
    } else { $docker.error = "$ps" }
} catch { $docker.error = "$_" }

# --- ports ---
$ports = [ordered]@{
    temporal_7233 = Test-TcpPort 7233
    litellm_20128 = Test-TcpPort 20128
    searxng_8080  = Test-TcpPort 8080
    ollama_11434  = Test-TcpPort 11434
}

# --- queue ---
$queuePath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
$q = Read-JsonSafe $queuePath
$qStats = [ordered]@{
    path = $queuePath
    exists = [bool]$q
    total = 0; pending = 0; done = 0; blocked = 0; in_progress = 0
    pending_ids = @()
}
if ($q -and $q.tasks) {
    $tasks = @($q.tasks)
    $qStats.total = $tasks.Count
    $qStats.pending = @($tasks | Where-Object { $_.status -eq "pending" }).Count
    $qStats.done = @($tasks | Where-Object { $_.status -eq "done" }).Count
    $qStats.blocked = @($tasks | Where-Object { $_.status -eq "blocked" }).Count
    $qStats.in_progress = @($tasks | Where-Object { $_.status -eq "in_progress" }).Count
    $qStats.pending_ids = @($tasks | Where-Object { $_.status -eq "pending" } | Select-Object -First 15 -ExpandProperty id)
}

# --- evidence pack ---
$evidenceKeys = @(
    "full_gap_scan", "holographic_gap", "weak_strategy_scan", "weak_strategy_policy_scan",
    "scan_stack", "local_capability_registry", "grok_session_context",
    "gap_driven_progressor", "integrated_bus", "roi_self_loop"
)
$evidence = @()
foreach ($k in $evidenceKeys) {
    $p = Join-Path $runtime "state\$k\latest.json"
    $j = Read-JsonSafe $p
    $row = [ordered]@{
        key = $k
        path = $p
        exists = [bool]$j
        age_min = (Get-FileAgeMinutes $p)
    }
    if ($j) {
        if ($j.counts) { $row.counts = $j.counts }
        if ($j.gap_count) { $row.gap_count = $j.gap_count }
        if ($j.goal_cn) { $row.goal_cn = $j.goal_cn }
        if ($j.completion_claim_allowed -ne $null) { $row.completion_claim_allowed = $j.completion_claim_allowed }
        if ($j.user_intent_anchor_cn) { $row.user_intent_anchor_cn = $j.user_intent_anchor_cn }
        if ($j.claim_state) { $row.claim_state = $j.claim_state }
        if ($j.gaps_ranked) { $row.gaps_ranked_n = @($j.gaps_ranked).Count }
        if ($j.findings) { $row.findings_n = @($j.findings).Count }
        if ($j.usable -ne $null) { $row.usable = $j.usable }
        if ($j.counts -and $j.counts.usable -ne $null) { $row.scan_usable = $j.counts.usable }
    }
    $evidence += $row
}

# --- intent anchors (facts about intent files) ---
$intentFiles = @(
    (Join-Path $bridge "grok_p0_autonomous_background_base.v1.json"),
    (Join-Path $bridge "grok_brain_and_executor.v1.json"),
    (Join-Path $runtime "state\grok_session_context\latest.json"),
    (Join-Path $runtime "state\full_gap_scan\latest.json")
)
$intentPresence = @($intentFiles | ForEach-Object {
    [ordered]@{ path = $_; exists = (Test-Path -LiteralPath $_) }
})

$session = Read-JsonSafe (Join-Path $runtime "state\grok_session_context\latest.json")
$fullGap = Read-JsonSafe (Join-Path $runtime "state\full_gap_scan\latest.json")
$policy = Read-JsonSafe (Join-Path $runtime "state\weak_strategy_policy_scan\latest.json")
$scanSt = Read-JsonSafe (Join-Path $runtime "state\scan_stack\latest.json")

$deep = $null
if ($Deep) {
    $psScript = Join-Path $bridge "Invoke-GrokScanStack.ps1"
    if (Test-Path $psScript) {
        try {
            & $psScript -PolicyScan -Quiet 2>$null | Out-Null
            $policy = Read-JsonSafe (Join-Path $runtime "state\weak_strategy_policy_scan\latest.json")
            $deep = [ordered]@{ policy_scan_ran = $true; findings = $(if ($policy.counts) { $policy.counts.findings_total } else { $null }) }
        } catch {
            $deep = [ordered]@{ policy_scan_ran = $false; error = "$_" }
        }
    }
}

# --- summary signals for gap engine ---
$signals = [ordered]@{
    docker_up           = [bool]$docker.daemon_ok
    temporal_up         = [bool]$ports.temporal_7233
    litellm_up          = [bool]$ports.litellm_20128
    searxng_up          = [bool]$ports.searxng_8080
    queue_pending_low   = ($qStats.pending -lt 3)
    queue_pending       = $qStats.pending
    full_gap_exists     = [bool]$fullGap
    p0_honest_open      = $true  # always until closed by evidence
    scan_stack_usable   = if ($scanSt.counts) { $scanSt.counts.usable } else { 0 }
    policy_findings     = if ($policy.counts) { $policy.counts.findings_total } else { 0 }
    session_age_min     = (Get-FileAgeMinutes (Join-Path $runtime "state\grok_session_context\latest.json"))
    full_gap_age_min    = (Get-FileAgeMinutes (Join-Path $runtime "state\full_gap_scan\latest.json"))
    container_names     = @($docker.containers | ForEach-Object { $_.name })
    has_houtai_gongren  = [bool](@($docker.containers | Where-Object { $_.name -match "houtai|gongren|worker" }).Count)
    has_naijiu_shiwu    = [bool](@($docker.containers | Where-Object { $_.name -match "naijiu|temporal|shiwu" }).Count)
}

$snap = [ordered]@{
    schema_version = "xinao.local_state_sense.v1"
    sentinel       = "SENTINEL:LOCAL_STATE_SENSE"
    generated_at   = (Get-Date).ToString("o")
    purpose_cn     = "极致可读本机事实快照 — 供 Gap-Driven Progressor 对照意图"
    auth_shape_cn  = "禁止清单制 deny_list_not_allow_list：默认可读尽读，不用白名单收窄"
    deny_list      = $denyList
    roots          = $roots
    roots_policy_cn = "下列 roots 是扫描锚点与动态发现结果，不是「只允许这些」的白名单闭合集；扩域只加锚，不改成 allow-only"
    docker         = $docker
    ports          = $ports
    task_queue     = $qStats
    evidence       = $evidence
    intent_files   = $intentPresence
    session_brief  = if ($session) {
        [ordered]@{
            user_intent_anchor_cn = $session.user_intent_anchor_cn
            resume = $session.session_resume_brief_cn
            next = $session.next_machine_actions
            last = $session.last_machine_actions
        }
    } else { $null }
    full_gap_brief = if ($fullGap) {
        [ordered]@{
            goal_cn = $fullGap.goal_cn
            gaps_ranked = $fullGap.gaps_ranked
            top3_weld = $fullGap.top3_weld
            completion_claim_allowed = $fullGap.completion_claim_allowed
        }
    } else { $null }
    signals        = $signals
    deep           = $deep
    completion_claim_allowed = $false
}

Write-JsonFile $latestPath $snap
$stamp = Join-Path $stateOut ("sense_{0:yyyyMMdd_HHmmss}.json" -f (Get-Date))
Write-JsonFile $stamp $snap

if (-not $Quiet) {
    Write-Host "state_sense docker=$($signals.docker_up) temporal=$($signals.temporal_up) pending=$($signals.queue_pending) policy_findings=$($signals.policy_findings)"
    Write-Host "evidence: $latestPath"
}

# emit object for pipeline callers
$snap
