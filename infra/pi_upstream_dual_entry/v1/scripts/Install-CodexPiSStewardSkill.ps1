#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$CodexHome = 'C:\Users\xx363\.codex'
)

. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

$source = Join-Path $script:PiDualEntrySourceRoot 'codex-skills\steward-pis-evolution'
$skillsRoot = Join-Path $CodexHome 'skills'
$target = Join-Path $skillsRoot 'steward-pis-evolution'
$manifestPath = Join-Path $target '.xinao-projection.json'

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "PI_CODEX_STEWARD_SOURCE_MISSING: $source"
}
if (-not (Test-Path -LiteralPath $CodexHome -PathType Container)) {
    throw "PI_CODEX_HOME_MISSING: $CodexHome"
}

$sourcePrefix = [IO.Path]::GetFullPath($source).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
$skillsPrefix = [IO.Path]::GetFullPath($skillsRoot).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
$targetFull = [IO.Path]::GetFullPath($target)
if (-not ($targetFull + [IO.Path]::DirectorySeparatorChar).StartsWith($skillsPrefix,[StringComparison]::OrdinalIgnoreCase)) {
    throw "PI_CODEX_STEWARD_TARGET_ESCAPE: $targetFull"
}

$previousOwned = @()
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    try { $previous = Get-Content -Raw -LiteralPath $manifestPath -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "PI_CODEX_STEWARD_MANIFEST_INVALID: $manifestPath" }
    if ([string]$previous.schema -ne 'xinao.codex_pis_steward_projection.v1') {
        throw "PI_CODEX_STEWARD_MANIFEST_IDENTITY_MISMATCH: $manifestPath"
    }
    $previousOwned = @($previous.owned_files | ForEach-Object { [string]$_ })
}

New-Item -ItemType Directory -Force -Path $target | Out-Null
$owned = @()
$hashes = [ordered]@{}
foreach ($item in @(Get-ChildItem -LiteralPath $source -Recurse -File | Sort-Object FullName)) {
    $sourceFull = [IO.Path]::GetFullPath($item.FullName)
    if (-not $sourceFull.StartsWith($sourcePrefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw "PI_CODEX_STEWARD_SOURCE_ESCAPE: $sourceFull"
    }
    $relative = $sourceFull.Substring($sourcePrefix.Length).Replace('\','/')
    if ([string]::IsNullOrWhiteSpace($relative) -or $relative -match '(^|/)\.\.(/|$)') {
        throw "PI_CODEX_STEWARD_RELATIVE_PATH_INVALID: $relative"
    }
    $destination = Join-Path $target $relative.Replace('/','\')
    $destinationParent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
    $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceFull).Hash.ToLowerInvariant()
    if ((Test-Path -LiteralPath $destination -PathType Leaf) -and $relative -notin $previousOwned) {
        $existingHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ($existingHash -ne $sourceHash) {
            throw "PI_CODEX_STEWARD_PROJECTION_CONFLICT: $destination"
        }
    }
    Copy-Item -LiteralPath $sourceFull -Destination $destination -Force
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant() -ne $sourceHash) {
        throw "PI_CODEX_STEWARD_PROJECTION_DRIFT: $destination"
    }
    $owned += $relative
    $hashes[$relative] = $sourceHash
}

$targetPrefix = $targetFull.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
foreach ($stale in @($previousOwned | Where-Object { $_ -notin $owned })) {
    if ([string]::IsNullOrWhiteSpace($stale) -or $stale -match '(^|/)\.\.(/|$)') {
        throw "PI_CODEX_STEWARD_STALE_PATH_INVALID: $stale"
    }
    $stalePath = [IO.Path]::GetFullPath((Join-Path $target $stale.Replace('/','\')))
    if (-not $stalePath.StartsWith($targetPrefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw "PI_CODEX_STEWARD_STALE_PATH_ESCAPE: $stalePath"
    }
    if (Test-Path -LiteralPath $stalePath -PathType Leaf) {
        Remove-Item -LiteralPath $stalePath -Force
    }
}

Write-PiDualEntryJsonAtomic -Path $manifestPath -Value ([ordered]@{
    schema = 'xinao.codex_pis_steward_projection.v1'
    source_root = $source
    target_root = $target
    owned_files = @($owned)
    sha256 = $hashes
})

[pscustomobject]@{
    schema = 'xinao.codex_pis_steward_install_receipt.v1'
    source = $source
    target = $target
    manifest = $manifestPath
    owned_files = @($owned)
    manifest_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant()
}
