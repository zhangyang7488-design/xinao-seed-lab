#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RelativePath,
    [Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSourceSha256,
    [Parameter(Mandatory)][string]$CandidateAcceptanceReceipt,
    [Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedAcceptanceSha256
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

Assert-PiDualEntryBinary
$normalized = $RelativePath.Replace('/','\')
if ($normalized -notmatch '^(agents|contract)\\[a-zA-Z0-9][a-zA-Z0-9._-]*\.md$') {
    throw "PI_PROMOTION_RELATIVE_PATH_REJECTED: $RelativePath"
}
$leading = Get-PiDualEntrySpec -Profile 'prime-s'
$stable = Get-PiDualEntrySpec -Profile 'prime-b'
$source = [IO.Path]::GetFullPath((Join-Path $leading.OverlayRoot $normalized))
$destination = [IO.Path]::GetFullPath((Join-Path $stable.OverlayRoot $normalized))
$leadingRoot = [IO.Path]::GetFullPath($leading.OverlayRoot).TrimEnd('\') + '\'
$stableRoot = [IO.Path]::GetFullPath($stable.OverlayRoot).TrimEnd('\') + '\'
if (-not $source.StartsWith($leadingRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'PI_PROMOTION_SOURCE_ESCAPE' }
if (-not $destination.StartsWith($stableRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'PI_PROMOTION_DESTINATION_ESCAPE' }
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "PI_PROMOTION_SOURCE_MISSING: $source" }

$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
if ($sourceHash -ne $ExpectedSourceSha256.ToLowerInvariant()) {
    throw "PI_PROMOTION_SOURCE_HASH_MISMATCH: expected=$ExpectedSourceSha256 actual=$sourceHash"
}
$acceptanceRoot = [IO.Path]::GetFullPath((Join-Path $script:PiDualEntryStateRoot 'acceptance')).TrimEnd('\') + '\'
$acceptance = [IO.Path]::GetFullPath($CandidateAcceptanceReceipt)
if (-not $acceptance.StartsWith($acceptanceRoot,[StringComparison]::OrdinalIgnoreCase)) {
    throw "PI_PROMOTION_ACCEPTANCE_OUTSIDE_ROOT: $acceptance"
}
if (-not (Test-Path -LiteralPath $acceptance -PathType Leaf)) { throw "PI_PROMOTION_ACCEPTANCE_MISSING: $acceptance" }
$acceptanceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $acceptance).Hash.ToLowerInvariant()
if ($acceptanceHash -ne $ExpectedAcceptanceSha256.ToLowerInvariant()) {
    throw "PI_PROMOTION_ACCEPTANCE_HASH_MISMATCH: expected=$ExpectedAcceptanceSha256 actual=$acceptanceHash"
}

$transactionId = 'promote-' + [DateTimeOffset]::Now.ToString('yyyyMMddTHHmmssffffzzz').Replace(':','') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
$transactionRoot = Join-Path $script:PiDualEntryStateRoot "promotions\$transactionId"
New-Item -ItemType Directory -Force -Path $transactionRoot | Out-Null
$preimage = Join-Path $transactionRoot 'preimage.md'
$preimageExisted = Test-Path -LiteralPath $destination -PathType Leaf
$preimageHash = $null
if ($preimageExisted) {
    Copy-Item -LiteralPath $destination -Destination $preimage
    $preimageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $preimage).Hash.ToLowerInvariant()
}
$preparePath = Join-Path $transactionRoot 'prepare.json'
Write-PiDualEntryJsonAtomic -Path $preparePath -Value ([ordered]@{
    schema = 'xinao.pi_selective_promotion.prepare.v1'
    transaction_id = $transactionId
    relative_path = $normalized
    source = $source
    source_sha256 = $sourceHash
    destination = $destination
    preimage_existed = $preimageExisted
    preimage_sha256 = $preimageHash
    candidate_acceptance = $acceptance
    candidate_acceptance_sha256 = $acceptanceHash
    excluded_roots = @('auth.json','account-binding.json','sessions','whole profile','whole island')
})

function Restore-Preimage {
    if ($preimageExisted) {
        Copy-Item -LiteralPath $preimage -Destination $destination -Force
    } elseif (Test-Path -LiteralPath $destination -PathType Leaf) {
        Remove-Item -LiteralPath $destination -Force
    }
}

try {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    $temporary = "$destination.$PID.tmp"
    [IO.File]::WriteAllBytes($temporary,[IO.File]::ReadAllBytes($source))
    Move-Item -LiteralPath $temporary -Destination $destination -Force
    $promotedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
    if ($promotedHash -ne $sourceHash) { throw 'PI_PROMOTION_DESTINATION_HASH_MISMATCH' }

    & (Join-Path $PSScriptRoot 'Initialize-UpstreamPiProfiles.ps1') -Profile prime-b | Out-Null
    $freshReceipt = Join-Path $transactionRoot 'prime-b-fresh.json'
    & (Join-Path $PSScriptRoot 'Test-UpstreamPiDualEntry.ps1') -Profile prime-b -RunLiveModelProbe -ReceiptPath $freshReceipt | Out-Null
} catch {
    Restore-Preimage
    & (Join-Path $PSScriptRoot 'Initialize-UpstreamPiProfiles.ps1') -Profile prime-b | Out-Null
    throw
}

$receiptPath = Join-Path $transactionRoot 'promotion.receipt.json'
$receipt = [ordered]@{
    schema = 'xinao.pi_selective_promotion.receipt.v1'
    status = 'promoted'
    transaction_id = $transactionId
    relative_path = $normalized
    source_sha256 = $sourceHash
    destination_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
    preimage_existed = $preimageExisted
    preimage_path = if ($preimageExisted) { $preimage } else { $null }
    preimage_sha256 = $preimageHash
    candidate_acceptance = $acceptance
    candidate_acceptance_sha256 = $acceptanceHash
    prime_b_fresh_receipt = $freshReceipt
    forbidden_state_touched = $false
}
Write-PiDualEntryJsonAtomic -Path $receiptPath -Value $receipt
[ordered]@{receipt_path=$receiptPath;receipt=$receipt} | ConvertTo-Json -Depth 8
