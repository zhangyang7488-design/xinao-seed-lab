[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "bridge.config.json"),
    [switch]$IncludeCodexDelivery
)

$ErrorActionPreference = "Stop"
if (-not $PSScriptRoot) { $PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }

function Invoke-HttpProbe([string]$Url, [int]$TimeoutSec = 5, [string]$BearerToken = $null) {
    try {
        $params = @{ Uri = $Url; UseBasicParsing = $true; TimeoutSec = $TimeoutSec }
        if ($BearerToken) { $params.Headers = @{ Authorization = "Bearer $BearerToken" } }
        $resp = Invoke-WebRequest @params
        return [ordered]@{ ok = $true; status_code = $resp.StatusCode }
    }
    catch {
        return [ordered]@{ ok = $false; error = $_.Exception.Message }
    }
}

$litellmKey = if ($env:LITELLM_MASTER_KEY) { $env:LITELLM_MASTER_KEY } else { "sk-xinao-thin-glue-local" }

function Test-TcpPort([int]$Port) {
    try {
        $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -WarningAction SilentlyContinue
        return [bool]$tcp.TcpTestSucceeded
    }
    catch { return $false }
}

$grokSelf = [ordered]@{
    checkpoint   = Test-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context\latest.json"
    memory_md    = Test-Path "C:\Users\xx363\.grok\memory\MEMORY.md"
    workspace_mcp = Test-Path (Join-Path $PSScriptRoot "..\.grok\config.toml")
    registry_scan = Test-Path "D:\XINAO_RESEARCH_RUNTIME\state\local_capability_registry\latest.json"
    docker       = [ordered]@{ ok = $false }
    litellm_20128 = Invoke-HttpProbe "http://127.0.0.1:20128/v1/models" 8 $litellmKey
    ollama_11434  = Invoke-HttpProbe "http://127.0.0.1:11434/api/tags"
    qdrant_6333   = Invoke-HttpProbe "http://127.0.0.1:6333/readyz" 3
    windows_mcp   = Test-Path "D:\XINAO_RESEARCH_RUNTIME\tools\windows-mcp\Sbroenne.WindowsMcp.exe"
}

try {
    docker info 2>&1 | Out-Null
    $grokSelf.docker.ok = ($LASTEXITCODE -eq 0)
}
catch {
    $grokSelf.docker.error = $_.Exception.Message
}

$result = [ordered]@{
    schema_version   = "xinao.grok_self_capability_status.v1"
    generated_at     = (Get-Date).ToString("o")
    scope_cn         = "Grok 岛自身能力；不含 Codex 投递闭合"
    not_333_mainline = $true
    grok_self        = $grokSelf
    delivery_role    = "codex_delivery_on_user_request_only"
}

if ($IncludeCodexDelivery) {
    $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $base = [string]$config.ingress_base_url
    $ingressStatus = if ($config.PSObject.Properties['ingress_base_url_status']) { [string]$config.ingress_base_url_status } else { "legacy" }

    function Invoke-LocalGet([string]$Path) {
        try {
            $resp = Invoke-WebRequest -Uri ($base.TrimEnd('/') + $Path) -UseBasicParsing -TimeoutSec 15
            return [ordered]@{ ok = $true; status_code = $resp.StatusCode; body = $resp.Content }
        }
        catch {
            return [ordered]@{ ok = $false; error = $_.Exception.Message }
        }
    }

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

    $result.schema_version = "xinao.grok_admin_bridge.status.v1"
    $result.scope_cn = "Grok 自身 + Codex 投递探活（用户已请求投递面）"
    $result.codex_delivery = [ordered]@{
        ingress_base_url_status = $ingressStatus
        ingress_health = Invoke-LocalGet "/health"
        codex_a_panel  = Invoke-LocalGet "/codex-a/panel-readback"
        xinao_mcp_http = [ordered]@{ ok = (Test-TcpPort 19460) }
        ucp_codex_a_probe = $ucp
        current_intent_id = if ($admitted) { $admitted.current_intent_id } else { if ($episode) { $episode.intent_id } else { "YELLOW_BOOTSTRAP_INTENT_SPINE_MISSING" } }
        intent_episode_ref = $config.intent_episode_ref
        intent_state_ref = $config.intent_state_ref
    }
}

$result | ConvertTo-Json -Depth 8