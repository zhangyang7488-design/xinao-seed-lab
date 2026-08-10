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
$installedValidatorBindingSha256 = "__XINAO_SELECTOR_VALIDATOR_BINDING_SHA256__"
$installedValidatorBindingBase64 = "__XINAO_SELECTOR_VALIDATOR_BINDING_BASE64__"
$validatorBindingPlaceholder = "__XINAO_" + "SELECTOR_VALIDATOR_BINDING_SHA256__"
$validatorBindingBase64Placeholder = "__XINAO_" + "SELECTOR_VALIDATOR_BINDING_BASE64__"
$validatorClosure = @(
    "scripts/build_selector_release.py",
    "services/__init__.py",
    "services/agent_runtime/__init__.py",
    "services/agent_runtime/selector_release.py"
)
$collector = Join-Path $PSScriptRoot "quota-query.mjs"
if (-not (Test-Path -LiteralPath $collector -PathType Leaf)) {
    throw "XINAO_QUOTA_COLLECTOR_MISSING: $collector"
}

function Get-Sha256Hex {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes
    )

    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}

function Initialize-XinaoTrustedFileNative {
    if ($null -ne ("XinaoTrustedFileNative" -as [type])) {
        return
    }
    $nativeSource = @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class XinaoTrustedFileNative
{
    public const uint FileAttributeDirectory = 0x00000010;
    public const uint FileAttributeReparsePoint = 0x00000400;
    private const uint GenericRead = 0x80000000;
    private const uint FileReadAttributes = 0x00000080;
    private const uint FileShareRead = 0x00000001;
    private const uint OpenExisting = 3;
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

    private static SafeFileHandle OpenNoReparse(
        string path,
        uint desiredAccess,
        uint extraFlags)
    {
        SafeFileHandle handle = CreateFileW(
            path,
            desiredAccess,
            FileShareRead,
            IntPtr.Zero,
            OpenExisting,
            FileFlagOpenReparsePoint | extraFlags,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error, "CreateFileW no-reparse open failed: " + path);
        }
        return handle;
    }

    public static SafeFileHandle OpenReadFile(string path)
    {
        return OpenNoReparse(path, GenericRead, FileFlagSequentialScan);
    }

    public static SafeFileHandle OpenDirectory(string path)
    {
        return OpenNoReparse(path, FileReadAttributes, FileFlagBackupSemantics);
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

    public static string GetIdentity(SafeFileHandle handle)
    {
        ByHandleFileInformation information;
        if (!GetFileInformationByHandle(handle, out information))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        return information.VolumeSerialNumber.ToString("x8") + ":" +
            information.FileIndexHigh.ToString("x8") +
            information.FileIndexLow.ToString("x8");
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

function Add-NoReparseAncestorLocks {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.List[IDisposable]]$Handles,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.HashSet[string]]$Seen,
        [Parameter(Mandatory = $true)]
        [string]$ErrorCode
    )

    Initialize-XinaoTrustedFileNative
    $current = Split-Path -Parent ([IO.Path]::GetFullPath($Path))
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
        $ancestor = $ancestors[$index]
        if (-not $Seen.Add($ancestor)) {
            continue
        }
        $directoryHandle = $null
        try {
            $directoryHandle = [XinaoTrustedFileNative]::OpenDirectory($ancestor)
            $attributes = [XinaoTrustedFileNative]::GetAttributes($directoryHandle)
            if (
                ($attributes -band [XinaoTrustedFileNative]::FileAttributeDirectory) -eq 0 -or
                ($attributes -band [XinaoTrustedFileNative]::FileAttributeReparsePoint) -ne 0
            ) {
                throw "${ErrorCode}: $ancestor"
            }
            [void]$Handles.Add($directoryHandle)
            $directoryHandle = $null
        }
        catch {
            if ($null -ne $directoryHandle) {
                $directoryHandle.Dispose()
            }
            if ($_.Exception.Message.StartsWith("${ErrorCode}:", [StringComparison]::Ordinal)) {
                throw
            }
            throw "${ErrorCode}: path=$ancestor error=$($_.Exception.Message)"
        }
    }
}

function Add-HashBoundReadLock {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha256,
        [Parameter(Mandatory = $true)]
        [long]$ExpectedSizeBytes,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.List[IDisposable]]$Handles,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [Collections.Generic.HashSet[string]]$SeenAncestors,
        [Parameter(Mandatory = $true)]
        [string]$ReparseErrorCode,
        [Parameter(Mandatory = $true)]
        [string]$HashErrorCode
    )

    Initialize-XinaoTrustedFileNative
    Add-NoReparseAncestorLocks -Path $Path -Handles $Handles `
        -Seen $SeenAncestors -ErrorCode $ReparseErrorCode
    $safeHandle = $null
    $handle = $null
    try {
        $safeHandle = [XinaoTrustedFileNative]::OpenReadFile($Path)
        $attributes = [XinaoTrustedFileNative]::GetAttributes($safeHandle)
        if (($attributes -band [XinaoTrustedFileNative]::FileAttributeReparsePoint) -ne 0) {
            throw "${ReparseErrorCode}: $Path"
        }
        $finalPath = [XinaoTrustedFileNative]::GetFinalPath($safeHandle)
        $fileIdentity = [XinaoTrustedFileNative]::GetIdentity($safeHandle)
        $handle = [IO.FileStream]::new($safeHandle, [IO.FileAccess]::Read)
        $safeHandle = $null
        $hasher = [Security.Cryptography.SHA256]::Create()
        try {
            $observedSha = [Convert]::ToHexString($hasher.ComputeHash($handle)).ToLowerInvariant()
        }
        finally {
            $hasher.Dispose()
        }
        if ($handle.Length -ne $ExpectedSizeBytes -or $observedSha -ne $ExpectedSha256) {
            throw (
                "${HashErrorCode}: path=$Path " +
                "expected=$ExpectedSha256 observed=$observedSha"
            )
        }
        $handle.Position = 0
        Add-NoReparseAncestorLocks -Path $finalPath -Handles $Handles `
            -Seen $SeenAncestors -ErrorCode $ReparseErrorCode
        [void]$Handles.Add($handle)
        $handle = $null
        [pscustomobject]@{
            final_path = [IO.Path]::GetFullPath($finalPath)
            file_identity = $fileIdentity
        }
    }
    catch {
        if ($null -ne $handle) {
            $handle.Dispose()
        } elseif ($null -ne $safeHandle) {
            $safeHandle.Dispose()
        }
        if (
            $_.Exception.Message.StartsWith("${ReparseErrorCode}:", [StringComparison]::Ordinal) -or
            $_.Exception.Message.StartsWith("${HashErrorCode}:", [StringComparison]::Ordinal)
        ) {
            throw
        }
        throw "${HashErrorCode}: path=$Path error=$($_.Exception.Message)"
    }
}

function Get-PhysicalRootForRelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FinalPath,
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $root = [IO.Path]::GetFullPath($FinalPath)
    foreach ($segment in @($RelativePath -split '/' | Where-Object { $_ -ne "" })) {
        $root = Split-Path -Parent $root
    }
    [IO.Path]::GetFullPath($root)
}

function Assert-ExactPhysicalRelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PhysicalRoot,
        [Parameter(Mandatory = $true)]
        [string]$RelativePath,
        [Parameter(Mandatory = $true)]
        [string]$FinalPath,
        [Parameter(Mandatory = $true)]
        [string]$ErrorCode
    )

    $expected = [IO.Path]::GetFullPath(
        (Join-Path $PhysicalRoot ($RelativePath -replace '/', '\'))
    )
    $observed = [IO.Path]::GetFullPath($FinalPath)
    if (-not $expected.Equals($observed, [StringComparison]::OrdinalIgnoreCase)) {
        throw "${ErrorCode}: relative=$RelativePath expected=$expected observed=$observed"
    }
}

function Invoke-HiddenProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
    $startInfo.StandardErrorEncoding = [Text.Encoding]::UTF8
    foreach ($argument in $ArgumentList) {
        [void]$startInfo.ArgumentList.Add([string]$argument)
    }

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "process did not start: $FilePath"
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        [pscustomobject]@{
            ExitCode = $process.ExitCode
            StdOut = $stdoutTask.GetAwaiter().GetResult()
            StdErr = $stderrTask.GetAwaiter().GetResult()
        }
    }
    finally {
        $process.Dispose()
    }
}

function Resolve-BasePython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate
    )

    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        throw "XINAO_SELECTOR_RELEASE_VALIDATOR_PYTHON_MISSING: $Candidate"
    }
    $probe = Invoke-HiddenProcess -FilePath $Candidate -ArgumentList @(
        "-I", "-S", "-B", "-c", "import os,sys; print(os.path.realpath(sys._base_executable))"
    )
    $lines = @(
        $probe.StdOut -split "`r?`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    $basePython = [string]($lines | Select-Object -Last 1)
    if (
        $probe.ExitCode -ne 0 -or
        [string]::IsNullOrWhiteSpace($basePython) -or
        -not [IO.Path]::IsPathFullyQualified($basePython)
    ) {
        throw (
            "XINAO_SELECTOR_RELEASE_VALIDATOR_PYTHON_INVALID: " +
            "exit=$($probe.ExitCode) stdout=$($probe.StdOut.Trim()) stderr=$($probe.StdErr.Trim())"
        )
    }
    $resolved = [IO.Path]::GetFullPath($basePython)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "XINAO_SELECTOR_RELEASE_VALIDATOR_PYTHON_MISSING: $resolved"
    }
    $resolved
}

function Resolve-BaseNode {
    $nodeCommand = Get-Command node.exe -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    $candidate = [string]$nodeCommand.Source
    if (
        [string]::IsNullOrWhiteSpace($candidate) -or
        -not [IO.Path]::IsPathFullyQualified($candidate)
    ) {
        throw "XINAO_QUOTA_NODE_INVALID: native node.exe required"
    }
    $resolved = [IO.Path]::GetFullPath($candidate)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "XINAO_QUOTA_NODE_MISSING: $resolved"
    }
    $resolved
}

$relativeSourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$relativeScript = Join-Path $relativeSourceRoot "scripts\quota_query\Get-AIQuota.ps1"
$relativeValidator = Join-Path $relativeSourceRoot "scripts\build_selector_release.py"
$currentScript = [IO.Path]::GetFullPath($PSCommandPath)
$isRepositoryConsumer = (
    (Test-Path -LiteralPath $relativeScript -PathType Leaf) -and
    (Test-Path -LiteralPath $relativeValidator -PathType Leaf) -and
    [IO.Path]::GetFullPath($relativeScript) -eq $currentScript
)
$trustedCollectorHandles = [Collections.Generic.List[IDisposable]]::new()
$trustedCollectorAncestors = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
if ($isRepositoryConsumer) {
    $collectorPhysical = [IO.Path]::GetFullPath($collector)
    $nodePhysical = Resolve-BaseNode
} else {
    if (
        $installedValidatorBindingSha256 -eq $validatorBindingPlaceholder -or
        $installedValidatorBindingBase64 -eq $validatorBindingBase64Placeholder
    ) {
        throw "XINAO_SELECTOR_VALIDATOR_TRUST_ANCHOR_MISSING: $currentScript"
    }
    try {
        $bindingBytes = [Convert]::FromBase64String($installedValidatorBindingBase64)
    } catch {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: embedded base64"
    }
    $observedBindingSha = Get-Sha256Hex -Bytes $bindingBytes
    if ($observedBindingSha -ne $installedValidatorBindingSha256) {
        throw (
            "XINAO_SELECTOR_VALIDATOR_BINDING_HASH_MISMATCH: " +
            "expected=$installedValidatorBindingSha256 observed=$observedBindingSha"
        )
    }
    try {
        $bindingText = [Text.UTF8Encoding]::new($false, $true).GetString($bindingBytes)
        $binding = $bindingText | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: embedded JSON"
    }
    if ($binding.schema_version -ne "xinao.selector_validator_binding.v2") {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: schema mismatch"
    }
    $collectorBinding = $binding.collector
    $collectorPath = [string]$collectorBinding.path
    if (
        [string]::IsNullOrWhiteSpace($collectorPath) -or
        -not [IO.Path]::IsPathFullyQualified($collectorPath) -or
        [string]$collectorBinding.sha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: collector"
    }
    $collectorLockArguments = @{
        Path = [IO.Path]::GetFullPath($collectorPath)
        ExpectedSha256 = [string]$collectorBinding.sha256
        ExpectedSizeBytes = [long]$collectorBinding.size_bytes
        Handles = $trustedCollectorHandles
        SeenAncestors = $trustedCollectorAncestors
        ReparseErrorCode = "XINAO_QUOTA_COLLECTOR_REPARSE_POINT"
        HashErrorCode = "XINAO_QUOTA_COLLECTOR_HASH_MISMATCH"
    }
    $trustedCollector = Add-HashBoundReadLock @collectorLockArguments
    $collectorPhysical = [string]$trustedCollector.final_path

    $nodeBinding = $binding.node
    $nodePath = [string]$nodeBinding.path
    if (
        [string]::IsNullOrWhiteSpace($nodePath) -or
        -not [IO.Path]::IsPathFullyQualified($nodePath) -or
        [string]$nodeBinding.sha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: node"
    }
    $nodeLockArguments = @{
        Path = [IO.Path]::GetFullPath($nodePath)
        ExpectedSha256 = [string]$nodeBinding.sha256
        ExpectedSizeBytes = [long]$nodeBinding.size_bytes
        Handles = $trustedCollectorHandles
        SeenAncestors = $trustedCollectorAncestors
        ReparseErrorCode = "XINAO_QUOTA_NODE_REPARSE_POINT"
        HashErrorCode = "XINAO_QUOTA_NODE_HASH_MISMATCH"
    }
    $trustedNode = Add-HashBoundReadLock @nodeLockArguments
    $nodePhysical = [string]$trustedNode.final_path
}

# No epoch means an explicit human/live query and preserves the original UX.
if ([string]::IsNullOrWhiteSpace($EpochId)) {
    $arguments = @($collectorPhysical)
    if ($Json) { $arguments += "--json" }
    if ($NoLiveCodex) { $arguments += "--no-live-codex" }
    try {
        $direct = Invoke-HiddenProcess -FilePath $nodePhysical -ArgumentList $arguments
    }
    finally {
        for ($index = $trustedCollectorHandles.Count - 1; $index -ge 0; $index--) {
            $trustedCollectorHandles[$index].Dispose()
        }
        $trustedCollectorHandles.Clear()
    }
    [Console]::Out.Write($direct.StdOut)
    [Console]::Error.Write($direct.StdErr)
    exit $direct.ExitCode
}

$pointer = Join-Path $RuntimeRoot "state\grok_supervisor_selector\current.json"
if (-not (Test-Path -LiteralPath $pointer -PathType Leaf)) {
    throw "XINAO_SELECTOR_RELEASE_POINTER_MISSING: $pointer"
}

# Repository calls trust the selected source tree itself.  Installed calls have
# no source-tree dependency: the embedded binding hash-closes collector, Node,
# and the standard-library validator carrier before any of them execute.
$trustedValidatorHandles = [Collections.Generic.List[IDisposable]]::new()
$trustedValidatorAncestors = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
if ($isRepositoryConsumer) {
    $validatorRoot = $relativeSourceRoot
    $validatorCli = $relativeValidator
    $candidatePython = Join-Path $relativeSourceRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $candidatePython -PathType Leaf)) {
        $pythonCommand = Get-Command python -CommandType Application -ErrorAction Stop |
            Select-Object -First 1
        $candidatePython = [string]$pythonCommand.Source
    }
    $validatorPython = Resolve-BasePython -Candidate $candidatePython
} else {
    $validatorRootText = [string]$binding.validator_root
    if (
        [string]::IsNullOrWhiteSpace($validatorRootText) -or
        -not [IO.Path]::IsPathFullyQualified($validatorRootText)
    ) {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: validator_root"
    }
    $validatorRoot = [IO.Path]::GetFullPath($validatorRootText)
    foreach ($directory in @(
        $validatorRoot,
        (Join-Path $validatorRoot "scripts"),
        (Join-Path $validatorRoot "services"),
        (Join-Path $validatorRoot "services\agent_runtime")
    )) {
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
            throw "XINAO_SELECTOR_VALIDATOR_CLOSURE_MISSING: $directory"
        }
        $directoryItem = Get-Item -LiteralPath $directory -Force
        if (($directoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "XINAO_SELECTOR_VALIDATOR_CLOSURE_REPARSE_POINT: $directory"
        }
    }
    $observedClosure = @(
        Get-ChildItem -LiteralPath $validatorRoot -Recurse -File -Force |
            ForEach-Object {
                [IO.Path]::GetRelativePath($validatorRoot, $_.FullName).Replace('\', '/')
            } |
            Sort-Object
    )
    $expectedClosure = @($validatorClosure | Sort-Object)
    if (($observedClosure -join "`n") -ne ($expectedClosure -join "`n")) {
        throw "XINAO_SELECTOR_VALIDATOR_CLOSURE_UNEXPECTED_FILE"
    }
    $fileRows = @($binding.files)
    if ($fileRows.Count -ne $validatorClosure.Count) {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: closure count"
    }
    $trustedValidatorFinalPaths = @{}
    $physicalValidatorRoot = ""
    for ($index = 0; $index -lt $validatorClosure.Count; $index++) {
        $expectedRelative = $validatorClosure[$index]
        $row = $fileRows[$index]
        if ([string]$row.path -ne $expectedRelative) {
            throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: closure path $index"
        }
        $expectedSha = [string]$row.sha256
        if ($expectedSha -notmatch '^[0-9a-f]{64}$') {
            throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: closure hash $index"
        }
        $target = Join-Path $validatorRoot ($expectedRelative -replace '/', '\')
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
            throw "XINAO_SELECTOR_VALIDATOR_CLOSURE_MISSING: $target"
        }
        $lockArguments = @{
            Path = $target
            ExpectedSha256 = $expectedSha
            ExpectedSizeBytes = [long]$row.size_bytes
            Handles = $trustedValidatorHandles
            SeenAncestors = $trustedValidatorAncestors
            ReparseErrorCode = "XINAO_SELECTOR_VALIDATOR_CLOSURE_REPARSE_POINT"
            HashErrorCode = "XINAO_SELECTOR_VALIDATOR_CLOSURE_HASH_MISMATCH"
        }
        $trustedFile = Add-HashBoundReadLock @lockArguments
        $trustedValidatorFinalPaths[$expectedRelative] = [string]$trustedFile.final_path
        if ($index -eq 0) {
            $physicalValidatorRoot = Get-PhysicalRootForRelativePath `
                -FinalPath $trustedFile.final_path -RelativePath $expectedRelative
        }
        Assert-ExactPhysicalRelativePath -PhysicalRoot $physicalValidatorRoot `
            -RelativePath $expectedRelative -FinalPath $trustedFile.final_path `
            -ErrorCode "XINAO_SELECTOR_VALIDATOR_CLOSURE_ROOT_MISMATCH"
    }
    $validatorCli = [string]$trustedValidatorFinalPaths["scripts/build_selector_release.py"]
    $validatorPythonText = [string]$binding.python_executable
    if (
        [string]::IsNullOrWhiteSpace($validatorPythonText) -or
        -not [IO.Path]::IsPathFullyQualified($validatorPythonText)
    ) {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: python_executable"
    }
    $validatorPython = [IO.Path]::GetFullPath($validatorPythonText)
    if (-not (Test-Path -LiteralPath $validatorPython -PathType Leaf)) {
        throw "XINAO_SELECTOR_RELEASE_VALIDATOR_PYTHON_MISSING: $validatorPython"
    }
    $expectedPythonSha = [string]$binding.python_sha256
    if ($expectedPythonSha -notmatch '^[0-9a-f]{64}$') {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: python_sha256"
    }
    $pythonLockArguments = @{
        Path = $validatorPython
        ExpectedSha256 = $expectedPythonSha
        ExpectedSizeBytes = [long]$binding.python_size_bytes
        Handles = $trustedValidatorHandles
        SeenAncestors = $trustedValidatorAncestors
        ReparseErrorCode = "XINAO_SELECTOR_VALIDATOR_PYTHON_REPARSE_POINT"
        HashErrorCode = "XINAO_SELECTOR_VALIDATOR_PYTHON_HASH_MISMATCH"
    }
    $trustedPython = Add-HashBoundReadLock @pythonLockArguments
    $validatorPython = [string]$trustedPython.final_path
}

try {
    $validation = Invoke-HiddenProcess -FilePath $validatorPython -ArgumentList @(
        "-I", "-S", "-B", $validatorCli,
        "--runtime-root", $RuntimeRoot,
        "--show-current"
    )
} catch {
    throw "XINAO_SELECTOR_RELEASE_VALIDATION_FAILED: verifier launch failed: $($_.Exception.Message)"
} finally {
    for ($index = $trustedValidatorHandles.Count - 1; $index -ge 0; $index--) {
        $trustedValidatorHandles[$index].Dispose()
    }
    $trustedValidatorHandles.Clear()
}
$validationLines = @(
    $validation.StdOut -split "`r?`n" |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
$validationLast = $validationLines | Select-Object -Last 1
if ($validation.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($validationLast)) {
    throw (
        "XINAO_SELECTOR_RELEASE_VALIDATION_FAILED: " +
        "exit=$($validation.ExitCode) stdout=$($validation.StdOut.Trim()) " +
        "stderr=$($validation.StdErr.Trim())"
    )
}
try {
    $validatedRelease = $validationLast | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw "XINAO_SELECTOR_RELEASE_VALIDATION_FAILED: validator output was not JSON"
}
$releaseRoot = [string]$validatedRelease.release_root
$python = [string]$validatedRelease.python_executable
$validatedPointer = [string]$validatedRelease.pointer_path
$executionBinding = $validatedRelease.execution_binding
if (
    [string]::IsNullOrWhiteSpace($releaseRoot) -or
    [string]::IsNullOrWhiteSpace($python) -or
    [string]::IsNullOrWhiteSpace($validatedPointer) -or
    [IO.Path]::GetFullPath($validatedPointer) -ne [IO.Path]::GetFullPath($pointer)
) {
    throw "XINAO_SELECTOR_RELEASE_VALIDATION_FAILED: validated identity incomplete"
}
if (
    $null -eq $executionBinding -or
    [string]$executionBinding.schema_version -ne "xinao.selector_release_execution_binding.v1" -or
    -not ([IO.Path]::GetFullPath([string]$executionBinding.release_root)).Equals(
        [IO.Path]::GetFullPath($releaseRoot),
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "XINAO_SELECTOR_RELEASE_EXECUTION_BINDING_INVALID: identity"
}
$releaseFileRows = @($executionBinding.files)
if ($releaseFileRows.Count -eq 0) {
    throw "XINAO_SELECTOR_RELEASE_EXECUTION_BINDING_INVALID: empty closure"
}
$collectorArgs = @($nodePhysical, $collectorPhysical, "--json")
if ($NoLiveCodex) { $collectorArgs += "--no-live-codex" }
$trustedReleaseHandles = [Collections.Generic.List[IDisposable]]::new()
$trustedReleaseAncestors = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
$trustedReleaseFinalPaths = @{}
$releasePathsSeen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
$physicalReleaseRoot = ""
try {
    for ($index = 0; $index -lt $releaseFileRows.Count; $index++) {
        $row = $releaseFileRows[$index]
        $relativePath = [string]$row.path
        if (
            [string]::IsNullOrWhiteSpace($relativePath) -or
            [IO.Path]::IsPathFullyQualified($relativePath) -or
            @($relativePath -split '/' | Where-Object { $_ -eq ".." }).Count -ne 0 -or
            -not $releasePathsSeen.Add($relativePath)
        ) {
            throw "XINAO_SELECTOR_RELEASE_EXECUTION_BINDING_INVALID: path=$relativePath"
        }
        $expectedSha = [string]$row.sha256
        if ($expectedSha -notmatch '^[0-9a-f]{64}$' -or [long]$row.size_bytes -lt 0) {
            throw "XINAO_SELECTOR_RELEASE_EXECUTION_BINDING_INVALID: identity=$relativePath"
        }
        $target = Join-Path $releaseRoot ($relativePath -replace '/', '\')
        $releaseLockArguments = @{
            Path = $target
            ExpectedSha256 = $expectedSha
            ExpectedSizeBytes = [long]$row.size_bytes
            Handles = $trustedReleaseHandles
            SeenAncestors = $trustedReleaseAncestors
            ReparseErrorCode = "XINAO_SELECTOR_RELEASE_EXECUTION_REPARSE_POINT"
            HashErrorCode = "XINAO_SELECTOR_RELEASE_EXECUTION_HASH_MISMATCH"
        }
        $trustedFile = Add-HashBoundReadLock @releaseLockArguments
        $trustedReleaseFinalPaths[$relativePath] = [string]$trustedFile.final_path
        if ($index -eq 0) {
            $physicalReleaseRoot = Get-PhysicalRootForRelativePath `
                -FinalPath $trustedFile.final_path -RelativePath $relativePath
        }
        Assert-ExactPhysicalRelativePath -PhysicalRoot $physicalReleaseRoot `
            -RelativePath $relativePath -FinalPath $trustedFile.final_path `
            -ErrorCode "XINAO_SELECTOR_RELEASE_EXECUTION_ROOT_MISMATCH"
    }
    $epochRelativePath = "scripts/quota_dispatch_epoch.py"
    if (-not $trustedReleaseFinalPaths.ContainsKey($epochRelativePath)) {
        throw "XINAO_SELECTOR_RELEASE_EXECUTION_BINDING_INVALID: epoch missing"
    }
    $pythonBinding = $executionBinding.python
    if (
        $null -eq $pythonBinding -or
        [string]$pythonBinding.path -ne $python -or
        [string]$pythonBinding.sha256 -notmatch '^[0-9a-f]{64}$' -or
        [long]$pythonBinding.size_bytes -lt 0
    ) {
        throw "XINAO_SELECTOR_RELEASE_EXECUTION_BINDING_INVALID: python"
    }
    $releasePythonLockArguments = @{
        Path = $python
        ExpectedSha256 = [string]$pythonBinding.sha256
        ExpectedSizeBytes = [long]$pythonBinding.size_bytes
        Handles = $trustedReleaseHandles
        SeenAncestors = $trustedReleaseAncestors
        ReparseErrorCode = "XINAO_SELECTOR_RELEASE_PYTHON_REPARSE_POINT"
        HashErrorCode = "XINAO_SELECTOR_RELEASE_PYTHON_HASH_MISMATCH"
    }
    $trustedReleasePython = Add-HashBoundReadLock @releasePythonLockArguments
    $physicalPython = [string]$trustedReleasePython.final_path
    $relativePython = [IO.Path]::GetRelativePath($releaseRoot, $python)
    if (
        -not [IO.Path]::IsPathFullyQualified($relativePython) -and
        -not $relativePython.StartsWith(".." + [IO.Path]::DirectorySeparatorChar) -and
        $relativePython -ne ".."
    ) {
        Assert-ExactPhysicalRelativePath -PhysicalRoot $physicalReleaseRoot `
            -RelativePath ($relativePython -replace '\\', '/') `
            -FinalPath $physicalPython `
            -ErrorCode "XINAO_SELECTOR_RELEASE_PYTHON_ROOT_MISMATCH"
    }
    $epochScript = [string]$trustedReleaseFinalPaths[$epochRelativePath]
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
    $epoch = Invoke-HiddenProcess -FilePath $physicalPython -ArgumentList $arguments
}
finally {
    for ($index = $trustedReleaseHandles.Count - 1; $index -ge 0; $index--) {
        $trustedReleaseHandles[$index].Dispose()
    }
    $trustedReleaseHandles.Clear()
    for ($index = $trustedCollectorHandles.Count - 1; $index -ge 0; $index--) {
        $trustedCollectorHandles[$index].Dispose()
    }
    $trustedCollectorHandles.Clear()
}
if ($epoch.ExitCode -ne 0) {
    throw (
        "XINAO_QUOTA_EPOCH_QUERY_FAILED: exit=$($epoch.ExitCode) " +
        "stdout=$($epoch.StdOut.Trim()) stderr=$($epoch.StdErr.Trim())"
    )
}
$lines = @($epoch.StdOut -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
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
