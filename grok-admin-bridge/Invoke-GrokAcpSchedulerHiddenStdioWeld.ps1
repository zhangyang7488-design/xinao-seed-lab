#Requires -Version 5.1
<#
.SYNOPSIS
  Thin endpoint weld for ACP, hidden stdio, and shell_terminal capability deny.
.DESCRIPTION
  The legacy filename is retained for callers, but scheduler_tick and resident
  WorkerPool orchestration are retired. The canonical model-worker route is
  Temporal + Docker houtai-gongren + worker-internal LangGraph with dynamic workers.
.EXAMPLE
  .\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action TerminalCapability
  .\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action HiddenStdio
  .\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action Weld
#>
param(
    [ValidateSet("Inventory", "Smoke", "Acp", "HiddenStdio", "TerminalCapability", "Weld")]
    [string]$Action = "Weld",
    [ValidateSet("ensure", "submit", "run", "status", "cancel", "history", "close", "raw")]
    [string]$AcpAction = "status",
    [string]$Session = "xinao-main",
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$DualBrainRoot = "E:\XINAO_RESEARCH_WORKSPACES\S\projects\dual-brain-coordination",
    [string]$HiddenStdioCurrent = "D:\XINAO_RESEARCH_RUNTIME\tools\hidden-stdio\current.json",
    [switch]$Quiet
)

Set-StrictMode -Version 2
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = "D:\XINAO_RESEARCH_RUNTIME"
$stateDir = Join-Path $runtime "state\capability_max_weld"
$zhDir = Join-Path $runtime "readback\zh"
$evidencePath = Join-Path $stateDir "weld_acp_hidden_stdio.json"
$zhPath = Join-Path $zhDir "weld_acp_hidden_stdio_latest.md"
$acpAdapter = Join-Path $DualBrainRoot "adapters\grok\Invoke-XinaoGrokAcp.ps1"
$terminalCap = Join-Path $bridge "Invoke-GrokAcpxTerminalCapabilityEnforce.ps1"

function Get-HiddenStdioInfo {
    $info = [ordered]@{
        current_json = $HiddenStdioCurrent
        current_json_exists = (Test-Path -LiteralPath $HiddenStdioCurrent -PathType Leaf)
        launcher_path = $null
        generation_id = $null
        child_creation_flag = $null
        binary_exists = $false
    }
    if ($info.current_json_exists) {
        $current = Get-Content -LiteralPath $HiddenStdioCurrent -Raw -Encoding UTF8 | ConvertFrom-Json
        $info.launcher_path = [string]$current.launcher_path
        $info.generation_id = [string]$current.generation_id
        $info.child_creation_flag = [string]$current.child_creation_flag
        if ($info.launcher_path) {
            $info.binary_exists = Test-Path -LiteralPath $info.launcher_path -PathType Leaf
        }
    }
    return $info
}

function Invoke-TerminalCapabilityEnforce {
    $result = [ordered]@{
        ok = $false
        script = $terminalCap
        present = (Test-Path -LiteralPath $terminalCap -PathType Leaf)
        required_csv = "run_terminal_cmd,run_terminal_command"
        exit_code = $null
        error = $null
    }
    if (-not $result.present) {
        $result.error = "TERMINAL_CAPABILITY_SCRIPT_MISSING"
        return $result
    }
    try {
        & $terminalCap -Action Enforce -DualBrainRoot $DualBrainRoot -Quiet
        $result.exit_code = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
        $result.ok = ($result.exit_code -eq 0)
        if (-not $result.ok) { $result.error = "TERMINAL_CAPABILITY_ENFORCE_FAILED" }
    }
    catch {
        $result.error = "$_"
    }
    return $result
}

function Invoke-HiddenStdioSmoke {
    $hidden = Get-HiddenStdioInfo
    $result = [ordered]@{
        ok = $false
        launcher_path = $hidden.launcher_path
        generation_id = $hidden.generation_id
        child_creation_flag = $hidden.child_creation_flag
        exit_code = $null
        stdout = $null
        stderr = $null
        error = $null
    }
    if (-not $hidden.binary_exists) {
        $result.error = "HIDDEN_STDIO_BINARY_MISSING"
        return $result
    }
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $hidden.launcher_path
        $psi.Arguments = 'cmd.exe /d /s /c echo HIDDEN_STDIO_SMOKE_OK'
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $process = [Diagnostics.Process]::Start($psi)
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(10000)) {
            try { $process.Kill($true) } catch { $process.Kill() }
            [void]$process.WaitForExit(5000)
            $result.error = "HIDDEN_STDIO_SMOKE_TIMEOUT"
            return $result
        }
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $result.exit_code = $process.ExitCode
        $result.stdout = ($stdout | Out-String).Trim()
        $result.stderr = ($stderr | Out-String).Trim()
        $result.ok = ($process.ExitCode -eq 0 -and $result.stdout -match "HIDDEN_STDIO_SMOKE_OK")
    }
    catch {
        $result.error = "$_"
    }
    return $result
}

function Invoke-AcpThin {
    $result = [ordered]@{
        ok = $false
        adapter = $acpAdapter
        adapter_exists = (Test-Path -LiteralPath $acpAdapter -PathType Leaf)
        action = $AcpAction
        session = $Session
        exit_code = $null
        stdout = $null
        error = $null
        default_model_worker_route = $false
    }
    if (-not $result.adapter_exists) {
        $result.error = "ACP_ADAPTER_MISSING"
        return $result
    }
    $arguments = @("-NoProfile", "-File", $acpAdapter, "-Action", $AcpAction, "-Session", $Session)
    if ($Prompt) { $arguments += @("-Prompt", $Prompt) }
    if ($PromptFile) { $arguments += @("-PromptFile", $PromptFile) }
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "pwsh"
        $psi.Arguments = ($arguments | ForEach-Object {
                if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
            }) -join " "
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $process = [Diagnostics.Process]::Start($psi)
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(120000)) {
            try { $process.Kill($true) } catch { $process.Kill() }
            [void]$process.WaitForExit(5000)
            $result.error = "ACP_THIN_TIMEOUT"
            return $result
        }
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $result.exit_code = $process.ExitCode
        $result.stdout = (($stdout + "`n" + $stderr) | Out-String).Trim()
        if ($result.stdout.Length -gt 4000) { $result.stdout = $result.stdout.Substring(0, 4000) }
        $result.ok = ($process.ExitCode -eq 0)
    }
    catch {
        $result.error = "$_"
    }
    return $result
}

function Get-Inventory {
    $hidden = Get-HiddenStdioInfo
    return [ordered]@{
        schema_version = "xinao.acp_hidden_stdio_inventory.v2"
        canonical_default_route = "temporal_docker_houtai_gongren_worker_internal_langgraph"
        worker_selection = "dynamic_positive_net_benefit"
        available_workers = @("grok", "codex_agents", "combined")
        soft_preference_when_close = "grok"
        worker_width = "dynamic_ready_frontier_quota_latency_evidence"
        acp = [ordered]@{
            adapter = $acpAdapter
            present = (Test-Path -LiteralPath $acpAdapter -PathType Leaf)
            activation = "only_when_current_task_needs_acp"
        }
        hidden_stdio = $hidden
        shell_terminal_capability = [ordered]@{
            enforce_script = $terminalCap
            present = (Test-Path -LiteralPath $terminalCap -PathType Leaf)
            required_csv = "run_terminal_cmd,run_terminal_command"
        }
        scheduler_tick_default = $false
        worker_pool_default = $false
        resident_control_plane_default = $false
    }
}

function Write-WeldEvidence {
    param([Parameter(Mandatory)][System.Collections.IDictionary]$Payload)
    New-Item -ItemType Directory -Force -Path $stateDir, $zhDir | Out-Null
    [IO.File]::WriteAllText($evidencePath, ($Payload | ConvertTo-Json -Depth 12) + [Environment]::NewLine, $utf8)
    $readback = @(
        "# ACP + hidden-stdio + shell_terminal capability 薄焊",
        "",
        "- ok: **$($Payload.ok)**",
        "- canonical route: Temporal + Docker houtai-gongren + worker-internal LangGraph",
        "- worker selection: dynamic positive net benefit; soft preference Grok",
        "- scheduler_tick default: **false**",
        "- WorkerPool default: **false**",
        "- terminal capability: **$($Payload.checks.terminal_capability.ok)**",
        "- hidden stdio: **$($Payload.checks.hidden_stdio.ok)**",
        "- evidence: ``$evidencePath``"
    ) -join [Environment]::NewLine
    [IO.File]::WriteAllText($zhPath, $readback + [Environment]::NewLine, $utf8)
}

switch ($Action) {
    "Inventory" {
        $result = Get-Inventory
    }
    "TerminalCapability" {
        $result = Invoke-TerminalCapabilityEnforce
    }
    "HiddenStdio" {
        $result = Invoke-HiddenStdioSmoke
    }
    "Acp" {
        $result = Invoke-AcpThin
    }
    "Smoke" {
        $terminal = Invoke-TerminalCapabilityEnforce
        $hidden = Invoke-HiddenStdioSmoke
        $result = [ordered]@{
            ok = [bool]($terminal.ok -and $hidden.ok)
            terminal_capability = $terminal
            hidden_stdio = $hidden
            scheduler_tick_default = $false
            worker_pool_default = $false
        }
    }
    "Weld" {
        $terminal = Invoke-TerminalCapabilityEnforce
        $hidden = Invoke-HiddenStdioSmoke
        $result = [ordered]@{
            schema_version = "xinao.acp_hidden_stdio_weld.v2"
            generated_at = (Get-Date).ToString("o")
            ok = [bool]($terminal.ok -and $hidden.ok)
            completion_claim_allowed = $false
            canonical_default_route = "temporal_docker_houtai_gongren_worker_internal_langgraph"
            worker_selection = "dynamic_positive_net_benefit"
            available_workers = @("grok", "codex_agents", "combined")
            soft_preference_when_close = "grok"
            checks = [ordered]@{
                terminal_capability = $terminal
                hidden_stdio = $hidden
            }
            scheduler_tick_default = $false
            worker_pool_default = $false
            resident_control_plane_default = $false
            evidence_path = $evidencePath
            readback_path = $zhPath
        }
        Write-WeldEvidence -Payload $result
    }
}

if (-not $Quiet) { $result | ConvertTo-Json -Depth 12 }
if ($result.PSObject.Properties.Name -contains "ok" -and -not [bool]$result.ok) { exit 1 }
