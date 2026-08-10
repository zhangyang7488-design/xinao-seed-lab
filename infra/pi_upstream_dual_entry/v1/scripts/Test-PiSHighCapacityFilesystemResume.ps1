#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AgentDir,
    [Parameter(Mandatory)][string]$PiToolRoot,
    [Parameter(Mandatory)][string]$WorkRoot,
    [Parameter(Mandatory)][string]$ReceiptPath,
    [ValidateRange(30000,600000)][int]$TimeoutMs = 120000
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$CanonicalHarnessSha256 = 'ffd09a360411fd32c4764a8369d61a58effdd973e564d111be2a400db6ea53d6'
$AllowedAgentParent = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\body-labs\prime-s'
$AllowedWorkParent = 'D:\XINAO_RESEARCH_RUNTIME\temp\body-lab'
$ExpectedPiVersion = '0.84.1'
$ExpectedSubagentsVersion = '0.44.0'

if (-not ('XinaoPiHighCapacityFinalPath' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class XinaoPiHighCapacityFinalPath {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string path,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(
        SafeFileHandle handle,
        StringBuilder path,
        uint pathLength,
        uint flags);

    public static string Get(string path) {
        const uint FileShareReadWriteDelete = 7;
        const uint OpenExisting = 3;
        const uint FileFlagBackupSemantics = 0x02000000;
        using (SafeFileHandle handle = CreateFileW(path, 0, FileShareReadWriteDelete, IntPtr.Zero, OpenExisting, FileFlagBackupSemantics, IntPtr.Zero)) {
            if (handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
            StringBuilder buffer = new StringBuilder(32768);
            uint length = GetFinalPathNameByHandleW(handle, buffer, (uint)buffer.Capacity, 0);
            if (length == 0 || length >= buffer.Capacity) throw new Win32Exception(Marshal.GetLastWin32Error());
            string value = buffer.ToString();
            if (value.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)) return @"\\" + value.Substring(8);
            if (value.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase)) return value.Substring(4);
            return value;
        }
    }
}
'@
}

function Get-NormalizedHighCapacityFilesystemPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\','/')
}

function Test-HighCapacityFilesystemPathEqual {
    param([Parameter(Mandatory)][string]$Left,[Parameter(Mandatory)][string]$Right)
    [string]::Equals(
        (Get-NormalizedHighCapacityFilesystemPath $Left),
        (Get-NormalizedHighCapacityFilesystemPath $Right),
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Test-HighCapacityFilesystemPathWithin {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Parent)
    $target = Get-NormalizedHighCapacityFilesystemPath $Path
    $prefix = (Get-NormalizedHighCapacityFilesystemPath $Parent) + [IO.Path]::DirectorySeparatorChar
    $target.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)
}

function Assert-HighCapacityFilesystemNoReparseAncestor {
    param([Parameter(Mandatory)][string]$Path)
    $cursor = Get-NormalizedHighCapacityFilesystemPath $Path
    $root = [IO.Path]::GetPathRoot($cursor)
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_REPARSE_ANCESTOR_REJECTED: $cursor"
            }
        }
        if (Test-HighCapacityFilesystemPathEqual $cursor $root) { break }
        $parent = Split-Path -Parent $cursor
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ceq $cursor) { break }
        $cursor = $parent
    }
}

function Get-HighCapacityFilesystemGuardedRealPath {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][ValidateSet('Leaf','Container')][string]$PathType,
        [Parameter(Mandatory)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType $PathType)) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_REALPATH_TARGET_MISSING: ${Label}: $Path"
    }
    Assert-HighCapacityFilesystemNoReparseAncestor $Path
    $lexical = Get-NormalizedHighCapacityFilesystemPath $Path
    $real = Get-NormalizedHighCapacityFilesystemPath ([XinaoPiHighCapacityFinalPath]::Get($lexical))
    if (-not (Test-HighCapacityFilesystemPathEqual $lexical $real)) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_REALPATH_IDENTITY_DRIFT: ${Label}: lexical=$lexical real=$real"
    }
    $real
}

function Assert-HighCapacityFilesystemRealPathWithin {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][ValidateSet('Leaf','Container')][string]$PathType,
        [Parameter(Mandatory)][string]$ParentRealPath,
        [Parameter(Mandatory)][string]$Label
    )
    $real = Get-HighCapacityFilesystemGuardedRealPath -Path $Path -PathType $PathType -Label $Label
    if (-not (Test-HighCapacityFilesystemPathWithin $real $ParentRealPath)) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_REALPATH_CONTAINMENT_FAILED: ${Label}: path=$real parent=$ParentRealPath"
    }
    $real
}

function Get-HighCapacityFilesystemSha256Text {
    param([Parameter(Mandatory)][string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($Text))
        ([BitConverter]::ToString($digest)).Replace('-','').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-HighCapacityFilesystemVerifiedPackageIdentity {
    param(
        [Parameter(Mandatory)][string]$PackageRoot,
        [Parameter(Mandatory)][string]$ContainingRealPath,
        [Parameter(Mandatory)][string]$ExpectedName,
        [Parameter(Mandatory)][string]$ExpectedVersion,
        [Parameter(Mandatory)][string]$Label
    )
    $rootReal = Assert-HighCapacityFilesystemRealPathWithin -Path $PackageRoot -PathType Container -ParentRealPath $ContainingRealPath -Label "$Label root"
    $packageJsonPath = Join-Path $PackageRoot 'package.json'
    $packageJsonReal = Assert-HighCapacityFilesystemRealPathWithin -Path $packageJsonPath -PathType Leaf -ParentRealPath $rootReal -Label "$Label package.json"
    $packageJson = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
    if ([string]$packageJson.name -cne $ExpectedName -or [string]$packageJson.version -cne $ExpectedVersion) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_PACKAGE_IDENTITY_DRIFT: ${Label}: expected=$ExpectedName@$ExpectedVersion actual=$($packageJson.name)@$($packageJson.version)"
    }
    [ordered]@{
        label = $Label
        root = $rootReal
        package_json = $packageJsonReal
        package_json_bytes = (Get-Item -LiteralPath $packageJsonPath -Force).Length
        package_json_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $packageJsonPath).Hash.ToLowerInvariant()
        name = [string]$packageJson.name
        version = [string]$packageJson.version
        no_reparse = $true
        realpath_contained = $true
    }
}

function Get-HighCapacityFilesystemFileState {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ present = $false; bytes = 0; sha256 = 'absent' }
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_FILE_REPARSE_REJECTED: $Path"
    }
    [ordered]@{
        present = $true
        bytes = [long]$item.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    }
}

function Test-HighCapacityFilesystemFileStateEqual {
    param([Parameter(Mandatory)]$Left,[Parameter(Mandatory)]$Right)
    [bool]$Left.present -eq [bool]$Right.present -and
        [long]$Left.bytes -eq [long]$Right.bytes -and
        [string]$Left.sha256 -ceq [string]$Right.sha256
}

function Get-HighCapacityFilesystemTreeFingerprint {
    param([Parameter(Mandatory)][string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return 'absent' }
    $normalized = Get-NormalizedHighCapacityFilesystemPath $Root
    $rootItem = Get-Item -LiteralPath $normalized -Force
    if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_TREE_REPARSE_REJECTED: $normalized"
    }
    $builder = New-Object Text.StringBuilder
    foreach ($entry in @(Get-ChildItem -LiteralPath $normalized -Recurse -Force | Sort-Object FullName)) {
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_TREE_REPARSE_REJECTED: $($entry.FullName)"
        }
        $relative = $entry.FullName.Substring($normalized.Length + 1).Replace('\','/')
        if ($entry -is [IO.DirectoryInfo]) {
            [void]$builder.Append('D').Append("`t").Append($relative).Append("`n")
        } elseif ($entry -is [IO.FileInfo]) {
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $entry.FullName).Hash.ToLowerInvariant()
            [void]$builder.Append('F').Append("`t").Append($relative).Append("`t").Append($entry.Length).Append("`t").Append($hash).Append("`n")
        } else {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_TREE_ENTRY_TYPE_REJECTED: $($entry.FullName)"
        }
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($builder.ToString()))
        ([BitConverter]::ToString($digest)).Replace('-','').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-HighCapacityFilesystemDirectoryEmpty {
    param([Parameter(Mandatory)][string]$Path)
    (Test-Path -LiteralPath $Path -PathType Container) -and
        @(Get-ChildItem -LiteralPath $Path -Force).Count -eq 0
}

function Replace-HighCapacityFilesystemTextExactlyOnce {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Anchor,
        [Parameter(Mandatory)][string]$Replacement,
        [Parameter(Mandatory)][string]$Label
    )
    $first = $Text.IndexOf($Anchor,[StringComparison]::Ordinal)
    if ($first -lt 0) { throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_PROJECTION_ANCHOR_MISSING: $Label" }
    if ($Text.IndexOf($Anchor,$first + $Anchor.Length,[StringComparison]::Ordinal) -ge 0) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_PROJECTION_ANCHOR_AMBIGUOUS: $Label"
    }
    $Text.Substring(0,$first) + $Replacement + $Text.Substring($first + $Anchor.Length)
}

function ConvertTo-HighCapacityFilesystemNativeArgument {
    param([AllowEmptyString()][string]$Value)
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = New-Object Text.StringBuilder
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $slashes++
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($slashes * 2) + 1)))
            [void]$builder.Append('"')
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) {
            [void]$builder.Append(('\' * $slashes))
            $slashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($slashes -gt 0) { [void]$builder.Append(('\' * ($slashes * 2))) }
    [void]$builder.Append('"')
    $builder.ToString()
}

function Invoke-HighCapacityFilesystemHiddenProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][hashtable]$EnvironmentOverrides,
        [Parameter(Mandatory)][int]$ProcessTimeoutMs
    )
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $quotedArguments = @($Arguments | ForEach-Object { ConvertTo-HighCapacityFilesystemNativeArgument ([string]$_) })
    $startInfo.Arguments = $quotedArguments -join ' '
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($entry in $EnvironmentOverrides.GetEnumerator()) {
        $environmentKey = [string]$entry.Key
        if ($startInfo.EnvironmentVariables.ContainsKey($environmentKey)) {
            $startInfo.EnvironmentVariables.Remove($environmentKey)
        }
        $startInfo.EnvironmentVariables[$environmentKey] = [string]$entry.Value
    }
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_PROCESS_START_FAILED' }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($ProcessTimeoutMs)) {
            try { $process.Kill() } catch { }
            $process.WaitForExit()
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_PROCESS_TIMEOUT: milliseconds=$ProcessTimeoutMs"
        }
        [Threading.Tasks.Task]::WaitAll(@($stdoutTask,$stderrTask))
        [ordered]@{
            exit_code = [int]$process.ExitCode
            stdout = [string]$stdoutTask.Result
            stderr = [string]$stderrTask.Result
        }
    } finally {
        $process.Dispose()
    }
}

function Write-HighCapacityFilesystemJsonAtomic {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)]$Value)
    $target = Get-NormalizedHighCapacityFilesystemPath $Path
    $parent = Split-Path -Parent $target
    if (-not [string]::IsNullOrWhiteSpace($parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temporary = "$target.tmp-$PID-$([Guid]::NewGuid().ToString('N'))"
    try {
        $json = $Value | ConvertTo-Json -Depth 18
        [IO.File]::WriteAllText($temporary,"$json`n",[Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $target -Force
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Test-HighCapacityFilesystemExactBudget {
    param([Parameter(Mandatory)]$Budget)
    if ($null -eq $Budget) { return $false }
    $names = @($Budget.PSObject.Properties.Name | Sort-Object)
    $names.Count -eq 2 -and
        $names[0] -ceq 'graceTurns' -and
        $names[1] -ceq 'maxTurns' -and
        [int]$Budget.maxTurns -eq 30 -and
        [int]$Budget.graceTurns -eq 0
}

function Restore-HighCapacityFilesystemChildSessions {
    param(
        [Parameter(Mandatory)][string]$ChildRoot,
        [Parameter(Mandatory)][string]$SessionsRoot,
        [Parameter(Mandatory)][bool]$ChildRootExisted,
        [Parameter(Mandatory)][bool]$SessionsRootExisted,
        [Parameter(Mandatory)][hashtable]$EntryNamesBefore,
        [Parameter(Mandatory)][string]$FingerprintBefore
    )
    $removedDirectories = 0
    $removedFiles = 0
    $removedBytes = [long]0
    $descendantsScanned = 0
    Assert-HighCapacityFilesystemNoReparseAncestor $SessionsRoot
    Assert-HighCapacityFilesystemNoReparseAncestor $ChildRoot
    if (Test-Path -LiteralPath $ChildRoot) {
        $childRootNormalized = Get-NormalizedHighCapacityFilesystemPath $ChildRoot
        foreach ($entry in @(Get-ChildItem -LiteralPath $childRootNormalized -Force)) {
            if ($EntryNamesBefore.ContainsKey($entry.Name.ToLowerInvariant())) { continue }
            if (-not ($entry -is [IO.DirectoryInfo]) -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $entry.Name -notmatch '^[a-f0-9]{8}$') {
                throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_UNCLASSIFIED_CHILD_SESSION_ARTIFACT: $($entry.FullName)"
            }
            $resolved = Get-NormalizedHighCapacityFilesystemPath $entry.FullName
            if (-not (Test-HighCapacityFilesystemPathEqual (Split-Path -Parent $resolved) $childRootNormalized)) {
                throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_SESSION_TARGET_ESCAPED: $resolved"
            }
            $descendants = @(Get-ChildItem -LiteralPath $resolved -Recurse -Force)
            $descendantsScanned += $descendants.Count
            foreach ($descendant in $descendants) {
                if (($descendant.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                    throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_NESTED_CHILD_SESSION_REPARSE_REJECTED: $($descendant.FullName)"
                }
            }
            $files = @($descendants | Where-Object { $_ -is [IO.FileInfo] })
            $removedFiles += $files.Count
            if ($files.Count -gt 0) {
                $removedBytes += [long](($files | Measure-Object -Property Length -Sum).Sum)
            }
            Remove-Item -LiteralPath $resolved -Recurse -Force
            if (Test-Path -LiteralPath $resolved) {
                throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_SESSION_RETIRE_FAILED: $resolved"
            }
            $removedDirectories++
        }
    }
    if (-not $ChildRootExisted -and (Test-Path -LiteralPath $ChildRoot -PathType Container)) {
        if (@(Get-ChildItem -LiteralPath $ChildRoot -Force).Count -ne 0) {
            throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CREATED_CHILD_SESSION_ROOT_NOT_EMPTY'
        }
        [IO.Directory]::Delete((Get-NormalizedHighCapacityFilesystemPath $ChildRoot))
    }
    if (-not $SessionsRootExisted -and (Test-Path -LiteralPath $SessionsRoot -PathType Container)) {
        if (@(Get-ChildItem -LiteralPath $SessionsRoot -Force).Count -ne 0) {
            throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CREATED_SESSIONS_ROOT_NOT_EMPTY'
        }
        [IO.Directory]::Delete((Get-NormalizedHighCapacityFilesystemPath $SessionsRoot))
    }
    $fingerprintAfter = Get-HighCapacityFilesystemTreeFingerprint $ChildRoot
    if ($fingerprintAfter -cne $FingerprintBefore) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_SESSION_TREE_NOT_RESTORED: before=$FingerprintBefore after=$fingerprintAfter"
    }
    [ordered]@{
        initial_state = $(if ($ChildRootExisted) { 'present' } else { 'absent' })
        final_state = $(if (Test-Path -LiteralPath $ChildRoot) { 'present' } else { 'absent' })
        fingerprint_before = $FingerprintBefore
        fingerprint_after = $fingerprintAfter
        new_session_directories_removed = $removedDirectories
        files_removed = $removedFiles
        bytes_removed = $removedBytes
        preexisting_direct_entries = $EntryNamesBefore.Count
        preexisting_entries_preserved = $true
        descendants_scanned_before_delete = $descendantsScanned
        nested_reparse_points_found = 0
        reparse_points_followed = 0
        restored_exactly = $true
    }
}

function Restore-HighCapacityFilesystemExactFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$StateBefore,
        [Parameter(Mandatory)][string]$BackupPath
    )
    $target = Get-NormalizedHighCapacityFilesystemPath $Path
    Assert-HighCapacityFilesystemNoReparseAncestor $target
    if ([bool]$StateBefore.present) {
        if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_FILE_BACKUP_MISSING: $BackupPath"
        }
        $backupState = Get-HighCapacityFilesystemFileState $BackupPath
        if (-not (Test-HighCapacityFilesystemFileStateEqual $StateBefore $backupState)) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_FILE_BACKUP_DRIFTED: $BackupPath"
        }
        $temporary = "$target.restore-$PID-$([Guid]::NewGuid().ToString('N')).tmp"
        try {
            [IO.File]::WriteAllBytes($temporary,[IO.File]::ReadAllBytes($BackupPath))
            Move-Item -LiteralPath $temporary -Destination $target -Force
        } finally {
            if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
        }
    } elseif (Test-Path -LiteralPath $target) {
        $item = Get-Item -LiteralPath $target -Force
        if (-not ($item -is [IO.FileInfo]) -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_UNCLASSIFIED_MUTABLE_FILE: $target"
        }
        Remove-Item -LiteralPath $target -Force
    }
    $stateAfter = Get-HighCapacityFilesystemFileState $target
    if (-not (Test-HighCapacityFilesystemFileStateEqual $StateBefore $stateAfter)) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_MUTABLE_FILE_NOT_RESTORED: $target"
    }
    [ordered]@{
        path = $target
        initial_present = [bool]$StateBefore.present
        initial_bytes = [long]$StateBefore.bytes
        initial_sha256 = [string]$StateBefore.sha256
        final_present = [bool]$stateAfter.present
        final_bytes = [long]$stateAfter.bytes
        final_sha256 = [string]$stateAfter.sha256
        restored_exactly = $true
    }
}

$agent = Get-NormalizedHighCapacityFilesystemPath $AgentDir
$piRoot = Get-NormalizedHighCapacityFilesystemPath $PiToolRoot
$work = Get-NormalizedHighCapacityFilesystemPath $WorkRoot
$receiptTarget = Get-NormalizedHighCapacityFilesystemPath $ReceiptPath
$allowedAgentRoot = Get-NormalizedHighCapacityFilesystemPath $AllowedAgentParent
$allowedWorkRoot = Get-NormalizedHighCapacityFilesystemPath $AllowedWorkParent

if (-not (Test-HighCapacityFilesystemPathWithin $agent $allowedAgentRoot)) {
    throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_DISPOSABLE_MAIN_LAB_REQUIRED: $agent"
}
if (-not (Test-HighCapacityFilesystemPathEqual $piRoot (Join-Path $agent 'pi-tool-root'))) {
    throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_ROOT_PAIR_MISMATCH: agent=$agent pi_tool_root=$piRoot"
}
if (-not (Test-HighCapacityFilesystemPathWithin $work $allowedWorkRoot)) {
    throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_WORK_ROOT_OUTSIDE_ALLOWED_PARENT: $work"
}
if (Test-Path -LiteralPath $work) {
    throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_WORK_ROOT_ALREADY_EXISTS: $work"
}
Assert-HighCapacityFilesystemNoReparseAncestor $agent
Assert-HighCapacityFilesystemNoReparseAncestor $piRoot
Assert-HighCapacityFilesystemNoReparseAncestor $work

$agentNodeModules = Join-Path $agent 'npm\node_modules'
$packageRoot = Join-Path $agentNodeModules 'pi-subagents'
$settingsPath = Join-Path $agent 'settings.json'
$modelsPath = Join-Path $agent 'models.json'
$capacityConfigPath = Join-Path $agent 'extensions\subagent\config.json'
$authPath = Join-Path $agent 'auth.json'
$modelsStorePath = Join-Path $agent 'models-store.json'
$runHistoryPath = Join-Path $agent 'run-history.jsonl'
$piSpawnSourcePath = Join-Path $packageRoot 'src\runs\shared\pi-spawn.ts'
$agentSessionsRoot = Join-Path $agent 'sessions'
$childSessionsRoot = Join-Path $agentSessionsRoot 'children'
$stopFixtureAgentPaths = @(
    (Join-Path $agent 'agents\stop-fixture.md'),
    (Join-Path $agent 'agents\stop-race-fixture.md')
)
$piToolNodeModules = Join-Path $piRoot 'node_modules'
$piToolScopeRoot = Join-Path $piToolNodeModules '@earendil-works'
$piCodingAgentRoot = Join-Path $piToolScopeRoot 'pi-coding-agent'
$isolatedCodingAgentNodeModules = Join-Path $piCodingAgentRoot 'node_modules'
$piPeerRoot = Join-Path $isolatedCodingAgentNodeModules '@earendil-works'
$piAgentCoreRoot = Join-Path $piPeerRoot 'pi-agent-core'
$piAiRoot = Join-Path $piPeerRoot 'pi-ai'
$piTuiRoot = Join-Path $piPeerRoot 'pi-tui'
$cliPath = Join-Path $piCodingAgentRoot 'dist\cli.js'
$sdkPath = Join-Path $piCodingAgentRoot 'dist\core\sdk.js'
$extensionRunnerPath = Join-Path $piCodingAgentRoot 'dist\core\extensions\runner.js'
$piAgentCoreEntryPath = Join-Path $piAgentCoreRoot 'dist\index.js'
$piAiEntryPath = Join-Path $piAiRoot 'dist\index.js'
$piTuiEntryPath = Join-Path $piTuiRoot 'dist\index.js'
$rpcClientPath = Join-Path $piCodingAgentRoot 'dist\modes\rpc\rpc-client.js'
$canonicalHarness = Join-Path $PSScriptRoot 'Test-PiSubagentFilesystemPolicyBodyLab.mjs'
$stopHarness = Join-Path $PSScriptRoot 'Test-PiSubagentSessionStopProcess.mjs'
$stopExtension = Join-Path $PSScriptRoot 'fixtures\pi-owner-stop-autolaunch.ts'
$stopFixture = Join-Path $PSScriptRoot 'fixtures\pi-owner-stop-child.mjs'
$requiredFiles = @(
    (Join-Path $packageRoot 'package.json'),
    (Join-Path $packageRoot 'src\runs\background\async-execution.ts'),
    (Join-Path $packageRoot 'src\runs\background\async-resume.ts'),
    $piSpawnSourcePath,
    (Join-Path $piAgentCoreRoot 'package.json'),
    (Join-Path $piAiRoot 'package.json'),
    (Join-Path $piTuiRoot 'package.json'),
    $cliPath,
    $sdkPath,
    $extensionRunnerPath,
    $piAgentCoreEntryPath,
    $piAiEntryPath,
    $piTuiEntryPath,
    $rpcClientPath,
    $canonicalHarness,
    $stopHarness,
    $stopExtension,
    $stopFixture,
    $capacityConfigPath
)
foreach ($requiredFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_REQUIRED_FILE_MISSING: $requiredFile"
    }
}

$agentReal = Get-HighCapacityFilesystemGuardedRealPath -Path $agent -PathType Container -Label 'AgentDir'
$piRootReal = Assert-HighCapacityFilesystemRealPathWithin -Path $piRoot -PathType Container -ParentRealPath $agentReal -Label 'paired PiToolRoot'
$agentNodeModulesReal = Assert-HighCapacityFilesystemRealPathWithin -Path $agentNodeModules -PathType Container -ParentRealPath $agentReal -Label 'AgentDir npm node_modules'
$subagentsPackageIdentity = Get-HighCapacityFilesystemVerifiedPackageIdentity `
    -PackageRoot $packageRoot `
    -ContainingRealPath $agentNodeModulesReal `
    -ExpectedName 'pi-subagents' `
    -ExpectedVersion $ExpectedSubagentsVersion `
    -Label 'pi-subagents'
$piToolNodeModulesReal = Assert-HighCapacityFilesystemRealPathWithin -Path $piToolNodeModules -PathType Container -ParentRealPath $piRootReal -Label 'PiToolRoot node_modules'
$piCodingAgentIdentity = Get-HighCapacityFilesystemVerifiedPackageIdentity `
    -PackageRoot $piCodingAgentRoot `
    -ContainingRealPath $piToolNodeModulesReal `
    -ExpectedName '@earendil-works/pi-coding-agent' `
    -ExpectedVersion $ExpectedPiVersion `
    -Label 'isolated pi-coding-agent'
$isolatedCodingAgentNodeModulesReal = Assert-HighCapacityFilesystemRealPathWithin -Path $isolatedCodingAgentNodeModules -PathType Container -ParentRealPath $piCodingAgentIdentity.root -Label 'isolated pi-coding-agent node_modules'
$piAgentCoreIdentity = Get-HighCapacityFilesystemVerifiedPackageIdentity -PackageRoot $piAgentCoreRoot -ContainingRealPath $isolatedCodingAgentNodeModulesReal -ExpectedName '@earendil-works/pi-agent-core' -ExpectedVersion $ExpectedPiVersion -Label 'isolated pi-agent-core'
$piAiIdentity = Get-HighCapacityFilesystemVerifiedPackageIdentity -PackageRoot $piAiRoot -ContainingRealPath $isolatedCodingAgentNodeModulesReal -ExpectedName '@earendil-works/pi-ai' -ExpectedVersion $ExpectedPiVersion -Label 'isolated pi-ai'
$piTuiIdentity = Get-HighCapacityFilesystemVerifiedPackageIdentity -PackageRoot $piTuiRoot -ContainingRealPath $isolatedCodingAgentNodeModulesReal -ExpectedName '@earendil-works/pi-tui' -ExpectedVersion $ExpectedPiVersion -Label 'isolated pi-tui'
$cliReal = Assert-HighCapacityFilesystemRealPathWithin -Path $cliPath -PathType Leaf -ParentRealPath $piCodingAgentIdentity.root -Label 'isolated Pi CLI'
$sdkReal = Assert-HighCapacityFilesystemRealPathWithin -Path $sdkPath -PathType Leaf -ParentRealPath $piCodingAgentIdentity.root -Label 'isolated Pi SDK'
$extensionRunnerReal = Assert-HighCapacityFilesystemRealPathWithin -Path $extensionRunnerPath -PathType Leaf -ParentRealPath $piCodingAgentIdentity.root -Label 'isolated Pi extension runner'
$piAgentCoreEntryReal = Assert-HighCapacityFilesystemRealPathWithin -Path $piAgentCoreEntryPath -PathType Leaf -ParentRealPath $piAgentCoreIdentity.root -Label 'isolated pi-agent-core entry'
$piAiEntryReal = Assert-HighCapacityFilesystemRealPathWithin -Path $piAiEntryPath -PathType Leaf -ParentRealPath $piAiIdentity.root -Label 'isolated pi-ai entry'
$piTuiEntryReal = Assert-HighCapacityFilesystemRealPathWithin -Path $piTuiEntryPath -PathType Leaf -ParentRealPath $piTuiIdentity.root -Label 'isolated pi-tui entry'
$rpcClientReal = Assert-HighCapacityFilesystemRealPathWithin -Path $rpcClientPath -PathType Leaf -ParentRealPath $piCodingAgentIdentity.root -Label 'isolated Pi RPC client'
$cliIdentityState = Get-HighCapacityFilesystemFileState $cliPath
$rpcIdentityState = Get-HighCapacityFilesystemFileState $rpcClientPath
$piCodingAgentIdentity['cli_realpath'] = $cliReal
$piCodingAgentIdentity['cli_bytes'] = $cliIdentityState.bytes
$piCodingAgentIdentity['cli_sha256'] = $cliIdentityState.sha256
$piCodingAgentIdentity['sdk_realpath'] = $sdkReal
$piCodingAgentIdentity['sdk_sha256'] = (Get-FileHash -Algorithm SHA256 -LiteralPath $sdkPath).Hash.ToLowerInvariant()
$piCodingAgentIdentity['extension_runner_realpath'] = $extensionRunnerReal
$piCodingAgentIdentity['extension_runner_sha256'] = (Get-FileHash -Algorithm SHA256 -LiteralPath $extensionRunnerPath).Hash.ToLowerInvariant()
$piCodingAgentIdentity['rpc_client_realpath'] = $rpcClientReal
$piCodingAgentIdentity['rpc_client_bytes'] = $rpcIdentityState.bytes
$piCodingAgentIdentity['rpc_client_sha256'] = $rpcIdentityState.sha256
$piCodingAgentIdentity['isolated_package_identity_sha256'] = Get-HighCapacityFilesystemSha256Text (@(
    $piCodingAgentIdentity.root,
    $piCodingAgentIdentity.name,
    $piCodingAgentIdentity.version,
    $piCodingAgentIdentity.package_json_sha256,
    $cliIdentityState.sha256,
    $rpcIdentityState.sha256
) -join "`n")

$nodePathEntries = @($agentNodeModulesReal,$piToolNodeModulesReal,$isolatedCodingAgentNodeModulesReal)
$isolatedNodePath = $nodePathEntries -join [IO.Path]::PathSeparator
$rootProcessEnvironmentOverrides = @{
    PI_SUBAGENT_PI_BINARY = ' '
    PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT = [string]$piCodingAgentIdentity.root
    NODE_PATH = $isolatedNodePath
}
$processEnvironmentKeys = @('PI_SUBAGENT_PI_BINARY','PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT','NODE_PATH','NODE_OPTIONS','XINAO_PI_HIGH_CAPACITY_CHILD_IDENTITY_CONFIG')
$parentEnvironmentBefore = [ordered]@{}
foreach ($key in $processEnvironmentKeys) {
    $parentEnvironmentBefore[$key] = [Environment]::GetEnvironmentVariable($key,[EnvironmentVariableTarget]::Process)
}

$agentSessionsRootExisted = Test-Path -LiteralPath $agentSessionsRoot -PathType Container
$childSessionsRootExisted = Test-Path -LiteralPath $childSessionsRoot -PathType Container
$childSessionsFingerprintBefore = Get-HighCapacityFilesystemTreeFingerprint $childSessionsRoot
$childSessionEntryNamesBefore = @{}
if ($childSessionsRootExisted) {
    foreach ($entry in @(Get-ChildItem -LiteralPath $childSessionsRoot -Force)) {
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_PREEXISTING_CHILD_SESSION_REPARSE_REJECTED: $($entry.FullName)"
        }
        $childSessionEntryNamesBefore[$entry.Name.ToLowerInvariant()] = $true
    }
}

$actualCanonicalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $canonicalHarness).Hash.ToLowerInvariant()
if ($actualCanonicalHash -cne $CanonicalHarnessSha256) {
    throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CANONICAL_HASH_MISMATCH: expected=$CanonicalHarnessSha256 actual=$actualCanonicalHash"
}

New-Item -ItemType Directory -Force -Path $work | Out-Null
$allowedWorkParentReal = Get-HighCapacityFilesystemGuardedRealPath -Path $allowedWorkRoot -PathType Container -Label 'allowed body-lab parent'
$workReal = Assert-HighCapacityFilesystemRealPathWithin -Path $work -PathType Container -ParentRealPath $allowedWorkParentReal -Label 'caller WorkRoot'
$moduleRoot = Join-Path $work 'package-source'
$codexHome = Join-Path $work 'codex-home'
$fixtureRoot = Join-Path $work 'fixture'
$sessionDir = Join-Path $work 'root-sessions'
$projectedHarness = Join-Path $work 'Test-PiSubagentFilesystemPolicyBodyLab.high-capacity-projected.mjs'
$bodyReceiptPath = Join-Path $work 'body-lab-receipt.json'
$mutableAgentBackupRoot = Join-Path $work 'baseline-agent-files'
$childIdentityDirectory = Join-Path $work 'actual-child-identity'
$childIdentityPreloadPath = Join-Path $work 'actual-child-identity-preload.mjs'
$childIdentityConfigPath = Join-Path $work 'actual-child-identity-config.json'
New-Item -ItemType Directory -Force -Path $moduleRoot,$codexHome,$mutableAgentBackupRoot,$childIdentityDirectory | Out-Null
$moduleRootReal = Assert-HighCapacityFilesystemRealPathWithin -Path $moduleRoot -PathType Container -ParentRealPath $workReal -Label 'fixture package-source root'
$codexHomeReal = Assert-HighCapacityFilesystemRealPathWithin -Path $codexHome -PathType Container -ParentRealPath $workReal -Label 'fixture CodexHome'
$mutableAgentBackupRootReal = Assert-HighCapacityFilesystemRealPathWithin -Path $mutableAgentBackupRoot -PathType Container -ParentRealPath $workReal -Label 'fixture baseline backup root'
$childIdentityDirectoryReal = Assert-HighCapacityFilesystemRealPathWithin -Path $childIdentityDirectory -PathType Container -ParentRealPath $workReal -Label 'actual child identity evidence root'
$childIdentityDiagnosticDirectory = Join-Path $childIdentityDirectory 'preload-start'
New-Item -ItemType Directory -Force -Path $childIdentityDiagnosticDirectory | Out-Null
$childIdentityDiagnosticDirectoryReal = Assert-HighCapacityFilesystemRealPathWithin -Path $childIdentityDiagnosticDirectory -PathType Container -ParentRealPath $childIdentityDirectoryReal -Label 'actual child preload diagnostic root'

$childIdentityPreloadSource = @'
import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CONFIG_ENV = "XINAO_PI_HIGH_CAPACITY_CHILD_IDENTITY_CONFIG";

function sha256(value) {
	return createHash("sha256").update(value).digest("hex");
}

function realpath(value) {
	return (fs.realpathSync.native ?? fs.realpathSync)(value);
}

function pathEqual(left, right) {
	return path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase();
}

function pathWithin(value, root) {
	const candidate = path.resolve(value).toLowerCase();
	const prefix = `${path.resolve(root).toLowerCase()}${path.sep}`;
	return candidate.startsWith(prefix);
}

function packageIdentityFromEntry(entryPath, expectedName) {
	let cursor = path.dirname(entryPath);
	while (true) {
		const packageJsonPath = path.join(cursor, "package.json");
		if (fs.existsSync(packageJsonPath)) {
			const raw = fs.readFileSync(packageJsonPath);
			const parsed = JSON.parse(raw.toString("utf8"));
			if (parsed.name === expectedName) {
				return {
					rootRealpath: realpath(cursor),
					name: parsed.name,
					version: parsed.version,
					packageJsonRealpath: realpath(packageJsonPath),
					packageJsonBytes: raw.byteLength,
					packageJsonSha256: sha256(raw),
				};
			}
		}
		const parent = path.dirname(cursor);
		if (parent === cursor) break;
		cursor = parent;
	}
	throw new Error(`actual child package root not found for ${expectedName}: ${entryPath}`);
}

function fileIdentity(filePath) {
	const resolved = realpath(filePath);
	const content = fs.readFileSync(resolved);
	return { realpath: resolved, bytes: content.byteLength, sha256: sha256(content) };
}

const configPath = process.env[CONFIG_ENV];
if (typeof configPath === "string" && configPath.length > 0) {
	const configRaw = fs.readFileSync(configPath);
	const config = JSON.parse(configRaw.toString("utf8"));
	const argv1 = process.argv[1];
	fs.mkdirSync(config.diagnosticDirectory, { recursive: true });
	fs.writeFileSync(path.join(config.diagnosticDirectory, `${process.pid}.json`), `${JSON.stringify({ pid: process.pid, ppid: process.ppid, child: process.env.PI_SUBAGENT_CHILD ?? null, argv: process.argv, nodeOptions: process.env.NODE_OPTIONS ?? null, configPath }, null, 2)}\n`, "utf8");
	if (process.env.PI_SUBAGENT_CHILD === "1" && typeof argv1 === "string" && pathEqual(realpath(argv1), config.expectedEntries.piCodingAgentCli)) {
		const observedExactLoads = new Map();
		const unexpectedTargetLoads = new Set();
		const exactEntries = Object.entries(config.expectedEntries);
		const expectedRoots = Object.values(config.expectedRoots);
		const targetPackagePattern = /[\\/]node_modules[\\/]@earendil-works[\\/]pi-(?:coding-agent|agent-core|ai|tui)[\\/]/i;
		const requiredLoadedLabels = ["piCodingAgentCli", "piAgentCoreEntry", "piAiEntry", "piTuiEntry"];
		const probeInstance = randomUUID();
		const argvText = process.argv.join("\n");
		const caseName = argvText.match(/CASE_[A-Z0-9_]+/)?.[0];
		const labRunMarker = argvText.match(/LAB_RUN_[0-9a-f-]{36}/i)?.[0];
		let identityWritten = false;

		function buildPayload(identityFileName, recordedAtMs) {
			const loadedEntries = Object.fromEntries([...observedExactLoads.entries()].sort(([left], [right]) => left.localeCompare(right)));
			const packageEntries = {
				piCodingAgent: loadedEntries.piCodingAgentCli,
				piAgentCore: loadedEntries.piAgentCoreEntry,
				piAi: loadedEntries.piAiEntry,
				piTui: loadedEntries.piTuiEntry,
			};
			const packageNames = {
				piCodingAgent: "@earendil-works/pi-coding-agent",
				piAgentCore: "@earendil-works/pi-agent-core",
				piAi: "@earendil-works/pi-ai",
				piTui: "@earendil-works/pi-tui",
			};
			const packages = {};
			for (const [label, entry] of Object.entries(packageEntries)) {
				if (entry?.realpath) packages[label] = packageIdentityFromEntry(entry.realpath, packageNames[label]);
			}
			const packageRootRaw = process.env.PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT ?? "";
			const nodePathRaw = process.env.NODE_PATH ?? "";
			return {
				schema: "xinao.pi_s_high_capacity_actual_child_identity.v1",
				token: config.token,
				probeInstance,
				identityFileName,
				recordedAtMs,
				pid: process.pid,
				ppid: process.ppid,
				caseName,
				labRunMarker,
				execPath: process.execPath,
				execPathRealpath: realpath(process.execPath),
				argv: [...process.argv],
				argv1Realpath: realpath(argv1),
				piSubagentChildRaw: process.env.PI_SUBAGENT_CHILD,
				piBinaryRaw: process.env.PI_SUBAGENT_PI_BINARY ?? null,
				piBinaryTrimmed: (process.env.PI_SUBAGENT_PI_BINARY ?? "").trim(),
				piCodingAgentPackageRootRaw: packageRootRaw,
				piCodingAgentPackageRootRealpath: packageRootRaw ? realpath(packageRootRaw) : null,
				nodePathRaw,
				nodePathEntryRealpaths: nodePathRaw.split(path.delimiter).filter(Boolean).map((entry) => realpath(entry)),
				configPathRealpath: realpath(configPath),
				configSha256: sha256(configRaw),
				loadedEntries,
				requiredLoadedLabels,
				unexpectedTargetLoads: [...unexpectedTargetLoads].sort(),
				packages,
				cliIdentity: fileIdentity(argv1),
			};
		}

		function writeIdentityRecordIfReady() {
			if (identityWritten || typeof caseName !== "string" || caseName === "CASE_UNKNOWN" || typeof labRunMarker !== "string") return;
			if (!requiredLoadedLabels.every((label) => observedExactLoads.has(label))) return;
			identityWritten = true;
			const identityFileName = `${config.token}.${process.pid}.json`;
			const payloadText = `${JSON.stringify(buildPayload(identityFileName, Date.now()), null, 2)}\n`;
			const identityPath = path.join(config.identityDirectory, identityFileName);
			const temporaryPath = `${identityPath}.${randomUUID()}.tmp`;
			fs.writeFileSync(temporaryPath, payloadText, { encoding: "utf8", flag: "wx" });
			fs.renameSync(temporaryPath, identityPath);
		}

		function observeLoadedUrl(url, format) {
			if (typeof url !== "string" || !url.startsWith("file:")) return;
			let loadedPath;
			try {
				loadedPath = realpath(fileURLToPath(url));
			} catch {
				return;
			}
			for (const [label, expectedPath] of exactEntries) {
				if (pathEqual(loadedPath, expectedPath)) {
					observedExactLoads.set(label, { url, realpath: loadedPath, format: String(format ?? "") });
				}
			}
			if (targetPackagePattern.test(loadedPath) && !expectedRoots.some((root) => pathEqual(loadedPath, root) || pathWithin(loadedPath, root))) {
				unexpectedTargetLoads.add(loadedPath);
			}
			writeIdentityRecordIfReady();
		}

		registerHooks({
			resolve(specifier, context, nextResolve) {
				return nextResolve(specifier, context);
			},
			load(url, context, nextLoad) {
				const result = nextLoad(url, context);
				observeLoadedUrl(url, result?.format ?? context?.format);
				return result;
			},
		});
	}
}
'@
[IO.File]::WriteAllText($childIdentityPreloadPath,$childIdentityPreloadSource,[Text.UTF8Encoding]::new($false))
$childIdentityPreloadReal = Assert-HighCapacityFilesystemRealPathWithin -Path $childIdentityPreloadPath -PathType Leaf -ParentRealPath $workReal -Label 'actual child identity preload'
$childIdentityToken = Get-HighCapacityFilesystemSha256Text (([guid]::NewGuid().ToString('N')) + "`n" + $workReal + "`n" + $piRootReal)
$childIdentityConfig = [ordered]@{
    schema = 'xinao.pi_s_high_capacity_actual_child_identity_config.v1'
    token = $childIdentityToken
    identityDirectory = $childIdentityDirectoryReal
    diagnosticDirectory = $childIdentityDiagnosticDirectoryReal
    expectedRoots = [ordered]@{
        piCodingAgent = [string]$piCodingAgentIdentity.root
        piAgentCore = [string]$piAgentCoreIdentity.root
        piAi = [string]$piAiIdentity.root
        piTui = [string]$piTuiIdentity.root
    }
    expectedEntries = [ordered]@{
        piCodingAgentCli = $cliReal
        piCodingAgentSdk = $sdkReal
        piCodingAgentExtensionRunner = $extensionRunnerReal
        piAgentCoreEntry = $piAgentCoreEntryReal
        piAiEntry = $piAiEntryReal
        piTuiEntry = $piTuiEntryReal
    }
}
$childIdentityConfigJson = ($childIdentityConfig | ConvertTo-Json -Depth 8) + "`n"
[IO.File]::WriteAllText($childIdentityConfigPath,$childIdentityConfigJson,[Text.UTF8Encoding]::new($false))
$childIdentityConfigReal = Assert-HighCapacityFilesystemRealPathWithin -Path $childIdentityConfigPath -PathType Leaf -ParentRealPath $workReal -Label 'actual child identity config'
$childIdentityPreloadState = Get-HighCapacityFilesystemFileState $childIdentityPreloadPath
$childIdentityConfigState = Get-HighCapacityFilesystemFileState $childIdentityConfigPath
$preloadUri = ([Uri]$childIdentityPreloadReal).AbsoluteUri
$rootProcessEnvironmentOverrides['NODE_OPTIONS'] = "--import=$preloadUri"
$rootProcessEnvironmentOverrides['XINAO_PI_HIGH_CAPACITY_CHILD_IDENTITY_CONFIG'] = $childIdentityConfigReal
$nodeCommand = (Get-Command node.exe -ErrorAction Stop).Source
$nodeCommandReal = Get-HighCapacityFilesystemGuardedRealPath -Path $nodeCommand -PathType Leaf -Label 'Node executable'
$preloadCheck = Invoke-HighCapacityFilesystemHiddenProcess -FilePath $nodeCommand -Arguments @('--check',$childIdentityPreloadReal) -WorkingDirectory $work -EnvironmentOverrides @{} -ProcessTimeoutMs 30000
if ($preloadCheck.exit_code -ne 0) {
    throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_PRELOAD_NODE_CHECK_FAILED: $($preloadCheck.stderr)`n$($preloadCheck.stdout)"
}

$agentSourceBefore = Get-HighCapacityFilesystemTreeFingerprint (Join-Path $packageRoot 'src')
$piSpawnSourceBefore = Get-HighCapacityFilesystemFileState $piSpawnSourcePath
$settingsBefore = Get-HighCapacityFilesystemFileState $settingsPath
$modelsBefore = Get-HighCapacityFilesystemFileState $modelsPath
$capacityConfigBefore = Get-HighCapacityFilesystemFileState $capacityConfigPath
$stopAgentsBefore = @($stopFixtureAgentPaths | ForEach-Object { Get-HighCapacityFilesystemFileState $_ })
$cliBefore = Get-HighCapacityFilesystemFileState $cliPath
$sdkBefore = Get-HighCapacityFilesystemFileState $sdkPath
$extensionRunnerBefore = Get-HighCapacityFilesystemFileState $extensionRunnerPath
$piAgentCoreEntryBefore = Get-HighCapacityFilesystemFileState $piAgentCoreEntryPath
$piAiEntryBefore = Get-HighCapacityFilesystemFileState $piAiEntryPath
$piTuiEntryBefore = Get-HighCapacityFilesystemFileState $piTuiEntryPath
$rpcBefore = Get-HighCapacityFilesystemFileState $rpcClientPath
$mutableAgentFileSpecs = @(
    [ordered]@{ name = 'auth_json'; path = $authPath; backup = (Join-Path $mutableAgentBackupRoot 'auth.json') },
    [ordered]@{ name = 'models_store_json'; path = $modelsStorePath; backup = (Join-Path $mutableAgentBackupRoot 'models-store.json') },
    [ordered]@{ name = 'run_history_jsonl'; path = $runHistoryPath; backup = (Join-Path $mutableAgentBackupRoot 'run-history.jsonl') }
)
$mutableAgentFileSnapshots = @()
$receipt = [ordered]@{
    schema = 'xinao.pi_s_high_capacity_filesystem_resume_acceptance.v1'
    status = 'running'
    generated_at = [DateTimeOffset]::Now.ToString('o')
    agent_dir = $agent
    pi_tool_root = $piRoot
    work_root = $work
    canonical_harness = [ordered]@{
        path = $canonicalHarness
        bytes = (Get-Item -LiteralPath $canonicalHarness).Length
        sha256 = $actualCanonicalHash
    }
    projected_harness = $null
    actual_child_identity = [ordered]@{
        schema = 'xinao.pi_s_high_capacity_actual_child_identity_evidence.v1'
        preload = [ordered]@{
            path = $childIdentityPreloadReal
            bytes = [long]$childIdentityPreloadState.bytes
            sha256 = [string]$childIdentityPreloadState.sha256
            node_options = [string]$rootProcessEnvironmentOverrides['NODE_OPTIONS']
            node_check = 'pass'
        }
        config = [ordered]@{
            path = $childIdentityConfigReal
            bytes = [long]$childIdentityConfigState.bytes
            sha256 = [string]$childIdentityConfigState.sha256
            token_sha256 = (Get-HighCapacityFilesystemSha256Text $childIdentityToken)
        }
        expected_node_exec_realpath = $nodeCommandReal
        expected_cli_realpath = $cliReal
        expected_loaded_entries = $childIdentityConfig.expectedEntries
        binding = 'pre-provider exact-load record + provider case/lab/timestamp + transcript'
        cases = $null
        identity_record_count = 0
        root_identity_record_count = $null
        verified = $false
    }
    capacity_config = $null
    core_isolation = [ordered]@{
        agent_realpath = $agentReal
        pi_tool_root_realpath = $piRootReal
        paired_pi_tool_root = $true
        all_key_paths_no_reparse = $true
        all_key_paths_realpath_contained = $true
        pi_subagents = $subagentsPackageIdentity
        pi_coding_agent = $piCodingAgentIdentity
        isolated_dependencies = @($piAgentCoreIdentity,$piAiIdentity,$piTuiIdentity)
    }
    process_environment = [ordered]@{
        scope = 'body-node-process-and-inherited-descendants-only'
        parent_process_modified = $false
        pi_subagent_pi_binary_override_raw = ' '
        pi_subagent_pi_binary_override_trimmed_empty = $true
        pi_coding_agent_package_root_override = [string]$piCodingAgentIdentity.root
        node_path_override = $isolatedNodePath
        node_path_entries = $nodePathEntries
        node_options_override = [string]$rootProcessEnvironmentOverrides['NODE_OPTIONS']
        child_identity_config_override = $childIdentityConfigReal
        parent_presence_before = [ordered]@{
            pi_subagent_pi_binary = ($null -ne $parentEnvironmentBefore['PI_SUBAGENT_PI_BINARY'])
            pi_coding_agent_package_root = ($null -ne $parentEnvironmentBefore['PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT'])
            node_path = ($null -ne $parentEnvironmentBefore['NODE_PATH'])
        }
        hostile_parent = $null
        observed_in_body_process = $null
        parent_process_unchanged_after = $null
        descendant_core_escape_blocked = $null
    }
    isolation = $null
    mutable_agent_files_baseline = $null
    body_lab = $null
    provider_resume = $null
    filesystem_resume = $null
    clean = $null
    error = $null
}

try {
    $hostilePiBinary = [string]$parentEnvironmentBefore['PI_SUBAGENT_PI_BINARY']
    $hostilePackageRoot = [string]$parentEnvironmentBefore['PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT']
    $hostileNodePathRaw = [string]$parentEnvironmentBefore['NODE_PATH']
    $hostileNodePathEntries = @($hostileNodePathRaw.Split([IO.Path]::PathSeparator,[StringSplitOptions]::RemoveEmptyEntries))
    if ([string]::IsNullOrWhiteSpace($hostilePiBinary) -or
        [string]::IsNullOrWhiteSpace($hostilePackageRoot) -or
        [string]::IsNullOrWhiteSpace($hostileNodePathRaw) -or
        $hostileNodePathEntries.Count -ne 1) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_HOSTILE_PARENT_ENVIRONMENT_REQUIRED'
    }
    $hostilePiBinaryReal = Get-HighCapacityFilesystemGuardedRealPath -Path $hostilePiBinary -PathType Leaf -Label 'hostile inherited Pi binary'
    $hostilePackageRootReal = Get-HighCapacityFilesystemGuardedRealPath -Path $hostilePackageRoot -PathType Container -Label 'hostile inherited Pi package root'
    $hostileNodePathReal = Get-HighCapacityFilesystemGuardedRealPath -Path $hostileNodePathEntries[0] -PathType Container -Label 'hostile inherited NODE_PATH'
    $hostileRealPaths = @($hostilePiBinaryReal,$hostilePackageRootReal,$hostileNodePathReal)
    if (@($hostileRealPaths | Select-Object -Unique).Count -ne 3) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_HOSTILE_PARENT_PATHS_NOT_DISTINCT'
    }
    foreach ($hostileRealPath in $hostileRealPaths) {
        if ((Test-HighCapacityFilesystemPathEqual $hostileRealPath $agentReal) -or
            (Test-HighCapacityFilesystemPathWithin $hostileRealPath $agentReal) -or
            (Test-HighCapacityFilesystemPathEqual $hostileRealPath $piRootReal) -or
            (Test-HighCapacityFilesystemPathWithin $hostileRealPath $piRootReal)) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_HOSTILE_PARENT_PATH_INSIDE_ISOLATED_ROOT: $hostileRealPath"
        }
    }
    $hostileInvocationMarker = Join-Path (Split-Path -Parent $hostilePiBinaryReal) 'hostile-pi-invoked.marker'
    if (Test-Path -LiteralPath $hostileInvocationMarker) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_HOSTILE_INVOCATION_MARKER_PREEXISTS: $hostileInvocationMarker"
    }
    $receipt.process_environment.hostile_parent = [ordered]@{
        pi_binary_realpath = $hostilePiBinaryReal
        pi_binary_value_sha256 = Get-HighCapacityFilesystemSha256Text $hostilePiBinary
        pi_coding_agent_package_root_realpath = $hostilePackageRootReal
        pi_coding_agent_package_root_value_sha256 = Get-HighCapacityFilesystemSha256Text $hostilePackageRoot
        node_path_realpath = $hostileNodePathReal
        node_path_value_sha256 = Get-HighCapacityFilesystemSha256Text $hostileNodePathRaw
        paths_existing = $true
        paths_no_reparse = $true
        paths_distinct = $true
        outside_isolated_roots = $true
        invocation_marker = $hostileInvocationMarker
        invocation_marker_absent_before = $true
        invocation_marker_absent_after = $null
    }
    foreach ($spec in $mutableAgentFileSpecs) {
        $state = Get-HighCapacityFilesystemFileState ([string]$spec.path)
        if ([bool]$state.present) {
            [IO.File]::WriteAllBytes([string]$spec.backup,[IO.File]::ReadAllBytes([string]$spec.path))
            $backupState = Get-HighCapacityFilesystemFileState ([string]$spec.backup)
            if (-not (Test-HighCapacityFilesystemFileStateEqual $state $backupState)) {
                throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_MUTABLE_FILE_BACKUP_FAILED: $($spec.path)"
            }
        }
        $mutableAgentFileSnapshots += [pscustomobject][ordered]@{
            name = [string]$spec.name
            path = [string]$spec.path
            backup = [string]$spec.backup
            state = $state
        }
    }
    $receipt.mutable_agent_files_baseline = @($mutableAgentFileSnapshots | ForEach-Object {
        [ordered]@{
            name = $_.name
            path = $_.path
            present = [bool]$_.state.present
            bytes = [long]$_.state.bytes
            sha256 = [string]$_.state.sha256
        }
    })
    if (-not $settingsBefore.present) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_SETTINGS_MISSING: $settingsPath"
    }
    $settings = Get-Content -Raw -LiteralPath $settingsPath -Encoding UTF8 | ConvertFrom-Json
    if (-not ($settings.subagents.modelScope.allow -is [Collections.IList])) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_SETTINGS_MODEL_SCOPE_ALLOW_MISSING'
    }
    if (-not (Get-HighCapacityFilesystemDirectoryEmpty $codexHome)) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CODEX_HOME_NOT_EMPTY_AT_START'
    }
    $receipt.isolation = [ordered]@{
        paired_pi_tool_root = $true
        pi_tool_root = $piRootReal
        fixture_package_source = $moduleRootReal
        fixture_codex_home = $codexHomeReal
        fixture_baseline_backup_root = $mutableAgentBackupRootReal
        fixture_codex_home_under_work_root = (Test-HighCapacityFilesystemPathWithin $codexHomeReal $workReal)
        fixture_codex_home_empty_at_start = $true
    }
    $capacityConfig = Get-Content -Raw -LiteralPath $capacityConfigPath -Encoding UTF8 | ConvertFrom-Json
    if (-not (Test-HighCapacityFilesystemExactBudget $capacityConfig.turnBudget)) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_GLOBAL_TURN_BUDGET_NOT_EXACT'
    }
    if (-not (Test-HighCapacityFilesystemPathEqual ([string]$capacityConfig.defaultSessionDir) $childSessionsRoot)) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_DEFAULT_SESSION_DIR_MISMATCH: expected=$childSessionsRoot actual=$($capacityConfig.defaultSessionDir)"
    }
    $receipt.capacity_config = [ordered]@{
        path = $capacityConfigPath
        bytes = $capacityConfigBefore.bytes
        sha256 = $capacityConfigBefore.sha256
        turn_budget = $capacityConfig.turnBudget
        launch_request_turn_budget_override = $false
        default_session_dir = [string]$capacityConfig.defaultSessionDir
        default_session_dir_matches = $true
    }
    New-Item -ItemType Directory -Force -Path $childSessionsRoot | Out-Null
    $childSessionsItem = Get-Item -LiteralPath $childSessionsRoot -Force
    if (($childSessionsItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_SESSION_ROOT_REPARSE_REJECTED: $childSessionsRoot"
    }

    Get-ChildItem -LiteralPath $packageRoot -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $moduleRoot -Recurse -Force
    }
    $moduleSourceBefore = Get-HighCapacityFilesystemTreeFingerprint (Join-Path $moduleRoot 'src')

    $moduleNodeModules = Join-Path $moduleRoot 'node_modules'
    $moduleScope = Join-Path $moduleNodeModules '@earendil-works'
    $agentNpmRoot = Split-Path -Parent $packageRoot
    New-Item -ItemType Directory -Force -Path $moduleScope | Out-Null
    foreach ($dependency in @('jiti','typebox','yaml')) {
        $source = Join-Path $agentNpmRoot $dependency
        if (-not (Test-Path -LiteralPath $source -PathType Container)) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_DEPENDENCY_MISSING: $source"
        }
        $sourceReal = Assert-HighCapacityFilesystemRealPathWithin -Path $source -PathType Container -ParentRealPath $agentNodeModulesReal -Label "isolated package dependency $dependency"
        New-Item -ItemType Junction -Path (Join-Path $moduleNodeModules $dependency) -Target $sourceReal | Out-Null
    }
    $peerDependencies = [ordered]@{
        'pi-coding-agent' = [string]$piCodingAgentIdentity.root
        'pi-agent-core' = [string]$piAgentCoreIdentity.root
        'pi-ai' = [string]$piAiIdentity.root
        'pi-tui' = [string]$piTuiIdentity.root
    }
    foreach ($peer in $peerDependencies.GetEnumerator()) {
        if (-not (Test-Path -LiteralPath $peer.Value -PathType Container)) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_PEER_DEPENDENCY_MISSING: $($peer.Value)"
        }
        New-Item -ItemType Junction -Path (Join-Path $moduleScope $peer.Key) -Target $peer.Value | Out-Null
    }

    $canonicalText = [IO.File]::ReadAllText($canonicalHarness,[Text.Encoding]::UTF8)
    $newline = if ($canonicalText.Contains("`r`n")) { "`r`n" } else { "`n" }
    $projectedText = $canonicalText
    $tab = [char]9

    $piSpawnSourceAnchor = $tab + '"src/runs/shared/pi-args.ts",'
    $piSpawnSourceProjection = @(
        ($tab + '"src/runs/shared/pi-args.ts",'),
        ($tab + '"src/runs/shared/pi-spawn.ts",')
    ) -join $newline
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $piSpawnSourceAnchor -Replacement $piSpawnSourceProjection -Label 'pi-spawn-source-binding'

    $artifactsAssertion = "`t" + 'assert.ok(typeof descriptor.artifactsDir === "string" && !path.resolve(descriptor.artifactsDir).toLowerCase().startsWith(`${path.resolve(fixture.root).toLowerCase()}${path.sep}`));'
    $restrictedSignatureAnchor = 'function assertRestrictedAsyncSurfaces({ status, descriptor, result }, fixture) {'
    $restrictedSignatureProjection = 'function assertRestrictedAsyncSurfaces({ status, descriptor, result }, fixture, expectInitialTurnBudget) {'
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $restrictedSignatureAnchor -Replacement $restrictedSignatureProjection -Label 'restricted-descriptor-expectation-signature'

    $descriptorAnchor = @(
        "`tassert.equal(descriptor.thinking, `"max`");",
        $artifactsAssertion
    ) -join $newline
    $descriptorProjection = @(
        "`tassert.equal(descriptor.thinking, `"max`");",
        "`tif (expectInitialTurnBudget) {",
        "`t`tassert.deepEqual(descriptor.initialTurnBudget, { maxTurns: 30, graceTurns: 0 }, `"raw source recovery descriptor initialTurnBudget drifted`");",
        "`t`tassert.deepEqual(Object.keys(descriptor.initialTurnBudget).sort(), [`"graceTurns`", `"maxTurns`"], `"raw source recovery descriptor initialTurnBudget keys drifted`");",
        "`t`tassert.equal(Object.prototype.hasOwnProperty.call(descriptor.initialTurnBudget, `"outcome`"), false, `"raw source recovery descriptor retained outcome`");",
        "`t`tassert.equal(Object.prototype.hasOwnProperty.call(descriptor.initialTurnBudget, `"turnCount`"), false, `"raw source recovery descriptor retained turnCount`");",
        "`t} else {",
        "`t`tassert.equal(descriptor.initialTurnBudget, undefined, `"ordinary resumed recovery descriptor unexpectedly retained an initial turn budget`");",
        "`t}",
        "`tassert.equal(descriptor.enforceHardTurnLimit, false, `"raw recovery descriptor hard-limit flag drifted`");",
        $artifactsAssertion
    ) -join $newline
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $descriptorAnchor -Replacement $descriptorProjection -Label 'raw-source-and-resume-descriptor-assertions'

    $returnAnchor = @(
        "`t`tartifactsDir: descriptor.artifactsDir,",
        "`t};"
    ) -join $newline
    $returnProjection = @(
        ($tab + $tab + 'runnerPid: status.pid,'),
        "`t`tartifactsDir: descriptor.artifactsDir,",
        "`t`tinitialTurnBudget: descriptor.initialTurnBudget,",
        "`t`tinitialTurnBudgetPresent: descriptor.initialTurnBudget !== undefined,",
        "`t`tenforceHardTurnLimit: descriptor.enforceHardTurnLimit,",
        "`t};"
    ) -join $newline
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $returnAnchor -Replacement $returnProjection -Label 'descriptor-evidence-return'

    $noPolicySignatureAnchor = 'function assertNoPolicyAsyncSurfaces({ status, descriptor, result }, fixture) {'
    $noPolicySignatureProjection = 'function assertNoPolicyAsyncSurfaces({ status, descriptor, result }, fixture, expectInitialTurnBudget) {'
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $noPolicySignatureAnchor -Replacement $noPolicySignatureProjection -Label 'no-policy-descriptor-expectation-signature'

    $noPolicyAnchor = @(
        "`tassert.equal(descriptor.thinking, `"max`");",
        "`tfor (const [label, value] of [",
        "`t`t[`"status root`", status],"
    ) -join $newline
    $noPolicyProjection = @(
        "`tassert.equal(descriptor.thinking, `"max`");",
        "`tif (expectInitialTurnBudget) {",
        "`t`tassert.deepEqual(descriptor.initialTurnBudget, { maxTurns: 30, graceTurns: 0 }, `"no-policy raw source recovery descriptor initialTurnBudget drifted`");",
        "`t`tassert.deepEqual(Object.keys(descriptor.initialTurnBudget).sort(), [`"graceTurns`", `"maxTurns`"], `"no-policy raw source recovery descriptor initialTurnBudget keys drifted`");",
        "`t`tassert.equal(Object.prototype.hasOwnProperty.call(descriptor.initialTurnBudget, `"outcome`"), false, `"no-policy raw source recovery descriptor retained outcome`");",
        "`t`tassert.equal(Object.prototype.hasOwnProperty.call(descriptor.initialTurnBudget, `"turnCount`"), false, `"no-policy raw source recovery descriptor retained turnCount`");",
        "`t} else {",
        "`t`tassert.equal(descriptor.initialTurnBudget, undefined, `"ordinary no-policy resumed recovery descriptor unexpectedly retained an initial turn budget`");",
        "`t}",
        "`tassert.equal(descriptor.enforceHardTurnLimit, false, `"no-policy raw recovery descriptor hard-limit flag drifted`");",
        "`tfor (const [label, value] of [",
        "`t`t[`"status root`", status],"
    ) -join $newline
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $noPolicyAnchor -Replacement $noPolicyProjection -Label 'no-policy-raw-source-and-resume-descriptor-assertions'

    $noPolicyReturnAnchor = "`treturn { model: descriptor.model, thinking: descriptor.thinking };"
    $noPolicyReturnProjection = $tab + 'return { model: descriptor.model, thinking: descriptor.thinking, initialTurnBudget: descriptor.initialTurnBudget, initialTurnBudgetPresent: descriptor.initialTurnBudget !== undefined, enforceHardTurnLimit: descriptor.enforceHardTurnLimit, runnerPid: status.pid };'
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $noPolicyReturnAnchor -Replacement $noPolicyReturnProjection -Label 'no-policy-descriptor-evidence-return'

    $restrictedSourceCallAnchor = 'durableEvidence = assertRestrictedAsyncSurfaces(surfaces, fixture);'
    $restrictedSourceCallProjection = 'durableEvidence = assertRestrictedAsyncSurfaces(surfaces, fixture, true);'
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $restrictedSourceCallAnchor -Replacement $restrictedSourceCallProjection -Label 'restricted-source-raw-expectation'
    $restrictedResumeCallAnchor = 'const resumedDurableEvidence = assertRestrictedAsyncSurfaces(detachedAndResume.resumeSurfaces, fixture);'
    $restrictedResumeCallProjection = 'const resumedDurableEvidence = assertRestrictedAsyncSurfaces(detachedAndResume.resumeSurfaces, fixture, false);'
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $restrictedResumeCallAnchor -Replacement $restrictedResumeCallProjection -Label 'restricted-resume-raw-expectation'
    $noPolicySourceCallAnchor = 'const noPolicyDurableEvidence = assertNoPolicyAsyncSurfaces(noPolicyDetachedAndResume.sourceSurfaces, fixture);'
    $noPolicySourceCallProjection = 'const noPolicyDurableEvidence = assertNoPolicyAsyncSurfaces(noPolicyDetachedAndResume.sourceSurfaces, fixture, true);'
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $noPolicySourceCallAnchor -Replacement $noPolicySourceCallProjection -Label 'no-policy-source-raw-expectation'
    $noPolicyResumeCallAnchor = 'const noPolicyResumeEvidence = assertNoPolicyAsyncSurfaces(noPolicyDetachedAndResume.resumeSurfaces, fixture);'
    $noPolicyResumeCallProjection = 'const noPolicyResumeEvidence = assertNoPolicyAsyncSurfaces(noPolicyDetachedAndResume.resumeSurfaces, fixture, false);'
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $noPolicyResumeCallAnchor -Replacement $noPolicyResumeCallProjection -Label 'no-policy-resume-raw-expectation'
    $noPolicyCompareAnchor = 'assert.deepEqual(noPolicyResumeEvidence, noPolicyDurableEvidence, "no-policy resume changed model identity/thinking evidence");'
    $noPolicyCompareProjection = @(
        'assert.equal(noPolicyResumeEvidence.model, noPolicyDurableEvidence.model, "no-policy resume changed model identity evidence");',
        "`t`tassert.equal(noPolicyResumeEvidence.thinking, noPolicyDurableEvidence.thinking, `"no-policy resume changed thinking evidence`");"
    ) -join $newline
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $noPolicyCompareAnchor -Replacement $noPolicyCompareProjection -Label 'no-policy-stable-evidence-comparison'

    $childRequestsAnchor = 'const childRequests = stub.requests.filter((request) => !request.isRoot);'
    $childRequestsProjection = @(
        'const childRequests = stub.requests.filter((request) => !request.isRoot);',
        ($tab + $tab + 'assert.ok(childRequests.length > 0, "actual child provider requests missing");'),
        ($tab + $tab + 'const childRuntimeIdentityRequests = [];'),
        ($tab + $tab + 'for (const request of childRequests.filter((candidate) => candidate.caseName !== "CASE_UNKNOWN")) {'),
        ($tab + $tab + $tab + 'const providerBodyText = JSON.stringify(request.body);'),
        ($tab + $tab + $tab + 'assert.equal(providerBodyText.includes(request.caseName), true, request.caseName + " provider body lost case marker");'),
        ($tab + $tab + $tab + 'assert.equal(providerBodyText.includes(fixture.labRunMarker), true, request.caseName + " provider body lost lab marker");'),
        ($tab + $tab + $tab + 'let binding = childRuntimeIdentityRequests.find((candidate) => candidate.caseName === request.caseName);'),
        ($tab + $tab + $tab + 'if (!binding) {'),
        ($tab + $tab + $tab + $tab + 'binding = { caseName: request.caseName, labRunMarker: fixture.labRunMarker, firstProviderAtMs: request.at, providerBodySha256: [] };'),
        ($tab + $tab + $tab + $tab + 'childRuntimeIdentityRequests.push(binding);'),
        ($tab + $tab + $tab + '}'),
        ($tab + $tab + $tab + 'binding.firstProviderAtMs = Math.min(binding.firstProviderAtMs, request.at);'),
        ($tab + $tab + $tab + 'binding.providerBodySha256.push(sha256(providerBodyText));'),
        ($tab + $tab + '}')
    ) -join $newline
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $childRequestsAnchor -Replacement $childRequestsProjection -Label 'provider-child-case-time-binding'

    $receiptAnchor = @(
        "`t`t`tresume_retained_policy: true,",
        "`t`t`tresume_max_subagent_depth: durableEvidence.maxSubagentDepth,"
    ) -join $newline
    $receiptProjection = @(
        ($tab + $tab + $tab + 'lab_run_marker: fixture.labRunMarker,'),
        ($tab + $tab + $tab + 'child_runtime_identity_requests: childRuntimeIdentityRequests,'),
        "`t`t`tresume_retained_policy: true,",
        "`t`t`tresume_reached_provider: childRequests.some((request) => request.caseName === `"CASE_RESUME_SAFE`"),",
        "`t`t`tsource_initial_turn_budget: durableEvidence.initialTurnBudget,",
        "`t`t`tresume_initial_turn_budget_present: resumedDurableEvidence.initialTurnBudgetPresent,",
        "`t`t`tsource_enforce_hard_turn_limit: durableEvidence.enforceHardTurnLimit,",
        "`t`t`tresume_enforce_hard_turn_limit: resumedDurableEvidence.enforceHardTurnLimit,",
        "`t`t`tfilesystem_policy_digest: durableEvidence.filesystemPolicyDigest,",
        "`t`t`tresume_filesystem_policy_digest: resumedDurableEvidence.filesystemPolicyDigest,",
        "`t`t`tno_policy_resume_reached_provider: childRequests.some((request) => request.caseName === `"CASE_NO_POLICY_RESUME_SAFE`"),",
        "`t`t`tno_policy_source_initial_turn_budget: noPolicyDurableEvidence.initialTurnBudget,",
        "`t`t`tno_policy_resume_initial_turn_budget_present: noPolicyResumeEvidence.initialTurnBudgetPresent,",
        "`t`t`tno_policy_source_enforce_hard_turn_limit: noPolicyDurableEvidence.enforceHardTurnLimit,",
        "`t`t`tno_policy_resume_enforce_hard_turn_limit: noPolicyResumeEvidence.enforceHardTurnLimit,",
        "`t`t`troot_process_pi_binary_raw: process.env.PI_SUBAGENT_PI_BINARY,",
        "`t`t`troot_process_pi_binary_trimmed_empty: (process.env.PI_SUBAGENT_PI_BINARY ?? String()).trim().length === 0,",
        "`t`t`troot_process_pi_coding_agent_package_root: process.env.PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT,",
        "`t`t`troot_process_node_path: process.env.NODE_PATH,",
        ($tab + $tab + $tab + 'root_process_node_options: process.env.NODE_OPTIONS,'),
        ($tab + $tab + $tab + 'root_process_child_identity_config: process.env.XINAO_PI_HIGH_CAPACITY_CHILD_IDENTITY_CONFIG,'),
        ($tab + $tab + $tab + 'source_runner_pid: durableEvidence.runnerPid,'),
        ($tab + $tab + $tab + 'resume_runner_pid: resumedDurableEvidence.runnerPid,'),
        ($tab + $tab + $tab + 'no_policy_source_runner_pid: noPolicyDurableEvidence.runnerPid,'),
        ($tab + $tab + $tab + 'no_policy_resume_runner_pid: noPolicyResumeEvidence.runnerPid,'),
        "`t`t`tresume_max_subagent_depth: durableEvidence.maxSubagentDepth,"
    ) -join $newline
    $projectedText = Replace-HighCapacityFilesystemTextExactlyOnce -Text $projectedText -Anchor $receiptAnchor -Replacement $receiptProjection -Label 'receipt-cross-product-evidence'

    [IO.File]::WriteAllText($projectedHarness,$projectedText,[Text.UTF8Encoding]::new($false))
    $projectedState = Get-HighCapacityFilesystemFileState $projectedHarness
    $receipt.projected_harness = [ordered]@{
        path = $projectedHarness
        bytes = $projectedState.bytes
        sha256 = $projectedState.sha256
        source_sha256 = $actualCanonicalHash
        transformation = 'exact-anchor-v2: assertion, receipt, and test-only actual-child pre-provider load identity instrumentation; launch parameters remain canonical and global turnBudget comes from guarded config'
        assertion_and_receipt_only = $false
        test_instrumentation_only = $true
        provider_headers_instrumented = $false
        launch_parameter_semantics_changed = $false
        launch_turn_budget_override = $false
        product_source_changed = $false
        node_check = $null
    }

    $projectedCheck = Invoke-HighCapacityFilesystemHiddenProcess -FilePath $nodeCommand -Arguments @('--check',$projectedHarness) -WorkingDirectory $work -EnvironmentOverrides $rootProcessEnvironmentOverrides -ProcessTimeoutMs 30000
    if ($projectedCheck.exit_code -ne 0) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_PROJECTED_NODE_CHECK_FAILED: $($projectedCheck.stderr)`n$($projectedCheck.stdout)"
    }
    $receipt.projected_harness.node_check = 'pass'

    $processResult = Invoke-HighCapacityFilesystemHiddenProcess -FilePath $nodeCommand -Arguments @(
        $projectedHarness,
        '--cli',$cliPath,
        '--rpc-client',$rpcClientPath,
        '--agent-dir',$agent,
        '--module-root',$moduleRoot,
        '--codex-home',$codexHome,
        '--stop-harness',$stopHarness,
        '--stop-extension',$stopExtension,
        '--stop-fixture',$stopFixture,
        '--fixture-root',$fixtureRoot,
        '--session-dir',$sessionDir,
        '--receipt',$bodyReceiptPath,
        '--timeout-ms',([string]$TimeoutMs)
    ) -WorkingDirectory $work -EnvironmentOverrides $rootProcessEnvironmentOverrides -ProcessTimeoutMs ($TimeoutMs + 180000)
    if ($processResult.exit_code -ne 0) {
        $failureOutput = (($processResult.stderr + "`n" + $processResult.stdout).Trim())
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_BODY_LAB_FAILED: exit=$($processResult.exit_code) output=$failureOutput"
    }
    if (-not (Test-Path -LiteralPath $bodyReceiptPath -PathType Leaf)) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_BODY_RECEIPT_MISSING'
    }
    $bodyReceipt = Get-Content -Raw -LiteralPath $bodyReceiptPath -Encoding UTF8 | ConvertFrom-Json
    if ([string]$bodyReceipt.schema -cne 'xinao.pi_subagents_filesystem_policy_body_lab.v1' -or [string]$bodyReceipt.status -cne 'verified') {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_BODY_RECEIPT_INVALID'
    }
    if (
        [string]$bodyReceipt.root_process_pi_binary_raw -cne ' ' -or
        [bool]$bodyReceipt.root_process_pi_binary_trimmed_empty -ne $true -or
        -not (Test-HighCapacityFilesystemPathEqual ([string]$bodyReceipt.root_process_pi_coding_agent_package_root) ([string]$piCodingAgentIdentity.root)) -or
        [string]$bodyReceipt.root_process_node_path -cne $isolatedNodePath -or
        [string]$bodyReceipt.root_process_node_options -cne [string]$rootProcessEnvironmentOverrides['NODE_OPTIONS'] -or
        -not (Test-HighCapacityFilesystemPathEqual ([string]$bodyReceipt.root_process_child_identity_config) $childIdentityConfigReal)
    ) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_BODY_PROCESS_ENVIRONMENT_ESCAPE'
    }
    $receipt.process_environment.observed_in_body_process = [ordered]@{
        pi_subagent_pi_binary_raw = [string]$bodyReceipt.root_process_pi_binary_raw
        pi_subagent_pi_binary_trimmed_empty = [bool]$bodyReceipt.root_process_pi_binary_trimmed_empty
        pi_coding_agent_package_root = [string]$bodyReceipt.root_process_pi_coding_agent_package_root
        node_path = [string]$bodyReceipt.root_process_node_path
        node_options = [string]$bodyReceipt.root_process_node_options
        child_identity_config = [string]$bodyReceipt.root_process_child_identity_config
        exact_overrides_observed = $true
    }
    $bodyPiSpawnSourceHashProperty = $bodyReceipt.filesystem_policy_source_sha256.PSObject.Properties['src/runs/shared/pi-spawn.ts']
    if ($null -eq $bodyPiSpawnSourceHashProperty -or
        [string]$bodyPiSpawnSourceHashProperty.Value -cne [string]$piSpawnSourceBefore.sha256) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_PI_SPAWN_SOURCE_BINDING_INVALID'
    }
    $receipt.actual_child_identity['pi_spawn_source'] = [ordered]@{
        path = $piSpawnSourcePath
        bytes = [long]$piSpawnSourceBefore.bytes
        sha256 = [string]$piSpawnSourceBefore.sha256
    }
    $identityRequests = @($bodyReceipt.child_runtime_identity_requests)
    if ($identityRequests.Count -le 0) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_PROVIDER_REQUEST_COUNT_INVALID'
    }
    $identityRequestCaseNames = @($identityRequests | ForEach-Object { [string]$_.caseName } | Select-Object -Unique)
    if ($identityRequestCaseNames.Count -ne $identityRequests.Count) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_PROVIDER_CASE_NOT_UNIQUE'
    }
    $identityFiles = @(Get-ChildItem -LiteralPath $childIdentityDirectory -Force -File)
    if ($identityFiles.Count -ne $identityRequestCaseNames.Count) {
        throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_RECORD_COUNT_INVALID: cases=$($identityRequestCaseNames.Count) files=$($identityFiles.Count)"
    }
    $identityCases = @{}
    $identityRecordNames = @{}
    $identityFileEntries = @{}
    foreach ($identityFile in $identityFiles) {
        $identityFileText = [IO.File]::ReadAllText($identityFile.FullName,[Text.Encoding]::UTF8)
        try {
            $identity = $identityFileText | ConvertFrom-Json
        } catch {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_JSON_INVALID: $($_.Exception.Message)"
        }
        $identityCaseName = [string]$identity.caseName
        if ([string]::IsNullOrWhiteSpace($identityCaseName) -or $identityFileEntries.ContainsKey($identityCaseName)) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_CASE_NOT_UNIQUE: $identityCaseName"
        }
        $identityFileEntries[$identityCaseName] = [pscustomobject]@{
            identity = $identity
            path = $identityFile.FullName
            text = $identityFileText
        }
    }
    $expectedLoadedEntries = [ordered]@{
        piCodingAgentCli = $cliReal
        piAgentCoreEntry = $piAgentCoreEntryReal
        piAiEntry = $piAiEntryReal
        piTuiEntry = $piTuiEntryReal
    }
    $expectedPackages = [ordered]@{
        piCodingAgent = $piCodingAgentIdentity
        piAgentCore = $piAgentCoreIdentity
        piAi = $piAiIdentity
        piTui = $piTuiIdentity
    }
    $identityCaseEvidence = [ordered]@{}
    foreach ($request in $identityRequests) {
        $caseName = [string]$request.caseName
        if ([string]$request.labRunMarker -cne [string]$bodyReceipt.lab_run_marker -or
            [long]$request.firstProviderAtMs -le 0 -or
            @($request.providerBodySha256).Count -le 0 -or
            @($request.providerBodySha256 | Where-Object { [string]$_ -notmatch '^[a-f0-9]{64}$' }).Count -ne 0 -or
            -not $identityFileEntries.ContainsKey($caseName)) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_REQUEST_BINDING_INVALID: $($request.caseName)"
        }
        $identityEntry = $identityFileEntries[$caseName]
        $identity = $identityEntry.identity
        if ([string]$identity.schema -cne 'xinao.pi_s_high_capacity_actual_child_identity.v1' -or
            [string]$identity.token -cne $childIdentityToken -or
            [string]$identity.caseName -cne $caseName -or
            [string]$identity.labRunMarker -cne [string]$bodyReceipt.lab_run_marker -or
            [string]$identity.probeInstance -notmatch '^[0-9a-f-]{36}$' -or
            [int]$identity.pid -le 0 -or
            [int]$identity.ppid -le 0 -or
            [long]$identity.recordedAtMs -le 0 -or
            [long]$identity.recordedAtMs -gt [long]$request.firstProviderAtMs -or
            [string]$identity.piSubagentChildRaw -cne '1') {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_PAYLOAD_INVALID: $caseName"
        }
        $identityFileName = [string]$identity.identityFileName
        if ([IO.Path]::GetFileName($identityFileName) -cne $identityFileName -or
            $identityFileName -notmatch ('^' + [regex]::Escape($childIdentityToken) + '\.[0-9]+\.json$') -or
            $identityRecordNames.ContainsKey($identityFileName.ToLowerInvariant())) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_RECORD_NAME_INVALID: $identityFileName"
        }
        $identityRecordNames[$identityFileName.ToLowerInvariant()] = $true
        $identityFilePath = Join-Path $childIdentityDirectory $identityFileName
        $identityFileReal = Assert-HighCapacityFilesystemRealPathWithin -Path $identityFilePath -PathType Leaf -ParentRealPath $childIdentityDirectoryReal -Label "actual child identity record $identityFileName"
        $identityFileText = [IO.File]::ReadAllText($identityFilePath,[Text.Encoding]::UTF8)
        if (-not (Test-HighCapacityFilesystemPathEqual $identityFilePath ([string]$identityEntry.path)) -or $identityFileText -cne [string]$identityEntry.text) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_RECORD_LOOKUP_MISMATCH: $identityFileName"
        }
        if (-not (Test-HighCapacityFilesystemPathEqual ([string]$identity.execPathRealpath) $nodeCommandReal) -or
            -not (Test-HighCapacityFilesystemPathEqual ([string]$identity.argv1Realpath) $cliReal) -or
            @($identity.argv).Count -lt 2 -or
            -not (Test-HighCapacityFilesystemPathEqual ([string]$identity.argv[1]) $cliReal) -or
            [string]$identity.piBinaryRaw -cne ' ' -or
            [string]$identity.piBinaryTrimmed -cne '' -or
            -not (Test-HighCapacityFilesystemPathEqual ([string]$identity.piCodingAgentPackageRootRaw) ([string]$piCodingAgentIdentity.root)) -or
            -not (Test-HighCapacityFilesystemPathEqual ([string]$identity.piCodingAgentPackageRootRealpath) ([string]$piCodingAgentIdentity.root)) -or
            [string]$identity.nodePathRaw -cne $isolatedNodePath -or
            @($identity.nodePathEntryRealpaths).Count -ne $nodePathEntries.Count -or
            -not (Test-HighCapacityFilesystemPathEqual ([string]$identity.configPathRealpath) $childIdentityConfigReal) -or
            [string]$identity.configSha256 -cne [string]$childIdentityConfigState.sha256 -or
            [string]$identity.cliIdentity.sha256 -cne [string]$cliIdentityState.sha256 -or
            [long]$identity.cliIdentity.bytes -ne [long]$cliIdentityState.bytes -or
            -not (Test-HighCapacityFilesystemPathEqual ([string]$identity.cliIdentity.realpath) $cliReal)) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_PROCESS_IDENTITY_INVALID: $caseName"
        }
        for ($nodePathIndex = 0; $nodePathIndex -lt $nodePathEntries.Count; $nodePathIndex++) {
            if (-not (Test-HighCapacityFilesystemPathEqual ([string]$identity.nodePathEntryRealpaths[$nodePathIndex]) ([string]$nodePathEntries[$nodePathIndex]))) {
                throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_NODE_PATH_ENTRY_INVALID: case=$caseName index=$nodePathIndex"
            }
        }
        if (@($identity.unexpectedTargetLoads).Count -ne 0) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_UNEXPECTED_PACKAGE_LOAD: case=$caseName loads=$($identity.unexpectedTargetLoads -join ',')"
        }
        $loadedEntryEvidence = [ordered]@{}
        foreach ($entrySpec in $expectedLoadedEntries.GetEnumerator()) {
            $loadedProperty = $identity.loadedEntries.PSObject.Properties[[string]$entrySpec.Key]
            $loaded = if ($null -eq $loadedProperty) { $null } else { $loadedProperty.Value }
            if ($null -eq $loaded -or
                [string]$loaded.format -cne 'module' -or
                -not (Test-HighCapacityFilesystemPathEqual ([string]$loaded.realpath) ([string]$entrySpec.Value))) {
                throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_REQUIRED_LOAD_MISSING: case=$caseName entry=$($entrySpec.Key)"
            }
            $loadedState = Get-HighCapacityFilesystemFileState ([string]$loaded.realpath)
            $loadedEntryEvidence[[string]$entrySpec.Key] = [ordered]@{
                realpath = [string]$loaded.realpath
                format = [string]$loaded.format
                bytes = [long]$loadedState.bytes
                sha256 = [string]$loadedState.sha256
            }
        }
        foreach ($packageSpec in $expectedPackages.GetEnumerator()) {
            $packageProperty = $identity.packages.PSObject.Properties[[string]$packageSpec.Key]
            $actualPackage = if ($null -eq $packageProperty) { $null } else { $packageProperty.Value }
            $expectedPackage = $packageSpec.Value
            if ($null -eq $actualPackage -or
                [string]$actualPackage.name -cne [string]$expectedPackage.name -or
                [string]$actualPackage.version -cne [string]$expectedPackage.version -or
                -not (Test-HighCapacityFilesystemPathEqual ([string]$actualPackage.rootRealpath) ([string]$expectedPackage.root)) -or
                -not (Test-HighCapacityFilesystemPathEqual ([string]$actualPackage.packageJsonRealpath) ([string]$expectedPackage.package_json)) -or
                [string]$actualPackage.packageJsonSha256 -cne [string]$expectedPackage.package_json_sha256) {
                throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_PACKAGE_IDENTITY_INVALID: case=$caseName package=$($packageSpec.Key)"
            }
        }
        $record = [pscustomobject][ordered]@{
            case_name = $caseName
            pid = [int]$identity.pid
            ppid = [int]$identity.ppid
            probe_instance = [string]$identity.probeInstance
            recorded_at_ms = [long]$identity.recordedAtMs
            provider_at_ms = [long]$request.firstProviderAtMs
            provider_body_sha256 = @($request.providerBodySha256)
            identity_file = $identityFileReal
            identity_file_bytes = (Get-Item -LiteralPath $identityFilePath -Force).Length
            identity_file_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $identityFilePath).Hash.ToLowerInvariant()
            loaded_entries = $loadedEntryEvidence
        }
        if (-not $identityCases.ContainsKey($caseName)) { $identityCases[$caseName] = @() }
        $identityCases[$caseName] = @($identityCases[$caseName]) + @($record)
    }
    foreach ($criticalCase in @('CASE_FOREGROUND_SAFE','CASE_DETACHED_SAFE','CASE_RESUME_SAFE','CASE_NO_POLICY_DETACHED_SAFE','CASE_NO_POLICY_RESUME_SAFE')) {
        if (-not $identityCases.ContainsKey($criticalCase) -or @($identityCases[$criticalCase]).Count -ne 1) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_CRITICAL_CASE_MISSING: $criticalCase"
        }
        $records = @($identityCases[$criticalCase])
        $pids = @($records | ForEach-Object { $_.pid } | Select-Object -Unique)
        $probes = @($records | ForEach-Object { $_.probe_instance } | Select-Object -Unique)
        if ($pids.Count -ne 1 -or $probes.Count -ne 1) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_CASE_INCONSISTENT: $criticalCase"
        }
        $transcript = $bodyReceipt.child_tool_result_evidence.PSObject.Properties[$criticalCase].Value
        if ($null -eq $transcript -or [string]$transcript.transcriptSha256 -notmatch '^[a-f0-9]{64}$') {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_IDENTITY_TRANSCRIPT_BINDING_MISSING: $criticalCase"
        }
        $identityCaseEvidence[$criticalCase] = [ordered]@{
            pid = [int]$records[0].pid
            ppid = [int]$records[0].ppid
            probe_instance = [string]$records[0].probe_instance
            provider_request_count = @($records[0].provider_body_sha256).Count
            provider_body_sha256 = @($records[0].provider_body_sha256)
            recorded_at_ms = [long]$records[0].recorded_at_ms
            provider_at_ms = [long]$records[0].provider_at_ms
            identity_file_sha256 = @($records | ForEach-Object { $_.identity_file_sha256 })
            transcript_sha256 = [string]$transcript.transcriptSha256
            loaded_entries = $records[0].loaded_entries
        }
    }
    $runnerBindings = [ordered]@{
        CASE_DETACHED_SAFE = [int]$bodyReceipt.source_runner_pid
        CASE_RESUME_SAFE = [int]$bodyReceipt.resume_runner_pid
        CASE_NO_POLICY_DETACHED_SAFE = [int]$bodyReceipt.no_policy_source_runner_pid
        CASE_NO_POLICY_RESUME_SAFE = [int]$bodyReceipt.no_policy_resume_runner_pid
    }
    foreach ($runnerBinding in $runnerBindings.GetEnumerator()) {
        $caseEvidence = $identityCaseEvidence[[string]$runnerBinding.Key]
        if ([int]$runnerBinding.Value -le 0 -or
            [int]$caseEvidence.ppid -ne [int]$runnerBinding.Value -or
            [int]$caseEvidence.pid -eq [int]$runnerBinding.Value) {
            throw "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CHILD_RUNNER_PID_BINDING_INVALID: case=$($runnerBinding.Key) runner=$($runnerBinding.Value) child=$($caseEvidence.pid) ppid=$($caseEvidence.ppid)"
        }
        $caseEvidence['runner_pid'] = [int]$runnerBinding.Value
        $caseEvidence['child_pid_differs_from_runner'] = $true
    }
    if ([string]$identityCaseEvidence.CASE_DETACHED_SAFE.probe_instance -ceq [string]$identityCaseEvidence.CASE_RESUME_SAFE.probe_instance -or
        [string]$identityCaseEvidence.CASE_NO_POLICY_DETACHED_SAFE.probe_instance -ceq [string]$identityCaseEvidence.CASE_NO_POLICY_RESUME_SAFE.probe_instance) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_SOURCE_RESUME_PROCESS_IDENTITY_REUSED'
    }
    $receipt.actual_child_identity.cases = $identityCaseEvidence
    $receipt.actual_child_identity.identity_record_count = $identityFiles.Count
    $receipt.actual_child_identity.root_identity_record_count = 0
    $receipt.actual_child_identity.verified = $true
    $receipt.process_environment.descendant_core_escape_blocked = $true

    if (-not (Test-HighCapacityFilesystemExactBudget $bodyReceipt.source_initial_turn_budget)) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_SOURCE_BUDGET_NOT_EXACT'
    }
    if (-not (Test-HighCapacityFilesystemExactBudget $bodyReceipt.no_policy_source_initial_turn_budget)) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_NO_POLICY_SOURCE_BUDGET_NOT_EXACT'
    }
    if ([bool]$bodyReceipt.resume_initial_turn_budget_present -or [bool]$bodyReceipt.no_policy_resume_initial_turn_budget_present) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_ORDINARY_REVIVED_BUDGET_UNEXPECTED'
    }
    if (
        [bool]$bodyReceipt.source_enforce_hard_turn_limit -or
        [bool]$bodyReceipt.resume_enforce_hard_turn_limit -or
        [bool]$bodyReceipt.no_policy_source_enforce_hard_turn_limit -or
        [bool]$bodyReceipt.no_policy_resume_enforce_hard_turn_limit
    ) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_HARD_LIMIT_FLAG_CHANGED'
    }
    if (
        $bodyReceipt.detached_async_complete -ne $true -or
        $bodyReceipt.resume_retained_policy -ne $true -or
        $bodyReceipt.resume_reached_provider -ne $true -or
        $bodyReceipt.no_policy_resume_reached_provider -ne $true -or
        [int]$bodyReceipt.resume_max_subagent_depth -ne 0 -or
        [string]$bodyReceipt.filesystem_policy_digest -notmatch '^[a-f0-9]{64}$' -or
        [string]$bodyReceipt.resume_filesystem_policy_digest -cne [string]$bodyReceipt.filesystem_policy_digest -or
        $bodyReceipt.allowed_source_tree_unchanged -ne $true -or
        $bodyReceipt.project_artifacts_written -ne $false -or
        $bodyReceipt.owner_stop_process_terminated -ne $true
    ) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CROSS_PRODUCT_EVIDENCE_INVALID'
    }

    $moduleSourceAfter = Get-HighCapacityFilesystemTreeFingerprint (Join-Path $moduleRoot 'src')
    $agentSourceAfter = Get-HighCapacityFilesystemTreeFingerprint (Join-Path $packageRoot 'src')
    $settingsAfter = Get-HighCapacityFilesystemFileState $settingsPath
    $modelsAfter = Get-HighCapacityFilesystemFileState $modelsPath
    $capacityConfigAfter = Get-HighCapacityFilesystemFileState $capacityConfigPath
    $stopAgentsAfter = @($stopFixtureAgentPaths | ForEach-Object { Get-HighCapacityFilesystemFileState $_ })
    $cliAfter = Get-HighCapacityFilesystemFileState $cliPath
    $sdkAfter = Get-HighCapacityFilesystemFileState $sdkPath
    $extensionRunnerAfter = Get-HighCapacityFilesystemFileState $extensionRunnerPath
    $piAgentCoreEntryAfter = Get-HighCapacityFilesystemFileState $piAgentCoreEntryPath
    $piAiEntryAfter = Get-HighCapacityFilesystemFileState $piAiEntryPath
    $piTuiEntryAfter = Get-HighCapacityFilesystemFileState $piTuiEntryPath
    $rpcAfter = Get-HighCapacityFilesystemFileState $rpcClientPath
    $stopAgentsRestored = $true
    for ($index = 0; $index -lt $stopAgentsBefore.Count; $index++) {
        if (-not (Test-HighCapacityFilesystemFileStateEqual $stopAgentsBefore[$index] $stopAgentsAfter[$index])) {
            $stopAgentsRestored = $false
        }
    }
    $clean = [ordered]@{
        caller_work_root_retained = (Test-Path -LiteralPath $work -PathType Container)
        caller_agent_source_unchanged = ($agentSourceAfter -ceq $agentSourceBefore)
        package_source_projection_unchanged = ($moduleSourceAfter -ceq $moduleSourceBefore)
        settings_restored = (Test-HighCapacityFilesystemFileStateEqual $settingsBefore $settingsAfter)
        models_restored = (Test-HighCapacityFilesystemFileStateEqual $modelsBefore $modelsAfter)
        capacity_config_unchanged = (Test-HighCapacityFilesystemFileStateEqual $capacityConfigBefore $capacityConfigAfter)
        stop_agent_projections_restored = $stopAgentsRestored
        cli_unchanged = (Test-HighCapacityFilesystemFileStateEqual $cliBefore $cliAfter)
        sdk_unchanged = (Test-HighCapacityFilesystemFileStateEqual $sdkBefore $sdkAfter)
        extension_runner_unchanged = (Test-HighCapacityFilesystemFileStateEqual $extensionRunnerBefore $extensionRunnerAfter)
        pi_agent_core_entry_unchanged = (Test-HighCapacityFilesystemFileStateEqual $piAgentCoreEntryBefore $piAgentCoreEntryAfter)
        pi_ai_entry_unchanged = (Test-HighCapacityFilesystemFileStateEqual $piAiEntryBefore $piAiEntryAfter)
        pi_tui_entry_unchanged = (Test-HighCapacityFilesystemFileStateEqual $piTuiEntryBefore $piTuiEntryAfter)
        rpc_client_unchanged = (Test-HighCapacityFilesystemFileStateEqual $rpcBefore $rpcAfter)
        actual_child_identity_verified = [bool]$receipt.actual_child_identity.verified
        actual_child_identity_records_bound = ($identityFiles.Count -eq $identityRequests.Count -and $identityRecordNames.Count -eq $identityRequests.Count)
        codex_home_empty_after = (Get-HighCapacityFilesystemDirectoryEmpty $codexHome)
        restricted_allowed_tree_unchanged = [bool]$bodyReceipt.allowed_source_tree_unchanged
        project_artifacts_written = [bool]$bodyReceipt.project_artifacts_written
        owner_stop_process_terminated = [bool]$bodyReceipt.owner_stop_process_terminated
    }
    if (@($clean.GetEnumerator() | Where-Object {
        if ($_.Key -ceq 'project_artifacts_written') { [bool]$_.Value }
        else { -not [bool]$_.Value }
    }).Count -ne 0) {
        throw 'PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CLEAN_EVIDENCE_FAILED'
    }

    $receipt.body_lab = $bodyReceipt
    $receipt.provider_resume = [ordered]@{
        provider = [string]$bodyReceipt.provider
        detached_complete = [bool]$bodyReceipt.detached_async_complete
        resume_reached_provider = [bool]$bodyReceipt.resume_reached_provider
        no_policy_resume_reached_provider = [bool]$bodyReceipt.no_policy_resume_reached_provider
        child_request_count = [int]$bodyReceipt.child_request_count
        async_id = [string]$bodyReceipt.async_id
    }
    $receipt.filesystem_resume = [ordered]@{
        source_initial_turn_budget = $bodyReceipt.source_initial_turn_budget
        resume_initial_turn_budget_present = [bool]$bodyReceipt.resume_initial_turn_budget_present
        source_enforce_hard_turn_limit = [bool]$bodyReceipt.source_enforce_hard_turn_limit
        resume_enforce_hard_turn_limit = [bool]$bodyReceipt.resume_enforce_hard_turn_limit
        no_policy_source_initial_turn_budget = $bodyReceipt.no_policy_source_initial_turn_budget
        no_policy_resume_initial_turn_budget_present = [bool]$bodyReceipt.no_policy_resume_initial_turn_budget_present
        no_policy_source_enforce_hard_turn_limit = [bool]$bodyReceipt.no_policy_source_enforce_hard_turn_limit
        no_policy_resume_enforce_hard_turn_limit = [bool]$bodyReceipt.no_policy_resume_enforce_hard_turn_limit
        source_filesystem_policy_digest = [string]$bodyReceipt.filesystem_policy_digest
        resume_filesystem_policy_digest = [string]$bodyReceipt.resume_filesystem_policy_digest
        resume_max_subagent_depth = [int]$bodyReceipt.resume_max_subagent_depth
        resume_retained_policy = [bool]$bodyReceipt.resume_retained_policy
    }
    $receipt.clean = $clean
    $receipt.status = 'verified'
} catch {
    $receipt.status = 'blocked'
    $receipt.error = [string]$_.Exception.Message
} finally {
    $cleanupFailures = New-Object Collections.Generic.List[string]
    $parentEnvironmentUnchanged = $true
    foreach ($key in $processEnvironmentKeys) {
        $currentParentValue = [Environment]::GetEnvironmentVariable($key,[EnvironmentVariableTarget]::Process)
        if (-not [object]::Equals($parentEnvironmentBefore[$key],$currentParentValue)) {
            $parentEnvironmentUnchanged = $false
        }
    }
    if ($null -ne $receipt.process_environment.hostile_parent) {
        $receipt.process_environment.hostile_parent.invocation_marker_absent_after = -not (Test-Path -LiteralPath ([string]$receipt.process_environment.hostile_parent.invocation_marker))
        if (-not [bool]$receipt.process_environment.hostile_parent.invocation_marker_absent_after) {
            [void]$cleanupFailures.Add('hostile-pi-invocation-marker-present')
        }
    }
    $receipt.process_environment.parent_process_unchanged_after = $parentEnvironmentUnchanged
    if ($null -eq $receipt.clean) { $receipt.clean = [ordered]@{} }
    $receipt.clean['parent_process_environment_unchanged'] = $parentEnvironmentUnchanged
    if (-not $parentEnvironmentUnchanged) {
        [void]$cleanupFailures.Add('parent-process-environment-drifted')
    }
    $mutableAgentFileCleanup = [ordered]@{}
    foreach ($snapshot in $mutableAgentFileSnapshots) {
        try {
            $mutableAgentFileCleanup[$snapshot.name] = Restore-HighCapacityFilesystemExactFile `
                -Path $snapshot.path `
                -StateBefore $snapshot.state `
                -BackupPath $snapshot.backup
        } catch {
            $fileCleanupError = [string]$_.Exception.Message
            $mutableAgentFileCleanup[$snapshot.name] = [ordered]@{
                path = $snapshot.path
                restored_exactly = $false
                error = $fileCleanupError
            }
            [void]$cleanupFailures.Add("mutable-file:$($snapshot.name):$fileCleanupError")
        }
    }
    if ($null -eq $receipt.clean) { $receipt.clean = [ordered]@{} }
    $receipt.clean['mutable_agent_files'] = $mutableAgentFileCleanup
    try {
        $childSessionCleanup = Restore-HighCapacityFilesystemChildSessions `
            -ChildRoot $childSessionsRoot `
            -SessionsRoot $agentSessionsRoot `
            -ChildRootExisted $childSessionsRootExisted `
            -SessionsRootExisted $agentSessionsRootExisted `
            -EntryNamesBefore $childSessionEntryNamesBefore `
            -FingerprintBefore $childSessionsFingerprintBefore
        if ($null -eq $receipt.clean) { $receipt.clean = [ordered]@{} }
        $receipt.clean['child_sessions'] = $childSessionCleanup
        $receipt.clean['transcript_hashes_bound_before_session_retirement'] = ($null -ne $receipt.body_lab)
    } catch {
        $sessionCleanupError = [string]$_.Exception.Message
        $receipt.clean['child_sessions'] = [ordered]@{
            restored_exactly = $false
            error = $sessionCleanupError
        }
        [void]$cleanupFailures.Add("child-sessions:$sessionCleanupError")
    }
    if ($cleanupFailures.Count -gt 0) {
        $cleanupError = $cleanupFailures -join '; '
        $receipt.status = 'blocked'
        $receipt.error = if ([string]::IsNullOrWhiteSpace([string]$receipt.error)) {
            "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CLEANUP_FAILED: $cleanupError"
        } else {
            "PI_HIGH_CAPACITY_FILESYSTEM_RESUME_CLEANUP_FAILED: $cleanupError; prior=$($receipt.error)"
        }
    }
    $receipt.completed_at = [DateTimeOffset]::Now.ToString('o')
    Write-HighCapacityFilesystemJsonAtomic -Path $receiptTarget -Value $receipt
    [Console]::Out.WriteLine(($receipt | ConvertTo-Json -Depth 18))
}

if ([string]$receipt.status -cne 'verified') { exit 1 }
