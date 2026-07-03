[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\xx363\CodexWorkspaces\B\nianhua",
    [string]$WorkspaceRoot = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace"
)

$ErrorActionPreference = "Stop"
$repairUtf8 = Join-Path $PSScriptRoot "Repair-GrokBridgeScriptsUtf8.ps1"
if (Test-Path -LiteralPath $repairUtf8) {
    & $repairUtf8 -BridgeRoot $PSScriptRoot | Out-Null
}
$startMcp = Join-Path $RepoRoot "scripts\start_xinao_mcp_http.ps1"
if (Test-Path -LiteralPath $startMcp) {
    & $startMcp | Out-String | Write-Output
}

$configToml = Join-Path $WorkspaceRoot ".grok\config.toml"
if (-not (Test-Path -LiteralPath $configToml)) {
    throw "GROK_PROJECT_CONFIG_MISSING: $configToml"
}

$statusScript = Join-Path $WorkspaceRoot "grok-admin-bridge\Get-GrokLocalCapabilityStatus.ps1"
$status = & $statusScript | ConvertFrom-Json

$stateDir = "D:\XINAO_CLEAN_RUNTIME\state\grok_admin_bridge"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$latest = [ordered]@{
    schema_version = "xinao.grok_admin_bridge.install.v1"
    status = "installed"
    generated_at = (Get-Date).ToString("o")
    workspace_root = $WorkspaceRoot
    grok_project_config = $configToml
    mcp_server = "xinao @ http://127.0.0.1:19460/mcp"
    capability_status = $status
    grok_l0_bootstrap = @{
        bootstrap_md = (Join-Path $WorkspaceRoot "grok-admin-bridge\GROK_L0_BOOTSTRAP.md")
        gate_script = (Join-Path $WorkspaceRoot "grok-admin-bridge\Invoke-GrokL0BootstrapGate.ps1")
        auto_rule = (Join-Path $WorkspaceRoot ".grok\rules\00-grok-l0-bootstrap.md")
        session_start_hook = (Join-Path $WorkspaceRoot ".grok\hooks\session-start-l0-gate.json")
        required_before_any_action = $true
    }
    scripts = @{
        status = $statusScript
        inject = (Join-Path $WorkspaceRoot "grok-admin-bridge\Send-GrokIntentToCodexA.ps1")
        ucp = (Join-Path $WorkspaceRoot "grok-admin-bridge\Invoke-GrokUcpDispatch.ps1")
        parallel_audit = (Join-Path $WorkspaceRoot "grok-admin-bridge\Invoke-GrokParallelGlobalAudit.ps1")
        parallel_audit_status = (Join-Path $WorkspaceRoot "grok-admin-bridge\Get-GrokParallelGlobalAuditStatus.ps1")
        l0_gate = (Join-Path $WorkspaceRoot "grok-admin-bridge\Invoke-GrokL0BootstrapGate.ps1")
    }
    usage = @{
        default_flow = "User -> Grok (preserve intent) -> Send-GrokIntentToCodexA -> CodexA brain turn"
        touch_flow = "Get-GrokLocalCapabilityStatus or Invoke-GrokUcpDispatch for local probes"
        restart_grok = "Restart Grok session or run /mcps refresh so xinao MCP tools load"
    }
    not_user_completion = $true
}
$latestPath = Join-Path $stateDir "latest.json"
$latest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $latestPath -Encoding UTF8

Write-Output "GROK_ADMIN_BRIDGE_INSTALLED"
Write-Output "state=$latestPath"
Write-Output "mcp_config=$configToml"
Write-Output "current_intent_id=$($status.current_intent_id)"
Write-Output "ingress_ok=$($status.ingress_health.ok)"
Write-Output "SENTINEL:GROK_ADMIN_BRIDGE_READY"