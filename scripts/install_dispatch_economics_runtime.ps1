#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
$source = Join-Path $SourceRoot "scripts\quota_query\Get-AIQuota.ps1"
$target = Join-Path $RuntimeRoot "state\quota_query\Get-AIQuota.ps1"
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "XINAO_QUOTA_EPOCH_SOURCE_MISSING: $source"
}
if (-not (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $target) "quota-query.mjs") -PathType Leaf)) {
    throw "XINAO_QUOTA_LIVE_COLLECTOR_MISSING"
}
$tokens = $null
$errors = $null
[void][Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if (@($errors).Count -gt 0) {
    throw "XINAO_QUOTA_EPOCH_SOURCE_PARSE_FAILED: $($errors -join '; ')"
}
$sourceSha = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$previousSha = ""
$releaseId = "quota-epoch-" + (Get-Date -Format "yyyyMMddTHHmmss") + "-" + $sourceSha.Substring(0, 12)
$releaseRoot = Join-Path $RuntimeRoot ("state\quota_query_releases\" + $releaseId)
New-Item -ItemType Directory -Path $releaseRoot -ErrorAction Stop | Out-Null
$backup = ""
if (Test-Path -LiteralPath $target -PathType Leaf) {
    $previousSha = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    $backup = Join-Path $releaseRoot "previous.Get-AIQuota.ps1"
    [IO.File]::WriteAllBytes($backup, [IO.File]::ReadAllBytes($target))
}
$temporary = $target + "." + [guid]::NewGuid().ToString("N") + ".tmp"
try {
    [IO.File]::WriteAllBytes($temporary, [IO.File]::ReadAllBytes($source))
    if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceSha) {
        throw "XINAO_QUOTA_EPOCH_STAGING_HASH_MISMATCH"
    }
    Move-Item -LiteralPath $temporary -Destination $target -Force
}
finally {
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
}
$installedSha = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
if ($installedSha -ne $sourceSha) {
    throw "XINAO_QUOTA_EPOCH_INSTALL_HASH_MISMATCH"
}
$receipt = [ordered]@{
    schema_version = "xinao.dispatch_economics_runtime_install_receipt.v1"
    installed_at = (Get-Date).ToString("o")
    source_root = [IO.Path]::GetFullPath($SourceRoot)
    source_git_head = [string](git -C $SourceRoot rev-parse HEAD)
    source_ref = [IO.Path]::GetFullPath($source)
    source_sha256 = $sourceSha
    target_ref = [IO.Path]::GetFullPath($target)
    target_sha256 = $installedSha
    previous_sha256 = $previousSha
    rollback_ref = $backup
    release_id = $releaseId
    authority = $false
    completion_claim_allowed = $false
}
$receiptPath = Join-Path $releaseRoot "install-receipt.json"
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 8), $utf8)
$receipt | Add-Member -NotePropertyName receipt_ref -NotePropertyValue $receiptPath
$receipt | Add-Member -NotePropertyName receipt_sha256 -NotePropertyValue ((Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant())
$receipt | ConvertTo-Json -Depth 8
