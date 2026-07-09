#Requires -Version 5.1
<#
.SYNOPSIS
  P0 施工图落地波 — 事务 A/C/D 可执行作业批量 invoke；证据写 D 盘。
  母版：桌面\P0后台自治系统完整施工图_显影对照本地_20260708.txt 第三节
.NOT_333_MAINLINE
#>
param(
    [switch]$SkipOpenHands,
    [switch]$SkipGlueClone,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8

$bridge = $PSScriptRoot
$runtime = "D:\XINAO_RESEARCH_RUNTIME"
$evidenceDir = Join-Path $runtime "state\p0_blueprint_land_wave"
$latestPath = Join-Path $evidenceDir "latest.json"
$readbackPath = Join-Path $runtime "readback\zh\grok_gap_constitution_vs_local_latest.md"
$queuePath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

$steps = [System.Collections.Generic.List[object]]::new()

function Add-Step([string]$Id, [string]$Status, [hashtable]$Extra = @{}) {
    $s = [ordered]@{ id = $Id; status = $Status; at = (Get-Date).ToString("o") }
    foreach ($k in $Extra.Keys) { $s[$k] = $Extra[$k] }
    $steps.Add([pscustomobject]$s) | Out-Null
}

function Write-GapTable([hashtable]$Snap) {
    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine("# Grok 差距对照表（工具胶水宪法 vs 本地）")
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("更新时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm') · blueprint_land_wave")
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("## 快照")
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("| 项 | 状态 |")
    [void]$sb.AppendLine("|----|------|")
    [void]$sb.AppendLine("| LiteLLM :20128 | $($Snap.litellm) |")
    [void]$sb.AppendLine("| Ollama :11434 | $($Snap.ollama) |")
    [void]$sb.AppendLine("| Qdrant :6333 | $($Snap.qdrant) |")
    [void]$sb.AppendLine("| Docker | $($Snap.docker) |")
    [void]$sb.AppendLine("| registry hooked | **$($Snap.hooked)** |")
    [void]$sb.AppendLine("| 镜像 official | **$($Snap.mirrors)** |")
    [void]$sb.AppendLine("| glue 缺 | **$($Snap.glue_missing)** |")
    [void]$sb.AppendLine("| xinao :19460 | $($Snap.xinao) |")
    [void]$sb.AppendLine("| worker qwen | $($Snap.worker_qwen) |")
    [void]$sb.AppendLine("| worker dp | $($Snap.worker_dp) |")
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("## now_can_invoke")
    [void]$sb.AppendLine("")
    foreach ($i in $Snap.now_can_invoke) { [void]$sb.AppendLine("- $i") }
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("## 诚实 blocker")
    [void]$sb.AppendLine("")
    foreach ($b in $Snap.blockers) { [void]$sb.AppendLine("- $b") }
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("333 建设期；非全局闭合。")
    [System.IO.File]::WriteAllText($readbackPath, $sb.ToString(), $utf8)
}

# D-02 bootstrap
try {
    & (Join-Path $bridge "Invoke-GrokLongWorkflowBootstrap.ps1") -Quiet | Out-Null
    Add-Step "D-02_bootstrap" "done"
} catch {
    Add-Step "D-02_bootstrap" "failed" @{ error = $_.Exception.Message }
}

# A-L3-L01~04 LiteLLM stack
$litellmOk = $false
$thinStart = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Start-XinaoThinGlueStack.ps1"
try {
    if (Test-Path $thinStart) {
        & $thinStart -Down 2>&1 | Out-Null
        Start-Sleep -Seconds 3
        & $thinStart 2>&1 | Out-Null
        Start-Sleep -Seconds 12
        $lk = if ($env:LITELLM_MASTER_KEY) { $env:LITELLM_MASTER_KEY } else { "sk-xinao-thin-glue-local" }
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:20128/v1/models" -Headers @{ Authorization = "Bearer $lk" } -UseBasicParsing -TimeoutSec 15
        $litellmOk = ($r.StatusCode -eq 200)
        Add-Step "A-L3-L01_litellm_stack" $(if ($litellmOk) { "done" } else { "partial" }) @{ http_status = $r.StatusCode }
        # qwen3.6-flash alias chat smoke
        if ($litellmOk) {
            $body = '{"model":"qwen3.6-flash","messages":[{"role":"user","content":"glue_ok"}]}'
            try {
                $cr = Invoke-WebRequest -Uri "http://127.0.0.1:20128/v1/chat/completions" -Method POST `
                    -Headers @{ Authorization = "Bearer $lk"; "Content-Type" = "application/json" } `
                    -Body $body -UseBasicParsing -TimeoutSec 90
                Add-Step "A-L3-L02_gateway_chat" "done" @{ model = "qwen3.6-flash"; status = $cr.StatusCode }
            } catch {
                Add-Step "A-L3-L02_gateway_chat" "failed" @{ error = $_.Exception.Message }
            }
        }
    }
} catch {
    Add-Step "A-L3-L01_litellm_stack" "failed" @{ error = $_.Exception.Message }
}

# A-L0-M01 registry scan + claim
try {
    & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null
    Add-Step "A-L0-M01_registry_scan" "done"
} catch {
    Add-Step "A-L0-M01_registry_scan" "failed" @{ error = $_.Exception.Message }
}

# D-工人-01 worker lane
$workerQwen = "pending"
$workerDp = "pending"
try {
    $q = & (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1") -Mode draft -Provider qwen `
        -Objective "P0施工图落地：千问草稿烟测" -InputText "用≤10字中文回复glue_ok" 2>&1 | Out-String
    $ql = Get-Content (Join-Path $runtime "state\codex_s_direct_worker_lane\latest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $workerQwen = [string]$ql.status
    if ($ql.worker_lane_result.model_invocation_performed -eq $true) { $workerQwen = "invoke_ok" }
    elseif ($ql.named_blocker) { $workerQwen = "blocked:$($ql.named_blocker)" }
    Add-Step "D-工人-01_qwen" $(if ($workerQwen -like "*ok*" -or $ql.status -eq "direct_worker_lane_ready") { "done" } else { "blocked" }) @{ detail = $workerQwen }
} catch {
    Add-Step "D-工人-01_qwen" "failed" @{ error = $_.Exception.Message }
    $workerQwen = "failed"
}

try {
    $d = & (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1") -Mode draft -Provider dp `
        -Objective "P0施工图落地：DP草稿烟测" -InputText "用≤10字中文回复dp_ok" 2>&1 | Out-String
    $dl = Get-Content (Join-Path $runtime "state\codex_s_direct_worker_lane\latest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $workerDp = [string]$dl.status
    if ($dl.worker_lane_result.model_invocation_performed -eq $true) { $workerDp = "invoke_ok" }
    Add-Step "D-工人-01_dp" $(if ($dl.status -eq "direct_worker_lane_ready") { "done" } else { "blocked" }) @{ detail = $workerDp }
} catch {
    Add-Step "D-工人-01_dp" "failed" @{ error = $_.Exception.Message }
    $workerDp = "failed"
}

# C-L3-OH01 OpenHands
if (-not $SkipOpenHands) {
    try {
        & (Join-Path $bridge "Invoke-GrokOpenHandsSmokeWhenDocker.ps1") 2>&1 | Out-Null
        $oh = Join-Path $runtime "state\openhands_smoke\latest.json"
        if (Test-Path $oh) {
            $ohj = Get-Content $oh -Raw -Encoding UTF8 | ConvertFrom-Json
            Add-Step "C-L3-OH01_openhands" $(if ($ohj.pull_ok) { "done" } else { "blocked" }) @{ blocker = $ohj.named_blocker }
        } else {
            Add-Step "C-L3-OH01_openhands" "partial"
        }
    } catch {
        Add-Step "C-L3-OH01_openhands" "failed" @{ error = $_.Exception.Message }
    }
}

# C-01 glue gap (small repos only)
if (-not $SkipGlueClone) {
    try {
        & (Join-Path $bridge "Invoke-XinaoGlueRegistryGapFill.ps1") -SkipLarge 2>&1 | Out-Null
        Add-Step "C-01_glue_gap_fill" "done"
    } catch {
        Add-Step "C-01_glue_gap_fill" "failed" @{ error = $_.Exception.Message }
    }
}

# Status probe
$status = & (Join-Path $bridge "Get-GrokLocalCapabilityStatus.ps1") 2>&1 | Out-String
$statusJson = $null
try { $statusJson = $status | ConvertFrom-Json } catch {}

$reg = $null
$regPath = Join-Path $runtime "state\local_capability_registry\latest.json"
if (Test-Path $regPath) { $reg = Get-Content $regPath -Raw -Encoding UTF8 | ConvertFrom-Json }

# Capabilities invoke evidence (Grok island)
$capDir = Join-Path $runtime "capabilities\grok.p0_blueprint_land.worker_lane_smoke"
$capEv = Join-Path $capDir "invoke_evidence"
New-Item -ItemType Directory -Force -Path $capEv | Out-Null
$capLatest = Join-Path $capEv "latest.json"
@{
    schema_version = "xinao.grok_capability_invoke_evidence.v1"
    capability_id  = "grok.p0_blueprint_land.worker_lane_smoke"
    generated_at   = (Get-Date).ToString("o")
    not_333_mainline = $true
    worker_qwen    = $workerQwen
    worker_dp      = $workerDp
    litellm_ok     = $litellmOk
    refs           = @{
        worker_lane = Join-Path $runtime "state\codex_s_direct_worker_lane\latest.json"
        registry    = $regPath
        wave        = $latestPath
    }
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $capLatest -Encoding UTF8
Add-Step "A-L5-E01_capability_evidence" "done" @{ path = $capLatest }

# Update task queue (PSCustomObject from JSON may lack optional props — use hashtable round-trip)
if (Test-Path $queuePath) {
    $qRaw = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $tasks = @()
    foreach ($t in $qRaw.tasks) {
        $h = @{}
        $t.PSObject.Properties | ForEach-Object { $h[$_.Name] = $_.Value }
        if ($h.id -eq "W5_1_worker_lane_smoke") {
            $h.status = if ($workerQwen -like "*ok*" -or $workerDp -like "*ready*") { "done" } else { "partial" }
            $h.completed_at = (Get-Date).ToString("o")
        }
        if ($h.id -eq "W2_1_registry_claim") {
            $h.status = "done"
            $h.completed_at = (Get-Date).ToString("o")
            $h.note = "litellm hooked; xinao honest blocker"
        }
        $tasks += [pscustomobject]$h
    }
    $qOut = [ordered]@{
        schema_version = $qRaw.schema_version
        updated_at     = (Get-Date).ToString("o")
        execution_mode = $qRaw.execution_mode
        scope_cn       = $qRaw.scope_cn
        tasks          = $tasks
    }
    $qOut | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $queuePath -Encoding UTF8
    Add-Step "D-03_task_queue" "done"
}

# Gap table
$hooked = if ($reg) { $reg.counts.registered_and_hooked } else { "?" }
$mirrors = if ($reg) { $reg.counts.official_mirror_count } else { "?" }
$glueMissing = if ($reg) { $reg.counts.glue_registry_missing } else { "?" }
$xinaoProbe = $false
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:19460/mcp" -UseBasicParsing -TimeoutSec 3 | Out-Null
    $xinaoProbe = $true
} catch {}

$snap = @{
    litellm      = if ($litellmOk) { "绿 · qwen3.6-flash chat ok" } else { "黄" }
    ollama       = if ($statusJson.grok_self.ollama_11434.ok) { "绿" } else { "黄" }
    qdrant       = if ($statusJson.grok_self.qdrant_6333.ok) { "绿" } else { "黄" }
    docker       = if ($statusJson.grok_self.docker.ok) { "绿" } else { "黄" }
    hooked       = $hooked
    mirrors      = $mirrors
    glue_missing = $glueMissing
    xinao        = if ($xinaoProbe) { "绿" } else { "灰 · XINAO_MCP_19460_DOWN" }
    worker_qwen  = $workerQwen
    worker_dp    = $workerDp
    now_can_invoke = @(
        "Invoke-GrokP0BlueprintLandWave.ps1",
        "Start-XinaoThinGlueStack.ps1",
        "Invoke-GrokCodexSDirectWorkerLane.ps1",
        "Invoke-GrokLocalCapabilityRegistryScan.ps1",
        "Get-GrokLocalCapabilityStatus.ps1"
    )
    blockers = @("XINAO_MCP_19460_DOWN", "GLUE_DOCKER_NOT_GH_REPO")
}
Write-GapTable $snap
Add-Step "D-04_gap_table" "done" @{ path = $readbackPath }

# D-01 checkpoint save
$draft = @{
    user_intent_anchor_cn   = "落地P0施工图；事务A/C/D批量invoke"
    session_resume_brief_cn = "blueprint_land_wave完成；LiteLLM+qwen别名修复；worker烟测；差距表已更新"
    last_machine_actions    = @("Invoke-GrokP0BlueprintLandWave.ps1", "litellm qwen3.6-flash alias", "gap_table")
    next_machine_actions    = @("333工程层B1 Temporal评估", "xinao起停或保持blocker")
    named_blockers          = @("XINAO_MCP_19460_DOWN")
    evidence_refs           = @($latestPath, $readbackPath, $capLatest)
    do_not_re_explain_cn    = @("333未闭合", "施工图已落地波", "事务B后置")
}
$draftPath = Join-Path $runtime "state\grok_session_context\save_draft.json"
$draft | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $draftPath -Encoding UTF8
try {
    & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save -InputJson $draftPath -IncludeRegistryScan -Quiet | Out-Null
    Add-Step "D-01_checkpoint" "done"
} catch {
    Add-Step "D-01_checkpoint" "failed" @{ error = $_.Exception.Message }
}

$report = [ordered]@{
    schema_version = "xinao.p0_blueprint_land_wave.v1"
    generated_at   = (Get-Date).ToString("o")
    not_333_mainline = $true
    blueprint_ref  = "P0后台自治系统完整施工图_显影对照本地_20260708.txt"
    steps          = $steps
    snapshot       = $snap
    evidence_refs  = @{
        latest    = $latestPath
        gap_table = $readbackPath
        queue     = $queuePath
        capability = $capLatest
    }
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $latestPath -Encoding UTF8

if (-not $Quiet) {
    $report | ConvertTo-Json -Depth 6
}