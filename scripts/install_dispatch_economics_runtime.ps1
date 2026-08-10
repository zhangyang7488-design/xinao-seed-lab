#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false, $true)
$bindingPlaceholder = "__XINAO_SELECTOR_VALIDATOR_BINDING_SHA256__"
$validatorClosure = @(
    "scripts/build_selector_release.py",
    "services/__init__.py",
    "services/agent_runtime/__init__.py",
    "services/agent_runtime/selector_release.py"
)
$sourceRootFull = [IO.Path]::GetFullPath($SourceRoot)
$source = Join-Path $sourceRootFull "scripts\quota_query\Get-AIQuota.ps1"
$targetDirectory = Join-Path $RuntimeRoot "state\quota_query"
$target = Join-Path $targetDirectory "Get-AIQuota.ps1"
$validatorBinding = Join-Path $targetDirectory "selector-validator-root.txt"
$releaseParent = Join-Path $RuntimeRoot "state\quota_query_releases"

function Get-Sha256Hex {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes
    )

    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
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
        [string]$Root
    )

    $candidate = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        $pythonCommand = Get-Command python -CommandType Application -ErrorAction Stop |
            Select-Object -First 1
        $candidate = [string]$pythonCommand.Source
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "XINAO_SELECTOR_RELEASE_VALIDATOR_PYTHON_MISSING: $candidate"
    }
    $lines = @(& $candidate -I -S -B -c "import os,sys; print(os.path.realpath(sys._base_executable))" 2>&1 |
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
    $resolved = [IO.Path]::GetFullPath($basePython)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "XINAO_SELECTOR_RELEASE_VALIDATOR_PYTHON_MISSING: $resolved"
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
            return [IO.FileStream]::new(
                $Path,
                [IO.FileMode]::OpenOrCreate,
                [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None
            )
        }
        catch [IO.IOException] {
            $nativeCode = $_.Exception.HResult -band 0xFFFF
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

if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "XINAO_QUOTA_EPOCH_SOURCE_MISSING: $source"
}
if (-not (Test-Path -LiteralPath (Join-Path $targetDirectory "quota-query.mjs") -PathType Leaf)) {
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
$placeholderMatches = [regex]::Matches($sourceText, [regex]::Escape($bindingPlaceholder)).Count
if ($placeholderMatches -ne 1) {
    throw "XINAO_SELECTOR_VALIDATOR_TRUST_ANCHOR_INVALID: count=$placeholderMatches"
}
$validatorPython = Resolve-BasePython -Root $sourceRootFull
$validatorPythonBytes = [IO.File]::ReadAllBytes($validatorPython)
$validatorPythonSha = Get-Sha256Hex -Bytes $validatorPythonBytes
$capturedValidatorBytes = [ordered]@{}
foreach ($relativeText in $validatorClosure) {
    $origin = Join-Path $sourceRootFull ($relativeText -replace '/', '\')
    $capturedValidatorBytes[$relativeText] = [IO.File]::ReadAllBytes($origin)
}

$installLockPath = Join-Path $targetDirectory ".install.lock"
$installLock = Enter-QuotaInstallLock -Path $installLockPath
try {
$previousTargetExisted = Test-Path -LiteralPath $target -PathType Leaf
$previousBindingExisted = Test-Path -LiteralPath $validatorBinding -PathType Leaf
$previousTargetBytes = if ($previousTargetExisted) { [IO.File]::ReadAllBytes($target) } else { $null }
$previousBindingBytes = if ($previousBindingExisted) {
    [IO.File]::ReadAllBytes($validatorBinding)
} else {
    $null
}
$previousSha = if ($previousTargetExisted) { Get-Sha256Hex -Bytes $previousTargetBytes } else { "" }
$previousBindingSha = if ($previousBindingExisted) {
    Get-Sha256Hex -Bytes $previousBindingBytes
} else {
    ""
}

$releaseId = (
    "quota-validator-" + (Get-Date -Format "yyyyMMddTHHmmssfff") + "-" +
    $sourceSha.Substring(0, 12) + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
)
$releaseRoot = Join-Path $releaseParent $releaseId
$validatorRoot = Join-Path $releaseRoot "validator"
$backup = ""
$bindingBackup = ""
$targetTemporary = $target + "." + [guid]::NewGuid().ToString("N") + ".tmp"
$bindingTemporary = $validatorBinding + "." + [guid]::NewGuid().ToString("N") + ".tmp"
$receiptPath = Join-Path $releaseRoot "install-receipt.json"
$receiptTemporary = $receiptPath + "." + [guid]::NewGuid().ToString("N") + ".tmp"
$releaseCreated = $false
$bindingPublished = $false
$targetPublished = $false
$rollbackSucceeded = $false
try {
    New-Item -ItemType Directory -Path $validatorRoot -ErrorAction Stop | Out-Null
    $releaseCreated = $true
    if ($previousTargetExisted) {
        $backup = Join-Path $releaseRoot "previous.Get-AIQuota.ps1"
        [IO.File]::WriteAllBytes($backup, $previousTargetBytes)
    }
    if ($previousBindingExisted) {
        $bindingBackup = Join-Path $releaseRoot "previous.selector-validator-root.txt"
        [IO.File]::WriteAllBytes($bindingBackup, $previousBindingBytes)
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
        schema_version = "xinao.selector_validator_binding.v1"
        validator_root = [IO.Path]::GetFullPath($validatorRoot)
        files = $validatorRows
        python_executable = $validatorPython
        python_sha256 = $validatorPythonSha
        python_size_bytes = $validatorPythonBytes.Length
        authority = $false
        completion_claim_allowed = $false
    }
    $bindingBytes = $utf8.GetBytes(($bindingPayload | ConvertTo-Json -Depth 8 -Compress) + "`n")
    $bindingSha = Get-Sha256Hex -Bytes $bindingBytes
    $installedText = $sourceText.Replace($bindingPlaceholder, $bindingSha)
    if ($installedText.Contains($bindingPlaceholder)) {
        throw "XINAO_SELECTOR_VALIDATOR_TRUST_ANCHOR_INJECTION_FAILED"
    }
    $installedBytes = $utf8.GetBytes($installedText)
    $installedSha = Get-Sha256Hex -Bytes $installedBytes
    [IO.File]::WriteAllBytes($targetTemporary, $installedBytes)
    [IO.File]::WriteAllBytes($bindingTemporary, $bindingBytes)
    if (
        (Get-Sha256Hex -Bytes ([IO.File]::ReadAllBytes($targetTemporary))) -ne $installedSha -or
        (Get-Sha256Hex -Bytes ([IO.File]::ReadAllBytes($bindingTemporary))) -ne $bindingSha
    ) {
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
    if (
        -not (Test-ExactInstalledState -Path $target -ExpectedPresent $previousTargetExisted -ExpectedBytes $previousTargetBytes) -or
        -not (Test-ExactInstalledState -Path $validatorBinding -ExpectedPresent $previousBindingExisted -ExpectedBytes $previousBindingBytes)
    ) {
        throw "XINAO_QUOTA_INSTALL_TARGET_CHANGED_BEFORE_PUBLISH"
    }

    # Publish the locator first.  Until the consumer swap completes, the old
    # embedded anchor rejects it, so concurrent reads fail closed rather than
    # executing a mismatched validator.
    Move-Item -LiteralPath $bindingTemporary -Destination $validatorBinding -Force
    $bindingPublished = $true
    Move-Item -LiteralPath $targetTemporary -Destination $target -Force
    $targetPublished = $true
    if (-not (Test-ExactInstalledState -Path $validatorBinding -ExpectedPresent $true -ExpectedBytes $bindingBytes)) {
        throw "XINAO_SELECTOR_VALIDATOR_BINDING_INSTALL_MISMATCH"
    }
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

    $receipt = [ordered]@{
        schema_version = "xinao.dispatch_economics_runtime_install_receipt.v2"
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
        validator_binding_ref = [IO.Path]::GetFullPath($validatorBinding)
        validator_binding_sha256 = $bindingSha
        validator_root_binding_ref = [IO.Path]::GetFullPath($validatorBinding)
        validator_root_binding_sha256 = $bindingSha
        target_ref = [IO.Path]::GetFullPath($target)
        target_sha256 = $installedSha
        previous_sha256 = $previousSha
        rollback_ref = $backup
        previous_validator_binding_sha256 = $previousBindingSha
        rollback_validator_binding_ref = $bindingBackup
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
        -not (Test-ExactInstalledState -Path $validatorBinding -ExpectedPresent $true -ExpectedBytes $bindingBytes)
    ) {
        throw "XINAO_QUOTA_INSTALL_FINAL_PAIR_READBACK_MISMATCH"
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
        if ($bindingPublished) {
            if (-not (Test-ExactInstalledState -Path $validatorBinding -ExpectedPresent $true -ExpectedBytes $bindingBytes)) {
                throw "validator binding changed before rollback: $validatorBinding"
            }
        }
        if ($targetPublished) {
            Restore-InstalledFile -TargetPath $target -PreviouslyExisted $previousTargetExisted -PreviousBytes $previousTargetBytes
        }
        if ($bindingPublished) {
            Restore-InstalledFile -TargetPath $validatorBinding -PreviouslyExisted $previousBindingExisted -PreviousBytes $previousBindingBytes
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
    Remove-Item -LiteralPath $bindingTemporary -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $receiptTemporary -Force -ErrorAction SilentlyContinue
}
$receipt | ConvertTo-Json -Depth 8
}
finally {
    $installLock.Dispose()
}
