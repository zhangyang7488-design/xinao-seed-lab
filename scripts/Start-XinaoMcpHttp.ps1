param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 19460
)

$ErrorActionPreference = "Stop"
$stateDir = Join-Path $RuntimeRoot "state\xinao_mcp_http"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$logPath = Join-Path $stateDir "mcp.stdout.log"
$errPath = Join-Path $stateDir "mcp.stderr.log"
$pidPath = Join-Path $stateDir "mcp.pid"
$latestPath = Join-Path $stateDir "latest.json"

$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    $py = "python"
}

$existingPid = ""
if (Test-Path -LiteralPath $pidPath) {
    $existingPid = (Get-Content -LiteralPath $pidPath -Raw).Trim()
}
if ($existingPid -match '^\d+$') {
    $existing = Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue
    if ($existing) {
        $payload = [ordered]@{
            schema_version = "xinao.mcp_http.v1"
            status = "already_running"
            mcp_url = "http://${BindHost}:$Port/mcp"
            pid = [int]$existingPid
            generated_at = (Get-Date).ToString("o")
        }
        $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $latestPath -Encoding UTF8
        $payload | ConvertTo-Json -Depth 6
        exit 0
    }
}

$portOpen = [bool](Test-NetConnection $BindHost -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded
if ($portOpen) {
    $payload = [ordered]@{
        schema_version = "xinao.mcp_http.v1"
        status = "port_in_use"
        mcp_url = "http://${BindHost}:$Port/mcp"
        named_blocker = "XINAO_MCP_PORT_ALREADY_BOUND"
        generated_at = (Get-Date).ToString("o")
    }
    $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $latestPath -Encoding UTF8
    $payload | ConvertTo-Json -Depth 6
    exit 1
}

$env:XINAO_REPO_ROOT = $RepoRoot
$env:XINAO_RUNTIME_ROOT = $RuntimeRoot
$env:XINAO_ROUTE_PROFILE = "seed_cortex_phase0"
$env:XINAO_MCP_HOST = $BindHost
$env:XINAO_MCP_PORT = [string]$Port
$env:PYTHONPATH = "$RepoRoot\src;$RepoRoot"

$serverScript = Join-Path $RepoRoot "services\mcp\xinao_mcp_server.py"
$proc = Start-Process `
    -FilePath $py `
    -ArgumentList @($serverScript, "--transport", "streamable-http") `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError $errPath `
    -PassThru
Set-Content -LiteralPath $pidPath -Value $proc.Id -Encoding ASCII

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    if ([bool](Test-NetConnection $BindHost -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
}

$payload = [ordered]@{
    schema_version = "xinao.mcp_http.v1"
    status = if ($ready) { "running" } else { "blocked" }
    named_blocker = if ($ready) { "" } else { "XINAO_MCP_START_TIMEOUT" }
    mcp_url = "http://${BindHost}:$Port/mcp"
    repo_root = $RepoRoot
    runtime_root = $RuntimeRoot
    pid = $proc.Id
    log = $logPath
    error_log = $errPath
    generated_at = (Get-Date).ToString("o")
    not_source_of_truth = $true
    not_user_completion = $true
}
$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $latestPath -Encoding UTF8
$payload | ConvertTo-Json -Depth 8
exit $(if ($ready) { 0 } else { 1 })