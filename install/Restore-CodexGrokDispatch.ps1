#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallReceiptPath
)

$ErrorActionPreference = "Stop"

function Get-Sha256Lower([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$InstallReceiptPath = [IO.Path]::GetFullPath($InstallReceiptPath)
if (-not (Test-Path -LiteralPath $InstallReceiptPath -PathType Leaf)) {
    throw "CODEX_GROK_ROLLBACK_RECEIPT_MISSING: $InstallReceiptPath"
}
$receipt = Get-Content -LiteralPath $InstallReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
if ([string]$receipt.schema_version -ne "xinao.codex_grok_dispatch_install_receipt.v2") {
    throw "CODEX_GROK_ROLLBACK_RECEIPT_SCHEMA_MISMATCH"
}
$items = @($receipt.install_items | Sort-Object { [int]$_.promotion_order } -Descending)
if ($items.Count -lt 2) {
    throw "CODEX_GROK_ROLLBACK_RECEIPT_ITEMS_INVALID"
}
$pointerPath = [IO.Path]::GetFullPath([string]$receipt.release_pointer_ref)
if (-not (Test-Path -LiteralPath $pointerPath -PathType Leaf)) {
    throw "CODEX_GROK_ROLLBACK_CURRENT_POINTER_MISSING"
}
$currentPointer = Get-Content -LiteralPath $pointerPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
if ([string]$currentPointer.release_id -ne [string]$receipt.release_id) {
    throw "CODEX_GROK_ROLLBACK_CURRENT_POINTER_DRIFT"
}

$recoveryCopies = [Collections.Generic.List[object]]::new()
$restoreStages = [Collections.Generic.List[object]]::new()
foreach ($item in $items) {
    $target = [IO.Path]::GetFullPath([string]$item.target_ref)
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        throw "CODEX_GROK_ROLLBACK_CURRENT_TARGET_MISSING: $target"
    }
    if ((Get-Sha256Lower $target) -ne [string]$item.installed_sha256) {
        throw "CODEX_GROK_ROLLBACK_CURRENT_TARGET_DRIFT: $target"
    }
    $recoveryRef = $target + "." + [guid]::NewGuid().ToString("N") + ".rollback-current"
    [IO.File]::WriteAllBytes($recoveryRef, [IO.File]::ReadAllBytes($target))
    if ((Get-Sha256Lower $recoveryRef) -ne [string]$item.installed_sha256) {
        throw "CODEX_GROK_ROLLBACK_RECOVERY_COPY_HASH_MISMATCH: $target"
    }
    $recoveryCopies.Add([pscustomobject]@{ target_ref = $target; recovery_ref = $recoveryRef })

    $restoreRef = ""
    if ([bool]$item.previous_exists) {
        $rollbackRef = [IO.Path]::GetFullPath([string]$item.rollback_ref)
        if (-not (Test-Path -LiteralPath $rollbackRef -PathType Leaf) -or
            (Get-Sha256Lower $rollbackRef) -ne [string]$item.previous_sha256) {
            throw "CODEX_GROK_ROLLBACK_BACKUP_INVALID: $target"
        }
        $restoreRef = $target + "." + [guid]::NewGuid().ToString("N") + ".rollback-stage"
        [IO.File]::WriteAllBytes($restoreRef, [IO.File]::ReadAllBytes($rollbackRef))
        if ((Get-Sha256Lower $restoreRef) -ne [string]$item.previous_sha256) {
            throw "CODEX_GROK_ROLLBACK_STAGE_HASH_MISMATCH: $target"
        }
    }
    $restoreStages.Add([pscustomobject]@{
        target_ref = $target
        restore_ref = $restoreRef
        previous_exists = [bool]$item.previous_exists
        previous_sha256 = [string]$item.previous_sha256
        promotion_order = [int]$item.promotion_order
    })
}

$changed = [Collections.Generic.List[object]]::new()
try {
    foreach ($item in $restoreStages) {
        if ($item.previous_exists) {
            Move-Item -LiteralPath $item.restore_ref -Destination $item.target_ref -Force
            if ((Get-Sha256Lower $item.target_ref) -ne $item.previous_sha256) {
                throw "CODEX_GROK_ROLLBACK_READBACK_HASH_MISMATCH: $($item.target_ref)"
            }
        }
        else {
            Remove-Item -LiteralPath $item.target_ref -Force
        }
        $changed.Add($item)
    }

    if ([bool]$receipt.previous_pointer_exists) {
        $previousPointer = [IO.Path]::GetFullPath([string]$receipt.previous_pointer_rollback_ref)
        if (-not (Test-Path -LiteralPath $previousPointer -PathType Leaf) -or
            (Get-Sha256Lower $previousPointer) -ne [string]$receipt.previous_pointer_sha256) {
            throw "CODEX_GROK_ROLLBACK_PREVIOUS_POINTER_INVALID"
        }
        $pointerTemporary = $pointerPath + "." + [guid]::NewGuid().ToString("N") + ".rollback"
        [IO.File]::WriteAllBytes($pointerTemporary, [IO.File]::ReadAllBytes($previousPointer))
        Move-Item -LiteralPath $pointerTemporary -Destination $pointerPath -Force
    }
    else {
        Remove-Item -LiteralPath $pointerPath -Force -ErrorAction SilentlyContinue
    }

    [ordered]@{
        schema_version = "xinao.codex_grok_dispatch_rollback_result.v1"
        rolled_back_at = (Get-Date).ToUniversalTime().ToString("o")
        release_id = [string]$receipt.release_id
        restored_item_count = $changed.Count
        release_pointer_restored = [bool]$receipt.previous_pointer_exists
        auth_profile_touched = $false
        authority = $false
        completion_claim_allowed = $false
    } | ConvertTo-Json -Depth 6
}
catch {
    foreach ($recovery in @($recoveryCopies | Sort-Object { $_.target_ref })) {
        try {
            Move-Item -LiteralPath $recovery.recovery_ref -Destination $recovery.target_ref -Force
        }
        catch { }
    }
    throw
}
finally {
    foreach ($recovery in $recoveryCopies) {
        Remove-Item -LiteralPath $recovery.recovery_ref -Force -ErrorAction SilentlyContinue
    }
    foreach ($stage in $restoreStages) {
        if (-not [string]::IsNullOrWhiteSpace([string]$stage.restore_ref)) {
            Remove-Item -LiteralPath $stage.restore_ref -Force -ErrorAction SilentlyContinue
        }
    }
}
