#Requires -Version 7.2
<#
.SYNOPSIS
  Start promoted Temporal worker as a Hidden host process (no compose recreate).

.DESCRIPTION
  G23/G1 ops helper. Sets PYTHONPATH=repo+src, launches adapters/temporal/run_worker.py
  Hidden (CreateNoWindow / WindowStyle Hidden), and writes pid + logs under the evidence
  dir (default: saturation/G1_temporal_worker).

  Does not touch client/policy/service/cli/mcp/pyproject. Does not docker compose.

.PARAMETER ProjectRoot
  dual-brain-coordination repo root

.PARAMETER EvidenceDir
  Directory for worker_pid.txt / logs (default night-run G1_temporal_worker)

.PARAMETER PythonExe
  Optional override for python.exe

.PARAMETER PassThru
  Return process metadata object to the caller
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$ProjectRoot = 'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination',
    [string]$EvidenceDir = 'D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712\saturation\G1_temporal_worker',
    [string]$PythonExe = '',
    [string]$Address = '127.0.0.1:7233',
    [string]$Namespace = 'default',
    [string]$TaskQueue = 'xinao-dualbrain-promoted-v1',
    [string]$WorkerIdentity = 'xinao-promoted-worker-g1',
    [string]$DeploymentManifest = '',
    [string]$DeploymentName = '',
    [string]$BuildId = '',
    [switch]$Unversioned,
    [switch]$PassThru
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProgressPreference = 'SilentlyContinue'

$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
[void][IO.Directory]::CreateDirectory($EvidenceDir)

function Resolve-PythonExe {
    param([string]$Root, [string]$Override)
    if ($Override -and (Test-Path -LiteralPath $Override -PathType Leaf)) {
        return [IO.Path]::GetFullPath($Override)
    }
    $candidates = @(
        (Join-Path $Root '.venv\Scripts\python.exe'),
        (Join-Path $Root 'venv\Scripts\python.exe')
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c -PathType Leaf) {
            return [IO.Path]::GetFullPath($c)
        }
    }
    throw "PYTHON_NOT_FOUND: project .venv missing under $Root"
}

$py = Resolve-PythonExe -Root $ProjectRoot -Override $PythonExe
$entry = Join-Path $ProjectRoot 'adapters\temporal\run_worker.py'
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw "MISSING_ENTRY: $entry"
}

$manifestPath = $DeploymentManifest
if (-not $manifestPath) {
    $manifestPath = Join-Path $ProjectRoot 'adapters\temporal\worker_deployment.v1.json'
}
$manifest = $null
if (-not $Unversioned -and (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json -Depth 20
    if (-not $DeploymentName) { $DeploymentName = [string]$manifest.deployment_name }
    if (-not $BuildId) { $BuildId = [string]$manifest.build_id }
}
$useWorkerVersioning = -not $Unversioned -and [bool]$BuildId
if ($useWorkerVersioning -and -not $DeploymentName) {
    throw 'XINAO_TEMPORAL_WORKER_VERSIONING_IDENTITY_REQUIRED: deployment name missing'
}

$srcDir = Join-Path $ProjectRoot 'src'
# Required: repo (adapters.*) + src (xinao_coordination.*)
$pythonPath = ($ProjectRoot, $srcDir) -join [IO.Path]::PathSeparator
if ($env:PYTHONPATH -and $env:PYTHONPATH.Trim().Length -gt 0) {
    $pythonPath = $pythonPath + [IO.Path]::PathSeparator + $env:PYTHONPATH
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$stdoutLog = Join-Path $EvidenceDir ("worker_stdout_{0}.log" -f $stamp)
$stderrLog = Join-Path $EvidenceDir ("worker_stderr_{0}.log" -f $stamp)
# Stable alias paths (overwritten each start) for tooling that expects fixed names.
$stdoutAlias = Join-Path $EvidenceDir 'worker_stdout.log'
$stderrAlias = Join-Path $EvidenceDir 'worker_stderr.log'
$startLog = Join-Path $EvidenceDir 'worker_start.log'
$pidFile = Join-Path $EvidenceDir 'worker_pid.txt'
$bootStamp = (Get-Date).ToUniversalTime().ToString('o')

# Child inherits this process env.
$env:PYTHONPATH = $pythonPath
$env:XINAO_TEMPORAL_ADDRESS = $Address
$env:XINAO_TEMPORAL_NAMESPACE = $Namespace
$env:XINAO_TEMPORAL_TASK_QUEUE = $TaskQueue
$env:XINAO_TEMPORAL_WORKER_LOG = $startLog
if ($WorkerIdentity) {
    $env:XINAO_TEMPORAL_WORKER_IDENTITY = $WorkerIdentity
}
if ($useWorkerVersioning) {
    $env:XINAO_TEMPORAL_WORKER_VERSIONING = '1'
    $env:XINAO_TEMPORAL_WORKER_DEPLOYMENT_NAME = $DeploymentName
    $env:XINAO_TEMPORAL_WORKER_BUILD_ID = $BuildId
}
else {
    Remove-Item Env:XINAO_TEMPORAL_WORKER_VERSIONING -ErrorAction SilentlyContinue
    Remove-Item Env:XINAO_TEMPORAL_WORKER_DEPLOYMENT_NAME -ErrorAction SilentlyContinue
    Remove-Item Env:XINAO_TEMPORAL_WORKER_BUILD_ID -ErrorAction SilentlyContinue
}

# Start-Process with RedirectStandard* uses UseShellExecute=false and keeps
# file handles in the OS for the child lifetime (parent may exit safely).
# WindowStyle Hidden + no new console reduces flash vs bare console subsystem.
$proc = Start-Process `
    -FilePath $py `
    -ArgumentList @($entry) `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

if (-not $proc) {
    throw "WORKER_START_FAILED: Start-Process returned null for $entry"
}

Start-Sleep -Milliseconds 900
# Refresh HasExited
try { $null = $proc.Refresh() } catch { }
$alive = $false
try { $alive = -not $proc.HasExited } catch { $alive = $false }
$pidValue = $proc.Id

# Stable aliases (best-effort copy of the first chunk / path pointer via hardlink-ish copy)
try {
    Copy-Item -LiteralPath $stdoutLog -Destination $stdoutAlias -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $stderrLog -Destination $stderrAlias -Force -ErrorAction SilentlyContinue
} catch { }

$pidLine = "new_pid={0} alive={1} entry=adapters/temporal/run_worker.py queue={2} versioning={3} deployment={4} build_id={5} method=Start-Process.WindowStyle.Hidden PYTHONPATH=repo+src utc={6}" -f `
    $pidValue, $alive, $TaskQueue, $useWorkerVersioning, $DeploymentName, $BuildId, $bootStamp
[IO.File]::WriteAllText($pidFile, $pidLine + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

try {
    $marker = "{0} INFO g23.start_worker_hidden started pid={1} alive={2} address={3} queue={4} identity={5} versioning={6} deployment={7} build_id={8} stdout={9}" -f `
        (Get-Date -Format 'yyyy-MM-dd HH:mm:ss,fff'), $pidValue, $alive, $Address, $TaskQueue, $WorkerIdentity, $useWorkerVersioning, $DeploymentName, $BuildId, $stdoutLog
    [IO.File]::AppendAllText($startLog, $marker + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
} catch { }

$meta = [ordered]@{
    schema           = 'g23.start_worker_hidden.v2'
    started_at_utc   = $bootStamp
    pid              = $pidValue
    alive            = $alive
    exit_code        = $(if ($alive) { $null } else { try { $proc.ExitCode } catch { $null } })
    method           = 'Start-Process -WindowStyle Hidden -RedirectStandardOutput/Error'
    python_exe       = $py
    entry            = $entry
    project_root     = $ProjectRoot
    pythonpath       = $pythonPath
    address          = $Address
    namespace        = $Namespace
    task_queue       = $TaskQueue
    worker_identity  = $WorkerIdentity
    use_worker_versioning = [bool]$useWorkerVersioning
    deployment_manifest = $(if ($manifest) { $manifestPath } else { $null })
    deployment_name  = $(if ($useWorkerVersioning) { $DeploymentName } else { $null })
    build_id         = $(if ($useWorkerVersioning) { $BuildId } else { $null })
    evidence_dir     = $EvidenceDir
    pid_file         = $pidFile
    stdout_log       = $stdoutLog
    stderr_log       = $stderrLog
    start_log        = $startLog
    compose_recreate = $false
}

if (-not $alive) {
    $errTail = ''
    try {
        if (Test-Path -LiteralPath $stderrLog) {
            $errTail = (Get-Content -LiteralPath $stderrLog -Tail 40 -ErrorAction SilentlyContinue) -join "`n"
        }
    } catch { }
    throw ("WORKER_EXITED_IMMEDIATELY: pid={0} exit_code={1} stderr_tail=`n{2}" -f $pidValue, $meta.exit_code, $errTail)
}

Write-Host ("start_worker_hidden: pid={0} alive={1} log={2}" -f $pidValue, $alive, $startLog)

if ($PassThru) {
    return [pscustomobject]$meta
}
