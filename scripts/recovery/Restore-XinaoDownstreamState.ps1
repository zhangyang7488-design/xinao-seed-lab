[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$RuntimeRoot = $(if ($env:XINAO_RESEARCH_RUNTIME) { $env:XINAO_RESEARCH_RUNTIME } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$SnapshotDirectory = '',
    [string]$TemporalAddress = '127.0.0.1:7233',
    [switch]$ReplaceExisting,
    [switch]$SkipPostRestoreCanary
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$composePath = Join-Path $RepoRoot 'docker-compose.yml'
$backupScript = Join-Path $PSScriptRoot 'Backup-XinaoDownstreamState.ps1'
$verifyScript = Join-Path $PSScriptRoot 'Test-XinaoDownstreamRecovery.ps1'
$snapshotRoot = Join-Path $RuntimeRoot 'recovery\downstream-state'
if ([string]::IsNullOrWhiteSpace($SnapshotDirectory)) {
    $latest = Get-Content -LiteralPath (Join-Path $snapshotRoot 'latest.json') -Raw | ConvertFrom-Json -Depth 20
    $SnapshotDirectory = [string]$latest.snapshot_directory
}
$manifestPath = Join-Path $SnapshotDirectory 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Downstream snapshot manifest is missing: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -Depth 30
if ($manifest.schema_version -ne 'xinao.downstream_recovery_snapshot.v1') {
    throw "Unexpected downstream snapshot schema: $($manifest.schema_version)"
}

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

$containerId = ((Invoke-Compose -Arguments @('ps', '-q', 'shiwu-ku')) | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($containerId)) {
    throw 'The shiwu-ku PostgreSQL container must be running before downstream restore.'
}
$pgUser = ((Invoke-Compose -Arguments @(
    'exec', '-T', 'shiwu-ku', 'sh', '-lc', 'printf %s "${POSTGRES_USER:-postgres}"'
)) | Out-String).Trim()

$targetInventory = [System.Collections.Generic.List[object]]::new()
foreach ($database in @($manifest.postgres.databases)) {
    $name = [string]$database.name
    if ($name -notmatch '^[A-Za-z0-9_]+$') { throw "Unsafe database name in snapshot: $name" }
    $tableCountText = ((Invoke-Compose -Arguments @(
        'exec', '-T', 'shiwu-ku', 'psql', '-U', $pgUser, '-d', $name,
        '-At', '-c', "select count(*) from information_schema.tables where table_schema not in ('pg_catalog','information_schema')"
    )) | Out-String).Trim()
    $tableCount = 0
    [void][int]::TryParse($tableCountText, [ref]$tableCount)
    $targetInventory.Add([ordered]@{ database = $name; user_table_count = $tableCount })
}

if (-not $ReplaceExisting) {
    [ordered]@{
        status = 'existing_target_preserved'
        reason = 'Pass -ReplaceExisting only from a verified fresh-machine recovery transaction.'
        snapshot_directory = $SnapshotDirectory
        target_inventory = @($targetInventory)
        mutation_performed = $false
    } | ConvertTo-Json -Depth 8
    exit 2
}

$operationId = 'restore-downstream-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$operationRoot = Join-Path $RuntimeRoot "state\downstream_recovery_operations\$operationId"
New-Item -ItemType Directory -Force -Path $operationRoot | Out-Null
$operationPath = Join-Path $operationRoot 'operation.json'
$operation = [ordered]@{
    schema_version = 'xinao.downstream_recovery_operation.v1'
    operation_id = $operationId
    started_at = (Get-Date).ToString('o')
    source_snapshot = $SnapshotDirectory
    source_manifest_sha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    target_inventory = @($targetInventory)
    authority = 'fresh_machine_recovery_replace_existing_switch'
    trusted_local_snapshot = $true
    pre_restore_snapshot = $null
    state = 'captured'
    rollback_attempted = $false
    rollback_status = 'not_needed'
}
Write-JsonAtomic -Path $operationPath -Value $operation

$preRestoreJson = & $backupScript -RepoRoot $RepoRoot -RuntimeRoot $RuntimeRoot `
    -SkipLatestPointer 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { throw "Pre-restore rollback snapshot failed: $preRestoreJson" }
$preRestore = $preRestoreJson | ConvertFrom-Json -Depth 20
$operation.pre_restore_snapshot = [string]$preRestore.snapshot_directory
$operation.state = 'pre_restore_snapshot_verified'
Write-JsonAtomic -Path $operationPath -Value $operation

function Restore-Snapshot {
    param([Parameter(Mandatory)][string]$Directory)
    $sourceManifest = Get-Content -LiteralPath (Join-Path $Directory 'manifest.json') -Raw | ConvertFrom-Json -Depth 30
    foreach ($database in @($sourceManifest.postgres.databases)) {
        $name = [string]$database.name
        if ($name -notmatch '^[A-Za-z0-9_]+$') { throw "Unsafe database name: $name" }
        $archive = Join-Path $Directory ([string]$database.archive)
        $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne [string]$database.sha256) { throw "Snapshot hash mismatch: $archive" }
        $containerArchive = "/tmp/$operationId-$name.dump"
        try {
            $copyOutput = & docker cp $archive "${containerId}:$containerArchive" 2>&1
            if ($LASTEXITCODE -ne 0) { throw "docker cp failed: $($copyOutput -join ' ')" }
            Invoke-Compose -Arguments @(
                'exec', '-T', 'shiwu-ku', 'psql', '-U', $pgUser, '-d', 'postgres', '-v', 'ON_ERROR_STOP=1',
                '-c', "select pg_terminate_backend(pid) from pg_stat_activity where datname='$name' and pid<>pg_backend_pid()"
            ) | Out-Null
            Invoke-Compose -Arguments @('exec', '-T', 'shiwu-ku', 'dropdb', '-U', $pgUser, '--if-exists', '--force', $name) | Out-Null
            Invoke-Compose -Arguments @('exec', '-T', 'shiwu-ku', 'createdb', '-U', $pgUser, '-T', 'template0', $name) | Out-Null
            Invoke-Compose -Arguments @(
                'exec', '-T', 'shiwu-ku', 'pg_restore', '-U', $pgUser,
                '--exit-on-error', '--no-owner', '--no-privileges', '-d', $name, $containerArchive
            ) | Out-Null
        }
        finally {
            try { Invoke-Compose -Arguments @('exec', '-T', 'shiwu-ku', 'rm', '-f', $containerArchive) | Out-Null } catch { }
        }
    }
    $langGraphArchive = Join-Path $Directory ([string]$sourceManifest.langgraph.archive)
    $langGraphTarget = Join-Path $RuntimeRoot 'state\langgraph_checkpoint\integrated_bus.sqlite'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $langGraphTarget) | Out-Null
    Copy-Item -LiteralPath $langGraphArchive -Destination $langGraphTarget -Force
    $integrity = (& sqlite3 $langGraphTarget 'PRAGMA quick_check;' 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $integrity -ne 'ok') { throw "Restored LangGraph SQLite failed integrity: $integrity" }
}

$stoppedServices = @('houtai-gongren', 'mowei-zhixing', 'shiwu-mianban', 'naijiu-shiwu')
try {
    Invoke-Compose -Arguments (@('stop', '--timeout', '30') + $stoppedServices) | Out-Null
    $operation.state = 'restore_in_progress'
    Write-JsonAtomic -Path $operationPath -Value $operation
    Restore-Snapshot -Directory $SnapshotDirectory
    Invoke-Compose -Arguments (@('up', '-d') + $stoppedServices) | Out-Null

    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $health = & temporal operator cluster health --address $TemporalAddress --output json 2>$null | Out-String
        if ($LASTEXITCODE -eq 0 -and $health -match 'SERVING') { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'Temporal did not become SERVING within 120 seconds.' }

    $verifyArguments = @{
        RepoRoot = $RepoRoot
        RuntimeRoot = $RuntimeRoot
        SnapshotDirectory = $SnapshotDirectory
        TemporalAddress = $TemporalAddress
        RunRestoreDrill = $true
    }
    if (-not $SkipPostRestoreCanary) { $verifyArguments.RunLangGraphCanary = $true }
    $verificationText = & $verifyScript @verifyArguments 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Post-restore verification failed: $verificationText" }
    $verification = $verificationText | ConvertFrom-Json -Depth 20
    if ($verification.status -ne 'verified') {
        throw "Post-restore verification did not authorize closure: $($verification.status)"
    }
    $operation.state = 'verified'
    $operation['finished_at'] = (Get-Date).ToString('o')
    $operation['verification'] = [string]$verification.evidence
    Write-JsonAtomic -Path $operationPath -Value $operation
}
catch {
    $operation.state = 'restore_failed_rollback_started'
    $operation['error'] = $_.Exception.Message
    $operation.rollback_attempted = $true
    Write-JsonAtomic -Path $operationPath -Value $operation
    try {
        Restore-Snapshot -Directory ([string]$preRestore.snapshot_directory)
        Invoke-Compose -Arguments (@('up', '-d') + $stoppedServices) | Out-Null
        $operation.rollback_status = 'restored_pre_restore_snapshot'
    }
    catch {
        $operation.rollback_status = 'failed'
        $operation['rollback_error'] = $_.Exception.Message
    }
    $operation.state = 'failed'
    $operation['finished_at'] = (Get-Date).ToString('o')
    Write-JsonAtomic -Path $operationPath -Value $operation
    throw
}

[ordered]@{
    status = 'verified'
    operation_id = $operationId
    operation = $operationPath
    source_snapshot = $SnapshotDirectory
    rollback_snapshot = [string]$preRestore.snapshot_directory
    post_restore_verification = [string]$operation.verification
} | ConvertTo-Json -Depth 8
