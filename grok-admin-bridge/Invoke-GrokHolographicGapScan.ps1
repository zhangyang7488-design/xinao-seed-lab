#Requires -Version 5.1
<#
.SYNOPSIS
  全息差距扫描：施工包=图景(静态) · 本地=事实(此刻读盘) · 输出差距矩阵，不另写死「事实文档」。
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

function Step-Ok([bool]$b) { if ($b) { "green" } else { "gap" } }

$composeNames = & (Join-Path $bridge "Invoke-GrokResolveComposeNames.ps1") -ConfigPath $ConfigPath
function Get-ComposeServiceEntry([string]$Key) {
    # Get-XinaoComposeDisplayNames returns OrderedDictionary (not PSCustomObject)
    $svcMap = $composeNames.services
    if ($null -eq $svcMap) { return $null }
    if ($svcMap -is [System.Collections.IDictionary]) {
        if ($svcMap.Contains($Key)) { return $svcMap[$Key] }
        return $null
    }
    $prop = $svcMap.PSObject.Properties | Where-Object { $_.Name -eq $Key } | Select-Object -First 1
    if ($prop) { return $prop.Value }
    return $null
}
function Test-ComposeContainer([string]$PsText, [string]$Key, [switch]$RequireHealthy) {
    $svc = Get-ComposeServiceEntry $Key
    if (-not $svc) { return $false }
    $slugs = @()
    if ($svc.slug_set) { $slugs += @($svc.slug_set) }
    if ($svc.container_name) { $slugs += [string]$svc.container_name }
    if ($svc.legacy_slugs) { $slugs += @($svc.legacy_slugs) }
    foreach ($slug in ($slugs | Select-Object -Unique)) {
        if (-not $slug) { continue }
        if ($RequireHealthy) {
            if ($PsText -match "$([regex]::Escape([string]$slug)).*healthy") { return $true }
        } elseif ($PsText -match [regex]::Escape([string]$slug)) {
            return $true
        }
    }
    return $false
}

# --- 此刻事实（读盘，不维护平行文档）---
$composeUp = $false
$workerHealthy = $false
$temporalListen = $false
try {
    $names = docker ps --format "{{.Names}}|{{.Status}}" 2>&1 | Out-String
    $composeUp = (Test-ComposeContainer $names "shiwu-ku") -and (Test-ComposeContainer $names "houtai-gongren")
    $workerHealthy = Test-ComposeContainer $names "houtai-gongren" -RequireHealthy
} catch { }

try {
    $temporalListen = (Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue).TcpTestSucceeded
} catch { }

$taskLatest = Join-Path $runtime "state\task_entry\latest.json"
$waveLatest = Join-Path $runtime "state\task_entry\wave_closure\latest.json"
$checkpoint = "D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context\latest.json"
$claimState = ""
$spine = @{ "0" = "gap"; "1" = "gap"; "2" = "gap"; "3" = "gap"; "4" = "gap"; "5" = "gap"; "6" = "gap"; "7" = "gap" }

if (Test-Path $taskLatest) {
    $t = Get-Content $taskLatest -Raw -Encoding UTF8 | ConvertFrom-Json
    $claimState = [string]$t.claim_state
    $spine["0"] = "green"
    if ($t.temporal_7233_ok -eq $true -or $temporalListen) { $spine["1"] = "green" }
    if ($workerHealthy) { $spine["2"] = "green" }
    if ($claimState -eq "durable_claimed") { $spine["3"] = "green" }
}
if (Test-Path $waveLatest) {
    $w = Get-Content $waveLatest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($w.steps.step4_langgraph_ok) { $spine["4"] = "green" }
    if ($w.steps.step5_execution_ok) { $spine["5"] = "green" }
    if ($w.steps.step6_fanin_ok) { $spine["6"] = "green" }
    if ($w.steps.step7_continue_ok) { $spine["7"] = "green" }
}

$temporalHealthy = $false
$litellmHealthy = $false
try {
    $ps = docker ps --format "{{.Names}}|{{.Status}}" 2>&1 | Out-String
    $temporalHealthy = Test-ComposeContainer $ps "naijiu-shiwu" -RequireHealthy
    $litellmHealthy = Test-ComposeContainer $ps "moxing-wangguan" -RequireHealthy
} catch { }

$nine = [ordered]@{
    hot_path_s_repo       = Step-Ok (Test-Path (Join-Path $sRepo "docker-compose.yml"))
    hot_path_grok_bridge  = Step-Ok (Test-Path (Join-Path $bridge "Invoke-GrokTaskEntryClaimDurable.ps1"))
    evidence_root         = Step-Ok (Test-Path $runtime)
    checkpoint_live       = Step-Ok (Test-Path $checkpoint)
    memory_md             = Step-Ok (Test-Path "C:\Users\xx363\.grok\memory\MEMORY.md")
    preamble_contract     = Step-Ok (Test-Path (Join-Path $bridge "grok_construction_package_preamble.v1.json"))
    gap_scan_self         = "green"
    step1_h_temporal_hc   = $(if ($temporalHealthy) { "green" } elseif ($composeUp) { "partial" } else { "gap" })
    step1_h_litellm_hc   = $(if ($litellmHealthy) { "green" } elseif ($composeUp) { "partial" } else { "gap" })
    git_working_tree      = "gap"
    autonomous_queue      = "gap"
}
try {
    Push-Location (Split-Path $bridge -Parent)
    $st = git status --porcelain 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0 -and -not $st.Trim()) { $nine.git_working_tree = "green" }
    Pop-Location
} catch { Pop-Location -EA SilentlyContinue }

$lq = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
$lwf = Join-Path $runtime "state\grok_long_workflow\latest.json"
$pendingTaskCount = 0
if (Test-Path $lq) {
    $qSnap = Get-Content $lq -Raw -Encoding UTF8 | ConvertFrom-Json
    $pendingTaskCount = @($qSnap.tasks | Where-Object { $_.status -eq "pending" }).Count
}
if ((Test-Path $lq) -and (Test-Path $lwf) -and $composeUp) { $nine.autonomous_queue = "green" }
elseif ((Test-Path $lq) -and $composeUp) { $nine.autonomous_queue = "partial" }

$taskObj = $null
if (Test-Path $taskLatest) { $taskObj = Get-Content $taskLatest -Raw -Encoding UTF8 | ConvertFrom-Json }
$waveObj = $null
if (Test-Path $waveLatest) { $waveObj = Get-Content $waveLatest -Raw -Encoding UTF8 | ConvertFrom-Json }

$intakeDir = Join-Path $runtime "state\task_entry\intake"
$readbackZh = Join-Path $runtime "readback\zh"
$wfId = ""; $runId = ""
if ($taskObj) {
    if ($taskObj.PSObject.Properties["temporal_workflow_id"]) { $wfId = [string]$taskObj.temporal_workflow_id }
    elseif ($taskObj.PSObject.Properties["workflow_id"]) { $wfId = [string]$taskObj.workflow_id }
    if ($taskObj.PSObject.Properties["temporal_workflow_run_id"]) { $runId = [string]$taskObj.temporal_workflow_run_id }
    elseif ($taskObj.PSObject.Properties["run_id"]) { $runId = [string]$taskObj.run_id }
}
$postgresHealthy = $false
try {
    $ps2 = docker ps --format "{{.Names}}|{{.Status}}" 2>&1 | Out-String
    $postgresHealthy = Test-ComposeContainer $ps2 "shiwu-ku" -RequireHealthy
} catch { }

$aaqLatest = Join-Path $runtime "state\aaq\integrated_bus\latest.json"
$aaqObj = $null
if (Test-Path $aaqLatest) { $aaqObj = Get-Content $aaqLatest -Raw -Encoding UTF8 | ConvertFrom-Json }
$promoOk = $false
$promoLatest = Get-ChildItem (Join-Path $runtime "readback") -Filter "integrated_bus_promotion_*.json" -File -EA SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($promoLatest) {
    try {
        $pj = Get-Content $promoLatest.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($pj.validation.passed -eq $true -or $pj.memory_promoted -eq $true) { $promoOk = $true }
    } catch { }
}
if ($aaqObj -and $aaqObj.promotion_gate_passed -eq $true) { $promoOk = $true }
$evoState = Join-Path $runtime "state\proactive_evolution_intake\latest.json"
$evoOk = Test-Path $evoState

$horizontal = [ordered]@{
    step0 = [ordered]@{
        h1_entry_ps1      = Step-Ok (Test-Path (Join-Path $bridge "Invoke-GrokTaskEntry.ps1"))
        h2_task_module      = Step-Ok (Test-Path (Join-Path $bridge "grok_task_entry_module.v1.json"))
        h3_latest_json      = Step-Ok (Test-Path $taskLatest)
        h4_intake_dir       = Step-Ok (Test-Path $intakeDir)
        h5_get_status_ps1   = Step-Ok (Test-Path (Join-Path $bridge "Get-GrokTaskEntryStatus.ps1"))
        h6_readback_zh      = Step-Ok (Test-Path $readbackZh)
        h7_staging_honest   = $(if ($taskObj) { "green" } else { "gap" })
    }
    step1 = [ordered]@{
        h1_compose_yml      = Step-Ok (Test-Path (Join-Path $sRepo "docker-compose.yml"))
        h2_start_script     = Step-Ok (Test-Path (Join-Path $sRepo "scripts\Start-XinaoBaseCompose.ps1"))
        h3_port_7233        = Step-Ok $temporalListen
        h4_temporal_hc      = $(if ($temporalHealthy) { "green" } elseif ($composeUp) { "partial" } else { "gap" })
        h5_postgres_hc      = $(if ($postgresHealthy) { "green" } elseif ($composeUp) { "partial" } else { "gap" })
        h6_litellm_hc       = $(if ($litellmHealthy) { "green" } elseif ($composeUp) { "partial" } else { "gap" })
        h7_compose_evidence = Step-Ok (Test-Path (Join-Path $runtime "state\xinao_base_compose\latest.json"))
    }
    step2 = [ordered]@{
        h1_worker_up        = Step-Ok (Test-ComposeContainer $names "houtai-gongren")
        h2_worker_healthy   = Step-Ok $workerHealthy
        h3_status_script    = Step-Ok (Test-Path (Join-Path $sRepo "scripts\Status-XinaoBaseCompose.ps1"))
        h4_daemon_evidence  = Step-Ok (Test-Path (Join-Path $runtime "state\integrated_bus_worker_daemon\latest.json"))
        h5_qdrant_up        = Step-Ok (Test-ComposeContainer $names "xiangliang-ku")
        h6_temporal_ui      = Step-Ok (Test-ComposeContainer $names "shiwu-mianban")
        h7_compose_service  = Step-Ok (Test-Path (Join-Path $sRepo "docker-compose.yml"))
    }
    step3 = [ordered]@{
        h1_claim_ps1        = Step-Ok (Test-Path (Join-Path $bridge "Invoke-GrokTaskEntryClaimDurable.ps1"))
        h2_claim_py         = Step-Ok (Test-Path (Join-Path $sRepo "services\agent_runtime\task_entry_claim.py"))
        h3_durable_evidence = Step-Ok (Test-Path (Join-Path $runtime "state\task_entry\durable_claim\latest.json"))
        h4_wf_evidence      = Step-Ok (Test-Path (Join-Path $runtime "state\temporal_codex_task_workflow\latest.json"))
        h5_durable_claimed  = $(if ($claimState -eq "durable_claimed") { "green" } else { "gap" })
        h6_workflow_id      = $(if ($wfId) { "green" } else { "gap" })
        h7_run_id           = $(if ($runId) { "green" } else { "gap" })
    }
    step4 = [ordered]@{
        h1_wave_status_ps1  = Step-Ok (Test-Path (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1"))
        h2_wave_closure     = Step-Ok (Test-Path $waveLatest)
        h3_langgraph_ok     = $(if ($waveObj -and $waveObj.steps.step4_langgraph_ok) { "green" } else { "gap" })
        h4_integrated_bus   = Step-Ok ((Get-ChildItem -Path (Join-Path $runtime "readback") -Filter "integrated_bus_*.json" -ErrorAction SilentlyContinue | Select-Object -First 1) -ne $null)
        h5_glue_seam        = Step-Ok (Test-Path (Join-Path $runtime "state\glue_seam_invoke\latest.json"))
        h6_child_wf         = Step-Ok (Test-Path (Join-Path $runtime "state\integrated_bus_child_wf\latest.json"))
        h7_worker_polling   = Step-Ok $workerHealthy
    }
    step5 = [ordered]@{
        h1_continue_ps1     = Step-Ok (Test-Path (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1"))
        h2_thin_glue_ev     = Step-Ok (Test-Path (Join-Path $runtime "state\thin_glue_l3_execute\latest.json"))
        h3_litellm_up       = $(if ($litellmHealthy) { "green" } else { "gap" })
        h4_worker_lane      = Step-Ok (Test-Path (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1"))
        h5_execution_ok     = $(if ($waveObj -and $waveObj.steps.step5_execution_ok) { "green" } else { "gap" })
        h6_direct_lane_ev   = Step-Ok (Test-Path (Join-Path $runtime "state\codex_s_direct_worker_lane\latest.json"))
        h7_compose_litellm  = Step-Ok (Test-ComposeContainer $names "moxing-wangguan")
    }
    step6 = [ordered]@{
        h1_fanin_ok         = $(if ($waveObj -and $waveObj.steps.step6_fanin_ok) { "green" } else { "gap" })
        h2_aaq_evidence     = Step-Ok (Test-Path (Join-Path $runtime "state\aaq\integrated_bus\latest.json"))
        h3_zh_readback      = Step-Ok ((Get-ChildItem -Path $readbackZh -Filter "integrated_bus_*.md" -ErrorAction SilentlyContinue | Select-Object -First 1) -ne $null)
        h4_wave_closure     = Step-Ok (Test-Path $waveLatest)
        h5_fanin_honest     = $(if ($waveObj -and $waveObj.steps.step6_fanin_ok) { "green" } elseif ($waveObj) { "partial" } else { "gap" })
        h6_task_lineage     = $(if ($taskObj -and $claimState -eq "durable_claimed") { "green" } else { "gap" })
        h7_promotion_gate   = $(if ($promoOk) { "green" } elseif ($promoLatest) { "partial" } else { "gap" })
    }
    step7 = [ordered]@{
        h1_continue_wave    = Step-Ok (Test-Path (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1"))
        h2_wf_history_ev    = Step-Ok (Test-Path (Join-Path $runtime "state\temporal_codex_task_workflow\latest.json"))
        h3_continue_ok      = $(if ($waveObj -and $waveObj.steps.step7_continue_ok) { "green" } else { "partial" })
        h4_gap_scan         = "green"
        h5_long_workflow    = Step-Ok (Test-Path $lwf)
        h6_checkpoint       = Step-Ok (Test-Path $checkpoint)
        h7_evolution_honest = $(if ($evoOk) { "green" } else { "partial" })
    }
}

$horizontalGapCount = 0
foreach ($stepKey in $horizontal.Keys) {
    foreach ($cell in $horizontal[$stepKey].Values) {
        if ($cell -eq "gap") { $horizontalGapCount++ }
    }
}

$gaps = [System.Collections.Generic.List[string]]::new()
if (-not $composeUp) { [void]$gaps.Add("COMPOSE_NOT_UP") }
if (-not $workerHealthy) { [void]$gaps.Add("WORKER_NOT_HEALTHY") }
if ($spine["3"] -ne "green") { [void]$gaps.Add("SPINE_3_NOT_CLAIMED") }
if ($nine.git_working_tree -eq "gap") { [void]$gaps.Add("GROK_ISLAND_UNCOMMITTED_WELDS") }
if ($nine.autonomous_queue -eq "gap") { [void]$gaps.Add("AUTONOMOUS_QUEUE_NOT_LIVE") }
if (-not $temporalHealthy -and $composeUp) { [void]$gaps.Add("STEP1_HORIZONTAL_TEMPORAL_HEALTHCHECK") }
if (-not $litellmHealthy -and $composeUp) { [void]$gaps.Add("STEP1_HORIZONTAL_LITELLM_HEALTHCHECK") }
if ($horizontalGapCount -gt 0) { [void]$gaps.Add("HORIZONTAL_GRID_GAPS:$horizontalGapCount") }

$nextWeld = [System.Collections.Generic.List[object]]::new()
if ($nine.git_working_tree -eq "gap") {
    [void]$nextWeld.Add([ordered]@{ priority = 0; action_cn = "commit merge 未提交焊点"; invoke = "git commit"; status = "open" })
}
if (-not ($temporalHealthy -and $litellmHealthy)) {
    [void]$nextWeld.Add([ordered]@{ priority = 1; action_cn = "步1横向 healthcheck"; invoke = "S/docker-compose.yml"; status = "open" })
}
if ($nine.autonomous_queue -ne "green") {
    [void]$nextWeld.Add([ordered]@{ priority = 2; action_cn = "long_workflow+gap 联动"; invoke = "Invoke-GrokLongWorkflowBootstrap"; status = "open" })
}
if ($pendingTaskCount -gt 0) {
    [void]$nextWeld.Add([ordered]@{ priority = 3; action_cn = "7×24 真推下一 pending task"; invoke = "Invoke-GrokLongWorkflowRunNext"; status = "open" })
}
if ($nextWeld.Count -eq 0) {
    if (-not $evoOk) {
        [void]$nextWeld.Add([ordered]@{ priority = 0; action_cn = "种子 wave11 队列（愿景大包+主动进化+M1-M4）"; invoke = "Invoke-GrokLongWorkflowRunNext -SeedWave11"; status = "planned" })
    } else {
        [void]$nextWeld.Add([ordered]@{ priority = 0; action_cn = "按 vision_mega_package 逐项真测推进"; invoke = "state/vision_mega_package/latest.json"; status = "planned" })
    }
    [void]$nextWeld.Add([ordered]@{ priority = 1; action_cn = "成熟控制面焊通 Pro 验收节点（DeepSeek V4 Pro；DP仅缩写）"; invoke = "grok_deepseek_v4_pro_review_node.v1.json"; status = "planned" })
}

$report = [ordered]@{
    schema_version       = "xinao.holographic_gap.v1"
    sentinel             = "SENTINEL:HOLOGRAPHIC_GAP_LIVE_SCAN"
    scanned_at           = $ts
    fact_source_cn       = "此刻读盘；事实不另写死文档；本 JSON 仅扫描时刻快照"
    picture_source_cn    = "施工包前置+全息图景合同；相对静态"
    spine_0to7           = $spine
    horizontal_grids     = $horizontal
    horizontal_gap_count = $horizontalGapCount
    nine_grid            = $nine
    named_gaps           = @($gaps)
    claim_state_latest   = $claimState
    compose_up           = $composeUp
    pending_task_count   = $pendingTaskCount
    next_weld_queue      = $nextWeld
    completion_claim_allowed = $false
}

$outDir = Join-Path $runtime "state\holographic_gap"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$latest = Join-Path $outDir "latest.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $latest -Encoding UTF8

if (-not $Quiet) { $report | ConvertTo-Json -Depth 8 }
exit 0