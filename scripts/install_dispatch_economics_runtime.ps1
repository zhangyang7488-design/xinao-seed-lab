#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false, $true)
$bindingShaPlaceholder = "__XINAO_SELECTOR_VALIDATOR_BINDING_SHA256__"
$bindingBase64Placeholder = "__XINAO_SELECTOR_VALIDATOR_BINDING_BASE64__"
$validatorClosure = @(
    "scripts/build_selector_release.py",
    "services/__init__.py",
    "services/agent_runtime/__init__.py",
    "services/agent_runtime/selector_release.py"
)
$sourceRootFull = [IO.Path]::GetFullPath($SourceRoot)
$source = Join-Path $sourceRootFull "scripts\quota_query\Get-AIQuota.ps1"
$runtimeRootRequested = [IO.Path]::GetFullPath($RuntimeRoot)

function Get-Sha256Hex {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes
    )

    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}

function Initialize-XinaoInstallPathNative {
    if ($null -ne ("XinaoInstallPathNative" -as [type])) {
        return
    }
    $nativeSource = @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class XinaoInstallPathNative
{
    public const uint FileAttributeDirectory = 0x00000010;
    public const uint FileAttributeReparsePoint = 0x00000400;
    private const uint GenericRead = 0x80000000;
    private const uint GenericWrite = 0x40000000;
    private const uint FileReadAttributes = 0x00000080;
    private const uint FileShareRead = 0x00000001;
    private const uint OpenExisting = 3;
    private const uint OpenAlways = 4;
    private const uint FileFlagBackupSemantics = 0x02000000;
    private const uint FileFlagOpenReparsePoint = 0x00200000;
    private const uint FileFlagSequentialScan = 0x08000000;

    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation
    {
        public uint FileAttributes;
        public FILETIME CreationTime;
        public FILETIME LastAccessTime;
        public FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle file,
        out ByHandleFileInformation information);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(
        SafeFileHandle file,
        StringBuilder path,
        uint pathLength,
        uint flags);

    public static SafeFileHandle OpenDirectory(string path)
    {
        SafeFileHandle handle = CreateFileW(
            path,
            FileReadAttributes,
            FileShareRead,
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics | FileFlagOpenReparsePoint,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error, "CreateFileW directory open failed: " + path);
        }
        return handle;
    }

    public static SafeFileHandle OpenReadFile(string path)
    {
        SafeFileHandle handle = CreateFileW(
            path,
            GenericRead,
            FileShareRead,
            IntPtr.Zero,
            OpenExisting,
            FileFlagOpenReparsePoint | FileFlagSequentialScan,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error, "CreateFileW file open failed: " + path);
        }
        return handle;
    }

    public static SafeFileHandle OpenExclusiveLock(string path)
    {
        SafeFileHandle handle = CreateFileW(
            path,
            GenericRead | GenericWrite,
            0,
            IntPtr.Zero,
            OpenAlways,
            FileFlagOpenReparsePoint,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error, "CreateFileW lock open failed: " + path);
        }
        return handle;
    }

    public static uint GetAttributes(SafeFileHandle handle)
    {
        ByHandleFileInformation information;
        if (!GetFileInformationByHandle(handle, out information))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        return information.FileAttributes;
    }

    public static string GetFinalPath(SafeFileHandle handle)
    {
        int capacity = 512;
        while (true)
        {
            StringBuilder value = new StringBuilder(capacity);
            uint length = GetFinalPathNameByHandleW(handle, value, (uint)capacity, 0);
            if (length == 0)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            if (length < capacity)
            {
                string path = value.ToString();
                if (path.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
                {
                    return @"\\" + path.Substring(8);
                }
                if (path.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase))
                {
                    return path.Substring(4);
                }
                return path;
            }
            capacity = checked((int)length + 1);
        }
    }
}
'@
    Add-Type -TypeDefinition $nativeSource -Language CSharp | Out-Null
}

function Add-NoReparseInstallDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.List[IDisposable]]$Handles,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.HashSet[string]]$Seen
    )

    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not $Seen.Add($fullPath)) {
        return
    }
    $handle = $null
    try {
        $handle = [XinaoInstallPathNative]::OpenDirectory($fullPath)
        $attributes = [XinaoInstallPathNative]::GetAttributes($handle)
        if (
            ($attributes -band [XinaoInstallPathNative]::FileAttributeDirectory) -eq 0 -or
            ($attributes -band [XinaoInstallPathNative]::FileAttributeReparsePoint) -ne 0
        ) {
            throw "XINAO_QUOTA_INSTALL_NAMESPACE_REPARSE_POINT: $fullPath"
        }
        [void]$Handles.Add($handle)
        $handle = $null
    }
    finally {
        if ($null -ne $handle) {
            $handle.Dispose()
        }
    }
}

function Add-NoReparseInstallAncestry {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.List[IDisposable]]$Handles,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.HashSet[string]]$Seen
    )

    $current = [IO.Path]::GetFullPath($Path)
    $ancestors = [Collections.Generic.List[string]]::new()
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        [void]$ancestors.Add($current)
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) {
            break
        }
        $current = $parent
    }
    for ($index = $ancestors.Count - 1; $index -ge 0; $index--) {
        Add-NoReparseInstallDirectory -Path $ancestors[$index] `
            -Handles $Handles -Seen $Seen
    }
}

function Open-FixedInstallDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.List[IDisposable]]$Handles,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.HashSet[string]]$Seen
    )

    Initialize-XinaoInstallPathNative
    Add-NoReparseInstallAncestry -Path $Path -Handles $Handles -Seen $Seen
    $leafHandle = [XinaoInstallPathNative]::OpenDirectory([IO.Path]::GetFullPath($Path))
    try {
        $attributes = [XinaoInstallPathNative]::GetAttributes($leafHandle)
        if (($attributes -band [XinaoInstallPathNative]::FileAttributeReparsePoint) -ne 0) {
            throw "XINAO_QUOTA_INSTALL_NAMESPACE_REPARSE_POINT: $Path"
        }
        $finalPath = [IO.Path]::GetFullPath(
            [XinaoInstallPathNative]::GetFinalPath($leafHandle)
        )
        Add-NoReparseInstallAncestry -Path $finalPath -Handles $Handles -Seen $Seen
        $finalPath
    }
    finally {
        $leafHandle.Dispose()
    }
}

function Get-InstallFileCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.List[IDisposable]]$Handles,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.HashSet[string]]$Seen,
        [switch]$Hold
    )

    $fullPath = [IO.Path]::GetFullPath($Path)
    Add-NoReparseInstallAncestry -Path (Split-Path -Parent $fullPath) `
        -Handles $Handles -Seen $Seen
    $safeHandle = [XinaoInstallPathNative]::OpenReadFile($fullPath)
    $stream = $null
    try {
        $attributes = [XinaoInstallPathNative]::GetAttributes($safeHandle)
        if (
            ($attributes -band [XinaoInstallPathNative]::FileAttributeDirectory) -ne 0 -or
            ($attributes -band [XinaoInstallPathNative]::FileAttributeReparsePoint) -ne 0
        ) {
            throw "XINAO_QUOTA_INSTALL_FILE_REPARSE_POINT: $fullPath"
        }
        $finalPath = [IO.Path]::GetFullPath(
            [XinaoInstallPathNative]::GetFinalPath($safeHandle)
        )
        Add-NoReparseInstallAncestry -Path (Split-Path -Parent $finalPath) `
            -Handles $Handles -Seen $Seen
        $stream = [IO.FileStream]::new($safeHandle, [IO.FileAccess]::Read)
        $safeHandle = $null
        $memory = [IO.MemoryStream]::new()
        try {
            $stream.CopyTo($memory)
            $bytes = $memory.ToArray()
        }
        finally {
            $memory.Dispose()
        }
        $stream.Position = 0
        if ($Hold) {
            [void]$Handles.Add($stream)
            $stream = $null
        }
        [pscustomobject]@{
            path = $finalPath
            bytes = $bytes
            sha256 = Get-Sha256Hex -Bytes $bytes
            size_bytes = $bytes.Length
        }
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        } elseif ($null -ne $safeHandle) {
            $safeHandle.Dispose()
        }
    }
}

function Assert-InstallLeafNotReparse {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$ErrorCode
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "${ErrorCode}: $Path"
    }
}

function Get-SourceGitHead {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $lines = @(& git -C $Root rev-parse HEAD 2>&1 | ForEach-Object { [string]$_ })
    $exitCode = $LASTEXITCODE
    $head = [string](@($lines | Where-Object { $_ -match '^[0-9a-fA-F]{40}$' }) |
        Select-Object -Last 1)
    if ($exitCode -ne 0 -or $head -notmatch '^[0-9a-fA-F]{40}$') {
        throw "XINAO_QUOTA_EPOCH_SOURCE_GIT_HEAD_UNAVAILABLE: $Root"
    }
    $head.ToLowerInvariant()
}

function Resolve-BasePython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.List[IDisposable]]$Handles,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.HashSet[string]]$Seen
    )

    $candidate = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        $pythonCommand = Get-Command python.exe -CommandType Application -ErrorAction Stop |
            Select-Object -First 1
        $candidate = [string]$pythonCommand.Source
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "XINAO_SELECTOR_RELEASE_VALIDATOR_PYTHON_MISSING: $candidate"
    }
    $candidateCapture = Get-InstallFileCapture -Path $candidate `
        -Handles $Handles -Seen $Seen -Hold
    $candidatePhysical = [string]$candidateCapture.path
    if ([IO.Path]::GetExtension($candidatePhysical) -ne ".exe") {
        throw "XINAO_SELECTOR_RELEASE_VALIDATOR_PYTHON_INVALID: native python.exe required"
    }
    $lines = @(& $candidatePhysical -I -S -B -c "import os,sys; print(os.path.realpath(sys._base_executable))" 2>&1 |
        ForEach-Object { [string]$_ })
    $exitCode = $LASTEXITCODE
    $basePython = [string](@($lines | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_)
    }) | Select-Object -Last 1)
    if (
        $exitCode -ne 0 -or
        [string]::IsNullOrWhiteSpace($basePython) -or
        -not [IO.Path]::IsPathFullyQualified($basePython)
    ) {
        throw (
            "XINAO_SELECTOR_RELEASE_VALIDATOR_PYTHON_INVALID: " +
            "exit=$exitCode output=$($lines -join [Environment]::NewLine)"
        )
    }
    $baseCapture = Get-InstallFileCapture -Path ([IO.Path]::GetFullPath($basePython)) `
        -Handles $Handles -Seen $Seen -Hold
    [pscustomobject]@{
        candidate = $candidateCapture
        base = $baseCapture
    }
}

function Resolve-BaseNode {
    $nodeCommand = Get-Command node.exe -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    $candidate = [string]$nodeCommand.Source
    if (
        [string]::IsNullOrWhiteSpace($candidate) -or
        -not [IO.Path]::IsPathFullyQualified($candidate)
    ) {
        throw "XINAO_QUOTA_INSTALL_NODE_INVALID: native node.exe required"
    }
    $resolved = [IO.Path]::GetFullPath($candidate)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "XINAO_QUOTA_INSTALL_NODE_MISSING: $resolved"
    }
    $resolved
}

function Test-ExactInstalledState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [bool]$ExpectedPresent,
        [AllowEmptyCollection()]
        [byte[]]$ExpectedBytes
    )

    $present = Test-Path -LiteralPath $Path -PathType Leaf
    if ($present -ne $ExpectedPresent) {
        return $false
    }
    if (-not $ExpectedPresent) {
        return $true
    }
    $observed = [IO.File]::ReadAllBytes($Path)
    $observed.Length -eq $ExpectedBytes.Length -and
        (Get-Sha256Hex -Bytes $observed) -eq (Get-Sha256Hex -Bytes $ExpectedBytes)
}

function Restore-InstalledFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetPath,
        [Parameter(Mandatory = $true)]
        [bool]$PreviouslyExisted,
        [AllowEmptyCollection()]
        [byte[]]$PreviousBytes
    )

    if (-not $PreviouslyExisted) {
        Remove-Item -LiteralPath $TargetPath -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $TargetPath) {
            throw "rollback could not remove newly installed file: $TargetPath"
        }
        return
    }
    $restoreTemporary = $TargetPath + "." + [guid]::NewGuid().ToString("N") + ".restore.tmp"
    try {
        [IO.File]::WriteAllBytes($restoreTemporary, $PreviousBytes)
        Move-Item -LiteralPath $restoreTemporary -Destination $TargetPath -Force
        if (-not (Test-ExactInstalledState -Path $TargetPath -ExpectedPresent $true -ExpectedBytes $PreviousBytes)) {
            throw "rollback readback mismatch: $TargetPath"
        }
    }
    finally {
        Remove-Item -LiteralPath $restoreTemporary -Force -ErrorAction SilentlyContinue
    }
}

function Enter-QuotaInstallLock {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [int]$TimeoutMilliseconds = 30000
    )

    $deadline = [Environment]::TickCount64 + $TimeoutMilliseconds
    while ($true) {
        try {
            $handle = [XinaoInstallPathNative]::OpenExclusiveLock($Path)
            $attributes = [XinaoInstallPathNative]::GetAttributes($handle)
            if (($attributes -band [XinaoInstallPathNative]::FileAttributeReparsePoint) -ne 0) {
                $handle.Dispose()
                throw "XINAO_QUOTA_INSTALL_LOCK_REPARSE_POINT: $Path"
            }
            return $handle
        }
        catch [ComponentModel.Win32Exception] {
            $nativeCode = $_.Exception.NativeErrorCode
            if ($nativeCode -ne 32) {
                throw (
                    "XINAO_QUOTA_INSTALL_LOCK_FAILED: path=$Path " +
                    "error=$($_.Exception.Message)"
                )
            }
            if ([Environment]::TickCount64 -ge $deadline) {
                throw "XINAO_QUOTA_INSTALL_LOCK_TIMEOUT: $Path"
            }
            Start-Sleep -Milliseconds 50
        }
    }
}

$installNamespaceHandles = [Collections.Generic.List[IDisposable]]::new()
$installNamespaceSeen = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
if (-not (Test-Path -LiteralPath $runtimeRootRequested -PathType Container)) {
    throw "XINAO_QUOTA_INSTALL_RUNTIME_ROOT_MISSING: $runtimeRootRequested"
}
try {
$physicalRuntimeRoot = Open-FixedInstallDirectory -Path $runtimeRootRequested `
    -Handles $installNamespaceHandles -Seen $installNamespaceSeen
$stateDirectoryRequested = Join-Path $physicalRuntimeRoot "state"
[IO.Directory]::CreateDirectory($stateDirectoryRequested) | Out-Null
$physicalStateDirectory = Open-FixedInstallDirectory -Path $stateDirectoryRequested `
    -Handles $installNamespaceHandles -Seen $installNamespaceSeen
$targetDirectoryRequested = Join-Path $physicalStateDirectory "quota_query"
[IO.Directory]::CreateDirectory($targetDirectoryRequested) | Out-Null
$targetDirectory = Open-FixedInstallDirectory -Path $targetDirectoryRequested `
    -Handles $installNamespaceHandles -Seen $installNamespaceSeen
$releaseParentRequested = Join-Path $physicalStateDirectory "quota_query_releases"
[IO.Directory]::CreateDirectory($releaseParentRequested) | Out-Null
$releaseParent = Open-FixedInstallDirectory -Path $releaseParentRequested `
    -Handles $installNamespaceHandles -Seen $installNamespaceSeen
$target = Join-Path $targetDirectory "Get-AIQuota.ps1"
$collector = Join-Path $targetDirectory "quota-query.mjs"

if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "XINAO_QUOTA_EPOCH_SOURCE_MISSING: $source"
}
if (-not (Test-Path -LiteralPath $collector -PathType Leaf)) {
    throw "XINAO_QUOTA_LIVE_COLLECTOR_MISSING"
}
foreach ($relativeText in $validatorClosure) {
    $origin = Join-Path $sourceRootFull ($relativeText -replace '/', '\')
    if (-not (Test-Path -LiteralPath $origin -PathType Leaf)) {
        throw "XINAO_SELECTOR_RELEASE_VALIDATOR_MISSING: $origin"
    }
}
$tokens = $null
$errors = $null
[void][Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if (@($errors).Count -gt 0) {
    throw "XINAO_QUOTA_EPOCH_SOURCE_PARSE_FAILED: $($errors -join '; ')"
}

$sourceGitHead = Get-SourceGitHead -Root $sourceRootFull
$sourceBytes = [IO.File]::ReadAllBytes($source)
$sourceSha = Get-Sha256Hex -Bytes $sourceBytes
$sourceText = $utf8.GetString($sourceBytes)
foreach ($placeholder in @($bindingShaPlaceholder, $bindingBase64Placeholder)) {
    $placeholderMatches = [regex]::Matches($sourceText, [regex]::Escape($placeholder)).Count
    if ($placeholderMatches -ne 1) {
        throw (
            "XINAO_SELECTOR_VALIDATOR_TRUST_ANCHOR_INVALID: " +
            "placeholder=$placeholder count=$placeholderMatches"
        )
    }
}
$capturedValidatorBytes = [ordered]@{}
foreach ($relativeText in $validatorClosure) {
    $origin = Join-Path $sourceRootFull ($relativeText -replace '/', '\')
    $capturedValidatorBytes[$relativeText] = [IO.File]::ReadAllBytes($origin)
}

$installLockPath = Join-Path $targetDirectory ".install.lock"
$installLock = Enter-QuotaInstallLock -Path $installLockPath
try {
$validatorPythonResolution = Resolve-BasePython -Root $sourceRootFull `
    -Handles $installNamespaceHandles -Seen $installNamespaceSeen
$validatorPythonCandidateCapture = $validatorPythonResolution.candidate
$validatorPythonCapture = $validatorPythonResolution.base
$validatorPython = [string]$validatorPythonCapture.path
$validatorPythonBytes = [byte[]]$validatorPythonCapture.bytes
$validatorPythonSha = [string]$validatorPythonCapture.sha256
$previousTargetExisted = Test-Path -LiteralPath $target -PathType Leaf
Assert-InstallLeafNotReparse -Path $target -ErrorCode "XINAO_QUOTA_INSTALL_TARGET_REPARSE_POINT"
$previousTargetBytes = if ($previousTargetExisted) { [IO.File]::ReadAllBytes($target) } else { $null }
$previousSha = if ($previousTargetExisted) { Get-Sha256Hex -Bytes $previousTargetBytes } else { "" }
$collectorCapture = Get-InstallFileCapture -Path $collector `
    -Handles $installNamespaceHandles -Seen $installNamespaceSeen -Hold
$collector = [string]$collectorCapture.path
$collectorBytes = [byte[]]$collectorCapture.bytes
$collectorSha = [string]$collectorCapture.sha256
$nodeCandidate = Resolve-BaseNode
$nodeCapture = Get-InstallFileCapture -Path $nodeCandidate `
    -Handles $installNamespaceHandles -Seen $installNamespaceSeen -Hold
$nodeExecutable = [string]$nodeCapture.path
$nodeBytes = [byte[]]$nodeCapture.bytes
$nodeSha = [string]$nodeCapture.sha256

$releaseId = (
    "quota-validator-" + (Get-Date -Format "yyyyMMddTHHmmssfff") + "-" +
    $sourceSha.Substring(0, 12) + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
)
$releaseRoot = Join-Path $releaseParent $releaseId
$validatorRoot = Join-Path $releaseRoot "validator"
$backup = ""
$targetTemporary = $target + "." + [guid]::NewGuid().ToString("N") + ".tmp"
$receiptPath = Join-Path $releaseRoot "install-receipt.json"
$receiptTemporary = $receiptPath + "." + [guid]::NewGuid().ToString("N") + ".tmp"
$releaseCreated = $false
$targetPublished = $false
$rollbackSucceeded = $false
try {
    New-Item -ItemType Directory -Path $validatorRoot -ErrorAction Stop | Out-Null
    $releaseCreated = $true
    if ($previousTargetExisted) {
        $backup = Join-Path $releaseRoot "previous.Get-AIQuota.ps1"
        [IO.File]::WriteAllBytes($backup, $previousTargetBytes)
    }
    $validatorRows = @()
    foreach ($relativeText in $validatorClosure) {
        $selectedBytes = [byte[]]$capturedValidatorBytes[$relativeText]
        $destination = Join-Path $validatorRoot ($relativeText -replace '/', '\')
        [IO.Directory]::CreateDirectory((Split-Path -Parent $destination)) | Out-Null
        [IO.File]::WriteAllBytes($destination, $selectedBytes)
        $readback = [IO.File]::ReadAllBytes($destination)
        $expectedSha = Get-Sha256Hex -Bytes $selectedBytes
        if ($readback.Length -ne $selectedBytes.Length -or (Get-Sha256Hex -Bytes $readback) -ne $expectedSha) {
            throw "XINAO_SELECTOR_VALIDATOR_RELEASE_READBACK_MISMATCH: $relativeText"
        }
        $validatorRows += [ordered]@{
            path = $relativeText
            sha256 = $expectedSha
            size_bytes = $selectedBytes.Length
        }
    }

    $bindingPayload = [ordered]@{
        schema_version = "xinao.selector_validator_binding.v2"
        validator_root = [IO.Path]::GetFullPath($validatorRoot)
        files = $validatorRows
        python_executable = $validatorPython
        python_sha256 = $validatorPythonSha
        python_size_bytes = $validatorPythonBytes.Length
        python_candidate = [ordered]@{
            path = [string]$validatorPythonCandidateCapture.path
            sha256 = [string]$validatorPythonCandidateCapture.sha256
            size_bytes = [long]$validatorPythonCandidateCapture.size_bytes
        }
        collector = [ordered]@{
            path = [IO.Path]::GetFullPath($collector)
            sha256 = $collectorSha
            size_bytes = $collectorBytes.Length
        }
        node = [ordered]@{
            path = $nodeExecutable
            sha256 = $nodeSha
            size_bytes = $nodeBytes.Length
        }
        authority = $false
        completion_claim_allowed = $false
    }
    $bindingBytes = $utf8.GetBytes(($bindingPayload | ConvertTo-Json -Depth 8 -Compress) + "`n")
    $bindingSha = Get-Sha256Hex -Bytes $bindingBytes
    $bindingBase64 = [Convert]::ToBase64String($bindingBytes)
    $installedText = $sourceText.Replace($bindingShaPlaceholder, $bindingSha).
        Replace($bindingBase64Placeholder, $bindingBase64)
    if (
        $installedText.Contains($bindingShaPlaceholder) -or
        $installedText.Contains($bindingBase64Placeholder)
    ) {
        throw "XINAO_SELECTOR_VALIDATOR_TRUST_ANCHOR_INJECTION_FAILED"
    }
    $installedBytes = $utf8.GetBytes($installedText)
    $installedSha = Get-Sha256Hex -Bytes $installedBytes
    [IO.File]::WriteAllBytes($targetTemporary, $installedBytes)
    if ((Get-Sha256Hex -Bytes ([IO.File]::ReadAllBytes($targetTemporary))) -ne $installedSha) {
        throw "XINAO_QUOTA_EPOCH_STAGING_HASH_MISMATCH"
    }
    $stagedTokens = $null
    $stagedErrors = $null
    [void][Management.Automation.Language.Parser]::ParseFile(
        $targetTemporary,
        [ref]$stagedTokens,
        [ref]$stagedErrors
    )
    if (@($stagedErrors).Count -gt 0) {
        throw "XINAO_QUOTA_EPOCH_STAGED_PARSE_FAILED: $($stagedErrors -join '; ')"
    }

    foreach ($relativeText in $validatorClosure) {
        $origin = Join-Path $sourceRootFull ($relativeText -replace '/', '\')
        $observedBytes = [IO.File]::ReadAllBytes($origin)
        $expectedBytes = [byte[]]$capturedValidatorBytes[$relativeText]
        if (
            $observedBytes.Length -ne $expectedBytes.Length -or
            (Get-Sha256Hex -Bytes $observedBytes) -ne (Get-Sha256Hex -Bytes $expectedBytes)
        ) {
            throw "XINAO_SELECTOR_VALIDATOR_SOURCE_CHANGED: $relativeText"
        }
    }
    $observedSourceBytes = [IO.File]::ReadAllBytes($source)
    if (
        $observedSourceBytes.Length -ne $sourceBytes.Length -or
        (Get-Sha256Hex -Bytes $observedSourceBytes) -ne $sourceSha
    ) {
        throw "XINAO_QUOTA_EPOCH_SOURCE_CHANGED"
    }
    Assert-InstallLeafNotReparse -Path $target `
        -ErrorCode "XINAO_QUOTA_INSTALL_TARGET_REPARSE_POINT"
    if (-not (Test-ExactInstalledState -Path $target -ExpectedPresent $previousTargetExisted -ExpectedBytes $previousTargetBytes)) {
        throw "XINAO_QUOTA_INSTALL_TARGET_CHANGED_BEFORE_PUBLISH"
    }
    if (-not (Test-ExactInstalledState -Path $collector -ExpectedPresent $true -ExpectedBytes $collectorBytes)) {
        throw "XINAO_QUOTA_INSTALL_COLLECTOR_CHANGED_BEFORE_PUBLISH"
    }
    if (-not (Test-ExactInstalledState -Path $nodeExecutable -ExpectedPresent $true -ExpectedBytes $nodeBytes)) {
        throw "XINAO_QUOTA_INSTALL_NODE_CHANGED_BEFORE_PUBLISH"
    }

    # The exact validator binding is embedded in these target bytes.  This one
    # atomic move is therefore the complete consumer generation commit point.
    Move-Item -LiteralPath $targetTemporary -Destination $target -Force
    $targetPublished = $true
    if (-not (Test-ExactInstalledState -Path $target -ExpectedPresent $true -ExpectedBytes $installedBytes)) {
        throw "XINAO_QUOTA_EPOCH_INSTALL_HASH_MISMATCH"
    }

    $observedGitHead = Get-SourceGitHead -Root $sourceRootFull
    if ($observedGitHead -ne $sourceGitHead) {
        throw (
            "XINAO_QUOTA_INSTALL_SOURCE_GIT_HEAD_CHANGED: " +
            "expected=$sourceGitHead observed=$observedGitHead"
        )
    }
    foreach ($relativeText in $validatorClosure) {
        $origin = Join-Path $sourceRootFull ($relativeText -replace '/', '\')
        $observedBytes = [IO.File]::ReadAllBytes($origin)
        $expectedBytes = [byte[]]$capturedValidatorBytes[$relativeText]
        if (
            $observedBytes.Length -ne $expectedBytes.Length -or
            (Get-Sha256Hex -Bytes $observedBytes) -ne (Get-Sha256Hex -Bytes $expectedBytes)
        ) {
            throw "XINAO_SELECTOR_VALIDATOR_SOURCE_CHANGED_AFTER_PUBLISH: $relativeText"
        }
    }
    if (-not (Test-ExactInstalledState -Path $collector -ExpectedPresent $true -ExpectedBytes $collectorBytes)) {
        throw "XINAO_QUOTA_INSTALL_COLLECTOR_CHANGED_AFTER_PUBLISH"
    }
    if (-not (Test-ExactInstalledState -Path $nodeExecutable -ExpectedPresent $true -ExpectedBytes $nodeBytes)) {
        throw "XINAO_QUOTA_INSTALL_NODE_CHANGED_AFTER_PUBLISH"
    }

    $receipt = [ordered]@{
        schema_version = "xinao.dispatch_economics_runtime_install_receipt.v3"
        installed_at = (Get-Date).ToString("o")
        source_root = $sourceRootFull
        source_git_head = $sourceGitHead
        source_ref = [IO.Path]::GetFullPath($source)
        source_sha256 = $sourceSha
        validator_root = [IO.Path]::GetFullPath($validatorRoot)
        validator_files = $validatorRows
        validator_python_ref = $validatorPython
        validator_python_sha256 = $validatorPythonSha
        validator_python_size_bytes = $validatorPythonBytes.Length
        validator_python_candidate_ref = [string]$validatorPythonCandidateCapture.path
        validator_python_candidate_sha256 = [string]$validatorPythonCandidateCapture.sha256
        validator_python_candidate_size_bytes = [long]$validatorPythonCandidateCapture.size_bytes
        collector_ref = [IO.Path]::GetFullPath($collector)
        collector_sha256 = $collectorSha
        collector_size_bytes = $collectorBytes.Length
        node_ref = $nodeExecutable
        node_sha256 = $nodeSha
        node_size_bytes = $nodeBytes.Length
        validator_binding_storage = "embedded_base64"
        validator_binding_sha256 = $bindingSha
        target_ref = [IO.Path]::GetFullPath($target)
        target_sha256 = $installedSha
        previous_sha256 = $previousSha
        rollback_ref = $backup
        release_id = $releaseId
        release_root = [IO.Path]::GetFullPath($releaseRoot)
        authority = $false
        completion_claim_allowed = $false
    }
    $receiptBytes = $utf8.GetBytes(($receipt | ConvertTo-Json -Depth 8) + "`n")
    [IO.File]::WriteAllBytes($receiptTemporary, $receiptBytes)
    Move-Item -LiteralPath $receiptTemporary -Destination $receiptPath
    $receiptReadback = [IO.File]::ReadAllBytes($receiptPath)
    if (
        $receiptReadback.Length -ne $receiptBytes.Length -or
        (Get-Sha256Hex -Bytes $receiptReadback) -ne (Get-Sha256Hex -Bytes $receiptBytes)
    ) {
        throw "XINAO_QUOTA_INSTALL_RECEIPT_READBACK_MISMATCH"
    }
    $receiptSha = Get-Sha256Hex -Bytes $receiptReadback
    $receipt | Add-Member -NotePropertyName receipt_ref -NotePropertyValue $receiptPath
    $receipt | Add-Member -NotePropertyName receipt_sha256 -NotePropertyValue $receiptSha
    if (
        -not (Test-ExactInstalledState -Path $target -ExpectedPresent $true -ExpectedBytes $installedBytes) -or
        -not (Test-ExactInstalledState -Path $collector -ExpectedPresent $true -ExpectedBytes $collectorBytes) -or
        -not (Test-ExactInstalledState -Path $nodeExecutable -ExpectedPresent $true -ExpectedBytes $nodeBytes)
    ) {
        throw "XINAO_QUOTA_INSTALL_FINAL_TARGET_READBACK_MISMATCH"
    }
}
catch {
    $installError = $_
    Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
    try {
        if ($targetPublished) {
            if (-not (Test-ExactInstalledState -Path $target -ExpectedPresent $true -ExpectedBytes $installedBytes)) {
                throw "installed consumer changed before rollback: $target"
            }
        }
        if ($targetPublished) {
            Restore-InstalledFile -TargetPath $target -PreviouslyExisted $previousTargetExisted -PreviousBytes $previousTargetBytes
        }
        $rollbackSucceeded = $true
    }
    catch {
        throw (
            "XINAO_QUOTA_EPOCH_INSTALL_ROLLBACK_FAILED: " +
            "install=$($installError.Exception.Message); rollback=$($_.Exception.Message); " +
            "recovery_root=$releaseRoot"
        )
    }
    if ($releaseCreated -and $rollbackSucceeded -and (Test-Path -LiteralPath $releaseRoot)) {
        Remove-Item -LiteralPath $releaseRoot -Recurse -Force -ErrorAction Stop
    }
    if ($installError.Exception.Message -like "XINAO_QUOTA_EPOCH_SOURCE_GIT_HEAD_UNAVAILABLE:*") {
        throw "XINAO_QUOTA_INSTALL_SOURCE_GIT_HEAD_CHANGED: $sourceRootFull"
    }
    throw $installError
}
finally {
    Remove-Item -LiteralPath $targetTemporary -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $receiptTemporary -Force -ErrorAction SilentlyContinue
}
$receipt | ConvertTo-Json -Depth 8
}
finally {
    $installLock.Dispose()
}
}
finally {
    for ($index = $installNamespaceHandles.Count - 1; $index -ge 0; $index--) {
        $installNamespaceHandles[$index].Dispose()
    }
    $installNamespaceHandles.Clear()
}
