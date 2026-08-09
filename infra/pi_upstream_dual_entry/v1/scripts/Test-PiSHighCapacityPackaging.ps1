#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AgentDir,
    [Parameter(Mandatory)][string]$PiToolRoot,
    [string]$ReceiptPath,
    [string]$TypeScriptCompilerPath,
    [switch]$SkipReplay
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-NormalizedPackagingPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\','/')
}

function Test-PackagingPathEqual {
    param([Parameter(Mandatory)][string]$Left,[Parameter(Mandatory)][string]$Right)
    [string]::Equals((Get-NormalizedPackagingPath $Left),(Get-NormalizedPackagingPath $Right),[StringComparison]::OrdinalIgnoreCase)
}

function Assert-PackagingNoReparsePath {
    param([Parameter(Mandatory)][string]$Path)
    $cursor = Get-NormalizedPackagingPath $Path
    $root = [IO.Path]::GetPathRoot($cursor)
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "PI_HIGH_CAPACITY_PACKAGING_REPARSE_POINT_REJECTED: $cursor"
            }
        }
        if (Test-PackagingPathEqual $cursor $root) { break }
        $parent = Split-Path -Parent $cursor
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ceq $cursor) { break }
        $cursor = $parent
    }
}

function Get-PatchRelativePaths {
    param([Parameter(Mandatory)][string]$PatchPath)
    $paths = New-Object Collections.Generic.List[string]
    foreach ($line in Get-Content -LiteralPath $PatchPath -Encoding UTF8) {
        if ($line -match '^diff --git a/(.+?) b/(.+)$') {
            if ($matches[1] -cne $matches[2]) { throw "PI_HIGH_CAPACITY_PACKAGING_PATCH_RENAME_REJECTED: $line" }
            $paths.Add(($matches[1] -replace '/','\'))
        }
    }
    if ($paths.Count -eq 0) { throw "PI_HIGH_CAPACITY_PACKAGING_PATCH_PATHS_MISSING: $PatchPath" }
    @($paths)
}

function Get-FileSetState {
    param([Parameter(Mandatory)][string]$Root,[Parameter(Mandatory)][string[]]$RelativePaths)
    $state = [ordered]@{}
    foreach ($relative in $RelativePaths) {
        $path = Join-Path $Root $relative
        if (-not (Test-Path -LiteralPath $path)) { $state[$relative] = 'absent'; continue }
        $item = Get-Item -LiteralPath $path -Force
        if (-not ($item -is [IO.FileInfo]) -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            $state[$relative] = 'invalid-object'
            continue
        }
        $state[$relative] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $state
}

function Test-StateEqual {
    param([Parameter(Mandatory)][System.Collections.IDictionary]$Left,[Parameter(Mandatory)][System.Collections.IDictionary]$Right)
    if ($Left.Count -ne $Right.Count) { return $false }
    foreach ($key in $Left.Keys) {
        if (-not $Right.Contains($key) -or [string]$Left[$key] -cne [string]$Right[$key]) { return $false }
    }
    $true
}

function Get-TreeFingerprint {
    param([Parameter(Mandatory)][string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return 'absent' }
    $rootPath = Get-NormalizedPackagingPath $Root
    $files = @(Get-ChildItem -LiteralPath $rootPath -Recurse -File -Force | Sort-Object FullName)
    $builder = New-Object Text.StringBuilder
    foreach ($file in $files) {
        if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "PI_HIGH_CAPACITY_PACKAGING_TREE_REPARSE_REJECTED: $($file.FullName)" }
        $relative = $file.FullName.Substring($rootPath.Length + 1).Replace('\','/')
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        [void]$builder.Append($relative).Append("`t").Append($file.Length).Append("`t").Append($hash).Append("`n")
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($builder.ToString()))
        ([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Get-CanonicalJsonFingerprint {
    param([Parameter(Mandatory)]$Value)
    $json = $Value | ConvertTo-Json -Depth 14 -Compress
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash($bytes)
    } finally {
        $sha.Dispose()
    }
    [ordered]@{
        canonicalization = 'powershell-converttojson-depth14-compress-utf8'
        bytes = $bytes.Length
        sha256 = ([BitConverter]::ToString($digest)).Replace('-','').ToLowerInvariant()
    }
}

function Copy-FileAtomic {
    param([Parameter(Mandatory)][string]$Source,[Parameter(Mandatory)][string]$Destination)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    $temporary = "$Destination.packaging-$PID-$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllBytes($temporary,[IO.File]::ReadAllBytes($Source))
        Move-Item -LiteralPath $temporary -Destination $Destination -Force
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Save-FileSet {
    param([Parameter(Mandatory)][string]$Root,[Parameter(Mandatory)][string[]]$RelativePaths,[Parameter(Mandatory)][string]$BackupRoot)
    $state = Get-FileSetState -Root $Root -RelativePaths $RelativePaths
    foreach ($relative in $RelativePaths) {
        if ($state[$relative] -ceq 'absent') { continue }
        if ($state[$relative] -ceq 'invalid-object') { throw "PI_HIGH_CAPACITY_PACKAGING_SNAPSHOT_INVALID_OBJECT: $relative" }
        $backup = Join-Path $BackupRoot $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item -LiteralPath (Join-Path $Root $relative) -Destination $backup -Force
    }
    $state
}

function Restore-FileSet {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string[]]$RelativePaths,
        [Parameter(Mandatory)][string]$BackupRoot,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Expected
    )
    foreach ($relative in $RelativePaths) {
        $destination = Join-Path $Root $relative
        if ($Expected[$relative] -ceq 'absent') {
            if (Test-Path -LiteralPath $destination -PathType Leaf) { Remove-Item -LiteralPath $destination -Force }
        } else {
            Copy-FileAtomic -Source (Join-Path $BackupRoot $relative) -Destination $destination
        }
    }
}

function Invoke-JsonScript {
    param([Parameter(Mandatory)][string]$ScriptPath,[Parameter(Mandatory)][hashtable]$Parameters)
    $output = & $ScriptPath @Parameters
    try { @($output)[-1] | ConvertFrom-Json } catch { ($output -join "`n") | ConvertFrom-Json }
}

function Assert-ExpectedFailure {
    param([Parameter(Mandatory)][scriptblock]$Action,[Parameter(Mandatory)][string]$Pattern,[Parameter(Mandatory)][string]$Label)
    $message = $null
    try { & $Action | Out-Null } catch { $message = [string]$_.Exception.Message }
    if ($null -eq $message -or $message -notlike $Pattern) {
        throw "PI_HIGH_CAPACITY_PACKAGING_EXPECTED_FAILURE_MISSING: label=$Label expected=$Pattern actual=$message"
    }
    $message
}

function Write-JsonAtomic {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Json)
    $target = [IO.Path]::GetFullPath($Path)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $temporary = "$target.tmp-$PID-$([Guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllText($temporary,$Json,[Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $target -Force
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
    }
}

$agent = Get-NormalizedPackagingPath $AgentDir
$core = Get-NormalizedPackagingPath $PiToolRoot
$labParent = Get-NormalizedPackagingPath (Split-Path -Parent $agent)
$primeSBodyLabs = Get-NormalizedPackagingPath (Split-Path -Parent $labParent)
if ((Split-Path -Leaf $labParent) -cne 'prime-s' -or (Split-Path -Leaf $primeSBodyLabs) -cne 'body-labs') {
    throw "PI_HIGH_CAPACITY_PACKAGING_DISPOSABLE_LAB_REQUIRED: $agent"
}
if (-not (Test-PackagingPathEqual $core (Join-Path $agent 'pi-tool-root'))) {
    throw "PI_HIGH_CAPACITY_PACKAGING_ROOT_PAIR_MISMATCH: agent=$agent core=$core"
}
Assert-PackagingNoReparsePath $agent
Assert-PackagingNoReparsePath $core

$packageRoot = Join-Path $agent 'npm\node_modules\pi-subagents'
$coreRoot = Join-Path $core 'node_modules\@earendil-works\pi-coding-agent'
$patchRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'patches'
$packagePatch = Join-Path $patchRoot 'pi-subagents-0.44.0-high-capacity-v1.patch'
$corePatch = Join-Path $patchRoot 'pi-coding-agent-0.84.1-high-capacity-v1.patch'
$packagePaths = Get-PatchRelativePaths $packagePatch
$corePaths = Get-PatchRelativePaths $corePatch
$applyScript = Join-Path $PSScriptRoot 'Apply-PiSHighCapacityCompatibility.ps1'
$restoreScript = Join-Path $PSScriptRoot 'Restore-PiSHighCapacityCompatibility.ps1'
$replayScript = Join-Path $PSScriptRoot 'Test-PiSHighCapacityReplay.ps1'
$oldScripts = @(
    @{ path = Join-Path $PSScriptRoot 'Apply-PiSSubagentsWindowsCompatibility.ps1'; field = 'high_capacity_combination_accepted' },
    @{ path = Join-Path $PSScriptRoot 'Apply-PiSSubagentsSessionStopCompatibility.ps1'; field = 'high_capacity_combination_accepted' },
    @{ path = Join-Path $PSScriptRoot 'Apply-PiSSubagentsFilesystemPolicy.ps1'; field = 'high_capacity_combination_accepted' }
)
foreach ($required in @($packageRoot,$coreRoot,$packagePatch,$corePatch,$applyScript,$restoreScript,$replayScript)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "PI_HIGH_CAPACITY_PACKAGING_REQUIRED_PATH_MISSING: $required" }
}

$tempParent = 'D:\XINAO_RESEARCH_RUNTIME\temp\pi-high-capacity-packaging'
$tempRoot = Join-Path $tempParent ([Guid]::NewGuid().ToString('N'))
$backupPackage = Join-Path $tempRoot 'backup-package'
$backupCore = Join-Path $tempRoot 'backup-core'
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
$started = [DateTimeOffset]::Now
$receipt = [ordered]@{
    schema = 'xinao.pi_s_high_capacity_packaging_acceptance.v1'
    status = 'running'
    started_at = $started.ToString('o')
    agent_dir = $agent
    pi_tool_root = $core
    cases = [ordered]@{}
    replay = $null
    replay_binding = $null
    restored_underlay = $false
    temp_cleanup = $false
    error = $null
}
$packageInitial = $null
$coreInitial = $null
$packageTreeInitial = $null
$coreTreeInitial = $null
$packageReal = "$packageRoot.packaging-real-$PID"

try {
    $packageInitial = Save-FileSet -Root $packageRoot -RelativePaths $packagePaths -BackupRoot $backupPackage
    $coreInitial = Save-FileSet -Root $coreRoot -RelativePaths $corePaths -BackupRoot $backupCore
    $packageTreeInitial = Get-TreeFingerprint (Join-Path $packageRoot 'src')
    $coreTreeInitial = Get-TreeFingerprint (Join-Path $coreRoot 'dist\core')

    $underlay = Invoke-JsonScript $restoreScript @{ AgentDir = $agent; PiToolRoot = $core; VerifyOnly = $true }
    if ($underlay.changed -or -not $underlay.verified) { throw 'PI_HIGH_CAPACITY_PACKAGING_INITIAL_UNDERLAY_NOT_VERIFIED' }

    $first = Invoke-JsonScript $applyScript @{ AgentDir = $agent; PiToolRoot = $core }
    $verify = Invoke-JsonScript $applyScript @{ AgentDir = $agent; PiToolRoot = $core; VerifyOnly = $true }
    $second = Invoke-JsonScript $applyScript @{ AgentDir = $agent; PiToolRoot = $core }
    if (-not $first.changed -or -not $first.sqlite_probe.ok -or $verify.changed -or $second.changed -or -not $verify.handshake_eligible) {
        throw 'PI_HIGH_CAPACITY_PACKAGING_APPLY_IDEMPOTENCE_FAILED'
    }
    $receipt.cases.apply = [ordered]@{ first_changed = $true; verify_changed = $false; second_changed = $false; sqlite = $true }

    foreach ($old in $oldScripts) {
        foreach ($verifyOnly in @($false,$true)) {
            $parameters = @{ AgentDir = $agent }
            if ($verifyOnly) { $parameters.VerifyOnly = $true }
            $oldReceipt = Invoke-JsonScript $old.path $parameters
            if ($oldReceipt.changed -or -not [bool]$oldReceipt.($old.field)) { throw "PI_HIGH_CAPACITY_PACKAGING_OLD_APPLY_REGRESSED: $($old.path)" }
        }
    }
    $receipt.cases.old_apply_capacity_final = [ordered]@{ scripts = 3; invocations = 6; changed = 0 }

    if (-not $SkipReplay) {
        $replayParameters = @{ AgentDir = $agent; PiToolRoot = $core }
        if (-not [string]::IsNullOrWhiteSpace($TypeScriptCompilerPath)) { $replayParameters.TypeScriptCompilerPath = $TypeScriptCompilerPath }
        $replay = Invoke-JsonScript $replayScript $replayParameters
        if ([string]$replay.status -cne 'verified' -or [int]$replay.tests.passed -ne 48 -or [string]$replay.strict_typescript.status -cne 'pass' -or [bool]$replay.strict_typescript.skip_lib_check) {
            throw 'PI_HIGH_CAPACITY_PACKAGING_REPLAY_FAILED'
        }
        $receipt.replay = $replay
        $receipt.replay_binding = Get-CanonicalJsonFingerprint $replay
    }

    $restoreFirst = Invoke-JsonScript $restoreScript @{ AgentDir = $agent; PiToolRoot = $core }
    $restoreVerify = Invoke-JsonScript $restoreScript @{ AgentDir = $agent; PiToolRoot = $core; VerifyOnly = $true }
    $restoreSecond = Invoke-JsonScript $restoreScript @{ AgentDir = $agent; PiToolRoot = $core }
    if (-not $restoreFirst.changed -or $restoreVerify.changed -or $restoreSecond.changed) { throw 'PI_HIGH_CAPACITY_PACKAGING_RESTORE_IDEMPOTENCE_FAILED' }
    $receipt.cases.restore = [ordered]@{ first_changed = $true; verify_changed = $false; second_changed = $false }

    # Retain one exact final file, return to underlay, then prove a mixed state is rejected before any other mutation.
    [void](Invoke-JsonScript $applyScript @{ AgentDir = $agent; PiToolRoot = $core })
    $mixedRelative = 'src\extension\index.ts'
    $mixedFinal = Join-Path $tempRoot 'mixed-final-index.ts'
    Copy-Item -LiteralPath (Join-Path $packageRoot $mixedRelative) -Destination $mixedFinal -Force
    [void](Invoke-JsonScript $restoreScript @{ AgentDir = $agent; PiToolRoot = $core })
    Copy-FileAtomic -Source $mixedFinal -Destination (Join-Path $packageRoot $mixedRelative)
    $mixedError = Assert-ExpectedFailure { & $applyScript -AgentDir $agent -PiToolRoot $core } 'PI_S_HIGH_CAPACITY_SOURCE_CONFLICT*' 'mixed-state'
    Copy-FileAtomic -Source (Join-Path $backupPackage $mixedRelative) -Destination (Join-Path $packageRoot $mixedRelative)
    if (-not (Test-StateEqual (Get-FileSetState $packageRoot $packagePaths) $packageInitial) -or -not (Test-StateEqual (Get-FileSetState $coreRoot $corePaths) $coreInitial)) {
        throw 'PI_HIGH_CAPACITY_PACKAGING_MIXED_ZERO_MUTATION_FAILED'
    }
    $receipt.cases.mixed = [ordered]@{ rejected = $true; error = $mixedError; restored = $true }

    # Let reads/staging proceed but deny replacement of core sdk; package changes must be rolled back.
    $sdkPath = Join-Path $coreRoot 'dist\core\sdk.js'
    $lock = [IO.File]::Open($sdkPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        $rollbackError = Assert-ExpectedFailure { & $applyScript -AgentDir $agent -PiToolRoot $core } 'PI_S_HIGH_CAPACITY_COMMIT_ROLLED_BACK*' 'midcommit-rollback'
    } finally { $lock.Dispose() }
    if (-not (Test-StateEqual (Get-FileSetState $packageRoot $packagePaths) $packageInitial) -or -not (Test-StateEqual (Get-FileSetState $coreRoot $corePaths) $coreInitial)) {
        throw 'PI_HIGH_CAPACITY_PACKAGING_ROLLBACK_NOT_EXACT'
    }
    $receipt.cases.rollback = [ordered]@{ injected = $true; rolled_back = $true; error = $rollbackError }

    # A legal lab whose package entry is a junction must be rejected by all four patch layers.
    Move-Item -LiteralPath $packageRoot -Destination $packageReal
    New-Item -ItemType Junction -Path $packageRoot -Target $packageReal | Out-Null
    try {
        $junctionErrors = @()
        foreach ($scriptPath in @($oldScripts.path) + @($applyScript)) {
            if ($scriptPath -ceq $applyScript) {
                $junctionErrors += Assert-ExpectedFailure { & $scriptPath -AgentDir $agent -PiToolRoot $core } '*REPARSE_POINT_REJECTED*' 'junction-high-capacity'
            } else {
                $junctionErrors += Assert-ExpectedFailure { & $scriptPath -AgentDir $agent } '*REPARSE_POINT_REJECTED*' 'junction-underlay'
            }
        }
    } finally {
        if (Test-Path -LiteralPath $packageRoot) { [IO.Directory]::Delete($packageRoot) }
        Move-Item -LiteralPath $packageReal -Destination $packageRoot
    }
    if ((Get-TreeFingerprint (Join-Path $packageRoot 'src')) -cne $packageTreeInitial) { throw 'PI_HIGH_CAPACITY_PACKAGING_JUNCTION_ZERO_MUTATION_FAILED' }
    $receipt.cases.junction = [ordered]@{ rejected = $true; layers = 4 }

    $stateRoot = Get-NormalizedPackagingPath (Split-Path -Parent $primeSBodyLabs)
    $primeB = Join-Path $stateRoot 'profiles\prime-b'
    $primeBTree = if (Test-Path -LiteralPath (Join-Path $primeB 'npm\node_modules\pi-subagents\src')) { Get-TreeFingerprint (Join-Path $primeB 'npm\node_modules\pi-subagents\src') } else { 'absent' }
    $primeBError = Assert-ExpectedFailure { & $applyScript -AgentDir $primeB -PiToolRoot $core } 'PI_S_HIGH_CAPACITY_TARGET_OUTSIDE_MAIN_PROFILE*' 'prime-b'
    $primeBAfter = if (Test-Path -LiteralPath (Join-Path $primeB 'npm\node_modules\pi-subagents\src')) { Get-TreeFingerprint (Join-Path $primeB 'npm\node_modules\pi-subagents\src') } else { 'absent' }
    if ($primeBAfter -cne $primeBTree) { throw 'PI_HIGH_CAPACITY_PACKAGING_PRIME_B_MUTATED' }
    $receipt.cases.prime_b = [ordered]@{ rejected = $true; unchanged = $true; error = $primeBError }

    if ((Get-TreeFingerprint (Join-Path $packageRoot 'src')) -cne $packageTreeInitial -or (Get-TreeFingerprint (Join-Path $coreRoot 'dist\core')) -cne $coreTreeInitial) {
        throw 'PI_HIGH_CAPACITY_PACKAGING_FINAL_UNDERLAY_DRIFT'
    }
    $receipt.restored_underlay = $true
    $receipt.status = 'verified'
} catch {
    $receipt.status = 'blocked'
    $receipt.error = [string]$_.Exception.Message
} finally {
    try {
        if (Test-Path -LiteralPath $packageRoot) {
            $packageItem = Get-Item -LiteralPath $packageRoot -Force
            if (($packageItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { [IO.Directory]::Delete($packageRoot) }
        }
        if ((Test-Path -LiteralPath $packageReal -PathType Container) -and -not (Test-Path -LiteralPath $packageRoot)) {
            Move-Item -LiteralPath $packageReal -Destination $packageRoot
        }
        if ($null -ne $packageInitial) { Restore-FileSet -Root $packageRoot -RelativePaths $packagePaths -BackupRoot $backupPackage -Expected $packageInitial }
        if ($null -ne $coreInitial) { Restore-FileSet -Root $coreRoot -RelativePaths $corePaths -BackupRoot $backupCore -Expected $coreInitial }
        if ($null -ne $packageTreeInitial -and $null -ne $coreTreeInitial) {
            $receipt.restored_underlay = ((Get-TreeFingerprint (Join-Path $packageRoot 'src')) -ceq $packageTreeInitial -and (Get-TreeFingerprint (Join-Path $coreRoot 'dist\core')) -ceq $coreTreeInitial)
        }
    } catch {
        $receipt.status = 'blocked'
        $receipt.error = "PI_HIGH_CAPACITY_PACKAGING_FINAL_RESTORE_FAILED: $($_.Exception.Message); prior=$($receipt.error)"
    }
    $resolvedTemp = Get-NormalizedPackagingPath $tempRoot
    $requiredPrefix = (Get-NormalizedPackagingPath $tempParent) + [IO.Path]::DirectorySeparatorChar
    if ($resolvedTemp.StartsWith($requiredPrefix,[StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolvedTemp) -match '^[a-f0-9]{32}$') {
        if (Test-Path -LiteralPath $resolvedTemp -PathType Container) { Remove-Item -LiteralPath $resolvedTemp -Recurse -Force }
        $receipt.temp_cleanup = -not (Test-Path -LiteralPath $resolvedTemp)
    }
    if (-not $receipt.restored_underlay -or -not $receipt.temp_cleanup) {
        $receipt.status = 'blocked'
        if ([string]::IsNullOrWhiteSpace([string]$receipt.error)) { $receipt.error = 'PI_HIGH_CAPACITY_PACKAGING_FINAL_INVARIANT_FAILED' }
    }
    $receipt.completed_at = [DateTimeOffset]::Now.ToString('o')
    $json = $receipt | ConvertTo-Json -Depth 14
    if (-not [string]::IsNullOrWhiteSpace($ReceiptPath)) { Write-JsonAtomic -Path $ReceiptPath -Json $json }
    [Console]::Out.WriteLine($json)
}

if ($receipt.status -cne 'verified') { exit 1 }
