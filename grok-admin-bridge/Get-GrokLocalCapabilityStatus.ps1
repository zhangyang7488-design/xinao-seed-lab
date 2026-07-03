[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "bridge.config.json")
)

$ErrorActionPreference = "Stop"
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$base = [string]$config.ingress_base_url

function Invoke-LocalGet([string]$Path) {
    try {
        $resp = Invoke-WebRequest -Uri ($base.TrimEnd('/') + $Path) -UseBasicParsing -TimeoutSec 15
        return [ordered]@{ ok = $true; status_code = $resp.StatusCode; body = $resp.Content }
    }
    catch {
        return [ordered]@{ ok = $false; error = $_.Exception.Message }
    }
}

$health = Invoke-LocalGet "/health"
$panel = Invoke-LocalGet "/codex-a/panel-readback"
$mcp = [ordered]@{ ok = $false }
try {
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 19460 -WarningAction SilentlyContinue
    $mcp.ok = [bool]$tcp.TcpTestSucceeded
}
catch {}

$episode = $null
$admitted = $null
if (Test-Path -LiteralPath $config.intent_episode_ref) {
    $episode = Get-Content -LiteralPath $config.intent_episode_ref -Raw | ConvertFrom-Json
}
if (Test-Path -LiteralPath $config.intent_state_ref) {
    $admitted = Get-Content -LiteralPath $config.intent_state_ref -Raw | ConvertFrom-Json
}

$ucp = [ordered]@{ ok = $false }
if ((Test-Path -LiteralPath $config.ucp_python) -and (Test-Path -LiteralPath $config.ucp_script)) {
    $out = & $config.ucp_python $config.ucp_script dispatch --source grok-admin --target codex_app_server_a --verb status 2>&1 | Out-String
    $ucp = [ordered]@{ ok = $LASTEXITCODE -eq 0; exit_code = $LASTEXITCODE; stdout = $out.Substring(0, [Math]::Min(2000, $out.Length)) }
}

[ordered]@{
    schema_version = "xinao.grok_admin_bridge.status.v1"
    generated_at = (Get-Date).ToString("o")
    ingress_health = $health
    codex_a_panel = $panel
    xinao_mcp_http = $mcp
    ucp_codex_a_probe = $ucp
    current_intent_id = if ($admitted) { $admitted.current_intent_id } else { if ($episode) { $episode.intent_id } else { "YELLOW_BOOTSTRAP_INTENT_SPINE_MISSING" } }
    intent_episode_ref = $config.intent_episode_ref
    intent_state_ref = $config.intent_state_ref
    delivery_role = $config.delivery_role
} | ConvertTo-Json -Depth 8