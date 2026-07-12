#Requires -Version 7.2

BeforeAll {
    $script:RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $script:Provisioner = Join-Path $script:RepoRoot 'provisioning\Invoke-XinaoAcpxManaged.ps1'
    $script:Adapter = Join-Path $script:RepoRoot 'adapters\grok\Invoke-XinaoGrokAcp.ps1'
    $script:CanonicalArchive = 'D:\XINAO_RESEARCH_RUNTIME\downloads\node-v24.16.0-win-x64.zip'
    $script:CanonicalNpmCache = 'D:\XINAO_RESEARCH_RUNTIME\cache\acpx\npm'
    $script:SandboxRoot = Join-Path $TestDrive 'acpx-integration'
    $script:SandboxProject = Join-Path $script:SandboxRoot 'project'
    $script:SandboxRuntime = Join-Path $script:SandboxRoot 'runtime'
    $script:SandboxDownloads = Join-Path $script:SandboxRoot 'downloads'
    $script:SandboxProvisioning = Join-Path $script:SandboxProject 'provisioning'
    $script:SandboxLockPath = Join-Path $script:SandboxProvisioning 'acpx-toolchain-lock.json'

    function Invoke-CapturedPwsh {
        param([Parameter(Mandatory)][string[]]$Arguments)
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = (Get-Command pwsh.exe -ErrorAction Stop).Source
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        foreach ($argument in $Arguments) { [void]$start.ArgumentList.Add($argument) }
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $start
        if (-not $process.Start()) { throw 'Pester failed to start pwsh child' }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(120000)) {
            try { $process.Kill($true) } catch { }
            throw 'Pester pwsh child timed out'
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $exitCode = $process.ExitCode
        $process.Dispose()
        return [pscustomobject]@{ ExitCode = $exitCode; Stdout = $stdout; Stderr = $stderr }
    }

    function Invoke-SandboxProvisioner {
        param(
            [ValidateSet('ensure', 'status')][string]$Target = 'ensure',
            [switch]$Offline,
            [switch]$ForceRepair
        )
        $arguments = @(
            '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', $script:Provisioner, '-ProjectRoot', $script:SandboxProject, '-Target', $Target
        )
        if ($Offline) { $arguments += '-Offline' }
        if ($ForceRepair) { $arguments += '-ForceRepair' }
        Invoke-CapturedPwsh -Arguments $arguments
    }

    function Start-SandboxProvisioner {
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = (Get-Command pwsh.exe -ErrorAction Stop).Source
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        foreach ($argument in @(
            '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', $script:Provisioner, '-ProjectRoot', $script:SandboxProject,
            '-Target', 'ensure', '-Offline'
        )) { [void]$start.ArgumentList.Add($argument) }
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $start
        if (-not $process.Start()) { throw 'Pester failed to start concurrent provisioner' }
        return [pscustomobject]@{
            Process = $process
            StdoutTask = $process.StandardOutput.ReadToEndAsync()
            StderrTask = $process.StandardError.ReadToEndAsync()
        }
    }

    function Complete-SandboxProvisioner {
        param([Parameter(Mandatory)][object]$Handle)
        if (-not $Handle.Process.WaitForExit(120000)) {
            try { $Handle.Process.Kill($true) } catch { }
            throw 'Concurrent provisioner timed out'
        }
        $result = [pscustomobject]@{
            ExitCode = $Handle.Process.ExitCode
            Stdout = $Handle.StdoutTask.GetAwaiter().GetResult()
            Stderr = $Handle.StderrTask.GetAwaiter().GetResult()
        }
        $Handle.Process.Dispose()
        return $result
    }

    function Get-TestTree {
        param([Parameter(Mandatory)][string]$Root)
        $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\')
        $rows = [Collections.Generic.List[string]]::new()
        $total = [long]0
        foreach ($file in Get-ChildItem -LiteralPath $rootPath -File -Recurse | Sort-Object FullName) {
            $relative = $file.FullName.Substring($rootPath.Length + 1).Replace('\', '/')
            if ($relative -eq 'generation.json') { continue }
            $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
            $rows.Add(('{0}|{1}|{2}' -f $relative, $file.Length, $hash))
            $total += [long]$file.Length
        }
        $sha = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes(($rows -join "`n")))
        return [pscustomobject]@{
            sha256 = [Convert]::ToHexString($sha)
            file_count = $rows.Count
            total_bytes = $total
        }
    }

    if (-not (Test-Path -LiteralPath $script:CanonicalArchive -PathType Leaf)) {
        throw "Canonical Node archive test fixture is missing: $script:CanonicalArchive"
    }
    if (-not (Test-Path -LiteralPath $script:CanonicalNpmCache -PathType Container)) {
        throw "Canonical npm cache test fixture is missing: $script:CanonicalNpmCache"
    }
    [void][IO.Directory]::CreateDirectory($script:SandboxProvisioning)
    Copy-Item -LiteralPath (Join-Path $script:RepoRoot 'provisioning\acpx-runtime') -Destination $script:SandboxProvisioning -Recurse
    Copy-Item -LiteralPath (Join-Path $script:RepoRoot 'provisioning\acpx-grok-config.json') -Destination $script:SandboxProvisioning
    Copy-Item -LiteralPath (Join-Path $script:RepoRoot 'provisioning\acpx-toolchain-lock.json') -Destination $script:SandboxLockPath
    [void][IO.Directory]::CreateDirectory($script:SandboxDownloads)
    Copy-Item -LiteralPath $script:CanonicalArchive -Destination (
        Join-Path $script:SandboxDownloads 'node-v24.16.0-win-x64.zip'
    )
    $sandboxLock = Get-Content -LiteralPath $script:SandboxLockPath -Raw | ConvertFrom-Json
    $sandboxLock.runtime_root = $script:SandboxRuntime
    $sandboxLock.cache_root = $script:CanonicalNpmCache
    $sandboxLock.download_root = $script:SandboxDownloads
    [IO.File]::WriteAllText(
        $script:SandboxLockPath,
        (($sandboxLock | ConvertTo-Json -Depth 20) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )

    $script:PriorNpmOffline = $env:npm_config_offline
    $env:npm_config_offline = 'true'
    $script:ColdResult = Invoke-SandboxProvisioner
}

AfterAll {
    $env:npm_config_offline = $script:PriorNpmOffline
}

Describe 'Pinned ACPX provisioning integrity' {
    It 'pins the top-level acpx tarball URL and integrity to package-lock' {
        $lock = Get-Content -LiteralPath (
            Join-Path $script:RepoRoot 'provisioning\acpx-toolchain-lock.json'
        ) -Raw | ConvertFrom-Json
        $packageLock = Get-Content -LiteralPath (
            Join-Path $script:RepoRoot 'provisioning\acpx-runtime\package-lock.json'
        ) -Raw | ConvertFrom-Json -AsHashtable
        $acpx = $packageLock['packages']['node_modules/acpx']
        $acpx['version'] | Should -Be $lock.acpx.version
        $acpx['resolved'] | Should -Be $lock.acpx.tarball_url
        $acpx['integrity'] | Should -Be $lock.acpx.tarball_integrity
    }

    It 'cold-provisions from verified local inputs and establishes an external file-index anchor' {
        $script:ColdResult.ExitCode | Should -Be 0 -Because $script:ColdResult.Stderr
        $result = $script:ColdResult.Stdout | ConvertFrom-Json
        $result.status | Should -Be 'verified'
        $result.fast_path | Should -BeFalse
        $result.trust_anchor_path.StartsWith($script:SandboxRuntime, [StringComparison]::OrdinalIgnoreCase) |
            Should -BeTrue
        $result.trust_anchor_path.StartsWith($script:SandboxProject, [StringComparison]::OrdinalIgnoreCase) |
            Should -BeFalse
        $anchor = Get-Content -LiteralPath $result.trust_anchor_path -Raw | ConvertFrom-Json
        @($anchor.files).Count | Should -BeGreaterThan 100
        $anchor.file_index_sha256 | Should -Be $result.payload_tree_sha256
        @(Get-ChildItem -LiteralPath $script:SandboxRuntime -Directory -Filter '.node-stage-*').Count |
            Should -Be 0
    }

    It 'serializes concurrent ensures and atomically repairs a corrupted pointer' {
        [IO.File]::WriteAllText(
            (Join-Path $script:SandboxRuntime 'current.json'),
            "{`"schema_version`":0}`n",
            [Text.UTF8Encoding]::new($false)
        )
        $handles = @(1..4 | ForEach-Object { Start-SandboxProvisioner })
        $results = @($handles | ForEach-Object { Complete-SandboxProvisioner -Handle $_ })
        @($results | Where-Object ExitCode -ne 0).Count | Should -Be 0 -Because (
            ($results | ForEach-Object Stderr) -join [Environment]::NewLine
        )
        $pointer = Get-Content -LiteralPath (Join-Path $script:SandboxRuntime 'current.json') -Raw |
            ConvertFrom-Json
        $pointer.schema_version | Should -Be 3
        Test-Path -LiteralPath $pointer.trust_anchor_path -PathType Leaf | Should -BeTrue
        @(Get-ChildItem -LiteralPath $script:SandboxRuntime -Directory -Filter '.node-stage-*').Count |
            Should -Be 0
    }

    It 'repairs a missing npm.cmd atomically from the verified archive while offline' {
        $lock = Get-Content -LiteralPath $script:SandboxLockPath -Raw | ConvertFrom-Json
        $npm = Join-Path $script:SandboxRuntime ("node-{0}\npm.cmd" -f $lock.node.version)
        Remove-Item -LiteralPath $npm -Force
        $result = Invoke-SandboxProvisioner -Offline
        $result.ExitCode | Should -Be 0 -Because $result.Stderr
        (Get-FileHash -LiteralPath $npm -Algorithm SHA256).Hash | Should -Be $lock.node.npm_cmd_sha256
        @($result.Stdout | ConvertFrom-Json).fast_path | Should -BeTrue
        @(Get-ChildItem -LiteralPath $script:SandboxRuntime -Directory -Filter '.node-stage-*').Count |
            Should -Be 0
    }

    It 'rejects payload plus manifest co-tamper against the external anchor and repairs from cache' {
        $pointer = Get-Content -LiteralPath (Join-Path $script:SandboxRuntime 'current.json') -Raw |
            ConvertFrom-Json
        $anchorHash = (Get-FileHash -LiteralPath $pointer.trust_anchor_path -Algorithm SHA256).Hash
        $cli = $pointer.cli_path
        Add-Content -LiteralPath $cli -Value '// simultaneous payload and manifest tamper' -Encoding utf8
        $manifestPath = Join-Path $pointer.generation_path 'generation.json'
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $tamperedTree = Get-TestTree -Root $pointer.generation_path
        $manifest.cli_sha256 = (Get-FileHash -LiteralPath $cli -Algorithm SHA256).Hash
        $manifest.payload_tree_sha256 = $tamperedTree.sha256
        $manifest.file_index_sha256 = $tamperedTree.sha256
        $manifest.payload_file_count = $tamperedTree.file_count
        $manifest.payload_total_bytes = $tamperedTree.total_bytes
        [IO.File]::WriteAllText(
            $manifestPath,
            (($manifest | ConvertTo-Json -Depth 20) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false)
        )


        $status = Invoke-SandboxProvisioner -Target status
        $status.ExitCode | Should -Be 0 -Because $status.Stderr
        @($status.Stdout | ConvertFrom-Json).status | Should -Be 'repair_required'
        $offline = Invoke-SandboxProvisioner -Offline
        $offline.ExitCode | Should -Not -Be 0
        ($offline.Stdout + $offline.Stderr) | Should -Match 'XINAO_ACPX_GENERATION_MISSING_OFFLINE'

        $repair = Invoke-SandboxProvisioner
        $repair.ExitCode | Should -Be 0 -Because $repair.Stderr
        @($repair.Stdout | ConvertFrom-Json).fast_path | Should -BeFalse
        (Get-FileHash -LiteralPath $pointer.trust_anchor_path -Algorithm SHA256).Hash |
            Should -Be $anchorHash
        @(Invoke-SandboxProvisioner -Target status).Stdout | ConvertFrom-Json |
            Select-Object -ExpandProperty status | Should -Be 'verified'
    }

    It 'cleans node extraction stages even when archive content validation fails' {
        $original = Get-Content -LiteralPath $script:SandboxLockPath -Raw
        try {
            $lock = $original | ConvertFrom-Json
            $lock.node.executable_sha256 = '0' * 64
            [IO.File]::WriteAllText(
                $script:SandboxLockPath,
                (($lock | ConvertTo-Json -Depth 20) + [Environment]::NewLine),
                [Text.UTF8Encoding]::new($false)
            )
            $failed = Invoke-SandboxProvisioner -ForceRepair
            $failed.ExitCode | Should -Not -Be 0
            ($failed.Stdout + $failed.Stderr) | Should -Match 'XINAO_ACPX_NODE_ARCHIVE_CONTENT_MISMATCH'
            @(Get-ChildItem -LiteralPath $script:SandboxRuntime -Directory -Filter '.node-stage-*').Count |
                Should -Be 0
        }
        finally {
            [IO.File]::WriteAllText($script:SandboxLockPath, $original, [Text.UTF8Encoding]::new($false))
        }
    }
}

Describe 'Grok ACP quiet output contract' {
    It 'filters only token and cost metadata while preserving final text and real errors' {
        $fakeRoot = Join-Path $TestDrive 'fake-adapter-project'
        $fakeAdapterDir = Join-Path $fakeRoot 'adapters\grok'
        $fakeProvisioning = Join-Path $fakeRoot 'provisioning'
        [void][IO.Directory]::CreateDirectory($fakeAdapterDir)
        [void][IO.Directory]::CreateDirectory($fakeProvisioning)
        Copy-Item -LiteralPath $script:Adapter -Destination (Join-Path $fakeAdapterDir 'Invoke-XinaoGrokAcp.ps1')
        Copy-Item -LiteralPath (Join-Path $script:RepoRoot 'provisioning\acpx-grok-config.json') -Destination $fakeProvisioning
        $fakeLauncher = @'
param(
    [string]$Target,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Remaining
)
$global:LASTEXITCODE = 0
$countPath = Join-Path $PSScriptRoot '.fake-call-count'
$count = if (Test-Path -LiteralPath $countPath) { [int](Get-Content -LiteralPath $countPath -Raw) } else { 0 }
$count++
[IO.File]::WriteAllText($countPath, [string]$count, [Text.UTF8Encoding]::new($false))
if ($count -ge 2) {
    Write-Output 'FINAL_VISIBLE'
    & $env:ComSpec /d /s /c 'echo [acpx] tokens: input=1 output=2 total=3 1>&2'
    & $env:ComSpec /d /s /c 'echo [acpx] cost: 0.01 USD 1>&2'
    & $env:ComSpec /d /s /c 'echo [acpx] error: real transport warning 1>&2'
    $global:LASTEXITCODE = 0
}
else {
    Write-Output '{"status":"ok"}'
}
'@
        [IO.File]::WriteAllText(
            (Join-Path $fakeProvisioning 'Invoke-XinaoAcpxManaged.ps1'),
            $fakeLauncher,
            [Text.UTF8Encoding]::new($false)
        )
        $grokHome = Join-Path $TestDrive 'fake-grok-home'
        $acpxHome = Join-Path $TestDrive 'fake-acpx-home'
        [void][IO.Directory]::CreateDirectory($grokHome)
        $result = Invoke-CapturedPwsh -Arguments @(
            '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', (Join-Path $fakeAdapterDir 'Invoke-XinaoGrokAcp.ps1'),
            '-Action', 'submit', '-Session', 'pester', '-Prompt', 'hello',
            '-GrokHome', $grokHome, '-AcpxHome', $acpxHome
        )
        $result.ExitCode | Should -Be 0 -Because $result.Stderr
        $result.Stdout | Should -Match 'FINAL_VISIBLE'
        ($result.Stdout + $result.Stderr) | Should -Not -Match '\[acpx\] tokens:'
        ($result.Stdout + $result.Stderr) | Should -Not -Match '\[acpx\] cost:'
        $result.Stderr | Should -Match '\[acpx\] error: real transport warning'
    }
}
