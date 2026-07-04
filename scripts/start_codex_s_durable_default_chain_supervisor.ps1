[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "",
    [string]$SourceRoot = "",
    [string]$PackagePath = "",
    [string]$SupervisorWaveId = "codex-s-durable-default-chain-supervisor-20260704-night",
    [string]$ParentWaveId = "source-frontier-workerpool-global-closure-20260704-verify-wave",
    [string]$TaskQueue = "xinao-codex-task-default",
    [int]$PollSeconds = 180,
    [int]$MinDispatchIntervalSeconds = 600,
    [int]$MaxCycles = 0,
    [int]$WorkflowTimeoutSeconds = 180,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $anchorFolder = ([string][char]0x65B0) + ([string][char]0x7CFB) + ([string][char]0x7EDF)
    $SourceRoot = Join-Path ([Environment]::GetFolderPath("Desktop")) $anchorFolder
}
if ([string]::IsNullOrWhiteSpace($PackagePath)) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $candidates = @(Get-ChildItem -LiteralPath $desktop -File -Filter "*20260704.bak_before_closure_update.txt" | Sort-Object LastWriteTime -Descending)
    if ($candidates.Count -gt 0) {
        $PackagePath = [string]$candidates[0].FullName
    }
}
if ([string]::IsNullOrWhiteSpace($Python)) {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $Python = $venvPython
    } else {
        $Python = "python"
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

Assert-True (Test-Path -LiteralPath $RepoRoot -PathType Container) "RepoRoot missing: $RepoRoot"
Assert-True (Test-Path -LiteralPath $SourceRoot -PathType Container) "SourceRoot missing: $SourceRoot"
Assert-True (Test-Path -LiteralPath $PackagePath -PathType Leaf) "PackagePath missing: $PackagePath"

$waveStem = ($SupervisorWaveId -replace '[^A-Za-z0-9_.-]+','-').Trim('.-')
if ([string]::IsNullOrWhiteSpace($waveStem)) { $waveStem = "wave" }
$stateRoot = Join-Path $RuntimeRoot "state\codex_s_durable_default_chain_supervisor"
$processRoot = Join-Path $stateRoot "process"
$logRoot = Join-Path $stateRoot "waves\$waveStem\process_logs"
New-Item -ItemType Directory -Force -Path $processRoot, $logRoot | Out-Null

$stdout = Join-Path $logRoot "supervisor.stdout.log"
$stderr = Join-Path $logRoot "supervisor.stderr.log"
$argsList = @(
    "-m", "services.agent_runtime.codex_s_durable_default_chain_supervisor",
    "--runtime-root", $RuntimeRoot,
    "--repo-root", $RepoRoot,
    "--source-root", $SourceRoot,
    "--package-path", $PackagePath,
    "--supervisor-wave-id", $SupervisorWaveId,
    "--parent-wave-id", $ParentWaveId,
    "--task-queue", $TaskQueue,
    "--poll-seconds", [string]$PollSeconds,
    "--min-dispatch-interval-seconds", [string]$MinDispatchIntervalSeconds,
    "--max-cycles", [string]$MaxCycles,
    "--workflow-timeout-seconds", [string]$WorkflowTimeoutSeconds
)

$process = Start-Process -FilePath $Python `
    -ArgumentList $argsList `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru

$matchingProcesses = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*services.agent_runtime.codex_s_durable_default_chain_supervisor*" -and
    $_.CommandLine -like "*--supervisor-wave-id $SupervisorWaveId*"
} | Select-Object ProcessId,ParentProcessId,Name,CommandLine)

$record = [ordered]@{
    schema_version = "xinao.codex_s.durable_default_chain_supervisor.process.v1"
    sentinel = "SENTINEL:XINAO_CODEX_S_DURABLE_DEFAULT_CHAIN_SUPERVISOR_V1"
    status = "background_supervisor_started"
    launcher_pid = $process.Id
    observed_process_ids = @($matchingProcesses | ForEach-Object { $_.ProcessId })
    process_name = $process.ProcessName
    repo_root = $RepoRoot
    runtime_root = $RuntimeRoot
    source_root = $SourceRoot
    package_path = $PackagePath
    supervisor_wave_id = $SupervisorWaveId
    parent_wave_id = $ParentWaveId
    task_queue = $TaskQueue
    poll_seconds = $PollSeconds
    min_dispatch_interval_seconds = $MinDispatchIntervalSeconds
    max_cycles = $MaxCycles
    stdout_ref = $stdout
    stderr_ref = $stderr
    hidden_window = $true
    pid_record_may_include_python_launcher = $true
    observed_processes = @($matchingProcesses)
    completion_claim_allowed = $false
    not_execution_controller = $true
    started_at = (Get-Date).ToString("o")
}
$processPath = Join-Path $processRoot "$waveStem.json"
$record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $processPath -Encoding UTF8

Write-Output "supervisor_pid=$($process.Id)"
Write-Output "process_ref=$processPath"
Write-Output "stdout_ref=$stdout"
Write-Output "stderr_ref=$stderr"
Write-Output "SENTINEL:XINAO_CODEX_S_DURABLE_DEFAULT_CHAIN_SUPERVISOR_V1"
