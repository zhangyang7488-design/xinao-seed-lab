#Requires -Version 5.1
<#
.SYNOPSIS
  全量差距扫描（强制.txt 机器入口）：图景/任务包 vs 本地事实 + L0-L6 采纳深度 + Top3 焊点。
  合同：grok_full_gap_scan_mandate.v1.json
#>
param(
    [string]$ConfigPath = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $ConfigPath
$sRepo = [string]$config.repo_root
$ts = (Get-Date).ToString("o")
$forceTxt = "C:\Users\xx363\Desktop\主线\00_路径权威.txt"
$mandatePath = Join-Path $bridge "grok_full_gap_scan_mandate.v1.json"

& (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -ConfigPath $ConfigPath -Quiet | Out-Null
$holPath = Join-Path $runtime "state\holographic_gap\latest.json"
$hol = if (Test-Path $holPath) {
    Get-Content $holPath -Raw -Encoding UTF8 | ConvertFrom-Json
} else { $null }

$gaps = [System.Collections.Generic.List[object]]::new()
function Add-Gap(
    [string]$Id,
    [string]$Pri,
    [string]$Class,
    [string]$Layer,
    [string]$Detail,
    [string]$Action,
    [string]$Probe = ""
) {
    [void]$script:gaps.Add([ordered]@{
            id            = $Id
            priority      = $Pri
            class_cn      = $Class
            adoption_layer = $Layer
            detail_cn     = $Detail
            action_cn     = $Action
            probe         = $Probe
        })
}

if (-not (Test-Path -LiteralPath $forceTxt)) {
    Add-Gap "PATH_AUTHORITY_MISSING" "P0" "语义图景" "L0" "Desktop\\主线\\00_路径权威.txt 不可读" "恢复 $forceTxt" $forceTxt
}

# --- G02/G03 LiteLLM 云路由 ---
$litellmCfg = Join-Path $sRepo "materials\thin_glue_litellm_config.yaml"
if (Test-Path $litellmCfg) {
    $yaml = Get-Content $litellmCfg -Raw -Encoding UTF8
    $hasDashscope = $yaml -match "dashscope|DASHSCOPE|qwen-turbo|qwen-plus|qwen-max"
    $hasOllamaOnly = $yaml -match "ollama/" -and -not $hasDashscope
    if ($hasOllamaOnly) {
        Add-Gap "LITELLM_QWEN_CLOUD_MISSING" "P0" "基础设施" "L1" `
            "网关只有本地 ollama 千问，无千问云 API（dashscope）" `
            "改 materials/thin_glue_litellm_config.yaml 加 dashscope + 环境变量 DASHSCOPE_API_KEY" $litellmCfg
    }
    if ($yaml -notmatch "deepseek") {
        Add-Gap "LITELLM_DEEPSEEK_CLOUD_MISSING" "P0" "基础设施" "L1" `
            "网关无 DeepSeek 云路由（V4 Pro 验收依赖）" `
            "thin_glue_litellm_config.yaml 加 deepseek/deepseek-chat 或 deepseek-v4-pro + DEEPSEEK_API_KEY" $litellmCfg
    }
} else {
    Add-Gap "LITELLM_CONFIG_MISSING" "P0" "基础设施" "L0" "LiteLLM 配置文件不存在" "恢复 materials/thin_glue_litellm_config.yaml" $litellmCfg
}

# --- G04/G05 worker lane 采纳深度 ---
$lanePath = Join-Path $runtime "state\codex_s_direct_worker_lane\latest.json"
if (Test-Path $lanePath) {
    $lane = Get-Content $lanePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($lane.not_333_mainline -eq $true) {
        Add-Gap "WORKER_LANE_SMOKE_NOT_MAINLINE" "P0" "采纳深度" "L3" `
            "千问/DP worker lane 能烟测，但标 not_333_mainline，未进 333 默认热路径" `
            "Temporal 波内 Activity 默认调千问 draft + Pro review；见规格书 G04/G05" $lanePath
    }
} else {
    Add-Gap "WORKER_LANE_NO_EVIDENCE" "P1" "采纳深度" "L1" `
        "无 worker lane 调用证据" `
        "E:\...\S\scripts\hardmode\Invoke-CodexSWorkerLane.ps1 -Provider qwen -Mode draft" $lanePath
}

$dpProv = Join-Path $runtime "state\dp_sidecar_execution_provider\latest.json"
if (Test-Path $dpProv) {
    $dp = Get-Content $dpProv -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($dp.runtime_enforced -eq $false -or $dp.trigger_installed -eq $false) {
        Add-Gap "PRO_REVIEW_NOT_RUNTIME_ENFORCED" "P0" "路由角色" "L2" `
            "DeepSeek V4 Pro 验收节点未 runtime_enforced（仍是候选/烟测）" `
            "主循环 trigger 绑定 Pro review 节点；合同 grok_deepseek_v4_pro_review_node" $dpProv
    }
}

# --- 云 API 密钥（L2 真调用前置）---
$preflightScript = Join-Path $bridge "Invoke-GrokEnsureCloudApiKeys.ps1"
if (Test-Path $preflightScript) {
    & $preflightScript -ConfigPath $ConfigPath -Quiet | Out-Null
    $prefPath = Join-Path $runtime "state\cloud_api_keys_preflight\latest.json"
    if (Test-Path $prefPath) {
        $pf = Get-Content $prefPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($pf.all_cloud_keys_ready -eq $false) {
            $miss = @()
            if ($pf.dashscope_present -eq $false) { $miss += "DASHSCOPE" }
            if ($pf.deepseek_present -eq $false) { $miss += "DEEPSEEK" }
            Add-Gap "CLOUD_API_KEYS_MISSING" "P0" "基础设施" "L2" `
                "千问/DeepSeek 云 API 未注入（$($miss -join '+')）；网关 models 有名但调不通" `
                ".\Invoke-GrokSyncCloudApiKeysToCompose.ps1 -RecreateGateway（源：C:\\Users\\xx363\\私钥）" $prefPath
        }
    }
}

# --- 主循环 ---
$triggerCand = Join-Path $runtime "state\default_main_loop_trigger_candidate\latest.json"
if (-not (Test-Path $triggerCand)) {
    Add-Gap "MAIN_LOOP_TRIGGER_NO_STATE" "P1" "纵向主轴" "L1" `
        "默认主循环 trigger 无 latest 状态（restore→dispatch→fan_in 未绑热路径）" `
        "python -m services.agent_runtime.default_main_loop_trigger_candidate 或绑 integrated_bus_v2" $triggerCand
}
elseif (Test-Path $triggerCand) {
    $tr = Get-Content $triggerCand -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($tr.sunset_stub -eq $true -or $tr.status -match "sunset") {
        Add-Gap "MAIN_LOOP_SUNSET_STUB" "P0" "采纳深度" "L1" `
            "default_main_loop_trigger_candidate 已 sunset，replacement=integrated_bus_v2；非 L4 热路径" `
            "走 integrated_bus_v2 Temporal 波内 + root_intent_loop trigger enforcement" $triggerCand
    }
    elseif ($tr.runtime_enforced -eq $false -or $tr.trigger_installed -eq $false) {
        Add-Gap "MAIN_LOOP_NOT_RUNTIME_ENFORCED" "P1" "路由角色" "L2" `
            "主循环 trigger 有状态但未 runtime_enforced" `
            "绑 Temporal activity + default_trigger_enforcement_latest" $triggerCand
    }
}

# --- 愿景 contracted ---
$visionPath = Join-Path $runtime "state\vision_mega_package\latest.json"
if (Test-Path $visionPath) {
    $vis = Get-Content $visionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($it in @($vis.items | Where-Object { $_.status -eq "contracted" })) {
        Add-Gap ("VISION_CONTRACTED_" + $it.id) "P1" "诚实闭合门" "L0" `
            "愿景 $($it.id) 仍 contracted：$($it.title_cn)" `
            "Invoke-GrokVisionMegaPackageTrueTest.ps1 -ItemId $($it.id)" $visionPath
    }
}

# --- 治理环 ---
$govPath = Join-Path $runtime "state\grok_governance\latest.json"
if (-not (Test-Path $govPath)) {
    Add-Gap "GOVERNANCE_NO_RECENT_EVIDENCE" "P2" "证据采纳链" "L1" `
        "无近期治理环落盘证据（平台变更可能跳过 0-7）" `
        "Invoke-GrokMatureFirstGovernanceGate.ps1 -RecordStep" $govPath
}

# --- routing_policy 千问优先 ---
$routePol = Join-Path $runtime "agent_runtime\routing_policy.json"
if (Test-Path $routePol) {
    $rp = Get-Content $routePol -Raw -Encoding UTF8 | ConvertFrom-Json
    $qwenRoute = @($rp.routes | Where-Object { $_.target -match "qwen" })
    if ($qwenRoute.Count -eq 0) {
        Add-Gap "ROUTING_POLICY_NO_QWEN" "P1" "路由角色" "L1" `
            "routing_policy 无千问路由；仍偏 deepseek draft" `
            "更新 agent_runtime/routing_policy.json 千问默认工人" $routePol
    }
}

# --- tool_table_coverage 差分轴（invoke_green vs thin_bind）---
$ttcPath = Join-Path $runtime "state\tool_table_coverage\latest.json"
if (-not (Test-Path -LiteralPath $ttcPath)) {
    $ttcPath = Join-Path $runtime "state\tool_table_coverage\v1.json"
}
$toolTableCoverage = $null
if (Test-Path -LiteralPath $ttcPath) {
    $ttc = Get-Content -LiteralPath $ttcPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $greenCnt = [int]$ttc.invoke_green_count
    $thinCnt = [int]$ttc.thin_bind_count
    $rowCnt = [int]$ttc.row_count
    $targetMet = ($ttc.target_met -eq $true)
    $toolTableCoverage = [ordered]@{
        probe_path         = $ttcPath
        invoke_green_count = $greenCnt
        thin_bind_count    = $thinCnt
        row_count          = $rowCnt
        diff_green_minus_thin = ($greenCnt - $thinCnt)
        coverage_ratio_est = $ttc.coverage_ratio_est
        target_green_min   = $ttc.target_green_min
        target_met         = $targetMet
        slo_met            = ($targetMet -and $greenCnt -gt $thinCnt)
        gap_cn             = "invoke_green=$greenCnt thin_bind=$thinCnt Δ=$($greenCnt - $thinCnt)/$rowCnt"
    }
    if (-not $targetMet) {
        Add-Gap "TOOL_TABLE_COVERAGE_BELOW_TARGET" "P1" "采纳深度" "L3" `
            "工具表 invoke_green=$greenCnt < target=$($ttc.target_green_min)；thin_bind=$thinCnt" `
            "python -m services.agent_runtime.tool_table_coverage --runtime-root $runtime" $ttcPath
    }
    if ($thinCnt -ge $greenCnt) {
        Add-Gap "TOOL_TABLE_THIN_BIND_DOMINATES" "P1" "采纳深度" "L3" `
            "工具表 thin_bind($thinCnt) ≥ invoke_green($greenCnt)；全表焊未达 FULL TABLE" `
            "推 integrated_bus_v2 --temporal 波内升级薄绑行" $ttcPath
    }
} else {
    Add-Gap "TOOL_TABLE_COVERAGE_MISSING" "P1" "采纳深度" "L1" `
        "无 tool_table_coverage latest；无法差分 invoke_green vs thin_bind" `
        "cd E:\XINAO_RESEARCH_WORKSPACES\S; python -m services.agent_runtime.tool_table_coverage" $ttcPath
}

# --- P0 honest ---
$p0Path = Join-Path $runtime "state\roi_self_loop\p0_honest_now_can_latest.json"
if (Test-Path $p0Path) {
    $p0 = Get-Content $p0Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($p0.completion_claim_allowed -eq $false) {
        Add-Gap "P0_NOT_CLOSED_HONEST" "P0" "诚实闭合门" "L2" `
            "P0 诚实尺：各层 partial，不得宣布闭合" `
            "按施工包 0-7 推真波 + 本扫描 Top3" $p0Path
    }
}

# --- 并入 holographic isomorphic_leftovers ---
$bridgePointerPath = Join-Path $bridge "grok_admin_bridge_canonical_pointer.v1.json"
$hasBridgePointer = Test-Path -LiteralPath $bridgePointerPath
if ($hol -and $hol.isomorphic_leftovers) {
    foreach ($iso in @($hol.isomorphic_leftovers)) {
        $exists = @($gaps | Where-Object { $_.id -eq $iso.id }).Count -gt 0
        if (-not $exists) {
            $isoId = [string]$iso.id
            $isoSev = [string]$iso.severity
            $isoDetail = [string]$iso.detail_cn
            $isoAction = [string]$iso.action_cn
            $isoPath = if ($iso.PSObject.Properties["path"]) { [string]$iso.path } else { "" }
            if ($isoId -eq "ISLAND_DUAL_BRIDGE_COPY") {
                continue
            }
            if ($isoId -eq "ISLAND_DUAL_BRIDGE_COPY_IGNORED" -and $hasBridgePointer) {
                $isoSev = "P2"
                if (-not $isoDetail) {
                    $isoDetail = "4.5 bridge STALE_MIRROR；Admin POINTER 已封口（read_only_pointer）"
                }
                if ($iso.mitigated -eq $true -and $isoDetail -notmatch "mitigated") {
                    $isoDetail = "$isoDetail [mitigated]"
                }
            }
            Add-Gap $isoId $isoSev "跨仓九宫" "L1" $isoDetail $isoAction $isoPath
        }
    }
}
if ($hol -and $hol.named_gaps) {
    foreach ($ng in @($hol.named_gaps | Where-Object { $_ })) {
        $exists = @($gaps | Where-Object { $_.id -eq $ng }).Count -gt 0
        if (-not $exists) {
            Add-Gap $ng "P1" "纵向主轴" "L2" "全息 named_gap：$ng" "见 holographic_gap latest" $holPath
        }
    }
}

# --- 排序 ---
$priOrder = @{ P0 = 0; P1 = 1; P2 = 2; P3 = 3 }
$sorted = @($gaps | Sort-Object { $priOrder[[string]$_.priority] }, { [string]$_.id })

$top3 = @($sorted | Select-Object -First 3 | ForEach-Object {
        [ordered]@{
            id         = $_.id
            action_cn  = $_.action_cn
            invoke     = $_.action_cn
            probe      = $_.probe
            layer      = $_.adoption_layer
        }
    })

$mapGreen = $false
if ($hol) {
    $mapGreen = ($hol.horizontal_gap_count -eq 0) -and (@($hol.named_gaps | Where-Object { $_ }).Count -eq 0)
}
$semanticGapCount = $sorted.Count
$mapGreenNotClosure = ($mapGreen -and $semanticGapCount -gt 0)

$remaining = $semanticGapCount
$afterTop3 = [Math]::Max(0, $remaining - 3)
$distanceCn = "剩余主要语义缺口约 $remaining 项；焊完 Top3 后预计仍剩约 $afterTop3 项（非终局闭合）"

$rulerPath = Join-Path $bridge "grok_holographic_multi_axis_ruler.v1.json"
$axisScore = @{}
if (Test-Path $rulerPath) {
    $ruler = Get-Content $rulerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($ax in @($ruler.axes)) {
        $fam = @($ax.gap_families)
        $hits = @($sorted | Where-Object {
                $fam -contains $_.id -or ($_.id -like ($fam[0] + "*"))
            })
        $axisScore[[string]$ax.id] = [ordered]@{
            name_cn    = $ax.name_cn
            gap_count  = $hits.Count
            gap_ids    = @($hits | ForEach-Object { $_.id })
            slo_met    = ($hits.Count -eq 0)
        }
    }
}
if ($toolTableCoverage) {
    $ttcGaps = @($sorted | Where-Object {
            $_.id -like "TOOL_TABLE_*"
        })
    $axisScore["A4_tool_table"] = [ordered]@{
        name_cn              = "工具表覆盖差分（invoke_green vs thin_bind）"
        invoke_green_count   = $toolTableCoverage.invoke_green_count
        thin_bind_count      = $toolTableCoverage.thin_bind_count
        diff_green_minus_thin = $toolTableCoverage.diff_green_minus_thin
        gap_count            = $ttcGaps.Count
        gap_ids              = @($ttcGaps | ForEach-Object { $_.id })
        slo_met              = ($toolTableCoverage.slo_met -and $ttcGaps.Count -eq 0)
        probe_path           = $toolTableCoverage.probe_path
    }
}

$out = [ordered]@{
    schema_version             = "xinao.full_gap_scan.v1"
    sentinel                   = "SENTINEL:FULL_GAP_SCAN"
    scanned_at                 = $ts
    mandate_ref                = "grok_full_gap_scan_mandate.v1.json"
    multi_axis_ruler_ref       = "grok_holographic_multi_axis_ruler.v1.json"
    spec_ref                   = "D:\\XINAO_RESEARCH_RUNTIME\\specs\\xinao_333_intent_spec_v20260709.md"
    human_trigger              = $forceTxt
    mandate_contract           = $mandatePath
    completion_claim_allowed   = $false
    holographic_map_all_green  = $mapGreen
    map_green_not_closure      = $mapGreenNotClosure
    semantic_gap_count         = $semanticGapCount
    axis_scorecard             = $axisScore
    tool_table_coverage_axis   = $toolTableCoverage
    gaps_ranked                = $sorted
    top3_weld                  = $top3
    distance_to_goal_cn        = $distanceCn
    goal_cn                    = "自驱 Seed Lab + 333 自动续跑 ResearchEpisode 闭环"
    honesty_cn                 = "含 L0-L6 采纳层 + A0-A11 多轴；地图全绿不等于闭合"
    holographic_gap_ref        = $holPath
}

$outDir = Join-Path $runtime "state\full_gap_scan"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$latest = Join-Path $outDir "latest.json"
$out | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $latest -Encoding UTF8

$rbDir = Join-Path $runtime "readback\zh"
New-Item -ItemType Directory -Force -Path $rbDir | Out-Null
$md = @(
    "# 全量差距扫描（强制令）",
    "- 时间：$ts",
    "- 语义缺口数：**$semanticGapCount**",
    "- 全息地图全绿：$mapGreen",
    "- 地图绿但语义未闭合：**$mapGreenNotClosure**",
    "",
    "## Top 3 下一焊点",
    ""
)
$i = 1
foreach ($t in $top3) {
    $md += "$i. **$($t.id)**（采纳 $($t.layer)）"
    $md += "   - $($t.action_cn)"
    if ($t.probe) { $md += "   - 路径：$($t.probe)" }
    $md += ""
    $i++
}
$md += "## 全部缺口（优先级序）"
$md += ""
foreach ($g in $sorted) {
    $md += "- **[$($g.priority)] $($g.id)** · $($g.class_cn) · **$($g.adoption_layer)** — $($g.detail_cn)"
}
$md += ""
$md += "## 离终局"
$md += $distanceCn
$mdPath = Join-Path $rbDir "full_gap_scan_latest.md"
$md -join "`n" | Set-Content -LiteralPath $mdPath -Encoding UTF8

if (-not $Quiet) { $out | ConvertTo-Json -Depth 8 }
exit 0