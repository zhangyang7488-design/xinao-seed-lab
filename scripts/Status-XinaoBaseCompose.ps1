param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $RepoRoot "docker-compose.yml"
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

$namesDoc = & (Join-Path $RepoRoot "scripts\Get-XinaoComposeDisplayNames.ps1")
$workerSlugs = @($namesDoc.worker.slug_set)
$workerContainerRunning = $false
$workerContainerName = [string]$namesDoc.worker_container
$workerDisplayCn = [string]$namesDoc.worker_display_cn
try {
    $psRaw = (& docker compose -f $composeFile ps --format json 2>&1 | Out-String).Trim()
    if ($psRaw) {
        $lines = $psRaw -split "`n" | Where-Object { $_.Trim() }
        foreach ($line in $lines) {
            try {
                $row = $line | ConvertFrom-Json
                if ($row.State -match "running" -and ($workerSlugs -contains $row.Name)) {
                    $workerContainerRunning = $true
                }
            } catch { }
        }
    }
} catch { }

$workerReady = $workerDaemonOk -or ($workerContainerRunning -and $temporalOk)

$litellmOk = [bool](Test-NetConnection -ComputerName 127.0.0.1 -Port 20128 -WarningAction SilentlyContinue).TcpTestSucceeded
$qdrantOk = [bool](Test-NetConnection -ComputerName 127.0.0.1 -Port 6333 -WarningAction SilentlyContinue).TcpTestSucceeded

$payload = [ordered]@{
    schema_version = "xinao.base_compose.status.v1"
    stack_version  = "XINAO_Base_V2_unified"
    golden_path    = $true
    temporal_7233  = $temporalOk
    temporal_ui_8080 = $uiOk
    litellm_20128  = $litellmOk
    qdrant_6333    = $qdrantOk
    worker_container = $workerContainerName
    worker_display_cn = $workerDisplayCn
    worker_container_running = $workerContainerRunning
    worker_daemon_ok = $workerDaemonOk
    worker_ready   = $workerReady
    binding_count  = $bindingCount
    compose_file   = $composeFile
    evidence_ref   = $evidencePath
    generated_at   = (Get-Date).ToString("o")
}
$payload | ConvertTo-Json -Depth 6