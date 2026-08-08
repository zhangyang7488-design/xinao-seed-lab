#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$AgentDir = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s',
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSHermesCompatibilityPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

$target = Get-NormalizedPiSHermesCompatibilityPath -Path $AgentDir
$activeTargets = @(
    Get-NormalizedPiSHermesCompatibilityPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s')
    Get-NormalizedPiSHermesCompatibilityPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-b')
)
$labParents = @(
    Get-NormalizedPiSHermesCompatibilityPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
    Get-NormalizedPiSHermesCompatibilityPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-b')
)
$targetParent = Get-NormalizedPiSHermesCompatibilityPath -Path (Split-Path -Parent $target)
if ($target -notin $activeTargets -and $targetParent -notin $labParents) {
    throw "PI_HERMES_PATCH_TARGET_OUTSIDE_MANAGED_PROFILE: $target"
}

$packageRoot = Join-Path $target 'npm\node_modules\pi-hermes-memory'
$packageJsonPath = Join-Path $packageRoot 'package.json'
$sourcePath = Join-Path $packageRoot 'src\store\session-parser.ts'
foreach ($required in @($packageJsonPath,$sourcePath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_HERMES_PATCH_SOURCE_MISSING: $required"
    }
}

$package = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$package.name -cne 'pi-hermes-memory' -or [string]$package.version -cne '0.9.4') {
    throw "PI_S_HERMES_PATCH_VERSION_UNSUPPORTED: $($package.name)@$($package.version)"
}

$upstreamHash = '09f32c1a2ccd9ac4234fd0474fdf1a3388ef9019a02d8104a5d05286966febf6'
$patchedHash = 'ce95cf4f1e1f953948e4d6395ca270b0641ddb99ee9481783315ea55e76299b6'
$beforeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
$changed = $false

if ($beforeHash -ceq $upstreamHash) {
    if ($VerifyOnly) {
        throw "PI_S_HERMES_PATCH_NOT_APPLIED: $sourcePath"
    }
    $source = [IO.File]::ReadAllText($sourcePath,[Text.UTF8Encoding]::new($false))
    $anchor = "  for (const entry of fs.readdirSync(sessionsDir)) {`n    const entryPath = path.join(sessionsDir, entry);"
    $replacement = @(
        "  for (const entry of fs.readdirSync(sessionsDir)) {"
        "    // pi-subagents writes transcript artifacts beside Pi sessions. They are not"
        "    // Pi v3 session JSONL and must not be parsed as session history."
        "    if (entry === 'subagent-artifacts') continue;"
        "    const entryPath = path.join(sessionsDir, entry);"
    ) -join "`n"
    if (-not $source.Contains($anchor)) { throw 'PI_S_HERMES_PATCH_ANCHOR_MISSING' }
    $updated = $source.Replace($anchor,$replacement)
    if ($updated -ceq $source) { throw 'PI_S_HERMES_PATCH_NO_CHANGE' }
    [IO.File]::WriteAllText($sourcePath,$updated,[Text.UTF8Encoding]::new($false))
    $changed = $true
} elseif ($beforeHash -cne $patchedHash) {
    throw "PI_S_HERMES_PATCH_SOURCE_CONFLICT: expected=$upstreamHash|$patchedHash actual=$beforeHash"
}

$afterHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
if ($afterHash -cne $patchedHash) {
    throw "PI_S_HERMES_PATCH_VERIFY_FAILED: expected=$patchedHash actual=$afterHash"
}
$verified = [IO.File]::ReadAllText($sourcePath,[Text.UTF8Encoding]::new($false))
if (-not $verified.Contains("if (entry === 'subagent-artifacts') continue;")) {
    throw 'PI_S_HERMES_PATCH_SEMANTIC_VERIFY_FAILED'
}

[pscustomobject]@{
    schema = 'xinao.pi_s_hermes_session_compatibility.v1'
    patch_id = 'pi-hermes-memory-0.9.4-ignore-subagent-artifacts-v1'
    agent_dir = $target
    package = 'pi-hermes-memory@0.9.4'
    source_path = $sourcePath
    before_sha256 = $beforeHash
    after_sha256 = $afterHash
    changed = $changed
    verify_only = [bool]$VerifyOnly
    subagent_transcripts_parsed_as_pi_sessions = $false
    child_artifacts_deleted = $false
} | ConvertTo-Json -Depth 5
