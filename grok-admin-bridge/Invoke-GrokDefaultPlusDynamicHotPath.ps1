#Requires -Version 5.1
<#
.SYNOPSIS
  默认+动态升级 · 三桌面实施源热路径检查与最小焊证据。
.DESCRIPTION
  对照：
    - 合同指针（默认+动态升级）
    - 后台免费本地搜索（SearXNG/rg/DDGS）
    - 外部成熟动态轮回+智能派模形状
  可选链式：WeakStrategyScan / ScanStack -PolicyScan / L4 search 烟测。
.EXAMPLE
  .\Invoke-GrokDefaultPlusDynamicHotPath.ps1
  .\Invoke-GrokDefaultPlusDynamicHotPath.ps1 -WithWeakStrategy -WithPolicyScan -ProbeSearch
#>
param(
    [switch]$WithWeakStrategy,
    [switch]$WithPolicyScan,
    [switch]$ProbeSearch,
    [switch]$RecordGovernance,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$bridge = $PSScriptRoot
$configPath = Join-Path $bridge "bridge.config.json"
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $configPath
$config = $null
try {
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch { }
$sRepo = if ($config -and $config.repo_root) { [string]$config.repo_root } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }

$ts = (Get-Date).ToString("o")
$runId = "hotpath_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$outDir = Join-Path $runtime "state\default_plus_dynamic_hotpath"
$latestPath = Join-Path $outDir "latest.json"
$zhPath = Join-Path $runtime "readback\zh\default_plus_dynamic_hotpath_latest.md"
New-Item -ItemType Directory -Force -Path $outDir, (Split-Path $zhPath) | Out-Null

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 20), $utf8)
}

function Read-JsonSafe([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}

function Test-TcpOpen([int]$Port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $iar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(1200, $false)
        if ($ok) { $c.EndConnect($iar); $c.Close(); return $true }
        $c.Close()
    } catch { }
    return $false
}

function Test-DockerNameRunning([string[]]$Patterns) {
    $names = @(docker ps --format "{{.Names}}" 2>$null | Where-Object { $_ })
    foreach ($n in $names) {
        foreach ($p in $Patterns) {
            if ($n -match $p) { return @{ running = $true; name = $n } }
        }
    }
    return @{ running = $false; name = $null }
}

function Invoke-SearxngJsonProbe([string]$BaseUrl) {
    $queries = @("ping", "langgraph supervisor", "searxng metasearch")
    $lastUrl = $null
    foreach ($q in $queries) {
        $enc = [uri]::EscapeDataString($q)
        $url = ("{0}/search?q={1}&format=json" -f $BaseUrl.TrimEnd("/"), $enc)
        $lastUrl = $url
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 12 -Headers @{ "User-Agent" = "XINAO-GrokHotPath/1.0" }
            $parsed = $resp.Content | ConvertFrom-Json
            $count = 0
            if ($parsed.results) { $count = @($parsed.results).Count }
            if ($resp.StatusCode -eq 200 -and $count -gt 0) {
                return [ordered]@{ ok = $true; hit_count = $count; url = $url; query = $q; error = $null }
            }
        } catch {
            return [ordered]@{ ok = $false; hit_count = 0; url = $url; query = $q; error = "$_" }
        }
    }
    return [ordered]@{ ok = $false; hit_count = 0; url = $lastUrl; error = "no_hits_all_queries" }
}

function Invoke-RgSmoke([string]$RepoRoot, [string]$Pattern) {
    $rg = $null
    $scanRg = "E:\XINAO_EXTERNAL_MATURE\scan-stack\bin\rg.exe"
    if (Test-Path -LiteralPath $scanRg) { $rg = $scanRg }
    else {
        $w = Get-Command rg -ErrorAction SilentlyContinue
        if ($w) { $rg = $w.Source }
    }
    if (-not $rg) {
        return [ordered]@{ ok = $false; hit_count = 0; error = "rg_missing" }
    }
    try {
        $hits = & $rg -n --max-count 5 -g "!node_modules" -g "!.venv" -e $Pattern $RepoRoot 2>$null
        $arr = @($hits)
        return [ordered]@{ ok = ($arr.Count -gt 0); hit_count = $arr.Count; rg = $rg; sample = @($arr | Select-Object -First 3) }
    } catch {
        return [ordered]@{ ok = $false; hit_count = 0; error = "$_" }
    }
}

function Get-DynamicLoopShapeProof {
    param($BusObj)
    if (-not $BusObj) { return [ordered]@{ ok = $false; reason = "no_bus" } }
    $r = $BusObj.result
    if (-not $r) { $r = $BusObj }
    $draft = [string]$r.draft_model
    $review = [string]$r.review_model
    if (-not $review) { $review = [string]$r.pro_review_model }
    $shape = $r.dynamic_loop_shape
    if (-not $shape -and $BusObj.validation -and $BusObj.validation.checks) {
        $c = $BusObj.validation.checks
        $shape = [ordered]@{
            draft_model  = if ($c.draft_model_cloud_qwen) { $draft } else { $null }
            review_model = if ($c.L3_pro_review_after_draft) { $review } else { $null }
            parallel_semantic = $r.parallel_semantic
        }
    }
    $hasCloudDraft = ($draft -match "qwen|dashscope") -or ($shape -and [string]$shape.draft_model -match "qwen|dashscope")
    $hasProReview = ($review -match "deepseek|pro") -or ($shape -and [string]$shape.review_model -match "deepseek|pro")
    $rolling = [string]$r.parallel_semantic -match "rolling"
    $temporal = [string]$BusObj.invoke_mode -match "temporal"
    return [ordered]@{
        ok               = ($hasCloudDraft -and $hasProReview)
        draft_model      = $draft
        review_model     = $review
        parallel_semantic = [string]$r.parallel_semantic
        rolling_semantic = $rolling
        temporal_invoke  = $temporal
        mainline_hot     = ($BusObj.mainline_default_hot_path -eq $true)
        dynamic_loop_shape = $shape
    }
}

# --- 三桌面实施源 ---
$desktopSources = @(
    @{
        id   = "SRC_CONTRACT_POINTER"
        path = "C:\Users\xx363\Desktop\合同_默认加动态升级_指针_20260710.txt"
        mirror = Join-Path $bridge "grok_default_plus_dynamic_escalate_policy.v1.json"
    },
    @{
        id   = "SRC_BACKEND_SEARCH"
        path = "C:\Users\xx363\Desktop\后台免费本地搜索_成熟选型与集成_20260710.txt"
        mirror = Join-Path $sRepo "services\agent_runtime\thin_glue_l4_search.py"
    },
    @{
        id   = "SRC_DYNAMIC_LOOP_SHAPE"
        path = "C:\Users\xx363\Desktop\外部成熟_动态轮回与智能派模_完整形状_20260710.txt"
        mirror = Join-Path $runtime "state\integrated_bus_v2\latest.json"
    }
)

$sourceChecks = @()
foreach ($src in $desktopSources) {
    $sourceChecks += [ordered]@{
        id            = $src.id
        desktop_path  = $src.path
        desktop_ok    = (Test-Path -LiteralPath $src.path)
        machine_mirror = $src.mirror
        mirror_ok     = (Test-Path -LiteralPath $src.mirror)
    }
}

# --- 后台搜索热路径 ---
$searxContainer = Test-DockerNameRunning @("waiwang-sousuo", "searxng")
$searxPortOpen = Test-TcpOpen 8888
$searxProbe = if ($searxPortOpen) { Invoke-SearxngJsonProbe "http://127.0.0.1:8888" } else { [ordered]@{ ok = $false; hit_count = 0; error = "port_8888_closed" } }
$rgSmoke = Invoke-RgSmoke $sRepo "default_plus_dynamic_escalate"
$thinGlueSearchPath = Join-Path $runtime "state\thin_glue_search\latest.json"
$thinGlueSearch = Read-JsonSafe $thinGlueSearchPath
$searchAdapterEvidence = @{
    searxng = Join-Path $runtime "state\search\searxng\latest.json"
    ripgrep = Join-Path $runtime "state\search\ripgrep\latest.json"
    ddgs    = Join-Path $runtime "state\search\ddgs\latest.json"
    exa     = Join-Path $runtime "state\search\exa\latest.json"
}
$searchAdapterLatest = @{}
foreach ($kv in $searchAdapterEvidence.GetEnumerator()) {
    $searchAdapterLatest[$kv.Key] = Read-JsonSafe $kv.Value
}

function Get-SearchTierChainProof([object]$ThinGlue) {
    $chain = @("T0_searxng", "T0_ddgs_fallback", "T1_exa_dynamic")
    $ext = $null
    if ($ThinGlue -and $ThinGlue.external_search) { $ext = $ThinGlue.external_search }
    $searx = if ($ext -and $ext.searxng) { $ext.searxng } else { $null }
    $ddgs = if ($ext -and $ext.ddgs) { $ext.ddgs } else { $null }
    $exa = if ($ext -and $ext.exa) { $ext.exa } else { $null }
    if ($ext -and $ext.search_tier_chain) { $chain = @($ext.search_tier_chain) }
    $ddgsWired = ($ddgs -and ($ddgs.wired -eq $true -or $ddgs.skipped -eq $true -or $ddgs.adapter -eq "ddgs"))
    $exaWired = ($exa -and ($exa.wired -eq $true -or $ext.exa_dynamic_optional_tier3 -eq $true))
    return [ordered]@{
        tier_chain         = $chain
        T0_searxng_ok      = ($searxProbe.ok -or ($searx -and $searx.ok -eq $true))
        T0_rg_ok           = $rgSmoke.ok
        T0_ddgs_wired      = [bool]$ddgsWired
        T1_exa_wired       = [bool]$exaWired
        search_tier_used   = if ($ext) { [string]$ext.search_tier_used } else { $null }
        external_adapter   = if ($ext) { [string]$ext.adapter } else { $null }
        escalate_policy    = if ($ext) { [string]$ext.escalate_policy } else { "default_plus_dynamic_escalate.v1" }
        implemented        = ($rgSmoke.ok -and ($searxProbe.ok -or ($ThinGlue -and $ThinGlue.validation.passed -eq $true)) -and $ddgsWired -and $exaWired)
    }
}

$tierChainProof = Get-SearchTierChainProof $thinGlueSearch

$adapterEvidenceOk = ($searchAdapterLatest.searxng -and $searchAdapterLatest.ripgrep)
$searchHotPath = [ordered]@{
    tier_chain_cn     = "T0 SearXNG + rg; T1 Exa 动态; DDGS fallback"
    tier_chain_proof  = $tierChainProof
    waiwang_sousuo    = $searxContainer
    port_8888_open    = $searxPortOpen
    searxng_json_probe = $searxProbe
    ripgrep_smoke     = $rgSmoke
    thin_glue_search_evidence = $thinGlueSearchPath
    thin_glue_search_present  = ($null -ne $thinGlueSearch)
    adapter_evidence_paths    = $searchAdapterEvidence
    adapter_evidence_present  = @{
        searxng = ($null -ne $searchAdapterLatest.searxng)
        ripgrep = ($null -ne $searchAdapterLatest.ripgrep)
        ddgs    = ($null -ne $searchAdapterLatest.ddgs)
        exa     = ($null -ne $searchAdapterLatest.exa)
    }
    adapter_evidence_ok       = [bool]$adapterEvidenceOk
    dual_track_cn     = "后台 tool 搜 ≠ Grok 原生搜；禁止交叉当主路"
    backend_search_ok = ($tierChainProof.implemented -or ($rgSmoke.ok -and ($searxProbe.ok -or $thinGlueSearch.validation.passed -eq $true)))
}

# --- 动态轮回形状证据 ---
$busPath = Join-Path $runtime "state\integrated_bus_v2\latest.json"
$bus = Read-JsonSafe $busPath
$loopShape = Get-DynamicLoopShapeProof $bus
$policyPath = Join-Path $bridge "grok_default_plus_dynamic_escalate_policy.v1.json"
$specPath = Join-Path $runtime "specs\xinao_default_plus_dynamic_escalate_policy_20260710.md"

$modelHotPath = [ordered]@{
    authority_contract = $policyPath
    spec_mirror        = $specPath
    spec_present       = (Test-Path -LiteralPath $specPath)
    integrated_bus_v2  = $busPath
    loop_shape_proof   = $loopShape
    layers_cn          = "C=Temporal durable loop; B=LangGraph 角色编排; A=LiteLLM 云网关"
}

# --- 可选：L4 search 烟测 ---
$l4Probe = $null
if ($ProbeSearch) {
    $pyCode = @"
import json, sys
from datetime import datetime
from services.agent_runtime.thin_glue_l4_search import run_thin_glue_search
run_id = sys.argv[1] if len(sys.argv) > 1 else 'hotpath_probe'
payload = run_thin_glue_search(
    run_id=run_id,
    local_query='default_plus_dynamic_escalate',
    external_query='temporal langgraph supervisor worker',
    write=True,
)
print(json.dumps({
    'passed': payload.get('validation', {}).get('passed'),
    'local_hits': payload.get('local_hit_count', 0),
    'external_adapter': (payload.get('external_search') or {}).get('adapter'),
    'external_hits': payload.get('external_hit_count', 0),
}, ensure_ascii=False))
"@
    $tmpPy = Join-Path $outDir ("_l4_probe_{0}.py" -f (Get-Date -Format "HHmmss"))
    [System.IO.File]::WriteAllText($tmpPy, $pyCode, $utf8)
    try {
        Push-Location $sRepo
        $env:PYTHONPATH = $sRepo
        $out = python $tmpPy $runId 2>&1 | Out-String
        Pop-Location
        try { $l4Probe = $out.Trim() | ConvertFrom-Json } catch { $l4Probe = [ordered]@{ ok = $false; raw = $out } }
    } catch {
        Pop-Location -ErrorAction SilentlyContinue
        $l4Probe = [ordered]@{ ok = $false; error = "$_" }
    }
    if ($l4Probe) {
        $searchHotPath.l4_probe = $l4Probe
        if ($l4Probe.passed -eq $true) { $searchHotPath.backend_search_ok = $true }
    }
    foreach ($kv in $searchAdapterEvidence.GetEnumerator()) {
        $searchAdapterLatest[$kv.Key] = Read-JsonSafe $kv.Value
    }
    $adapterEvidenceOk = ($searchAdapterLatest.searxng -and $searchAdapterLatest.ripgrep)
    $searchHotPath.adapter_evidence_present = @{
        searxng = ($null -ne $searchAdapterLatest.searxng)
        ripgrep = ($null -ne $searchAdapterLatest.ripgrep)
        ddgs    = ($null -ne $searchAdapterLatest.ddgs)
        exa     = ($null -ne $searchAdapterLatest.exa)
    }
    $searchHotPath.adapter_evidence_ok = [bool]$adapterEvidenceOk
}

# --- 链式扫描 ---
$weakRef = Join-Path $runtime "state\weak_strategy_scan\latest.json"
$policyScanRef = Join-Path $runtime "state\weak_strategy_policy_scan\latest.json"
$policyMirrorRef = Join-Path $runtime "state\weak_strategy_scan\policy_scan_mirror_latest.json"
if ($WithPolicyScan) {
    & (Join-Path $bridge "Invoke-GrokScanStack.ps1") -PolicyScan -Quiet | Out-Null
}
if ($WithWeakStrategy) {
    & (Join-Path $bridge "Invoke-GrokWeakStrategyScan.ps1") -Quiet | Out-Null
}
$weakLatest = Read-JsonSafe $weakRef
$policyScanLatest = Read-JsonSafe $policyScanRef
$policyMirrorLatest = Read-JsonSafe $policyMirrorRef

# --- 热路径缺口（本脚本域，非全宇宙）---
$hotGaps = [System.Collections.Generic.List[object]]::new()
function Add-HotGap([string]$Id, [string]$Sev, [string]$Problem, [string]$Action) {
    $script:hotGaps.Add([ordered]@{
            id             = "HOTPATH_$Id"
            severity       = $Sev
            problem_cn     = $Problem
            next_action_cn = $Action
        })
}

foreach ($sc in $sourceChecks) {
    if (-not $sc.desktop_ok) {
        Add-HotGap "DESKTOP_SOURCE_MISSING_$($sc.id)" "P0" "桌面实施源缺失: $($sc.path)" "恢复桌面 txt 或改 wave_cycle 指针"
    }
    if (-not $sc.mirror_ok) {
        Add-HotGap "MACHINE_MIRROR_MISSING_$($sc.id)" "P0" "机器镜像缺失: $($sc.mirror)" "焊对应 contract/模块/证据"
    }
}
if (-not $rgSmoke.ok) {
    Add-HotGap "RG_SMOKE_FAIL" "P0" "本仓 rg 未命中 default_plus_dynamic_escalate" "确认 S 仓 thin_glue/default_plus_dynamic_escalate 在热路径"
}
if (-not $searxProbe.ok -and -not $thinGlueSearch) {
    Add-HotGap "SEARXNG_AND_EVIDENCE_MISSING" "P1" "SearXNG :8888 未通且无 thin_glue_search 证据" "docker compose up -d waiwang-sousuo 或 -ProbeSearch"
}
if (-not $loopShape.ok) {
    Add-HotGap "LOOP_SHAPE_UNPROVEN" "P1" "integrated_bus 缺云千问 draft + Pro review 形状证据" "跑 integrated_bus temporal 波并落盘 model 字段"
}
if ($weakLatest) {
    foreach ($g in @($weakLatest.gaps | Where-Object { $_.severity -eq "P0" } | Select-Object -First 5)) {
        Add-HotGap ("WEAKSTRAT_$($g.id)") "P0" ([string]$g.problem_cn) ([string]$g.next_action_cn)
    }
}

if (-not $tierChainProof.T0_ddgs_wired) {
    Add-HotGap "DDGS_FALLBACK_NOT_WIRED" "P1" "thin_glue 未证明 DDGS fallback 已接线" "确认 thin_glue_l4_search.run_external_search 含 DDGS 路径"
}
if (-not $tierChainProof.T1_exa_wired) {
    Add-HotGap "EXA_T1_NOT_WIRED" "P1" "thin_glue 未证明 T1 Exa 动态升级已接线" "确认 default_plus_dynamic_escalate.should_escalate_search + probe_exa"
}
if (-not $adapterEvidenceOk) {
    Add-HotGap "SEARCH_ADAPTER_EVIDENCE_MISSING" "P1" "缺 state/search/<adapter>/latest.json 分适配器证据" "跑 thin_glue_l4_search -ProbeSearch 或 integrated_bus 波内 search"
}

$hotGapsSorted = @($hotGaps | Sort-Object { @{ P0 = 0; P1 = 1; P2 = 2 }[[string]$_.severity] }, { [string]$_.id })
$p0Count = @($hotGapsSorted | Where-Object { $_.severity -eq "P0" }).Count

$implementationStatus = [ordered]@{
    rule_cn = "registered=合同/索引有登记；implemented=trace/证据可证已焊"
    SRC_CONTRACT_POINTER = [ordered]@{
        registered  = ($sourceChecks | Where-Object { $_.id -eq "SRC_CONTRACT_POINTER" } | Select-Object -First 1).mirror_ok
        implemented = (Test-Path -LiteralPath $policyPath)
    }
    SRC_BACKEND_SEARCH = [ordered]@{
        registered  = ($sourceChecks | Where-Object { $_.id -eq "SRC_BACKEND_SEARCH" } | Select-Object -First 1).mirror_ok
        implemented = [bool]$tierChainProof.implemented
        tier_chain  = $tierChainProof.tier_chain
    }
    SRC_DYNAMIC_LOOP_SHAPE = [ordered]@{
        registered  = ($sourceChecks | Where-Object { $_.id -eq "SRC_DYNAMIC_LOOP_SHAPE" } | Select-Object -First 1).mirror_ok
        implemented = [bool]$loopShape.ok
        draft_model = $loopShape.draft_model
        review_model = $loopShape.review_model
        rolling_semantic = $loopShape.rolling_semantic
    }
}

$report = [ordered]@{
    schema_version           = "xinao.default_plus_dynamic_hotpath.v1"
    sentinel               = "SENTINEL:DEFAULT_PLUS_DYNAMIC_HOTPATH_V1"
    generated_at           = $ts
    run_id                 = $runId
    completion_claim_allowed = $false
    authority_contract     = $policyPath
    implementation_sources = $sourceChecks
    implementation_status  = $implementationStatus
    search_hotpath         = $searchHotPath
    model_loop_hotpath     = $modelHotPath
    weak_strategy_ref      = $weakRef
    weak_strategy_gap_count = if ($weakLatest) { $weakLatest.gap_count } else { $null }
    policy_scan_ref        = $policyScanRef
    policy_scan_present    = ($null -ne $policyScanLatest)
    policy_scan_findings   = if ($policyScanLatest) { $policyScanLatest.counts.findings_total } else { $null }
    policy_scan_mirror_ref = $policyMirrorRef
    hotpath_gaps           = $hotGapsSorted
    hotpath_gap_count      = $hotGapsSorted.Count
    counts                 = @{
        P0 = $p0Count
        P1 = @($hotGapsSorted | Where-Object { $_.severity -eq "P1" }).Count
        P2 = @($hotGapsSorted | Where-Object { $_.severity -eq "P2" }).Count
    }
    invoke_chain_cn        = @(
        "Invoke-GrokDefaultPlusDynamicHotPath.ps1",
        "Invoke-GrokWeakStrategyScan.ps1",
        "Invoke-GrokScanStack.ps1 -PolicyScan"
    )
    honesty_cn             = "热路径检查≠形状闭合；P0 诚实尺仍可能来自 full_gap/weak_strategy"
}

Write-JsonFile $latestPath $report

$zh = @(
    "# 默认+动态升级 · 三源热路径",
    "",
    "- 时间: $ts",
    "- run_id: $runId",
    "- completion_claim_allowed: false",
    "- 热路径缺口: $($hotGapsSorted.Count)（P0=$p0Count）",
    "",
    "## 三桌面实施源",
    ($(foreach ($sc in $sourceChecks) { "- $($sc.id): 桌面=$($sc.desktop_ok) 镜像=$($sc.mirror_ok)" }) -join "`n"),
    "",
    "## 实施 vs 登记",
    "- 合同指针: reg=$($implementationStatus.SRC_CONTRACT_POINTER.registered) impl=$($implementationStatus.SRC_CONTRACT_POINTER.implemented)",
    "- 后台搜索: reg=$($implementationStatus.SRC_BACKEND_SEARCH.registered) impl=$($implementationStatus.SRC_BACKEND_SEARCH.implemented)",
    "- 动态轮回: reg=$($implementationStatus.SRC_DYNAMIC_LOOP_SHAPE.registered) impl=$($implementationStatus.SRC_DYNAMIC_LOOP_SHAPE.implemented)",
    "",
    "## 后台搜索",
    "- tier_chain: $($tierChainProof.tier_chain -join ' -> ')",
    "- T0 SearXNG=$($tierChainProof.T0_searxng_ok) rg=$($tierChainProof.T0_rg_ok) DDGS_wired=$($tierChainProof.T0_ddgs_wired) Exa_T1_wired=$($tierChainProof.T1_exa_wired)",
    "- SearXNG 容器: $($searxContainer.running) ($($searxContainer.name))",
    "- :8888 JSON: ok=$($searxProbe.ok) hits=$($searxProbe.hit_count)",
    "- rg 烟测: ok=$($rgSmoke.ok) hits=$($rgSmoke.hit_count)",
    "- thin_glue_search 证据: $(if ($thinGlueSearch) { 'present' } else { 'missing' })",
    "- adapter 证据 searxng=$($searchHotPath.adapter_evidence_present.searxng) ripgrep=$($searchHotPath.adapter_evidence_present.ripgrep)",
    "",
    "## 动态轮回形状",
    "- draft: $($loopShape.draft_model)",
    "- review: $($loopShape.review_model)",
    "- parallel_semantic: $($loopShape.parallel_semantic)",
    "- temporal: $($loopShape.temporal_invoke)",
    "",
    "## Top 缺口",
    ($(foreach ($g in ($hotGapsSorted | Select-Object -First 8)) { "- [$($g.severity)] $($g.id): $($g.problem_cn)" }) -join "`n"),
    "",
    "## invoke",
    "- ``Invoke-GrokDefaultPlusDynamicHotPath.ps1 -WithWeakStrategy -WithPolicyScan -ProbeSearch``",
    "- 证据: $latestPath"
)
[System.IO.File]::WriteAllText($zhPath, ($zh -join "`n"), $utf8)

if ($RecordGovernance) {
    & (Join-Path $bridge "Invoke-GrokMatureFirstGovernanceGate.ps1") `
        -RecordStep -StepId "1_external_search_mature" `
        -TaskClass "research_external" `
        -SummaryCn "三源热路径检查：合同/后台搜/动态轮回形状" `
        -ExternalRefs @(
            "C:\Users\xx363\Desktop\合同_默认加动态升级_指针_20260710.txt",
            "C:\Users\xx363\Desktop\后台免费本地搜索_成熟选型与集成_20260710.txt",
            "C:\Users\xx363\Desktop\外部成熟_动态轮回与智能派模_完整形状_20260710.txt"
        ) `
        -LocalRefs @($latestPath, $policyPath) `
        -CarrierChoice "Invoke-GrokDefaultPlusDynamicHotPath.ps1" `
        -Quiet | Out-Null
}

if (-not $Quiet) { $report | ConvertTo-Json -Depth 10 }
exit 0