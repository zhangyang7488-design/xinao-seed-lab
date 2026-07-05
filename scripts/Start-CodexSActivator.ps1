param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 19121,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Python)) {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $Python = $venvPython
    } else {
        $Python = "python"
    }
}

$stateRoot = Join-Path $RuntimeRoot "state\codex_s_activator"
$stateDir = Join-Path $stateRoot "ports\$Port"
$logDir = Join-Path $stateDir "logs"
New-Item -ItemType Directory -Force -Path $stateRoot, $stateDir, $logDir | Out-Null
$stdout = Join-Path $logDir "activator.stdout.log"
$stderr = Join-Path $logDir "activator.stderr.log"
$latest = Join-Path $stateDir "latest.json"
$rootLatest = Join-Path $stateRoot "latest.json"
$pidPath = Join-Path $stateDir "activator.pid"
$url = "http://${HostName}:$Port"

function Write-State {
    param([hashtable]$Payload)
    $Payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $latest -Encoding UTF8
    $Payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $rootLatest -Encoding UTF8
}

try {
    $health = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 2
    if ($health.ok -eq $true -and ($health.targets -contains "codex-s") -and [string]$health.runtime_root -eq $RuntimeRoot) {
        $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
        $payload = @{
            schema_version = "xinao.codex_s.activator.process.v1"
            status = "already_running"
            pid = if ($conn) { $conn.OwningProcess } else { 0 }
            process_id = if ($conn) { $conn.OwningProcess } else { 0 }
            port = $Port
            url = $url
            runtime_root = $RuntimeRoot
            repo_root = $RepoRoot
            targets = @($health.targets)
            health = $health
            stdout_ref = $stdout
            stderr_ref = $stderr
            completion_claim_allowed = $false
            not_execution_controller = $true
            generated_at = (Get-Date).ToString("o")
        }
        if ($conn) {
            Set-Content -LiteralPath $pidPath -Value $conn.OwningProcess -Encoding ASCII
        }
        Write-State $payload
        $payload | ConvertTo-Json -Depth 8
        exit 0
    }
} catch {
}

$argsList = @(
    "-m", "services.codex_activator.codex_activator",
    "--host", $HostName,
    "--port", [string]$Port,
    "--runtime", $RuntimeRoot
)
$env:XINAO_CODEX_ACTIVATOR_RUNTIME_ROOT = $RuntimeRoot
$env:XINAO_RUNTIME_REPO_READBACK_WRITE = "0"
$proc = Start-Process -FilePath $Python `
    -ArgumentList $argsList `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru
Set-Content -LiteralPath $pidPath -Value $proc.Id -Encoding ASCII
Start-Sleep -Seconds 2

$healthPayload = $null
try {
    $healthPayload = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 5
} catch {
}
$conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Set-Content -LiteralPath $pidPath -Value $conn.OwningProcess -Encoding ASCII
}

$payload = @{
    schema_version = "xinao.codex_s.activator.process.v1"
    status = if ($healthPayload -and $healthPayload.ok -eq $true) { "started" } else { "started_health_pending" }
    pid = if ($conn) { $conn.OwningProcess } else { $proc.Id }
    launched_pid = $proc.Id
    process_id = if ($conn) { $conn.OwningProcess } else { $proc.Id }
    port = $Port
    url = $url
    runtime_root = $RuntimeRoot
    repo_root = $RepoRoot
    targets = if ($healthPayload) { @($healthPayload.targets) } else { @() }
    health = if ($healthPayload) { $healthPayload } else { @{} }
    stdout_ref = $stdout
    stderr_ref = $stderr
    pid_ref = $pidPath
    completion_claim_allowed = $false
    not_execution_controller = $true
    generated_at = (Get-Date).ToString("o")
}
Write-State $payload
$payload | ConvertTo-Json -Depth 8
