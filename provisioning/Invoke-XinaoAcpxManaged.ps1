#Requires -Version 7.2
[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet('ensure', 'status', 'acpx')]
    [string]$Target = 'ensure',
    [string]$ProjectRoot = 'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination',
    [switch]$ForceRepair,
    [switch]$Offline,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TargetArgs = @()
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$PSNativeCommandUseErrorActionPreference = $true
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$lockPath = Join-Path $ProjectRoot 'provisioning\acpx-toolchain-lock.json'

function Read-JsonFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "XINAO_ACPX_REQUIRED_FILE_MISSING: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-Sha256 {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '' }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Get-TextSha256 {
    param([Parameter(Mandatory)][string]$Value)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-', '')
    }
    finally {
        $sha.Dispose()
    }
}

function Get-TreeDigest {
    param(
        [Parameter(Mandatory)][string]$Root,
        [string[]]$ExcludeRelativePaths = @()
    )
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $excluded = @{}
    foreach ($relative in $ExcludeRelativePaths) {
        $excluded[$relative.Replace('\', '/')] = $true
    }
    $files = [Collections.Generic.List[object]]::new()
    $totalBytes = [long]0
    $rows = foreach ($file in Get-ChildItem -LiteralPath $fullRoot -File -Recurse | Sort-Object FullName) {
        $relative = $file.FullName.Substring($fullRoot.Length + 1).Replace('\', '/')
        if ($excluded.ContainsKey($relative)) { continue }
        $hash = Get-Sha256 -Path $file.FullName
        $files.Add([ordered]@{
            path = $relative
            length = [long]$file.Length
            sha256 = $hash
        })
        $totalBytes += [long]$file.Length
        '{0}|{1}|{2}' -f $relative, $file.Length, $hash
    }
    $material = $rows -join "`n"
    [pscustomobject]@{
        sha256 = Get-TextSha256 -Value $material
        file_count = @($rows).Count
        total_bytes = $totalBytes
        files = @($files)
    }
}

function Invoke-ExclusiveFileLock {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][scriptblock]$Action,
        [ValidateRange(1, 60)][int]$TimeoutSeconds = 45
    )
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $Path))
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $stream = $null
    while ($null -eq $stream) {
        try {
            $stream = [IO.FileStream]::new(
                $Path,
                [IO.FileMode]::OpenOrCreate,
                [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None
            )
        }
        catch [IO.IOException] {
            if ([DateTime]::UtcNow -ge $deadline) { throw 'XINAO_ACPX_PROVISION_LOCK_TIMEOUT' }
            Start-Sleep -Milliseconds 200
        }
    }
    try { return & $Action }
    finally { $stream.Dispose() }
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object]$Value
    )
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $Path))
    $temp = Join-Path (Split-Path -Parent $Path) ('.{0}.{1}.{2}.tmp' -f ([IO.Path]::GetFileName($Path)), $PID, [guid]::NewGuid().ToString('N'))
    [IO.File]::WriteAllText($temp, (($Value | ConvertTo-Json -Depth 20) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Write-JsonCreateNew {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object]$Value
    )
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $Path))
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(
        (($Value | ConvertTo-Json -Depth 100) + [Environment]::NewLine)
    )
    $stream = [IO.FileStream]::new(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Test-PathUnderRoot {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Root
    )
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    return $fullPath.Equals($fullRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $fullPath.StartsWith($fullRoot + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Move-CorruptPathAside {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Root
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    if (-not (Test-PathUnderRoot -Path $Path -Root $Root)) {
        throw "XINAO_ACPX_UNSAFE_REPAIR_TARGET: $Path"
    }
    $destination = "$Path.corrupt.$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss')).$([guid]::NewGuid().ToString('N'))"
    Move-Item -LiteralPath $Path -Destination $destination
}

$lock = Read-JsonFile -Path $lockPath
if ([int]$lock.schema_version -ne 1) { throw 'XINAO_ACPX_UNSUPPORTED_LOCK' }
foreach ($property in $lock.inputs.PSObject.Properties) {
    $inputPath = Join-Path $ProjectRoot ([string]$property.Name)
    $actual = Get-Sha256 -Path $inputPath
    if ($actual -ne [string]$property.Value) {
        throw "XINAO_ACPX_INPUT_HASH_MISMATCH: $inputPath expected=$($property.Value) actual=$actual"
    }
}

$packageLockPath = Join-Path $ProjectRoot 'provisioning\acpx-runtime\package-lock.json'
$packageJsonPath = Join-Path $ProjectRoot 'provisioning\acpx-runtime\package.json'
$packageLock = Get-Content -LiteralPath $packageLockPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
$packageJson = Read-JsonFile -Path $packageJsonPath
$lockedAcpx = $packageLock['packages']['node_modules/acpx']
if (
    [int]$packageLock['lockfileVersion'] -ne 3 -or
    [string]$packageJson.dependencies.acpx -ne [string]$lock.acpx.version -or
    [string]$lockedAcpx['version'] -ne [string]$lock.acpx.version -or
    [string]$lockedAcpx['resolved'] -ne [string]$lock.acpx.tarball_url -or
    [string]$lockedAcpx['integrity'] -ne [string]$lock.acpx.tarball_integrity
) {
    throw 'XINAO_ACPX_TOP_LEVEL_PACKAGE_LOCK_MISMATCH'
}

$runtimeRoot = [IO.Path]::GetFullPath([string]$lock.runtime_root)
$cacheRoot = [IO.Path]::GetFullPath([string]$lock.cache_root)
$downloadRoot = [IO.Path]::GetFullPath([string]$lock.download_root)
$nodeRoot = Join-Path $runtimeRoot ("node-{0}" -f [string]$lock.node.version)
$nodeExe = Join-Path $nodeRoot 'node.exe'
$npmCmd = Join-Path $nodeRoot 'npm.cmd'
$nodeArchive = Join-Path $downloadRoot ("node-v{0}-win-x64.zip" -f [string]$lock.node.version)

function Test-NodeExecutable {
    if (-not (Test-Path -LiteralPath $nodeExe -PathType Leaf)) { return $false }
    try { $version = (& $nodeExe --version).TrimStart('v') } catch { return $false }
    return (
        $version -eq [string]$lock.node.version -and
        (Get-Sha256 -Path $nodeExe) -eq [string]$lock.node.executable_sha256
    )
}

function Test-NpmCommand {
    return (
        (Test-Path -LiteralPath $npmCmd -PathType Leaf) -and
        (Get-Sha256 -Path $npmCmd) -eq [string]$lock.node.npm_cmd_sha256
    )
}

function Get-VerifiedNodeArchive {
    [void][IO.Directory]::CreateDirectory($downloadRoot)
    [void][IO.Directory]::CreateDirectory($runtimeRoot)
    if ((Get-Sha256 -Path $nodeArchive) -ne [string]$lock.node.archive_sha256) {
        if ($Offline) { throw 'XINAO_ACPX_NODE_ARCHIVE_MISSING_OFFLINE' }
        $downloaded = $false
        for ($attempt = 1; $attempt -le 3 -and -not $downloaded; $attempt++) {
            $tempArchive = "$nodeArchive.$PID.$([guid]::NewGuid().ToString('N')).download"
            try {
                Invoke-WebRequest -UseBasicParsing -Uri ([string]$lock.node.archive_url) -OutFile $tempArchive -TimeoutSec 60
                if ((Get-Sha256 -Path $tempArchive) -ne [string]$lock.node.archive_sha256) {
                    throw 'XINAO_ACPX_NODE_DOWNLOAD_HASH_MISMATCH'
                }
                Move-Item -LiteralPath $tempArchive -Destination $nodeArchive -Force
                $downloaded = $true
            }
            catch {
                Remove-Item -LiteralPath $tempArchive -Force -ErrorAction SilentlyContinue
                if ($attempt -eq 3) { throw }
                Start-Sleep -Seconds $attempt
            }
        }
    }
    $actual = Get-Sha256 -Path $nodeArchive
    if ($actual -ne [string]$lock.node.archive_sha256) {
        throw "XINAO_ACPX_NODE_HASH_MISMATCH: expected=$($lock.node.archive_sha256) actual=$actual"
    }
    return $nodeArchive
}

function Repair-NpmCommandFromArchive {
    $archive = Get-VerifiedNodeArchive
    $stage = Join-Path $runtimeRoot ('.node-stage-' + [guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($stage)
    try {
        Expand-Archive -LiteralPath $archive -DestinationPath $stage
        $expanded = Join-Path $stage ("node-v{0}-win-x64" -f [string]$lock.node.version)
        $stagedNode = Join-Path $expanded 'node.exe'
        $stagedNpm = Join-Path $expanded 'npm.cmd'
        if (
            (Get-Sha256 -Path $stagedNode) -ne [string]$lock.node.executable_sha256 -or
            (Get-Sha256 -Path $stagedNpm) -ne [string]$lock.node.npm_cmd_sha256
        ) {
            throw 'XINAO_ACPX_NODE_ARCHIVE_CONTENT_MISMATCH'
        }
        if (-not (Test-Path -LiteralPath $nodeRoot -PathType Container)) {
            throw 'XINAO_ACPX_NODE_ROOT_MISSING_DURING_NPM_REPAIR'
        }
        $tempNpm = Join-Path $nodeRoot ('.npm.cmd.{0}.{1}.tmp' -f $PID, [guid]::NewGuid().ToString('N'))
        try {
            Copy-Item -LiteralPath $stagedNpm -Destination $tempNpm
            if ((Get-Sha256 -Path $tempNpm) -ne [string]$lock.node.npm_cmd_sha256) {
                throw 'XINAO_ACPX_NPM_ATOMIC_STAGE_HASH_MISMATCH'
            }
            Move-Item -LiteralPath $tempNpm -Destination $npmCmd -Force
        }
        finally {
            Remove-Item -LiteralPath $tempNpm -Force -ErrorAction SilentlyContinue
        }
        if (-not (Test-NpmCommand)) { throw 'XINAO_ACPX_NPM_REPAIR_FAILED' }
    }
    finally {
        if (Test-Path -LiteralPath $stage) {
            if (-not (Test-PathUnderRoot -Path $stage -Root $runtimeRoot)) {
                throw "XINAO_ACPX_UNSAFE_NODE_STAGE_CLEANUP: $stage"
            }
            Remove-Item -LiteralPath $stage -Recurse -Force
        }
    }
}

function Ensure-Node {
    if ((Test-NodeExecutable) -and -not $ForceRepair) {
        if (-not (Test-NpmCommand)) { Repair-NpmCommandFromArchive }
        return
    }
    $archive = Get-VerifiedNodeArchive
    $stage = Join-Path $runtimeRoot ('.node-stage-' + [guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($stage)
    try {
        Expand-Archive -LiteralPath $archive -DestinationPath $stage
        $expanded = Join-Path $stage ("node-v{0}-win-x64" -f [string]$lock.node.version)
        if (-not (Test-Path -LiteralPath (Join-Path $expanded 'node.exe') -PathType Leaf)) {
            throw 'XINAO_ACPX_NODE_ARCHIVE_LAYOUT_INVALID'
        }
        if (
            (Get-Sha256 -Path (Join-Path $expanded 'node.exe')) -ne [string]$lock.node.executable_sha256 -or
            (Get-Sha256 -Path (Join-Path $expanded 'npm.cmd')) -ne [string]$lock.node.npm_cmd_sha256
        ) {
            throw 'XINAO_ACPX_NODE_ARCHIVE_CONTENT_MISMATCH'
        }
        Move-CorruptPathAside -Path $nodeRoot -Root $runtimeRoot
        Move-Item -LiteralPath $expanded -Destination $nodeRoot
        if (-not (Test-NodeExecutable) -or -not (Test-NpmCommand)) {
            throw 'XINAO_ACPX_NODE_VERSION_MISMATCH'
        }
    }
    finally {
        if (Test-Path -LiteralPath $stage) {
            if (-not (Test-PathUnderRoot -Path $stage -Root $runtimeRoot)) {
                throw "XINAO_ACPX_UNSAFE_NODE_STAGE_CLEANUP: $stage"
            }
            Remove-Item -LiteralPath $stage -Recurse -Force
        }
    }
}

function Invoke-NpmCiBounded {
    param([Parameter(Mandatory)][string]$Prefix)
    $logRoot = Join-Path $runtimeRoot 'logs'
    [void][IO.Directory]::CreateDirectory($logRoot)
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $stamp = '{0}-{1}-{2}' -f [DateTime]::UtcNow.ToString('yyyyMMddHHmmss'), $PID, [guid]::NewGuid().ToString('N')
        $stdoutPath = Join-Path $logRoot ("npm-ci-$stamp.stdout.log")
        $stderrPath = Join-Path $logRoot ("npm-ci-$stamp.stderr.log")
        $process = Start-Process -FilePath $npmCmd -ArgumentList @(
            'ci', '--prefix', $Prefix, '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund'
        ) -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
        $timedOut = -not $process.WaitForExit(60000)
        if ($timedOut) {
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
            $process.WaitForExit()
        }
        $exitCode = if ($timedOut) { -1 } else { $process.ExitCode }
        $process.Dispose()
        if ($exitCode -eq 0) {
            Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
            return
        }
        $tail = ''
        if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
            $tail = (Get-Content -LiteralPath $stderrPath -Tail 20) -join ' | '
        }
        if ($attempt -eq 3) {
            throw "XINAO_ACPX_NPM_CI_FAILED: exit=$exitCode timeout=$timedOut detail=$tail"
        }
        Start-Sleep -Seconds $attempt
    }
}

$packageLockHash = [string]$lock.inputs.'provisioning/acpx-runtime/package-lock.json'
$runnerInputHash = [string]$lock.inputs.'provisioning/acpx-runtime/operation-runner.mjs'
$generationMaterial = @(
    "acpx=$($lock.acpx.version)"
    "acpx_git=$($lock.acpx.git_head)"
    "acpx_tarball=$($lock.acpx.tarball_url)"
    "acpx_integrity=$($lock.acpx.tarball_integrity)"
    "node=$($lock.node.version)"
    "node_archive=$($lock.node.archive_sha256)"
    "node_exe=$($lock.node.executable_sha256)"
    "node_npm_cmd=$($lock.node.npm_cmd_sha256)"
    @($lock.inputs.PSObject.Properties | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Value)" })
) -join "`n"
$generationFingerprint = Get-TextSha256 -Value $generationMaterial
$generationId = 'acpx-' + ([string]$lock.acpx.version) + '-' +
    $generationFingerprint.Substring(0, 24).ToLowerInvariant()
$generationsRoot = Join-Path $runtimeRoot 'generations'
$generationPath = Join-Path $generationsRoot $generationId
$manifestPath = Join-Path $generationPath 'generation.json'
$cliPath = Join-Path $generationPath 'node_modules\acpx\dist\cli.js'
$packagePath = Join-Path $generationPath 'node_modules\acpx\package.json'
$runnerPath = Join-Path $generationPath 'operation-runner.mjs'
$currentPath = Join-Path $runtimeRoot 'current.json'
$provisionLockPath = Join-Path $runtimeRoot 'provision.lock'
$trustAnchorRoot = Join-Path $runtimeRoot 'trust\payload-anchors'
$trustAnchorPath = Join-Path $trustAnchorRoot ($generationId + '.json')

if ((Test-PathUnderRoot -Path $trustAnchorPath -Root $ProjectRoot) -or
    (Test-PathUnderRoot -Path $trustAnchorPath -Root $generationPath)) {
    throw 'XINAO_ACPX_TRUST_ANCHOR_NOT_EXTERNAL'
}

function Test-NodeRuntime {
    return (Test-NodeExecutable) -and (Test-NpmCommand)
}

function Get-TrustAnchorForTree {
    param([Parameter(Mandatory)][object]$Tree)
    if (-not (Test-Path -LiteralPath $trustAnchorPath -PathType Leaf)) { return $null }
    try {
        $anchor = Read-JsonFile -Path $trustAnchorPath
        if (
            [int]$anchor.schema_version -ne 1 -or
            [string]$anchor.generation_id -ne $generationId -or
            [string]$anchor.generation_fingerprint -ne $generationFingerprint -or
            [string]$anchor.package_lock_sha256 -ne $packageLockHash -or
            [string]$anchor.acpx_tarball_url -ne [string]$lock.acpx.tarball_url -or
            [string]$anchor.acpx_tarball_integrity -ne [string]$lock.acpx.tarball_integrity
        ) { return $null }

        $rows = [Collections.Generic.List[string]]::new()
        $seenPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        $totalBytes = [long]0
        foreach ($entry in @($anchor.files)) {
            $relative = [string]$entry.path
            $length = [long]$entry.length
            $hash = [string]$entry.sha256
            if (
                $relative -eq '' -or $relative -match '(^/|\\|(^|/)\.\.($|/))' -or
                $length -lt 0 -or $hash -notmatch '^[A-F0-9]{64}$' -or
                -not $seenPaths.Add($relative)
            ) { return $null }
            $rows.Add(('{0}|{1}|{2}' -f $relative, $length, $hash))
            $totalBytes += $length
        }
        $indexSha256 = Get-TextSha256 -Value ($rows -join "`n")
        if (
            $indexSha256 -ne [string]$anchor.file_index_sha256 -or
            $indexSha256 -ne [string]$anchor.payload_tree_sha256 -or
            $rows.Count -ne [int]$anchor.payload_file_count -or
            $totalBytes -ne [long]$anchor.payload_total_bytes -or
            [string]$Tree.sha256 -ne [string]$anchor.payload_tree_sha256 -or
            [int]$Tree.file_count -ne [int]$anchor.payload_file_count -or
            [long]$Tree.total_bytes -ne [long]$anchor.payload_total_bytes
        ) { return $null }
        return $anchor
    }
    catch { return $null }
}

function Ensure-TrustAnchor {
    param([Parameter(Mandatory)][object]$Tree)
    if (Test-Path -LiteralPath $trustAnchorPath -PathType Leaf) {
        $existing = Get-TrustAnchorForTree -Tree $Tree
        if ($null -eq $existing) { throw 'XINAO_ACPX_TRUST_ANCHOR_CONFLICT' }
        return $existing
    }
    $anchor = [ordered]@{
        schema_version = 1
        generation_id = $generationId
        generation_fingerprint = $generationFingerprint
        package_lock_sha256 = $packageLockHash
        acpx_tarball_url = [string]$lock.acpx.tarball_url
        acpx_tarball_integrity = [string]$lock.acpx.tarball_integrity
        node_archive_sha256 = [string]$lock.node.archive_sha256
        payload_tree_sha256 = [string]$Tree.sha256
        file_index_sha256 = [string]$Tree.sha256
        payload_file_count = [int]$Tree.file_count
        payload_total_bytes = [long]$Tree.total_bytes
        files = @($Tree.files)
        established_at_utc = [DateTime]::UtcNow.ToString('o')
        provenance = 'fresh npm ci from frozen package lock; install scripts disabled'
    }
    try {
        Write-JsonCreateNew -Path $trustAnchorPath -Value $anchor
    }
    catch [IO.IOException] {
        $raced = Get-TrustAnchorForTree -Tree $Tree
        if ($null -eq $raced) { throw 'XINAO_ACPX_TRUST_ANCHOR_CREATE_RACE_CONFLICT' }
        return $raced
    }
    $written = Get-TrustAnchorForTree -Tree $Tree
    if ($null -eq $written) { throw 'XINAO_ACPX_TRUST_ANCHOR_WRITE_INVALID' }
    return $written
}

function Write-CurrentPointer {
    Write-JsonAtomic -Path $currentPath -Value ([ordered]@{
        schema_version = 3
        generation_id = $generationId
        generation_path = $generationPath
        node_path = $nodeExe
        cli_path = $cliPath
        runner_path = $runnerPath
        generation_fingerprint = $generationFingerprint
        trust_anchor_path = $trustAnchorPath
        trust_anchor_sha256 = Get-Sha256 -Path $trustAnchorPath
        updated_at_utc = [DateTime]::UtcNow.ToString('o')
    })
}

function Test-CurrentPointer {
    if (-not (Test-Path -LiteralPath $currentPath -PathType Leaf)) { return $false }
    try { $current = Read-JsonFile -Path $currentPath } catch { return $false }
    return (
        [int]$current.schema_version -eq 3 -and
        [string]$current.generation_id -eq $generationId -and
        [string]$current.generation_path -eq $generationPath -and
        [string]$current.node_path -eq $nodeExe -and
        [string]$current.cli_path -eq $cliPath -and
        [string]$current.runner_path -eq $runnerPath -and
        [string]$current.generation_fingerprint -eq $generationFingerprint -and
        [string]$current.trust_anchor_path -eq $trustAnchorPath -and
        [string]$current.trust_anchor_sha256 -eq (Get-Sha256 -Path $trustAnchorPath)
    )
}

function Get-ValidGeneration {
    if ($ForceRepair -or -not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { return $null }
    try { $manifest = Read-JsonFile -Path $manifestPath } catch { return $null }
    if ([int]$manifest.schema_version -ne 3 -or [string]$manifest.generation_id -ne $generationId) {
        return $null
    }
    if ([string]$manifest.generation_fingerprint -ne $generationFingerprint) { return $null }
    if ((Get-Sha256 -Path $cliPath) -ne [string]$manifest.cli_sha256) { return $null }
    if ((Get-Sha256 -Path $packagePath) -ne [string]$manifest.package_sha256) { return $null }
    if ((Get-Sha256 -Path $runnerPath) -ne $runnerInputHash) { return $null }
    try { $package = Read-JsonFile -Path $packagePath } catch { return $null }
    if ([string]$package.version -ne [string]$lock.acpx.version) { return $null }
    $tree = Get-TreeDigest -Root $generationPath -ExcludeRelativePaths @('generation.json')
    $anchor = Get-TrustAnchorForTree -Tree $tree
    if ($null -eq $anchor) { return $null }
    if (
        [string]$tree.sha256 -ne [string]$manifest.payload_tree_sha256 -or
        [int]$tree.file_count -ne [int]$manifest.payload_file_count -or
        [long]$tree.total_bytes -ne [long]$manifest.payload_total_bytes -or
        [string]$manifest.file_index_sha256 -ne [string]$anchor.file_index_sha256 -or
        [string]$manifest.trust_anchor_path -ne $trustAnchorPath -or
        [string]$manifest.trust_anchor_sha256 -ne (Get-Sha256 -Path $trustAnchorPath)
    ) {
        return $null
    }
    return $manifest
}

function Ensure-Generation {
    $valid = Get-ValidGeneration
    if ($null -ne $valid) {
        $pointerRepaired = -not (Test-CurrentPointer)
        if ($pointerRepaired) { Write-CurrentPointer }
        return [pscustomobject]@{ FastPath = $true; PointerRepaired = $pointerRepaired; Manifest = $valid }
    }
    if ($Offline) { throw 'XINAO_ACPX_GENERATION_MISSING_OFFLINE' }
    [void][IO.Directory]::CreateDirectory($generationsRoot)
    [void][IO.Directory]::CreateDirectory($cacheRoot)
    $stage = Join-Path $generationsRoot ('.stage-' + [guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($stage)
    try {
        foreach ($name in @('package.json', 'package-lock.json', '.npmrc')) {
            Copy-Item -LiteralPath (Join-Path $ProjectRoot "provisioning\acpx-runtime\$name") -Destination (Join-Path $stage $name)
        }
        Copy-Item -LiteralPath (Join-Path $ProjectRoot 'provisioning\acpx-runtime\operation-runner.mjs') -Destination (Join-Path $stage 'operation-runner.mjs')
        $priorCache = $env:npm_config_cache
        try {
            $env:npm_config_cache = $cacheRoot
            Invoke-NpmCiBounded -Prefix $stage
        }
        finally {
            $env:npm_config_cache = $priorCache
        }
        $stageCli = Join-Path $stage 'node_modules\acpx\dist\cli.js'
        $stagePackage = Join-Path $stage 'node_modules\acpx\package.json'
        $reported = (& $nodeExe $stageCli --version).Trim()
        if ($reported -ne [string]$lock.acpx.version) {
            throw "XINAO_ACPX_VERSION_MISMATCH: expected=$($lock.acpx.version) actual=$reported"
        }
        $tree = Get-TreeDigest -Root $stage
        $anchor = Ensure-TrustAnchor -Tree $tree
        $manifest = [ordered]@{
            schema_version = 3
            generation_id = $generationId
            generation_fingerprint = $generationFingerprint
            acpx_version = [string]$lock.acpx.version
            acpx_git_head = [string]$lock.acpx.git_head
            node_version = (& $nodeExe --version).TrimStart('v')
            node_executable_sha256 = Get-Sha256 -Path $nodeExe
            package_lock_sha256 = $packageLockHash
            cli_sha256 = Get-Sha256 -Path $stageCli
            package_sha256 = Get-Sha256 -Path $stagePackage
            runner_sha256 = Get-Sha256 -Path (Join-Path $stage 'operation-runner.mjs')
            payload_tree_sha256 = [string]$tree.sha256
            file_index_sha256 = [string]$anchor.file_index_sha256
            payload_file_count = [int]$tree.file_count
            payload_total_bytes = [long]$tree.total_bytes
            trust_anchor_path = $trustAnchorPath
            trust_anchor_sha256 = Get-Sha256 -Path $trustAnchorPath
            installed_at_utc = [DateTime]::UtcNow.ToString('o')
            install_scripts = 'disabled'
        }
        Write-JsonAtomic -Path (Join-Path $stage 'generation.json') -Value $manifest
        Move-CorruptPathAside -Path $generationPath -Root $generationsRoot
        Move-Item -LiteralPath $stage -Destination $generationPath
        Write-CurrentPointer
        return [pscustomobject]@{ FastPath = $false; PointerRepaired = $false; Manifest = $manifest }
    }
    finally {
        if (Test-Path -LiteralPath $stage) {
            if (-not (Test-PathUnderRoot -Path $stage -Root $generationsRoot)) {
                throw "XINAO_ACPX_UNSAFE_STAGE_CLEANUP: $stage"
            }
            Remove-Item -LiteralPath $stage -Recurse -Force
        }
    }
}

function Remove-StaleNodeStages {
    if (-not (Test-Path -LiteralPath $runtimeRoot -PathType Container)) { return }
    foreach ($candidate in Get-ChildItem -LiteralPath $runtimeRoot -Directory -Filter '.node-stage-*') {
        if (-not (Test-PathUnderRoot -Path $candidate.FullName -Root $runtimeRoot)) {
            throw "XINAO_ACPX_UNSAFE_NODE_STAGE_CLEANUP: $($candidate.FullName)"
        }
        Remove-Item -LiteralPath $candidate.FullName -Recurse -Force
    }
}

function Write-QueueOwnershipEvent {
    param(
        [Parameter(Mandatory)][string]$Code,
        [Parameter(Mandatory)][string]$LockPath,
        [string]$Detail = ''
    )
    $eventPath = Join-Path $runtimeRoot 'queue-ownership-events.jsonl'
    $value = [ordered]@{
        at_utc = [DateTime]::UtcNow.ToString('o')
        code = $Code
        lock_path = $LockPath
        detail = $Detail
        verifier_pid = $PID
    }
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes((($value | ConvertTo-Json -Compress) + [Environment]::NewLine))
    $stream = [IO.FileStream]::new($eventPath, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Protect-AcpxQueueOwnership {
    $profileRoot = if ($env:USERPROFILE) { $env:USERPROFILE } elseif ($env:HOME) { $env:HOME } else { '' }
    if ($profileRoot -eq '') { return }
    $queueRoot = Join-Path ([IO.Path]::GetFullPath($profileRoot)) '.acpx\queues'
    if (-not (Test-Path -LiteralPath $queueRoot -PathType Container)) { return }
    $quarantineRoot = Join-Path ([IO.Path]::GetFullPath($profileRoot)) '.acpx\quarantine'
    foreach ($lockFile in Get-ChildItem -LiteralPath $queueRoot -File -Filter '*.lock') {
        $valid = $false
        $detail = ''
        try {
            $lease = Read-JsonFile -Path $lockFile.FullName
            $ownerPid = [int]$lease.pid
            $createdAt = if ($lease.createdAt -is [DateTime]) {
                ([DateTime]$lease.createdAt).ToUniversalTime()
            }
            else {
                [DateTimeOffset]::Parse([string]$lease.createdAt).UtcDateTime
            }
            $process = Get-Process -Id $ownerPid -ErrorAction Stop
            $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction Stop
            $commandLine = [string]$cim.CommandLine
            $processStart = $process.StartTime.ToUniversalTime()
            $valid =
                ([string]$cim.ExecutablePath).Equals($nodeExe, [StringComparison]::OrdinalIgnoreCase) -and
                $commandLine.Contains('__queue-owner', [StringComparison]::Ordinal) -and
                $commandLine.Contains((Join-Path $runtimeRoot 'generations'), [StringComparison]::OrdinalIgnoreCase) -and
                $commandLine.Contains('node_modules\acpx\dist\cli.js', [StringComparison]::OrdinalIgnoreCase) -and
                [Math]::Abs(($processStart - $createdAt).TotalSeconds) -le 30
            if (-not $valid) {
                $detail = "pid=$ownerPid process_start=$($processStart.ToString('o')) lease_created=$($createdAt.ToString('o'))"
            }
        }
        catch {
            $detail = $_.Exception.Message
        }
        if ($valid) { continue }
        [void][IO.Directory]::CreateDirectory($quarantineRoot)
        $destination = Join-Path $quarantineRoot ("{0}.{1}.{2}.quarantined" -f $lockFile.Name, [DateTime]::UtcNow.ToString('yyyyMMddHHmmss'), [guid]::NewGuid().ToString('N'))
        try {
            Move-Item -LiteralPath $lockFile.FullName -Destination $destination
            Write-QueueOwnershipEvent -Code 'ACPX_QUEUE_LOCK_QUARANTINED' -LockPath $lockFile.FullName -Detail $detail
        }
        catch {
            Write-QueueOwnershipEvent -Code 'ACPX_QUEUE_LOCK_QUARANTINE_FAILED' -LockPath $lockFile.FullName -Detail $_.Exception.Message
            throw "XINAO_ACPX_UNSAFE_QUEUE_LOCK: $($lockFile.FullName)"
        }
    }
}

if ($Target -eq 'status') {
    $snapshot = Invoke-ExclusiveFileLock -Path $provisionLockPath -TimeoutSeconds 10 -Action {
        $nodeValid = Test-NodeRuntime
        $valid = if ($nodeValid) { Get-ValidGeneration } else { $null }
        $pointerValid = $null -ne $valid -and (Test-CurrentPointer)
        [ordered]@{
            status = if ($null -ne $valid -and $pointerValid) { 'verified' } else { 'repair_required' }
            generation_id = $generationId
            generation_path = $generationPath
            generation_fingerprint = $generationFingerprint
            node_ready = $nodeValid
            trust_anchor_path = $trustAnchorPath
            trust_anchor_valid = $null -ne $valid
            current_pointer_valid = $pointerValid
            fast_path_ready = $null -ne $valid -and $pointerValid
        }
    }
    $snapshot | ConvertTo-Json -Depth 10
    return
}

$result = Invoke-ExclusiveFileLock -Path $provisionLockPath -Action {
    Remove-StaleNodeStages
    Ensure-Node
    Ensure-Generation
}
if ($Target -eq 'ensure') {
    [ordered]@{
        status = 'verified'
        generation_id = $generationId
        generation_path = $generationPath
        fast_path = [bool]$result.FastPath
        current_pointer_repaired = [bool]$result.PointerRepaired
        acpx_version = [string]$result.Manifest.acpx_version
        node_version = [string]$result.Manifest.node_version
        payload_tree_sha256 = [string]$result.Manifest.payload_tree_sha256
        file_index_sha256 = [string]$result.Manifest.file_index_sha256
        trust_anchor_path = [string]$result.Manifest.trust_anchor_path
        trust_anchor_sha256 = [string]$result.Manifest.trust_anchor_sha256
    } | ConvertTo-Json -Depth 10
    return
}

# acpx owns its heartbeat/owner-generation queue protocol. This thin launcher
# never moves or quarantines queue locks based on a single ambiguous read.
& $nodeExe $cliPath @TargetArgs
