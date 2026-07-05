param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$Listen = "ws://127.0.0.1:19131",
    [string]$CodexHome = "C:\Users\xx363\.codex-seed-cortex",
    [string]$CodexExe = ""
)

$ErrorActionPreference = "Stop"

$stateDir = Join-Path $RuntimeRoot "state\codex_tui_remote_app_server_launch_profile"
$logDir = Join-Path $stateDir "logs"
New-Item -ItemType Directory -Force -Path $stateDir, $logDir | Out-Null

$latest = Join-Path $stateDir "latest.json"
$pidPath = Join-Path $stateDir "app-server.pid"
$stdout = Join-Path $logDir "app-server.stdout.log"
$stderr = Join-Path $logDir "app-server.stderr.log"

function Write-State {
    param([hashtable]$Payload)
    $Payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $latest -Encoding UTF8
}

function Get-ListenPort {
    param([string]$Url)
    if ($Url -match ':(\d+)(?:/)?$') { return [int]$Matches[1] }
    return 0
}

if ([string]::IsNullOrWhiteSpace($CodexExe)) {
    $cmd = Get-Command codex -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        $CodexExe = $cmd.Source
    }
}

$port = Get-ListenPort $Listen
if ($port -le 0) {
    throw "Unsupported listen URL: $Listen"
}

$existing = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    $payload = @{
        schema_version = "xinao.codex_tui_remote_app_server_launch_profile.v1"
        status = "already_running"
        listen = $Listen
        port = $port
        process_id = $existing.OwningProcess
        codex_home = $CodexHome
        stdout_ref = $stdout
        stderr_ref = $stderr
        pid_ref = $pidPath
        generated_at = (Get-Date).ToString("o")
        completion_claim_allowed = $false
        not_source_of_truth = $true
        not_user_completion = $true
        not_completion_decision = $true
        not_execution_controller = $true
    }
    Write-State $payload
    $payload | ConvertTo-Json -Depth 10
    exit 0
}

$env:CODEX_HOME = $CodexHome
$argsList = @("app-server", "--listen", $Listen)
$proc = Start-Process -FilePath $CodexExe `
    -ArgumentList $argsList `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

Set-Content -LiteralPath $pidPath -Value $proc.Id -Encoding ASCII
Start-Sleep -Seconds 2

$conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
$payload = @{
    schema_version = "xinao.codex_tui_remote_app_server_launch_profile.v1"
    status = if ($conn) { "started" } else { "started_health_pending" }
    listen = $Listen
    port = $port
    pid = $proc.Id
    process_id = if ($conn) { $conn.OwningProcess } else { $proc.Id }
    codex_home = $CodexHome
    codex_exe = $CodexExe
    stdout_ref = $stdout
    stderr_ref = $stderr
    pid_ref = $pidPath
    generated_at = (Get-Date).ToString("o")
    completion_claim_allowed = $false
    not_source_of_truth = $true
    not_user_completion = $true
    not_completion_decision = $true
    not_execution_controller = $true
}
Write-State $payload
$payload | ConvertTo-Json -Depth 10
