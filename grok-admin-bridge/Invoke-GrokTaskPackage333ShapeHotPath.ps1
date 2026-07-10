#Requires -Version 5.1
<#
.SYNOPSIS
  333 任务包七环形状 → Temporal integrated_bus 热路径（非只登记）。
.DESCRIPTION
  对照：桌面三 txt + xinao_333_intent_spec + holographic_gap TASK_PACKAGE_333_SHAPE_NOT_HOT。
  链：SyncCloudApiKeys → integrated_bus_runner --temporal → 333 shape 门 → GapScan 复验。
  证据：D:\XINAO_RESEARCH_RUNTIME\readback\zh\ + state\task_package_333_shape_hot\latest.json
  completion_claim_allowed 由扫描器决定；本脚本不宣布闭合。
.EXAMPLE
  .\Invoke-GrokTaskPackage333ShapeHotPath.ps1
  .\Invoke-GrokTaskPackage333ShapeHotPath.ps1 -AllowEphemeralWorker
  .\Invoke-GrokTaskPackage333ShapeHotPath.ps1 -SkipBusIfShapeHot -Quiet
#>
param(
    [switch]$AllowEphemeralWorker,
    [switch]$RescanGap,
    [switch]$SkipBusIfShapeHot,
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
try { $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
$sRepo = if ($config -and $config.repo_root) { [string]$config.repo_root } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }

$ts = (Get-Date).ToString("o")
$runId = "tp333_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$stateDir = Join-Path $runtime "state\task_package_333_shape_hot"
$stateLatest = Join-Path $stateDir "latest.json"
$zhDir = Join-Path $runtime "readback\zh"
$zhPath = Join-Path $zhDir ("task_package_333_shape_hot_{0}.md" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$zhLatest = Join-Path $zhDir "task_package_333_shape_hot_latest.md"
New-Item -ItemType Directory -Force -Path $stateDir, $zhDir | Out-Null

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 24), $utf8)
}

function Read-JsonSafe([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}

function Test-TcpOpen([int]$Port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $iar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(1500, $false)
        if ($ok) { $c.EndConnect($iar); $c.Close(); return $true }
        $c.Close()
    } catch { }
    return $false
}

function Get-333ShapeGate([object]$Bus) {
    if (-not $Bus) {
        return [ordered]@{
            hot           = $false
            shape_hot     = $false
            passed        = $false
            temporal      = $false
            qwen          = $false
            pro           = $false
            gateway       = $false
            rolling       = $false
            bus_passed    = $false
            detail        = "integrated_bus_v2/latest 缺失"
        }
    }
    $mode = [string]$Bus.invoke_mode
    $checks = $Bus.validation.checks
    $passed = ($Bus.validation.passed -eq $true)
    $temporal = ($mode -match "temporal")
    $qwen = $false
    $pro = $false
    $gateway = $false
    $rolling = $true
    if ($checks) {
        $qwen = ($checks.L3_qwen_draft_worker_lane -eq $true)
        $pro = ($checks.L3_pro_review_after_draft -eq $true)
        $gateway = ($checks.gateway_trace_completion -eq $true) -or ($checks.L3_litellm_completion -eq $true)
        if ($checks.parallel_semantic_documented -eq $true) {
            $rolling = ($checks.rolling_accept_trace -eq $true)
        }
    }
    $shapeHot = ($temporal -and $qwen -and $pro -and $gateway -and $rolling)
    return [ordered]@{
        hot            = $shapeHot
        shape_hot      = $shapeHot
        passed         = $shapeHot
        temporal       = $temporal
        qwen           = $qwen
        pro            = $pro
        gateway        = $gateway
        rolling        = $rolling
        bus_passed     = $passed
        invoke_mode    = $mode
        gate_cn        = "shape_hot=$shapeHot;full_passed=$passed;temporal=$temporal;qwen=$qwen;pro=$pro;gateway=$gateway;rolling=$rolling"
        worker_ownership = [string]$Bus.worker_ownership
    }
}

$actions = [System.Collections.Generic.List[string]]::new()
$refs = [System.Collections.Generic.List[string]]::new()

# --- 桌面三 txt + intent spec 指针 ---
$deskPtr = "C:\Users\xx363\Desktop\合同_默认加动态升级_指针_20260710.txt"
$deskSearch = "C:\Users\xx363\Desktop\后台免费本地搜索_成熟选型与集成_20260710.txt"
$deskLoop = "C:\Users\xx363\Desktop\外部成熟_动态轮回与智能派模_完整形状_20260710.txt"
$intentSpec = Join-Path $runtime "specs\xinao_333_intent_spec_v20260709.md"
foreach ($p in @($deskPtr, $deskSearch, $deskLoop, $intentSpec)) {
    if (Test-Path -LiteralPath $p) { [void]$refs.Add($p) }
}

# --- Step 1: Sync cloud API keys ---
try {
    & (Join-Path $bridge "Invoke-GrokSyncCloudApiKeysToCompose.ps1") -Quiet | Out-Null
    [void]$actions.Add("SyncCloudApiKeys")
} catch {
    [void]$actions.Add("SyncCloudApiKeys:ERROR:$($_.Exception.Message)")
}

# --- Step 2: infra probes ---
$temporalUp = Test-TcpOpen 7233
$daemon = Read-JsonSafe (Join-Path $runtime "state\integrated_bus_worker_daemon\latest.json")
$daemonPolling = ($daemon -and $daemon.status -eq "polling")
$dockerWorkerBlocker = $null
if ($daemonPolling) {
    $logTail = docker logs houtai-gongren --tail 30 2>&1 | Out-String
    if ($logTail -match "ImportError|beartype") {
        $dockerWorkerBlocker = "DOCKER_WORKER_ACTIVITY_IMPORT_BLOCKED"
    }
}

# --- Step 3: run integrated_bus temporal ---
$py = Join-Path $sRepo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { $py = "python" }
$env:XINAO_RESEARCH_RUNTIME = $runtime
if ($AllowEphemeralWorker -or $dockerWorkerBlocker) {
    $env:XINAO_INTEGRATED_BUS_EPHEMERAL_WORKER = "1"
    [void]$actions.Add("integrated_bus_runner --temporal (ephemeral_host; docker_blocker=$dockerWorkerBlocker)")
} else {
    $env:XINAO_INTEGRATED_BUS_EPHEMERAL_WORKER = "0"
    [void]$actions.Add("integrated_bus_runner --temporal (docker_daemon preferred)")
}

$busExit = -1
$busStdout = ""
$busSkipped = $false
$preBus = Read-JsonSafe (Join-Path $runtime "state\integrated_bus_v2\latest.json")
$preGate = Get-333ShapeGate $preBus
if ($SkipBusIfShapeHot -and $preGate.shape_hot) {
    $busSkipped = $true
    $busExit = 0
    $busStdout = "SKIP_BUS: shape_hot already true on integrated_bus_v2/latest"
    [void]$actions.Add($busStdout)
}

elseif ($temporalUp) {
    try {
        Push-Location $sRepo
        $env:PYTHONPATH = $sRepo
        $busStdout = & $py -m services.agent_runtime.integrated_bus_runner --temporal 2>&1 | Out-String
        $busExit = $LASTEXITCODE
        Pop-Location
    } catch {
        Pop-Location -ErrorAction SilentlyContinue
        $busStdout = $_.Exception.Message
        $busExit = 99
    }
} else {
    $busStdout = "TEMPORAL_7233_DOWN"
    [void]$actions.Add("SKIP_BUS: temporal not listening")
}

$busPath = Join-Path $runtime "state\integrated_bus_v2\latest.json"
$bus = Read-JsonSafe $busPath
$gate = Get-333ShapeGate $bus
[void]$refs.Add($busPath)

# --- Step 4: optional gap rescan ---
$gapBefore = Read-JsonSafe (Join-Path $runtime "state\holographic_gap\latest.json")
$hadGap = $false
if ($gapBefore -and $gapBefore.named_gaps) {
    $hadGap = @($gapBefore.named_gaps) -contains "TASK_PACKAGE_333_SHAPE_NOT_HOT"
}
$gapAfter = $gapBefore
if ($RescanGap -or $true) {
    try {
        & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null
        & (Join-Path $bridge "Invoke-GrokFullGapScan.ps1") -Quiet | Out-Null
        $gapAfter = Read-JsonSafe (Join-Path $runtime "state\holographic_gap\latest.json")
        [void]$actions.Add("HolographicGapScan+FullGapScan")
    } catch {
        [void]$actions.Add("GapScan:ERROR:$($_.Exception.Message)")
    }
}
$stillGap = $false
if ($gapAfter -and $gapAfter.named_gaps) {
    $stillGap = @($gapAfter.named_gaps) -contains "TASK_PACKAGE_333_SHAPE_NOT_HOT"
}

$completionAllowed = $false
if ($gapAfter -and $null -ne $gapAfter.completion_claim_allowed) {
    $completionAllowed = ($gapAfter.completion_claim_allowed -eq $true)
}

$payload = [ordered]@{
    schema_version          = "xinao.task_package_333_shape_hot.v1"
    sentinel                = "SENTINEL:TASK_PACKAGE_333_SHAPE_HOT_PATH"
    run_id                  = $runId
    generated_at            = $ts
    intent_spec_ref         = $intentSpec
    desktop_authority_refs  = @($deskPtr, $deskSearch, $deskLoop)
    gap_id                  = "TASK_PACKAGE_333_SHAPE_NOT_HOT"
    actions_executed        = @($actions)
    infra                   = [ordered]@{
        temporal_up         = $temporalUp
        daemon_polling      = $daemonPolling
        docker_worker_blocker = $dockerWorkerBlocker
    }
    bus_runner              = [ordered]@{
        exit_code           = $busExit
        skipped             = $busSkipped
        stdout_tail         = if ($busStdout.Length -gt 2000) { $busStdout.Substring($busStdout.Length - 2000) } else { $busStdout }
    }
    integrated_bus_v2_ref   = [ordered]@{
        path                = $busPath
        validation_passed   = if ($bus -and $bus.validation) { $bus.validation.passed } else { $null }
        validated_at        = if ($bus -and $bus.validation -and $bus.validation.validated_at) {
            if ($bus.validation.validated_at -is [datetime]) { $bus.validation.validated_at.ToUniversalTime().ToString("o") }
            else { [string]$bus.validation.validated_at }
        } else { $null }
        worker_ownership    = if ($bus) { [string]$bus.worker_ownership } else { $null }
    }
    shape_gate              = $gate
    gap_scan                = [ordered]@{
        had_gap_before      = $hadGap
        still_gap_after     = $stillGap
        integrated_bus_v2_hot = if ($gapAfter) { $gapAfter.integrated_bus_v2_hot } else { $null }
        integrated_bus_v2_gate = if ($gapAfter) { [string]$gapAfter.integrated_bus_v2_gate } else { $null }
        completion_claim_allowed = $completionAllowed
    }
    evidence_refs           = @($refs)
    honesty_cn              = if ($gate.hot) {
        "333 七环形状已进入 Temporal bus 热路径（shape_hot 绿 + 千问/Pro/网关/滚动波内）；full_passed=$($gate.bus_passed)；非终局闭合"
    } else {
        "333 形状未达热路径门：$($gate.gate_cn)；禁止假绿"
    }
    completion_claim_allowed = $false
}

Write-JsonFile $stateLatest $payload

$actionLines = [System.Collections.Generic.List[string]]::new()
foreach ($a in $actions) { [void]$actionLines.Add("- $a") }
$zhLines = @(
    "# 333 任务包形状热路径 $runId",
    "",
    "## 缺口（扫描前）",
    "- TASK_PACKAGE_333_SHAPE_NOT_HOT had=$hadGap",
    "- 详情：任务包七环未以 Temporal bus validation 绿+千问/Pro 波内为热路径证据",
    "",
    "## 动作"
) + @($actionLines.ToArray()) + @(
    "",
    "## 形状门（integrated_bus_v2）",
    "- $($gate.gate_cn)",
    "- worker_ownership: $($gate.worker_ownership)",
    "- bus_runner exit: $busExit (skipped=$busSkipped)",
    "",
    "## 扫描后",
    "- still_gap: $stillGap",
    "- integrated_bus_v2_hot: $(if ($gapAfter) { $gapAfter.integrated_bus_v2_hot } else { 'n/a' })",
    "- completion_claim_allowed: $completionAllowed",
    "",
    "## 诚实尺",
    "- $($payload.honesty_cn)",
    "",
    "## 证据",
    "- state: $stateLatest",
    "- bus: $busPath",
    "- gap: $(Join-Path $runtime 'state\holographic_gap\latest.json')"
)
$zhText = ($zhLines -join "`n") + "`n"
[System.IO.File]::WriteAllText($zhPath, $zhText, $utf8)
[System.IO.File]::WriteAllText($zhLatest, $zhText, $utf8)
$payload | Add-Member -NotePropertyName "readback_zh" -NotePropertyValue $zhPath -Force
$payload | Add-Member -NotePropertyName "readback_zh_latest" -NotePropertyValue $zhLatest -Force
Write-JsonFile $stateLatest $payload

if (-not $Quiet) {
    Write-Output ($payload | ConvertTo-Json -Depth 12)
}

if ($gate.hot -and -not $stillGap) { exit 0 }
if ($gate.hot) { exit 2 }
exit 1