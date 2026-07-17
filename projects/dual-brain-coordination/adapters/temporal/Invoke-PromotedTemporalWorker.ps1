#Requires -Version 7.2
<#
.SYNOPSIS
  Reproducible promoted Temporal worker ensure: describe pollers → start if missing.

.DESCRIPTION
  G23 ops entry for queue xinao-dualbrain-promoted-v1:
    1) temporal task-queue describe (real poller identities; never mock)
    2) if pollers present → record identities (no second worker unless -ForceStart)
    3) if no pollers → start via start_worker_hidden.ps1 (Hidden, PYTHONPATH=repo+src)
    4) write pid/log under G1_temporal_worker and G23_worker_ops.json

  This worker-only helper never mutates the Temporal server or compose stack.
  Server/schema migrations use their separately preregistered canary and rollback.

.PARAMETER ProjectRoot
  dual-brain-coordination repo root

.PARAMETER EvidenceDir
  Default night-run saturation/G1_temporal_worker

.PARAMETER ForceStart
  Start a worker even if pollers already present (ops only; not default)

.PARAMETER SkipStart
  Describe + evidence only; never start

.PARAMETER WaitPollerSec
  After start, wait up to N seconds for describe to show a poller
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$ProjectRoot = (Join-Path $PSScriptRoot '..\..'),
    [string]$EvidenceDir = 'D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712\saturation\G1_temporal_worker',
    [string]$Address = '127.0.0.1:7233',
    [string]$Namespace = 'default',
    [string]$TaskQueue = 'xinao-dualbrain-promoted-v1',
    [string]$WorkerIdentity = 'xinao-promoted-worker-g1',
    [string]$PythonExe = '',
    [string]$DeploymentManifest = '',
    [string]$DeploymentName = '',
    [string]$BuildId = '',
    [switch]$Unversioned,
    [string]$TemporalCli = '',
    [int]$WaitPollerSec = 20,
    [switch]$ForceStart,
    [switch]$SkipStart
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProgressPreference = 'SilentlyContinue'

$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
[void][IO.Directory]::CreateDirectory($EvidenceDir)

$startedUtc = (Get-Date).ToUniversalTime().ToString('o')
$opsPath = Join-Path $EvidenceDir 'G23_worker_ops.json'
$describeTxt = Join-Path $EvidenceDir 'queue_describe.txt'
$describeJson = Join-Path $EvidenceDir 'queue_describe.json'
$startScript = Join-Path $ProjectRoot 'adapters\temporal\start_worker_hidden.ps1'

function Resolve-TemporalCli {
    param([string]$Override)
    if ($Override -and (Test-Path -LiteralPath $Override -PathType Leaf)) {
        return [IO.Path]::GetFullPath($Override)
    }
    $cmd = Get-Command temporal -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    $wingetGuess = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    if (Test-Path -LiteralPath $wingetGuess) {
        $hit = Get-ChildItem -LiteralPath $wingetGuess -Filter 'temporal.exe' -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    throw 'TEMPORAL_CLI_NOT_FOUND: install Temporal CLI or pass -TemporalCli'
}

function Invoke-TaskQueueDescribe {
    param(
        [string]$Cli,
        [string]$Addr,
        [string]$Ns,
        [string]$Queue
    )
    $args = @(
        'task-queue', 'describe',
        '--task-queue', $Queue,
        '--address', $Addr,
        '--namespace', $Ns
    )
    $stdout = & $Cli @args 2>&1 | Out-String
    $rc = $LASTEXITCODE
    return [pscustomobject]@{
        exit_code = $rc
        text      = $stdout
    }
}

function Parse-PollerIdentities {
    param([string]$Text)
    $identities = [System.Collections.Generic.List[string]]::new()
    if (-not $Text) { return @() }

    # Typical table row:
    #   UNVERSIONED  workflow       31440@DESKTOP-IB5LQL0  44 seconds ago         100000
    # or identity=xinao-promoted-worker-g1
    foreach ($line in ($Text -split "`r?`n")) {
        $trim = $line.Trim()
        if (-not $trim) { continue }
        if ($trim -match '^(Task Queue|Pollers|BuildID|UNVERSIONED\s+BuildID)') { continue }
        if ($trim -notmatch 'workflow|activity') { continue }
        # identity token: either custom name or pid@host
        if ($trim -match '\s(xinao-promoted-worker[\w\-]*)\s') {
            $id = $Matches[1]
            if (-not $identities.Contains($id)) { [void]$identities.Add($id) }
            continue
        }
        if ($trim -match '\s(\d+@[A-Za-z0-9\-\._]+)\s') {
            $id = $Matches[1]
            if (-not $identities.Contains($id)) { [void]$identities.Add($id) }
            continue
        }
        if ($trim -match '\s([A-Za-z0-9][A-Za-z0-9_\-@\.]{2,80})\s+\d+\s+(second|minute|hour|day)') {
            $id = $Matches[1]
            if ($id -match '^(workflow|activity|UNVERSIONED|BuildID)$') { continue }
            if (-not $identities.Contains($id)) { [void]$identities.Add($id) }
        }
    }
    return @($identities)
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value
    )
    $parent = Split-Path -Parent $Path
    [void][IO.Directory]::CreateDirectory($parent)
    $temp = Join-Path $parent ('.{0}.{1}.{2}.tmp' -f ([IO.Path]::GetFileName($Path)), $PID, [guid]::NewGuid().ToString('N'))
    $json = $Value | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($temp, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

$cli = Resolve-TemporalCli -Override $TemporalCli
Write-Host "==> G23 Invoke-PromotedTemporalWorker" -ForegroundColor Cyan
Write-Host "    task_queue=$TaskQueue address=$Address"
Write-Host "    evidence=$EvidenceDir"
Write-Host "    temporal_cli=$cli"

$describe1 = Invoke-TaskQueueDescribe -Cli $cli -Addr $Address -Ns $Namespace -Queue $TaskQueue
[IO.File]::WriteAllText($describeTxt, $describe1.text, [Text.UTF8Encoding]::new($false))

$identities = @(Parse-PollerIdentities -Text $describe1.text)
$pollersPresent = ($identities.Count -gt 0)
# Heuristic backup: "Pollers:" section with later pid@host even if parser missed
if (-not $pollersPresent -and $describe1.text -match 'Pollers:' -and $describe1.text -match '\d+@[A-Za-z0-9\-]+') {
    $pollersPresent = $true
    if ($identities.Count -eq 0) {
        $identities = @([regex]::Matches($describe1.text, '(\d+@[A-Za-z0-9\-\._]+)') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
    }
}

Write-Host ("    pollers_present={0} identities={1}" -f $pollersPresent, ($identities -join ', '))

$action = 'record_existing_poller'
$startMeta = $null
$startedWorker = $false
$notes = [System.Collections.Generic.List[string]]::new()
[void]$notes.Add('Scope: adapters/temporal/** + evidence G1/G23 only.')
[void]$notes.Add('This helper is worker-only; server/schema migration is a separate preregistered operation.')

if ($pollersPresent -and -not $ForceStart) {
    $action = 'record_existing_poller'
    [void]$notes.Add('Pollers already present; identities recorded; worker not re-started (idempotent ensure).')
}
elseif ($SkipStart) {
    $action = 'describe_only_skip_start'
    [void]$notes.Add('SkipStart set; no worker launch.')
}
else {
    if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
        throw "MISSING: $startScript"
    }
    $action = $(if ($ForceStart -and $pollersPresent) { 'force_start_additional_worker' } else { 'start_worker_no_poller' })
    Write-Host "    action=$action → start_worker_hidden.ps1" -ForegroundColor Yellow
    $startMeta = & $startScript `
        -ProjectRoot $ProjectRoot `
        -EvidenceDir $EvidenceDir `
        -PythonExe $PythonExe `
        -Address $Address `
        -Namespace $Namespace `
        -TaskQueue $TaskQueue `
        -WorkerIdentity $WorkerIdentity `
        -DeploymentManifest $DeploymentManifest `
        -DeploymentName $DeploymentName `
        -BuildId $BuildId `
        -Unversioned:$Unversioned `
        -PassThru
    $startedWorker = $true
    [void]$notes.Add(("Started Hidden worker pid={0} method={1}" -f $startMeta.pid, $startMeta.method))

    # Wait for poller to appear
    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $WaitPollerSec))
    do {
        Start-Sleep -Seconds 2
        $describe1 = Invoke-TaskQueueDescribe -Cli $cli -Addr $Address -Ns $Namespace -Queue $TaskQueue
        $identities = @(Parse-PollerIdentities -Text $describe1.text)
        if ($identities.Count -eq 0 -and $describe1.text -match '\d+@[A-Za-z0-9\-]+') {
            $identities = @([regex]::Matches($describe1.text, '(\d+@[A-Za-z0-9\-\._]+)') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
        }
        $pollersPresent = ($identities.Count -gt 0)
        if ($pollersPresent) { break }
    } while ((Get-Date) -lt $deadline)

    [IO.File]::WriteAllText($describeTxt, $describe1.text, [Text.UTF8Encoding]::new($false))
    if ($pollersPresent) {
        [void]$notes.Add(("Post-start pollers ok: {0}" -f ($identities -join ', ')))
    }
    else {
        [void]$notes.Add("Post-start describe still empty pollers within WaitPollerSec=$WaitPollerSec")
    }
}

$describePayload = [ordered]@{
    captured_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    address         = $Address
    namespace       = $Namespace
    task_queue      = $TaskQueue
    exit_code       = $describe1.exit_code
    pollers_present = [bool]$pollersPresent
    identities      = @($identities)
    text_path       = $describeTxt
    text_excerpt    = if ($describe1.text.Length -gt 4000) { $describe1.text.Substring(0, 4000) } else { $describe1.text }
}
Write-JsonAtomic -Path $describeJson -Value $describePayload

$verdict = if ($pollersPresent) {
    if ($startedWorker) { 'PASS_WORKER_STARTED_POLLER_OK' } else { 'PASS_POLLER_ALREADY_PRESENT' }
}
else {
    if ($startedWorker) { 'FAIL_STARTED_BUT_NO_POLLER' } else { 'FAIL_NO_POLLER_NO_START' }
}

$ops = [ordered]@{
    schema_version            = 'xinao.g23_worker_ops.v1'
    station                   = 'G23'
    role                      = 'temporal_worker_reproducible_start'
    generated_at_utc          = (Get-Date).ToUniversalTime().ToString('o')
    started_at_utc            = $startedUtc
    verdict                   = $verdict
    action                    = $action
    task_queue                = $TaskQueue
    address                   = $Address
    namespace                 = $Namespace
    worker_identity_requested = $WorkerIdentity
    deployment_manifest       = $DeploymentManifest
    deployment_name_requested = $DeploymentName
    build_id_requested        = $BuildId
    unversioned_requested     = [bool]$Unversioned
    pollers_present           = [bool]$pollersPresent
    poller_identities         = @($identities)
    poller_count              = @($identities).Count
    worker_started            = [bool]$startedWorker
    force_start               = [bool]$ForceStart
    skip_start                = [bool]$SkipStart
    start                     = $startMeta
    entry                     = 'adapters/temporal/run_worker.py'
    start_script              = 'adapters/temporal/start_worker_hidden.ps1'
    invoke_script             = 'adapters/temporal/Invoke-PromotedTemporalWorker.ps1'
    pythonpath_policy         = 'repo + src (prepended)'
    hidden_policy             = 'Start-Process -WindowStyle Hidden + redirected stdio logs'
    evidence_dir              = $EvidenceDir
    evidence_paths            = @(
        $opsPath,
        $describeTxt,
        $describeJson,
        (Join-Path $EvidenceDir 'worker_pid.txt'),
        (Join-Path $EvidenceDir 'worker_start.log')
    )
    scope                     = @(
        'adapters/temporal/**',
        'saturation/G1_temporal_worker',
        'G23_worker_ops.json'
    )
    forbidden_touched         = $false
    compose_recreate_attempted = $false
    desktop_commander_used    = $false
    product_closed            = $false
    completion_claim_allowed  = $false
    notes                     = @($notes)
}

Write-JsonAtomic -Path $opsPath -Value $ops

Write-Host ("==> verdict={0} action={1} pollers={2}" -f $verdict, $action, ($identities -join ', ')) -ForegroundColor Green
Write-Host "    wrote $opsPath"

if ($verdict -like 'FAIL*') {
    exit 2
}
exit 0
