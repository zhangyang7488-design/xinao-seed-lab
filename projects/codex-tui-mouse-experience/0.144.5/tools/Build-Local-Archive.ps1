[CmdletBinding()]
param(
    [string]$Destination = "E:\XINAO_EXTERNAL_SOURCES\archives\codex-input-bridge\0.144.5-wt-1.24.11911.0-20260716",
    [string]$CodexRuntime = "D:\XINAO_RESEARCH_RUNTIME\tools\codex-input-canary\0.144.5-20260716-0e350e52-wt-composer",
    [string]$TerminalRuntime = "D:\XINAO_RESEARCH_RUNTIME\canary\wt-input-drag-20260716T225434\terminal",
    [string]$Shortcut = "C:\Users\xx363\Desktop\Codex 输入框试验版.lnk",
    [string]$Launcher = "C:\Users\xx363\CodexLaunchers\Open-Codex-S-Input-Canary.ps1"
)

$ErrorActionPreference = "Stop"

$packageRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$destinationParent = Split-Path -Parent $Destination
$deliveryManifestPath = Join-Path $packageRoot "artifact-manifest.json"

function Assert-FileIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [object]$ExpectedBytes = $null,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "ARCHIVE_IDENTITY_FILE_MISSING: $Label => $Path"
    }
    $file = Get-Item -LiteralPath $Path
    if ($null -ne $ExpectedBytes -and $file.Length -ne [int64]$ExpectedBytes) {
        throw "ARCHIVE_IDENTITY_BYTES_MISMATCH: $Label"
    }
    $actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
    if ($actualSha256 -ne $ExpectedSha256) {
        throw "ARCHIVE_IDENTITY_SHA256_MISMATCH: $Label"
    }
}

function Assert-SafeRelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([IO.Path]::IsPathRooted($Path) -or
        $Path.Replace('\', '/').Split('/') -contains '..') {
        throw "ARCHIVE_UNSAFE_RELATIVE_PATH: $Path"
    }
}

function Assert-ExactFileSet {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$ExpectedPaths,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
    $expected = @($ExpectedPaths | ForEach-Object { $_.Replace('\', '/') } | Sort-Object -Unique)
    if ($expected.Count -ne $ExpectedPaths.Count) {
        throw "ARCHIVE_DUPLICATE_EXPECTED_PATH: $Label"
    }
    $actual = @(Get-ChildItem -LiteralPath $resolvedRoot -File -Recurse -Force | ForEach-Object {
        $_.FullName.Substring($resolvedRoot.Length).TrimStart('\').Replace('\', '/')
    } | Sort-Object -Unique)
    $missing = @($expected | Where-Object { $_ -notin $actual })
    $unexpected = @($actual | Where-Object { $_ -notin $expected })
    if ($missing.Count -gt 0 -or $unexpected.Count -gt 0) {
        throw "ARCHIVE_SOURCE_FILE_SET_MISMATCH: $Label; missing=$($missing -join ','); unexpected=$($unexpected -join ',')"
    }
}

function Copy-ExactFiles {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string[]]$RelativePaths,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )

    foreach ($relativePath in $RelativePaths) {
        Assert-SafeRelativePath -Path $relativePath
        $normalized = $relativePath.Replace('/', '\')
        $source = Join-Path $SourceRoot $normalized
        $target = Join-Path $DestinationRoot $normalized
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
}

foreach ($path in @($packageRoot, $CodexRuntime, $TerminalRuntime)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "ARCHIVE_REQUIRED_DIRECTORY_MISSING: $path"
    }
}
foreach ($path in @($Shortcut, $Launcher)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "ARCHIVE_REQUIRED_FILE_MISSING: $path"
    }
}

$destinationFull = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
$Destination = $destinationFull
$destinationParent = Split-Path -Parent $Destination
foreach ($sourceRoot in @($packageRoot, $CodexRuntime, $TerminalRuntime)) {
    $sourceFull = (Resolve-Path -LiteralPath $sourceRoot).Path.TrimEnd('\')
    if ($destinationFull.Equals($sourceFull, [StringComparison]::OrdinalIgnoreCase) -or
        $destinationFull.StartsWith($sourceFull + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $sourceFull.StartsWith($destinationFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "ARCHIVE_DESTINATION_OVERLAPS_SOURCE: $destinationFull <=> $sourceFull"
    }
}

$deliveryManifest = Get-Content -LiteralPath $deliveryManifestPath -Raw | ConvertFrom-Json
if ($deliveryManifest.schema -ne "xinao.codex-input-bridge.delivery.v2" -or
    $deliveryManifest.status -ne "verified_by_user_window_validation" -or
    $deliveryManifest.secrets_copied -ne $false) {
    throw "ARCHIVE_DELIVERY_MANIFEST_NOT_ADMITTED"
}

$sourceArtifacts = @(
    $deliveryManifest.source.codex.bundle,
    $deliveryManifest.source.codex.patch,
    $deliveryManifest.source.windows_terminal.bundle,
    $deliveryManifest.source.windows_terminal.patch
)
$packageExpectedPaths = @("artifact-manifest.json")
foreach ($entry in @($deliveryManifest.package_support_files)) {
    Assert-SafeRelativePath -Path ([string]$entry.path)
    $packageExpectedPaths += [string]$entry.path
    $path = Join-Path $packageRoot ([string]$entry.path).Replace('/', '\')
    Assert-FileIdentity -Path $path -ExpectedSha256 ([string]$entry.sha256) `
        -ExpectedBytes ([int64]$entry.bytes) -Label "package:$($entry.path)"
}
foreach ($entry in $sourceArtifacts) {
    Assert-SafeRelativePath -Path ([string]$entry.path)
    $packageExpectedPaths += [string]$entry.path
    $path = Join-Path $packageRoot ([string]$entry.path).Replace('/', '\')
    Assert-FileIdentity -Path $path -ExpectedSha256 ([string]$entry.sha256) `
        -ExpectedBytes ([int64]$entry.bytes) -Label "source:$($entry.path)"
}
Assert-ExactFileSet -Root $packageRoot -ExpectedPaths $packageExpectedPaths -Label "package"

$codexManifestPath = Join-Path $CodexRuntime "manifest.sha256.json"
Assert-FileIdentity -Path (Join-Path $CodexRuntime "codex-tui.exe") `
    -ExpectedSha256 ([string]$deliveryManifest.local_runtime.codex_tui.sha256) `
    -ExpectedBytes ([int64]$deliveryManifest.local_runtime.codex_tui.bytes) -Label "codex-tui"
Assert-FileIdentity -Path (Join-Path $CodexRuntime "codex-code-mode-host.exe") `
    -ExpectedSha256 ([string]$deliveryManifest.local_runtime.code_mode_host.sha256) `
    -ExpectedBytes ([int64]$deliveryManifest.local_runtime.code_mode_host.bytes) -Label "code-mode-host"
Assert-FileIdentity -Path $codexManifestPath `
    -ExpectedSha256 ([string]$deliveryManifest.local_runtime.codex_runtime_manifest_sha256) `
    -ExpectedBytes $null -Label "codex-runtime-manifest"
$codexEntries = @(Get-Content -LiteralPath $codexManifestPath -Raw | ConvertFrom-Json)
if ($codexEntries.Count -ne 3) {
    throw "ARCHIVE_CODEX_RUNTIME_MANIFEST_COUNT_MISMATCH"
}
foreach ($entry in $codexEntries) {
    Assert-SafeRelativePath -Path ([string]$entry.path)
    Assert-FileIdentity -Path (Join-Path $CodexRuntime ([string]$entry.path).Replace('/', '\')) `
        -ExpectedSha256 ([string]$entry.sha256) -ExpectedBytes ([int64]$entry.bytes) `
        -Label "codex-runtime:$($entry.path)"
}
$codexExpectedPaths = @("manifest.sha256.json") + @($codexEntries | ForEach-Object { [string]$_.path })
Assert-ExactFileSet -Root $CodexRuntime -ExpectedPaths $codexExpectedPaths -Label "codex-runtime"

$terminalRoot = (Resolve-Path -LiteralPath $TerminalRuntime).Path.TrimEnd('\')
$terminalManifestPath = Join-Path (Split-Path -Parent $terminalRoot) "manifest.sha256.json"
Assert-FileIdentity -Path (Join-Path $terminalRoot "WindowsTerminal.exe") `
    -ExpectedSha256 ([string]$deliveryManifest.local_runtime.windows_terminal.sha256) `
    -ExpectedBytes ([int64]$deliveryManifest.local_runtime.windows_terminal.bytes) -Label "WindowsTerminal"
Assert-FileIdentity -Path (Join-Path $terminalRoot "Microsoft.Terminal.Control.dll") `
    -ExpectedSha256 ([string]$deliveryManifest.local_runtime.terminal_control_dll.sha256) `
    -ExpectedBytes ([int64]$deliveryManifest.local_runtime.terminal_control_dll.bytes) -Label "TerminalControl"
Assert-FileIdentity -Path $terminalManifestPath `
    -ExpectedSha256 ([string]$deliveryManifest.local_runtime.windows_terminal_build_manifest_sha256) `
    -ExpectedBytes $null -Label "windows-terminal-build-manifest"
$terminalEntries = @(Get-Content -LiteralPath $terminalManifestPath -Raw | ConvertFrom-Json)
if ($terminalEntries.Count -ne [int]$deliveryManifest.local_runtime.build_manifest_file_count) {
    throw "ARCHIVE_WINDOWS_TERMINAL_MANIFEST_COUNT_MISMATCH"
}
foreach ($entry in $terminalEntries) {
    Assert-SafeRelativePath -Path ([string]$entry.path)
    Assert-FileIdentity -Path (Join-Path $terminalRoot ([string]$entry.path).Replace('/', '\')) `
        -ExpectedSha256 ([string]$entry.sha256) -ExpectedBytes ([int64]$entry.bytes) `
        -Label "windows-terminal:$($entry.path)"
}
$terminalExpectedPaths = @($terminalEntries | ForEach-Object { [string]$_.path })
foreach ($allowedState in @("settings/state.json", "settings/elevated-state.json")) {
    if (Test-Path -LiteralPath (Join-Path $terminalRoot $allowedState.Replace('/', '\')) -PathType Leaf) {
        $terminalExpectedPaths += $allowedState
    }
}
Assert-ExactFileSet -Root $terminalRoot -ExpectedPaths $terminalExpectedPaths -Label "windows-terminal-runtime"

Assert-FileIdentity -Path $Shortcut -ExpectedSha256 ([string]$deliveryManifest.desktop.shortcut.sha256) `
    -ExpectedBytes $null -Label "desktop-shortcut"
Assert-FileIdentity -Path $Launcher -ExpectedSha256 ([string]$deliveryManifest.desktop.launcher_sha256) `
    -ExpectedBytes $null -Label "desktop-launcher"

if (Test-Path -LiteralPath $Destination) {
    throw "ARCHIVE_DESTINATION_ALREADY_EXISTS: $Destination"
}

New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
$destinationLeaf = Split-Path -Leaf $Destination
$staging = Join-Path $destinationParent ($destinationLeaf + ".partial-" + [Guid]::NewGuid().ToString("N"))
$stagingCreated = $false

try {
New-Item -ItemType Directory -Path $staging | Out-Null
$stagingCreated = $true
$archiveRoot = $staging

$packageDestination = Join-Path $archiveRoot "package"
$codexDestination = Join-Path $archiveRoot "runtime\codex"
$terminalDestination = Join-Path $archiveRoot "runtime\windows-terminal"
$desktopDestination = Join-Path $archiveRoot "desktop"
foreach ($path in @($packageDestination, $codexDestination, $terminalDestination, $desktopDestination)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

Copy-ExactFiles -SourceRoot $packageRoot -RelativePaths $packageExpectedPaths -DestinationRoot $packageDestination
Copy-ExactFiles -SourceRoot $CodexRuntime -RelativePaths $codexExpectedPaths -DestinationRoot $codexDestination
Copy-ExactFiles -SourceRoot $terminalRoot `
    -RelativePaths @($terminalEntries | ForEach-Object { [string]$_.path }) `
    -DestinationRoot $terminalDestination

Copy-Item -LiteralPath $Shortcut -Destination (Join-Path $desktopDestination "Codex 输入框试验版.lnk") -Force
Copy-Item -LiteralPath $Launcher -Destination (Join-Path $desktopDestination "Open-Codex-S-Input-Canary.ps1") -Force
Copy-Item -LiteralPath $terminalManifestPath -Destination (Join-Path $archiveRoot "runtime\windows-terminal.manifest.sha256.json") -Force
Copy-Item -LiteralPath (Join-Path $packageRoot "PRESERVATION.md") -Destination (Join-Path $archiveRoot "DO_NOT_DELETE.md") -Force
Copy-Item -LiteralPath (Join-Path $packageRoot "tools\VERIFY.ps1") -Destination (Join-Path $archiveRoot "VERIFY.ps1") -Force

$manifestPath = Join-Path $archiveRoot "archive-manifest.json"
$root = (Resolve-Path -LiteralPath $archiveRoot).Path.TrimEnd('\')
$entries = Get-ChildItem -LiteralPath $root -File -Recurse -Force |
    Where-Object { $_.FullName -ne $manifestPath } |
    ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($root.Length).TrimStart('\').Replace('\', '/')
            bytes = $_.Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
        }
    } |
    Sort-Object path
if (@($entries).Count -ne [int]$deliveryManifest.local_archive.manifested_payload_file_count) {
    throw "ARCHIVE_PAYLOAD_FILE_COUNT_MISMATCH"
}

$manifest = [ordered]@{
    schema = "xinao.codex-input-bridge.local-archive.v1"
    status = "built_pending_independent_verification"
    created_at = (Get-Date).ToString("o")
    product = [ordered]@{
        codex = "0.144.5"
        windows_terminal = "v1.24.11911.0"
        user_acceptance = "可以，目前看没有问题；可以交付"
    }
    excluded_by_design = @(
        "CODEX_HOME, credentials, login data, conversations and session state",
        "Windows Terminal state.json and elevated-state.json",
        "Cargo/MSBuild build and incremental caches",
        "temporary worktrees, clones and test logs"
    )
    file_count = @($entries).Count
    files = @($entries)
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM

& (Join-Path $archiveRoot "VERIFY.ps1") -ArchiveRoot $archiveRoot -AllowPending
if ($LASTEXITCODE -ne 0) {
    throw "ARCHIVE_VERIFICATION_FAILED"
}

$manifest["status"] = "verified"
$manifest["verified_at"] = (Get-Date).ToString("o")
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM
& (Join-Path $archiveRoot "VERIFY.ps1") -ArchiveRoot $archiveRoot | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "ARCHIVE_FINAL_MANIFEST_VERIFICATION_FAILED"
}

$finalManifestSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash
Move-Item -LiteralPath $archiveRoot -Destination $Destination
$stagingCreated = $false

[ordered]@{
    archive = $Destination
    file_count = @($entries).Count
    manifest_sha256 = $finalManifestSha256
    status = "verified"
} | ConvertTo-Json
} catch {
    $failure = $_
    if ($stagingCreated -and (Test-Path -LiteralPath $staging -PathType Container)) {
        $resolvedStaging = (Resolve-Path -LiteralPath $staging).Path.TrimEnd('\')
        $resolvedParent = Split-Path -Parent $resolvedStaging
        $resolvedLeaf = Split-Path -Leaf $resolvedStaging
        $expectedParent = [IO.Path]::GetFullPath($destinationParent).TrimEnd('\')
        if (-not $resolvedParent.Equals($expectedParent, [StringComparison]::OrdinalIgnoreCase) -or
            -not $resolvedLeaf.StartsWith($destinationLeaf + ".partial-", [StringComparison]::OrdinalIgnoreCase)) {
            throw "ARCHIVE_STAGING_CLEANUP_REFUSED: $resolvedStaging"
        }
        Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
    }
    throw $failure
}
