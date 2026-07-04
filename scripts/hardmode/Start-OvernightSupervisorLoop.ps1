[CmdletBinding()]
param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$IntentPackage = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge\intent_packages\grok_overnight_supervisor_loop_phase0_batch_20260704.json",
    [double]$DurationHours = 10,
    [string]$DeadlineAt = "",
    [int]$WaveIntervalSeconds = 0,
    [int]$HeartbeatSeconds = 300,
    [int]$TimeoutSeconds = 900,
    [switch]$RunLoop,
    [switch]$RunOnce,
    [switch]$Status,
    [switch]$NoWorkerStart
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$stateDir = Join-Path $RuntimeRoot "state\overnight_supervisor_loop"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$launcherLatest = Join-Path $stateDir "launcher_latest.json"
$pidPath = Join-Path $stateDir "loop.pid"
$stdoutPath = Join-Path $stateDir "loop.stdout.log"
$stderrPath = Join-Path $stateDir "loop.stderr.log"

function Write-JsonAtomic {
    param([string]$Path, [object]$Value, [int]$Depth = 12)
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $tmp = "$Path.$PID.tmp"
    ($Value | ConvertTo-Json -Depth $Depth) + [Environment]::NewLine | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Get-Python {
    $repoPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $repoPython -PathType Leaf) {
        return $repoPython
    }
    return (Get-Command python).Source
}

function Invoke-LoopModule {
    param([string[]]$ExtraArgs)
    $python = Get-Python
    $oldPythonPath = $env:PYTHONPATH
    $deadlineArgs = @()
    if ($DeadlineAt) {
        $deadlineArgs = @("--deadline-at", $DeadlineAt)
    }
    try {
        $env:PYTHONPATH = "$RepoRoot\src;$RepoRoot"
        & $python -m services.agent_runtime.overnight_supervisor_loop `
            --runtime-root $RuntimeRoot `
            --repo-root $RepoRoot `
            --intent-package $IntentPackage `
            --duration-hours $DurationHours `
            @deadlineArgs `
            --wave-interval-seconds $WaveIntervalSeconds `
            --heartbeat-seconds $HeartbeatSeconds `
            --timeout-seconds $TimeoutSeconds `
            @ExtraArgs
        $script:LoopModuleExitCode = $LASTEXITCODE
    }
    finally {
        $env:PYTHONPATH = $oldPythonPath
    }
}

if ($Status) {
    Invoke-LoopModule -ExtraArgs @("--status")
    exit $script:LoopModuleExitCode
}

if ($RunOnce) {
    Invoke-LoopModule -ExtraArgs @("--run-once")
    exit $script:LoopModuleExitCode
}

if ($RunLoop) {
    $payload = [ordered]@{
        schema_version = "xinao.codex_s.overnight_supervisor_loop.launcher.v1"
        status = "run_loop_disabled_reference_only"
        pid = 0
        task_id = "overnight_supervisor_loop_phase0_batch_20260704"
        work_id = "xinao_seed_cortex_phase0_20260701"
        route_profile = "seed_cortex_phase0"
        intent_package = $IntentPackage
        runtime_root = $RuntimeRoot
        repo_root = $RepoRoot
        duration_hours = $DurationHours
        deadline_at = $DeadlineAt
        wave_interval_seconds = $WaveIntervalSeconds
        watchdog_only = $true
        disabled = $true
        reference_only = $true
        not_main_loop = $true
        not_task_owner = $true
        not_completion_boundary = $true
        not_watch_owner = $true
        sleep_1800_default_main_loop_allowed = $false
        main_loop_replacement = "temporal_activity_event_queue_loop"
        completion_claim_allowed = $false
        not_user_completion = $true
        not_completion_decision = $true
        not_execution_controller = $true
        generated_at = (Get-Date).ToString("o")
    }
    Write-JsonAtomic -Path $launcherLatest -Value $payload
    $payload | ConvertTo-Json -Depth 10
    exit 0
}

$payload = [ordered]@{
    schema_version = "xinao.codex_s.overnight_supervisor_loop.launcher.v1"
    status = "launcher_disabled_reference_only"
    pid = 0
    task_id = "overnight_supervisor_loop_phase0_batch_20260704"
    work_id = "xinao_seed_cortex_phase0_20260701"
    route_profile = "seed_cortex_phase0"
    intent_package = $IntentPackage
    runtime_root = $RuntimeRoot
    repo_root = $RepoRoot
    duration_hours = $DurationHours
    deadline_at = $DeadlineAt
    wave_interval_seconds = $WaveIntervalSeconds
    heartbeat_seconds = $HeartbeatSeconds
    stdout_log = $stdoutPath
    stderr_log = $stderrPath
    pid_ref = $pidPath
    readback_zh = (Join-Path $RuntimeRoot "readback\zh\overnight_supervisor_loop_20260704.md")
    foreground_poll_required = $false
    poll_owner = "none_reference_only"
    user_prompts_required = $false
    watchdog_only = $true
    disabled = $true
    reference_only = $true
    not_main_loop = $true
    not_task_owner = $true
    not_completion_boundary = $true
    not_watch_owner = $true
    sleep_1800_default_main_loop_allowed = $false
    main_loop_replacement = "temporal_activity_event_queue_loop"
    completion_claim_allowed = $false
    not_user_completion = $true
    not_completion_decision = $true
    not_execution_controller = $true
    generated_at = (Get-Date).ToString("o")
}

Write-JsonAtomic -Path $launcherLatest -Value $payload
$payload | ConvertTo-Json -Depth 10
