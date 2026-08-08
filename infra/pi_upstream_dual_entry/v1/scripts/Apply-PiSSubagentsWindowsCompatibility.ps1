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

$target = Get-NormalizedPiSCompatibilityPath -Path $AgentDir
$activeTarget = Get-NormalizedPiSCompatibilityPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s')
$labParent = Get-NormalizedPiSCompatibilityPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
$targetParent = Get-NormalizedPiSCompatibilityPath -Path (Split-Path -Parent $target)
if ($target -ine $activeTarget -and $targetParent -ine $labParent) {
    throw "PI_S_SUBAGENTS_PATCH_TARGET_OUTSIDE_PRIME_S: $target"
}

$packageRoot = Join-Path $target 'npm\node_modules\pi-subagents'
$packageJsonPath = Join-Path $packageRoot 'package.json'
$sourcePath = Join-Path $packageRoot 'src\runs\foreground\subagent-executor.ts'
foreach ($required in @($packageJsonPath,$sourcePath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_SUBAGENTS_PATCH_SOURCE_MISSING: $required"
    }
}

$package = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$package.name -cne 'pi-subagents' -or [string]$package.version -cne '0.43.0') {
    throw "PI_S_SUBAGENTS_PATCH_VERSION_UNSUPPORTED: $($package.name)@$($package.version)"
}

$upstreamHash = '412b2a6eefb2d796fcfe1d4b933726b469cc0033db7f533ed09ecca95ec48332'
$patchedHash = '15e3e072431e43fa774d4d4993c606e0c671841539606fac90f9b86f94777b48'
$beforeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
$changed = $false

if ($beforeHash -ceq $upstreamHash) {
    if ($VerifyOnly) {
        throw "PI_S_SUBAGENTS_PATCH_NOT_APPLIED: $sourcePath"
    }
    $source = [IO.File]::ReadAllText($sourcePath,[Text.UTF8Encoding]::new($false))
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
    [IO.File]::WriteAllText($sourcePath,$updated,[Text.UTF8Encoding]::new($false))
    $changed = $true
} elseif ($beforeHash -cne $patchedHash) {
    throw "PI_S_SUBAGENTS_PATCH_SOURCE_CONFLICT: expected=$upstreamHash|$patchedHash actual=$beforeHash"
}

$afterHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
if ($afterHash -cne $patchedHash) {
    throw "PI_S_SUBAGENTS_PATCH_VERIFY_FAILED: expected=$patchedHash actual=$afterHash"
}
$verified = [IO.File]::ReadAllText($sourcePath,[Text.UTF8Encoding]::new($false))
if ($verified.Contains('const workflowRunId = _id;') -or -not $verified.Contains('const workflowRunId = `workflow-${randomUUID()}`;')) {
    throw 'PI_S_SUBAGENTS_PATCH_SEMANTIC_VERIFY_FAILED'
}

[pscustomobject]@{
    schema = 'xinao.pi_s_subagents_windows_compatibility.v1'
    patch_id = 'pi-subagents-0.43.0-portable-async-workflow-id-v1'
    agent_dir = $target
    package = 'pi-subagents@0.43.0'
    source_path = $sourcePath
    before_sha256 = $beforeHash
    after_sha256 = $afterHash
    changed = $changed
    verify_only = [bool]$VerifyOnly
    provider_tool_id_used_as_path = $false
} | ConvertTo-Json -Depth 5
