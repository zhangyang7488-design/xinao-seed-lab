#Requires -Version 5.1
<#
.SYNOPSIS
  Gap-Driven Progressor：Intent vs Current Reality → 合成任务 → 推队列 / Interject。
  不执行重型技术活本体；产出可 invoke 任务项。
  授权：禁止清单制（非白名单）— 默认可从任意可读事实发现任务；只禁 deny_list 真 gate。
.EXAMPLE
  .\Invoke-GrokGapDrivenProgressor.ps1
  .\Invoke-GrokGapDrivenProgressor.ps1 -DeepSense -PushQueue
  .\Invoke-GrokGapDrivenProgressor.ps1 -Status
#>
param(
    [switch]$DeepSense,
    [switch]$PushQueue,
    [switch]$NoPush,
    [switch]$Status,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\gap_driven_progressor"
$latestPath = Join-Path $outDir "latest.json"
$queuePath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
$interjectPath = Join-Path $runtime "readback\zh\gap_driven_interject_latest.md"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $interjectPath) | Out-Null

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 20), $utf8)
}

function Read-JsonSafe([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}

if ($Status) {
    $j = Read-JsonSafe $latestPath
    if (-not $Quiet) {
        if ($j) {
            Write-Host "GDP gaps=$($j.counts.gaps) tasks_synth=$($j.counts.tasks_synthesized) pushed=$($j.pushed_to_queue)"
            Write-Host "evidence: $latestPath"
        } else { Write-Host "no GDP latest yet" }
    }
    return $j
}

# default push unless NoPush
if (-not $NoPush) { $PushQueue = $true }

# 1) State sense
$senseScript = Join-Path $bridge "Get-GrokLocalStateSense.ps1"
$senseArgs = @{}
if ($DeepSense) { $senseArgs.Deep = $true }
$senseArgs.Quiet = $true
$sense = & $senseScript @senseArgs
if (-not $sense) { throw "state sense failed" }

# 2) Load intent
$p0 = Read-JsonSafe (Join-Path $bridge "grok_p0_autonomous_background_base.v1.json")
$session = Read-JsonSafe (Join-Path $runtime "state\grok_session_context\latest.json")
$fullGap = Read-JsonSafe (Join-Path $runtime "state\full_gap_scan\latest.json")
$weak = Read-JsonSafe (Join-Path $runtime "state\weak_strategy_scan\latest.json")
$policy = Read-JsonSafe (Join-Path $runtime "state\weak_strategy_policy_scan\latest.json")

$globalIntent = [ordered]@{
    north_star_cn = if ($p0) { $p0.north_star_cn } else { "P0 后台全自动底座" }
    global_is_cn  = if ($p0.global_definition_cn) { $p0.global_definition_cn.what_global_is } else { $null }
    global_not_cn = if ($p0.global_definition_cn) { $p0.global_definition_cn.what_global_is_not } else { @() }
    session_anchor_cn = if ($session) { $session.user_intent_anchor_cn } else { $null }
    full_gap_goal_cn  = if ($fullGap) { $fullGap.goal_cn } else { $null }
    isomorphic_goals  = if ($p0.p0_goals_isomorphic_to_grok_cn) { $p0.p0_goals_isomorphic_to_grok_cn.goals } else { @("自治","自修复","自进化","全局自洽","最大能力界面") }
    always = @(
        "意图-现实差距驱动推进，禁止只等用户点名任务",
        "completion_claim_allowed=false 直至 P0 真闭合",
        "非安全扫描目标；策略/结构/合同/发现",
        "成熟优先：外搜成熟思维/组件再焊",
        "禁止清单制：默认可感知/可生成任务；禁止白名单收窄能力面"
    )
    auth_shape = "deny_list_not_allow_list"
}

# 3) Gap analysis (deterministic synthesizer)
$gaps = [System.Collections.Generic.List[object]]::new()
$tasks = [System.Collections.Generic.List[object]]::new()
$sig = $sense.signals
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$pri = 500

function Add-GapTask {
    param(
        [string]$GapId,
        [string]$Severity,
        [string]$Domain,
        [string]$ProblemCn,
        [string]$IntentRef,
        [string]$TitleCn,
        [string]$Invoke,
        [int]$Priority
    )
    $gaps.Add([ordered]@{
        id = $GapId
        severity = $Severity
        domain = $Domain
        problem_cn = $ProblemCn
        intent_ref = $IntentRef
        reality_signal = $true
    }) | Out-Null
    $tasks.Add([ordered]@{
        id = "GDP_${stamp}_$($tasks.Count + 1)_$GapId"
        source_gap_id = $GapId
        source = "gap_driven_progressor"
        wave = "GDP"
        priority = $Priority
        status = "pending"
        title_cn = $TitleCn
        invoke = $Invoke
        domain = $Domain
        severity = $Severity
    }) | Out-Null
}

# --- from full_gap_scan ---
if ($fullGap -and $fullGap.gaps_ranked) {
    foreach ($g in @($fullGap.gaps_ranked)) {
        $gid = [string]$g.id
        if ([string]::IsNullOrWhiteSpace($gid)) { continue }
        $inv = if ($g.action_cn -match "GapScan|holographic") { "Invoke-GrokHolographicGapScan.ps1" }
            elseif ($g.id -match "TASK_PACKAGE|333|bus") { "Invoke-GrokScanStack.ps1 -PolicyScan" }
            elseif ($g.id -match "P0_NOT_CLOSED") { "Invoke-GrokGapDrivenProgressor.ps1 -DeepSense" }
            else { "Invoke-GrokHolographicGapScan.ps1" }
        # better invoke map
        if ($gid -eq "TASK_PACKAGE_333_SHAPE_NOT_HOT") {
            $inv = "Invoke-GrokTaskPackage333ShapeHotPath.ps1 -AllowEphemeralWorker -RescanGap"
        }
        if ($gid -eq "P0_NOT_CLOSED_HONEST") {
            $inv = "Invoke-GrokLongWorkflowBootstrap.ps1"
        }
        Add-GapTask -GapId $gid -Severity $(if ($g.priority) { $g.priority } else { "P1" }) `
            -Domain "full_gap" -ProblemCn $(if ($g.detail_cn) { $g.detail_cn } else { $g.id }) `
            -IntentRef "full_gap_scan.gaps_ranked" `
            -TitleCn "[GDP] $($g.action_cn)" -Invoke $inv -Priority ($pri++)
    }
} else {
    Add-GapTask -GapId "FULL_GAP_STALE_OR_MISSING" -Severity "P0" -Domain "sense" `
        -ProblemCn "full_gap_scan/latest 缺失或无 gaps — 意图-现实主尺断裂" `
        -IntentRef "global Intent ruler" `
        -TitleCn "[GDP] 重跑全息/全量差距扫" `
        -Invoke "Invoke-GrokHolographicGapScan.ps1" -Priority ($pri++)
}

# --- infrastructure reality ---
if (-not $sig.docker_up) {
    Add-GapTask -GapId "DOCKER_DOWN" -Severity "P0" -Domain "infra" `
        -ProblemCn "Docker daemon 不可用 — 后台底座热路无法跑" `
        -IntentRef "P0 后台可 invoke" `
        -TitleCn "[GDP] 恢复 Docker daemon" `
        -Invoke "docker info" -Priority ($pri++)
}
if (-not $sig.temporal_up) {
    Add-GapTask -GapId "TEMPORAL_7233_DOWN" -Severity "P0" -Domain "infra" `
        -ProblemCn "Temporal :7233 未监听 — 耐久主路断" `
        -IntentRef "Temporal 耐久脊柱" `
        -TitleCn "[GDP] 拉起 XINAO Base compose / Temporal" `
        -Invoke "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Start-XinaoBaseCompose.ps1" -Priority ($pri++)
}
if (-not $sig.litellm_up) {
    Add-GapTask -GapId "LITELLM_DOWN" -Severity "P1" -Domain "infra" `
        -ProblemCn "LiteLLM :20128 未起 — 云千问/Pro 网关断" `
        -IntentRef "派模 A/B/C 网关" `
        -TitleCn "[GDP] 探活/启动 thin-glue LiteLLM" `
        -Invoke "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Start-XinaoThinGlueStack.ps1" -Priority ($pri++)
}
if (-not $sig.searxng_up) {
    Add-GapTask -GapId "SEARXNG_NOT_DEFAULT_UP" -Severity "P1" -Domain "search_dual_track" `
        -ProblemCn "SearXNG 未在 :8080 — 后台 T0 搜默认面弱" `
        -IntentRef "搜索双轨 后台=XNG" `
        -TitleCn "[GDP] 默认波需要时 up profile search / 探 SearXNG" `
        -Invoke "docker ps; Invoke-GrokScanStack.ps1 -PolicyScan" -Priority ($pri++)
}

# --- scan stack / policy ---
if (-not $sig.scan_stack_usable -or $sig.scan_stack_usable -lt 20) {
    Add-GapTask -GapId "SCAN_STACK_WEAK" -Severity "P1" -Domain "capability" `
        -ProblemCn "scan-stack 可用引擎不足" `
        -IntentRef "最大能力界面" `
        -TitleCn "[GDP] 刷新 scan-stack Status" `
        -Invoke "Invoke-GrokScanStack.ps1 -Status" -Priority ($pri++)
}
if ($sig.policy_findings -gt 0) {
    Add-GapTask -GapId "WEAK_STRATEGY_POLICY_HITS" -Severity "P1" -Domain "weak_strategy" `
        -ProblemCn "PolicyScan 仍有 $($sig.policy_findings) 条弱策略命中（如 time.sleep 轮询）" `
        -IntentRef "弱智策略→规则收敛" `
        -TitleCn "[GDP] 处理 PolicyScan Top 命中（sleep 轮询等）" `
        -Invoke "Invoke-GrokScanStack.ps1 -PolicyScan" -Priority ($pri++)
} else {
    # ensure policy scan at least once recently
    $polAge = $null
    $polEv = @($sense.evidence | Where-Object { $_.key -eq "weak_strategy_policy_scan" } | Select-Object -First 1)
    if ($polEv -and $polEv.age_min -ne $null -and $polEv.age_min -gt 180) {
        Add-GapTask -GapId "POLICY_SCAN_STALE" -Severity "P2" -Domain "weak_strategy" `
            -ProblemCn "PolicyScan 证据过旧 ($($polEv.age_min) min)" `
            -IntentRef "持续差距扫描" `
            -TitleCn "[GDP] 刷新 PolicyScan" `
            -Invoke "Invoke-GrokScanStack.ps1 -PolicyScan" -Priority ($pri++)
    }
}

# --- queue starvation ---
if ($sig.queue_pending_low) {
    Add-GapTask -GapId "QUEUE_STARVATION" -Severity "P0" -Domain "progress" `
        -ProblemCn "pending 任务仅 $($sig.queue_pending) — 主窗易停（任务来源枯竭）" `
        -IntentRef "差距驱动持续推进" `
        -TitleCn "[GDP] 差距合成补位（本任务自身）+ RunNext" `
        -Invoke "Invoke-GrokLongWorkflowRunNext.ps1" -Priority ($pri++)
}

# --- session / dialogue trap ---
if ($session -and ($session.user_intent_anchor_cn -match "对话|dialogue|默认不接管")) {
    Add-GapTask -GapId "DIALOGUE_ONLY_STALL_RISK" -Severity "P1" -Domain "execution_mode" `
        -ProblemCn "会话锚偏 dialogue — 全局推进意图时需切 bounded/autonomous 或 GDP 强制补位" `
        -IntentRef "三档执行 + 伪权限" `
        -TitleCn "[GDP] 检查点改为可推进锚 + 再 GDP" `
        -Invoke "Invoke-GrokSessionContextCheckpoint.ps1 -Save" -Priority ($pri++)
}

# --- weak strategy gaps ---
if ($weak -and $weak.gaps) {
    foreach ($wg in @($weak.gaps | Select-Object -First 8)) {
        if ($wg.id -match "SCRIPT_REPLAY") { continue } # skip known false-pos noise bulk
        $already = @($gaps | Where-Object { $_.id -eq $wg.id }).Count -gt 0
        if ($already) { continue }
        Add-GapTask -GapId $wg.id -Severity $(if ($wg.severity) { $wg.severity } else { "P1" }) `
            -Domain $(if ($wg.domain) { $wg.domain } else { "weak" }) `
            -ProblemCn $wg.problem_cn -IntentRef "weak_strategy_scan" `
            -TitleCn "[GDP] $($wg.next_action_cn)" `
            -Invoke "Invoke-GrokScanStack.ps1 -PolicyScan" -Priority ($pri++)
    }
}

# --- always-on honesty ---
Add-GapTask -GapId "P0_HONEST_NO_CLAIM" -Severity "P0" -Domain "meta" `
    -ProblemCn "P0 完整自洽/自修复/自进化仍建设期 — 禁止宣布用户完成" `
    -IntentRef "completion_claim_allowed=false" `
    -TitleCn "[GDP] 刷新 now_can_do 诚实透镜（不宣称闭合）" `
    -Invoke "Invoke-GrokLongWorkflowBootstrap.ps1" -Priority 999

# 4) Classify done vs open (light)
$classified = [ordered]@{
    done_signals_cn = @(
        $(if ($sig.docker_up) { "Docker daemon 可达" } else { $null }),
        $(if ($sig.scan_stack_usable -ge 20) { "scan-stack $($sig.scan_stack_usable) 引擎可用" } else { $null }),
        $(if ($fullGap) { "full_gap_scan 有盘" } else { $null })
    ) | Where-Object { $_ }
    in_progress_cn = @(
        $(if ($sig.queue_pending -gt 0) { "队列 pending=$($sig.queue_pending)" } else { $null }),
        $(if ($sig.temporal_up) { "Temporal:7233 监听中" } else { $null })
    ) | Where-Object { $_ }
    open_gaps = @($gaps)
    implied_todos_cn = @($tasks | ForEach-Object { $_.title_cn })
}

# 5) Push queue (dedupe by source_gap_id among pending)
$pushed = @()
$skipped = @()
if ($PushQueue) {
    $q = Read-JsonSafe $queuePath
    if (-not $q) {
        $q = [ordered]@{
            schema_version = "xinao.grok_long_workflow_task_queue.v1"
            updated_at = (Get-Date).ToString("o")
            execution_mode = "gap_driven"
            tasks = @()
        }
    }
    $existingPendingGaps = @{}
    foreach ($t in @($q.tasks)) {
        if ($t.status -eq "pending" -and $t.source_gap_id) {
            $existingPendingGaps[[string]$t.source_gap_id] = $true
        }
        if ($t.status -eq "pending" -and $t.id -match '^GDP_') {
            # also mark by gap suffix
            if ($t.source_gap_id) { $existingPendingGaps[[string]$t.source_gap_id] = $true }
        }
    }
    $newList = [System.Collections.Generic.List[object]]::new()
    foreach ($t in @($q.tasks)) { [void]$newList.Add($t) }
    foreach ($t in $tasks) {
        $sg = [string]$t.source_gap_id
        if ($existingPendingGaps.ContainsKey($sg)) {
            $skipped += $sg
            continue
        }
        # skip pure meta honesty spam if already many GDP pending
        if ($sg -eq "P0_HONEST_NO_CLAIM" -and $sig.queue_pending -gt 2) {
            $skipped += $sg
            continue
        }
        [void]$newList.Add([pscustomobject]$t)
        $pushed += $t.id
        $existingPendingGaps[$sg] = $true
    }
    $qObj = [ordered]@{
        schema_version = if ($q.schema_version) { $q.schema_version } else { "xinao.grok_long_workflow_task_queue.v1" }
        updated_at = (Get-Date).ToString("o")
        execution_mode = "gap_driven_progressor"
        scope_cn = "GDP 自动补位：意图-现实差距合成任务"
        tasks = $newList.ToArray()
    }
    Write-JsonFile $queuePath $qObj
}

# 6) Interject markdown
$interject = @"
# Gap-Driven Progressor Interject

**时间：** $($(Get-Date).ToString('o'))

## 全局意图（持有）
- 北极星：$(($globalIntent.north_star_cn))
- 会话锚：$(($globalIntent.session_anchor_cn))
- FullGap 目标：$(($globalIntent.full_gap_goal_cn))

## 当前现实（摘要）
- Docker=$($sig.docker_up) Temporal=$($sig.temporal_up) LiteLLM=$($sig.litellm_up) SearXNG=$($sig.searxng_up)
- 队列 pending=$($sig.queue_pending) PolicyScan findings=$($sig.policy_findings) scan-stack usable=$($sig.scan_stack_usable)

## 意图 vs 现实 — 开放差距 ($($gaps.Count))
$($gaps | ForEach-Object { "- **$($_.severity)** ``$($_.id)``: $($_.problem_cn)" } | Out-String)

## 已合成任务（推入队列: $($PushQueue)）
$($tasks | Select-Object -First 20 | ForEach-Object { "- ``$($_.id)`` $($_.title_cn) → ``$($_.invoke)``" } | Out-String)

## 强制推进
检测到意图与当前现实存在差距；已生成任务并$($(if ($PushQueue) { '推入 task_queue' } else { '仅落盘未推队列' }))。
请执行：``Invoke-GrokLongWorkflowRunNext.ps1`` 或继续 GDP 循环。

completion_claim_allowed=false
"@
[System.IO.File]::WriteAllText($interjectPath, $interject, $utf8)

$result = [ordered]@{
    schema_version = "xinao.gap_driven_progressor.v1"
    sentinel       = "SENTINEL:GAP_DRIVEN_PROGRESSOR"
    generated_at   = (Get-Date).ToString("o")
    global_intent  = $globalIntent
    state_sense_ref = (Join-Path $runtime "state\local_state_sense\latest.json")
    signals        = $sig
    classified     = $classified
    gaps           = @($gaps)
    tasks_synthesized = @($tasks)
    pushed_to_queue = $PushQueue
    pushed_task_ids = $pushed
    skipped_dedupe  = $skipped
    queue_ref      = $queuePath
    interject_ref  = $interjectPath
    counts         = [ordered]@{
        gaps = $gaps.Count
        tasks_synthesized = $tasks.Count
        pushed = $pushed.Count
        skipped = $skipped.Count
    }
    now_can_do_cn  = @(
        "读 Interject: $interjectPath",
        "Invoke-GrokLongWorkflowRunNext.ps1",
        "Invoke-GrokLoopGuardian.ps1",
        "Invoke-GrokGapDrivenProgressor.ps1 -DeepSense"
    )
    completion_claim_allowed = $false
}

Write-JsonFile $latestPath $result
$stamped = Join-Path $outDir ("gdp_{0}.json" -f $stamp)
Write-JsonFile $stamped $result

if (-not $Quiet) {
    Write-Host "GDP gaps=$($gaps.Count) tasks=$($tasks.Count) pushed=$($pushed.Count) skipped_dedupe=$($skipped.Count)"
    Write-Host "interject: $interjectPath"
    Write-Host "evidence: $latestPath"
}

$result
