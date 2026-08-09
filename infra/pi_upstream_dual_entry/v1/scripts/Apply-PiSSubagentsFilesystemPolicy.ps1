#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$AgentDir = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s',
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSFilesystemPolicyPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\','/')
}

function Assert-PiSFilesystemPolicyNoReparsePath {
    param([Parameter(Mandatory)][string]$Path)
    $cursor = Get-NormalizedPiSFilesystemPolicyPath -Path $Path
    $root = [IO.Path]::GetPathRoot($cursor)
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "PI_S_FILESYSTEM_POLICY_PATCH_REPARSE_POINT_REJECTED: $cursor"
            }
        }
        if ([string]::Equals($cursor,$root,[StringComparison]::OrdinalIgnoreCase)) { break }
        $parent = Split-Path -Parent $cursor
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ceq $cursor) { break }
        $cursor = $parent
    }
}

$target = Get-NormalizedPiSFilesystemPolicyPath -Path $AgentDir
$activeTarget = Get-NormalizedPiSFilesystemPolicyPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s')
$labParent = Get-NormalizedPiSFilesystemPolicyPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
$targetParent = Get-NormalizedPiSFilesystemPolicyPath -Path (Split-Path -Parent $target)
if ($target -cne $activeTarget -and $targetParent -cne $labParent) {
    throw "PI_S_FILESYSTEM_POLICY_PATCH_TARGET_OUTSIDE_MAIN_PROFILE: $target"
}

$packageRoot = Join-Path $target 'npm\node_modules\pi-subagents'
$packageJsonPath = Join-Path $packageRoot 'package.json'
$patchPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'patches\pi-subagents-0.44.0-filesystem-policy.patch'
$expectedPatchHash = '37244821214a76d8f1cdc03e6a8105be95b2d862ee97cc79a9ca04967f1f21b5'
$files = [ordered]@{
    'src\extension\schemas.ts' = @{ Owner = '32c99f0e6614d747bd4dc3fd5ee84f47e4d600d3adb646b795413da10fe3b81e'; Final = 'ddd81da1c7d0063acadfe692378b640bf87418c699b3b471e5e74b7eac069bcc'; Capacity = 'd83e7ba5311dfc2d4b0316365ff934929abe6e1ce59ffeea5d4134c242b33302' }
    'src\runs\background\async-execution.ts' = @{ Owner = 'db7ed1d5d9e33dd1a81267ca9db775c7d3204d3f0f2e1eb2b38794150f0f3287'; Final = 'b8a272c050155439dc405da71d2cf5c21002744357b1c37e5f046c399cde10e7'; Capacity = 'ef0ba69b0c6d083b27e5f05336031556ad0a7a2646cfb018ec91a3100c8eadf4' }
    'src\runs\background\async-resume.ts' = @{ Owner = '8ba25898299ed73da20e1f66742aece1b25f4a5e852cf126f8d151373388ced9'; Final = 'ae3a301b1dab8ec0b8348def3111eb5382a8006d042b0726c313e8d83ef806e3'; Capacity = 'a32eb20de710ec4b443b1027d8bff76afc8d6e853d4d4e72783501b839764661' }
    'src\runs\background\stale-run-reconciler.ts' = @{ Owner = '2cd7978d8d5c1499d721882554cb2002f9cb926e39ec0ab2ae6cfa17b003ccc6'; Final = '4c5d1fb4e6ae436b7a03b9003867b04ea222e14c268f40f9b51eaa45cadedf9f'; Capacity = '4c5d1fb4e6ae436b7a03b9003867b04ea222e14c268f40f9b51eaa45cadedf9f' }
    'src\runs\background\subagent-runner.ts' = @{ Owner = '90886336f176488db2bfc945fb80072c88c04941dd703b2a5ae9e406566e538c'; Final = '599eb6faad6029272d26b41aa9ed8c6c0cd1b389230cd5fe46203a555312382d'; Capacity = 'ae581fd8367e8ae32c712afb3cc405b2fa9e6b686b6b14f81af54d870c550f86' }
    'src\runs\foreground\chain-execution.ts' = @{ Owner = 'a78410a15f7bc330fa50d490cbf7a36aeaef9a9f56311c0b32986839a70a02f4'; Final = 'c810388939735b169bba11c9cb8359803e063d408cd9d18feb1884ffebbdec41'; Capacity = 'aaf7271cd547c948ef1f4492f32ec85f7ab4a113fc19899c34396fe89ec7ef77' }
    'src\runs\foreground\execution.ts' = @{ Owner = '13e8daf52987c7d80d10146a1cfcc825bdcdfcdf5ee16f7bcae385294930fcd7'; Final = '3d757df6cf57b0865668da1ba876c10d57903601c18d77a01a01d25c6054cdb4'; Capacity = '3345076d827c8e63f973794a195fefab5e600e8c000583d4a98f72b52fb051ce' }
    'src\runs\foreground\subagent-executor.ts' = @{ Owner = '6022d233c27a0f796581ba6ebda282c736cf0442771f41a89ad290912898a220'; Final = 'f6e1ed79bfc0373e77efb0754dcfcddf643942d406d1c8371d57a5c3203f4fed'; Capacity = '411f4f275f164786f2388fb001d67954366d69fd5188a996b1a79d300dcd320e' }
    'src\runs\shared\filesystem-policy.ts' = @{ Owner = $null; Final = '4caaac5372aaf5a7b3e085e61f618140f61c0bcb21e9215c4729754c3a7fa867'; Capacity = '4caaac5372aaf5a7b3e085e61f618140f61c0bcb21e9215c4729754c3a7fa867' }
    'src\runs\shared\parallel-utils.ts' = @{ Owner = '5e09e6c32edfd2884cdcfc3dfa3f577a84b0e542580d30b903f68254cd08c549'; Final = '55a328d8b8b6a2d5802bdee1d512e06678f33cdaf7e574ab0713ac0df20c8dbf'; Capacity = '1d0b11ce0fab443cdbe9798007c5fc68f344757e617d8ced572f93fe4a047793' }
    'src\runs\shared\pi-args.ts' = @{ Owner = '3e6736f9be5e2b00c88e485c08bfef4391354dc2a61d710f97c8a30bcdfb9d6c'; Final = '20714d7c3ac80716ddcdabff4d63cdd25144748b3c74602de93587fa5c8f6020'; Capacity = 'a177dfe33d9eab63960df1cc998ead47be5138342427845d1896f9066332847f' }
    'src\runs\shared\subagent-prompt-runtime.ts' = @{ Owner = '19b81a4293be933154fa4afa1955012b189ba1093c1ffd0f788cb11a82b1cbce'; Final = '07733bb43a37e98f547a5b17a6d35c750433f1475a1fdbcecd52b79128915dd0'; Capacity = '07733bb43a37e98f547a5b17a6d35c750433f1475a1fdbcecd52b79128915dd0' }
    'src\shared\launch-contract.ts' = @{ Owner = '25b6342ff008d6c240e33b61f1d40c9b88aa7a3f2aadaf67740ff713bb13258e'; Final = 'a4251d0827c4c9b3611c8509e69331337a8636ac21cbf7a6c1bf7a8970e5fe76'; Capacity = 'a4251d0827c4c9b3611c8509e69331337a8636ac21cbf7a6c1bf7a8970e5fe76' }
    'src\shared\types.ts' = @{ Owner = 'd04043d8cbcdc9ee6e6a6d85b3e09d5282cd16a2b614a69758476ae13916fd09'; Final = '2e80765b425f6a8481cb559759b313ae679e2f67959a3c0f61214e1d529d6a33'; Capacity = 'acb00bd809ebaaf65bd67f300444ce314d6255739af5f140c8fed640ed8791ec' }
    'src\workflows\scripted-workflow.ts' = @{ Owner = '639af6b74b8c890ceef80c9d42f0a8ffbdaef8f7d67047bb9a6b4bb2077c034d'; Final = 'b67c105c52e33be616f316471601120751741f283a0ccea3f123fb9867ccf0e6'; Capacity = '80d38d915e08f0173387c14249bed9688d1f9ec1d5c7f177e6d4cafba68b2eea' }
}
$prerequisites = [ordered]@{
    'src\runs\shared\single-output.ts' = @{ Final = 'aa63de8ffd7e2ce671560c6cbded541e475bdfa700e33c069042b32af0c2605b'; Capacity = 'aa63de8ffd7e2ce671560c6cbded541e475bdfa700e33c069042b32af0c2605b' }
    'src\extension\index.ts' = @{ Final = '5170c2f15a74bcfc4edbfc2b20eef8494c6fb3836553da43c698596e357b7009'; Capacity = '2d3d3c61eb59186a2abdd59b235a834abe5ac7daca64c9a504bb902eb78ed5a9' }
    'src\extension\rpc.ts' = @{ Final = '397d971cc7ec1ef1df846426c654d343a3fa91ab718eec24a8e78a12ad0fc0a7'; Capacity = '637d4c70a99f229c11e743a6b2e41569b91217f36f002958bf3ad3ed2cae5599' }
    'src\shared\post-exit-stdio-guard.ts' = @{ Final = 'c8900cba6d57070f8d2adfd065a349fbc8d906294a83e80bd8284a24fce8b4d2'; Capacity = 'c8900cba6d57070f8d2adfd065a349fbc8d906294a83e80bd8284a24fce8b4d2' }
}

Assert-PiSFilesystemPolicyNoReparsePath -Path $packageRoot
Assert-PiSFilesystemPolicyNoReparsePath -Path $packageJsonPath
foreach ($relative in @($files.Keys) + @($prerequisites.Keys)) {
    Assert-PiSFilesystemPolicyNoReparsePath -Path (Join-Path $packageRoot $relative)
}

foreach ($required in @($packageJsonPath,$patchPath) + @($prerequisites.Keys | ForEach-Object { Join-Path $packageRoot $_ })) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_FILESYSTEM_POLICY_PATCH_SOURCE_MISSING: $required"
    }
}
$actualPatchHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $patchPath).Hash.ToLowerInvariant()
if ($actualPatchHash -cne $expectedPatchHash) {
    throw "PI_S_FILESYSTEM_POLICY_PATCH_IDENTITY_MISMATCH: expected=$expectedPatchHash actual=$actualPatchHash"
}
$package = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$package.name -cne 'pi-subagents' -or [string]$package.version -cne '0.44.0') {
    throw "PI_S_FILESYSTEM_POLICY_PATCH_VERSION_UNSUPPORTED: $($package.name)@$($package.version)"
}

$prerequisiteHashes = [ordered]@{}
foreach ($relative in $prerequisites.Keys) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $packageRoot $relative)).Hash.ToLowerInvariant()
    $prerequisiteHashes[$relative] = $actual
}
$allPrerequisitesFinal = @($prerequisites.Keys | Where-Object { $prerequisiteHashes[$_] -ceq $prerequisites[$_].Final }).Count -eq $prerequisites.Count
$allPrerequisitesCapacity = @($prerequisites.Keys | Where-Object { $prerequisiteHashes[$_] -ceq $prerequisites[$_].Capacity }).Count -eq $prerequisites.Count

$before = [ordered]@{}
foreach ($relative in $files.Keys) {
    $sourcePath = Join-Path $packageRoot $relative
    $before[$relative] = if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
        (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
    } else { 'absent' }
}
$allOwner = @($files.Keys | Where-Object {
    $expected = $files[$_].Owner
    ($null -eq $expected -and $before[$_] -ceq 'absent') -or ($null -ne $expected -and $before[$_] -ceq $expected)
}).Count -eq $files.Count
$allFinal = @($files.Keys | Where-Object { $before[$_] -ceq $files[$_].Final }).Count -eq $files.Count
$allCapacity = @($files.Keys | Where-Object { $before[$_] -ceq $files[$_].Capacity }).Count -eq $files.Count
$coherentOwner = $allOwner -and $allPrerequisitesFinal
$coherentFinal = $allFinal -and $allPrerequisitesFinal
$coherentCapacity = $allCapacity -and $allPrerequisitesCapacity
$changed = $false

if ($coherentOwner) {
    if ($VerifyOnly) { throw "PI_S_FILESYSTEM_POLICY_PATCH_NOT_APPLIED: $packageRoot" }
    & git -c core.autocrlf=false -C $packageRoot apply --check $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'PI_S_FILESYSTEM_POLICY_PATCH_CHECK_FAILED' }
    & git -c core.autocrlf=false -C $packageRoot apply $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'PI_S_FILESYSTEM_POLICY_PATCH_APPLY_FAILED' }
    $changed = $true
} elseif (-not $coherentFinal -and -not $coherentCapacity) {
    $actual = @($before.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ';'
    $prerequisiteActual = @($prerequisiteHashes.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ';'
    throw "PI_S_FILESYSTEM_POLICY_PATCH_SOURCE_CONFLICT: files=$actual prerequisites=$prerequisiteActual"
}

$after = [ordered]@{}
foreach ($relative in $files.Keys) {
    $sourcePath = Join-Path $packageRoot $relative
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "PI_S_FILESYSTEM_POLICY_PATCH_VERIFY_MISSING: $relative"
    }
    $after[$relative] = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
    $expected = if ($coherentCapacity) { $files[$relative].Capacity } else { $files[$relative].Final }
    if ($after[$relative] -cne $expected) {
        throw "PI_S_FILESYSTEM_POLICY_PATCH_VERIFY_FAILED: file=$relative expected=$expected actual=$($after[$relative])"
    }
}

$policyText = Get-Content -Raw -LiteralPath (Join-Path $packageRoot 'src\runs\shared\filesystem-policy.ts') -Encoding UTF8
$argsText = Get-Content -Raw -LiteralPath (Join-Path $packageRoot 'src\runs\shared\pi-args.ts') -Encoding UTF8
$resumeText = Get-Content -Raw -LiteralPath (Join-Path $packageRoot 'src\runs\background\async-resume.ts') -Encoding UTF8
$workflowText = Get-Content -Raw -LiteralPath (Join-Path $packageRoot 'src\workflows\scripted-workflow.ts') -Encoding UTF8
if (
    $policyText -notmatch 'bash is always denied' -or
    $policyText -notmatch 'fixed read/grep/find/ls allowlist' -or
    $policyText -notmatch 'registerFilesystemPolicyGate' -or
    $argsText -notmatch 'FILESYSTEM_POLICY_RUNTIME_SHA256_ENV' -or
    $argsText -notmatch 'FILESYSTEM_POLICY_GATE_SHA256_ENV' -or
    $argsText -notmatch 'args\.push\("--no-context-files"\)' -or
    $argsText -notmatch 'args\.push\("--no-skills"\)' -or
    $resumeText -notmatch 'refusing unrestricted resume' -or
    $resumeText -notmatch 'filesystemPolicy requires maxSubagentDepth=0' -or
    $workflowText -notmatch 'filesystemPolicy v1 supports one runs\.run child only'
) {
    throw 'PI_S_FILESYSTEM_POLICY_PATCH_SEMANTIC_VERIFY_FAILED'
}

[pscustomobject]@{
    schema = 'xinao.pi_s_subagents_filesystem_policy_compatibility.v1'
    patch_id = 'pi-subagents-0.44.0-task-filesystem-policy-v1'
    agent_dir = $target
    package = 'pi-subagents@0.44.0'
    patch_path = $patchPath
    patch_sha256 = $actualPatchHash
    before_sha256 = $before
    after_sha256 = $after
    prerequisite_sha256 = $prerequisiteHashes
    changed = $changed
    verify_only = [bool]$VerifyOnly
    source_file_count = $files.Count
    runtime_loader_sha256 = $after['src\runs\shared\subagent-prompt-runtime.ts']
    runtime_gate_sha256 = $after['src\runs\shared\filesystem-policy.ts']
    v1_fresh_single_child_only = $true
    v1_foreground_and_detached_single = $true
    bash_fixed_deny = $true
    project_context_and_skills_forced_off = $true
    restricted_max_subagent_depth = 0
    restricted_artifacts_use_managed_temp = $true
    async_resume_requires_consistent_durable_policy = $true
    prime_b_modified = $false
    high_capacity_combination_accepted = [bool]$coherentCapacity
} | ConvertTo-Json -Depth 7
