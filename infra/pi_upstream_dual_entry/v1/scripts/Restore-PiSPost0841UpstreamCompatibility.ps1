#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PiToolRoot,
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

$target = [IO.Path]::GetFullPath($PiToolRoot).TrimEnd('\')
$mainTarget = [IO.Path]::GetFullPath($script:PiDualEntryMainToolRoot).TrimEnd('\')
$labParent = [IO.Path]::GetFullPath((Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')).TrimEnd('\')
$labPrefix = $labParent + [IO.Path]::DirectorySeparatorChar
$isLabCore = $false
if ($target.StartsWith($labPrefix,[StringComparison]::OrdinalIgnoreCase)) {
    $relative = $target.Substring($labPrefix.Length)
    $segments = @($relative.Split([IO.Path]::DirectorySeparatorChar,[StringSplitOptions]::RemoveEmptyEntries))
    $isLabCore = ($segments.Count -eq 2 -and $segments[1] -ceq 'pi-tool-root')
}
if ($target -ine $mainTarget -and -not $isLabCore) {
    throw "PI_S_POST0841_RESTORE_TARGET_OUTSIDE_MAIN_OR_BODY_LAB: $target"
}

$packageRoot = Join-Path $target 'node_modules\@earendil-works\pi-coding-agent'
$specs = @(
    [pscustomobject]@{
        Name = 'pi-ai-openai-completions'
        Path = Join-Path $packageRoot 'node_modules\@earendil-works\pi-ai\dist\api\openai-completions.js'
        Upstream = '727d744f20985f667151e8ecee3ad30af388d9d66d91a92d0fb9ad3261da4363'
        Patched = 'bd251314511dfac520d6a850871a3359c1d82a3e68f0ef4b72f13dc5e0137070'
        Preimage = Join-Path $target 'xinao-compatibility-preimages\post-0.84.1\pi-ai-openai-completions.upstream.js'
    },
    [pscustomobject]@{
        Name = 'pi-ai-deepseek-models'
        Path = Join-Path $packageRoot 'node_modules\@earendil-works\pi-ai\dist\providers\data\deepseek.json'
        Upstream = '0dcc807a4e5827b488c6ceac87884ff6e735e01cf4f2ddfec9dd812e6fde041b'
        Patched = '3594c8981450f5c44db389788da793ef5c78f153856c9560394eba1da6dfc3db'
        Preimage = Join-Path $target 'xinao-compatibility-preimages\post-0.84.1\pi-ai-deepseek-models.upstream.json'
    },
    [pscustomobject]@{
        Name = 'pi-tui-layout'
        Path = Join-Path $packageRoot 'node_modules\@earendil-works\pi-tui\dist\layout.js'
        Upstream = 'fdc6c58b4245e735a0daabdc93201017e77cbbb01d7d440eda6427270556b2af'
        Patched = '257a5e2f77e2bbb14d577279f4800bcd765bdd64c7e41d02d2c7929b28ee0b46'
        Preimage = Join-Path $target 'xinao-compatibility-preimages\post-0.84.1\pi-tui-layout.upstream.js'
    }
)

$changed = $false
foreach ($spec in $specs) {
    foreach ($required in @($spec.Path,$spec.Preimage)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "PI_S_POST0841_RESTORE_SOURCE_MISSING: $required"
        }
    }
    $preimageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $spec.Preimage).Hash.ToLowerInvariant()
    if ($preimageHash -cne $spec.Upstream) {
        throw "PI_S_POST0841_RESTORE_PREIMAGE_INVALID: file=$($spec.Name) expected=$($spec.Upstream) actual=$preimageHash"
    }
    $before = (Get-FileHash -Algorithm SHA256 -LiteralPath $spec.Path).Hash.ToLowerInvariant()
    if ($before -ceq $spec.Patched) {
        if ($VerifyOnly) { throw "PI_S_POST0841_RESTORE_NOT_APPLIED: $($spec.Path)" }
        Copy-Item -LiteralPath $spec.Preimage -Destination $spec.Path -Force
        $changed = $true
    } elseif ($before -cne $spec.Upstream) {
        throw "PI_S_POST0841_RESTORE_SOURCE_CONFLICT: file=$($spec.Name) expected=$($spec.Patched)|$($spec.Upstream) actual=$before"
    }
    $after = (Get-FileHash -Algorithm SHA256 -LiteralPath $spec.Path).Hash.ToLowerInvariant()
    if ($after -cne $spec.Upstream) {
        throw "PI_S_POST0841_RESTORE_VERIFY_FAILED: file=$($spec.Name) expected=$($spec.Upstream) actual=$after"
    }
}

[pscustomobject]@{
    schema = 'xinao.pi_post_0841_upstream_restore.v1'
    patch_id = 'pi-0.84.1-upstream-20260808-deepseek-and-fullscreen-v1'
    pi_tool_root = $target
    changed = $changed
    verify_only = [bool]$VerifyOnly
    restored_upstream_preimages = $true
} | ConvertTo-Json -Depth 4
