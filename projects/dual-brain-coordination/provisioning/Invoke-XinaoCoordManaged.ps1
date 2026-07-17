#Requires -Version 7.2
<#
.SYNOPSIS
  Managed xinao-coord CLI/MCP launcher with generation fast-path provisioning.

.DESCRIPTION
  Temporal live MCP/CLI invocation:
    - Pass env vars on the caller process, or use -TemporalEnabled/-TemporalLive/-TemporalMock/-TemporalAddress.
    - Convenience targets: -Target temporal-status | temporal-start-promoted
    - Equivalent CLI: -Target cli -TargetArgs @('temporal-status')
    - Promoted start with args: -Target temporal-start-promoted -TargetArgs @('--task-id','<id>')
    - Force generation rebuild after uv sync / source change: -RebuildGeneration (alias for -ForceRepair).
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet('mcp', 'cli', 'python', 'ensure', 'status', 'temporal-status', 'temporal-start-promoted')]
    [string]$Target = 'cli',
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeRoot = '',
    [switch]$ForceRepair,
    [switch]$RebuildGeneration,
    [switch]$Offline,
    [string]$TemporalEnabled = '',
    [string]$TemporalLive = '',
    [string]$TemporalMock = '',
    [string]$TemporalAddress = '',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TargetArgs = @()
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$toolchainPath = Join-Path $ProjectRoot 'provisioning\toolchain-lock.json'
if ($RebuildGeneration) { $ForceRepair = $true }

function Set-TemporalChildEnvironment {
    param(
        [string]$Enabled = '',
        [string]$Live = '',
        [string]$Mock = '',
        [string]$Address = ''
    )
    $bindings = @(
        @{ Name = 'XINAO_TEMPORAL_ENABLED'; Value = $Enabled },
        @{ Name = 'XINAO_TEMPORAL_LIVE'; Value = $Live },
        @{ Name = 'XINAO_TEMPORAL_MOCK'; Value = $Mock },
        @{ Name = 'XINAO_TEMPORAL_ADDRESS'; Value = $Address }
    )
    foreach ($binding in $bindings) {
        if ([string]$binding.Value -ne '') {
            Set-Item -Path ("Env:{0}" -f $binding.Name) -Value ([string]$binding.Value)
        }
    }
}

function Resolve-InvocationTarget {
    param(
        [Parameter(Mandatory)][string]$RequestedTarget,
        [string[]]$RequestedArgs = @()
    )
    switch ($RequestedTarget) {
        'temporal-status' {
            return [pscustomobject]@{
                Target = 'cli'
                TargetArgs = if ($RequestedArgs.Count -gt 0) { $RequestedArgs } else { @('temporal-status') }
            }
        }
        'temporal-start-promoted' {
            $args = [Collections.Generic.List[string]]::new()
            if ($RequestedArgs.Count -eq 0 -or $RequestedArgs[0] -ne 'temporal-start-promoted') {
                [void]$args.Add('temporal-start-promoted')
            }
            foreach ($argument in $RequestedArgs) { [void]$args.Add($argument) }
            return [pscustomobject]@{
                Target = 'cli'
                TargetArgs = @($args)
            }
        }
        default {
            return [pscustomobject]@{
                Target = $RequestedTarget
                TargetArgs = $RequestedArgs
            }
        }
    }
}

function Read-JsonFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "XINAO_COORD_REQUIRED_FILE_MISSING: $Path"
    }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "XINAO_COORD_INVALID_JSON: $Path :: $($_.Exception.Message)"
    }
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object]$Value
    )
    $parent = Split-Path -Parent $Path
    [void][IO.Directory]::CreateDirectory($parent)
    $temp = Join-Path $parent ('.{0}.{1}.{2}.tmp' -f ([IO.Path]::GetFileName($Path)), $PID, [guid]::NewGuid().ToString('N'))
    [IO.File]::WriteAllText($temp, (($Value | ConvertTo-Json -Depth 20) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Get-Sha256 {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '' }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Assert-ExpectedHash {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Expected
    )
    $actual = Get-Sha256 -Path $Path
    if ($actual -ne $Expected) {
        throw "XINAO_COORD_HASH_MISMATCH: $Path expected=$Expected actual=$actual"
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

function Invoke-CapturedProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$WorkingDirectory = $ProjectRoot,
        [string]$Label = 'process',
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 300
    )
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $FilePath
    $start.WorkingDirectory = $WorkingDirectory
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in $Arguments) { [void]$start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw "XINAO_COORD_PROCESS_START_FAILED: $Label" }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $process.Kill($true) } catch { }
        try { $process.WaitForExit() } catch { }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $process.Dispose()
        $tail = (($stderr + [Environment]::NewLine + $stdout) -split "`r?`n" | Select-Object -Last 30) -join ' | '
        throw "XINAO_COORD_PROCESS_TIMEOUT: label=$Label timeout_seconds=$TimeoutSeconds :: $tail"
    }
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $process.ExitCode
    $process.Dispose()
    if ($exitCode -ne 0) {
        $tail = (($stderr + [Environment]::NewLine + $stdout) -split "`r?`n" | Select-Object -Last 30) -join ' | '
        throw "XINAO_COORD_PROCESS_FAILED: $Label exit=$exitCode :: $tail"
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Stdout = $stdout; Stderr = $stderr }
}

function Invoke-WithFileLock {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][scriptblock]$Action,
        [int]$TimeoutSeconds = 600
    )
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $Path))
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $stream = $null
    while ($null -eq $stream -and [DateTime]::UtcNow -lt $deadline) {
        try {
            $stream = [IO.FileStream]::new($Path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        }
        catch [IO.IOException] {
            Start-Sleep -Milliseconds 150
        }
    }
    if ($null -eq $stream) { throw "XINAO_COORD_PROVISION_LOCK_TIMEOUT: $Path" }
    try { return & $Action } finally { $stream.Dispose() }
}

$toolchain = Read-JsonFile -Path $toolchainPath
if ([int]$toolchain.schema_version -ne 1 -or [string]$toolchain.project -ne 'xinao-dual-brain-coordination') {
    throw 'XINAO_COORD_UNSUPPORTED_TOOLCHAIN_LOCK'
}
if ($RuntimeRoot -eq '') { $RuntimeRoot = [string]$toolchain.runtime_root }
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$generationsRoot = Join-Path $RuntimeRoot 'generations'
$currentPath = Join-Path $RuntimeRoot 'current.json'
$provisionLock = Join-Path $RuntimeRoot 'provision.lock'
$eventsPath = Join-Path $RuntimeRoot 'provision-events.jsonl'
$buildConstraints = Join-Path $ProjectRoot 'provisioning\build-constraints.txt'
$uvCacheRoot = [IO.Path]::GetFullPath([string]$toolchain.cache_root)
$wheelCacheRoot = [IO.Path]::GetFullPath([string]$toolchain.wheel_cache_root)

function Write-ProvisionEvent {
    param(
        [Parameter(Mandatory)][string]$Code,
        [Parameter(Mandatory)][string]$GenerationId,
        [string]$Detail = ''
    )
    [void][IO.Directory]::CreateDirectory($RuntimeRoot)
    $value = [ordered]@{
        at_utc = [DateTime]::UtcNow.ToString('o')
        code = $Code
        generation_id = $GenerationId
        detail = $Detail
        pid = $PID
    }
    $line = ($value | ConvertTo-Json -Compress) + [Environment]::NewLine
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($line)
    $stream = [IO.FileStream]::new($eventsPath, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Assert-ProjectInputs {
    foreach ($property in $toolchain.inputs.PSObject.Properties) {
        $path = Join-Path $ProjectRoot ([string]$property.Name)
        Assert-ExpectedHash -Path $path -Expected ([string]$property.Value)
    }
}

function Invoke-CapturedProcessWithRetry {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$WorkingDirectory = $ProjectRoot,
        [string]$Label = 'process',
        [int]$Attempts = 3,
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 600
    )
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            return Invoke-CapturedProcess -FilePath $FilePath -Arguments $Arguments -WorkingDirectory $WorkingDirectory -Label $Label -TimeoutSeconds $TimeoutSeconds
        }
        catch {
            $transient = $_.Exception.Message -match '(?i)timed?\s*out|request failed|failed to fetch|connection|temporar|429|502|503|network'
            if (-not $transient -or $attempt -ge $Attempts) { throw }
            $delay = [Math]::Min(8, [Math]::Pow(2, $attempt - 1))
            [Console]::Error.WriteLine("XINAO_COORD_TRANSIENT_RETRY: label=$Label attempt=$attempt delay_seconds=$delay")
            Start-Sleep -Seconds $delay
        }
    }
}

function Get-CachedProjectWheel {
    param([Parameter(Mandatory)][string]$Fingerprint)
    $directory = Join-Path $wheelCacheRoot $Fingerprint.ToLowerInvariant()
    $manifestPath = Join-Path $directory 'wheel.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { return $null }
    try { $manifest = Read-JsonFile -Path $manifestPath } catch { return $null }
    if ([string]$manifest.source_fingerprint -ne $Fingerprint) { return $null }
    $wheel = Join-Path $directory ([string]$manifest.filename)
    if ((Get-Sha256 -Path $wheel) -ne [string]$manifest.sha256) { return $null }
    return $wheel
}

function Save-CachedProjectWheel {
    param(
        [Parameter(Mandatory)][string]$Fingerprint,
        [Parameter(Mandatory)][string]$WheelPath
    )
    $directory = Join-Path $wheelCacheRoot $Fingerprint.ToLowerInvariant()
    [void][IO.Directory]::CreateDirectory($directory)
    $destination = Join-Path $directory ([IO.Path]::GetFileName($WheelPath))
    $temp = "$destination.$PID.$([guid]::NewGuid().ToString('N')).tmp"
    Copy-Item -LiteralPath $WheelPath -Destination $temp -Force
    Move-Item -LiteralPath $temp -Destination $destination -Force
    Write-JsonAtomic -Path (Join-Path $directory 'wheel.json') -Value ([ordered]@{
        schema_version = 1
        source_fingerprint = $Fingerprint
        filename = [IO.Path]::GetFileName($destination)
        sha256 = Get-Sha256 -Path $destination
        cached_at_utc = [DateTime]::UtcNow.ToString('o')
    })
    return $destination
}

function Get-SourceFingerprint {
    $relativePaths = @(
        'pyproject.toml',
        'README.md',
        'uv.lock',
        'provisioning\build-constraints.txt',
        'provisioning\toolchain-lock.json',
        'provisioning\Invoke-XinaoCoordManaged.ps1',
        'provisioning\Invoke-XinaoCoordReconcile.ps1',
        'configs\modules\amq.toml',
        'configs\modules\m_keep.toml',
        'configs\modules\temporal.toml'
    )
    $sourceRoot = Join-Path $ProjectRoot 'src'
    $relativePaths += Get-ChildItem -LiteralPath $sourceRoot -File -Recurse | Where-Object {
        $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -notin @('.pyc', '.pyo', '.pyd.tmp')
    } | ForEach-Object {
        [IO.Path]::GetRelativePath($ProjectRoot, $_.FullName)
    }
    $rows = foreach ($relative in ($relativePaths | Sort-Object -Unique)) {
        $path = Join-Path $ProjectRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "XINAO_COORD_SOURCE_FILE_MISSING: $path"
        }
        '{0}|{1}|{2}' -f ($relative -replace '\\', '/'), (Get-Item -LiteralPath $path).Length, (Get-Sha256 -Path $path)
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($rows -join "`n"))))).Replace('-', '')
    }
    finally {
        $sha.Dispose()
    }
}

function Get-ContentTreeFingerprint {
    param(
        [Parameter(Mandatory)][string]$Root,
        [string[]]$ExcludeRelativePath = @()
    )
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "XINAO_COORD_INTEGRITY_ROOT_MISSING: $Root"
    }
    $fullRoot = [IO.Path]::GetFullPath($Root)
    $excluded = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($relative in $ExcludeRelativePath) { [void]$excluded.Add(($relative -replace '\\', '/')) }
    $files = @(Get-ChildItem -LiteralPath $fullRoot -File -Recurse | Where-Object {
        $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -notin @('.pyc', '.pyo')
    })
    $rows = [Collections.Generic.List[string]]::new()
    [long]$totalBytes = 0
    foreach ($file in ($files | Sort-Object FullName)) {
        $relative = ([IO.Path]::GetRelativePath($fullRoot, $file.FullName) -replace '\\', '/')
        if ($excluded.Contains($relative)) { continue }
        $totalBytes += $file.Length
        $rows.Add(('{0}|{1}|{2}' -f $relative, $file.Length, (Get-Sha256 -Path $file.FullName)))
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($rows -join "`n"))))).Replace('-', '')
    }
    finally {
        $sha.Dispose()
    }
    return [pscustomobject]@{ sha256 = $digest; file_count = $rows.Count; total_bytes = $totalBytes }
}

function Get-PythonRuntimeProbe {
    param([Parameter(Mandatory)][string]$PythonPath)
    $probe = Invoke-CapturedProcess -FilePath $PythonPath -Arguments @(
        '-c',
        'import apsw,importlib.metadata as m,json,mcp,opentelemetry,os,platform,sys; machine=platform.machine().lower(); target="x86_64-pc-windows-msvc" if os.name=="nt" and machine in {"amd64","x86_64"} else f"{machine}-{sys.platform}"; print(json.dumps({"python":platform.python_version(),"implementation":sys.implementation.name,"platform":target,"base_prefix":sys.base_prefix,"project":m.version("xinao-dual-brain-coordination"),"mcp":m.version("mcp"),"a2a-sdk":m.version("a2a-sdk"),"apsw":m.version("apsw"),"opentelemetry-api":m.version("opentelemetry-api"),"temporalio":m.version("temporalio")}))'
    ) -Label 'generation runtime probe' -TimeoutSeconds 60
    return $probe.Stdout.Trim() | ConvertFrom-Json
}

function Test-PythonRuntimeProbe {
    param([Parameter(Mandatory)][object]$Probe)
    return [string]$Probe.python -eq [string]$toolchain.python.request -and
        [string]$Probe.implementation -eq [string]$toolchain.python.implementation -and
        [string]$Probe.platform -eq [string]$toolchain.python.platform -and
        [string]$Probe.project -eq '0.1.0' -and
        [string]$Probe.mcp -eq '1.28.0' -and
        [string]$Probe.temporalio -eq '1.30.0'
}

function Get-GenerationDescriptor {
    param([Parameter(Mandatory)][string]$Fingerprint)
    $id = 'coord-' + $Fingerprint.Substring(0, 24).ToLowerInvariant()
    $path = Join-Path $generationsRoot $id
    return [pscustomobject]@{
        Id = $id
        Path = $path
        Venv = Join-Path $path 'venv'
        Manifest = Join-Path $path 'generation.json'
        Python = Join-Path $path 'venv\Scripts\python.exe'
        Cli = Join-Path $path 'venv\Scripts\xinao-coord.exe'
        Mcp = Join-Path $path 'venv\Scripts\xinao-coord-mcp.exe'
    }
}

function Get-ValidGeneration {
    param(
        [Parameter(Mandatory)][object]$Descriptor,
        [Parameter(Mandatory)][string]$Fingerprint
    )
    if ($ForceRepair -or -not (Test-Path -LiteralPath $Descriptor.Manifest -PathType Leaf)) { return $null }
    try { $manifest = Read-JsonFile -Path $Descriptor.Manifest } catch { return $null }
    if ([int]$manifest.schema_version -ne 2 -or [string]$manifest.generation_id -ne $Descriptor.Id -or [string]$manifest.source_fingerprint -ne $Fingerprint) { return $null }
    if (-not (Test-PathUnderRoot -Path $Descriptor.Path -Root $generationsRoot)) { return $null }
    foreach ($item in @(
        @{ Path = $Descriptor.Python; Hash = [string]$manifest.targets.python_sha256 },
        @{ Path = $Descriptor.Cli; Hash = [string]$manifest.targets.cli_sha256 },
        @{ Path = $Descriptor.Mcp; Hash = [string]$manifest.targets.mcp_sha256 }
    )) {
        if ((Get-Sha256 -Path $item.Path) -ne $item.Hash) { return $null }
    }
    try {
        $probe = Get-PythonRuntimeProbe -PythonPath $Descriptor.Python
        if (-not (Test-PythonRuntimeProbe -Probe $probe)) { return $null }
        $baseRoot = [IO.Path]::GetFullPath([string]$manifest.python.base_prefix)
        if (-not (Test-PathUnderRoot -Path $baseRoot -Root (Join-Path $RuntimeRoot 'python'))) { return $null }
        if (-not $baseRoot.Equals([IO.Path]::GetFullPath([string]$probe.base_prefix), [StringComparison]::OrdinalIgnoreCase)) { return $null }
        $generationIntegrity = Get-ContentTreeFingerprint -Root $Descriptor.Path -ExcludeRelativePath @('generation.json')
        $baseIntegrity = Get-ContentTreeFingerprint -Root $baseRoot
        foreach ($pair in @(
            @{ Actual = $generationIntegrity; Expected = $manifest.integrity.generation },
            @{ Actual = $baseIntegrity; Expected = $manifest.integrity.python_base }
        )) {
            if ([string]$pair.Actual.sha256 -ne [string]$pair.Expected.sha256 -or
                [long]$pair.Actual.file_count -ne [long]$pair.Expected.file_count -or
                [long]$pair.Actual.total_bytes -ne [long]$pair.Expected.total_bytes) { return $null }
        }
    }
    catch { return $null }
    return [pscustomobject]@{ Descriptor = $Descriptor; Manifest = $manifest; FastPath = $true }
}

function Ensure-Uv {
    $uvPath = [string]$toolchain.uv.executable
    $expectedHash = [string]$toolchain.uv.sha256
    if ((Get-Sha256 -Path $uvPath) -eq $expectedHash) {
        $version = Invoke-CapturedProcess -FilePath $uvPath -Arguments @('--version') -Label 'uv version' -TimeoutSeconds 30
        if ($version.Stdout -match ('^uv ' + [regex]::Escape([string]$toolchain.uv.version) + '\b')) { return $uvPath }
    }
    if ($Offline) { throw 'XINAO_COORD_UV_MISSING_OR_INVALID_OFFLINE' }

    $bootstrap = Join-Path $RuntimeRoot 'bootstrap'
    [void][IO.Directory]::CreateDirectory($bootstrap)
    $installer = Join-Path $bootstrap ('uv-{0}-installer.ps1' -f [string]$toolchain.uv.version)
    if ((Get-Sha256 -Path $installer) -ne [string]$toolchain.uv.installer_sha256) {
        $temp = "$installer.$PID.download"
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 180 -Uri ([string]$toolchain.uv.installer_url) -OutFile $temp
        Assert-ExpectedHash -Path $temp -Expected ([string]$toolchain.uv.installer_sha256)
        Move-Item -LiteralPath $temp -Destination $installer -Force
    }
    $uvDirectory = Split-Path -Parent $uvPath
    [void][IO.Directory]::CreateDirectory($uvDirectory)
    if (Test-Path -LiteralPath $uvPath -PathType Leaf) {
        $quarantine = "$uvPath.invalid-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))"
        Move-Item -LiteralPath $uvPath -Destination $quarantine -Force
    }
    $previousInstallDir = $env:UV_INSTALL_DIR
    $previousNoPath = $env:UV_NO_MODIFY_PATH
    try {
        $env:UV_INSTALL_DIR = $uvDirectory
        $env:UV_NO_MODIFY_PATH = '1'
        Invoke-CapturedProcess -FilePath (Get-Command pwsh.exe -ErrorAction Stop).Source -Arguments @(
            '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $installer
        ) -Label 'uv pinned installer' -TimeoutSeconds 180 | Out-Null
    }
    finally {
        $env:UV_INSTALL_DIR = $previousInstallDir
        $env:UV_NO_MODIFY_PATH = $previousNoPath
    }
    Assert-ExpectedHash -Path $uvPath -Expected $expectedHash
    return $uvPath
}

function New-Generation {
    param(
        [Parameter(Mandatory)][object]$Descriptor,
        [Parameter(Mandatory)][string]$Fingerprint
    )
    $uvPath = Ensure-Uv
    [void][IO.Directory]::CreateDirectory($generationsRoot)
    if (Test-Path -LiteralPath $Descriptor.Path -PathType Container) {
        if (-not (Test-PathUnderRoot -Path $Descriptor.Path -Root $generationsRoot)) {
            throw 'XINAO_COORD_GENERATION_PATH_ESCAPE'
        }
        $quarantine = '{0}.invalid-{1}-{2}' -f $Descriptor.Path, [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'), $PID
        Move-Item -LiteralPath $Descriptor.Path -Destination $quarantine
    }
    [void][IO.Directory]::CreateDirectory($Descriptor.Path)
    $dist = Join-Path $Descriptor.Path 'dist'
    [void][IO.Directory]::CreateDirectory($dist)

    $environmentNames = @(
        'UV_PROJECT_ENVIRONMENT', 'UV_CACHE_DIR', 'UV_PYTHON_INSTALL_DIR', 'UV_BUILD_CONSTRAINT',
        'UV_NO_PROGRESS', 'UV_MANAGED_PYTHON', 'UV_PYTHON_DOWNLOADS', 'UV_LINK_MODE'
    )
    $previous = @{}
    foreach ($name in $environmentNames) {
        $previous[$name] = [pscustomobject]@{ Exists = Test-Path "Env:\$name"; Value = [Environment]::GetEnvironmentVariable($name) }
    }
    try {
        $env:UV_PROJECT_ENVIRONMENT = $Descriptor.Venv
        $env:UV_CACHE_DIR = $uvCacheRoot
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeRoot 'python'
        $env:UV_BUILD_CONSTRAINT = $buildConstraints
        $env:UV_NO_PROGRESS = '1'
        $env:UV_MANAGED_PYTHON = '1'
        $env:UV_PYTHON_DOWNLOADS = if ($Offline) { 'never' } else { 'automatic' }
        $env:UV_LINK_MODE = 'copy'
        [void][IO.Directory]::CreateDirectory($env:UV_CACHE_DIR)
        [void][IO.Directory]::CreateDirectory($env:UV_PYTHON_INSTALL_DIR)

        $syncArgs = @(
            'sync', '--project', $ProjectRoot, '--frozen', '--no-dev', '--no-install-project',
            '--managed-python', '--python', [string]$toolchain.python.request, '--link-mode', 'copy', '--compile-bytecode'
        )
        if ($Offline) { $syncArgs += '--offline' }
        Invoke-CapturedProcessWithRetry -FilePath $uvPath -Arguments $syncArgs -Label 'uv frozen runtime sync' -TimeoutSeconds 900 | Out-Null

        $cachedWheel = Get-CachedProjectWheel -Fingerprint $Fingerprint
        if ($null -ne $cachedWheel) {
            Copy-Item -LiteralPath $cachedWheel -Destination (Join-Path $dist ([IO.Path]::GetFileName($cachedWheel))) -Force
        }
        else {
            $buildArgs = @(
                'build', '--wheel', '--out-dir', $dist, '--python', [string]$toolchain.python.request,
                '--managed-python', '--build-constraints', $buildConstraints, '--require-hashes', $ProjectRoot
            )
            if ($Offline) { $buildArgs += '--offline' }
            Invoke-CapturedProcessWithRetry -FilePath $uvPath -Arguments $buildArgs -Label 'uv hashed project build' -TimeoutSeconds 600 | Out-Null
        }
        $wheels = @(Get-ChildItem -LiteralPath $dist -Filter 'xinao_dual_brain_coordination-*.whl' -File)
        if ($wheels.Count -ne 1) { throw "XINAO_COORD_PROJECT_WHEEL_COUNT_INVALID: $($wheels.Count)" }
        $wheel = $wheels[0]
        if ($null -eq $cachedWheel) { [void](Save-CachedProjectWheel -Fingerprint $Fingerprint -WheelPath $wheel.FullName) }
        Invoke-CapturedProcess -FilePath $uvPath -Arguments @(
            'pip', 'install', '--python', $Descriptor.Python, '--no-deps', '--no-index', '--reinstall', $wheel.FullName
        ) -Label 'uv local wheel install' -TimeoutSeconds 300 | Out-Null
        Invoke-CapturedProcess -FilePath $uvPath -Arguments @(
            'pip', 'check', '--python', $Descriptor.Python
        ) -Label 'uv dependency check' -TimeoutSeconds 120 | Out-Null

        $versions = Get-PythonRuntimeProbe -PythonPath $Descriptor.Python
        if (-not (Test-PythonRuntimeProbe -Probe $versions)) {
            throw "XINAO_COORD_GENERATION_VERSION_MISMATCH: $($versions | ConvertTo-Json -Compress)"
        }
        foreach ($targetPath in @($Descriptor.Python, $Descriptor.Cli, $Descriptor.Mcp)) {
            if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
                throw "XINAO_COORD_GENERATION_TARGET_MISSING: $targetPath"
            }
        }

        $baseRoot = [IO.Path]::GetFullPath([string]$versions.base_prefix)
        if (-not (Test-PathUnderRoot -Path $baseRoot -Root (Join-Path $RuntimeRoot 'python'))) {
            throw "XINAO_COORD_PYTHON_BASE_PATH_ESCAPE: $baseRoot"
        }
        $generationIntegrity = Get-ContentTreeFingerprint -Root $Descriptor.Path -ExcludeRelativePath @('generation.json')
        $baseIntegrity = Get-ContentTreeFingerprint -Root $baseRoot

        $manifest = [ordered]@{
            schema_version = 2
            generation_id = $Descriptor.Id
            source_fingerprint = $Fingerprint
            created_at_utc = [DateTime]::UtcNow.ToString('o')
            project_root = $ProjectRoot
            runtime_root = $RuntimeRoot
            uv = [ordered]@{ version = [string]$toolchain.uv.version; sha256 = Get-Sha256 -Path $uvPath }
            python = [ordered]@{
                request = [string]$toolchain.python.request
                actual = [string]$versions.python
                implementation = [string]$versions.implementation
                platform = [string]$versions.platform
                base_prefix = $baseRoot
            }
            versions = $versions
            wheel = [ordered]@{ name = $wheel.Name; sha256 = Get-Sha256 -Path $wheel.FullName }
            targets = [ordered]@{
                python_sha256 = Get-Sha256 -Path $Descriptor.Python
                cli_sha256 = Get-Sha256 -Path $Descriptor.Cli
                mcp_sha256 = Get-Sha256 -Path $Descriptor.Mcp
            }
            integrity = [ordered]@{
                generation = $generationIntegrity
                python_base = $baseIntegrity
            }
        }
        Write-JsonAtomic -Path $Descriptor.Manifest -Value $manifest
        return $manifest
    }
    catch {
        if (Test-Path -LiteralPath $Descriptor.Path -PathType Container) {
            $failed = '{0}.failed-{1}-{2}' -f $Descriptor.Path, [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'), $PID
            try {
                Move-Item -LiteralPath $Descriptor.Path -Destination $failed
            }
            catch {
                [Console]::Error.WriteLine("XINAO_COORD_FAILED_GENERATION_QUARANTINE_FAILED: $($_.Exception.Message)")
            }
        }
        throw
    }
    finally {
        foreach ($name in $environmentNames) {
            if ($previous[$name].Exists) {
                [Environment]::SetEnvironmentVariable($name, [string]$previous[$name].Value)
            }
            else {
                Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
            }
        }
    }
}

function Set-CurrentGeneration {
    param(
        [Parameter(Mandatory)][object]$Descriptor,
        [Parameter(Mandatory)][string]$Fingerprint
    )
    Write-JsonAtomic -Path $currentPath -Value ([ordered]@{
        schema_version = 1
        generation_id = $Descriptor.Id
        source_fingerprint = $Fingerprint
        generation_path = $Descriptor.Path
        updated_at_utc = [DateTime]::UtcNow.ToString('o')
    })
}

function Test-CurrentGenerationPointer {
    param(
        [Parameter(Mandatory)][object]$Descriptor,
        [Parameter(Mandatory)][string]$Fingerprint
    )
    if (-not (Test-Path -LiteralPath $currentPath -PathType Leaf)) { return $false }
    try { $pointer = Read-JsonFile -Path $currentPath } catch { return $false }
    return [string]$pointer.generation_id -eq $Descriptor.Id -and
        [string]$pointer.source_fingerprint -eq $Fingerprint -and
        [IO.Path]::GetFullPath([string]$pointer.generation_path).Equals($Descriptor.Path, [StringComparison]::OrdinalIgnoreCase)
}

function Ensure-Generation {
    Assert-ProjectInputs
    $fingerprint = Get-SourceFingerprint
    $descriptor = Get-GenerationDescriptor -Fingerprint $fingerprint
    $valid = Get-ValidGeneration -Descriptor $descriptor -Fingerprint $fingerprint
    if ($null -ne $valid -and (Test-CurrentGenerationPointer -Descriptor $descriptor -Fingerprint $fingerprint)) { return $valid }

    return Invoke-WithFileLock -Path $provisionLock -Action {
        $validInside = Get-ValidGeneration -Descriptor $descriptor -Fingerprint $fingerprint
        if ($null -ne $validInside) {
            Set-CurrentGeneration -Descriptor $descriptor -Fingerprint $fingerprint
            return $validInside
        }
        Write-ProvisionEvent -Code 'PROVISION_STARTED' -GenerationId $descriptor.Id
        try {
            $manifest = New-Generation -Descriptor $descriptor -Fingerprint $fingerprint
            Set-CurrentGeneration -Descriptor $descriptor -Fingerprint $fingerprint
            Write-ProvisionEvent -Code 'PROVISION_VERIFIED' -GenerationId $descriptor.Id -Detail ([string]$manifest.wheel.sha256)
            return [pscustomobject]@{ Descriptor = $descriptor; Manifest = $manifest; FastPath = $false }
        }
        catch {
            Write-ProvisionEvent -Code 'PROVISION_FAILED' -GenerationId $descriptor.Id -Detail $_.Exception.Message
            throw
        }
    }
}

[void][IO.Directory]::CreateDirectory($RuntimeRoot)
if ($Target -eq 'status') {
    Assert-ProjectInputs
    $fingerprint = Get-SourceFingerprint
    $descriptor = Get-GenerationDescriptor -Fingerprint $fingerprint
    $valid = Get-ValidGeneration -Descriptor $descriptor -Fingerprint $fingerprint
    [ordered]@{
        status = if ($null -ne $valid) { 'verified' } else { 'missing_or_invalid' }
        source_fingerprint = $fingerprint
        generation_id = $descriptor.Id
        generation_path = $descriptor.Path
        current_pointer = if (Test-Path -LiteralPath $currentPath) { Read-JsonFile -Path $currentPath } else { $null }
        fast_path_ready = $null -ne $valid
    } | ConvertTo-Json -Depth 12
    exit 0
}

$resolvedTarget = Resolve-InvocationTarget -RequestedTarget $Target -RequestedArgs $TargetArgs
$Target = [string]$resolvedTarget.Target
$TargetArgs = @([string[]]$resolvedTarget.TargetArgs)

$generation = Ensure-Generation
if ($Target -eq 'ensure') {
    [ordered]@{
        status = 'verified'
        generation_id = $generation.Descriptor.Id
        generation_path = $generation.Descriptor.Path
        fast_path = [bool]$generation.FastPath
        versions = $generation.Manifest.versions
    } | ConvertTo-Json -Depth 12
    exit 0
}

$targetPath = switch ($Target) {
    'mcp' { $generation.Descriptor.Mcp }
    'cli' { $generation.Descriptor.Cli }
    'python' { $generation.Descriptor.Python }
}
$env:XINAO_COORD_GENERATION_ID = [string]$generation.Descriptor.Id
$env:XINAO_COORD_SOURCE_FINGERPRINT = [string]$generation.Manifest.source_fingerprint
Set-TemporalChildEnvironment -Enabled $TemporalEnabled -Live $TemporalLive -Mock $TemporalMock -Address $TemporalAddress
& $targetPath @TargetArgs
$exitCode = $LASTEXITCODE
if ($null -eq $exitCode) { $exitCode = 0 }
exit $exitCode
