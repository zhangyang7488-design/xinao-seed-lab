#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$AgentDir = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s',
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSCompatibilityPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-PiSCompatibilityNoReparsePath {
    param([Parameter(Mandatory)][string]$Path)
    $cursor = Get-NormalizedPiSCompatibilityPath -Path $Path
    $root = [IO.Path]::GetPathRoot($cursor)
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "PI_S_SUBAGENTS_PATCH_REPARSE_POINT_REJECTED: $cursor"
            }
        }
        if ([string]::Equals($cursor,$root,[StringComparison]::OrdinalIgnoreCase)) { break }
        $parent = Split-Path -Parent $cursor
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ceq $cursor) { break }
        $cursor = $parent
    }
}

$target = Get-NormalizedPiSCompatibilityPath -Path $AgentDir
$activeTargets = @(
    Get-NormalizedPiSCompatibilityPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s')
    Get-NormalizedPiSCompatibilityPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-b')
)
$labParents = @(
    Get-NormalizedPiSCompatibilityPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
    Get-NormalizedPiSCompatibilityPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-b')
)
$targetParent = Get-NormalizedPiSCompatibilityPath -Path (Split-Path -Parent $target)
if ($target -notin $activeTargets -and $targetParent -notin $labParents) {
    throw "PI_SUBAGENTS_PATCH_TARGET_OUTSIDE_MANAGED_PROFILE: $target"
}

$packageRoot = Join-Path $target 'npm\node_modules\pi-subagents'
$packageJsonPath = Join-Path $packageRoot 'package.json'
$asyncSourcePath = Join-Path $packageRoot 'src\runs\foreground\subagent-executor.ts'
$singleOutputSourcePath = Join-Path $packageRoot 'src\runs\shared\single-output.ts'
foreach ($pathToValidate in @($packageRoot,$packageJsonPath,$asyncSourcePath,$singleOutputSourcePath)) {
    Assert-PiSCompatibilityNoReparsePath -Path $pathToValidate
}
foreach ($required in @($packageJsonPath,$asyncSourcePath,$singleOutputSourcePath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_SUBAGENTS_PATCH_SOURCE_MISSING: $required"
    }
}

$package = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
$packageVersion = [string]$package.version
if (
    [string]$package.name -cne 'pi-subagents' -or
    $packageVersion -notin @('0.43.0','0.44.0')
) {
    throw "PI_S_SUBAGENTS_PATCH_VERSION_UNSUPPORTED: $($package.name)@$($package.version)"
}

$asyncUpstreamHash = if ($packageVersion -ceq '0.44.0') {
    '59216ed57a01b240359bf68a3ef5ddd80a981d76ff31760095e6acf2c1b34fa1'
} else {
    '412b2a6eefb2d796fcfe1d4b933726b469cc0033db7f533ed09ecca95ec48332'
}
$asyncPatchedHash = if ($packageVersion -ceq '0.44.0') {
    $asyncUpstreamHash
} else {
    '15e3e072431e43fa774d4d4993c606e0c671841539606fac90f9b86f94777b48'
}
$asyncOwnerSessionStopCombinedHash = '6022d233c27a0f796581ba6ebda282c736cf0442771f41a89ad290912898a220'
$asyncFilesystemPolicyCombinedHash = 'f6e1ed79bfc0373e77efb0754dcfcddf643942d406d1c8371d57a5c3203f4fed'
$asyncHighCapacityCombinedHash = '411f4f275f164786f2388fb001d67954366d69fd5188a996b1a79d300dcd320e'
$asyncAcceptedHashes = if ($packageVersion -ceq '0.44.0') {
    @($asyncUpstreamHash,$asyncOwnerSessionStopCombinedHash,$asyncFilesystemPolicyCombinedHash,$asyncHighCapacityCombinedHash)
} else {
    @($asyncUpstreamHash,$asyncPatchedHash)
}
$singleOutputUpstreamHash = 'f2af95cd15e1fd021bff802812043704d5569c5eeed9a8f13741174654de4e08'
$singleOutputPatchedHash = 'aa63de8ffd7e2ce671560c6cbded541e475bdfa700e33c069042b32af0c2605b'
$asyncBeforeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $asyncSourcePath).Hash.ToLowerInvariant()
$singleOutputBeforeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $singleOutputSourcePath).Hash.ToLowerInvariant()
$changed = $false

if ($packageVersion -ceq '0.44.0') {
    if ($asyncBeforeHash -notin $asyncAcceptedHashes) {
        throw "PI_S_SUBAGENTS_PATCH_SOURCE_CONFLICT: expected=$($asyncAcceptedHashes -join '|') actual=$asyncBeforeHash"
    }
} elseif ($asyncBeforeHash -ceq $asyncUpstreamHash) {
    if ($VerifyOnly) {
        throw "PI_S_SUBAGENTS_PATCH_NOT_APPLIED: $asyncSourcePath"
    }
    $source = [IO.File]::ReadAllText($asyncSourcePath,[Text.UTF8Encoding]::new($false))
    $upstreamLine = "`t`t`t`tconst workflowRunId = _id;"
    $replacement = @(
        "`t`t`t`t// Provider tool-call IDs may contain characters such as ``|`` that are"
        "`t`t`t`t// illegal in Windows path segments. An async workflow ID is a public"
        "`t`t`t`t// runtime handle, not the provider's tool-call identity, so generate a"
        "`t`t`t`t// portable handle before it reaches async directories or result files."
        ("`t`t`t`t" + 'const workflowRunId = `workflow-${randomUUID()}`;')
    ) -join "`n"
    if (-not $source.Contains($upstreamLine)) {
        throw 'PI_S_SUBAGENTS_PATCH_ANCHOR_MISSING'
    }
    $updated = $source.Replace($upstreamLine,$replacement)
    if ($updated -ceq $source) { throw 'PI_S_SUBAGENTS_PATCH_NO_CHANGE' }
    [IO.File]::WriteAllText($asyncSourcePath,$updated,[Text.UTF8Encoding]::new($false))
    $changed = $true
} elseif ($asyncBeforeHash -cne $asyncPatchedHash) {
    throw "PI_S_SUBAGENTS_PATCH_SOURCE_CONFLICT: expected=$asyncUpstreamHash|$asyncPatchedHash actual=$asyncBeforeHash"
}

$asyncAfterHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $asyncSourcePath).Hash.ToLowerInvariant()
if ($packageVersion -ceq '0.44.0' -and $asyncAfterHash -notin $asyncAcceptedHashes) {
    throw "PI_S_SUBAGENTS_PATCH_VERIFY_FAILED: expected=$($asyncAcceptedHashes -join '|') actual=$asyncAfterHash"
}
if ($packageVersion -cne '0.44.0' -and $asyncAfterHash -cne $asyncPatchedHash) {
    throw "PI_S_SUBAGENTS_PATCH_VERIFY_FAILED: expected=$asyncPatchedHash actual=$asyncAfterHash"
}
$verified = [IO.File]::ReadAllText($asyncSourcePath,[Text.UTF8Encoding]::new($false))
if (
    $verified.Contains('const workflowRunId = _id;') -or
    (
        $packageVersion -ceq '0.44.0' -and
        -not $verified.Contains('const workflowRunId = randomUUID();')
    ) -or
    (
        $packageVersion -ceq '0.43.0' -and
        -not $verified.Contains('const workflowRunId = `workflow-${randomUUID()}`;')
    )
) {
    throw 'PI_S_SUBAGENTS_PATCH_SEMANTIC_VERIFY_FAILED'
}

if ($singleOutputBeforeHash -ceq $singleOutputUpstreamHash) {
    if ($VerifyOnly) {
        throw "PI_S_SUBAGENTS_SINGLE_OUTPUT_PATCH_NOT_APPLIED: $singleOutputSourcePath"
    }
    $source = [IO.File]::ReadAllText($singleOutputSourcePath,[Text.UTF8Encoding]::new($false))
    $snapshotAnchor = @(
        'export interface SingleOutputSnapshot {'
        "`texists: boolean;"
        "`tmtimeMs?: number;"
        "`tsize?: number;"
        '}'
        ''
        '/**'
    ) -join "`n"
    $snapshotReplacement = @(
        'export interface SingleOutputSnapshot {'
        "`texists: boolean;"
        "`tmtimeMs?: number;"
        "`tsize?: number;"
        '}'
        ''
        'function comparableOutputPath(filePath: string, cwd: string): string {'
        "`tlet normalized = filePath;"
        "`t" + 'if (process.platform === "win32" && normalized.startsWith("/") && !normalized.startsWith("//") && !normalized.includes("\\")) {'
        "`t`t" + 'const shellDrive = normalized.match(/^\/(?:mnt\/|cygdrive\/)?([a-z])(?:\/(.*))?$/i);'
        "`t`tif (shellDrive) {"
        "`t`t`t" + 'const suffix = shellDrive[2]?.replaceAll("/", "\\");'
        "`t`t`t" + 'normalized = `${shellDrive[1]!.toUpperCase()}:\\${suffix ?? ""}`;'
        "`t`t}"
        "`t}"
        "`tconst resolved = path.resolve(cwd, normalized);"
        "`t" + 'return process.platform === "win32" ? resolved.toLowerCase() : resolved;'
        '}'
        ''
        '/**'
    ) -join "`n"
    $targetAnchor = @(
        "`tif (!messages?.length || !outputPath) return undefined;"
        "`tconst resolvedTarget = path.resolve(cwd ?? `".`", outputPath);"
        "`t" + 'const comparableTarget = process.platform === "win32" ? resolvedTarget.toLowerCase() : resolvedTarget;'
    ) -join "`n"
    $targetReplacement = @(
        "`tif (!messages?.length || !outputPath) return undefined;"
        "`tconst comparisonCwd = cwd ?? `".`";"
        "`tconst comparableTarget = comparableOutputPath(outputPath, comparisonCwd);"
    ) -join "`n"
    $writeAnchor = @(
        "`t`t`tif (typeof args.path !== `"string`" || typeof args.content !== `"string`") continue;"
        "`t`t`tconst resolvedWritePath = path.resolve(cwd ?? `".`", args.path);"
        "`t`t`t" + 'const comparableWritePath = process.platform === "win32" ? resolvedWritePath.toLowerCase() : resolvedWritePath;'
    ) -join "`n"
    $writeReplacement = @(
        "`t`t`tif (typeof args.path !== `"string`" || typeof args.content !== `"string`") continue;"
        "`t`t`tconst comparableWritePath = comparableOutputPath(args.path, comparisonCwd);"
    ) -join "`n"
    foreach ($anchor in @($snapshotAnchor,$targetAnchor,$writeAnchor)) {
        if (-not $source.Contains($anchor)) { throw 'PI_S_SUBAGENTS_SINGLE_OUTPUT_PATCH_ANCHOR_MISSING' }
    }
    $updated = $source.Replace($snapshotAnchor,$snapshotReplacement).Replace($targetAnchor,$targetReplacement).Replace($writeAnchor,$writeReplacement)
    if ($updated -ceq $source) { throw 'PI_S_SUBAGENTS_SINGLE_OUTPUT_PATCH_NO_CHANGE' }
    [IO.File]::WriteAllText($singleOutputSourcePath,$updated,[Text.UTF8Encoding]::new($false))
    $changed = $true
} elseif ($singleOutputBeforeHash -cne $singleOutputPatchedHash) {
    throw "PI_S_SUBAGENTS_SINGLE_OUTPUT_PATCH_SOURCE_CONFLICT: expected=$singleOutputUpstreamHash|$singleOutputPatchedHash actual=$singleOutputBeforeHash"
}

$singleOutputAfterHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $singleOutputSourcePath).Hash.ToLowerInvariant()
if ($singleOutputAfterHash -cne $singleOutputPatchedHash) {
    throw "PI_S_SUBAGENTS_SINGLE_OUTPUT_PATCH_VERIFY_FAILED: expected=$singleOutputPatchedHash actual=$singleOutputAfterHash"
}
$singleOutputVerified = [IO.File]::ReadAllText($singleOutputSourcePath,[Text.UTF8Encoding]::new($false))
if (
    -not $singleOutputVerified.Contains('function comparableOutputPath(filePath: string, cwd: string): string') -or
    -not $singleOutputVerified.Contains('normalized.match(/^\/(?:mnt\/|cygdrive\/)?([a-z])(?:\/(.*))?$/i)') -or
    $singleOutputVerified.Contains('const resolvedWritePath = path.resolve(cwd ?? ".", args.path);')
) {
    throw 'PI_S_SUBAGENTS_SINGLE_OUTPUT_PATCH_SEMANTIC_VERIFY_FAILED'
}

[pscustomobject]@{
    schema = 'xinao.pi_s_subagents_windows_compatibility.v1'
    patch_id = $(if ($packageVersion -ceq '0.44.0') { 'pi-subagents-0.44.0-windows-compatibility-v3' } else { 'pi-subagents-0.43.0-windows-compatibility-v2' })
    agent_dir = $target
    package = "pi-subagents@$packageVersion"
    source_path = $asyncSourcePath
    source_paths = @($asyncSourcePath,$singleOutputSourcePath)
    before_sha256 = $asyncBeforeHash
    after_sha256 = $asyncAfterHash
    single_output_before_sha256 = $singleOutputBeforeHash
    single_output_after_sha256 = $singleOutputAfterHash
    changed = $changed
    verify_only = [bool]$VerifyOnly
    provider_tool_id_used_as_path = $false
    upstream_portable_workflow_id = [bool]($packageVersion -ceq '0.44.0')
    owner_session_stop_combination_accepted = [bool]($packageVersion -ceq '0.44.0' -and $asyncAfterHash -ceq $asyncOwnerSessionStopCombinedHash)
    filesystem_policy_combination_accepted = [bool]($packageVersion -ceq '0.44.0' -and $asyncAfterHash -ceq $asyncFilesystemPolicyCombinedHash)
    high_capacity_combination_accepted = [bool]($packageVersion -ceq '0.44.0' -and $asyncAfterHash -ceq $asyncHighCapacityCombinedHash)
    msys_drive_path_authorship_equivalence = $true
} | ConvertTo-Json -Depth 5
