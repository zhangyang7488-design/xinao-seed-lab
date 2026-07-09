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

# --- 此刻事实（读盘，不维护平行文档）---
$composeUp = $false
$workerHealthy = $false
$temporalListen = $false
try {
    $names = docker ps --format "{{.Names}}|{{.Status}}" 2>&1 | Out-String
    $composeUp = ($names -match "xinao-temporal-postgres") -and ($names -match "xinao-worker")
    $workerHealthy = ($names -match "xinao-worker.*healthy")
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
    $temporalHealthy = ($ps -match "xinao-temporal-server.*healthy")
    $litellmHealthy = ($ps -match "xinao-thin-glue-litellm.*healthy")
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
if ((Test-Path $lq) -and $composeUp) { $nine.autonomous_queue = "partial" }

$gaps = [System.Collections.Generic.List[string]]::new()
if (-not $composeUp) { [void]$gaps.Add("COMPOSE_NOT_UP") }
if (-not $workerHealthy) { [void]$gaps.Add("WORKER_NOT_HEALTHY") }
if ($spine["3"] -ne "green") { [void]$gaps.Add("SPINE_3_NOT_CLAIMED") }
if ($nine.git_working_tree -eq "gap") { [void]$gaps.Add("GROK_ISLAND_UNCOMMITTED_WELDS") }
if ($nine.autonomous_queue -eq "gap") { [void]$gaps.Add("AUTONOMOUS_QUEUE_NOT_LIVE") }
if (-not $temporalHealthy -and $composeUp) { [void]$gaps.Add("STEP1_HORIZONTAL_TEMPORAL_HEALTHCHECK") }
if (-not $litellmHealthy -and $composeUp) { [void]$gaps.Add("STEP1_HORIZONTAL_LITELLM_HEALTHCHECK") }

$nextWeld = @(
    [ordered]@{ priority = 0; action_cn = "commit merge Grok岛+S仓焊点"; invoke = "git add/commit workspace+S" }
    [ordered]@{ priority = 1; action_cn = "步1横向 healthcheck"; invoke = "S/docker-compose.yml"; status = $(if ($temporalHealthy -and $litellmHealthy) { "done" } else { "open" }) }
    [ordered]@{ priority = 2; action_cn = "默认主路：TaskEntry后自动 ContinueWave+GapScan"; invoke = "Invoke-GrokTaskEntryClaimDurable -AutoWaveClosure" }
    [ordered]@{ priority = 3; action_cn = "九宫：long_workflow 队列与 compose 联动"; invoke = "Invoke-GrokLongWorkflowBootstrap" }
)

$report = [ordered]@{
    schema_version       = "xinao.holographic_gap.v1"
    sentinel             = "SENTINEL:HOLOGRAPHIC_GAP_LIVE_SCAN"
    scanned_at           = $ts
    fact_source_cn       = "此刻读盘；事实不另写死文档；本 JSON 仅扫描时刻快照"
    picture_source_cn    = "施工包前置+全息图景合同；相对静态"
    spine_0to7           = $spine
    nine_grid            = $nine
    named_gaps           = @($gaps)
    claim_state_latest   = $claimState
    compose_up           = $composeUp
    next_weld_queue      = $nextWeld
    completion_claim_allowed = $false
}

$outDir = Join-Path $runtime "state\holographic_gap"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$latest = Join-Path $outDir "latest.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $latest -Encoding UTF8

if (-not $Quiet) { $report | ConvertTo-Json -Depth 8 }
exit 0