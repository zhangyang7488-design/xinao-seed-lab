[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AgentDir,
    [Parameter(Mandatory)][string]$PiToolRoot,
    [string]$ReceiptPath,
    [string]$TypeScriptCompilerPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-CanonicalDirectory {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Label)
    $resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\','/')
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "PI_HIGH_CAPACITY_REPLAY_DIRECTORY_MISSING: ${Label}: $resolved"
    }
    return (Get-Item -LiteralPath $resolved).FullName.TrimEnd('\','/')
}

function Get-RequiredFile {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Label)
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "PI_HIGH_CAPACITY_REPLAY_FILE_MISSING: ${Label}: $resolved"
    }
    return (Get-Item -LiteralPath $resolved).FullName
}

function Get-VerifiedTypeShim {
    param(
        [Parameter(Mandatory)][string]$ShimRoot,
        [Parameter(Mandatory)][string]$ManifestPath
    )
    $root = Get-CanonicalDirectory -Path $ShimRoot -Label 'high-capacity TypeScript fixture root'
    $manifestFile = Get-RequiredFile -Path $ManifestPath -Label 'high-capacity TypeScript fixture manifest'
    $manifestSha = (Get-FileHash -LiteralPath $manifestFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedManifestSha = 'b2af2e32e31c3e90806a2d514cc2f39fc18976edf2547c532ba1941317dc8804'
    if ($manifestSha -cne $expectedManifestSha) {
        throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_MANIFEST_DRIFT: expected=$expectedManifestSha actual=$manifestSha"
    }
    $manifestRaw = [IO.File]::ReadAllText($manifestFile,[Text.Encoding]::UTF8)
    $manifest = $manifestRaw | ConvertFrom-Json
    if ([string]$manifest.schema -cne 'xinao.pi_s_high_capacity_type_shim_manifest.v1') {
        throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_SCHEMA_DRIFT: $($manifest.schema)"
    }

    $expectedPackages = [ordered]@{
        '@earendil-works/pi-coding-agent' = @{ version = '0.0.0-pi-subagents-test-shim'; package_json = 'pi-coding-agent/package.json' }
        '@earendil-works/pi-agent-core' = @{ version = '0.81.0'; package_json = 'node_modules/@earendil-works/pi-agent-core/package.json' }
        '@earendil-works/pi-ai' = @{ version = '0.81.0'; package_json = 'node_modules/@earendil-works/pi-ai/package.json' }
        '@earendil-works/pi-tui' = @{ version = '0.81.0'; package_json = 'node_modules/@earendil-works/pi-tui/package.json' }
        '@types/node' = @{ version = '24.13.3'; package_json = 'node_modules/@types/node/package.json' }
        'typebox' = @{ version = '1.1.38'; package_json = 'node_modules/typebox/package.json' }
        '@anthropic-ai/sdk' = @{ version = '0.91.1'; package_json = 'node_modules/@anthropic-ai/sdk/package.json' }
        '@google/genai' = @{ version = '1.52.0'; package_json = 'node_modules/@google/genai/package.json' }
        'openai' = @{ version = '6.26.0'; package_json = 'node_modules/openai/package.json' }
        'undici-types' = @{ version = '7.18.2'; package_json = 'node_modules/undici-types/package.json' }
    }
    $manifestPackages = @($manifest.packages)
    if ($manifestPackages.Count -ne $expectedPackages.Count) {
        throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_PACKAGE_COUNT_DRIFT: expected=$($expectedPackages.Count) actual=$($manifestPackages.Count)"
    }
    foreach ($package in $manifestPackages) {
        $name = [string]$package.name
        if (-not $expectedPackages.Contains($name)) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_PACKAGE_UNEXPECTED: $name"
        }
        $expected = $expectedPackages[$name]
        if ([string]$package.version -cne [string]$expected.version -or [string]$package.package_json -cne [string]$expected.package_json) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_PACKAGE_MANIFEST_DRIFT: $name"
        }
        $packagePath = Join-Path $root ([string]$package.package_json -replace '/','\')
        $packageFile = Get-RequiredFile -Path $packagePath -Label "high-capacity TypeScript fixture package $name"
        $packageJson = [IO.File]::ReadAllText($packageFile,[Text.Encoding]::UTF8) | ConvertFrom-Json
        if ([string]$packageJson.name -cne $name -or [string]$packageJson.version -cne [string]$expected.version) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_PACKAGE_IDENTITY_DRIFT: expected=$name@$($expected.version) actual=$($packageJson.name)@$($packageJson.version)"
        }
    }

    $expectedClosure = [ordered]@{
        'typebox' = @{ path = 'node_modules/typebox'; declarations = 376; bytes = 493061 }
        '@anthropic-ai/sdk' = @{ path = 'node_modules/@anthropic-ai/sdk'; declarations = 64; bytes = 603832 }
        '@google/genai' = @{ path = 'node_modules/@google/genai'; declarations = 1; bytes = 924 }
        'openai' = @{ path = 'node_modules/openai'; declarations = 101; bytes = 1349192 }
        'undici-types' = @{ path = 'node_modules/undici-types'; declarations = 42; bytes = 102052 }
    }
    foreach ($name in $expectedClosure.Keys) {
        $expected = $expectedClosure[$name]
        $packageRoot = Get-CanonicalDirectory -Path (Join-Path $root ($expected.path -replace '/','\')) -Label "high-capacity declaration closure $name"
        $declarations = @(Get-ChildItem -LiteralPath $packageRoot -Recurse -File | Where-Object { $_.Name -match '\.d\.(?:ts|mts|cts)$' })
        [Int64]$declarationBytes = 0
        foreach ($declaration in $declarations) { $declarationBytes += [Int64]$declaration.Length }
        if ($declarations.Count -ne [int]$expected.declarations -or $declarationBytes -ne [Int64]$expected.bytes) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_CLOSURE_DRIFT: package=$name files=$($declarations.Count)/$($expected.declarations) bytes=$declarationBytes/$($expected.bytes)"
        }
    }

    $googleRoot = Join-Path $root 'node_modules\@google\genai'
    $googlePackagePath = Join-Path $googleRoot 'package.json'
    $googleProjectionPath = Join-Path $googleRoot 'index.d.ts'
    $googlePackage = [IO.File]::ReadAllText((Get-RequiredFile -Path $googlePackagePath -Label 'Google declaration projection package'),[Text.Encoding]::UTF8) | ConvertFrom-Json
    $googleDotExport = $googlePackage.exports.PSObject.Properties['.'].Value
    if ($googlePackage.private -ne $true -or [string]$googlePackage.type -cne 'module' -or [string]$googlePackage.types -cne './index.d.ts' -or
        [string]$googlePackage.xinaoPiHighCapacityProjection -cne 'exact-google-shared-four-symbol-v1' -or
        @($googlePackage.exports.PSObject.Properties).Count -ne 1 -or @($googleDotExport.PSObject.Properties).Count -ne 1 -or
        [string]$googleDotExport.types -cne './index.d.ts') {
        throw 'PI_HIGH_CAPACITY_REPLAY_GOOGLE_PROJECTION_PACKAGE_DRIFT'
    }
    $googleProjectionFile = Get-RequiredFile -Path $googleProjectionPath -Label 'Google declaration projection'
    $googleProjectionSha = (Get-FileHash -LiteralPath $googleProjectionFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $googleProjectionText = [IO.File]::ReadAllText($googleProjectionFile,[Text.Encoding]::UTF8)
    if ($googleProjectionSha -cne 'e6c27ddd9ce5b2a0a3084e4f1b7ae292848f4d09b8a204bc5cebf2a2a923b406' -or
        $googleProjectionText -cmatch '\b(?:any|unknown)\b' -or $googleProjectionText -match '\[[^\]]+\:\s*(?:string|number|symbol)\s*\]') {
        throw "PI_HIGH_CAPACITY_REPLAY_GOOGLE_PROJECTION_SEMANTIC_DRIFT: sha=$googleProjectionSha"
    }

    $anthropicTypesPath = Join-Path $root 'node_modules\@anthropic-ai\sdk\internal\types.d.mts'
    $anthropicTypesFile = Get-RequiredFile -Path $anthropicTypesPath -Label 'Anthropic normalized declaration'
    $anthropicTypesSha = (Get-FileHash -LiteralPath $anthropicTypesFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $anthropicLines = [IO.File]::ReadAllLines($anthropicTypesFile,[Text.Encoding]::UTF8)
    $expectedAnthropicBlock = @(
        "type UndiciTypesRequestInit = NotAny<import('undici-types').RequestInit>;",
        'type UndiciRequestInit = never;',
        'type BunRequestInit = never;',
        'type NodeFetch2RequestInit = never;',
        'type NodeFetch3RequestInit = never;'
    )
    if ($anthropicTypesSha -cne '844c88be6a4d6da685761537c5830547405e78a6668461d95c92e5914646b6e0' -or $anthropicLines.Count -lt 52) {
        throw "PI_HIGH_CAPACITY_REPLAY_ANTHROPIC_NORMALIZATION_DRIFT: sha=$anthropicTypesSha"
    }
    for ($i = 0; $i -lt $expectedAnthropicBlock.Count; $i++) {
        if ($anthropicLines[47 + $i] -cne $expectedAnthropicBlock[$i]) {
            throw "PI_HIGH_CAPACITY_REPLAY_ANTHROPIC_ALIAS_DRIFT: line=$($i + 48)"
        }
    }
    $anthropicText = [IO.File]::ReadAllText($anthropicTypesFile,[Text.Encoding]::UTF8)
    if ([regex]::Matches($anthropicText,"import\('undici-types'\)").Count -ne 1 -or
        $anthropicText -match "import\('(?:undici|node-fetch|node-fetch\.js)'\)" -or
        $anthropicText -match "import\('(?:\.\./)+(?:node_modules/)?(?:undici-types|undici|node-fetch)") {
        throw 'PI_HIGH_CAPACITY_REPLAY_ANTHROPIC_OPTIONAL_PROBE_DRIFT'
    }
    $undiciPackageSha = (Get-FileHash -LiteralPath (Join-Path $root 'node_modules\undici-types\package.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    $undiciEntrySha = (Get-FileHash -LiteralPath (Join-Path $root 'node_modules\undici-types\index.d.ts') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($undiciPackageSha -cne '01701286a0441eddf1cd47d488047d363ce7d75466e7b6c89f1c605fba1c3957' -or
        $undiciEntrySha -cne 'c9381908473a1c92cb8c516b184e75f4d226dad95c3a85a5af35f670064d9a2f') {
        throw "PI_HIGH_CAPACITY_REPLAY_UNDICI_TYPES_IDENTITY_DRIFT: package=$undiciPackageSha entry=$undiciEntrySha"
    }

    $projections = @($manifest.projections)
    if ($projections.Count -ne 2 -or [string]$projections[0].id -cne 'anthropic-request-init-environment-normalization-v1' -or
        [string]$projections[0].source_file_sha256 -cne '030b4826be530097518e418eb7a1f1bff2d4cb829f8a8a867a44545108417cbd' -or
        [string]$projections[0].source_block_sha256 -cne 'd74622479e0fbcb1573bbe7e459a8aa33a9662e7d79b6d7baa47da88b92e4665' -or
        [string]$projections[1].id -cne 'google-genai-google-shared-four-symbol-v1' -or
        [string]$projections[1].source_package_json_sha256 -cne 'ec761756421ea5502c23dbebfb4bc2b74c3ff842597199f2f330afc49cbdedc7' -or
        [string]$projections[1].source_declaration_sha256 -cne '07402ed4b198040ee270efb5823e357f2eb30e7b3957ca8f58feed5f40758033' -or
        [string]$projections[1].consumer_sha256 -cne '11255b947bb4ac43cbe2d20fc56e0716aacf0f814b6c56655b841de15fb2016a') {
        throw 'PI_HIGH_CAPACITY_REPLAY_PROJECTION_PROVENANCE_DRIFT'
    }

    $actualPaths = @(Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object { $_.FullName })
    [Array]::Sort($actualPaths,[StringComparer]::OrdinalIgnoreCase)
    $manifestFiles = @($manifest.files)
    if ($actualPaths.Count -ne [int]$manifest.file_count -or $manifestFiles.Count -ne [int]$manifest.file_count) {
        throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_FILE_COUNT_DRIFT: manifest=$($manifest.file_count) listed=$($manifestFiles.Count) actual=$($actualPaths.Count)"
    }

    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    [Int64]$totalBytes = 0
    $canonicalLines = [Text.StringBuilder]::new()
    foreach ($entry in $manifestFiles) {
        $relative = [string]$entry.path
        if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or $relative.Contains(':') -or $relative -match '(^|/)\.\.(/|$)') {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_PATH_INVALID: $relative"
        }
        if (-not $seen.Add($relative)) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_PATH_DUPLICATE: $relative"
        }
        if ($relative -notmatch '\.d\.(?:ts|mts|cts)$' -and (Split-Path -Leaf $relative) -cne 'package.json') {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_FILE_KIND_UNEXPECTED: $relative"
        }
        $candidate = [IO.Path]::GetFullPath((Join-Path $root ($relative -replace '/','\')))
        $requiredPrefix = $root + [IO.Path]::DirectorySeparatorChar
        if (-not $candidate.StartsWith($requiredPrefix,[StringComparison]::OrdinalIgnoreCase)) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_PATH_ESCAPE: $relative"
        }
        $file = Get-RequiredFile -Path $candidate -Label 'high-capacity TypeScript fixture member'
        $bytes = [Int64](Get-Item -LiteralPath $file).Length
        $sha = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($bytes -ne [Int64]$entry.bytes -or $sha -cne [string]$entry.sha256) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_MEMBER_DRIFT: $relative"
        }
        $totalBytes += $bytes
        [void]$canonicalLines.Append($relative).Append("`t").Append($bytes).Append("`t").Append($sha).Append("`n")
    }
    foreach ($actualPath in $actualPaths) {
        $relative = $actualPath.Substring($root.Length + 1).Replace('\','/')
        if (-not $seen.Contains($relative)) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_UNMANIFESTED_FILE: $relative"
        }
    }
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $treeHashBytes = $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonicalLines.ToString()))
        $treeSha = ([BitConverter]::ToString($treeHashBytes)).Replace('-','').ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }
    if ($totalBytes -ne [Int64]$manifest.total_bytes -or $treeSha -cne [string]$manifest.tree_sha256) {
        throw "PI_HIGH_CAPACITY_REPLAY_TYPE_SHIM_TREE_DRIFT: bytes=$totalBytes/$($manifest.total_bytes) sha=$treeSha/$($manifest.tree_sha256)"
    }
    return [pscustomobject]@{
        root = $root
        file_count = $actualPaths.Count
        total_bytes = $totalBytes
        tree_sha256 = $treeSha
        manifest_sha256 = $manifestSha
        packages = @($manifestPackages | ForEach-Object { [ordered]@{ name = [string]$_.name; version = [string]$_.version } })
        declaration_closure = $manifest.declaration_closure
        projections = @($manifest.projections)
    }
}

function Get-VerifiedTypeScriptCompilerFixture {
    param(
        [Parameter(Mandatory)][string]$FixtureRoot,
        [Parameter(Mandatory)][string]$ManifestPath
    )
    $root = Get-CanonicalDirectory -Path $FixtureRoot -Label 'high-capacity TypeScript compiler fixture root'
    $manifestFile = Get-RequiredFile -Path $ManifestPath -Label 'high-capacity TypeScript compiler fixture manifest'
    $manifestSha = (Get-FileHash -LiteralPath $manifestFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($manifestSha -cne '0c7d1b6dbc0e275efab1ab5bc8a6e58ede001a7297772a8d499f238b5aeb43e1') {
        throw "PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_MANIFEST_DRIFT: $manifestSha"
    }
    $manifest = [IO.File]::ReadAllText($manifestFile,[Text.Encoding]::UTF8) | ConvertFrom-Json
    if ([string]$manifest.schema -cne 'xinao.pi_s_high_capacity_typescript_compiler_fixture_manifest.v1' -or [string]$manifest.package -cne 'typescript' -or [string]$manifest.version -cne '5.9.3' -or [string]$manifest.package_json -cne 'package.json' -or [string]$manifest.compiler -cne 'lib/tsc.js' -or [string]$manifest.implementation -cne 'lib/_tsc.js') {
        throw 'PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_IDENTITY_DRIFT'
    }
    $packageFile = Get-RequiredFile -Path (Join-Path $root 'package.json') -Label 'TypeScript compiler package manifest'
    $packageJson = [IO.File]::ReadAllText($packageFile,[Text.Encoding]::UTF8) | ConvertFrom-Json
    if ([string]$packageJson.name -cne 'typescript' -or [string]$packageJson.version -cne '5.9.3') {
        throw "PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_PACKAGE_DRIFT: $($packageJson.name)@$($packageJson.version)"
    }

    $actualPaths = @(Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object { $_.FullName })
    [Array]::Sort($actualPaths,[StringComparer]::OrdinalIgnoreCase)
    $manifestFiles = @($manifest.files)
    if ($actualPaths.Count -ne [int]$manifest.file_count -or $manifestFiles.Count -ne [int]$manifest.file_count) {
        throw "PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_FILE_COUNT_DRIFT: manifest=$($manifest.file_count) listed=$($manifestFiles.Count) actual=$($actualPaths.Count)"
    }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    [Int64]$totalBytes = 0
    $canonicalLines = [Text.StringBuilder]::new()
    foreach ($entry in $manifestFiles) {
        $relative = [string]$entry.path
        if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or $relative.Contains(':') -or $relative -match '(^|/)\.\.(/|$)' -or -not $seen.Add($relative)) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_PATH_INVALID: $relative"
        }
        if ($relative -cne 'package.json' -and $relative -cne 'lib/tsc.js' -and $relative -cne 'lib/_tsc.js' -and $relative -notmatch '^lib/lib[^/]*\.d\.ts$') {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_FILE_KIND_UNEXPECTED: $relative"
        }
        $candidate = [IO.Path]::GetFullPath((Join-Path $root ($relative -replace '/','\')))
        if (-not $candidate.StartsWith($root + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_PATH_ESCAPE: $relative"
        }
        $file = Get-RequiredFile -Path $candidate -Label 'high-capacity TypeScript compiler fixture member'
        $bytes = [Int64](Get-Item -LiteralPath $file).Length
        $sha = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($bytes -ne [Int64]$entry.bytes -or $sha -cne [string]$entry.sha256) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_MEMBER_DRIFT: $relative"
        }
        $totalBytes += $bytes
        [void]$canonicalLines.Append($relative).Append("`t").Append($bytes).Append("`t").Append($sha).Append("`n")
    }
    foreach ($actualPath in $actualPaths) {
        $relative = $actualPath.Substring($root.Length + 1).Replace('\','/')
        if (-not $seen.Contains($relative)) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_UNMANIFESTED_FILE: $relative"
        }
    }
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $treeHashBytes = $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonicalLines.ToString()))
        $treeSha = ([BitConverter]::ToString($treeHashBytes)).Replace('-','').ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }
    if ($totalBytes -ne [Int64]$manifest.total_bytes -or $treeSha -cne [string]$manifest.tree_sha256) {
        throw "PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_TREE_DRIFT: bytes=$totalBytes/$($manifest.total_bytes) sha=$treeSha/$($manifest.tree_sha256)"
    }
    $compiler = Get-RequiredFile -Path (Join-Path $root 'lib\tsc.js') -Label 'TypeScript compiler entry'
    $implementation = Get-RequiredFile -Path (Join-Path $root 'lib\_tsc.js') -Label 'TypeScript compiler implementation'
    return [pscustomobject]@{
        root = $root
        compiler_path = $compiler
        version = '5.9.3'
        file_count = $actualPaths.Count
        total_bytes = $totalBytes
        tree_sha256 = $treeSha
        manifest_sha256 = $manifestSha
        compiler_sha256 = (Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant()
        implementation_sha256 = (Get-FileHash -LiteralPath $implementation -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Assert-NoReparseContainedPath {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label
    )
    $canonicalRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\','/')
    $canonicalPath = [IO.Path]::GetFullPath($Path)
    $prefix = $canonicalRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $canonicalPath.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_PATH_ESCAPE: ${Label}: $canonicalPath"
    }
    $rootItem = Get-Item -LiteralPath $canonicalRoot -Force
    if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_REPARSE: ${Label}: $canonicalRoot"
    }
    $relative = $canonicalPath.Substring($canonicalRoot.Length + 1)
    $current = $canonicalRoot
    foreach ($segment in $relative.Split([IO.Path]::DirectorySeparatorChar,[StringSplitOptions]::RemoveEmptyEntries)) {
        $current = Join-Path $current $segment
        $item = Get-Item -LiteralPath $current -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_REPARSE: ${Label}: $current"
        }
    }
}

function Get-VerifiedJitiAliasProjection {
    param(
        [Parameter(Mandatory)][string]$CorePackageRoot,
        [Parameter(Mandatory)][string]$ManifestPath
    )
    $root = Get-CanonicalDirectory -Path $CorePackageRoot -Label 'Pi coding-agent replay package'
    $manifestFile = Get-RequiredFile -Path $ManifestPath -Label 'high-capacity Jiti alias manifest'
    $manifestSha = (Get-FileHash -LiteralPath $manifestFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($manifestSha -cne '72dab53502a6d0af9b037cd7b6c53be77a77415ed8affb342492ccaff13936a6') {
        throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_MANIFEST_DRIFT: $manifestSha"
    }
    $manifest = [IO.File]::ReadAllText($manifestFile,[Text.Encoding]::UTF8) | ConvertFrom-Json
    if ([string]$manifest.schema -cne 'xinao.pi_s_high_capacity_jiti_alias_manifest.v1' -or [string]$manifest.core_package -cne '@earendil-works/pi-coding-agent' -or [string]$manifest.core_package_version -cne '0.84.1') {
        throw 'PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_MANIFEST_IDENTITY_DRIFT'
    }
    $expectedNames = @('@earendil-works/pi-coding-agent','@earendil-works/pi-agent-core','@earendil-works/pi-ai','@earendil-works/pi-tui')
    $packages = @($manifest.packages)
    if ($packages.Count -ne $expectedNames.Count) {
        throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_PACKAGE_COUNT_DRIFT: expected=$($expectedNames.Count) actual=$($packages.Count)"
    }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $verified = @()
    foreach ($package in $packages) {
        $name = [string]$package.name
        if ($name -notin $expectedNames -or -not $seen.Add($name) -or [string]$package.version -cne '0.84.1') {
            throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_PACKAGE_IDENTITY_DRIFT: $name@$($package.version)"
        }
        $packageRelative = [string]$package.package_json
        $entryRelative = [string]$package.entry
        foreach ($relative in @($packageRelative,$entryRelative)) {
            if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or $relative.Contains(':') -or $relative -match '(^|/)\.\.(/|$)') {
                throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_PATH_INVALID: $relative"
            }
        }
        $packageFile = Get-RequiredFile -Path (Join-Path $root ($packageRelative -replace '/','\')) -Label "$name package manifest"
        $entryFile = Get-RequiredFile -Path (Join-Path $root ($entryRelative -replace '/','\')) -Label "$name Jiti entry"
        Assert-NoReparseContainedPath -Root $root -Path $packageFile -Label "$name package manifest"
        Assert-NoReparseContainedPath -Root $root -Path $entryFile -Label "$name Jiti entry"
        $packageSha = (Get-FileHash -LiteralPath $packageFile -Algorithm SHA256).Hash.ToLowerInvariant()
        $entrySha = (Get-FileHash -LiteralPath $entryFile -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($packageSha -cne [string]$package.package_sha256 -or $entrySha -cne [string]$package.entry_sha256) {
            throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_MEMBER_DRIFT: $name package=$packageSha entry=$entrySha"
        }
        $packageJson = [IO.File]::ReadAllText($packageFile,[Text.Encoding]::UTF8) | ConvertFrom-Json
        if ([string]$packageJson.name -cne $name -or [string]$packageJson.version -cne '0.84.1') {
            throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_PACKAGE_JSON_DRIFT: $name"
        }
        $selector = [string]$package.entry_selector
        if ($selector -ceq 'main') {
            $declared = [string]$packageJson.main
        } elseif ($selector -ceq 'exports[.].import') {
            $rootExport = $packageJson.exports.PSObject.Properties['.']
            $declared = if ($null -eq $rootExport) { $null } else { [string]$rootExport.Value.import }
        } elseif ($selector -ceq 'exports[./compat].import') {
            $compatExport = $packageJson.exports.PSObject.Properties['./compat']
            $declared = if ($null -eq $compatExport) { $null } else { [string]$compatExport.Value.import }
        } else {
            throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_SELECTOR_UNEXPECTED: $name $selector"
        }
        if ($declared -cne [string]$package.entry_value) {
            throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_DECLARATION_DRIFT: $name expected=$($package.entry_value) actual=$declared"
        }
        $declaredEntry = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $packageFile) ($declared -replace '/','\')))
        if ($declaredEntry -cne [IO.Path]::GetFullPath($entryFile)) {
            throw "PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_ENTRY_MISMATCH: $name"
        }
        $verified += [ordered]@{
            name = $name
            version = '0.84.1'
            package_json = $packageRelative
            package_sha256 = $packageSha
            entry = $entryRelative
            entry_sha256 = $entrySha
            entry_selector = $selector
        }
    }
    if ($seen.Count -ne $expectedNames.Count) {
        throw 'PI_HIGH_CAPACITY_REPLAY_JITI_ALIAS_PACKAGE_SET_DRIFT'
    }
    return [pscustomobject]@{ manifest_sha256 = $manifestSha; packages = $verified }
}

function ConvertTo-ForwardSlashPath {
    param([Parameter(Mandatory)][string]$Path)
    if ($Path -match '[*?\[\]]') {
        $parent = Split-Path -Parent $Path
        $leaf = Split-Path -Leaf $Path
        if ($leaf -cne '*.d.ts' -or [string]::IsNullOrWhiteSpace($parent) -or $parent -match '[*?\[\]]') {
            throw "PI_HIGH_CAPACITY_REPLAY_PATH_GLOB_INVALID: $Path"
        }
        return ((Join-Path ([IO.Path]::GetFullPath($parent)) $leaf) -replace '\\','/')
    }
    return ([IO.Path]::GetFullPath($Path) -replace '\\','/')
}

function Invoke-HiddenProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][hashtable]$Environment,
        [int]$TimeoutMs = 120000
    )
    $quote = {
        param([string]$Value)
        if ([string]::IsNullOrEmpty($Value)) { return '""' }
        if ($Value -notmatch '[\s"]') { return $Value }
        return '"' + ($Value -replace '(\\*)"','$1$1\"' -replace '(\\+)$','$1$1') + '"'
    }
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $FilePath
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $start.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    $start.Arguments = (@($Arguments | ForEach-Object { & $quote ([string]$_) }) -join ' ')
    foreach ($entry in $Environment.GetEnumerator()) { $start.EnvironmentVariables[[string]$entry.Key] = [string]$entry.Value }
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { throw "PI_HIGH_CAPACITY_REPLAY_PROCESS_START_FAILED: $FilePath" }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TimeoutMs)) {
        try {
            $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
            if (Test-Path -LiteralPath $taskkill -PathType Leaf) {
                $killStart = New-Object Diagnostics.ProcessStartInfo
                $killStart.FileName = $taskkill
                $killStart.Arguments = "/F /T /PID $($process.Id)"
                $killStart.UseShellExecute = $false
                $killStart.CreateNoWindow = $true
                $killStart.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
                $killProcess = [Diagnostics.Process]::Start($killStart)
                [void]$killProcess.WaitForExit(10000)
            } else {
                $process.Kill()
            }
        } catch {}
        $process.WaitForExit()
        throw "PI_HIGH_CAPACITY_REPLAY_PROCESS_TIMEOUT: $FilePath $($Arguments -join ' ')"
    }
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    return [pscustomobject]@{
        exit_code = [int]$process.ExitCode
        stdout = [string]$stdout
        stderr = [string]$stderr
    }
}

function Get-NodeTestCount {
    param([Parameter(Mandatory)][string]$Text,[Parameter(Mandatory)][string]$Kind)
    $matches = [regex]::Matches($Text,"(?m)[^`r`n]*\b$([regex]::Escape($Kind))\s+(\d+)\s*`r?$")
    if ($matches.Count -eq 0) { throw "PI_HIGH_CAPACITY_REPLAY_TAP_COUNT_MISSING: $Kind" }
    return [int]$matches[$matches.Count - 1].Groups[1].Value
}

function Write-JsonAtomic {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Json)
    $target = [IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $temporary = "$target.tmp-$PID-$([guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllText($temporary,$Json,[Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $target -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Resolve-TypeScriptCompiler {
    param(
        [string]$ExplicitPath,
        [Parameter(Mandatory)][string]$BundledPath
    )
    $bundled = Get-RequiredFile -Path $BundledPath -Label 'sealed TypeScript 5.9.3 compiler'
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $explicit = Get-RequiredFile -Path $ExplicitPath -Label 'explicit TypeScript compiler override'
        if ([IO.Path]::GetFullPath($explicit) -cne [IO.Path]::GetFullPath($bundled)) {
            throw "PI_HIGH_CAPACITY_REPLAY_TYPESCRIPT_COMPILER_OVERRIDE_NONCANONICAL: $explicit"
        }
    }
    return $bundled
}

$scriptFiles = [ordered]@{
    runtime_ledger = @{ file = 'Test-PiSHighCapacityRuntimeLedger.test.mjs'; expected = 11 }
    provider_gate = @{ file = 'Test-PiSHighCapacityProviderGate.test.mjs'; expected = 10 }
    lifecycle_rpc = @{ file = 'Test-PiSHighCapacityLifecycleRpc.test.mjs'; expected = 8 }
    spawn_ticket_wiring = @{ file = 'Test-PiSHighCapacitySpawnTicketWiring.test.mjs'; expected = 9 }
    width_turn_preflight = @{ file = 'Test-PiSHighCapacityWidthTurnPreflight.test.mjs'; expected = 9 }
    public_tasks = @{ file = 'Test-PiSHighCapacityPublicTasks.test.mjs'; expected = 1 }
}
$supportFiles = @(
    'Test-PiSHighCapacitySupport.mjs',
    'Test-PiSHighCapacityMockPiChild.mjs'
)

$canonicalAgentDir = $null
$canonicalPiToolRoot = $null
$tempBase = [IO.Path]::GetFullPath('D:\XINAO_RESEARCH_RUNTIME\temp\pi-high-capacity-acceptance').TrimEnd('\','/')
$tempRoot = $null
$cleanupVerified = $false
$startedAt = [DateTimeOffset]::Now
$receipt = [ordered]@{
    schema = 'xinao.pi_s_high_capacity_replay_acceptance.v1'
    status = 'running'
    started_at = $startedAt.ToString('o')
    agent_dir = $null
    pi_tool_root = $null
    test_matrices = @()
    tests = [ordered]@{ expected = 48; observed = 0; passed = 0; failed = 0 }
    strict_typescript = [ordered]@{ status = 'not-run'; compiler = $null }
    type_shim = $null
    typescript_compiler_fixture = $null
    jiti_alias_projection = $null
    syntax = [ordered]@{ status = 'not-run'; files = 0 }
    runtime_projection = $null
    peer = $null
    temp_cleanup = $false
    error = $null
}

try {
    $canonicalAgentDir = Get-CanonicalDirectory -Path $AgentDir -Label 'AgentDir'
    $canonicalPiToolRoot = Get-CanonicalDirectory -Path $PiToolRoot -Label 'PiToolRoot'
    $receipt.agent_dir = $canonicalAgentDir
    $receipt.pi_tool_root = $canonicalPiToolRoot

    $typeShim = Get-VerifiedTypeShim -ShimRoot (Join-Path $PSScriptRoot 'Test-PiSHighCapacityTypeShim') -ManifestPath (Join-Path $PSScriptRoot 'Test-PiSHighCapacityTypeShim.manifest.json')
    $receipt.type_shim = [ordered]@{
        file_count = $typeShim.file_count
        total_bytes = $typeShim.total_bytes
        tree_sha256 = $typeShim.tree_sha256
        manifest_sha256 = $typeShim.manifest_sha256
        packages = $typeShim.packages
        declaration_closure = $typeShim.declaration_closure
        projections = $typeShim.projections
    }
    $compilerFixture = Get-VerifiedTypeScriptCompilerFixture -FixtureRoot (Join-Path $PSScriptRoot 'Test-PiSHighCapacityCompilerFixture') -ManifestPath (Join-Path $PSScriptRoot 'Test-PiSHighCapacityCompilerFixture.manifest.json')
    $receipt.typescript_compiler_fixture = [ordered]@{
        version = $compilerFixture.version
        file_count = $compilerFixture.file_count
        total_bytes = $compilerFixture.total_bytes
        tree_sha256 = $compilerFixture.tree_sha256
        manifest_sha256 = $compilerFixture.manifest_sha256
        compiler_sha256 = $compilerFixture.compiler_sha256
        implementation_sha256 = $compilerFixture.implementation_sha256
    }
    $subagentsRoot = Get-CanonicalDirectory -Path (Join-Path $canonicalAgentDir 'npm\node_modules\pi-subagents') -Label 'pi-subagents replay root'
    $peerPath = Get-RequiredFile -Path (Join-Path $canonicalAgentDir 'agents\peer.md') -Label 'peer frontmatter'
    $corePackageRoot = Get-CanonicalDirectory -Path (Join-Path $canonicalPiToolRoot 'node_modules\@earendil-works\pi-coding-agent') -Label 'Pi coding-agent replay package'
    $jitiAliasProjection = Get-VerifiedJitiAliasProjection -CorePackageRoot $corePackageRoot -ManifestPath (Join-Path $PSScriptRoot 'Test-PiSHighCapacityJitiAlias.manifest.json')
    $receipt.jiti_alias_projection = [ordered]@{
        manifest_sha256 = $jitiAliasProjection.manifest_sha256
        packages = $jitiAliasProjection.packages
        transport = 'createJiti options only'
        environment_injection = $false
    }
    $npmRuntime = Get-RequiredFile -Path (Join-Path $subagentsRoot 'src\runs\shared\xinao-pi-subagent-capacity-runtime.js') -Label 'npm capacity runtime'
    $coreRuntime = Get-RequiredFile -Path (Join-Path $corePackageRoot 'dist\core\xinao-pi-subagent-capacity-runtime.js') -Label 'core capacity runtime'
    [void](Get-RequiredFile -Path (Join-Path $corePackageRoot 'dist\core\sdk.js') -Label 'core sdk')
    [void](Get-RequiredFile -Path (Join-Path $canonicalAgentDir 'npm\node_modules\jiti\lib\jiti.mjs') -Label 'jiti')

    $npmRuntimeHash = (Get-FileHash -LiteralPath $npmRuntime -Algorithm SHA256).Hash.ToLowerInvariant()
    $coreRuntimeHash = (Get-FileHash -LiteralPath $coreRuntime -Algorithm SHA256).Hash.ToLowerInvariant()
    $npmRuntimeLength = (Get-Item -LiteralPath $npmRuntime).Length
    $coreRuntimeLength = (Get-Item -LiteralPath $coreRuntime).Length
    if ($npmRuntimeHash -cne $coreRuntimeHash -or $npmRuntimeLength -ne $coreRuntimeLength) {
        throw "PI_HIGH_CAPACITY_REPLAY_RUNTIME_PROJECTION_DRIFT: npm=$npmRuntimeHash/$npmRuntimeLength core=$coreRuntimeHash/$coreRuntimeLength"
    }
    $receipt.runtime_projection = [ordered]@{ byte_equal = $true; bytes = $npmRuntimeLength; sha256 = $npmRuntimeHash }
    $receipt.peer = [ordered]@{ path = $peerPath; sha256 = (Get-FileHash -LiteralPath $peerPath -Algorithm SHA256).Hash.ToLowerInvariant() }

    New-Item -ItemType Directory -Force -Path $tempBase | Out-Null
    $tempRoot = Join-Path $tempBase ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $canonicalTempPrefix = $tempBase + [IO.Path]::DirectorySeparatorChar
    $canonicalTempRoot = [IO.Path]::GetFullPath($tempRoot)
    if (-not $canonicalTempRoot.StartsWith($canonicalTempPrefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw "PI_HIGH_CAPACITY_REPLAY_TEMP_ESCAPE: $canonicalTempRoot"
    }

    $nodeCommand = Get-Command node -ErrorAction Stop
    $nodePath = $nodeCommand.Source
    $childEnvironment = @{
        XINAO_PI_HIGH_CAPACITY_AGENT_DIR = $canonicalAgentDir
        XINAO_PI_HIGH_CAPACITY_PI_TOOL_ROOT = $canonicalPiToolRoot
        XINAO_PI_HIGH_CAPACITY_TEMP_ROOT = $canonicalTempRoot
        NODE_PATH = (@(
            (Join-Path $canonicalAgentDir 'npm\node_modules'),
            (Join-Path $canonicalPiToolRoot 'node_modules'),
            (Join-Path $corePackageRoot 'node_modules')
        ) -join [IO.Path]::PathSeparator)
        TEMP = $canonicalTempRoot
        TMP = $canonicalTempRoot
        TMPDIR = $canonicalTempRoot
    }

    $allNodeFiles = @($scriptFiles.Values | ForEach-Object { Join-Path $PSScriptRoot $_.file }) + @($supportFiles | ForEach-Object { Join-Path $PSScriptRoot $_ })
    foreach ($file in $allNodeFiles) {
        $checked = Get-RequiredFile -Path $file -Label 'high-capacity acceptance script'
        $syntaxResult = Invoke-HiddenProcess -FilePath $nodePath -Arguments @('--check',$checked) -Environment $childEnvironment -TimeoutMs 30000
        if ($syntaxResult.exit_code -ne 0) {
            throw "PI_HIGH_CAPACITY_REPLAY_NODE_CHECK_FAILED: $checked`n$($syntaxResult.stderr)$($syntaxResult.stdout)"
        }
    }
    $receipt.syntax = [ordered]@{ status = 'pass'; files = $allNodeFiles.Count }

    $observedTests = 0
    $observedPass = 0
    $observedFail = 0
    $matrixReceipts = @()
    foreach ($entry in $scriptFiles.GetEnumerator()) {
        $testPath = Join-Path $PSScriptRoot $entry.Value.file
        $result = Invoke-HiddenProcess -FilePath $nodePath -Arguments @('--test',$testPath) -Environment $childEnvironment
        $combined = "$($result.stdout)`n$($result.stderr)"
        if ($result.exit_code -ne 0) {
            throw "PI_HIGH_CAPACITY_REPLAY_TEST_FAILED: $($entry.Key) exit=$($result.exit_code)`n$combined"
        }
        $tests = Get-NodeTestCount -Text $combined -Kind 'tests'
        $passed = Get-NodeTestCount -Text $combined -Kind 'pass'
        $failed = Get-NodeTestCount -Text $combined -Kind 'fail'
        if ($tests -ne [int]$entry.Value.expected -or $passed -ne [int]$entry.Value.expected -or $failed -ne 0) {
            throw "PI_HIGH_CAPACITY_REPLAY_TEST_COUNT_DRIFT: $($entry.Key) expected=$($entry.Value.expected) tests=$tests pass=$passed fail=$failed"
        }
        $observedTests += $tests
        $observedPass += $passed
        $observedFail += $failed
        $matrixReceipts += [ordered]@{ name = $entry.Key; expected = [int]$entry.Value.expected; tests = $tests; passed = $passed; failed = $failed }
    }
    if ($observedTests -ne 48 -or $observedPass -ne 48 -or $observedFail -ne 0) {
        throw "PI_HIGH_CAPACITY_REPLAY_AGGREGATE_DRIFT: tests=$observedTests pass=$observedPass fail=$observedFail"
    }
    $receipt.test_matrices = $matrixReceipts
    $receipt.tests = [ordered]@{ expected = 48; observed = $observedTests; passed = $observedPass; failed = $observedFail }

    $tscPath = Resolve-TypeScriptCompiler -ExplicitPath $TypeScriptCompilerPath -BundledPath $compilerFixture.compiler_path
    $fixtureNodeModules = Join-Path $typeShim.root 'node_modules'
    $fixtureCodingAgent = Join-Path $typeShim.root 'pi-coding-agent'
    $typeRoots = Join-Path $fixtureNodeModules '@types'
    [void](Get-CanonicalDirectory -Path $typeRoots -Label 'Node type roots')
    $strictConfigPath = Join-Path $canonicalTempRoot 'Test-PiSHighCapacityReplay.generated.tsconfig.json'
    $strictConfig = [ordered]@{
        compilerOptions = [ordered]@{
            target = 'ES2023'
            module = 'NodeNext'
            moduleResolution = 'NodeNext'
            strict = $true
            noUncheckedIndexedAccess = $true
            noEmit = $true
            skipLibCheck = $false
            allowImportingTsExtensions = $true
            resolveJsonModule = $true
            paths = [ordered]@{
                '@earendil-works/pi-agent-core' = @((ConvertTo-ForwardSlashPath -Path (Join-Path $fixtureNodeModules '@earendil-works\pi-agent-core\dist\index.d.ts')))
                '@earendil-works/pi-agent-core/*' = @((ConvertTo-ForwardSlashPath -Path (Join-Path $fixtureNodeModules '@earendil-works\pi-agent-core\dist\*.d.ts')))
                '@earendil-works/pi-ai' = @((ConvertTo-ForwardSlashPath -Path (Join-Path $fixtureNodeModules '@earendil-works\pi-ai\dist\index.d.ts')))
                '@earendil-works/pi-ai/*' = @((ConvertTo-ForwardSlashPath -Path (Join-Path $fixtureNodeModules '@earendil-works\pi-ai\dist\*.d.ts')))
                '@earendil-works/pi-coding-agent' = @((ConvertTo-ForwardSlashPath -Path (Join-Path $fixtureCodingAgent 'dist\index.d.ts')))
                '@earendil-works/pi-tui' = @((ConvertTo-ForwardSlashPath -Path (Join-Path $fixtureNodeModules '@earendil-works\pi-tui\dist\index.d.ts')))
            }
            types = @('node')
            typeRoots = @((ConvertTo-ForwardSlashPath -Path $typeRoots))
            forceConsistentCasingInFileNames = $true
        }
        include = @(
            (ConvertTo-ForwardSlashPath -Path (Join-Path $subagentsRoot 'index.ts')),
            ((ConvertTo-ForwardSlashPath -Path (Join-Path $subagentsRoot 'src')) + '/**/*.ts')
        )
    }
    [IO.File]::WriteAllText($strictConfigPath,($strictConfig | ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
    $strictResult = Invoke-HiddenProcess -FilePath $nodePath -Arguments @($tscPath,'--project',$strictConfigPath,'--pretty','false') -Environment $childEnvironment
    if ($strictResult.exit_code -ne 0) {
        throw "PI_HIGH_CAPACITY_REPLAY_STRICT_TSC_FAILED: exit=$($strictResult.exit_code)`n$($strictResult.stdout)`n$($strictResult.stderr)"
    }
    $receipt.strict_typescript = [ordered]@{ status = 'pass'; compiler = $tscPath; compiler_version = $compilerFixture.version; compiler_sha256 = $compilerFixture.compiler_sha256; strict = $true; no_unchecked_indexed_access = $true; skip_lib_check = $false; fixture_tree_sha256 = $typeShim.tree_sha256 }
    $receipt.status = 'verified'
} catch {
    $receipt.status = 'blocked'
    $receipt.error = [string]$_.Exception.Message
} finally {
    if ($null -ne $tempRoot) {
        $resolvedBase = [IO.Path]::GetFullPath($tempBase).TrimEnd('\','/')
        $resolvedTarget = [IO.Path]::GetFullPath($tempRoot)
        $requiredPrefix = $resolvedBase + [IO.Path]::DirectorySeparatorChar
        $leaf = Split-Path -Leaf $resolvedTarget
        if ($resolvedTarget.StartsWith($requiredPrefix,[StringComparison]::OrdinalIgnoreCase) -and $leaf -match '^[0-9a-f]{32}$') {
            if (Test-Path -LiteralPath $resolvedTarget) { Remove-Item -LiteralPath $resolvedTarget -Recurse -Force }
            $cleanupVerified = -not (Test-Path -LiteralPath $resolvedTarget)
        }
    }
    $receipt.temp_cleanup = $cleanupVerified
    if (-not $cleanupVerified -and $null -ne $tempRoot) {
        $receipt.status = 'blocked'
        if ([string]::IsNullOrWhiteSpace([string]$receipt.error)) { $receipt.error = "PI_HIGH_CAPACITY_REPLAY_TEMP_CLEANUP_FAILED: $tempRoot" }
    }
    $receipt.completed_at = [DateTimeOffset]::Now.ToString('o')
    $json = $receipt | ConvertTo-Json -Depth 12
    if (-not [string]::IsNullOrWhiteSpace($ReceiptPath)) { Write-JsonAtomic -Path $ReceiptPath -Json $json }
    Write-Output $json
}

if ($receipt.status -cne 'verified') { exit 1 }
