# SENTINEL:XINAO_XINAOSURFACE_SOURCE_FAMILY_DEPLOY_CONSUMER_V1
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$VersionLabel = "",
    [switch]$SkipBuild,
    [switch]$KeepRepoBuildArtifacts,
    [switch]$PromoteShortcut
)

$ErrorActionPreference = "Stop"

function Assert-UnderRoot {
    param(
        [string]$Path,
        [string]$Root,
        [string]$Message
    )
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Message path=$fullPath root=$fullRoot"
    }
}

function Write-JsonFile {
    param([string]$Path, [object]$Payload)
    $dir = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $tmp = "$Path.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()).tmp"
    $Payload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

$manifestPath = Join-Path $RepoRoot "apps\xinao-surface\SURFACE_MANIFEST.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "MANIFEST_NOT_FOUND: $manifestPath"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($VersionLabel)) {
    $VersionLabel = [string]$manifest.version_label
}
if ([string]::IsNullOrWhiteSpace($VersionLabel)) {
    throw "VERSION_LABEL_MISSING"
}

$appRoot = Join-Path $RepoRoot ([string]$manifest.source_path)
$builderConfig = Join-Path $appRoot "electron-builder.yml"
$artifactRoot = [string]$manifest.deploy.target_root
$targetDir = Join-Path $artifactRoot ("app-s-mainline-$VersionLabel")
$buildRoot = Join-Path $appRoot "dist\win-unpacked"
$builtExe = Join-Path $buildRoot "XINAOSurface.exe"
$deployedExe = Join-Path $targetDir "XINAOSurface.exe"
$shortcutPath = [string]$manifest.deploy.shortcut_path
$shortcutUpdateScript = Join-Path $RepoRoot ([string]$manifest.deploy.shortcut_update_command)
$evidencePath = [string]$manifest.deploy.evidence_path
if ([string]::IsNullOrWhiteSpace($evidencePath)) {
    $evidencePath = Join-Path $RuntimeRoot "state\xinao_surface_deploy\latest.json"
}

Assert-UnderRoot -Path $appRoot -Root $RepoRoot -Message "APP_ROOT_OUTSIDE_REPO"
Assert-UnderRoot -Path $targetDir -Root $artifactRoot -Message "TARGET_DIR_OUTSIDE_ARTIFACT_ROOT"

$shortcutTargetBefore = ""
if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
    $shortcutBefore = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    $shortcutTargetBefore = [string]$shortcutBefore.TargetPath
}

if (-not $SkipBuild) {
    Push-Location $appRoot
    try {
        & npx.cmd electron-builder --dir --config $builderConfig --config.electronVersion=43.0.0
        if ($LASTEXITCODE -ne 0) {
            throw "ELECTRON_BUILDER_FAILED exit=$LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath $builtExe -PathType Leaf) -and -not ($SkipBuild -and (Test-Path -LiteralPath $deployedExe -PathType Leaf))) {
    throw "BUILT_OR_DEPLOYED_EXE_NOT_FOUND: built=$builtExe deployed=$deployedExe"
}

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
if (Test-Path -LiteralPath $builtExe -PathType Leaf) {
    if (Test-Path -LiteralPath $targetDir) {
        Assert-UnderRoot -Path $targetDir -Root $artifactRoot -Message "TARGET_DELETE_OUTSIDE_ARTIFACT_ROOT"
        Remove-Item -LiteralPath $targetDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    Copy-Item -Path (Join-Path $buildRoot "*") -Destination $targetDir -Recurse -Force
}

if (-not (Test-Path -LiteralPath $shortcutUpdateScript -PathType Leaf)) {
    throw "SHORTCUT_UPDATE_SCRIPT_NOT_FOUND: $shortcutUpdateScript"
}
if ($PromoteShortcut) {
    & $shortcutUpdateScript -TargetVersionLabel $VersionLabel -ArtifactRoot $artifactRoot -ShortcutPath $shortcutPath
    $shortcutExitCode = $LASTEXITCODE
    if ($null -ne $shortcutExitCode -and $shortcutExitCode -ne 0) {
        throw "SHORTCUT_UPDATE_FAILED exit=$shortcutExitCode"
    }
}

$shortcutTargetAfter = ""
if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
    $shortcutAfter = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    $shortcutTargetAfter = [string]$shortcutAfter.TargetPath
}

$checks = [ordered]@{
    manifest_present = (Test-Path -LiteralPath $manifestPath -PathType Leaf)
    build_or_existing_deploy_present = ((Test-Path -LiteralPath $builtExe -PathType Leaf) -or (Test-Path -LiteralPath $deployedExe -PathType Leaf))
    deployed_exe_present = (Test-Path -LiteralPath $deployedExe -PathType Leaf)
    shortcut_present = (Test-Path -LiteralPath $shortcutPath -PathType Leaf)
    shortcut_not_promoted_without_flag = ($PromoteShortcut -or $shortcutTargetAfter -eq $shortcutTargetBefore)
    target_under_artifact_root = $true
}
$validationPassed = -not ($checks.Values -contains $false)

$repoCommit = ""
try {
    $repoCommit = (& git -C $RepoRoot rev-parse --short HEAD).Trim()
} catch {
    $repoCommit = ""
}

$evidence = [ordered]@{
    schema_version = "xinao.codex_s.xinao_surface_deploy.v1"
    sentinel = "SENTINEL:XINAO_XINAOSURFACE_SOURCE_FAMILY_DEPLOYED"
    status = if ($validationPassed -and $PromoteShortcut) { "xinao_surface_deploy_ready" } elseif ($validationPassed) { "xinao_surface_candidate_deploy_ready_shortcut_not_promoted" } else { "xinao_surface_deploy_blocked" }
    action = "xinao_surface_build_deploy_verify_shortcut"
    app_id = [string]$manifest.app_id
    family_id = [string]$manifest.source_family.family_id
    version_label = $VersionLabel
    deployed_at = (Get-Date).ToString("o")
    repo_root = $RepoRoot
    repo_commit = $repoCommit
    manifest_path = $manifestPath
    build_root = $buildRoot
    target_dir = $targetDir
    deployed_exe = $deployedExe
    shortcut_path = $shortcutPath
    shortcut_promoted = [bool]$PromoteShortcut
    shortcut_target_before = $shortcutTargetBefore
    shortcut_target_after = $shortcutTargetAfter
    shortcut_promotion_policy = "manual_promote_after_feature_parity_left_sidebar_event_stream"
    manifest_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash
    deployed_exe_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $deployedExe).Hash
    validation = [ordered]@{
        passed = $validationPassed
        checks = $checks
    }
    completion_claim_allowed = $false
    not_user_completion = $true
    not_completion_decision = $true
    not_execution_controller = $true
}
Write-JsonFile -Path $evidencePath -Payload $evidence

if (-not $KeepRepoBuildArtifacts) {
    $distPath = Join-Path $appRoot "dist"
    if (Test-Path -LiteralPath $distPath) {
        Assert-UnderRoot -Path $distPath -Root $appRoot -Message "DIST_DELETE_OUTSIDE_APP_ROOT"
        Remove-Item -LiteralPath $distPath -Recurse -Force
    }
}

Write-Output "xinao_surface_deploy_latest=$evidencePath"
Write-Output "xinao_surface_deployed_exe=$deployedExe"
Write-Output "xinao_surface_shortcut_promoted=$([bool]$PromoteShortcut)"
Write-Output "validation_result=$(if ($validationPassed) { 'PASS' } else { 'FAIL' })"
Write-Output "SENTINEL:XINAO_XINAOSURFACE_SOURCE_FAMILY_DEPLOYED"
if (-not $validationPassed) {
    exit 1
}
