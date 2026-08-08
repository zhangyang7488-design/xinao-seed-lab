#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$PiToolRoot = 'D:\XINAO_RESEARCH_RUNTIME\tools\pi\0.84.1',
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSCorePath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

$target = Get-NormalizedPiSCorePath -Path $PiToolRoot
$activeTarget = Get-NormalizedPiSCorePath -Path $script:PiDualEntryToolRoot
$labParent = Get-NormalizedPiSCorePath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
$labPrefix = $labParent + [IO.Path]::DirectorySeparatorChar
$isLabCore = $false
if ($target.StartsWith($labPrefix,[StringComparison]::OrdinalIgnoreCase)) {
    $relative = $target.Substring($labPrefix.Length)
    $segments = @($relative.Split([IO.Path]::DirectorySeparatorChar,[StringSplitOptions]::RemoveEmptyEntries))
    $isLabCore = ($segments.Count -eq 2 -and $segments[1] -ceq 'pi-tool-root')
}
if ($target -ine $activeTarget -and -not $isLabCore) {
    throw "PI_S_MIDTURN_RESTORE_TARGET_OUTSIDE_CORE_OR_BODY_LAB: $target"
}

$packageRoot = Join-Path $target 'node_modules\@earendil-works\pi-coding-agent'
$packageJsonPath = Join-Path $packageRoot 'package.json'
$sourcePath = Join-Path $packageRoot 'dist\core\agent-session.js'
$preimagePath = Join-Path $target 'xinao-compatibility-preimages\pi-coding-agent-0.84.1-agent-session.upstream.js'
foreach ($required in @($packageJsonPath,$sourcePath,$preimagePath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_MIDTURN_RESTORE_REQUIRED_FILE_MISSING: $required"
    }
}

$package = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$package.name -cne '@earendil-works/pi-coding-agent' -or [string]$package.version -cne '0.84.1') {
    throw "PI_S_MIDTURN_RESTORE_VERSION_UNSUPPORTED: $($package.name)@$($package.version)"
}

$upstreamHash = '91e72d5497f665e731cbd79da6a6e826d8cae7d2ce156a7dee39f8ca205e32c8'
$patchedHash = '3d42e3311f1b7b5b72aa81dd745cf7a8e089e9b7708abe5e33b9b553651739e6'
$legacyPatchedHash = '604748b31a08b583aa056c1527b4f4d62afc69aefea28e094e53a8d7ce81185a'
$preimageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $preimagePath).Hash.ToLowerInvariant()
if ($preimageHash -cne $upstreamHash) {
    throw "PI_S_MIDTURN_RESTORE_PREIMAGE_INVALID: expected=$upstreamHash actual=$preimageHash"
}
$beforeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
$changed = $false
if ($VerifyOnly) {
    if ($beforeHash -cne $upstreamHash) {
        throw "PI_S_MIDTURN_RESTORE_NOT_APPLIED: expected=$upstreamHash actual=$beforeHash"
    }
} elseif ($beforeHash -in @($patchedHash,$legacyPatchedHash)) {
    Copy-Item -LiteralPath $preimagePath -Destination $sourcePath -Force
    $changed = $true
} elseif ($beforeHash -cne $upstreamHash) {
    throw "PI_S_MIDTURN_RESTORE_SOURCE_CONFLICT: expected=$patchedHash|$legacyPatchedHash|$upstreamHash actual=$beforeHash"
}

$afterHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
if ($afterHash -cne $upstreamHash) {
    throw "PI_S_MIDTURN_RESTORE_VERIFY_FAILED: expected=$upstreamHash actual=$afterHash"
}

[pscustomobject]@{
    schema = 'xinao.pi_midturn_compaction_restore.v2'
    restore_id = 'pi-coding-agent-0.84.1-midturn-compaction-backpressure-restore-v2'
    pi_tool_root = $target
    package = '@earendil-works/pi-coding-agent@0.84.1'
    source_path = $sourcePath
    preimage_path = $preimagePath
    preimage_sha256 = $preimageHash
    before_sha256 = $beforeHash
    after_sha256 = $afterHash
    changed = $changed
    verify_only = [bool]$VerifyOnly
    active_process_restart_required = $true
    launcher_gate_must_remain_off_until_reapply = $true
} | ConvertTo-Json -Depth 4
