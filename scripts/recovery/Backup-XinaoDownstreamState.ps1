[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$RuntimeRoot = $(if ($env:XINAO_RESEARCH_RUNTIME) { $env:XINAO_RESEARCH_RUNTIME } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$OutputRoot = '',
    [string]$TemporalAddress = '127.0.0.1:7233',
    [switch]$SkipLatestPointer,
    [switch]$NoQuiesce
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $RuntimeRoot 'recovery\downstream-state'
}
$composePath = Join-Path $RepoRoot 'docker-compose.yml'
if (-not (Test-Path -LiteralPath $composePath -PathType Leaf)) {
    throw "Compose file is missing: $composePath"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI is required for the downstream snapshot.'
}
if (-not (Get-Command sqlite3 -ErrorAction SilentlyContinue)) {
    throw 'Pinned or system sqlite3 CLI is required for a consistent LangGraph backup.'
}

$runId = 'downstream-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$runDirectory = Join-Path $OutputRoot $runId
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $output = & docker compose -f $composePath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Arguments -join ' ') :: $($output -join ' ')"
    }
    return @($output)
}

function Write-JsonAtomic {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)]$Value)
    $temporary = "$Path.$PID.tmp"
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporary -Encoding utf8NoBOM
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

$openWorkflows = @()
$openWorkflowsStatus = 'unavailable'
if (Get-Command temporal -ErrorAction SilentlyContinue) {
    try {
        $workflowJson = (& temporal workflow list --address $TemporalAddress --query 'ExecutionStatus="Running"' --limit 200 --output json 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $workflowJson) {
            $parsed = $workflowJson | ConvertFrom-Json -Depth 30
            $openWorkflows = @($parsed | ForEach-Object {
                [ordered]@{
                    workflow_id = [string]$_.execution.workflowId
                    run_id = [string]$_.execution.runId
                    type = [string]$_.type.name
                    status = [string]$_.status
                    start_time = [string]$_.startTime
                }
            })
            $openWorkflowsStatus = 'captured_before_quiesce'
        }
        elseif ($LASTEXITCODE -eq 0) {
            $openWorkflowsStatus = 'captured_empty_before_quiesce'
        }
    }
    catch {
        $openWorkflowsStatus = 'unavailable'
    }
}

$runningServices = @(
    Invoke-Compose -Arguments @('ps', '--status', 'running', '--services') |
        ForEach-Object { ([string]$_).Trim() } |
        Where-Object { $_ }
)
$quiesceOrder = @('houtai-gongren', 'mowei-zhixing', 'naijiu-shiwu')
$servicesToQuiesce = @($quiesceOrder | Where-Object { $_ -in $runningServices })
$stoppedBySnapshot = [System.Collections.Generic.List[string]]::new()
$snapshotStatus = if ($NoQuiesce) { 'verified_component_archives' } else { 'verified_quiesced_snapshot' }

try {
    if (-not $NoQuiesce) {
        $workersToStop = @($servicesToQuiesce | Where-Object { $_ -ne 'naijiu-shiwu' })
        if ($workersToStop.Count -gt 0) {
            Invoke-Compose -Arguments (@('stop', '--timeout', '30') + $workersToStop) | Out-Null
            foreach ($service in $workersToStop) { $stoppedBySnapshot.Add($service) }
        }
        if ('naijiu-shiwu' -in $servicesToQuiesce) {
            Invoke-Compose -Arguments @('stop', '--timeout', '30', 'naijiu-shiwu') | Out-Null
            $stoppedBySnapshot.Add('naijiu-shiwu')
        }
    }

    $containerId = ((Invoke-Compose -Arguments @('ps', '-q', 'shiwu-ku')) | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($containerId)) {
    throw 'The shiwu-ku PostgreSQL container is not running.'
}
$pgUser = ((Invoke-Compose -Arguments @(
    'exec', '-T', 'shiwu-ku', 'sh', '-lc', 'printf %s "${POSTGRES_USER:-postgres}"'
)) | Out-String).Trim()
$pgDatabase = ((Invoke-Compose -Arguments @(
    'exec', '-T', 'shiwu-ku', 'sh', '-lc', 'printf %s "${POSTGRES_DB:-postgres}"'
)) | Out-String).Trim()

$databaseRows = Invoke-Compose -Arguments @(
    'exec', '-T', 'shiwu-ku', 'psql', '-U', $pgUser, '-d', $pgDatabase,
    '-At', '-F', '|', '-c',
    "select datname,pg_database_size(datname) from pg_database where datname like 'temporal%' order by datname"
)
$databases = [System.Collections.Generic.List[object]]::new()
foreach ($row in $databaseRows) {
    if ([string]::IsNullOrWhiteSpace([string]$row)) { continue }
    $parts = ([string]$row).Split('|', 2)
    if ($parts.Count -ne 2 -or $parts[0] -notmatch '^[A-Za-z0-9_]+$') {
        throw "Unexpected PostgreSQL database inventory row: $row"
    }
    $databaseName = $parts[0]
    $containerDump = "/tmp/$runId-$databaseName.dump"
    $hostDump = Join-Path $runDirectory "$databaseName.dump"
    try {
        Invoke-Compose -Arguments @(
            'exec', '-T', 'shiwu-ku', 'pg_dump', '-U', $pgUser, '-d', $databaseName,
            '--format=c', '--no-owner', '--no-privileges', '--file', $containerDump
        ) | Out-Null
        Invoke-Compose -Arguments @(
            'exec', '-T', 'shiwu-ku', 'pg_restore', '--list', $containerDump
        ) | Out-Null
        $copyOutput = & docker cp "${containerId}:$containerDump" $hostDump 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "docker cp failed for ${databaseName}: $($copyOutput -join ' ')"
        }
    }
    finally {
        try {
            Invoke-Compose -Arguments @('exec', '-T', 'shiwu-ku', 'rm', '-f', $containerDump) | Out-Null
        }
        catch {
            Write-Warning "Could not remove container temporary dump: $containerDump"
        }
    }
    $dumpItem = Get-Item -LiteralPath $hostDump
    $databases.Add([ordered]@{
        name = $databaseName
        source_size_bytes = [int64]$parts[1]
        archive = $dumpItem.Name
        archive_size_bytes = [int64]$dumpItem.Length
        sha256 = (Get-FileHash -LiteralPath $hostDump -Algorithm SHA256).Hash.ToLowerInvariant()
        format = 'postgresql_custom_no_owner_no_privileges'
    })
}
if ($databases.Count -lt 2) {
    throw "Expected Temporal core and visibility databases; found $($databases.Count)."
}

$langGraphSource = Join-Path $RuntimeRoot 'state\langgraph_checkpoint\integrated_bus.sqlite'
if (-not (Test-Path -LiteralPath $langGraphSource -PathType Leaf)) {
    throw "LangGraph checkpoint is missing: $langGraphSource"
}
$langGraphBackup = Join-Path $runDirectory 'integrated_bus.sqlite'
$sqliteTarget = $langGraphBackup.Replace('\', '/')
$sqliteOutput = & sqlite3 $langGraphSource ".backup '$sqliteTarget'" 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "sqlite backup failed: $($sqliteOutput -join ' ')"
}
$integrity = (& sqlite3 $langGraphBackup 'PRAGMA quick_check;' 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $integrity -ne 'ok') {
    throw "LangGraph backup integrity check failed: $integrity"
}

$wslConfig = Join-Path $env:USERPROFILE '.wslconfig'
$wslEntry = $null
if (Test-Path -LiteralPath $wslConfig -PathType Leaf) {
    $wslCopy = Join-Path $runDirectory 'wslconfig.txt'
    Copy-Item -LiteralPath $wslConfig -Destination $wslCopy -Force
    $wslEntry = [ordered]@{
        file = (Split-Path -Leaf $wslCopy)
        sha256 = (Get-FileHash -LiteralPath $wslCopy -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$composeHashes = @(
    Invoke-Compose -Arguments @('config', '--hash', '*') |
        ForEach-Object {
            $parts = ([string]$_).Trim().Split(' ', 2, [StringSplitOptions]::RemoveEmptyEntries)
            if ($parts.Count -eq 2) { [ordered]@{ service = $parts[0]; sha256 = $parts[1] } }
        }
)
$composeImages = @(
    Invoke-Compose -Arguments @('config', '--images') |
        ForEach-Object { ([string]$_).Trim() } |
        Where-Object { $_ } |
        Sort-Object -Unique
)
$composeVolumes = @(
    Invoke-Compose -Arguments @('config', '--volumes') |
        ForEach-Object { ([string]$_).Trim() } |
        Where-Object { $_ } |
        Sort-Object -Unique
)

$langGraphItem = Get-Item -LiteralPath $langGraphBackup
$manifest = [ordered]@{
    schema_version = 'xinao.downstream_recovery_snapshot.v1'
    snapshot_id = $runId
    captured_at = (Get-Date).ToString('o')
    status = $snapshotStatus
    source = [ordered]@{
        repo_root = $RepoRoot
        compose_file = $composePath
        compose_sha256 = (Get-FileHash -LiteralPath $composePath -Algorithm SHA256).Hash.ToLowerInvariant()
        runtime_root = $RuntimeRoot
        temporal_address = $TemporalAddress
    }
    restore_semantics = [ordered]@{
        downstream_truth = @('temporal_postgresql_core', 'temporal_postgresql_visibility', 'langgraph_sqlite')
        credentials_included = $false
        docker_images_included = $false
        restore_requires_native_reauthentication = $true
        live_target_replacement_requires_explicit_replace_existing_switch = $true
        cross_component_point_in_time = if ($NoQuiesce) { 'not_claimed' } else { 'application_writers_quiesced' }
    }
    postgres = [ordered]@{
        service = 'shiwu-ku'
        databases = @($databases)
    }
    langgraph = [ordered]@{
        source = $langGraphSource
        archive = $langGraphItem.Name
        archive_size_bytes = [int64]$langGraphItem.Length
        sha256 = (Get-FileHash -LiteralPath $langGraphBackup -Algorithm SHA256).Hash.ToLowerInvariant()
        quick_check = $integrity
    }
    wsl = $wslEntry
    compose = [ordered]@{
        service_hashes = $composeHashes
        images = $composeImages
        volumes = $composeVolumes
    }
    open_workflows = $openWorkflows
    open_workflows_inventory_status = $openWorkflowsStatus
    evidence = [ordered]@{
        postgresql_archives_listed_by_pg_restore = $true
        langgraph_sqlite_quick_check = $integrity
        credential_values_exported = $false
        opaque_payloads_may_contain_user_task_material = $true
        application_writes_quiesced = (-not $NoQuiesce)
        quiesced_services = @($stoppedBySnapshot)
        closure_claim_allowed = (-not $NoQuiesce)
    }
}
$manifestPath = Join-Path $runDirectory 'manifest.json'
Write-JsonAtomic -Path $manifestPath -Value $manifest
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
$latest = [ordered]@{
    schema_version = 'xinao.downstream_recovery_latest.v1'
    snapshot_id = $runId
    snapshot_directory = $runDirectory
    manifest = $manifestPath
    manifest_sha256 = $manifestHash
    captured_at = $manifest.captured_at
}
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
if (-not $SkipLatestPointer) {
    Write-JsonAtomic -Path (Join-Path $OutputRoot 'latest.json') -Value $latest
}
}
finally {
    if ($stoppedBySnapshot.Count -gt 0) {
        if ('naijiu-shiwu' -in $stoppedBySnapshot) {
            Invoke-Compose -Arguments @('start', 'naijiu-shiwu') | Out-Null
            $temporalReady = $false
            for ($attempt = 0; $attempt -lt 60; $attempt++) {
                $health = (& docker inspect --format '{{.State.Health.Status}}' naijiu-shiwu 2>$null | Out-String).Trim()
                if ($LASTEXITCODE -eq 0 -and $health -eq 'healthy') {
                    $temporalReady = $true
                    break
                }
                Start-Sleep -Seconds 2
            }
            if (-not $temporalReady) {
                throw 'Temporal service did not become healthy after downstream snapshot.'
            }
        }
        $workersToRestart = @($stoppedBySnapshot | Where-Object { $_ -ne 'naijiu-shiwu' })
        if ($workersToRestart.Count -gt 0) {
            Invoke-Compose -Arguments (@('start') + $workersToRestart) | Out-Null
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $runDirectory 'manifest.json') -PathType Leaf) -and
        @(Get-ChildItem -LiteralPath $runDirectory -Force -ErrorAction SilentlyContinue).Count -eq 0) {
        Remove-Item -LiteralPath $runDirectory
    }
}

[ordered]@{
    status = $snapshotStatus
    snapshot_id = $runId
    snapshot_directory = $runDirectory
    manifest = $manifestPath
    database_count = $databases.Count
    open_workflow_count = $openWorkflows.Count
    credentials_exported = $false
    application_writes_quiesced = (-not $NoQuiesce)
    latest_pointer_updated = (-not $SkipLatestPointer)
} | ConvertTo-Json -Depth 8
