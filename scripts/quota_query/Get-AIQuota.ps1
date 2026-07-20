#Requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$NoLiveCodex,
    [string]$EpochId = "",
    [string]$InvalidateReason = "",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$collector = Join-Path $PSScriptRoot "quota-query.mjs"
if (-not (Test-Path -LiteralPath $collector -PathType Leaf)) {
    throw "XINAO_QUOTA_COLLECTOR_MISSING: $collector"
}

# No epoch means an explicit human/live query and preserves the original UX.
if ([string]::IsNullOrWhiteSpace($EpochId)) {
    $arguments = @($collector)
    if ($Json) { $arguments += "--json" }
    if ($NoLiveCodex) { $arguments += "--no-live-codex" }
    & node @arguments
    exit $LASTEXITCODE
}

$pointer = Join-Path $RuntimeRoot "state\grok_supervisor_selector\current.json"
if (-not (Test-Path -LiteralPath $pointer -PathType Leaf)) {
    throw "XINAO_SELECTOR_RELEASE_POINTER_MISSING: $pointer"
}
try {
    $release = Get-Content -LiteralPath $pointer -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
} catch {
    throw "XINAO_SELECTOR_RELEASE_POINTER_INVALID: $pointer"
}
$releaseRoot = [string]$release.release_root
$manifest = [string]$release.release_manifest_ref
if (
    [string]::IsNullOrWhiteSpace($releaseRoot) -or
    -not (Test-Path -LiteralPath $manifest -PathType Leaf)
) {
    throw "XINAO_SELECTOR_RELEASE_POINTER_INCOMPLETE: $pointer"
}
try {
    $releaseManifest = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
} catch {
    throw "XINAO_SELECTOR_RELEASE_MANIFEST_INVALID: $manifest"
}
$python = [string]$releaseManifest.python_executable
$epochScript = Join-Path $releaseRoot "scripts\quota_dispatch_epoch.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "XINAO_SELECTOR_RELEASE_PYTHON_MISSING: $python"
}
if (-not (Test-Path -LiteralPath $epochScript -PathType Leaf)) {
    throw "XINAO_QUOTA_EPOCH_SCRIPT_MISSING: $epochScript"
}
$collectorArgs = @("node", $collector, "--json")
if ($NoLiveCodex) { $collectorArgs += "--no-live-codex" }
$arguments = @(
    "-I", "-B", $epochScript,
    "--runtime-root", $RuntimeRoot,
    "--epoch-id", $EpochId,
    "--collector-command-json", ($collectorArgs | ConvertTo-Json -Compress)
)
if (-not [string]::IsNullOrWhiteSpace($InvalidateReason)) {
    $arguments += @("--invalidate-reason", $InvalidateReason)
}
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    $arguments += @("--output", $OutputPath)
}
$lines = @(& $python @arguments 2>&1 | ForEach-Object { [string]$_ })
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "XINAO_QUOTA_EPOCH_QUERY_FAILED: exit=$exitCode output=$($lines -join [Environment]::NewLine)"
}
$last = @($lines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) | Select-Object -Last 1
if ($Json) {
    $last
} else {
    $resolved = $last | ConvertFrom-Json -ErrorAction Stop
    [pscustomobject]@{
        epoch_id = [string]$resolved.snapshot.epoch_id
        snapshot_id = [string]$resolved.snapshot.snapshot_id
        freshness = [string]$resolved.snapshot.freshness
        status = [string]$resolved.status
        dispatch_blocked = $resolved.dispatch_blocked -eq $true
        snapshot_ref = [string]$resolved.snapshot.snapshot_ref
    } | Format-List | Out-String | Write-Output
}
