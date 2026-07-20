#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$TargetLauncher = "C:\Users\xx363\CodexLaunchers\Invoke-Codex-GrokWorkerPool.ps1"
)

$ErrorActionPreference = "Stop"
$source = Join-Path $SourceRoot "launchers\Invoke-Codex-GrokWorkerPool.ps1"
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "CODEX_GROK_LAUNCHER_SOURCE_MISSING: $source"
}
$tokens = $null
$errors = $null
[void][Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if (@($errors).Count -gt 0) {
    throw "CODEX_GROK_LAUNCHER_SOURCE_PARSE_FAILED: $($errors -join '; ')"
}
$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$previousHash = ""
$backup = ""
$releaseId = "dispatch-" + (Get-Date -Format "yyyyMMddTHHmmss") + "-" + $sourceHash.Substring(0, 12)
$releaseRoot = Join-Path $RuntimeRoot ("state\codex_grok_dispatch_releases\" + $releaseId)
New-Item -ItemType Directory -Path $releaseRoot -ErrorAction Stop | Out-Null
if (Test-Path -LiteralPath $TargetLauncher -PathType Leaf) {
    $previousHash = (Get-FileHash -LiteralPath $TargetLauncher -Algorithm SHA256).Hash.ToLowerInvariant()
    $backup = Join-Path $releaseRoot "previous.Invoke-Codex-GrokWorkerPool.ps1"
    [IO.File]::WriteAllBytes($backup, [IO.File]::ReadAllBytes($TargetLauncher))
}
$targetParent = Split-Path -Parent $TargetLauncher
New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
$temporary = $TargetLauncher + "." + [guid]::NewGuid().ToString("N") + ".tmp"
try {
    [IO.File]::WriteAllBytes($temporary, [IO.File]::ReadAllBytes($source))
    if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceHash) {
        throw "CODEX_GROK_LAUNCHER_STAGING_HASH_MISMATCH"
    }
    Move-Item -LiteralPath $temporary -Destination $TargetLauncher -Force
}
finally {
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
}
$installedHash = (Get-FileHash -LiteralPath $TargetLauncher -Algorithm SHA256).Hash.ToLowerInvariant()
if ($installedHash -ne $sourceHash) {
    throw "CODEX_GROK_LAUNCHER_INSTALL_HASH_MISMATCH"
}
$receipt = [ordered]@{
    schema_version = "xinao.codex_grok_dispatch_install_receipt.v1"
    installed_at = (Get-Date).ToString("o")
    source_root = [IO.Path]::GetFullPath($SourceRoot)
    source_git_head = [string](git -C $SourceRoot rev-parse HEAD)
    source_ref = [IO.Path]::GetFullPath($source)
    source_sha256 = $sourceHash
    target_ref = [IO.Path]::GetFullPath($TargetLauncher)
    target_sha256 = $installedHash
    previous_sha256 = $previousHash
    rollback_ref = $backup
    release_id = $releaseId
    dispatch_epoch_policy = "stable_episode_identity_plus_s_quota_dispatch_epoch"
    unscoped_ordinary_mode = "fail_closed_before_provider"
    package_epoch_policy = "exact_neutral_manifest_epoch_reseal_on_expiry"
    authority = $false
    completion_claim_allowed = $false
}
$receiptPath = Join-Path $releaseRoot "install-receipt.json"
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 8), $utf8)
$receipt | Add-Member -NotePropertyName receipt_ref -NotePropertyValue $receiptPath
$receipt | Add-Member -NotePropertyName receipt_sha256 -NotePropertyValue ((Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant())
$receipt | ConvertTo-Json -Depth 8
