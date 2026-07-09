param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $RepoRoot "docker-compose.xinao-base.yml"
$evidencePath = Join-Path $RuntimeRoot "state\xinao_base_compose\latest.json"
$daemonEv = Join-Path $RuntimeRoot "state\integrated_bus_worker_daemon\latest.json"

$temporalOk = [bool](Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue).TcpTestSucceeded
$uiOk = [bool](Test-NetConnection -ComputerName 127.0.0.1 -Port 8080 -WarningAction SilentlyContinue).TcpTestSucceeded
$workerDaemonOk = $false
$bindingCount = 0
if (Test-Path -LiteralPath $daemonEv) {
    try {
        $dj = Get-Content $daemonEv -Raw -Encoding UTF8 | ConvertFrom-Json
        $bindingCount = [int]$dj.binding_count
        $workerDaemonOk = ($dj.status -eq "polling" -and $bindingCount -gt 0)
    } catch { }
}

$workerContainerRunning = $false
try {
    $psRaw = (& docker compose -f $composeFile ps --format json 2>&1 | Out-String).Trim()
    if ($psRaw) {
        $lines = $psRaw -split "`n" | Where-Object { $_.Trim() }
        foreach ($line in $lines) {
            try {
                $row = $line | ConvertFrom-Json
                if ($row.Name -eq "xinao-worker" -and $row.State -match "running") {
                    $workerContainerRunning = $true
                }
            } catch { }
        }
    }
} catch { }

$workerReady = $workerDaemonOk -or ($workerContainerRunning -and $temporalOk)

$payload = [ordered]@{
    schema_version = "xinao.base_compose.status.v1"
    golden_path    = $true
    temporal_7233  = $temporalOk
    temporal_ui_8080 = $uiOk
    worker_container_running = $workerContainerRunning
    worker_daemon_ok = $workerDaemonOk
    worker_ready   = $workerReady
    binding_count  = $bindingCount
    compose_file   = $composeFile
    evidence_ref   = $evidencePath
    generated_at   = (Get-Date).ToString("o")
}
$payload | ConvertTo-Json -Depth 6