#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$AgentDir = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s',
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSOwnerStopPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-PiSOwnerStopNoReparsePath {
    param([Parameter(Mandatory)][string]$Path)
    $cursor = Get-NormalizedPiSOwnerStopPath -Path $Path
    $root = [IO.Path]::GetPathRoot($cursor)
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "PI_S_OWNER_STOP_PATCH_REPARSE_POINT_REJECTED: $cursor"
            }
        }
        if ([string]::Equals($cursor,$root,[StringComparison]::OrdinalIgnoreCase)) { break }
        $parent = Split-Path -Parent $cursor
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ceq $cursor) { break }
        $cursor = $parent
    }
}

$target = Get-NormalizedPiSOwnerStopPath -Path $AgentDir
$activeTarget = Get-NormalizedPiSOwnerStopPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s')
$labParent = Get-NormalizedPiSOwnerStopPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
$targetParent = Get-NormalizedPiSOwnerStopPath -Path (Split-Path -Parent $target)
if ($target -cne $activeTarget -and $targetParent -cne $labParent) {
    throw "PI_S_OWNER_STOP_PATCH_TARGET_OUTSIDE_MAIN_PROFILE: $target"
}

$packageRoot = Join-Path $target 'npm\node_modules\pi-subagents'
$packageJsonPath = Join-Path $packageRoot 'package.json'
$patchPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'patches\pi-subagents-0.44.0-owner-session-stop.patch'
$files = [ordered]@{
    'src\shared\types.ts' = @{
        Upstream = '5d9db5524d03dd16b3f23751f268e4833658ee5bbd169b87c4a213accd19f50a'
        Patched = 'd04043d8cbcdc9ee6e6a6d85b3e09d5282cd16a2b614a69758476ae13916fd09'
        Final = '2e80765b425f6a8481cb559759b313ae679e2f67959a3c0f61214e1d529d6a33'
        Capacity = 'acb00bd809ebaaf65bd67f300444ce314d6255739af5f140c8fed640ed8791ec'
    }
    'src\extension\index.ts' = @{
        Upstream = '357051982f4fe95f00c5970ac2626c4449943b1cc586d01a97dc3000250c846c'
        Patched = '5170c2f15a74bcfc4edbfc2b20eef8494c6fb3836553da43c698596e357b7009'
        Final = '5170c2f15a74bcfc4edbfc2b20eef8494c6fb3836553da43c698596e357b7009'
        Capacity = '2d3d3c61eb59186a2abdd59b235a834abe5ac7daca64c9a504bb902eb78ed5a9'
    }
    'src\extension\rpc.ts' = @{
        Upstream = '5c0b683c8e7a59fd5fa730e10039ff8b9e84b465af6202c52405ec5798179a93'
        Patched = '397d971cc7ec1ef1df846426c654d343a3fa91ab718eec24a8e78a12ad0fc0a7'
        Final = '397d971cc7ec1ef1df846426c654d343a3fa91ab718eec24a8e78a12ad0fc0a7'
        Capacity = '637d4c70a99f229c11e743a6b2e41569b91217f36f002958bf3ad3ed2cae5599'
    }
    'src\runs\foreground\subagent-executor.ts' = @{
        Upstream = '59216ed57a01b240359bf68a3ef5ddd80a981d76ff31760095e6acf2c1b34fa1'
        Patched = '6022d233c27a0f796581ba6ebda282c736cf0442771f41a89ad290912898a220'
        Final = 'f6e1ed79bfc0373e77efb0754dcfcddf643942d406d1c8371d57a5c3203f4fed'
        Capacity = '411f4f275f164786f2388fb001d67954366d69fd5188a996b1a79d300dcd320e'
    }
    'src\shared\post-exit-stdio-guard.ts' = @{
        Upstream = '19cd314075b019a2d0a18ff46b4c1a11cc211dc5d52a3dca40cd8434dc992b14'
        Patched = 'c8900cba6d57070f8d2adfd065a349fbc8d906294a83e80bd8284a24fce8b4d2'
        Final = 'c8900cba6d57070f8d2adfd065a349fbc8d906294a83e80bd8284a24fce8b4d2'
        Capacity = 'c8900cba6d57070f8d2adfd065a349fbc8d906294a83e80bd8284a24fce8b4d2'
    }
    'src\runs\background\subagent-runner.ts' = @{
        Upstream = 'e0fe620fa0b598e0eed2131ae92059d02bf3be72c2b6ed9d6956be1cc05cc852'
        Patched = '90886336f176488db2bfc945fb80072c88c04941dd703b2a5ae9e406566e538c'
        Final = '599eb6faad6029272d26b41aa9ed8c6c0cd1b389230cd5fe46203a555312382d'
        Capacity = 'ae581fd8367e8ae32c712afb3cc405b2fa9e6b686b6b14f81af54d870c550f86'
    }
}

Assert-PiSOwnerStopNoReparsePath -Path $packageRoot
Assert-PiSOwnerStopNoReparsePath -Path $packageJsonPath
foreach ($relative in $files.Keys) {
    Assert-PiSOwnerStopNoReparsePath -Path (Join-Path $packageRoot $relative)
}

foreach ($required in @($packageJsonPath,$patchPath) + @($files.Keys | ForEach-Object { Join-Path $packageRoot $_ })) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_OWNER_STOP_PATCH_SOURCE_MISSING: $required"
    }
}

$package = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$package.name -cne 'pi-subagents' -or [string]$package.version -cne '0.44.0') {
    throw "PI_S_OWNER_STOP_PATCH_VERSION_UNSUPPORTED: $($package.name)@$($package.version)"
}

$before = [ordered]@{}
foreach ($relative in $files.Keys) {
    $before[$relative] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $packageRoot $relative)).Hash.ToLowerInvariant()
}
$allUpstream = @($files.Keys | Where-Object { $before[$_] -ceq $files[$_].Upstream }).Count -eq $files.Count
$allPatched = @($files.Keys | Where-Object { $before[$_] -ceq $files[$_].Patched }).Count -eq $files.Count
$allFinal = @($files.Keys | Where-Object { $before[$_] -ceq $files[$_].Final }).Count -eq $files.Count
$allCapacity = @($files.Keys | Where-Object { $before[$_] -ceq $files[$_].Capacity }).Count -eq $files.Count
$legacyV1Files = @(
    'src\shared\types.ts',
    'src\extension\index.ts',
    'src\extension\rpc.ts',
    'src\runs\foreground\subagent-executor.ts'
)
$processTreeFiles = @(
    'src\shared\post-exit-stdio-guard.ts',
    'src\runs\background\subagent-runner.ts'
)
$legacyV1Patched = (
    @($legacyV1Files | Where-Object { $before[$_] -ceq $files[$_].Patched }).Count -eq $legacyV1Files.Count -and
    @($processTreeFiles | Where-Object { $before[$_] -ceq $files[$_].Upstream }).Count -eq $processTreeFiles.Count
)
$changed = $false

if ($allUpstream) {
    if ($VerifyOnly) { throw "PI_S_OWNER_STOP_PATCH_NOT_APPLIED: $packageRoot" }
    & git -c core.autocrlf=false -C $packageRoot apply --check $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'PI_S_OWNER_STOP_PATCH_CHECK_FAILED' }
    & git -c core.autocrlf=false -C $packageRoot apply $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'PI_S_OWNER_STOP_PATCH_APPLY_FAILED' }
    $changed = $true
} elseif ($legacyV1Patched) {
    if ($VerifyOnly) { throw "PI_S_OWNER_STOP_PROCESS_TREE_PATCH_NOT_APPLIED: $packageRoot" }
    $includeArgs = @(
        '--include=src/shared/post-exit-stdio-guard.ts',
        '--include=src/runs/background/subagent-runner.ts'
    )
    & git -c core.autocrlf=false -C $packageRoot apply --check @includeArgs $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'PI_S_OWNER_STOP_PROCESS_TREE_PATCH_CHECK_FAILED' }
    & git -c core.autocrlf=false -C $packageRoot apply @includeArgs $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'PI_S_OWNER_STOP_PROCESS_TREE_PATCH_APPLY_FAILED' }
    $changed = $true
} elseif (-not $allPatched -and -not $allFinal -and -not $allCapacity) {
    $actual = @($before.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ';'
    throw "PI_S_OWNER_STOP_PATCH_SOURCE_CONFLICT: $actual"
}

$after = [ordered]@{}
foreach ($relative in $files.Keys) {
    $after[$relative] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $packageRoot $relative)).Hash.ToLowerInvariant()
    $expected = if ($allCapacity) { $files[$relative].Capacity } elseif ($allFinal) { $files[$relative].Final } else { $files[$relative].Patched }
    if ($after[$relative] -cne $expected) {
        throw "PI_S_OWNER_STOP_PATCH_VERIFY_FAILED: file=$relative expected=$expected actual=$($after[$relative])"
    }
}

$rpcText = Get-Content -Raw -LiteralPath (Join-Path $packageRoot 'src\extension\rpc.ts') -Encoding UTF8
$executorText = Get-Content -Raw -LiteralPath (Join-Path $packageRoot 'src\runs\foreground\subagent-executor.ts') -Encoding UTF8
$typesText = Get-Content -Raw -LiteralPath (Join-Path $packageRoot 'src\shared\types.ts') -Encoding UTF8
$processGuardText = Get-Content -Raw -LiteralPath (Join-Path $packageRoot 'src\shared\post-exit-stdio-guard.ts') -Encoding UTF8
$runnerText = Get-Content -Raw -LiteralPath (Join-Path $packageRoot 'src\runs\background\subagent-runner.ts') -Encoding UTF8
if (
    $rpcText -notmatch '"stop-session"' -or
    $rpcText -notmatch 'stopOwnerSession' -or
    $rpcText -notmatch 'readProcessTerminal' -or
    $rpcText -notmatch 'sessionStopFences\.add' -or
    $rpcText -notmatch 'owner mismatch' -or
    $rpcText -notmatch 'ownerStops\.delete' -or
    $executorText -notmatch 'Subagent launch rejected: the owning Pi session is stopping\.' -or
    ([regex]::Matches($executorText,'sessionStopFenced\(\)')).Count -lt 3 -or
    $executorText -notmatch 'async launch commit fence' -or
    $typesText -notmatch 'sessionStopFences\?: Set<string>' -or
    $processGuardText -notmatch 'spawnSync\("taskkill", \["/F", "/T", "/PID"' -or
    $processGuardText -notmatch 'export function tryStopChildTree' -or
    $runnerText -notmatch 'registerStop\?\.\(\(\) => \{[\s\S]{0,400}tryStopChildTree\(child\)'
) {
    throw 'PI_S_OWNER_STOP_PATCH_SEMANTIC_VERIFY_FAILED'
}

[pscustomobject]@{
    schema = 'xinao.pi_s_subagents_owner_session_stop_compatibility.v2'
    patch_id = 'pi-subagents-0.44.0-owner-session-stop-v2'
    agent_dir = $target
    package = 'pi-subagents@0.44.0'
    patch_path = $patchPath
    before_sha256 = $before
    after_sha256 = $after
    changed = $changed
    verify_only = [bool]$VerifyOnly
    owner_session_stop_rpc = $true
    exact_owner_union = $true
    new_launch_fence = $true
    in_process_workflow_abort = $true
    detached_process_terminal_observation = $true
    windows_stop_owns_child_process_tree = $true
    stop_timeout_remains_honest_partial = $true
    filesystem_policy_combination_accepted = [bool]$allFinal
    high_capacity_combination_accepted = [bool]$allCapacity
    cold_backup_modified = $false
} | ConvertTo-Json -Depth 6
