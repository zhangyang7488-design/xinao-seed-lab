[CmdletBinding()]
param(
    [string]$ArchiveRoot = $PSScriptRoot,
    [switch]$AllowPending
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath $ArchiveRoot).Path.TrimEnd('\')
$manifestPath = Join-Path $root "archive-manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "ARCHIVE_MANIFEST_MISSING: $manifestPath"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema -ne "xinao.codex-input-bridge.local-archive.v1") {
    throw "ARCHIVE_SCHEMA_MISMATCH: $($manifest.schema)"
}
$allowedStatuses = if ($AllowPending) {
    @("built_pending_independent_verification", "verified")
} else {
    @("verified")
}
if ([string]$manifest.status -notin $allowedStatuses) {
    throw "ARCHIVE_STATUS_NOT_ADMITTED: $($manifest.status)"
}

function Assert-ArchivedIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [object]$ExpectedBytes = $null,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "ARCHIVE_PRODUCT_FILE_MISSING: $Label => $Path"
    }
    $file = Get-Item -LiteralPath $Path
    if ($null -ne $ExpectedBytes -and $file.Length -ne [int64]$ExpectedBytes) {
        throw "ARCHIVE_PRODUCT_BYTES_MISMATCH: $Label"
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash -ne $ExpectedSha256) {
        throw "ARCHIVE_PRODUCT_SHA256_MISMATCH: $Label"
    }
}

function Assert-SafeArchivedRelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([IO.Path]::IsPathRooted($Path) -or
        $Path.Replace('\', '/').Split('/') -contains '..') {
        throw "ARCHIVE_PRODUCT_UNSAFE_RELATIVE_PATH: $Path"
    }
}

$expected = @{}
foreach ($entry in @($manifest.files)) {
    $relative = [string]$entry.path
    if ($expected.ContainsKey($relative)) {
        throw "ARCHIVE_DUPLICATE_MANIFEST_PATH: $relative"
    }
    $expected[$relative] = $entry
}

$actual = @{}
Get-ChildItem -LiteralPath $root -File -Recurse -Force |
    Where-Object { $_.FullName -ne $manifestPath } |
    ForEach-Object {
        $relative = $_.FullName.Substring($root.Length).TrimStart('\').Replace('\', '/')
        $actual[$relative] = $_
    }

if ([int]$manifest.file_count -ne @($manifest.files).Count -or
    [int]$manifest.file_count -ne $actual.Count) {
    throw "ARCHIVE_MANIFEST_FILE_COUNT_MISMATCH"
}

$missing = @($expected.Keys | Where-Object { -not $actual.ContainsKey($_) } | Sort-Object)
$unexpected = @($actual.Keys | Where-Object { -not $expected.ContainsKey($_) } | Sort-Object)
if ($missing.Count -gt 0) {
    throw "ARCHIVE_MISSING_FILES: $($missing -join ', ')"
}
if ($unexpected.Count -gt 0) {
    throw "ARCHIVE_UNEXPECTED_FILES: $($unexpected -join ', ')"
}

$mismatches = [System.Collections.Generic.List[string]]::new()
foreach ($relative in ($expected.Keys | Sort-Object)) {
    $entry = $expected[$relative]
    $file = $actual[$relative]
    if ([int64]$file.Length -ne [int64]$entry.bytes) {
        $mismatches.Add("bytes:$relative")
        continue
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
    if ($hash -ne [string]$entry.sha256) {
        $mismatches.Add("sha256:$relative")
    }
}
if ($mismatches.Count -gt 0) {
    throw "ARCHIVE_FILE_MISMATCH: $($mismatches -join ', ')"
}

$deliveryManifestPath = Join-Path $root "package\artifact-manifest.json"
$deliveryManifest = Get-Content -LiteralPath $deliveryManifestPath -Raw | ConvertFrom-Json
if ($deliveryManifest.schema -ne "xinao.codex-input-bridge.delivery.v2" -or
    $deliveryManifest.status -ne "verified_by_user_window_validation" -or
    $deliveryManifest.secrets_copied -ne $false) {
    throw "ARCHIVE_PRODUCT_MANIFEST_NOT_ADMITTED"
}
if ($actual.Count -ne [int]$deliveryManifest.local_archive.manifested_payload_file_count) {
    throw "ARCHIVE_PRODUCT_PAYLOAD_FILE_COUNT_MISMATCH"
}

foreach ($entry in @($deliveryManifest.package_support_files)) {
    Assert-SafeArchivedRelativePath -Path ([string]$entry.path)
    Assert-ArchivedIdentity `
        -Path (Join-Path $root ("package\" + ([string]$entry.path).Replace('/', '\'))) `
        -ExpectedSha256 ([string]$entry.sha256) -ExpectedBytes ([int64]$entry.bytes) `
        -Label "package:$($entry.path)"
}
$sourceArtifacts = @(
    $deliveryManifest.source.codex.bundle,
    $deliveryManifest.source.codex.patch,
    $deliveryManifest.source.windows_terminal.bundle,
    $deliveryManifest.source.windows_terminal.patch
)
foreach ($entry in $sourceArtifacts) {
    Assert-SafeArchivedRelativePath -Path ([string]$entry.path)
    Assert-ArchivedIdentity `
        -Path (Join-Path $root ("package\" + ([string]$entry.path).Replace('/', '\'))) `
        -ExpectedSha256 ([string]$entry.sha256) -ExpectedBytes ([int64]$entry.bytes) `
        -Label "source:$($entry.path)"
}

Assert-ArchivedIdentity -Path (Join-Path $root "runtime\codex\codex-tui.exe") `
    -ExpectedSha256 ([string]$deliveryManifest.local_runtime.codex_tui.sha256) `
    -ExpectedBytes ([int64]$deliveryManifest.local_runtime.codex_tui.bytes) -Label "codex-tui"
Assert-ArchivedIdentity -Path (Join-Path $root "runtime\codex\codex-code-mode-host.exe") `
    -ExpectedSha256 ([string]$deliveryManifest.local_runtime.code_mode_host.sha256) `
    -ExpectedBytes ([int64]$deliveryManifest.local_runtime.code_mode_host.bytes) -Label "code-mode-host"
Assert-ArchivedIdentity -Path (Join-Path $root "runtime\codex\manifest.sha256.json") `
    -ExpectedSha256 ([string]$deliveryManifest.local_runtime.codex_runtime_manifest_sha256) `
    -ExpectedBytes $null -Label "codex-runtime-manifest"
$codexManifest = @(Get-Content -LiteralPath (Join-Path $root "runtime\codex\manifest.sha256.json") -Raw | ConvertFrom-Json)
if ($codexManifest.Count -ne 3) {
    throw "ARCHIVE_PRODUCT_CODEX_MANIFEST_COUNT_MISMATCH"
}
foreach ($entry in $codexManifest) {
    Assert-SafeArchivedRelativePath -Path ([string]$entry.path)
    Assert-ArchivedIdentity `
        -Path (Join-Path $root ("runtime\codex\" + ([string]$entry.path).Replace('/', '\'))) `
        -ExpectedSha256 ([string]$entry.sha256) -ExpectedBytes ([int64]$entry.bytes) `
        -Label "codex-runtime:$($entry.path)"
}

$terminalManifestPath = Join-Path $root "runtime\windows-terminal.manifest.sha256.json"
Assert-ArchivedIdentity -Path $terminalManifestPath `
    -ExpectedSha256 ([string]$deliveryManifest.local_runtime.windows_terminal_build_manifest_sha256) `
    -ExpectedBytes $null -Label "windows-terminal-build-manifest"
$terminalEntries = @(Get-Content -LiteralPath $terminalManifestPath -Raw | ConvertFrom-Json)
if ($terminalEntries.Count -ne [int]$deliveryManifest.local_runtime.build_manifest_file_count) {
    throw "ARCHIVE_PRODUCT_WINDOWS_TERMINAL_MANIFEST_COUNT_MISMATCH"
}
foreach ($entry in $terminalEntries) {
    Assert-SafeArchivedRelativePath -Path ([string]$entry.path)
    Assert-ArchivedIdentity `
        -Path (Join-Path $root ("runtime\windows-terminal\" + ([string]$entry.path).Replace('/', '\'))) `
        -ExpectedSha256 ([string]$entry.sha256) -ExpectedBytes ([int64]$entry.bytes) `
        -Label "windows-terminal:$($entry.path)"
}

Assert-ArchivedIdentity -Path (Join-Path $root "desktop\Codex 输入框试验版.lnk") `
    -ExpectedSha256 ([string]$deliveryManifest.desktop.shortcut.sha256) -ExpectedBytes $null `
    -Label "desktop-shortcut"
Assert-ArchivedIdentity -Path (Join-Path $root "desktop\Open-Codex-S-Input-Canary.ps1") `
    -ExpectedSha256 ([string]$deliveryManifest.desktop.launcher_sha256) -ExpectedBytes $null `
    -Label "desktop-launcher"

$expectedProductPaths = @("package/artifact-manifest.json")
$expectedProductPaths += @($deliveryManifest.package_support_files | ForEach-Object {
    "package/" + ([string]$_.path).Replace('\', '/')
})
$expectedProductPaths += @($sourceArtifacts | ForEach-Object {
    "package/" + ([string]$_.path).Replace('\', '/')
})
$expectedProductPaths += "runtime/codex/manifest.sha256.json"
$expectedProductPaths += @($codexManifest | ForEach-Object {
    "runtime/codex/" + ([string]$_.path).Replace('\', '/')
})
$expectedProductPaths += @($terminalEntries | ForEach-Object {
    "runtime/windows-terminal/" + ([string]$_.path).Replace('\', '/')
})
$expectedProductPaths += @(
    "runtime/windows-terminal.manifest.sha256.json",
    "desktop/Codex 输入框试验版.lnk",
    "desktop/Open-Codex-S-Input-Canary.ps1",
    "DO_NOT_DELETE.md",
    "VERIFY.ps1"
)
$expectedProductPaths = @($expectedProductPaths | Sort-Object -Unique)

$preservationEntry = @($deliveryManifest.package_support_files | Where-Object { $_.path -eq "PRESERVATION.md" })
$verifyEntry = @($deliveryManifest.package_support_files | Where-Object { $_.path -eq "tools/VERIFY.ps1" })
if ($preservationEntry.Count -ne 1 -or $verifyEntry.Count -ne 1) {
    throw "ARCHIVE_PRODUCT_ROOT_IDENTITY_ENTRY_MISSING"
}
Assert-ArchivedIdentity -Path (Join-Path $root "DO_NOT_DELETE.md") `
    -ExpectedSha256 ([string]$preservationEntry[0].sha256) `
    -ExpectedBytes ([int64]$preservationEntry[0].bytes) -Label "root-preservation"
Assert-ArchivedIdentity -Path (Join-Path $root "VERIFY.ps1") `
    -ExpectedSha256 ([string]$verifyEntry[0].sha256) `
    -ExpectedBytes ([int64]$verifyEntry[0].bytes) -Label "root-verifier"

$missingProduct = @($expectedProductPaths | Where-Object { -not $actual.ContainsKey($_) })
$unexpectedProduct = @($actual.Keys | Where-Object { $_ -notin $expectedProductPaths })
if ($missingProduct.Count -gt 0 -or $unexpectedProduct.Count -gt 0 -or
    $expectedProductPaths.Count -ne $actual.Count) {
    throw "ARCHIVE_PRODUCT_FILE_SET_MISMATCH: missing=$($missingProduct -join ','); unexpected=$($unexpectedProduct -join ',')"
}

foreach ($forbidden in @(
    "runtime\windows-terminal\settings\state.json",
    "runtime\windows-terminal\settings\elevated-state.json"
)) {
    if (Test-Path -LiteralPath (Join-Path $root $forbidden)) {
        throw "ARCHIVE_FORBIDDEN_SESSION_STATE: $forbidden"
    }
}

foreach ($bundle in @(
    "package\source\codex-input-wt-bridge-0.144.5.bundle",
    "package\source\windows-terminal-composer-region-v1.24.11911.0.bundle"
)) {
    & git bundle verify (Join-Path $root $bundle) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "ARCHIVE_GIT_BUNDLE_INVALID: $bundle"
    }
}

[ordered]@{
    archive = $root
    status = "verified"
    file_count = $actual.Count
    manifest_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash
    forbidden_session_state_absent = $true
    git_bundles_verified = 2
} | ConvertTo-Json
