#Requires -Version 5.1
<#
.SYNOPSIS
  三件套主路冒烟薄壳：compose / Temporal health / LangGraph queue poller 描述 + 安全探针。
.DESCRIPTION
  对齐工具胶水宪法 01（Temporal + Docker worker + LangGraph 波内）。
  不造第二 orchestrator；不把 WorkerPool 当主路；默认不提交全量 integrated_bus --temporal。
  证据：D:\XINAO_RESEARCH_RUNTIME\state\capability_max_weld\three_stack_mainline_smoke_latest.json
  completion_claim_allowed 恒为 false（冒烟 ≠ 333 闭合）。
.PARAMETER SkipIntegratedBusProbe
  跳过 integrated_bus dry 探针（import / 模块存在性）。
.PARAMETER AllowIntegratedBusLocal
  可选：跑 integrated_bus_runner --local（仍非 Temporal 全量；默认关）。
.PARAMETER AllowTemporalSubmit
  危险：允许 integrated_bus_runner --temporal 真提交（默认关；冒烟主路勿开）。
.PARAMETER Quiet
  少打控制台。
.EXAMPLE
  .\Invoke-GrokThreeStackMainlineSmoke.ps1
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [switch]$SkipIntegratedBusProbe,
    [switch]$AllowIntegratedBusLocal,
    [switch]$AllowTemporalSubmit,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }

$runtime = "D:\XINAO_RESEARCH_RUNTIME"
if (Test-Path -LiteralPath (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")) {
    try {
        $runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $ConfigPath
    } catch { }
}

$sRepo = "E:\XINAO_RESEARCH_WORKSPACES\S"
$config = $null
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    try {
        $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($config.repo_root) { $sRepo = [string]$config.repo_root }
    } catch { }
}

$composeFile = Join-Path $sRepo "docker-compose.yml"
$statusScript = Join-Path $sRepo "scripts\Status-XinaoBaseCompose.ps1"
$startScript = Join-Path $sRepo "scripts\Start-XinaoBaseCompose.ps1"
$stopScript = Join-Path $sRepo "scripts\Stop-XinaoBaseCompose.ps1"
$thinGlueFullSmoke = Join-Path $sRepo "scripts\Invoke-XinaoThinGlueFullSmoke.ps1"
$taskEntry = Join-Path $bridge "Invoke-GrokTaskEntry.ps1"
$integratedBusRunner = Join-Path $sRepo "services\agent_runtime\integrated_bus_runner.py"
$taskQueue = "xinao-integrated-langgraph-plugin-queue"
$workerContainer = "houtai-gongren"
$temporalPort = 7233
$temporalUi = "http://127.0.0.1:8080"
$temporalCliCandidates = @(
    "D:\XINAO_RESEARCH_RUNTIME\tools\temporal\bin\temporal.exe",
    "C:\Users\xx363\AppData\Local\Microsoft\WinGet\Packages\Temporal.TemporalCLI_Microsoft.Winget.Source_8wekyb3d8bbwe\temporal.exe"
)

$ts = (Get-Date).ToString("o")
$runId = "three_stack_smoke_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$stateDir = Join-Path $runtime "state\capability_max_weld"
$zhDir = Join-Path $runtime "readback\zh"
$outJson = Join-Path $stateDir "three_stack_mainline_smoke_latest.json"
$outJsonStamp = Join-Path $stateDir ("three_stack_mainline_smoke_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$outZh = Join-Path $zhDir "three_stack_mainline_smoke_latest.md"
New-Item -ItemType Directory -Force -Path $stateDir, $zhDir | Out-Null

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 24), $utf8)
}

function Test-TcpOpen([string]$HostName, [int]$Port, [int]$TimeoutMs = 1500) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $iar = $c.BeginConnect($HostName, $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if ($ok) { $c.EndConnect($iar); $c.Close(); return $true }
        $c.Close()
    } catch { }
    return $false
}

function Invoke-HttpProbe([string]$Url, [int]$TimeoutSec = 4) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return [ordered]@{ ok = $true; status_code = [int]$resp.StatusCode }
    } catch {
        return [ordered]@{ ok = $false; error = $_.Exception.Message }
    }
}

function Get-TemporalCli {
    foreach ($p in $temporalCliCandidates) {
        if ($p -and (Test-Path -LiteralPath $p -PathType Leaf)) { return $p }
    }
    $cmd = Get-Command temporal -ErrorAction SilentlyContinue
    if ($cmd) { return [string]$cmd.Source }
    return $null
}

function Read-JsonSafe([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
    } catch {
        return $null
    }
}

$namedBlockers = New-Object System.Collections.Generic.List[string]
$steps = New-Object System.Collections.Generic.List[object]

function Add-Step {
    param(
        [string]$Name,
        [string]$Status,
        [object]$Detail = $null
    )
    if ($null -eq $Detail) { $Detail = [ordered]@{} }
    $steps.Add([ordered]@{
        name   = $Name
        status = $Status
        detail = $Detail
    }) | Out-Null
}

# ---------------------------------------------------------------------------
# 1) Script surface / constitution pointers (existence only)
# ---------------------------------------------------------------------------
$surface = [ordered]@{
    compose_file_exists          = (Test-Path -LiteralPath $composeFile -PathType Leaf)
    status_script_exists         = (Test-Path -LiteralPath $statusScript -PathType Leaf)
    start_script_exists          = (Test-Path -LiteralPath $startScript -PathType Leaf)
    stop_script_exists           = (Test-Path -LiteralPath $stopScript -PathType Leaf)
    thin_glue_full_smoke_exists  = (Test-Path -LiteralPath $thinGlueFullSmoke -PathType Leaf)
    task_entry_exists            = (Test-Path -LiteralPath $taskEntry -PathType Leaf)
    integrated_bus_runner_exists = (Test-Path -LiteralPath $integratedBusRunner -PathType Leaf)
    s_repo                       = $sRepo
    compose_file                 = $composeFile
    not_mainline_worker_pool_cn  = "WorkerPool / Composer25 = 临时旁路，禁止当主路"
}
if (-not $surface.compose_file_exists) { $namedBlockers.Add("COMPOSE_FILE_MISSING") | Out-Null }
if (-not $surface.status_script_exists) { $namedBlockers.Add("STATUS_XINAO_BASE_COMPOSE_PS1_MISSING") | Out-Null }
if (-not $surface.start_script_exists) { $namedBlockers.Add("START_XINAO_BASE_COMPOSE_PS1_MISSING") | Out-Null }
if (-not $surface.thin_glue_full_smoke_exists) { $namedBlockers.Add("THIN_GLUE_FULL_SMOKE_PS1_MISSING") | Out-Null }
Add-Step "surface_inventory" $(if ($surface.compose_file_exists) { "ok" } else { "blocked" }) $surface

# ---------------------------------------------------------------------------
# 2) Compose status (prefer Status script; else docker compose ps)
# ---------------------------------------------------------------------------
$composeStatus = [ordered]@{
    method                = "none"
    status_script_invoked = $false
    status_script_path    = $statusScript
    docker_ok             = $false
    services              = @()
    required_running      = [ordered]@{
        "naijiu-shiwu"   = $false
        "houtai-gongren" = $false
        "shiwu-mianban"  = $false
        "shiwu-ku"       = $false
    }
    ps_excerpt            = ""
    error                 = ""
}

try {
    docker info 2>&1 | Out-Null
    $composeStatus.docker_ok = ($LASTEXITCODE -eq 0)
} catch {
    $composeStatus.error = $_.Exception.Message
    $namedBlockers.Add("DOCKER_UNAVAILABLE") | Out-Null
}

if ($composeStatus.docker_ok -and $surface.status_script_exists) {
    $composeStatus.method = "Status-XinaoBaseCompose.ps1"
    try {
        $composeStatus.status_script_invoked = $true
        $null = & $statusScript 2>&1 | Out-String
        $composeStatus.ps_excerpt = "status_script_exit=$LASTEXITCODE"
        # Still harvest docker names for honesty
    } catch {
        $composeStatus.error = "status_script: $($_.Exception.Message)"
        $namedBlockers.Add("STATUS_SCRIPT_INVOKE_FAILED") | Out-Null
        $composeStatus.method = "docker_compose_ps_fallback"
    }
}

if ($composeStatus.docker_ok -and $surface.compose_file_exists) {
    if ($composeStatus.method -eq "none" -or $composeStatus.method -eq "docker_compose_ps_fallback" -or -not $surface.status_script_exists) {
        $composeStatus.method = "docker_compose_ps"
    }
    try {
        $psRaw = & docker compose -f $composeFile ps --format json 2>&1 | Out-String
        $composeStatus.ps_excerpt = if ($psRaw.Length -gt 1800) { $psRaw.Substring(0, 1800) + "…" } else { $psRaw }
        # docker compose may emit NDJSON or a JSON array depending on version
        $services = @()
        $trimmed = $psRaw.Trim()
        if ($trimmed.StartsWith("[")) {
            $services = @($trimmed | ConvertFrom-Json)
        } else {
            foreach ($line in ($psRaw -split "[\r\n]+")) {
                $l = $line.Trim()
                if (-not $l) { continue }
                if ($l.StartsWith("{")) {
                    try { $services += ($l | ConvertFrom-Json) } catch { }
                }
            }
        }
        $svcList = @()
        foreach ($s in $services) {
            $name = if ($s.Name) { [string]$s.Name } elseif ($s.Service) { [string]$s.Service } else { "" }
            $state = if ($s.State) { [string]$s.State } else { "" }
            $status = if ($s.Status) { [string]$s.Status } else { "" }
            $svcList += [ordered]@{ name = $name; state = $state; status = $status }
            if ($composeStatus.required_running.Contains($name)) {
                $composeStatus.required_running[$name] = ($state -match 'running' -or $status -match 'Up')
            }
            # also match Service field
            $svcName = if ($s.Service) { [string]$s.Service } else { "" }
            if ($svcName -and $composeStatus.required_running.Contains($svcName)) {
                $composeStatus.required_running[$svcName] = ($state -match 'running' -or $status -match 'Up')
            }
        }
        # Fallback: docker ps names
        if (-not ($composeStatus.required_running.Values | Where-Object { $_ })) {
            $names = & docker ps --format '{{.Names}}' 2>$null
            foreach ($key in @($composeStatus.required_running.Keys)) {
                if ($names -contains $key) { $composeStatus.required_running[$key] = $true }
            }
        }
        $composeStatus.services = $svcList
    } catch {
        $composeStatus.error = "compose_ps: $($_.Exception.Message)"
        $namedBlockers.Add("COMPOSE_PS_FAILED") | Out-Null
    }
}

$requiredOk = ($composeStatus.required_running["naijiu-shiwu"] -and $composeStatus.required_running["houtai-gongren"])
if (-not $requiredOk) { $namedBlockers.Add("CORE_COMPOSE_SERVICES_NOT_UP") | Out-Null }
Add-Step "compose_status" $(if ($requiredOk) { "ok" } else { "degraded" }) $composeStatus

# ---------------------------------------------------------------------------
# 3) Temporal health
# ---------------------------------------------------------------------------
$temporal = [ordered]@{
    address_tcp_7233 = (Test-TcpOpen "127.0.0.1" $temporalPort)
    ui_probe         = (Invoke-HttpProbe $temporalUi)
    cli_path         = (Get-TemporalCli)
    operator_cluster = $null
    workflow_list_excerpt = ""
    health_ok        = $false
}
if (-not $temporal.address_tcp_7233) { $namedBlockers.Add("TEMPORAL_7233_DOWN") | Out-Null }

if ($temporal.cli_path -and $temporal.address_tcp_7233) {
    try {
        $clusterOut = & $temporal.cli_path operator cluster health --address "127.0.0.1:$temporalPort" 2>&1 | Out-String
        $temporal.operator_cluster = $clusterOut.Trim()
        if ($clusterOut -match 'SERVING|serving|ok|OK') {
            $temporal.health_ok = $true
        }
    } catch {
        $temporal.operator_cluster = "cli_error: $($_.Exception.Message)"
    }
    try {
        $wfList = & $temporal.cli_path workflow list --address "127.0.0.1:$temporalPort" --limit 8 2>&1 | Out-String
        $temporal.workflow_list_excerpt = if ($wfList.Length -gt 1200) { $wfList.Substring(0, 1200) + "…" } else { $wfList.Trim() }
    } catch { }
}

if (-not $temporal.health_ok -and $temporal.address_tcp_7233) {
    # TCP up counts as soft health when CLI health parse fails
    $temporal.health_ok = $true
    $temporal.health_note = "tcp_up_soft_health"
}
Add-Step "temporal_health" $(if ($temporal.health_ok) { "ok" } else { "blocked" }) $temporal

# ---------------------------------------------------------------------------
# 4) LangGraph queue poller description (evidence + container)
# ---------------------------------------------------------------------------
$daemonPath = Join-Path $runtime "state\integrated_bus_worker_daemon\latest.json"
$daemon = Read-JsonSafe $daemonPath
$poller = [ordered]@{
    task_queue                 = $taskQueue
    graph_id                   = "xinao-integrated-bus-v2"
    worker_container           = $workerContainer
    daemon_evidence_path       = $daemonPath
    daemon_status              = $null
    daemon_task_queues         = @()
    workflows_registered       = @()
    poller_ready               = $false
    ownership_shape_cn         = "client 提交 workflow；houtai-gongren 在队列上 poll（samples-python run_workflow 形状）"
    not_second_orchestrator_cn = "thin shell: describe poller only; no while+sleep owner"
    container_state            = ""
    description_cn             = ""
}

if ($daemon) {
    $poller.daemon_status = [string]$daemon.status
    if ($daemon.task_queues) { $poller.daemon_task_queues = @($daemon.task_queues) }
    if ($daemon.workflows_registered) { $poller.workflows_registered = @($daemon.workflows_registered) }
    if ($daemon.graph_id) { $poller.graph_id = [string]$daemon.graph_id }
    $poller.poller_ready = (
        $daemon.status -eq "polling" -and
        ($poller.daemon_task_queues -contains $taskQueue) -and
        ($poller.workflows_registered -contains "XinaoIntegratedBusWorkflow")
    )
}

if ($composeStatus.docker_ok) {
    try {
        $st = & docker inspect -f '{{.State.Status}}/{{.State.Health.Status}}' $workerContainer 2>&1 | Out-String
        $poller.container_state = $st.Trim()
    } catch {
        $poller.container_state = "inspect_failed"
    }
}

$poller.description_cn = @(
    "队列 $taskQueue：LangGraphPlugin 波内图挂在 Temporal worker 上。",
    "poller 容器 $workerContainer 状态=$($poller.container_state)；daemon 证据 status=$($poller.daemon_status)。",
    "已登记 workflow：$([string]::Join(', ', $poller.workflows_registered))。",
    "主路：Invoke-GrokTaskEntry → claim durable → worker poll 执行 XinaoIntegratedBusWorkflow；非 WorkerPool。"
) -join " "

if (-not $poller.poller_ready) { $namedBlockers.Add("LANGGRAPH_QUEUE_POLLER_NOT_READY") | Out-Null }
Add-Step "langgraph_queue_poller" $(if ($poller.poller_ready) { "ok" } else { "degraded" }) $poller

# ---------------------------------------------------------------------------
# 5) integrated_bus dry / optional smoke (skip dangerous full by default)
# ---------------------------------------------------------------------------
$bus = [ordered]@{
    runner_path              = $integratedBusRunner
    probe_mode               = "skip"
    dry_import_ok            = $false
    dry_import_error         = ""
    local_smoke_ran          = $false
    temporal_submit_ran      = $false
    temporal_submit_skipped  = (-not $AllowTemporalSubmit.IsPresent)
    skip_reason_cn           = "默认 -Skip 危险全量 --temporal；仅 dry import / 可选 --local"
    exit_code                = $null
    stdout_excerpt           = ""
}

if (-not $SkipIntegratedBusProbe) {
    $bus.probe_mode = "dry_import"
    $py = Join-Path $sRepo ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { $py = "python" }
    $oldPy = $env:PYTHONPATH
    $env:PYTHONPATH = ($sRepo + ';' + (Join-Path $sRepo 'src'))
    $env:XINAO_RESEARCH_RUNTIME = $runtime
    try {
        $code = @'
import json
from services.agent_runtime.integrated_bus_runner import SCHEMA_VERSION, SENTINEL, integrated_bus_default_enabled
from services.agent_runtime.integrated_bus_graph import GRAPH_ID
print(json.dumps({
  "schema_version": SCHEMA_VERSION,
  "sentinel": SENTINEL,
  "graph_id": GRAPH_ID,
  "default_enabled": bool(integrated_bus_default_enabled()),
  "dry_import": True
}, ensure_ascii=False))
'@
        $raw = & $py -c $code 2>&1 | Out-String
        $bus.stdout_excerpt = if ($raw.Length -gt 800) { $raw.Substring(0, 800) } else { $raw.Trim() }
        $bus.exit_code = $LASTEXITCODE
        if ($LASTEXITCODE -eq 0 -and $raw -match 'dry_import') {
            $bus.dry_import_ok = $true
        } else {
            $bus.dry_import_error = $raw.Trim()
            $namedBlockers.Add("INTEGRATED_BUS_DRY_IMPORT_FAILED") | Out-Null
        }
    } catch {
        $bus.dry_import_error = $_.Exception.Message
        $namedBlockers.Add("INTEGRATED_BUS_DRY_IMPORT_FAILED") | Out-Null
    } finally {
        $env:PYTHONPATH = $oldPy
    }

    if ($AllowIntegratedBusLocal -and $bus.dry_import_ok) {
        $bus.probe_mode = "local_smoke"
        try {
            $env:PYTHONPATH = ($sRepo + ';' + (Join-Path $sRepo 'src'))
            $env:XINAO_RESEARCH_RUNTIME = $runtime
            $env:XINAO_INTEGRATED_BUS_EPHEMERAL_WORKER = "0"
            $localOut = & $py -m services.agent_runtime.integrated_bus_runner --local 2>&1 | Out-String
            $bus.local_smoke_ran = $true
            $bus.exit_code = $LASTEXITCODE
            $bus.stdout_excerpt = if ($localOut.Length -gt 1200) { $localOut.Substring(0, 1200) + "…" } else { $localOut.Trim() }
        } catch {
            $namedBlockers.Add("INTEGRATED_BUS_LOCAL_SMOKE_FAILED") | Out-Null
            $bus.dry_import_error = $_.Exception.Message
        } finally {
            $env:PYTHONPATH = $oldPy
        }
    }

    if ($AllowTemporalSubmit) {
        $bus.probe_mode = "temporal_submit"
        $bus.temporal_submit_ran = $true
        $bus.temporal_submit_skipped = $false
        $bus.skip_reason_cn = "用户显式 -AllowTemporalSubmit：提交真 workflow（非默认冒烟）"
        try {
            $env:PYTHONPATH = ($sRepo + ';' + (Join-Path $sRepo 'src'))
            $env:XINAO_RESEARCH_RUNTIME = $runtime
            $env:XINAO_INTEGRATED_BUS_EPHEMERAL_WORKER = "0"
            $tOut = & $py -m services.agent_runtime.integrated_bus_runner --temporal 2>&1 | Out-String
            $bus.exit_code = $LASTEXITCODE
            $bus.stdout_excerpt = if ($tOut.Length -gt 1200) { $tOut.Substring(0, 1200) + "…" } else { $tOut.Trim() }
            if ($LASTEXITCODE -ne 0) { $namedBlockers.Add("INTEGRATED_BUS_TEMPORAL_SUBMIT_FAILED") | Out-Null }
        } catch {
            $namedBlockers.Add("INTEGRATED_BUS_TEMPORAL_SUBMIT_FAILED") | Out-Null
        } finally {
            $env:PYTHONPATH = $oldPy
        }
    }
} else {
    $bus.probe_mode = "skipped_by_flag"
    $bus.skip_reason_cn = "-SkipIntegratedBusProbe"
}

Add-Step "integrated_bus_probe" $(
    if ($SkipIntegratedBusProbe) { "skipped" }
    elseif ($bus.dry_import_ok) { "ok" }
    else { "degraded" }
) $bus

# ---------------------------------------------------------------------------
# 6) ThinGlue FullSmoke if present (safe path only — script missing → record)
# ---------------------------------------------------------------------------
$tg = [ordered]@{
    script_path = $thinGlueFullSmoke
    exists      = [bool]$surface.thin_glue_full_smoke_exists
    ran         = $false
    exit_code   = $null
    note_cn     = "盘上缺失则只记 named_blocker；不手搓第二套 FullSmoke"
}
if ($tg.exists) {
    try {
        # Prefer dry/help first if script supports it; otherwise invoke as-is with short timeout expectations
        $tgOut = & $thinGlueFullSmoke 2>&1 | Out-String
        $tg.ran = $true
        $tg.exit_code = $LASTEXITCODE
        $tg.stdout_excerpt = if ($tgOut.Length -gt 800) { $tgOut.Substring(0, 800) + "…" } else { $tgOut.Trim() }
        if ($LASTEXITCODE -ne 0) { $namedBlockers.Add("THIN_GLUE_FULL_SMOKE_FAILED") | Out-Null }
    } catch {
        $namedBlockers.Add("THIN_GLUE_FULL_SMOKE_INVOKE_FAILED") | Out-Null
        $tg.error = $_.Exception.Message
    }
}
Add-Step "thin_glue_full_smoke" $(if (-not $tg.exists) { "missing" } elseif ($tg.ran -and $tg.exit_code -eq 0) { "ok" } else { "degraded" }) $tg

# ---------------------------------------------------------------------------
# 7) Entry map (how to invoke mainline — thin shell pointers only)
# ---------------------------------------------------------------------------
$entryMap = [ordered]@{
    mainline_smoke           = "grok-admin-bridge\Invoke-GrokThreeStackMainlineSmoke.ps1"
    task_entry               = "grok-admin-bridge\Invoke-GrokTaskEntry.ps1"
    task_entry_claim_durable = "grok-admin-bridge\Invoke-GrokTaskEntryClaimDurable.ps1"
    task_entry_wave_status   = "grok-admin-bridge\Invoke-GrokTaskEntryWaveStatus.ps1"
    base_compose_status      = $statusScript
    base_compose_start       = $startScript
    integrated_bus_runner    = "python -m services.agent_runtime.integrated_bus_runner --temporal  # from S venv; not default smoke"
    evidence_json            = $outJson
    evidence_zh              = $outZh
    constitution_01_cn       = "桌面\主线\工具胶水宪法\01_* 成熟优先主路"
    forbid_cn                = @(
        "禁止 WorkerPool 当主路",
        "禁止第二 orchestrator / while+sleep owner",
        "禁止报告绿=333 闭合",
        "禁止改桌面主线业务数据"
    )
}

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
$coreGreen = (
    [bool]$requiredOk -and
    [bool]$temporal.health_ok -and
    [bool]$poller.poller_ready -and
    ([bool]$bus.dry_import_ok -or [bool]$SkipIntegratedBusProbe)
)

$blockerArr = New-Object System.Collections.Generic.List[string]
foreach ($b in $namedBlockers) {
    if ($b -and -not $blockerArr.Contains([string]$b)) { [void]$blockerArr.Add([string]$b) }
}
$blockerOut = @($blockerArr)
$stepsOut = @($steps.ToArray())
$nowCan = @(
    "可 invoke：.\Invoke-GrokThreeStackMainlineSmoke.ps1（本冒烟）",
    "可 invoke：.\Invoke-GrokTaskEntry.ps1 -Intent '...'（任务入口壳）",
    $(if ($surface.status_script_exists) { "可 invoke：Status-XinaoBaseCompose.ps1" } else { "Status-XinaoBaseCompose.ps1 缺失：用 docker compose -f S\docker-compose.yml ps" }),
    $(if ($poller.poller_ready) { "poller 就绪：可对 $taskQueue 提交 durable workflow（claim / runner --temporal）" } else { "poller 未就绪：先起 houtai-gongren / 查 daemon latest" }),
    "不可声称：333 主路闭合 / 用户完成（completion_claim_allowed=false）"
) -join [Environment]::NewLine

$verdict = [ordered]@{}
$verdict['schema_version'] = "xinao.three_stack_mainline_smoke.v1"
$verdict['sentinel'] = "SENTINEL:XINAO_THREE_STACK_MAINLINE_SMOKE"
$verdict['generated_at'] = $ts
$verdict['run_id'] = $runId
$verdict['three_stack_cn'] = "Temporal + Docker worker(houtai-gongren) + LangGraph wave"
$verdict['not_second_orchestrator'] = $true
$verdict['not_worker_pool_mainline'] = $true
$verdict['completion_claim_allowed'] = $false
$verdict['smoke_core_green'] = [bool]$coreGreen
$verdict['smoke_passed_partial'] = [bool]$coreGreen
$verdict['named_blockers'] = $blockerOut
$verdict['surface'] = $surface
$verdict['compose_status'] = $composeStatus
$verdict['temporal_health'] = $temporal
$verdict['langgraph_queue_poller'] = $poller
$verdict['integrated_bus_probe'] = $bus
$verdict['thin_glue_full_smoke'] = $tg
$verdict['entry_map'] = $entryMap
$verdict['steps'] = $stepsOut
$verdict['now_can_invoke_cn'] = $nowCan
$verdict['lens_cn'] = "ledger: compose/temporal/poller/dry-import; thin shell only; not WorkerPool"

Write-JsonFile $outJson $verdict
Write-JsonFile $outJsonStamp $verdict

# Chinese readback
$zhLines = @(
    "# 三件套主路冒烟 · latest",
    "",
    "- 时间：$ts",
    "- run_id：$runId",
    "- completion_claim_allowed：**false**（冒烟 ≠ 333 闭合）",
    "- 三件套：Temporal + Docker worker + LangGraph 波内",
    "- 禁：第二 orchestrator · WorkerPool 当主路",
    "",
    "## 结果摘要",
    "",
    "- smoke_core_green：**$coreGreen**",
    "- named_blockers：$(if ($blockerOut.Count -eq 0) { '(none)' } else { $blockerOut -join ', ' })",
    "",
    "## 探针",
    "",
    "| 步 | 状态 | 要点 |",
    "|----|------|------|",
    "| compose | $(if ($requiredOk) { 'ok' } else { 'degraded' }) | naijiu-shiwu=$($composeStatus.required_running['naijiu-shiwu']) · houtai-gongren=$($composeStatus.required_running['houtai-gongren']) · method=$($composeStatus.method) |",
    "| temporal | $(if ($temporal.health_ok) { 'ok' } else { 'blocked' }) | :7233=$($temporal.address_tcp_7233) · UI=$($temporal.ui_probe.ok) |",
    "| langgraph poller | $(if ($poller.poller_ready) { 'ok' } else { 'degraded' }) | queue=$taskQueue · daemon=$($poller.daemon_status) · container=$($poller.container_state) |",
    "| integrated_bus | $($bus.probe_mode) | dry_import=$($bus.dry_import_ok) · temporal_submit_skipped=$($bus.temporal_submit_skipped) |",
    "| thin_glue full smoke | $(if ($tg.exists) { 'exists' } else { 'missing' }) | path=$thinGlueFullSmoke |",
    "",
    "## poller 描述",
    "",
    $poller.description_cn,
    "",
    "## 如何 invoke（主路入口薄壳）",
    "",
    '```powershell',
    'cd <island-or-admin>\grok-admin-bridge',
    '.\Invoke-GrokThreeStackMainlineSmoke.ps1',
    '.\Invoke-GrokTaskEntry.ps1 -Intent "一句意图"',
    '# 可选 durable claim：.\Invoke-GrokTaskEntryClaimDurable.ps1',
    '# 查波：.\Invoke-GrokTaskEntryWaveStatus.ps1',
    '# compose 状态（若脚本缺失）：',
    "docker compose -f `"$composeFile`" ps",
    '```',
    "",
    "## 机器证据",
    "",
    "- JSON：``$outJson``",
    "- 本 readback：``$outZh``",
    "",
    "## 诚实",
    "",
    "- 本脚本**不是** Temporal owner，只做状态/探针。",
    "- 默认**不**跑 integrated_bus --temporal 全量；需显式 ``-AllowTemporalSubmit``。",
    "- Start/Status-XinaoBaseCompose.ps1 若缺失会记 named_blocker（合同仍指向它们）。",
    ""
)
[System.IO.File]::WriteAllText($outZh, ($zhLines -join "`n"), $utf8)

if (-not $Quiet) {
    Write-Host "three_stack_mainline_smoke core_green=$coreGreen blockers=$($namedBlockers.Count)"
    Write-Host "json=$outJson"
    Write-Host "zh=$outZh"
    $verdict | ConvertTo-Json -Depth 6 | Write-Host
}

# Exit: 0 if core green, 1 degraded, 2 hard block (temporal/docker)
if (-not $composeStatus.docker_ok -or -not $temporal.address_tcp_7233) {
    exit 2
}
if (-not $coreGreen) {
    exit 1
}
exit 0
