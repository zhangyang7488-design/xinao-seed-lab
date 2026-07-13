[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$RuntimeRoot = $(if ($env:XINAO_RESEARCH_RUNTIME) { $env:XINAO_RESEARCH_RUNTIME } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$SnapshotDirectory = '',
    [string]$TemporalAddress = '127.0.0.1:7233',
    [switch]$RunRestoreDrill,
    [switch]$RunLangGraphCanary,
    [switch]$RunGrokCanary,
    [string]$GrokPayload = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$composePath = Join-Path $RepoRoot 'docker-compose.yml'
$snapshotRoot = Join-Path $RuntimeRoot 'recovery\downstream-state'
if ([string]::IsNullOrWhiteSpace($SnapshotDirectory)) {
    $latestPath = Join-Path $snapshotRoot 'latest.json'
    if (-not (Test-Path -LiteralPath $latestPath -PathType Leaf)) {
        throw "Downstream latest pointer is missing: $latestPath"
    }
    $latest = Get-Content -LiteralPath $latestPath -Raw | ConvertFrom-Json -Depth 20
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

$checks = [System.Collections.Generic.List[object]]::new()
function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Evidence)
    $checks.Add([ordered]@{ name = $Name; passed = $Passed; evidence = $Evidence })
}
function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $output = & docker compose -f $composePath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Arguments -join ' ') :: $($output -join ' ')"
    }
    return @($output)
}

$hashFailures = [System.Collections.Generic.List[string]]::new()
foreach ($database in @($manifest.postgres.databases)) {
    $archive = Join-Path $SnapshotDirectory ([string]$database.archive)
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
        $hashFailures.Add("missing:$archive")
        continue
    }
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne [string]$database.sha256) {
        $hashFailures.Add("hash:$archive")
    }
}
$langGraphArchive = Join-Path $SnapshotDirectory ([string]$manifest.langgraph.archive)
if (-not (Test-Path -LiteralPath $langGraphArchive -PathType Leaf)) {
    $hashFailures.Add("missing:$langGraphArchive")
}
elseif ((Get-FileHash -LiteralPath $langGraphArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$manifest.langgraph.sha256) {
    $hashFailures.Add("hash:$langGraphArchive")
}
Add-Check 'snapshot_hashes' ($hashFailures.Count -eq 0) ($hashFailures -join ';')

$sqliteIntegrity = (& sqlite3 $langGraphArchive 'PRAGMA quick_check;' 2>&1 | Out-String).Trim()
Add-Check 'langgraph_sqlite_restore_source' ($LASTEXITCODE -eq 0 -and $sqliteIntegrity -eq 'ok') $sqliteIntegrity

$containerId = ((Invoke-Compose -Arguments @('ps', '-q', 'shiwu-ku')) | Out-String).Trim()
Add-Check 'postgres_container_running' (-not [string]::IsNullOrWhiteSpace($containerId)) 'service=shiwu-ku'
$pgUser = ((Invoke-Compose -Arguments @(
    'exec', '-T', 'shiwu-ku', 'sh', '-lc', 'printf %s "${POSTGRES_USER:-postgres}"'
)) | Out-String).Trim()
$pgDatabase = ((Invoke-Compose -Arguments @(
    'exec', '-T', 'shiwu-ku', 'sh', '-lc', 'printf %s "${POSTGRES_DB:-postgres}"'
)) | Out-String).Trim()

$archiveListFailures = [System.Collections.Generic.List[string]]::new()
foreach ($database in @($manifest.postgres.databases)) {
    $archive = Join-Path $SnapshotDirectory ([string]$database.archive)
    $containerArchive = "/tmp/recovery-check-$PID-$([string]$database.name).dump"
    try {
        $copyOutput = & docker cp $archive "${containerId}:$containerArchive" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "docker cp failed: $($copyOutput -join ' ')" }
        Invoke-Compose -Arguments @('exec', '-T', 'shiwu-ku', 'pg_restore', '--list', $containerArchive) | Out-Null
    }
    catch {
        $archiveListFailures.Add("$([string]$database.name):$($_.Exception.Message)")
    }
    finally {
        try { Invoke-Compose -Arguments @('exec', '-T', 'shiwu-ku', 'rm', '-f', $containerArchive) | Out-Null } catch { }
    }
}
Add-Check 'postgres_archives_listable' ($archiveListFailures.Count -eq 0) ($archiveListFailures -join ';')

if ($RunRestoreDrill) {
    $drillFailures = [System.Collections.Generic.List[string]]::new()
    $drillEvidence = [System.Collections.Generic.List[string]]::new()
    foreach ($database in @($manifest.postgres.databases)) {
        $sourceName = [string]$database.name
        $drillName = "xinao_drill_$($sourceName)_$PID".ToLowerInvariant()
        if ($drillName.Length -gt 63) { $drillName = $drillName.Substring(0, 63) }
        $archive = Join-Path $SnapshotDirectory ([string]$database.archive)
        $containerArchive = "/tmp/recovery-drill-$PID-$sourceName.dump"
        try {
            Invoke-Compose -Arguments @('exec', '-T', 'shiwu-ku', 'dropdb', '-U', $pgUser, '--if-exists', '--force', $drillName) | Out-Null
            Invoke-Compose -Arguments @('exec', '-T', 'shiwu-ku', 'createdb', '-U', $pgUser, '-T', 'template0', $drillName) | Out-Null
            $copyOutput = & docker cp $archive "${containerId}:$containerArchive" 2>&1
            if ($LASTEXITCODE -ne 0) { throw "docker cp failed: $($copyOutput -join ' ')" }
            Invoke-Compose -Arguments @(
                'exec', '-T', 'shiwu-ku', 'pg_restore', '-U', $pgUser,
                '--exit-on-error', '--no-owner', '--no-privileges', '-d', $drillName, $containerArchive
            ) | Out-Null
            $tableCountText = ((Invoke-Compose -Arguments @(
                'exec', '-T', 'shiwu-ku', 'psql', '-U', $pgUser, '-d', $drillName,
                '-At', '-c', "select count(*) from information_schema.tables where table_schema not in ('pg_catalog','information_schema')"
            )) | Out-String).Trim()
            $tableCount = 0
            if (-not [int]::TryParse($tableCountText, [ref]$tableCount) -or $tableCount -lt 1) {
                throw "restored table count is invalid: $tableCountText"
            }
            $drillEvidence.Add("${sourceName}:$tableCount")
        }
        catch {
            $drillFailures.Add("${sourceName}:$($_.Exception.Message)")
        }
        finally {
            try { Invoke-Compose -Arguments @('exec', '-T', 'shiwu-ku', 'dropdb', '-U', $pgUser, '--if-exists', '--force', $drillName) | Out-Null } catch { }
            try { Invoke-Compose -Arguments @('exec', '-T', 'shiwu-ku', 'rm', '-f', $containerArchive) | Out-Null } catch { }
        }
    }
    Add-Check 'postgres_isolated_restore_drill' ($drillFailures.Count -eq 0) (($drillEvidence + $drillFailures) -join ';')
}

$healthOutput = & temporal operator cluster health --address $TemporalAddress --output json 2>&1 | Out-String
$temporalHealthy = $LASTEXITCODE -eq 0 -and $healthOutput -match 'SERVING'
Add-Check 'temporal_cluster_health' $temporalHealthy 'status=SERVING'

$composeState = @(
    & docker compose -f $composePath ps --format json 2>$null |
        ForEach-Object { if ($_ -and $_.Trim()) { $_ | ConvertFrom-Json } }
)
$requiredServices = @('shiwu-ku', 'naijiu-shiwu', 'houtai-gongren')
$unhealthy = @(
    foreach ($service in $requiredServices) {
        $row = @($composeState | Where-Object Service -eq $service | Select-Object -First 1)
        if ($row.Count -eq 0 -or $row[0].State -ne 'running' -or ($row[0].Health -and $row[0].Health -ne 'healthy')) {
            $service
        }
    }
)
Add-Check 'canonical_compose_services' ($unhealthy.Count -eq 0) ("unhealthy=" + ($unhealthy -join ','))

$pollerJson = (& temporal task-queue describe --address $TemporalAddress --task-queue 'xinao-integrated-langgraph-plugin-queue' --output json 2>$null | Out-String).Trim()
$pollerCount = 0
if ($LASTEXITCODE -eq 0 -and $pollerJson) {
    try { $pollerCount = @((($pollerJson | ConvertFrom-Json -Depth 30).pollers)).Count } catch { $pollerCount = 0 }
}
Add-Check 'houtai_langgraph_poller' ($pollerCount -gt 0) "pollers=$pollerCount"

$importOutput = Invoke-Compose -Arguments @(
    'exec', '-T', 'houtai-gongren', 'python', '-c',
    'import langgraph; print("LANGGRAPH_IMPORT_OK")'
)
Add-Check 'worker_langgraph_import' ((($importOutput | Out-String).Trim()) -match 'LANGGRAPH_IMPORT_OK') 'import=ok'

if ($RunLangGraphCanary) {
    $python = Join-Path $RepoRoot 'projects\dual-brain-coordination\.venv\Scripts\python.exe'
    $canary = Join-Path $RepoRoot 'projects\dual-brain-coordination\scripts\run_temporal_kernel_convergence_canary.py'
    $canaryOutput = & $python $canary 2>&1 | Out-String
    $canaryPassed = $LASTEXITCODE -eq 0 -and $canaryOutput -match '"ok": true'
    Add-Check 'temporal_langgraph_real_canary' $canaryPassed (($canaryOutput -split "`r?`n" | Select-Object -Last 1) -join '')
}

if ($RunGrokCanary) {
    if ([string]::IsNullOrWhiteSpace($GrokPayload) -or -not (Test-Path -LiteralPath $GrokPayload -PathType Leaf)) {
        Add-Check 'canonical_grok_real_canary' $false 'payload_missing'
    }
    else {
        $python = Join-Path $RepoRoot 'projects\dual-brain-coordination\.venv\Scripts\python.exe'
        $runner = Join-Path $RepoRoot 'projects\dual-brain-coordination\scripts\run_canonical_grok_transaction.py'
        $grokOutput = & $python $runner --payload $GrokPayload 2>&1 | Out-String
        $grokPassed = $LASTEXITCODE -eq 0 -and $grokOutput -match '"ok": true'
        Add-Check 'canonical_grok_real_canary' $grokPassed (($grokOutput -split "`r?`n" | Select-Object -Last 1) -join '')
    }
}

$failed = @($checks | Where-Object passed -ne $true)
$runtimeClosureRequested = [bool]($RunRestoreDrill -and ($RunLangGraphCanary -or $RunGrokCanary))
$runId = 'verify-downstream-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
$evidenceRoot = Join-Path $RuntimeRoot 'state\downstream_recovery_verification'
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
$result = [ordered]@{
    schema_version = 'xinao.downstream_recovery_verification.v1'
    verification_id = $runId
    verified_at = (Get-Date).ToString('o')
    snapshot_directory = $SnapshotDirectory
    status = if ($failed.Count -eq 0 -and $runtimeClosureRequested) { 'verified' } else { 'partial' }
    closure_claim_allowed = ($failed.Count -eq 0 -and $runtimeClosureRequested)
    passed = $checks.Count - $failed.Count
    failed = $failed.Count
    requested_drills = [ordered]@{
        isolated_postgres_restore = [bool]$RunRestoreDrill
        temporal_langgraph_canary = [bool]$RunLangGraphCanary
        canonical_grok_canary = [bool]$RunGrokCanary
    }
    checks = @($checks)
    disclosure = [ordered]@{
        credential_values_exported = $false
        opaque_snapshot_payloads_inspected = $false
        evidence_contains_only_metadata_and_check_results = $true
    }
}
$resultPath = Join-Path $evidenceRoot "$runId.json"
$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $resultPath -Encoding utf8NoBOM
[ordered]@{
    status = $result.status
    passed = $result.passed
    failed = $result.failed
    evidence = $resultPath
} | ConvertTo-Json -Depth 6
if ($failed.Count -gt 0) { exit 1 }
