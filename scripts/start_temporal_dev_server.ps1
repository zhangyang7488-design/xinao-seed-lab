param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$TemporalAddress = "127.0.0.1",
    [int]$Port = 7233,
    [int]$UiPort = 8233,
    [int]$WaitSeconds = 45
)

$ErrorActionPreference = "Stop"

$stateDir = Join-Path $RuntimeRoot "state\temporal_dev_server"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$logPath = Join-Path $stateDir "server.stdout.log"
$errPath = Join-Path $stateDir "server.stderr.log"
$pidPath = Join-Path $stateDir "server.pid"
$dbPath = Join-Path $stateDir "temporal-dev-server.db"
$evidencePath = Join-Path $stateDir "latest.json"

function Write-Evidence {
    param([object]$Payload)
    $Payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
    $Payload | ConvertTo-Json -Depth 12
}

function Test-TemporalPort {
    return [bool](Test-NetConnection $TemporalAddress -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded
}

$temporalCommand = Get-Command temporal -ErrorAction SilentlyContinue
if (-not $temporalCommand) {
    Write-Evidence ([ordered]@{
        schema_version = "xinao.temporal_dev_server.v1"
        status = "blocked"
        named_blocker = "TEMPORAL_CLI_NOT_FOUND"
        temporal_address = "$TemporalAddress`:$Port"
        generated_at = (Get-Date).ToString("o")
        not_source_of_truth = $true
        not_user_completion = $true
        not_completion_decision = $true
    })
    exit 1
}

if (Test-TemporalPort) {
    $payload = [ordered]@{
        schema_version = "xinao.temporal_dev_server.v1"
        status = "already_running"
        temporal_address = "$TemporalAddress`:$Port"
        ui_address = "http://$TemporalAddress`:$UiPort"
        pid = $null
        pid_ref = $pidPath
        log = $logPath
        error_log = $errPath
        db_filename = $dbPath
        generated_at = (Get-Date).ToString("o")
        verify_command = "temporal workflow list --address $TemporalAddress`:$Port"
        route_profile = "seed_cortex_phase0"
        old_clean_runtime_authority = $false
        not_source_of_truth = $true
        not_user_completion = $true
        not_completion_decision = $true
    }
    Write-Evidence $payload
    exit 0
}

$args = @(
    "server",
    "start-dev",
    "--ip",
    $TemporalAddress,
    "--port",
    [string]$Port,
    "--ui-port",
    [string]$UiPort,
    "--db-filename",
    $dbPath,
    "--log-level",
    "warn"
)

$proc = Start-Process `
    -FilePath $temporalCommand.Source `
    -ArgumentList $args `
    -WorkingDirectory $stateDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError $errPath `
    -PassThru
Set-Content -LiteralPath $pidPath -Value $proc.Id -Encoding ASCII

$portOpen = $false
for ($attempt = 0; $attempt -lt $WaitSeconds; $attempt++) {
    if (Test-TemporalPort) {
        $portOpen = $true
        break
    }
    Start-Sleep -Seconds 1
}

$payload = [ordered]@{
    schema_version = "xinao.temporal_dev_server.v1"
    status = if ($portOpen) { "running" } else { "blocked" }
    named_blocker = if ($portOpen) { "" } else { "TEMPORAL_SERVER_START_TIMEOUT" }
    temporal_address = "$TemporalAddress`:$Port"
    ui_address = "http://$TemporalAddress`:$UiPort"
    pid = $proc.Id
    process_alive = [bool](Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)
    pid_ref = $pidPath
    log = $logPath
    error_log = $errPath
    db_filename = $dbPath
    generated_at = (Get-Date).ToString("o")
    verify_command = "temporal workflow list --address $TemporalAddress`:$Port"
    route_profile = "seed_cortex_phase0"
    old_clean_runtime_authority = $false
    not_source_of_truth = $true
    not_user_completion = $true
    not_completion_decision = $true
}
Write-Evidence $payload
exit $(if ($portOpen) { 0 } else { 1 })
