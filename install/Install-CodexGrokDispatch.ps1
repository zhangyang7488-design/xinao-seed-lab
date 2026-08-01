#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$TargetLauncher = "C:\Users\xx363\CodexLaunchers\Invoke-Codex-GrokWorkerPool.ps1",
    [string]$TargetBridgeRoot = "C:\Users\xx363\Grok_Admin_Isolated\workspace\grok-admin-bridge",
    [string]$AuthProfileRoot = "C:\Users\xx363\.grok-bg-workers"
)

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false)

function Get-Sha256Lower([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-PowerShellSource([string]$Path) {
    $tokens = $null
    $errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    if (@($errors).Count -gt 0) {
        throw "CODEX_GROK_INSTALL_SOURCE_PARSE_FAILED: $Path :: $($errors -join '; ')"
    }
}

function Write-AtomicFileFromSource([string]$Source, [string]$Target, [string]$ExpectedSha256) {
    $parent = Split-Path -Parent $Target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = $Target + "." + [guid]::NewGuid().ToString("N") + ".tmp"
    try {
        [IO.File]::WriteAllBytes($temporary, [IO.File]::ReadAllBytes($Source))
        if ((Get-Sha256Lower $temporary) -ne $ExpectedSha256) {
            throw "CODEX_GROK_INSTALL_STAGING_HASH_MISMATCH: $Target"
        }
        Move-Item -LiteralPath $temporary -Destination $Target -Force
    }
    finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$TargetLauncher = [IO.Path]::GetFullPath($TargetLauncher)
$TargetBridgeRoot = [IO.Path]::GetFullPath($TargetBridgeRoot)
$AuthProfileRoot = [IO.Path]::GetFullPath($AuthProfileRoot)

$sourceLauncher = Join-Path $SourceRoot "launchers\Invoke-Codex-GrokWorkerPool.ps1"
$sourceRollback = Join-Path $SourceRoot "install\Restore-CodexGrokDispatch.ps1"
$runtimeRelativeFiles = @(
    "GrokAuthenticatedCatalogTime.ps1",
    "GrokAuthenticatedCatalogRefresh.ps1",
    "Invoke-CodexDispatchGrokWorkerPool.ps1",
    "Invoke-GrokComposer25Worker.ps1"
)
$requiredTargetDependencies = @(
    "GrokWindowsPathIdentity.ps1",
    "GrokWorkerProcessRuntime.ps1",
    "Invoke-GrokWorkerPool.ps1",
    "GrokWorkerSelectionReceipt.ps1",
    "resolve_grok_worker_selection_receipt.py",
    "GrokSupervisorRootCapability.ps1",
    "Test-GrokCliEffectiveOutput.ps1"
)

$sourcePaths = @($sourceLauncher, $sourceRollback) + @(
    $runtimeRelativeFiles | ForEach-Object { Join-Path $SourceRoot ("grok-admin-bridge\" + $_) }
)
foreach ($sourcePath in $sourcePaths) {
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "CODEX_GROK_INSTALL_SOURCE_MISSING: $sourcePath"
    }
    if ([IO.Path]::GetExtension($sourcePath) -ieq ".ps1") {
        Assert-PowerShellSource $sourcePath
    }
}

$runtimeSourceHashes = [ordered]@{}
foreach ($relative in $runtimeRelativeFiles) {
    $runtimeSourceHashes[$relative] = Get-Sha256Lower (Join-Path $SourceRoot ("grok-admin-bridge\" + $relative))
}
$closureJson = $runtimeSourceHashes | ConvertTo-Json -Compress
$closureSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($utf8.GetBytes($closureJson))
).ToLowerInvariant()
$launcherSha256 = Get-Sha256Lower $sourceLauncher
$rollbackScriptSha256 = Get-Sha256Lower $sourceRollback
$releaseId = "dispatch-" + (Get-Date -Format "yyyyMMddTHHmmssfff") + "-" + $closureSha256.Substring(0, 12)
$releaseBase = Join-Path $RuntimeRoot "state\codex_grok_dispatch_releases"
$releaseRoot = Join-Path $releaseBase $releaseId
$rollbackRoot = Join-Path $releaseRoot "rollback"
New-Item -ItemType Directory -Path $rollbackRoot -ErrorAction Stop | Out-Null

$installedRollbackScript = Join-Path $releaseRoot "Restore-CodexGrokDispatch.ps1"
[IO.File]::WriteAllBytes($installedRollbackScript, [IO.File]::ReadAllBytes($sourceRollback))
if ((Get-Sha256Lower $installedRollbackScript) -ne $rollbackScriptSha256) {
    throw "CODEX_GROK_ROLLBACK_SCRIPT_INSTALL_HASH_MISMATCH"
}

$installSpecs = [Collections.Generic.List[object]]::new()
$promotionOrder = 0
foreach ($relative in $runtimeRelativeFiles) {
    $promotionOrder += 1
    $installSpecs.Add([pscustomobject][ordered]@{
        role = "runtime_bridge"
        relative_ref = $relative
        source_ref = Join-Path $SourceRoot ("grok-admin-bridge\" + $relative)
        source_sha256 = [string]$runtimeSourceHashes[$relative]
        target_ref = Join-Path $TargetBridgeRoot $relative
        promotion_order = $promotionOrder
    })
}
$promotionOrder += 1
$installSpecs.Add([pscustomobject][ordered]@{
    role = "public_launcher"
    relative_ref = "Invoke-Codex-GrokWorkerPool.ps1"
    source_ref = $sourceLauncher
    source_sha256 = $launcherSha256
    target_ref = $TargetLauncher
    promotion_order = $promotionOrder
})

$prepared = [Collections.Generic.List[object]]::new()
foreach ($spec in $installSpecs) {
    $target = [IO.Path]::GetFullPath([string]$spec.target_ref)
    $targetParent = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
    $previousExists = Test-Path -LiteralPath $target -PathType Leaf
    $previousSha256 = ""
    $rollbackRef = ""
    if ($previousExists) {
        $previousSha256 = Get-Sha256Lower $target
        $rollbackRef = Join-Path $rollbackRoot (("{0:D2}-" -f [int]$spec.promotion_order) + [IO.Path]::GetFileName($target))
        [IO.File]::WriteAllBytes($rollbackRef, [IO.File]::ReadAllBytes($target))
        if ((Get-Sha256Lower $rollbackRef) -ne $previousSha256) {
            throw "CODEX_GROK_ROLLBACK_BACKUP_HASH_MISMATCH: $target"
        }
    }
    $stageRef = $target + "." + $releaseId + ".stage"
    [IO.File]::WriteAllBytes($stageRef, [IO.File]::ReadAllBytes([string]$spec.source_ref))
    if ((Get-Sha256Lower $stageRef) -ne [string]$spec.source_sha256) {
        throw "CODEX_GROK_INSTALL_STAGING_HASH_MISMATCH: $target"
    }
    $prepared.Add([pscustomobject][ordered]@{
        role = [string]$spec.role
        relative_ref = [string]$spec.relative_ref
        source_ref = [IO.Path]::GetFullPath([string]$spec.source_ref)
        source_sha256 = [string]$spec.source_sha256
        target_ref = $target
        installed_sha256 = [string]$spec.source_sha256
        previous_exists = [bool]$previousExists
        previous_sha256 = $previousSha256
        rollback_ref = $rollbackRef
        stage_ref = $stageRef
        promotion_order = [int]$spec.promotion_order
    })
}

$pointerPath = Join-Path $releaseBase "current.json"
$previousPointerExists = Test-Path -LiteralPath $pointerPath -PathType Leaf
$previousPointerSha256 = ""
$previousPointerBackup = ""
if ($previousPointerExists) {
    $previousPointerSha256 = Get-Sha256Lower $pointerPath
    $previousPointerBackup = Join-Path $rollbackRoot "previous.current.json"
    [IO.File]::WriteAllBytes($previousPointerBackup, [IO.File]::ReadAllBytes($pointerPath))
    if ((Get-Sha256Lower $previousPointerBackup) -ne $previousPointerSha256) {
        throw "CODEX_GROK_PREVIOUS_POINTER_BACKUP_HASH_MISMATCH"
    }
}

$promoted = [Collections.Generic.List[object]]::new()
$receiptPath = Join-Path $releaseRoot "install-receipt.json"
try {
    foreach ($item in @($prepared | Sort-Object promotion_order)) {
        Move-Item -LiteralPath $item.stage_ref -Destination $item.target_ref -Force
        if ((Get-Sha256Lower $item.target_ref) -ne [string]$item.installed_sha256) {
            throw "CODEX_GROK_INSTALL_READBACK_HASH_MISMATCH: $($item.target_ref)"
        }
        $promoted.Add($item)
    }

    $dependencyHashes = [ordered]@{}
    foreach ($relative in $requiredTargetDependencies) {
        $dependencyPath = Join-Path $TargetBridgeRoot $relative
        if (-not (Test-Path -LiteralPath $dependencyPath -PathType Leaf)) {
            throw "CODEX_GROK_TARGET_DEPENDENCY_MISSING: $dependencyPath"
        }
        if ([IO.Path]::GetExtension($dependencyPath) -ieq ".ps1") {
            Assert-PowerShellSource $dependencyPath
        }
        $dependencyHashes[$relative] = Get-Sha256Lower $dependencyPath
    }

    $authPath = Join-Path $AuthProfileRoot "auth.json"
    $authPresent = $false
    try {
        $authPresent = (
            (Test-Path -LiteralPath $authPath -PathType Leaf) -and
            (Get-Item -LiteralPath $authPath -Force -ErrorAction Stop).Length -gt 0
        )
    }
    catch { $authPresent = $false }

    $sourceGitHead = @(& git -C $SourceRoot rev-parse HEAD 2>$null | Select-Object -First 1)
    if (@($sourceGitHead).Count -ne 1 -or [string]$sourceGitHead[0] -notmatch '^[0-9a-fA-F]{40}$') {
        throw "CODEX_GROK_INSTALL_SOURCE_GIT_IDENTITY_UNAVAILABLE"
    }
    $receiptItems = @($prepared | Sort-Object promotion_order | ForEach-Object {
        [ordered]@{
            role = $_.role
            relative_ref = $_.relative_ref
            source_ref = $_.source_ref
            source_sha256 = $_.source_sha256
            target_ref = $_.target_ref
            installed_sha256 = $_.installed_sha256
            previous_exists = $_.previous_exists
            previous_sha256 = $_.previous_sha256
            rollback_ref = $_.rollback_ref
            promotion_order = $_.promotion_order
        }
    })
    $receipt = [ordered]@{
        schema_version = "xinao.codex_grok_dispatch_install_receipt.v2"
        installed_at = (Get-Date).ToUniversalTime().ToString("o")
        release_id = $releaseId
        source_root = $SourceRoot
        source_git_head = [string]$sourceGitHead[0]
        target_bridge_root = $TargetBridgeRoot
        bridge_closure_sha256 = $closureSha256
        bridge_runtime_files = $runtimeSourceHashes
        target_dependency_hashes = $dependencyHashes
        install_items = $receiptItems
        auth_profile_root = $AuthProfileRoot
        auth_state = if ($authPresent) { "present_nonempty" } else { "login_required" }
        auth_present = [bool]$authPresent
        auth_bytes_read = $false
        auth_copied_or_backed_up = $false
        catalog_is_auth_proof = $false
        rollback_script_ref = $installedRollbackScript
        rollback_script_sha256 = $rollbackScriptSha256
        release_pointer_ref = $pointerPath
        previous_pointer_exists = [bool]$previousPointerExists
        previous_pointer_sha256 = $previousPointerSha256
        previous_pointer_rollback_ref = $previousPointerBackup
        dispatch_epoch_policy = "stable_episode_identity_plus_s_quota_dispatch_epoch"
        unscoped_ordinary_mode = "fail_closed_before_provider"
        package_epoch_policy = "exact_neutral_manifest_epoch_reseal_on_expiry"
        exact_prior_reuse_policy = "local_classification_before_provider_auth_zero_refresh_zero_worker_zero_tokens"
        authority = $false
        completion_claim_allowed = $false
    }
    [IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 10), $utf8)
    $receiptSha256 = Get-Sha256Lower $receiptPath
    $pointer = [ordered]@{
        schema_version = "xinao.codex_grok_dispatch_release_pointer.v2"
        release_id = $releaseId
        install_receipt_ref = $receiptPath
        install_receipt_sha256 = $receiptSha256
        source_git_head = [string]$sourceGitHead[0]
        bridge_closure_sha256 = $closureSha256
        target_bridge_root = $TargetBridgeRoot
        authority = $false
        completion_claim_allowed = $false
    }
    New-Item -ItemType Directory -Path $releaseBase -Force | Out-Null
    $pointerTemporary = $pointerPath + "." + [guid]::NewGuid().ToString("N") + ".tmp"
    try {
        [IO.File]::WriteAllText($pointerTemporary, ($pointer | ConvertTo-Json -Depth 8), $utf8)
        Move-Item -LiteralPath $pointerTemporary -Destination $pointerPath -Force
    }
    finally {
        Remove-Item -LiteralPath $pointerTemporary -Force -ErrorAction SilentlyContinue
    }
    $pointerReadback = Get-Content -LiteralPath $pointerPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
    if ([string]$pointerReadback.release_id -ne $releaseId -or
        [string]$pointerReadback.install_receipt_sha256 -ne $receiptSha256) {
        throw "CODEX_GROK_RELEASE_POINTER_READBACK_MISMATCH"
    }

    $receipt | Add-Member -NotePropertyName receipt_ref -NotePropertyValue $receiptPath
    $receipt | Add-Member -NotePropertyName receipt_sha256 -NotePropertyValue $receiptSha256
    $receipt | Add-Member -NotePropertyName release_pointer_sha256 -NotePropertyValue (Get-Sha256Lower $pointerPath)
    $receipt | ConvertTo-Json -Depth 10
}
catch {
    try {
        if ($previousPointerExists) {
            Write-AtomicFileFromSource `
                -Source $previousPointerBackup `
                -Target $pointerPath `
                -ExpectedSha256 $previousPointerSha256
        }
        else {
            Remove-Item -LiteralPath $pointerPath -Force -ErrorAction SilentlyContinue
        }
    }
    catch { }
    foreach ($item in @($promoted | Sort-Object promotion_order -Descending)) {
        try {
            if ([bool]$item.previous_exists) {
                Write-AtomicFileFromSource `
                    -Source $item.rollback_ref `
                    -Target $item.target_ref `
                    -ExpectedSha256 $item.previous_sha256
            }
            else {
                Remove-Item -LiteralPath $item.target_ref -Force -ErrorAction SilentlyContinue
            }
        }
        catch { }
    }
    throw
}
finally {
    foreach ($item in $prepared) {
        Remove-Item -LiteralPath $item.stage_ref -Force -ErrorAction SilentlyContinue
    }
}
