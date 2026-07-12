#Requires -Version 7.2
[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory)][string]$PointerPath,
    [Parameter(Mandatory)][string]$RuntimeRoot,
    [Parameter(Mandatory)][string]$ExpectedCurrentGeneration,
    [Parameter(Mandatory)][string]$RestoreGeneration,
    [switch]$AllowLivePointer,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$PointerPath = [IO.Path]::GetFullPath($PointerPath)
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$livePointer = [IO.Path]::GetFullPath((Join-Path $RuntimeRoot 'current.json'))
if (
    $Apply -and
    -not $AllowLivePointer -and
    $PointerPath.Equals($livePointer, [StringComparison]::OrdinalIgnoreCase)
) {
    throw 'XINAO_COORD_ROLLBACK_CANARY_REFUSES_LIVE_POINTER'
}

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "missing json: $Path" }
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-JsonReplace([string]$Path, [object]$Value) {
    $directory = Split-Path -Parent $Path
    [void][IO.Directory]::CreateDirectory($directory)
    $temporary = Join-Path $directory ('.{0}.{1}.tmp' -f ([IO.Path]::GetFileName($Path)), [guid]::NewGuid().ToString('N'))
    $backup = "$Path.rollback-backup"
    [IO.File]::WriteAllText($temporary, (($Value | ConvertTo-Json -Depth 12) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        [IO.File]::Replace($temporary, $Path, $backup, $true)
    }
    else {
        [IO.File]::Move($temporary, $Path)
    }
}

$current = Read-Json $PointerPath
if ([string]$current.generation_id -ne $ExpectedCurrentGeneration) {
    throw "current generation mismatch: $($current.generation_id)"
}
$restoreRoot = [IO.Path]::GetFullPath((Join-Path $RuntimeRoot ("generations\{0}" -f $RestoreGeneration)))
$generationsRoot = [IO.Path]::GetFullPath((Join-Path $RuntimeRoot 'generations'))
if (-not $restoreRoot.StartsWith($generationsRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'restore generation escaped runtime root'
}
$manifestPath = Join-Path $restoreRoot 'generation.json'
$manifest = Read-Json $manifestPath
if ([string]$manifest.generation_id -ne $RestoreGeneration) {
    throw 'restore manifest generation mismatch'
}
$replacement = [ordered]@{
    schema_version = 1
    generation_id = $RestoreGeneration
    source_fingerprint = [string]$manifest.source_fingerprint
    generation_path = $restoreRoot
    updated_at_utc = [DateTime]::UtcNow.ToString('o')
}
if ($Apply) { Write-JsonReplace -Path $PointerPath -Value $replacement }

[ordered]@{
    ok = $true
    applied = [bool]$Apply
    pointer_path = $PointerPath
    expected_current = $ExpectedCurrentGeneration
    restore = $RestoreGeneration
    restore_manifest = $manifestPath
    replacement = $replacement
} | ConvertTo-Json -Depth 12
