#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PiToolRoot,
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPost0841Path {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

$target = Get-NormalizedPost0841Path -Path $PiToolRoot
$mainTarget = Get-NormalizedPost0841Path -Path $script:PiDualEntryMainToolRoot
$labParent = Get-NormalizedPost0841Path -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
$labPrefix = $labParent + [IO.Path]::DirectorySeparatorChar
$isLabCore = $false
if ($target.StartsWith($labPrefix,[StringComparison]::OrdinalIgnoreCase)) {
    $relative = $target.Substring($labPrefix.Length)
    $segments = @($relative.Split([IO.Path]::DirectorySeparatorChar,[StringSplitOptions]::RemoveEmptyEntries))
    $isLabCore = ($segments.Count -eq 2 -and $segments[1] -ceq 'pi-tool-root')
}
if ($target -ine $mainTarget -and -not $isLabCore) {
    throw "PI_S_POST0841_PATCH_TARGET_OUTSIDE_MAIN_OR_BODY_LAB: $target"
}

$packageRoot = Join-Path $target 'node_modules\@earendil-works\pi-coding-agent'
$packageJsonPath = Join-Path $packageRoot 'package.json'
$aiRoot = Join-Path $packageRoot 'node_modules\@earendil-works\pi-ai'
$tuiRoot = Join-Path $packageRoot 'node_modules\@earendil-works\pi-tui'
$aiPackagePath = Join-Path $aiRoot 'package.json'
$tuiPackagePath = Join-Path $tuiRoot 'package.json'
$aiPath = Join-Path $aiRoot 'dist\api\openai-completions.js'
$modelsPath = Join-Path $aiRoot 'dist\providers\data\deepseek.json'
$layoutPath = Join-Path $tuiRoot 'dist\layout.js'
foreach ($required in @($packageJsonPath,$aiPackagePath,$tuiPackagePath,$aiPath,$modelsPath,$layoutPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_POST0841_PATCH_SOURCE_MISSING: $required"
    }
}

$package = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
$aiPackage = Get-Content -Raw -LiteralPath $aiPackagePath -Encoding UTF8 | ConvertFrom-Json
$tuiPackage = Get-Content -Raw -LiteralPath $tuiPackagePath -Encoding UTF8 | ConvertFrom-Json
if (
    [string]$package.name -cne '@earendil-works/pi-coding-agent' -or
    [string]$package.version -cne '0.84.1' -or
    [string]$aiPackage.version -cne '0.84.1' -or
    [string]$tuiPackage.version -cne '0.84.1'
) {
    throw "PI_S_POST0841_PATCH_VERSION_UNSUPPORTED: coding=$($package.version) ai=$($aiPackage.version) tui=$($tuiPackage.version)"
}

$specs = @(
    [pscustomobject]@{
        Name = 'pi-ai-openai-completions'
        Path = $aiPath
        Upstream = '727d744f20985f667151e8ecee3ad30af388d9d66d91a92d0fb9ad3261da4363'
        Patched = 'bd251314511dfac520d6a850871a3359c1d82a3e68f0ef4b72f13dc5e0137070'
        Preimage = Join-Path $target 'xinao-compatibility-preimages\post-0.84.1\pi-ai-openai-completions.upstream.js'
        Kind = 'deepseek-runtime'
    },
    [pscustomobject]@{
        Name = 'pi-ai-deepseek-models'
        Path = $modelsPath
        Upstream = '0dcc807a4e5827b488c6ceac87884ff6e735e01cf4f2ddfec9dd812e6fde041b'
        Patched = '3594c8981450f5c44db389788da793ef5c78f153856c9560394eba1da6dfc3db'
        Preimage = Join-Path $target 'xinao-compatibility-preimages\post-0.84.1\pi-ai-deepseek-models.upstream.json'
        Kind = 'deepseek-catalog'
    },
    [pscustomobject]@{
        Name = 'pi-tui-layout'
        Path = $layoutPath
        Upstream = 'fdc6c58b4245e735a0daabdc93201017e77cbbb01d7d440eda6427270556b2af'
        Patched = '257a5e2f77e2bbb14d577279f4800bcd765bdd64c7e41d02d2c7929b28ee0b46'
        Preimage = Join-Path $target 'xinao-compatibility-preimages\post-0.84.1\pi-tui-layout.upstream.js'
        Kind = 'fullscreen-layout'
    }
)

$changed = $false
foreach ($spec in $specs) {
    $before = (Get-FileHash -Algorithm SHA256 -LiteralPath $spec.Path).Hash.ToLowerInvariant()
    if ($before -ceq $spec.Upstream) {
        if ($VerifyOnly) { throw "PI_S_POST0841_PATCH_NOT_APPLIED: $($spec.Path)" }
        if (Test-Path -LiteralPath $spec.Preimage -PathType Leaf) {
            $preimageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $spec.Preimage).Hash.ToLowerInvariant()
            if ($preimageHash -cne $spec.Upstream) {
                throw "PI_S_POST0841_PATCH_PREIMAGE_CONFLICT: file=$($spec.Name) expected=$($spec.Upstream) actual=$preimageHash"
            }
        } else {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $spec.Preimage) | Out-Null
            Copy-Item -LiteralPath $spec.Path -Destination $spec.Preimage
        }

        $source = [IO.File]::ReadAllText($spec.Path,[Text.UTF8Encoding]::new($false))
        if ($spec.Kind -ceq 'deepseek-runtime') {
            $old = @(
                '    const useMaxTokens = baseUrl.includes("chutes.ai") ||'
                '        isMoonshot ||'
                '        isCloudflareAiGateway ||'
                '        isTogether ||'
                '        isNvidia ||'
                '        isAntLing ||'
                '        isZai;'
                '    const isGrok = provider === "xai" || baseUrl.includes("api.x.ai");'
                '    const isDeepSeek = provider === "deepseek" || baseUrl.includes("deepseek.com");'
            ) -join [char]10
            $new = @(
                '    const isDeepSeek = provider === "deepseek" || baseUrl.includes("deepseek.com");'
                '    const useMaxTokens = baseUrl.includes("chutes.ai") ||'
                '        isDeepSeek ||'
                '        isMoonshot ||'
                '        isCloudflareAiGateway ||'
                '        isTogether ||'
                '        isNvidia ||'
                '        isAntLing ||'
                '        isZai;'
                '    const isGrok = provider === "xai" || baseUrl.includes("api.x.ai");'
            ) -join [char]10
            if (-not $source.Contains($old)) { throw 'PI_S_POST0841_DEEPSEEK_RUNTIME_ANCHOR_MISSING' }
            $updated = $source.Replace($old,$new)
        } elseif ($spec.Kind -ceq 'deepseek-catalog') {
            $old = '"thinkingFormat":"deepseek"}'
            $new = '"thinkingFormat":"deepseek","maxTokensField":"max_tokens"}'
            $count = [regex]::Matches($source,[regex]::Escape($old)).Count
            if ($count -ne 2) { throw "PI_S_POST0841_DEEPSEEK_CATALOG_ANCHOR_COUNT: expected=2 actual=$count" }
            $updated = $source.Replace($old,$new)
        } else {
            $old = @(
                '            if (isImageLine(line) && box.rect.x === 0 && box.rect.width >= totalWidth)'
                '                screen[row] = line;'
                '            else'
                '                screen[row] = compositeTuiLine(screen[row] ?? "", line, box.rect.x, box.rect.width, totalWidth);'
            ) -join [char]10
            $new = @(
                '            if (box.rect.x === 0 && box.rect.width >= totalWidth && (isImageLine(line) || !screen[row])) {'
                '                screen[row] = line;'
                '            }'
                '            else {'
                '                screen[row] = compositeTuiLine(screen[row] ?? "", line, box.rect.x, box.rect.width, totalWidth);'
                '            }'
            ) -join [char]10
            if (-not $source.Contains($old)) { throw 'PI_S_POST0841_FULLSCREEN_LAYOUT_ANCHOR_MISSING' }
            $updated = $source.Replace($old,$new)
        }
        if ($updated -ceq $source) { throw "PI_S_POST0841_PATCH_NO_CHANGE: $($spec.Name)" }
        [IO.File]::WriteAllText($spec.Path,$updated,[Text.UTF8Encoding]::new($false))
        $changed = $true
    } elseif ($before -cne $spec.Patched) {
        throw "PI_S_POST0841_PATCH_SOURCE_CONFLICT: file=$($spec.Name) expected=$($spec.Upstream)|$($spec.Patched) actual=$before"
    }
}

$receipts = @()
foreach ($spec in $specs) {
    $after = (Get-FileHash -Algorithm SHA256 -LiteralPath $spec.Path).Hash.ToLowerInvariant()
    if ($after -cne $spec.Patched) {
        throw "PI_S_POST0841_PATCH_VERIFY_FAILED: file=$($spec.Name) expected=$($spec.Patched) actual=$after"
    }
    if (-not (Test-Path -LiteralPath $spec.Preimage -PathType Leaf)) {
        throw "PI_S_POST0841_PATCH_PREIMAGE_MISSING: $($spec.Preimage)"
    }
    $preimageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $spec.Preimage).Hash.ToLowerInvariant()
    if ($preimageHash -cne $spec.Upstream) {
        throw "PI_S_POST0841_PATCH_PREIMAGE_INVALID: file=$($spec.Name) expected=$($spec.Upstream) actual=$preimageHash"
    }
    $receipts += [pscustomobject]@{
        name = $spec.Name
        source_path = $spec.Path
        preimage_path = $spec.Preimage
        upstream_sha256 = $spec.Upstream
        patched_sha256 = $after
    }
}

$aiText = [IO.File]::ReadAllText($aiPath,[Text.UTF8Encoding]::new($false))
$models = Get-Content -Raw -LiteralPath $modelsPath -Encoding UTF8 | ConvertFrom-Json
$layoutText = [IO.File]::ReadAllText($layoutPath,[Text.UTF8Encoding]::new($false))
if (-not $aiText.Contains('        isDeepSeek ||')) { throw 'PI_S_POST0841_DEEPSEEK_RUNTIME_SEMANTIC_VERIFY_FAILED' }
foreach ($id in @('deepseek-v4-flash','deepseek-v4-pro')) {
    if ([string]$models.'openai-completions'.$id.compat.maxTokensField -cne 'max_tokens') {
        throw "PI_S_POST0841_DEEPSEEK_MODEL_SEMANTIC_VERIFY_FAILED: $id"
    }
}
if (-not $layoutText.Contains('box.rect.x === 0 && box.rect.width >= totalWidth && (isImageLine(line) || !screen[row])')) {
    throw 'PI_S_POST0841_FULLSCREEN_LAYOUT_SEMANTIC_VERIFY_FAILED'
}

[pscustomobject]@{
    schema = 'xinao.pi_post_0841_upstream_compatibility.v1'
    patch_id = 'pi-0.84.1-upstream-20260808-deepseek-and-fullscreen-v1'
    pi_tool_root = $target
    package = '@earendil-works/pi-coding-agent@0.84.1'
    upstream_commits = @(
        'c185d412382581860a489b4959737bad1d119492',
        '18dee5f0a89f41466e876cbbbfe77635cd250882'
    )
    files = $receipts
    changed = $changed
    verify_only = [bool]$VerifyOnly
    deepseek_builtin_and_custom_send_max_tokens = $true
    fullscreen_visible_output_preserved = $true
    shared_cold_backup_core_allowed = $false
    rollback_preimages_verified = $true
} | ConvertTo-Json -Depth 6
