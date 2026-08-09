#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PiToolRoot,
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSNativeContinuationPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

$target = Get-NormalizedPiSNativeContinuationPath -Path $PiToolRoot
$mainTarget = Get-NormalizedPiSNativeContinuationPath -Path $script:PiDualEntryMainToolRoot
$labParent = Get-NormalizedPiSNativeContinuationPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
$labPrefix = $labParent + [IO.Path]::DirectorySeparatorChar
$isLabCore = $false
if ($target.StartsWith($labPrefix,[StringComparison]::OrdinalIgnoreCase)) {
    $relative = $target.Substring($labPrefix.Length)
    $segments = @($relative.Split([IO.Path]::DirectorySeparatorChar,[StringSplitOptions]::RemoveEmptyEntries))
    $isLabCore = ($segments.Count -eq 2 -and $segments[1] -ceq 'pi-tool-root')
}
if ($target -cne $mainTarget -and -not $isLabCore) {
    throw "PI_S_NATIVE_CONTINUATION_RESTORE_TARGET_OUTSIDE_MAIN_OR_BODY_LAB: $target"
}

$packageRoot = Join-Path $target 'node_modules\@earendil-works\pi-coding-agent'
$packageJsonPath = Join-Path $packageRoot 'package.json'
$patchPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'patches\pi-coding-agent-0.84.1-native-continuation-abort-fence.patch'
$files = [ordered]@{
    'dist\core\agent-session.js' = @{
        MidTurnPreimage = '3d42e3311f1b7b5b72aa81dd745cf7a8e089e9b7708abe5e33b9b553651739e6'
        FullyRestored = '91e72d5497f665e731cbd79da6a6e826d8cae7d2ce156a7dee39f8ca205e32c8'
        Patched = 'afdb16fdacf1a66ac56a96bdcf924beddd3763a97eb8ee39ca2ae410faa7ce93'
    }
    'dist\core\agent-session.d.ts' = @{
        MidTurnPreimage = 'c18a61cf0952d19b2d7dfebcfbc0850d5103bcf53e867e466c6d69bcc1b618f6'
        FullyRestored = 'c18a61cf0952d19b2d7dfebcfbc0850d5103bcf53e867e466c6d69bcc1b618f6'
        Patched = 'f495c75f3ec032c7336b2234ee7ba5693f26b41f321ec48d570fed2d292f13e1'
    }
    'node_modules\@earendil-works\pi-agent-core\dist\agent-loop.js' = @{
        MidTurnPreimage = '43cc779ddaf90df41768d3d2d0f7d7ba8b8bce7bedc9dc6062ca8b4de84ae880'
        FullyRestored = '43cc779ddaf90df41768d3d2d0f7d7ba8b8bce7bedc9dc6062ca8b4de84ae880'
        Patched = 'c625c477ee786eeef1b4b5b03c0339e5bf78f90a5b8432018ae0f48dfc98723f'
    }
}

foreach ($required in @($packageJsonPath,$patchPath) + @($files.Keys | ForEach-Object { Join-Path $packageRoot $_ })) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_NATIVE_CONTINUATION_RESTORE_SOURCE_MISSING: $required"
    }
}

$package = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$package.name -cne '@earendil-works/pi-coding-agent' -or [string]$package.version -cne '0.84.1') {
    throw "PI_S_NATIVE_CONTINUATION_RESTORE_VERSION_UNSUPPORTED: $($package.name)@$($package.version)"
}

$before = [ordered]@{}
foreach ($relative in $files.Keys) {
    $before[$relative] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $packageRoot $relative)).Hash.ToLowerInvariant()
}
$allPreimage = @($files.Keys | Where-Object { $before[$_] -ceq $files[$_].MidTurnPreimage }).Count -eq $files.Count
$allFullyRestored = @($files.Keys | Where-Object { $before[$_] -ceq $files[$_].FullyRestored }).Count -eq $files.Count
$allPatched = @($files.Keys | Where-Object { $before[$_] -ceq $files[$_].Patched }).Count -eq $files.Count
$changed = $false

if ($allPatched) {
    if ($VerifyOnly) { throw "PI_S_NATIVE_CONTINUATION_RESTORE_NOT_APPLIED: $packageRoot" }
    & git -c core.autocrlf=false -C $packageRoot apply --reverse --check $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'PI_S_NATIVE_CONTINUATION_RESTORE_CHECK_FAILED' }
    & git -c core.autocrlf=false -C $packageRoot apply --reverse $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'PI_S_NATIVE_CONTINUATION_RESTORE_APPLY_FAILED' }
    $changed = $true
} elseif (-not $allPreimage -and -not $allFullyRestored) {
    $actual = @($before.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ';'
    throw "PI_S_NATIVE_CONTINUATION_RESTORE_SOURCE_CONFLICT: actual=$actual"
}

$after = [ordered]@{}
foreach ($relative in $files.Keys) {
    $after[$relative] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $packageRoot $relative)).Hash.ToLowerInvariant()
}
$afterMidTurnPreimage = @($files.Keys | Where-Object { $after[$_] -ceq $files[$_].MidTurnPreimage }).Count -eq $files.Count
$afterFullyRestored = @($files.Keys | Where-Object { $after[$_] -ceq $files[$_].FullyRestored }).Count -eq $files.Count
if (-not $afterMidTurnPreimage -and -not $afterFullyRestored) {
    $actual = @($after.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ';'
    throw "PI_S_NATIVE_CONTINUATION_RESTORE_VERIFY_FAILED: native_absent_safe_state=false actual=$actual"
}

[pscustomobject]@{
    schema = 'xinao.pi_native_continuation_restore.v1'
    restore_id = 'pi-coding-agent-0.84.1-native-continuation-abort-fence-restore-v3'
    pi_tool_root = $target
    package = '@earendil-works/pi-coding-agent@0.84.1'
    patch_path = $patchPath
    before_sha256 = $before
    after_sha256 = $after
    changed = $changed
    verify_only = [bool]$VerifyOnly
    native_continuation_absent = $true
    restored_to_midturn_preimage = $afterMidTurnPreimage
    fully_restored_upstream_accepted = $afterFullyRestored
    lower_layer_state = $(if ($afterMidTurnPreimage) { 'midturn_applied' } else { 'upstream_restored' })
    midturn_compaction_remains_applied = $afterMidTurnPreimage
    active_process_restart_required = $true
    cold_backup_modified = $false
} | ConvertTo-Json -Depth 6
