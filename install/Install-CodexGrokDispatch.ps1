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
        throw "CODEX_GROK_INSTALL_SOURCE_PARSE_FAILED: $Path"
    }
}

function Restore-PreviousInstallItem([object]$Item) {
    if ([bool]$Item.previous_exists) {
        $temporary = $Item.target_ref + "." + [guid]::NewGuid().ToString("N") + ".rollback"
        try {
            [IO.File]::WriteAllBytes($temporary, [IO.File]::ReadAllBytes($Item.rollback_ref))
            if ((Get-Sha256Lower $temporary) -ne [string]$Item.previous_sha256) {
                throw "CODEX_GROK_INSTALL_ROLLBACK_HASH_MISMATCH: $($Item.target_ref)"
            }
            Move-Item -LiteralPath $temporary -Destination $Item.target_ref -Force
        }
        finally {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }
    else {
        Remove-Item -LiteralPath $Item.target_ref -Force -ErrorAction SilentlyContinue
    }
}

$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$TargetLauncher = [IO.Path]::GetFullPath($TargetLauncher)
$TargetBridgeRoot = [IO.Path]::GetFullPath($TargetBridgeRoot)
$AuthProfileRoot = [IO.Path]::GetFullPath($AuthProfileRoot)
$runtimeRelativeFiles = @(
    "GrokAuthenticatedCatalogTime.ps1",
    "GrokAuthenticatedCatalogRefresh.ps1",
    "Invoke-CodexDispatchGrokWorkerPool.ps1",
    "Invoke-GrokComposer25Worker.ps1"
)
$sourceLauncher = Join-Path $SourceRoot "launchers\Invoke-Codex-GrokWorkerPool.ps1"
$specs = [Collections.Generic.List[object]]::new()
$order = 0
foreach ($relative in $runtimeRelativeFiles) {
    $order += 1
    $specs.Add([pscustomobject]@{
        role = "runtime_bridge"
        relative_ref = $relative
        source_ref = Join-Path $SourceRoot ("grok-admin-bridge\" + $relative)
        target_ref = Join-Path $TargetBridgeRoot $relative
        promotion_order = $order
    })
}
$order += 1
$specs.Add([pscustomobject]@{
    role = "public_launcher"
    relative_ref = "Invoke-Codex-GrokWorkerPool.ps1"
    source_ref = $sourceLauncher
    target_ref = $TargetLauncher
    promotion_order = $order
})

foreach ($spec in $specs) {
    if (-not (Test-Path -LiteralPath $spec.source_ref -PathType Leaf)) {
        throw "CODEX_GROK_INSTALL_SOURCE_MISSING: $($spec.source_ref)"
    }
    Assert-PowerShellSource $spec.source_ref
    $spec | Add-Member -NotePropertyName source_sha256 -NotePropertyValue (Get-Sha256Lower $spec.source_ref)
}
$runtimeHashes = [ordered]@{}
foreach ($spec in @($specs | Where-Object role -eq "runtime_bridge")) {
    $runtimeHashes[[string]$spec.relative_ref] = [string]$spec.source_sha256
}
$closureSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($utf8.GetBytes(($runtimeHashes | ConvertTo-Json -Compress)))
).ToLowerInvariant()
$releaseId = "dispatch-" + (Get-Date -Format "yyyyMMddTHHmmssfff") + "-" + $closureSha256.Substring(0, 12)
$releaseBase = Join-Path $RuntimeRoot "state\codex_grok_dispatch_releases"
$releaseRoot = Join-Path $releaseBase $releaseId
$backupRoot = Join-Path $releaseRoot "previous"
New-Item -ItemType Directory -Path $backupRoot -ErrorAction Stop | Out-Null

$prepared = [Collections.Generic.List[object]]::new()
foreach ($spec in $specs) {
    $target = [IO.Path]::GetFullPath([string]$spec.target_ref)
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    $previousExists = Test-Path -LiteralPath $target -PathType Leaf
    $previousSha256 = ""
    $rollbackRef = ""
    if ($previousExists) {
        $previousSha256 = Get-Sha256Lower $target
        $rollbackRef = Join-Path $backupRoot (("{0:D2}-" -f [int]$spec.promotion_order) + [IO.Path]::GetFileName($target))
        [IO.File]::WriteAllBytes($rollbackRef, [IO.File]::ReadAllBytes($target))
        if ((Get-Sha256Lower $rollbackRef) -ne $previousSha256) {
            throw "CODEX_GROK_INSTALL_BACKUP_HASH_MISMATCH: $target"
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

$promoted = [Collections.Generic.List[object]]::new()
$receiptPath = Join-Path $releaseRoot "install-receipt.json"
$pointerPath = Join-Path $releaseBase "current.json"
try {
    foreach ($item in @($prepared | Sort-Object promotion_order)) {
        Move-Item -LiteralPath $item.stage_ref -Destination $item.target_ref -Force
        if ((Get-Sha256Lower $item.target_ref) -ne [string]$item.installed_sha256) {
            throw "CODEX_GROK_INSTALL_READBACK_HASH_MISMATCH: $($item.target_ref)"
        }
        $promoted.Add($item)
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
    $sourceGitHead = [string](@(& git -C $SourceRoot rev-parse HEAD 2>$null | Select-Object -First 1)[0])
    if ($sourceGitHead -notmatch '^[0-9a-fA-F]{40}$') {
        throw "CODEX_GROK_INSTALL_SOURCE_GIT_IDENTITY_UNAVAILABLE"
    }
    $receipt = [ordered]@{
        schema_version = "xinao.codex_grok_dispatch_install_receipt.v2"
        installed_at = (Get-Date).ToUniversalTime().ToString("o")
        release_id = $releaseId
        source_root = $SourceRoot
        source_git_head = $sourceGitHead
        target_bridge_root = $TargetBridgeRoot
        bridge_closure_sha256 = $closureSha256
        install_items = @($prepared | Sort-Object promotion_order | ForEach-Object {
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
        auth_profile_root = $AuthProfileRoot
        auth_state = if ($authPresent) { "present_nonempty" } else { "login_required" }
        auth_present = [bool]$authPresent
        auth_bytes_read = $false
        auth_copied_or_backed_up = $false
        catalog_is_auth_proof = $false
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
        source_git_head = $sourceGitHead
        bridge_closure_sha256 = $closureSha256
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
    $receipt | Add-Member -NotePropertyName receipt_ref -NotePropertyValue $receiptPath
    $receipt | Add-Member -NotePropertyName receipt_sha256 -NotePropertyValue $receiptSha256
    $receipt | Add-Member -NotePropertyName release_pointer_ref -NotePropertyValue $pointerPath
    $receipt | Add-Member -NotePropertyName release_pointer_sha256 -NotePropertyValue (Get-Sha256Lower $pointerPath)
    $receipt | ConvertTo-Json -Depth 10
}
catch {
    foreach ($item in @($promoted | Sort-Object promotion_order -Descending)) {
        try { Restore-PreviousInstallItem $item } catch { }
    }
    throw
}
finally {
    foreach ($item in $prepared) {
        Remove-Item -LiteralPath $item.stage_ref -Force -ErrorAction SilentlyContinue
    }
}
