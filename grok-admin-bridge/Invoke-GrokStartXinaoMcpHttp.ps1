#Requires -Version 5.1
<#
.SYNOPSIS
  按成熟主路启动/重建 XINAO MCP HTTP（:19460）。非新控制面；薄壳转调 S 脚本。
.EXAMPLE
  .\Invoke-GrokStartXinaoMcpHttp.ps1
  .\Invoke-GrokStartXinaoMcpHttp.ps1 -Restart
#>
param(
    [switch]$Restart,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$start = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Start-XinaoMcpHttp.ps1"
$stateDir = Join-Path $runtime "state\xinao_mcp_http"
$pidPath = Join-Path $stateDir "mcp.pid"

if (-not (Test-Path -LiteralPath $start)) {
    throw "MISSING_MATURE_START: $start"
}

if ($Restart -and (Test-Path $pidPath)) {
    $pidTxt = (Get-Content $pidPath -Raw -ErrorAction SilentlyContinue).Trim()
    if ($pidTxt -match '^\d+$') {
        Stop-Process -Id ([int]$pidTxt) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidPath -Force -ErrorAction SilentlyContinue
}

& $start
$code = $LASTEXITCODE

# 端口探测（不用慢 Test-NetConnection）
function Test-PortFast([int]$Port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $iar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(800) -and $c.Connected
        try { $c.Close() } catch {}
        return $ok
    } catch { return $false }
}

$up = Test-PortFast 19460
$out = [ordered]@{
    schema_version = "xinao.grok_start_xinao_mcp.v1"
    generated_at   = (Get-Date).ToString("o")
    start_script   = $start
    exit_code      = $code
    port_19460_up  = $up
    mcp_url        = "http://127.0.0.1:19460/mcp"
    note_cn        = "GET 裸请求可能 406（streamable-http）；端口通+进程在即可。非 333 控制面。"
    claim_state    = if ($up) { "registered_and_hooked" } else { "blocked" }
    completion_claim_allowed = $false
}
$latest = Join-Path $stateDir "grok_start_latest.json"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($latest, ($out | ConvertTo-Json -Depth 8), $utf8)
if (-not $Quiet) {
    Write-Host "xinao_mcp port_up=$up exit=$code evidence=$latest"
}
if (-not $up) { exit 1 }
exit 0
