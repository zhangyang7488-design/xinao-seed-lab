param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [switch]$WithGateway,
    [switch]$Build,
    [int]$WaitSeconds = 120
)

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $RepoRoot "docker-compose.yml"
$stateDir = Join-Path $RuntimeRoot "state\xinao_base_compose"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$evidencePath = Join-Path $stateDir "latest.json"

function Write-Evidence([hashtable]$Payload) {
    $Payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
    $Payload | ConvertTo-Json -Depth 10
}

function Test-DockerDaemonReady {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $null = docker ps 2>&1
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $prev
    }
}

if (-not (Test-DockerDaemonReady)) {
    Write-Evidence ([ordered]@{
        schema_version = "xinao.base_compose.v1"
        status         = "blocked"
        named_blocker  = "DOCKER_DAEMON_DOWN"
        hint_cn        = "Start Docker Desktop then retry"
        compose_file   = $composeFile
        generated_at   = (Get-Date).ToString("o")
        golden_path    = $true
        not_user_completion = $true
    })
    exit 1
}

$env:XINAO_EVIDENCE_HOST = $RuntimeRoot -replace '\\', '/'
Set-Location $RepoRoot
$dockerArgs = @("compose", "-f", $composeFile, "up", "-d")
if ($Build) { $dockerArgs += "--build" }
if ($WithGateway) { $dockerArgs += "--profile"; $dockerArgs += "gateway" }
& docker @dockerArgs
if ($LASTEXITCODE -ne 0) {
    Write-Evidence ([ordered]@{
        schema_version = "xinao.base_compose.v1"
        status         = "failed"
        named_blocker  = "COMPOSE_UP_FAILED"
        exit_code      = $LASTEXITCODE
        generated_at   = (Get-Date).ToString("o")
    })
    exit $LASTEXITCODE
}

$temporalOk = $false
$uiOk = $false
for ($i = 0; $i -lt $WaitSeconds; $i++) {
    $temporalOk = [bool](Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue).TcpTestSucceeded
    $uiOk = [bool](Test-NetConnection -ComputerName 127.0.0.1 -Port 8080 -WarningAction SilentlyContinue).TcpTestSucceeded
    if ($temporalOk) { break }
    Start-Sleep -Seconds 1
}

$psOut = (& docker compose -f $composeFile ps --format json 2>&1 | Out-String).Trim()
$payload = [ordered]@{
    schema_version   = "xinao.base_compose.v1"
    status           = if ($temporalOk) { "running" } else { "partial" }
    named_blocker    = if ($temporalOk) { "" } else { "TEMPORAL_PORT_NOT_OPEN" }
    golden_path      = $true
    spine_unchanged  = "Temporal durable + LangGraph plugin worker"
    stack_version    = "XINAO_Base_V2_unified"
    compose_file     = $composeFile
    temporal_address = "127.0.0.1:7233"
    temporal_ui      = "http://127.0.0.1:8080"
    evidence_volume  = $RuntimeRoot
    worker_container = "xinao-worker"
    temporal_ok      = $temporalOk
    ui_ok            = $uiOk
    with_gateway     = [bool]$WithGateway
    verify_commands  = @(
        "docker compose -f `"$composeFile`" ps",
        "docker compose -f `"$composeFile`" logs -f xinao-worker",
        "temporal workflow list --address 127.0.0.1:7233"
    )
    ps_json_tail     = if ($psOut.Length -gt 4000) { $psOut.Substring($psOut.Length - 4000) } else { $psOut }
    generated_at     = (Get-Date).ToString("o")
    not_user_completion = $true
    replaces_dev_rescue = "start_temporal_dev_server.ps1 hidden Start-Process"
}
Write-Evidence $payload
exit $(if ($temporalOk) { 0 } else { 1 })