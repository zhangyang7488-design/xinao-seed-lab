#Requires -Version 5.1
[CmdletBinding()]
param([switch]$VerifyOnly)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

$spec = Get-PiDualEntrySpec -Profile 'prime-s'
$target = [IO.Path]::GetFullPath($spec.PiToolRoot).TrimEnd('\')
$expected = [IO.Path]::GetFullPath($script:PiDualEntryMainToolRoot).TrimEnd('\')
$backup = [IO.Path]::GetFullPath($script:PiDualEntryBackupToolRoot).TrimEnd('\')
if ($target -ine $expected -or $target -ieq $backup) {
    throw "PI_S_MAIN_CORE_TARGET_IDENTITY_INVALID: $target"
}

$installed = $false
if (-not (Test-Path -LiteralPath $spec.PiCommand -PathType Leaf)) {
    if ($VerifyOnly) { throw "PI_S_MAIN_CORE_NOT_INSTALLED: $($spec.PiCommand)" }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    $npm = Get-Command npm.cmd -ErrorAction Stop
    $installOutput = @(& $npm.Source install --prefix $target --no-audit --no-fund --save-exact "@earendil-works/pi-coding-agent@$script:PiDualEntryVersion" 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "PI_S_MAIN_CORE_INSTALL_FAILED: $($installOutput -join ' ')"
    }
    $installed = $true
}

Assert-PiDualEntryBinary -Spec $spec
$midTurnRaw = if ($VerifyOnly) {
    & (Join-Path $PSScriptRoot 'Apply-PiSMidTurnCompactionCompatibility.ps1') -PiToolRoot $target -VerifyOnly
} else {
    & (Join-Path $PSScriptRoot 'Apply-PiSMidTurnCompactionCompatibility.ps1') -PiToolRoot $target
}
$midTurn = ($midTurnRaw -join [Environment]::NewLine) | ConvertFrom-Json
$postRaw = if ($VerifyOnly) {
    & (Join-Path $PSScriptRoot 'Apply-PiSPost0841UpstreamCompatibility.ps1') -PiToolRoot $target -VerifyOnly
} else {
    & (Join-Path $PSScriptRoot 'Apply-PiSPost0841UpstreamCompatibility.ps1') -PiToolRoot $target
}
$post = ($postRaw -join [Environment]::NewLine) | ConvertFrom-Json

$behaviorRaw = @(& node (Join-Path $PSScriptRoot 'Test-PiSPost0841UpstreamCompatibility.mjs') --pi-root $target 2>&1)
if ($LASTEXITCODE -ne 0 -or ($behaviorRaw -join [Environment]::NewLine) -notmatch 'PIS_POST_0841_UPSTREAM_COMPATIBILITY_V1') {
    throw "PI_S_MAIN_CORE_BEHAVIOR_PROBE_FAILED: $($behaviorRaw -join ' ')"
}

$packagePath = Join-Path $target 'node_modules\@earendil-works\pi-coding-agent\package.json'
$packageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $packagePath).Hash.ToLowerInvariant()
$lockPath = Join-Path $target 'package-lock.json'
[pscustomobject]@{
    schema = 'xinao.pi_main_isolated_core.installation.v1'
    status = 'verified'
    profile = $spec.Profile
    pi_tool_root = $target
    pi_command = $spec.PiCommand
    pi_version = ([string](& $spec.PiCommand --version | Select-Object -First 1)).Trim()
    installed_now = $installed
    verify_only = [bool]$VerifyOnly
    package_sha256 = $packageHash
    package_lock_sha256 = if (Test-Path -LiteralPath $lockPath -PathType Leaf) {
        (Get-FileHash -Algorithm SHA256 -LiteralPath $lockPath).Hash.ToLowerInvariant()
    } else { $null }
    midturn_compaction_compatibility = $midTurn
    post_0841_upstream_compatibility = $post
    cold_backup_tool_root = $backup
    cold_backup_touched = $false
} | ConvertTo-Json -Depth 8
