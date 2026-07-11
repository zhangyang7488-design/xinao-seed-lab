#Requires -Version 5.1
<#
.SYNOPSIS
  Grok 长久工作流 bootstrap — 能力探活 + 任务队列 + 昨夜报告索引。
#>
param(
    [switch]$SeedDefaultQueue,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8

$bridge = Join-Path $PSScriptRoot "bridge.config.json"
$outDir = "D:\XINAO_RESEARCH_RUNTIME\state\grok_long_workflow"
$latest = Join-Path $outDir "latest.json"
$queuePath = Join-Path $outDir "task_queue.json"
$reportDir = "D:\XINAO_RESEARCH_RUNTIME\readback\zh"
$reportPath = Join-Path $reportDir "grok_overnight_report_latest.md"

New-Item -ItemType Directory -Force -Path $outDir, $reportDir | Out-Null

function Test-Tcp([int]$Port) {
    try {
        $t = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -WarningAction SilentlyContinue
        return [bool]$t.TcpTestSucceeded
    } catch { return $false }
}

function Invoke-HttpStatus([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return [ordered]@{ ok = $true; status = $r.StatusCode }
    } catch {
        return [ordered]@{ ok = $false; error = $_.Exception.Message }
    }
}

$gh = [ordered]@{ ok = $false }
try {
    $gout = gh auth status 2>&1 | Out-String
    $gh.ok = $LASTEXITCODE -eq 0
    $gh.summary = ($gout -split "`n" | Where-Object { $_ -match 'Logged in|account' } | Select-Object -First 2) -join '; '
} catch { $gh.error = $_.Exception.Message }

$docker = [ordered]@{ ok = $false }
try {
    docker info 2>&1 | Out-Null
    $docker.ok = $LASTEXITCODE -eq 0
} catch { $docker.error = $_.Exception.Message }

$capabilities = [ordered]@{
    memory_md     = Test-Path "C:\Users\xx363\.grok\memory\MEMORY.md"
    checkpoint    = Test-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context\latest.json"
    workspace_cfg = Test-Path (Join-Path $PSScriptRoot "..\.grok\config.toml")
    global_cfg    = Test-Path "C:\Users\xx363\.grok\config.toml"
    registry_scan = Test-Path "D:\XINAO_RESEARCH_RUNTIME\state\local_capability_registry\latest.json"
    github_mcp_backup = Test-Path "D:\Grok_一键恢复\workspace\mcps\grok_com_github"
    roi_self_loop     = Test-Path (Join-Path $PSScriptRoot "Invoke-GrokRoiSelfLoopDecide.ps1")
    run_next_script   = Test-Path (Join-Path $PSScriptRoot "Invoke-GrokLongWorkflowRunNext.ps1")
}
# 默认开工路径提示（不强制跑队列；RunNext 空队列自动 ROI→333）
$default_open_path_cn = "窗口干活：.\Invoke-GrokLongWorkflowRunNext.ps1 → 空队列自动 RoiDecide + 333服务波；无需粘贴投递文"

$probes = [ordered]@{
    litellm_20128 = Invoke-HttpStatus "http://127.0.0.1:20128/health"
    ollama_11434  = Invoke-HttpStatus "http://127.0.0.1:11434/api/tags"
    qdrant_6333   = Invoke-HttpStatus "http://127.0.0.1:6333/readyz"
    gh_cli        = $gh
    docker        = $docker
}

# Codex 投递面：deprecated 副尺；不作为 Grok 自身能力 blocker
$config = $null
if (Test-Path -LiteralPath $bridge) {
    $config = Get-Content -LiteralPath $bridge -Raw -Encoding UTF8 | ConvertFrom-Json
}
$ingressDeprecated = $true
if ($config -and $config.PSObject.Properties['ingress_base_url_status']) {
    $ingressDeprecated = ([string]$config.ingress_base_url_status -match 'deprecated')
}
$delivery_probes = [ordered]@{
    ingress_19102_status = if ($ingressDeprecated) { "deprecated_dev_rescue" } else { "legacy" }
    ingress_19102        = if ($ingressDeprecated) { [ordered]@{ ok = $false; skipped = $true; note_cn = "V2 主路不探 19102；显式投递用 -IncludeCodexDelivery" } } else { Invoke-HttpStatus "http://127.0.0.1:19102/health" }
    mcp_19460            = @{ ok = (Test-Tcp 19460) }
    note_cn              = "非 Grok 岛自身闭合条件；见 Get-GrokLocalCapabilityStatus.ps1 -IncludeCodexDelivery"
}

$blockers = @()
if (-not $docker.ok) { $blockers += "DOCKER_DAEMON_NOT_RUNNING" }

if ($SeedDefaultQueue -or -not (Test-Path -LiteralPath $queuePath)) {
    $queue = [ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        tasks          = @(
            [ordered]@{
                id       = "capability_maximize_github_mcp"
                status   = "pending"
                priority = 1
                title_cn = "确认 grok_com_github MCP 可用；搜外部成熟 repo 接缝"
            },
            [ordered]@{
                id       = "registry_scan_hook"
                status   = "pending"
                priority = 2
                title_cn = "跑 Invoke-GrokLocalCapabilityRegistryScan；认领躺尸能力"
            },
            [ordered]@{
                id       = "thin_glue_stack_when_docker"
                status   = "blocked"
                priority = 3
                title_cn = "Docker 绿后 LiteLLM:20128 + thin-provider 探活"
                blocker  = "DOCKER_DAEMON_NOT_RUNNING"
            },
            [ordered]@{
                id       = "tool_glue_constitution_align"
                status   = "in_progress"
                priority = 0
                title_cn = "Grok 岛合同对齐工具胶水宪法；自身工作流已建设"
            }
        )
    }
    ($queue | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $queuePath -Encoding UTF8
}

$queueObj = $null
if (Test-Path -LiteralPath $queuePath) {
    $queueObj = Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
}

$result = [ordered]@{
    schema_version       = "xinao.grok_long_workflow_bootstrap.v1"
    sentinel             = "SENTINEL:GROK_LONG_WORKFLOW_BOOTSTRAP"
    generated_at         = (Get-Date).ToString("o")
    contract_ref         = "grok-admin-bridge/grok_long_workflow_runtime.v1.json"
    capabilities         = $capabilities
    probes               = $probes
    delivery_probes      = $delivery_probes
    named_blockers       = $blockers
    task_queue_ref       = $queuePath
    task_queue           = $queueObj
    overnight_report     = $reportPath
    autonomous_ready     = ($blockers.Count -eq 0)
    scope_cn             = "Grok 岛自身能力；Codex ingress 不算 blocker"
    grok_role_cn         = "大脑+执行者+长久工作流；用户睡时除硬阻塞外全自动"
    default_open_path_cn = $default_open_path_cn
    completion_claim_allowed = $false
}

($result | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $latest -Encoding UTF8

$gapScript = Join-Path $PSScriptRoot "Invoke-GrokFullGapScan.ps1"
if (Test-Path -LiteralPath $gapScript) {
    & $gapScript -Quiet | Out-Null
}

if (-not $Quiet) {
    $result | ConvertTo-Json -Depth 8
}
exit 0