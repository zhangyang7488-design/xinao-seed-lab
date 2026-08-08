#Requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReceiptPath)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) { throw "PI_PROMOTION_RECEIPT_MISSING: $ReceiptPath" }
$receipt = Get-Content -Raw -LiteralPath $ReceiptPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$receipt.schema -ne 'xinao.pi_selective_promotion.receipt.v1' -or [string]$receipt.status -ne 'promoted') {
    throw 'PI_PROMOTION_RECEIPT_INVALID'
}
$stable = Get-PiDualEntrySpec -Profile 'prime-b'
$normalized = ([string]$receipt.relative_path).Replace('/','\')
if ($normalized -notmatch '^(agents|contract)\\[a-zA-Z0-9][a-zA-Z0-9._-]*\.md$') { throw 'PI_PROMOTION_ROLLBACK_PATH_REJECTED' }
$destination = [IO.Path]::GetFullPath((Join-Path $stable.OverlayRoot $normalized))
$stableRoot = [IO.Path]::GetFullPath($stable.OverlayRoot).TrimEnd('\') + '\'
if (-not $destination.StartsWith($stableRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'PI_PROMOTION_ROLLBACK_DESTINATION_ESCAPE' }
if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) { throw 'PI_PROMOTION_ROLLBACK_DESTINATION_MISSING' }
$currentHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
if ($currentHash -ne ([string]$receipt.destination_sha256).ToLowerInvariant()) {
    throw "PI_PROMOTION_ROLLBACK_CURRENT_HASH_MISMATCH: expected=$($receipt.destination_sha256) actual=$currentHash"
}

if ($receipt.preimage_existed -eq $true) {
    $preimage = [string]$receipt.preimage_path
    if (-not (Test-Path -LiteralPath $preimage -PathType Leaf)) { throw 'PI_PROMOTION_ROLLBACK_PREIMAGE_MISSING' }
    $preimageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $preimage).Hash.ToLowerInvariant()
    if ($preimageHash -ne ([string]$receipt.preimage_sha256).ToLowerInvariant()) { throw 'PI_PROMOTION_ROLLBACK_PREIMAGE_HASH_MISMATCH' }
    Copy-Item -LiteralPath $preimage -Destination $destination -Force
} else {
    Remove-Item -LiteralPath $destination -Force
}

& (Join-Path $PSScriptRoot 'Initialize-UpstreamPiProfiles.ps1') -Profile prime-b | Out-Null
$transactionRoot = Split-Path -Parent $ReceiptPath
$freshReceipt = Join-Path $transactionRoot 'prime-b-rollback-fresh.json'
& (Join-Path $PSScriptRoot 'Test-UpstreamPiDualEntry.ps1') -Profile prime-b -RunLiveModelProbe -ReceiptPath $freshReceipt | Out-Null
$rollbackPath = Join-Path $transactionRoot 'rollback.receipt.json'
$rollback = [ordered]@{
    schema = 'xinao.pi_selective_promotion.rollback.v1'
    status = 'rolled_back'
    transaction_id = [string]$receipt.transaction_id
    relative_path = $normalized
    restored_preimage = [bool]$receipt.preimage_existed
    destination_present = (Test-Path -LiteralPath $destination -PathType Leaf)
    prime_b_fresh_receipt = $freshReceipt
    forbidden_state_touched = $false
}
Write-PiDualEntryJsonAtomic -Path $rollbackPath -Value $rollback
[ordered]@{receipt_path=$rollbackPath;receipt=$rollback} | ConvertTo-Json -Depth 6
