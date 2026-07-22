#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$TargetLauncher = "C:\Users\xx363\CodexLaunchers\Invoke-Codex-OpenAiRelayWorker.ps1"
)

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false)
$coreRelativeFiles = @(
    "grok-admin-bridge\Invoke-CodexDispatchOpenAiRelayWorker.ps1",
    "grok-admin-bridge\Invoke-OpenAiCompatibleRelayWorker.ps1",
    "grok-admin-bridge\openai_sdk_wire.py",
    "grok-admin-bridge\validate_cognitive_audit_contract.py",
    "grok-admin-bridge\grok_openai_compatible_relay_worker.v1.json"
)
$optionalAdapterGroups = @(
    [ordered]@{
        adapter_id = "qwen_bailian_openai_compatible"
        files = @(
            "grok-admin-bridge\Invoke-CodexDispatchQwenWorker.ps1",
            "grok-admin-bridge\grok_qwen_bailian_relay_worker.v1.json"
        )
    },
    [ordered]@{
        adapter_id = "deepseek_openai_compatible"
        files = @(
            "grok-admin-bridge\Invoke-CodexDispatchDeepSeekWorker.ps1",
            "grok-admin-bridge\grok_deepseek_relay_worker.v1.json"
        )
    },
    [ordered]@{
        adapter_id = "lucis_openai_compatible"
        files = @(
            "grok-admin-bridge\Invoke-CodexDispatchLucisWorker.ps1",
            "grok-admin-bridge\grok_lucis_relay_worker.v1.json"
        )
    },
    [ordered]@{
        adapter_id = "ssstoken_openai_compatible_relay"
        files = @(
            "grok-admin-bridge\Invoke-CodexDispatchSssTokenWorker.ps1",
            "grok-admin-bridge\grok_ssstoken_relay_worker.v1.json"
        )
    }
)
$sourceLauncher = Join-Path $SourceRoot "launchers\Invoke-Codex-OpenAiRelayWorker.ps1"
$includedOptionalAdapters = @()
$includedOptionalAdapterFiles = @()
foreach ($adapterGroup in $optionalAdapterGroups) {
    $presentFiles = @($adapterGroup.files | Where-Object {
        Test-Path -LiteralPath (Join-Path $SourceRoot $_) -PathType Leaf
    })
    if ($presentFiles.Count -notin @(0, @($adapterGroup.files).Count)) {
        throw "CODEX_OPENAI_RELAY_OPTIONAL_ADAPTER_INCOMPLETE: $($adapterGroup.adapter_id)"
    }
    if ($presentFiles.Count -gt 0) {
        $includedOptionalAdapters += [string]$adapterGroup.adapter_id
        $includedOptionalAdapterFiles += @($adapterGroup.files)
    }
}
$relativeFiles = @($coreRelativeFiles) + @($includedOptionalAdapterFiles)
$allSources = @($sourceLauncher) + @($relativeFiles | ForEach-Object { Join-Path $SourceRoot $_ })
foreach ($source in $allSources) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "CODEX_OPENAI_RELAY_INSTALL_SOURCE_MISSING: $source"
    }
}
foreach ($source in @($allSources | Where-Object { [IO.Path]::GetExtension($_) -ieq ".ps1" })) {
    $tokens = $null
    $errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
    if (@($errors).Count -gt 0) {
        throw "CODEX_OPENAI_RELAY_INSTALL_SOURCE_PARSE_FAILED: $source"
    }
}

$fileHashes = [ordered]@{}
foreach ($relative in $relativeFiles) {
    $fileHashes[$relative.Replace('\', '/')] = (Get-FileHash -LiteralPath (Join-Path $SourceRoot $relative) -Algorithm SHA256).Hash.ToLowerInvariant()
}
$closureJson = $fileHashes | ConvertTo-Json -Compress
$closureSha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($utf8.GetBytes($closureJson))).ToLowerInvariant()
$releaseId = "relay-" + (Get-Date -Format "yyyyMMddTHHmmss") + "-" + $closureSha256.Substring(0, 12)
$releaseBase = Join-Path $RuntimeRoot "state\codex_openai_relay_releases"
$releaseRoot = Join-Path $releaseBase $releaseId
$bridgeTarget = Join-Path $releaseRoot "bridge"
New-Item -ItemType Directory -Path $bridgeTarget -ErrorAction Stop | Out-Null

foreach ($relative in $relativeFiles) {
    $source = Join-Path $SourceRoot $relative
    $target = Join-Path $bridgeTarget (Split-Path -Leaf $relative)
    [IO.File]::WriteAllBytes($target, [IO.File]::ReadAllBytes($source))
    $observed = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($observed -ne $fileHashes[$relative.Replace('\', '/')]) {
        throw "CODEX_OPENAI_RELAY_RELEASE_HASH_MISMATCH: $relative"
    }
}

$dispatchRef = Join-Path $bridgeTarget "Invoke-CodexDispatchOpenAiRelayWorker.ps1"
$dispatchSha256 = (Get-FileHash -LiteralPath $dispatchRef -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    schema_version = "xinao.codex_openai_relay_release_manifest.v2"
    release_id = $releaseId
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    source_root = [IO.Path]::GetFullPath($SourceRoot)
    source_git_head = [string](git -C $SourceRoot rev-parse HEAD)
    closure_sha256 = $closureSha256
    files = $fileHashes
    dispatch_ref = $dispatchRef
    dispatch_sha256 = $dispatchSha256
    provider_scope = "runtime_selected_admitted_openai_compatible_profile"
    core_files = @($coreRelativeFiles | ForEach-Object { $_.Replace('\', '/') })
    optional_adapters_included = @($includedOptionalAdapters)
    optional_adapter_files = @($includedOptionalAdapterFiles | ForEach-Object { $_.Replace('\', '/') })
    fixed_work_classes = @("general_cognitive", "cognitive_audit")
    module_binding_policy = "provider_and_adapter_identity_is_replaceable_without_changing_core_contract_or_owner_authority"
    package_width = 1
    global_concurrency = "dynamic_external_supervisor_not_fixed_here"
    authority = $false
    completion_claim_allowed = $false
}
$manifestPath = Join-Path $releaseRoot "release-manifest.json"
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8), $utf8)
$manifestSha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()

$pointer = [ordered]@{
    schema_version = "xinao.codex_openai_relay_release_pointer.v1"
    release_id = $releaseId
    manifest_ref = $manifestPath
    manifest_sha256 = $manifestSha256
    dispatch_ref = $dispatchRef
    dispatch_sha256 = $dispatchSha256
    authority = $false
    completion_claim_allowed = $false
}
New-Item -ItemType Directory -Force -Path $releaseBase | Out-Null
$pointerPath = Join-Path $releaseBase "current.json"
$pointerTemp = $pointerPath + "." + [guid]::NewGuid().ToString("N") + ".tmp"
[IO.File]::WriteAllText($pointerTemp, ($pointer | ConvertTo-Json -Depth 8), $utf8)
Move-Item -LiteralPath $pointerTemp -Destination $pointerPath -Force

$targetParent = Split-Path -Parent $TargetLauncher
New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
$launcherSha256 = (Get-FileHash -LiteralPath $sourceLauncher -Algorithm SHA256).Hash.ToLowerInvariant()
$launcherTemp = $TargetLauncher + "." + [guid]::NewGuid().ToString("N") + ".tmp"
[IO.File]::WriteAllBytes($launcherTemp, [IO.File]::ReadAllBytes($sourceLauncher))
if ((Get-FileHash -LiteralPath $launcherTemp -Algorithm SHA256).Hash.ToLowerInvariant() -ne $launcherSha256) {
    throw "CODEX_OPENAI_RELAY_LAUNCHER_STAGING_HASH_MISMATCH"
}
Move-Item -LiteralPath $launcherTemp -Destination $TargetLauncher -Force

[ordered]@{
    schema_version = "xinao.codex_openai_relay_install_receipt.v1"
    release_id = $releaseId
    release_manifest_ref = $manifestPath
    release_manifest_sha256 = $manifestSha256
    release_pointer_ref = $pointerPath
    dispatch_ref = $dispatchRef
    dispatch_sha256 = $dispatchSha256
    target_launcher = $TargetLauncher
    target_launcher_sha256 = (Get-FileHash -LiteralPath $TargetLauncher -Algorithm SHA256).Hash.ToLowerInvariant()
    authority = $false
    completion_claim_allowed = $false
} | ConvertTo-Json -Depth 8
