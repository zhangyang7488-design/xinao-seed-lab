#Requires -Version 7.2
[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet('Check', 'Status')]
    [string]$Mode = 'Check',
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ManagedPath = '',
    [string]$StateRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\reconcile',
    [string]$DatabasePath = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3',
    [ValidateRange(1, 120)][int]$MaxRuntimeSeconds = 90
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$StateRoot = [IO.Path]::GetFullPath($StateRoot)
$DatabasePath = [IO.Path]::GetFullPath($DatabasePath)
if ($ManagedPath -eq '') {
    $ManagedPath = Join-Path $ProjectRoot 'provisioning\Invoke-XinaoCoordManaged.ps1'
}
$ManagedPath = [IO.Path]::GetFullPath($ManagedPath)
$evidencePath = Join-Path $StateRoot 'evidence.jsonl'
$lockPath = Join-Path $StateRoot 'reconcile.lock'

function Add-Evidence {
    param([Parameter(Mandatory)][object]$Value)

    [void][IO.Directory]::CreateDirectory($StateRoot)
    $line = ($Value | ConvertTo-Json -Depth 12 -Compress) + [Environment]::NewLine
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($line)
    $stream = [IO.FileStream]::new(
        $evidencePath,
        [IO.FileMode]::Append,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Invoke-WithLock {
    param([Parameter(Mandatory)][scriptblock]$Action)

    [void][IO.Directory]::CreateDirectory($StateRoot)
    try {
        $stream = [IO.FileStream]::new(
            $lockPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    }
    catch [IO.IOException] {
        return [ordered]@{ ok = $true; action = 'operation_reconcile'; skipped = 'already_running' }
    }
    try { return & $Action } finally { $stream.Dispose() }
}

function Invoke-Reconcile {
    if (-not (Test-Path -LiteralPath $ManagedPath -PathType Leaf)) {
        throw "XINAO_COORD_RECONCILE_MANAGED_ENTRY_MISSING: $ManagedPath"
    }
    $started = [Diagnostics.Stopwatch]::StartNew()
    $previousDb = $env:XINAO_COORD_DB
    $previousOperations = $env:XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS
    try {
        $env:XINAO_COORD_DB = $DatabasePath
        $env:XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS = '1'
        $raw = & $ManagedPath -Target cli -TargetArgs @(
            'operation-reconcile',
            '--limit', '20',
            '--max-runtime-seconds', [string]$MaxRuntimeSeconds
        ) 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $env:XINAO_COORD_DB = $previousDb
        $env:XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS = $previousOperations
    }
    $started.Stop()
    $text = ($raw | Out-String).Trim()
    $parsed = $null
    if ($exitCode -eq 0 -and $text -ne '') {
        try { $parsed = $text | ConvertFrom-Json } catch { }
    }
    $status = if ($exitCode -eq 0 -and $null -ne $parsed -and [bool]$parsed.ok) { 'verified' } else { 'failed' }
    $record = [ordered]@{
        at_utc = [DateTime]::UtcNow.ToString('o')
        action = 'agent_operation.reconcile'
        bounded = $true
        max_runtime_seconds = $MaxRuntimeSeconds
        status = $status
        exit_code = $exitCode
        elapsed_ms = [int]$started.ElapsedMilliseconds
        stop_reason = if ($null -ne $parsed) { $parsed.stop_reason } else { $null }
        started_workers = if ($null -ne $parsed) { @($parsed.results | Where-Object { $_.spawned }).Count } else { 0 }
        sweep = if ($null -ne $parsed) { $parsed.sweep } else { $null }
        stderr_tail = if ($status -eq 'failed') { ($text -split "`r?`n" | Select-Object -Last 12) -join ' | ' } else { '' }
    }
    Add-Evidence -Value $record
    if ($status -ne 'verified') { throw "XINAO_COORD_RECONCILE_FAILED: exit=$exitCode" }
    return $record
}

switch ($Mode) {
    'Check' {
        Invoke-WithLock -Action { Invoke-Reconcile } | ConvertTo-Json -Depth 12
    }
    'Status' {
        $latest = if (Test-Path -LiteralPath $evidencePath -PathType Leaf) {
            Get-Content -LiteralPath $evidencePath -Tail 1 | ConvertFrom-Json
        }
        else { $null }
        [ordered]@{
            schema_version = 1
            at_utc = [DateTime]::UtcNow.ToString('o')
            persistence_mode = 'explicit_only_no_background_scheduler'
            background_reconciler_configured = $false
            evidence_path = $evidencePath
            latest = $latest
        } | ConvertTo-Json -Depth 12
    }
}
