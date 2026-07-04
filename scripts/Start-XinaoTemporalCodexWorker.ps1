param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$TaskQueue = "xinao-codex-task-default",
    [string]$CodexActivatorUrl = "http://127.0.0.1:19121",
    [string]$TaskName = "XINAO Seed Cortex S Temporal Worker",
    [switch]$InstallScheduledTask
)

$ErrorActionPreference = "Stop"

$stateDir = Join-Path $RuntimeRoot "state\temporal_codex_task_worker"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$logPath = Join-Path $stateDir "worker.stdout.log"
$errPath = Join-Path $stateDir "worker.stderr.log"
$pidPath = Join-Path $stateDir "worker.pid"
$evidencePath = Join-Path $stateDir "latest.json"
$scheduledTaskPath = Join-Path $stateDir "scheduled_task.json"

if ($InstallScheduledTask) {
    $scriptPath = $PSCommandPath
    $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -RepoRoot `"$RepoRoot`" -RuntimeRoot `"$RuntimeRoot`" -TaskQueue `"$TaskQueue`" -CodexActivatorUrl `"$CodexActivatorUrl`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Seed Cortex S long-lived Temporal worker polling xinao-codex-task-default. Not a completion source." -Force | Out-Null
    $taskPayload = [ordered]@{
        schema_version = "xinao.temporal_codex_task_worker.scheduled_task.v1"
        status = "registered"
        task_name = $TaskName
        task_queue = $TaskQueue
        repo_root = $RepoRoot
        runtime_root = $RuntimeRoot
        codex_activator_url = $CodexActivatorUrl
        poller_contract = "Temporal worker must poll xinao-codex-task-default; run_live_temporal_workflow must not create an inline Worker."
        verify_commands = @(
            "temporal task-queue describe --address 127.0.0.1:7233 --task-queue $TaskQueue --output json",
            "temporal workflow list --address 127.0.0.1:7233 --query `"TaskQueue='$TaskQueue'`""
        )
        generated_at = (Get-Date).ToString("o")
        route_profile = "seed_cortex_phase0"
        old_clean_runtime_authority = $false
        not_source_of_truth = $true
        not_user_completion = $true
        not_completion_decision = $true
    }
    $taskPayload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $scheduledTaskPath -Encoding UTF8
}

$existingPid = ""
if (Test-Path -LiteralPath $pidPath) {
    $existingPid = (Get-Content -LiteralPath $pidPath -Raw).Trim()
}
if ($existingPid -match '^\d+$') {
    $existing = Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue
    if ($existing) {
        $payload = [ordered]@{
            schema_version = "xinao.temporal_codex_task_worker.v1"
            status = "already_running"
            task_queue = $TaskQueue
            pid = [int]$existingPid
            codex_activator_url = $CodexActivatorUrl
            log = $logPath
            error_log = $errPath
            generated_at = (Get-Date).ToString("o")
            scheduled_task_name = $TaskName
            scheduled_task_ref = $scheduledTaskPath
            worker_polling_verify_command = "temporal task-queue describe --address 127.0.0.1:7233 --task-queue $TaskQueue --output json"
            workflow_list_verify_command = "temporal workflow list --address 127.0.0.1:7233 --query `"TaskQueue='$TaskQueue'`""
            route_profile = "seed_cortex_phase0"
            old_clean_runtime_authority = $false
            not_source_of_truth = $true
            not_user_completion = $true
            not_completion_decision = $true
        }
        $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
        $payload | ConvertTo-Json -Depth 6
        exit 0
    }
}

function Test-PythonTemporalio {
    param([string]$PythonPath)
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { return $false }
    & $PythonPath -c "import temporalio" 2>$null
    return $LASTEXITCODE -eq 0
}

$repoPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$runtimePython = Join-Path $RuntimeRoot "tool_envs\mature-runtime-py\Scripts\python.exe"
$systemPython = (Get-Command python).Source
if (Test-PythonTemporalio $repoPython) {
    $python = $repoPython
} elseif (Test-PythonTemporalio $runtimePython) {
    $python = $runtimePython
} else {
    $python = $systemPython
}

$args = @(
    "-m",
    "services.agent_runtime.temporal_codex_task_workflow",
    "--worker",
    "--task-queue",
    $TaskQueue,
    "--runtime-root",
    $RuntimeRoot
)

$env:CODEX_ACTIVATOR_URL = $CodexActivatorUrl

$proc = Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $RepoRoot -WindowStyle Hidden -RedirectStandardOutput $logPath -RedirectStandardError $errPath -PassThru
Set-Content -LiteralPath $pidPath -Value $proc.Id -Encoding ASCII

$payload = [ordered]@{
    schema_version = "xinao.temporal_codex_task_worker.v1"
    status = "started"
    task_queue = $TaskQueue
    pid = $proc.Id
    codex_activator_url = $CodexActivatorUrl
    log = $logPath
    error_log = $errPath
    generated_at = (Get-Date).ToString("o")
    scheduled_task_name = $TaskName
    scheduled_task_ref = $scheduledTaskPath
    worker_polling_verify_command = "temporal task-queue describe --address 127.0.0.1:7233 --task-queue $TaskQueue --output json"
    workflow_list_verify_command = "temporal workflow list --address 127.0.0.1:7233 --query `"TaskQueue='$TaskQueue'`""
    route_profile = "seed_cortex_phase0"
    old_clean_runtime_authority = $false
    not_source_of_truth = $true
    not_user_completion = $true
    not_completion_decision = $true
}
$payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
$payload | ConvertTo-Json -Depth 6
