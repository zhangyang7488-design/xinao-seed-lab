#Requires -Version 5.1
<#
.SYNOPSIS
  弱智策略全局扫描：对照 grok_default_plus_dynamic_escalate_policy.v1.json
.DESCRIPTION
  先钉死「本扫描的全局=什么」再扫，防止把全局缩成两个 case。
#>
param(
    [string]$ConfigPath = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $ConfigPath
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sRepo = [string]$config.repo_root
if (-not $sRepo) { $sRepo = "E:\XINAO_RESEARCH_WORKSPACES\S" }
$adminRoot = Split-Path $bridge -Parent
$ts = (Get-Date).ToString("o")
$policyPath = Join-Path $bridge "grok_default_plus_dynamic_escalate_policy.v1.json"
$policy = $null
if (Test-Path $policyPath) {
    $policy = Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

$gaps = [System.Collections.Generic.List[object]]::new()
function Add-W {
    param([string]$Id, [string]$Domain, [string]$Sev, [string]$Where, [string]$Problem, [string]$Action, [string]$Against = "")
    $script:gaps.Add([ordered]@{
            id               = "WEAK_STRATEGY_$Id"
            domain           = $Domain
            severity         = $Sev
            where            = $Where
            problem_cn       = $Problem
            against_intent   = $Against
            next_action_cn   = $Action
        })
}

function Test-DockerContainerRunning {
    param([string[]]$NamePatterns)
    $names = @(docker ps --format "{{.Names}}" 2>$null | Where-Object { $_ })
    foreach ($n in $names) {
        foreach ($p in $NamePatterns) {
            if ($n -match $p) { return $true }
        }
    }
    return $false
}

function Test-SearxDefaultInCompose {
    param([string]$ComposeYaml)
    if ($ComposeYaml -notmatch "(?ms)^\s*waiwang-sousuo:\s*\r?\n") { return $false }
    $block = $Matches[0]
    return -not ($block -match "(?m)^\s+profiles:\s*$")
}

function Test-BusRoleRoutingProof {
    param($BusObj)
    if (-not $BusObj) { return $false }
    $r = $BusObj.result
    if (-not $r) { $r = $BusObj }
    $draft = [string]$r.draft_model
    if (-not $draft -and $r.dynamic_loop_shape) { $draft = [string]$r.dynamic_loop_shape.draft_model }
    $review = [string]$r.review_model
    if (-not $review) { $review = [string]$r.pro_review_model }
    if (-not $review -and $r.dynamic_loop_shape) { $review = [string]$r.dynamic_loop_shape.review_model }
    $hasDraft = $draft -match "qwen|dashscope"
    $hasReview = $review -match "deepseek|pro"
    $hasLoopShape = $null -ne $r.dynamic_loop_shape
    if (-not $hasLoopShape -and $BusObj.validation -and $BusObj.validation.checks) {
        $hasLoopShape = $BusObj.validation.checks.dynamic_loop_shape_wired -eq $true
    }
    return ($hasDraft -and $hasReview -and $hasLoopShape)
}

# ========== 全局定义（防止被缩小）==========
$globalScope = [ordered]@{
    schema_version = "xinao.weak_strategy_scan_global_scope.v1"
    definition_cn  = "本扫描的「全局」= 与「默认+动态升级 / 双轨搜索 / 云千问+Pro / 旧文仅语义锚」相关的策略与实现面，不是全磁盘全宇宙"
    included_domains_cn = @(
        "D01_意图合同与反模式自洽",
        "D02_模型路由与云千问/Pro/本地",
        "D03_搜索双轨（后台 tool vs Grok 原生）",
        "D04_派模/并行/轮回策略痕迹",
        "D05_调度 owner（后台图 vs 聊天）",
        "D06_胶水与假绿（PASS/地图/配置有=闭环）",
        "D07_采纳深度（旁路冒充主路）",
        "D08_多仓/双真相/遗留策略",
        "D09_治理环/每波外搜是否被跳过的证据缺口",
        "D10_工具表默认必焊 vs 可选被写死或颠倒"
    )
    included_roots = @(
        $bridge,
        $sRepo,
        $runtime,
        "C:\Users\xx363\Desktop\工具胶水宪法"
    )
    included_artifacts_cn = @(
        "bridge grok_*.v1.json 关键策略合同",
        "S materials/thin_glue_litellm_config.yaml",
        "S services/agent_runtime 路由/worker/bus 默认",
        "S docker-compose 搜索默认热起（waiwang-sousuo 容器 running）",
        "D 盘 state 关键 latest（claim/bus/lane/trigger/governance）",
        "FullGap / holographic 若存在则并入"
    )
    explicitly_NOT_global_cn = @(
        "不是扫描整个 Windows 磁盘 / 所有桌面历史 txt 全文",
        "不是审计所有 S 源码每一行与全部 Temporal history",
        "不是测所有云 API 账单与所有开源仓 mirror",
        "不是重做全息 12 轴每一个子项（那是 FullGap 的职责）",
        "不是把「全局」缩成仅 CASE_MODEL + CASE_SEARCH 两个例子（例子只用于对照，扫描域见 included_domains）",
        "不是宣称扫完=P0 闭合"
    )
    authority_contract = $policyPath
    user_warning_cn    = "若用户说的全局大于本表 included，应扩域或另开扫描；禁止静默缩小还不声明"
}

# ---- D01 policy present ----
if (-not $policy) {
    Add-W "NO_AUTHORITY_CONTRACT" "D01" "P0" $policyPath "缺默认+动态升级权威合同" "补 grok_default_plus_dynamic_escalate_policy.v1.json" "核心意图合同"
} else {
    $core = ($policy.user_intent_core_cn | Out-String)
    if ($core -match "好用.*复刻|保留.*逻辑.*换胶水" -and $core -notmatch "语义锚") {
        Add-W "CONTRACT_STILL_SAYS_REPLAY_OLD" "D01" "P0" $policyPath "合同仍像复刻旧逻辑" "已纠偏则忽略；否则改 user_intent" "旧文=语义锚非复刻"
    }
    if (-not $policy.search_dual_track_cn) {
        Add-W "NO_SEARCH_DUAL_TRACK" "D01" "P0" $policyPath "合同无搜索双轨" "补 search_dual_track_cn" "双轨隔离"
    }
    if (-not $policy.old_as_text_role_cn -and $core -notmatch "语义锚") {
        Add-W "NO_OLD_TEXT_ROLE" "D01" "P1" $policyPath "未钉旧文角色" "补 old_as_text_role_cn" "语义锚"
    }
}

# ---- D02 model routing ----
$litellm = Join-Path $sRepo "materials\thin_glue_litellm_config.yaml"
if (Test-Path $litellm) {
    $ly = Get-Content -LiteralPath $litellm -Raw -Encoding UTF8
    $hasCloudQwen = $ly -match "dashscope"
    $hasLocal = $ly -match "ollama|qwen-local"
    $hasPro = $ly -match "deepseek"
    $autoIsLocal = $false
    if ($ly -match "(?s)model_name:\s*auto.*?model:\s*ollama") { $autoIsLocal = $true }
    if ($ly -match "(?s)model_name:\s*auto.*?model:\s*dashscope") { $autoIsLocal = $false }
    if (-not $hasCloudQwen) {
        Add-W "NO_CLOUD_QWEN_IN_GATEWAY" "D02" "P0" $litellm "网关无 dashscope 云千问" "加云千问路由" "千问=云"
    }
    if ($autoIsLocal) {
        Add-W "AUTO_DEFAULTS_LOCAL_QWEN" "D02" "P0" $litellm "auto 默认落到本地 ollama" "auto→dashscope 云" "禁止本地冒充千问默认"
    }
    if (-not $hasPro) {
        Add-W "NO_PRO_TIER_IN_GATEWAY" "D02" "P0" $litellm "网关无 Pro/deepseek 档" "加 deepseek-v4-pro" "T0 review 档"
    }
    # if only one model path overall
    if ($hasCloudQwen -and -not $hasPro) {
        Add-W "SINGLE_TIER_MODELS" "D02" "P1" $litellm "仅有便宜档无升级档" "补 T1/Pro" "T0+T1"
    }
} else {
    Add-W "LITELLM_CFG_MISSING" "D02" "P0" $litellm "无 LiteLLM 配置" "恢复 thin_glue_litellm_config.yaml" "层A网关"
}

# routing policy file
$rpCandidates = @(
    (Join-Path $runtime "agent_runtime\routing_policy.json"),
    (Join-Path $sRepo "agent_runtime\routing_policy.json"),
    (Join-Path $sRepo "materials\routing_policy.json")
)
$rpHit = $false
foreach ($rp in $rpCandidates) {
    if (Test-Path $rp) {
        $rpHit = $true
        $rtxt = Get-Content -LiteralPath $rp -Raw -Encoding UTF8
        if ($rtxt -match "ollama" -and $rtxt -notmatch "dashscope|qwen-cloud|cloud") {
            Add-W "ROUTING_POLICY_LOCAL_BIAS" "D02" "P0" $rp "routing_policy 偏本地无云千问" "改为云千问 draft" "云千问工人"
        }
        if ($rtxt -notmatch "qwen|dashscope" -and $rtxt -match "deepseek") {
            Add-W "ROUTING_POLICY_NO_QWEN_WORKER" "D02" "P1" $rp "有 deepseek 无千问工人路由" "补云千问 draft 角色" "T0 draft"
        }
    }
}
if (-not $rpHit) {
    Add-W "NO_ROUTING_POLICY_FILE" "D02" "P1" $runtime "未找到 routing_policy.json（角色绑定可能只在代码）" "落盘角色→模型策略或扫代码绑定" "POLICY 层"
}

# bus / instructor path doesn't prove draft=cloud
$lane = Join-Path $runtime "state\codex_s_direct_worker_lane\latest.json"
if (Test-Path $lane) {
    try {
        $lj = Get-Content -LiteralPath $lane -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($lj.not_333_mainline -eq $true) {
            Add-W "WORKER_LANE_NOT_MAINLINE_AS_DEFAULT" "D07" "P0" $lane "worker lane 烟测标 not_333_mainline，若当默认工人=弱智" "波内默认 draft 绑云千问 L4" "旁路冒充主路"
        }
    } catch { }
}

# ---- D03 search dual track ----
$compose = Join-Path $sRepo "docker-compose.yml"
if (Test-Path $compose) {
    $cy = Get-Content -LiteralPath $compose -Raw -Encoding UTF8
    $hasSearx = $cy -match "searxng|waiwang-sousuo"
    $searxDefaultInCompose = Test-SearxDefaultInCompose -ComposeYaml $cy
    if (-not $hasSearx) {
        Add-W "NO_SEARXNG_IN_COMPOSE" "D03" "P0" $compose "compose 无 SearXNG/T0 搜索" "加 waiwang-sousuo" "搜索 T0"
    } elseif (-not (Test-DockerContainerRunning -NamePatterns @("waiwang-sousuo", "searxng"))) {
        if ($searxDefaultInCompose) {
            Add-W "SEARXNG_NOT_RUNNING_DEFAULT" "D03" "P1" "docker" "waiwang-sousuo 已在 compose 默认定义但容器未运行" "docker compose up -d waiwang-sousuo 或 Start-XinaoBaseCompose" "T0 默认主路"
        } else {
            Add-W "SEARXNG_NOT_RUNNING_DEFAULT" "D03" "P1" "docker" "SearXNG 在 compose profile 可选但未运行" "默认波需 search 时 up --profile search 或改默认必起" "T0 默认主路"
        }
    }
}
# scripts that force grok as backend search or backend for grok (dual-track: Grok WebSearch ≠ 后台 SearXNG/Exa)
$bridgeScripts = Get-ChildItem $bridge -Filter "*.ps1" -File -ErrorAction SilentlyContinue
$scriptScanExclude = @("Invoke-GrokWeakStrategyScan.ps1")
foreach ($sc in $bridgeScripts) {
    if ($scriptScanExclude -contains $sc.Name) { continue }
    $t = Get-Content -LiteralPath $sc.FullName -Raw -ErrorAction SilentlyContinue
    if (-not $t) { continue }
    # skip detectors / policy contracts that document the anti-pattern, not enact it
    if ($t -match "WEAK_STRATEGY_SCRIPT_GROK|search_dual_track|双轨.*WebSearch|禁止.*WebSearch.*后台|Add-W\s+[`"']SCRIPT_GROK") { continue }
    if ($t -match "WebSearch" -and $t -match "integrated_bus|task_entry|Activity" -and $t -match "主搜|唯一搜") {
        Add-W "SCRIPT_GROK_SEARCH_AS_BACKEND" "D03" "P1" $sc.Name "脚本可能把 Grok 搜当后台" "改后台 SearXNG/Exa tool" "双轨"
    }
}
# Exa mention without secondary role
$exaInS = Select-String -Path (Join-Path $sRepo "services\agent_runtime\*.py") -Pattern "exa|Exa" -ErrorAction SilentlyContinue | Select-Object -First 5
$xngTool = Select-String -Path (Join-Path $sRepo "services\agent_runtime\*.py") -Pattern "searxng|SearXNG|waiwang" -ErrorAction SilentlyContinue | Select-Object -First 5
if (-not $xngTool -and -not $exaInS) {
    Add-W "NO_SEARCH_TOOL_IN_AGENT_RUNTIME" "D03" "P0" "$sRepo\services\agent_runtime" "agent_runtime 未见 SearXNG/Exa tool 挂点" "波内 search_web tool：T0 XNG T1 Exa" "后台 tool 搜"
} elseif ($exaInS -and -not $xngTool) {
    Add-W "EXA_WITHOUT_XNG_DEFAULT" "D03" "P1" "$sRepo\services\agent_runtime" "有 Exa 痕迹无 XNG 默认" "T0=XNG T1=Exa" "默认+升级"
}

# ---- D04 parallel / loop ----
# handroll while sleep in hot path scripts
$handroll = Select-String -Path (Join-Path $sRepo "services\agent_runtime\*.py") -Pattern "while True:|time\.sleep\(" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -notmatch "test_|_retired" } | Select-Object -First 15
foreach ($h in $handroll) {
    if ($h.Line -match "sleep" -and $h.Path -match "worker|loop|supervisor|orchestr") {
        Add-W "HANDROLL_SLEEP_LOOP" "D04" "P1" "$($h.Path):$($h.LineNumber)" "疑似手搓 sleep 轮询" "改 Temporal wait/signal" "旧实现勿复刻"
    }
}

# ---- D05 owner ----
$dynRoi = Join-Path $bridge "Invoke-GrokDynamicRoiFromIntent.ps1"
if (Test-Path $dynRoi) {
    # ok exists
} else {
    Add-W "NO_DYNAMIC_ROI_ENTRY" "D05" "P2" $bridge "无 DynamicRoi 入口（岛侧）" "可选补" "调度入口"
}

# trigger state
$trig = Join-Path $runtime "state\default_main_loop_trigger_candidate\latest.json"
if (Test-Path $trig) {
    try {
        $tj = Get-Content -LiteralPath $trig -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($tj.runtime_enforced -ne $true) {
            Add-W "MAIN_LOOP_NOT_RUNTIME_ENFORCED" "D05" "P0" $trig "主循环未 runtime_enforced" "焊 trigger 到 integrated_bus 热路径" "后台 owner"
        }
        if ($tj.mainline_default_hot_path -ne $true -and $tj.PSObject.Properties.Name -contains "mainline_default_hot_path") {
            Add-W "MAINLINE_HOT_PATH_FALSE" "D05" "P0" $trig "mainline_default_hot_path 非 true" "打开默认热路径" "T0"
        }
    } catch { }
} else {
    Add-W "NO_MAIN_LOOP_TRIGGER_STATE" "D05" "P1" $trig "无主循环 trigger 状态" "跑 trigger/verify 并绑 bus" "层C轮回"
}

# ---- D06 fake green ----
$busJson = Get-ChildItem (Join-Path $runtime "readback") -Filter "integrated_bus_*.json" -File -EA SilentlyContinue |
    Where-Object { $_.Name -notmatch "promotion|daemon|worker" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($busJson) {
    try {
        $bj = Get-Content -LiteralPath $busJson.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $passed = $bj.validation.passed -eq $true
        $r = $bj.result
        if (-not $r) { $r = $bj }
        if ($passed -and $r.langfuse_callback_wired -eq $false) {
            Add-W "BUS_GREEN_LANGFUSE_OFF" "D06" "P2" $busJson.FullName "bus 绿但 langfuse 未接线（观测缺口）" "可选接 callback" "假绿细项"
        }
        if ($passed -and -not (Test-BusRoleRoutingProof -BusObj $bj)) {
            Add-W "BUS_GREEN_NOT_PROOF_OF_ROLE_ROUTING" "D06" "P1" $busJson.FullName "bus validation 绿但缺 draft_model/review_model/dynamic_loop_shape 角色策略证据" "查 trace/model 字段与图节点绑定" "配置有≠策略闭环"
        }
    } catch { }
}

$hol = Join-Path $runtime "state\holographic_gap\latest.json"
if (Test-Path $hol) {
    try {
        $hj = Get-Content -LiteralPath $hol -Raw -Encoding UTF8 | ConvertFrom-Json
        if (($hj.horizontal_gap_count -eq 0) -and $hj.completion_claim_allowed -eq $true) {
            Add-W "HOLO_GREEN_ALLOWS_CLAIM" "D06" "P0" $hol "全息绿且允许 claim=危险假绿" "强制 completion_claim_allowed=false 直至 P0" "地图绿≠闭合"
        }
    } catch { }
}

# ---- D07 adoption ----
# if only gateway and no graph role bind in integrated_bus_graph for instructor only
$graph = Join-Path $sRepo "services\agent_runtime\integrated_bus_graph.py"
if (Test-Path $graph) {
    $gt = Get-Content -LiteralPath $graph -Raw -Encoding UTF8
    $hasInstructor = $gt -match "instructor|run_instructor"
    $hasExplicitQwenDraft = $gt -match "qwen-cloud|dashscope|draft.*qwen"
    $hasExplicitProReview = $gt -match "deepseek-v4-pro|review.*deepseek|run_.*review"
    if ($hasInstructor -and -not $hasExplicitQwenDraft) {
        Add-W "GRAPH_NO_EXPLICIT_CLOUD_QWEN_DRAFT_NODE" "D07" "P0" $graph "图内无显式云千问 draft 角色绑定（易假默认）" "节点级 model=云千问" "角色 T0"
    }
    if (-not $hasExplicitProReview) {
        Add-W "GRAPH_NO_EXPLICIT_PRO_REVIEW_NODE" "D07" "P0" $graph "图内无显式 Pro review 节点绑定" "review 节点绑 deepseek-v4-pro" "T0 review"
    }
}

# ---- D08 multi-repo ----
$islandBridge = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace-grok-4.5-island\grok-admin-bridge"
if (Test-Path $islandBridge) {
    $n = @(Get-ChildItem $islandBridge -File -EA SilentlyContinue).Count
    if ($n -gt 5) {
        Add-W "ISLAND_DUAL_BRIDGE" "D08" "P1" $islandBridge "4.5 双 bridge 副本" "权威仅 Admin" "双真相"
    }
}
try {
    $url = git -C $adminRoot remote get-url origin 2>$null
    if ($url -match "xinao-seed-lab") {
        Add-W "ADMIN_ORIGIN_S_COLLISION" "D08" "P0" $adminRoot "Admin origin 指向 S 仓名" "改/删 origin 防误 push" "多仓策略"
    }
} catch { }

# ---- D09 governance / every-wave external search ----
$gov = Join-Path $runtime "state\grok_governance\latest.json"
if (-not (Test-Path $gov)) {
    Add-W "NO_GOVERNANCE_EVIDENCE" "D09" "P1" $gov "无治理环落盘证据（每波外搜可能被跳过）" "平台变更先 RecordStep；每波外搜写 evidence" "每波治理环外搜"
} else {
    try {
        $gj = Get-Content -LiteralPath $gov -Raw -Encoding UTF8 | ConvertFrom-Json
        # stale if older than 7 days
        if ($gj.generated_at) {
            $dt = [datetimeoffset]::Parse($gj.generated_at)
            if (((Get-Date) - $dt.LocalDateTime).TotalDays -gt 7) {
                Add-W "GOVERNANCE_EVIDENCE_STALE" "D09" "P2" $gov "治理环证据过旧" "本波补外搜+落盘" "每波"
            }
        }
    } catch { }
}

# intent: re-search mature not replay - check if scripts say 复现旧逻辑（排除本扫描脚本自匹配）
$badReplay = Select-String -Path (Join-Path $bridge "*.ps1") -Pattern "复现旧|按旧逻辑|手搓并行" -ErrorAction SilentlyContinue |
    Where-Object { $_.Filename -ne "Invoke-GrokWeakStrategyScan.ps1" } | Select-Object -First 5
foreach ($b in $badReplay) {
    Add-W "SCRIPT_REPLAY_OLD_LOGIC" "D09" "P1" "$($b.Filename):$($b.LineNumber)" "脚本措辞像复现旧逻辑" "改为外搜成熟选型" "语义锚非复刻"
}

# ---- D10 tool table optional vs default ----
# searx profile-only already covered; ollama as default auto covered

# integrated_bus hot gate — suppress stale TASK_PACKAGE_333 P0 when bus validation already green
$integratedBusHot = $false
$busV2Path = Join-Path $runtime "state\integrated_bus_v2\latest.json"
if (Test-Path -LiteralPath $busV2Path) {
    try {
        $bv = Get-Content -LiteralPath $busV2Path -Raw -Encoding UTF8 | ConvertFrom-Json
        $mode = [string]$bv.invoke_mode
        $checks = $bv.validation.checks
        $workerOk = $checks.L3_qwen_draft_worker_lane -eq $true
        $proOk = $checks.L3_pro_review_after_draft -eq $true
        if ($bv.validation.passed -eq $true -and $mode -match "temporal" -and $workerOk -and $proOk) {
            $integratedBusHot = $true
        }
    } catch { }
}

# merge full gap P0 if any
$fg = Join-Path $runtime "state\full_gap_scan\latest.json"
if (Test-Path $fg) {
    try {
        $fj = Get-Content -LiteralPath $fg -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($g in @($fj.gaps_ranked | Where-Object { $_.priority -eq "P0" })) {
            $id = [string]$g.id
            if (-not $id -or $id -match "^WEAK_STRATEGY_") { continue }
            if ($integratedBusHot -and $id -match "TASK_PACKAGE_333|333_SHAPE_NOT_HOT") { continue }
            Add-W "FROM_FULLGAP_$id" "D06" "P0" "full_gap_scan" ([string]$g.detail_cn) ([string]$g.action_cn) "并入全量扫P0"
        }
    } catch { }
}

# sort
$order = @{ P0 = 0; P1 = 1; P2 = 2 }
$sorted = @($gaps | Sort-Object { $order[[string]$_.severity] }, { [string]$_.id })
$byDomain = @{}
foreach ($g in $sorted) {
    $d = [string]$g.domain
    if (-not $byDomain.ContainsKey($d)) { $byDomain[$d] = 0 }
    $byDomain[$d]++
}

$top5 = @($sorted | Select-Object -First 5)

$outDir = Join-Path $runtime "state\weak_strategy_scan"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$report = [ordered]@{
    schema_version             = "xinao.weak_strategy_scan.v1"
    sentinel                   = "SENTINEL:WEAK_STRATEGY_SCAN"
    generated_at               = $ts
    completion_claim_allowed   = $false
    global_scope               = $globalScope
    authority_contract         = $policyPath
    gap_count                  = $sorted.Count
    counts                     = @{
        P0 = @($sorted | Where-Object { $_.severity -eq "P0" }).Count
        P1 = @($sorted | Where-Object { $_.severity -eq "P1" }).Count
        P2 = @($sorted | Where-Object { $_.severity -eq "P2" }).Count
    }
    gaps_by_domain             = $byDomain
    gaps                       = $sorted
    top5_fix_now               = $top5
    honesty_cn                 = "本全局=上表 D01-D10 + 所列 roots；不是无限宇宙。若要更大全局须扩 included 并再扫。"
}

$latest = Join-Path $outDir "latest.json"
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latest -Encoding UTF8

$zhDir = Join-Path $runtime "readback\zh"
New-Item -ItemType Directory -Force -Path $zhDir | Out-Null
$zh = @(
    "# 弱智策略扫描（全局范围已声明）",
    "",
    "- 时间: $ts",
    "- 缺口数: $($sorted.Count)（P0=$($report.counts.P0) P1=$($report.counts.P1) P2=$($report.counts.P2)）",
    "- completion_claim_allowed: false",
    "",
    "## 本扫描「全局」=什么",
    ""
)
foreach ($x in $globalScope.included_domains_cn) { $zh += "- $x" }
$zh += ""
$zh += "## 明确不是全局"
foreach ($x in $globalScope.explicitly_NOT_global_cn) { $zh += "- $x" }
$zh += ""
$zh += "## Top5"
$i = 1
foreach ($t in $top5) {
    $zh += "$i. **$($t.id)** [$($t.severity)/$($t.domain)] $($t.problem_cn)"
    $zh += "   - 动作: $($t.next_action_cn)"
    $i++
}
$zh += ""
$zh += "## 全部"
foreach ($g in $sorted) {
    $zh += "- [$($g.severity)][$($g.domain)] **$($g.id)**: $($g.problem_cn)"
}
$zhPath = Join-Path $zhDir "weak_strategy_scan_latest.md"
$zh -join "`n" | Set-Content -LiteralPath $zhPath -Encoding UTF8

if (-not $Quiet) { $report | ConvertTo-Json -Depth 8 }
exit 0
