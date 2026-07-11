#Requires -Version 5.1
<#
.SYNOPSIS
  Claim Codex S Hardmode capabilities onto Grok 4.5 surface (config + invoke hints).
  Does NOT claim 333 ownership. Does NOT mount xinao-memory (Qdrant multi-stdio lock).
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Status,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8

$bridge = $PSScriptRoot
$runtime = "D:\XINAO_RESEARCH_RUNTIME"
$stateRoot = Join-Path $runtime "state\grok_codex_s_capability_surface"
$latestPath = Join-Path $stateRoot "latest.json"
New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null

$laneConfig = "C:\Users\xx363\.grok-4.5-lane\config.toml"
$islandConfig = "C:\Users\xx363\Grok_Admin_Isolated\workspace-grok-4.5-island\.grok\config.toml"
$sSnapshot = Join-Path $runtime "state\Codex_Situation_Island\state\capability_snapshot.json"
$sHardmodeLnk = "C:\Users\xx363\Desktop\OPEN CODEX S HARDMODE.lnk"
$sLight = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\hardmode\Invoke-CodexSLightResearchLoop.ps1"
$sWorker = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\hardmode\Invoke-CodexSWorkerLane.ps1"
$grokWorker = Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1"
$grokLight = Join-Path $bridge "Invoke-GrokCodexSLightResearchLoop.ps1"

function Test-ConfigHas([string]$Path, [string]$Needle) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    return [bool](Select-String -LiteralPath $Path -Pattern $Needle -Quiet)
}

$mcpClaims = @(
    @{ id = "windows";             mount = $true;  role = "desktop_ui"; note = "already shared" }
    @{ id = "xinao_stdio";         mount = $true;  role = "xinao_tools"; note = "stdio replace HTTP:19460" }
    @{ id = "codebase-memory";     mount = $true;  role = "repo_semantic"; note = "CBM cache grok45 separate from S" }
    @{ id = "chrome-devtools";     mount = $true;  role = "browser_debug"; note = "S hardmode same binary" }
    @{ id = "openaiDeveloperDocs"; mount = $true;  role = "openai_docs"; note = "HTTP MCP" }
    @{ id = "filesystem";          mount = $true;  role = "fs_roots"; note = "D/E/island roots" }
    @{ id = "fetch";               mount = $true;  role = "http_fetch"; note = "standard MCP" }
    @{ id = "mcp_memory";          mount = $true;  role = "graph_memory"; note = "NOT mem0 path" }
    @{ id = "xinao-memory";        mount = $false; role = "mem0_qdrant"; note = "SKIP: multi stdio → embedded Qdrant .lock; claim only" }
    @{ id = "codex_plugins_40";    mount = $false; role = "codex_native"; note = "SKIP: Codex runtime plugins not portable to Grok" }
    @{ id = "root_intent_loop";    mount = $false; role = "333_owner"; note = "SKIP: not Grok ownership" }
)

$invokeClaims = @(
    @{ id = "direct_worker_lane"; script = $grokWorker; s_src = $sWorker; note = "Qwen/DP single lane" }
    @{ id = "light_research_loop"; script = $grokLight; s_src = $sLight; note = "foreground research not 333" }
)

$configChecks = [ordered]@{
    lane_config   = $laneConfig
    lane_ok       = (Test-Path $laneConfig)
    island_config = $islandConfig
    island_ok     = (Test-Path $islandConfig)
    lane_has_xinao_stdio      = Test-ConfigHas $laneConfig 'xinao_mcp_server\.py'
    lane_has_codebase_memory  = Test-ConfigHas $laneConfig 'codebase-memory'
    lane_has_chrome_devtools  = Test-ConfigHas $laneConfig 'chrome-devtools'
    lane_has_openai_docs      = Test-ConfigHas $laneConfig 'openaiDeveloperDocs'
    lane_skips_xinao_memory   = -not (Test-ConfigHas $laneConfig 'xinao_memory_mcp_server')
    island_has_xinao_stdio    = Test-ConfigHas $islandConfig 'xinao_mcp_server\.py'
    island_has_codebase_memory = Test-ConfigHas $islandConfig 'codebase-memory'
    island_has_chrome_devtools = Test-ConfigHas $islandConfig 'chrome-devtools'
}

$bins = [ordered]@{
    windows_mcp      = Test-Path "D:\XINAO_RESEARCH_RUNTIME\tools\windows-mcp\Sbroenne.WindowsMcp.exe"
    codebase_memory  = Test-Path "D:\XINAO_RESEARCH_RUNTIME\tools\codebase-memory-mcp\codebase-memory-mcp.exe"
    s_python         = Test-Path "E:\XINAO_RESEARCH_WORKSPACES\S\.venv\Scripts\python.exe"
    xinao_mcp_py     = Test-Path "E:\XINAO_RESEARCH_WORKSPACES\S\services\mcp\xinao_mcp_server.py"
    chrome_devtools  = [bool](Get-Command chrome-devtools-mcp -EA SilentlyContinue)
    s_light_script   = Test-Path $sLight
    grok_light       = Test-Path $grokLight
    grok_worker      = Test-Path $grokWorker
    s_capability_snap = Test-Path $sSnapshot
    hardmode_lnk     = Test-Path $sHardmodeLnk
    mem0_qdrant_lock = Test-Path "D:\XINAO_RESEARCH_RUNTIME\state\mem0\qdrant\.lock"
}

# count concurrent memory-ish stdio (informational)
$memProcs = @(Get-CimInstance Win32_Process -EA SilentlyContinue | Where-Object {
        $_.CommandLine -match 'xinao_memory_mcp_server|codebase-memory-mcp|server-memory'
    })
$binProbe = [ordered]@{
    memory_related_process_count = $memProcs.Count
    xinao_memory_process_count   = @($memProcs | Where-Object { $_.CommandLine -match 'xinao_memory' }).Count
    codebase_memory_process_count = @($memProcs | Where-Object { $_.CommandLine -match 'codebase-memory' }).Count
}

$result = [ordered]@{
    schema_version           = "xinao.grok_codex_s_capability_surface_claim.v1"
    sentinel                 = "SENTINEL:GROK_CODEX_S_CAPABILITY_SURFACE"
    generated_at             = (Get-Date).ToString("o")
    source_ref               = $sHardmodeLnk
    s_capability_snapshot    = $sSnapshot
    not_333_mainline         = $true
    completion_claim_allowed = $false
    policy_cn                = "挂 S 对 Grok 有用的 MCP/脚本；不抢 333；不挂 xinao-memory 避免 mem0 Qdrant 多进程锁"
    mcp_claims               = $mcpClaims
    invoke_claims            = @(
        foreach ($i in $invokeClaims) {
            [ordered]@{
                id        = $i.id
                script    = $i.script
                script_ok = (Test-Path $i.script)
                s_src     = $i.s_src
                s_src_ok  = (Test-Path $i.s_src)
                note      = $i.note
            }
        }
    )
    config_checks            = $configChecks
    binary_probes            = $bins
    process_probe            = $binProbe
    now_can_invoke           = @(
        "Invoke-GrokCodexSDirectWorkerLane.ps1 -Mode draft -Provider auto -Objective '...' -InputText '...'",
        "Invoke-GrokCodexSLightResearchLoop.ps1 -Mode local_only -Objective '...' -LocalQuery '...'",
        "Invoke-GrokCodexSCapabilitySurfaceClaim.ps1 -Status",
        "MCP (restart Grok session): xinao stdio, windows, codebase-memory, chrome-devtools, openaiDeveloperDocs, filesystem, fetch, mcp_memory"
    )
    not_done_cn = @(
        "本会话 MCP 需重开 Grok 4.5 窗口才握手新配置",
        "xinao-memory 故意不挂；等跨进程 open/close 或单例 Qdrant server",
        "Codex 40 plugins / browser_use / computer_use 非 Grok 可移植",
        "挂能力 ≠ P0/333 闭合"
    )
    honesty_cn = "能力面 claim + 配置已写；completion_claim_allowed=false"
}

if ($Apply -or $Status -or -not $Apply) {
    [System.IO.File]::WriteAllText($latestPath, ($result | ConvertTo-Json -Depth 12), $utf8)
    if (-not $Quiet) { $result | ConvertTo-Json -Depth 12 }
}
exit 0
