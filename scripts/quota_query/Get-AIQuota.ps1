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
$validatorBindingPlaceholder = "__XINAO_" + "SELECTOR_VALIDATOR_BINDING_SHA256__"
$validatorBindingName = "selector-validator-root.txt"
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
        [Collections.Generic.List[IDisposable]]$Handles
    )

    $handle = [IO.FileStream]::new(
        $Path,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read
    )
    try {
        $hasher = [Security.Cryptography.SHA256]::Create()
        try {
            $observedSha = [Convert]::ToHexString($hasher.ComputeHash($handle)).ToLowerInvariant()
        }
        finally {
            $hasher.Dispose()
        }
        if ($handle.Length -ne $ExpectedSizeBytes -or $observedSha -ne $ExpectedSha256) {
            throw (
                "hash-bound read lock mismatch: path=$Path " +
                "expected=$ExpectedSha256 observed=$observedSha"
            )
        }
        $handle.Position = 0
        [void]$Handles.Add($handle)
    }
    catch {
        $handle.Dispose()
        throw
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

# Repository calls trust the selected source tree itself.  Installed calls have
# no source-tree dependency: the installer injects the exact binding-file hash
# into these trusted consumer bytes, and that binding hash-closes the complete
# standard-library validator carrier before any carrier Python is executed.
$relativeSourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$relativeScript = Join-Path $relativeSourceRoot "scripts\quota_query\Get-AIQuota.ps1"
$relativeValidator = Join-Path $relativeSourceRoot "scripts\build_selector_release.py"
$currentScript = [IO.Path]::GetFullPath($PSCommandPath)
$trustedValidatorHandles = [Collections.Generic.List[IDisposable]]::new()
if (
    (Test-Path -LiteralPath $relativeScript -PathType Leaf) -and
    (Test-Path -LiteralPath $relativeValidator -PathType Leaf) -and
    [IO.Path]::GetFullPath($relativeScript) -eq $currentScript
) {
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
    if ($installedValidatorBindingSha256 -eq $validatorBindingPlaceholder) {
        throw "XINAO_SELECTOR_VALIDATOR_TRUST_ANCHOR_MISSING: $currentScript"
    }
    $bindingPath = Join-Path $PSScriptRoot $validatorBindingName
    if (-not (Test-Path -LiteralPath $bindingPath -PathType Leaf)) {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_MISSING: $bindingPath"
    }
    $bindingBytes = [IO.File]::ReadAllBytes($bindingPath)
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
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: $bindingPath"
    }
    if ($binding.schema_version -ne "xinao.selector_validator_binding.v1") {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: schema mismatch"
    }
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
        $targetItem = Get-Item -LiteralPath $target -Force
        if (($targetItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "XINAO_SELECTOR_VALIDATOR_CLOSURE_REPARSE_POINT: $target"
        }
        try {
            $lockArguments = @{
                Path = $target
                ExpectedSha256 = $expectedSha
                ExpectedSizeBytes = [long]$row.size_bytes
                Handles = $trustedValidatorHandles
            }
            Add-HashBoundReadLock @lockArguments
            $targetItemAfterLock = Get-Item -LiteralPath $target -Force
            if (
                ($targetItemAfterLock.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
            ) {
                throw "XINAO_SELECTOR_VALIDATOR_CLOSURE_REPARSE_POINT: $target"
            }
        }
        catch {
            throw (
                "XINAO_SELECTOR_VALIDATOR_CLOSURE_HASH_MISMATCH: " +
                "path=$expectedRelative error=$($_.Exception.Message)"
            )
        }
    }
    $validatorCli = Join-Path $validatorRoot "scripts\build_selector_release.py"
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
    $validatorPythonItem = Get-Item -LiteralPath $validatorPython -Force
    if (($validatorPythonItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "XINAO_SELECTOR_VALIDATOR_PYTHON_REPARSE_POINT: $validatorPython"
    }
    $expectedPythonSha = [string]$binding.python_sha256
    if ($expectedPythonSha -notmatch '^[0-9a-f]{64}$') {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: python_sha256"
    }
    try {
        $pythonLockArguments = @{
            Path = $validatorPython
            ExpectedSha256 = $expectedPythonSha
            ExpectedSizeBytes = [long]$binding.python_size_bytes
            Handles = $trustedValidatorHandles
        }
        Add-HashBoundReadLock @pythonLockArguments
        $validatorPythonItemAfterLock = Get-Item -LiteralPath $validatorPython -Force
        if (
            ($validatorPythonItemAfterLock.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "XINAO_SELECTOR_VALIDATOR_PYTHON_REPARSE_POINT: $validatorPython"
        }
    }
    catch {
        throw (
            "XINAO_SELECTOR_VALIDATOR_PYTHON_HASH_MISMATCH: " +
            "error=$($_.Exception.Message)"
        )
    }
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
if (
    [string]::IsNullOrWhiteSpace($releaseRoot) -or
    [string]::IsNullOrWhiteSpace($python) -or
    [string]::IsNullOrWhiteSpace($validatedPointer) -or
    [IO.Path]::GetFullPath($validatedPointer) -ne [IO.Path]::GetFullPath($pointer)
) {
    throw "XINAO_SELECTOR_RELEASE_VALIDATION_FAILED: validated identity incomplete"
}
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
