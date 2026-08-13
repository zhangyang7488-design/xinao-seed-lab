#Requires -Version 7.4
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$SourceRepository = 'E:\XINAO_RESEARCH_WORKSPACES\xinao-native-research',
    [Parameter(Mandatory)][string]$StagingPath,
    [string]$ArtifactStorePath = 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-native-research\artifact-store',
    [string[]]$LiveConsumerRoot = @(
        'E:\XINAO_RESEARCH_WORKSPACES\S',
        'C:\Users\xx363\.codex\skills',
        'C:\Users\xx363\CodexLaunchers\Open-Codex-S-Hardmode-DeepSeek-V4Flash.ps1',
        'C:\Users\xx363\AppData\Local\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json'
    ),
    [string[]]$ColdReferenceRoot = @(
        'E:\CODEX_CLEANROOM\workspace\xinao\provenance'
    ),
    [string]$DesktopHandoffPath = 'C:\Users\xx363\Desktop\CURRENT_LOCAL_WORLD_HANDOFF_20260811_141610.zip',
    [string[]]$LegacyBundlePath = @(
        'E:\XINAO_COLD_STORAGE\xinao-global-clean-preimage-20260803-v1\xinao-native-research-preclean.bundle',
        'E:\XINAO_COLD_STORAGE\xinao-native-research-pre-neural-body-20260810.bundle'
    ),
    [ValidateRange(0, 64)][int]$ExpectedLinkedWorktreeCount = 2,
    [string[]]$ExpectedLinkedWorktreePath = @(),
    [ValidateRange(0, 1000000)][int]$MinimumStashCount = 1,
    [ValidateRange(0, 1000000)][int]$MinimumUnreachableObjectCount = 1,
    [bool]$RequireDirtyAgents = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Utf8NoBom = [Text.UTF8Encoding]::new($false)
$AllowedConsumerExtensions = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($extension in @(
    '.bat', '.cfg', '.cmd', '.ini', '.json', '.md', '.ps1', '.py', '.toml', '.txt',
    '.yaml', '.yml'
)) {
    [void]$AllowedConsumerExtensions.Add($extension)
}

function Get-FullPath {
    param([Parameter(Mandatory)][string]$Path)
    return [IO.Path]::GetFullPath($Path).TrimEnd([IO.Path]::DirectorySeparatorChar)
}

function Get-NormalizedRelativePath {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Path
    )
    return [IO.Path]::GetRelativePath($Root, $Path).Replace('\', '/')
}

function Assert-PathInside {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Candidate
    )
    $rootFull = Get-FullPath $Root
    $candidateFull = [IO.Path]::GetFullPath($Candidate)
    $prefix = $rootFull + [IO.Path]::DirectorySeparatorChar
    if (-not $candidateFull.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "RETIREMENT_PACK_PATH_ESCAPE: $candidateFull"
    }
    return $candidateFull
}

function Test-SameOrDescendantPath {
    param(
        [Parameter(Mandatory)][string]$Candidate,
        [Parameter(Mandatory)][string]$Root
    )
    $candidateFull = Get-FullPath $Candidate
    $rootFull = Get-FullPath $Root
    if ($candidateFull.Equals($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $candidateFull.StartsWith(
        $rootFull + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-NoReparseAncestor {
    param([Parameter(Mandatory)][string]$Path)
    $cursor = Get-Item -LiteralPath $Path -Force
    while ($null -ne $cursor) {
        if (($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "RETIREMENT_PACK_STAGING_REPARSE_BLOCKED: $($cursor.FullName)"
        }
        $cursor = $cursor.Parent
    }
}

function Write-JsonFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value,
        [ValidateRange(2, 100)][int]$Depth = 40
    )
    $parent = Split-Path -Parent $Path
    if ($parent) {
        [IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    $json = $Value | ConvertTo-Json -Depth $Depth
    [IO.File]::WriteAllText($Path, $json + "`n", $Utf8NoBom)
}

function Get-Sha256Hex {
    param([Parameter(Mandatory)][string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            return ([Convert]::ToHexString($sha.ComputeHash($stream))).ToLowerInvariant()
        } finally {
            $sha.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

function Get-TextSha256Hex {
    param([Parameter(Mandatory)][string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([Convert]::ToHexString($sha.ComputeHash($Utf8NoBom.GetBytes($Text)))).ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Invoke-NativeText {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$WorkingDirectory = '',
        [switch]$AllowFailure
    )
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $FilePath
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    if ($WorkingDirectory) {
        $psi.WorkingDirectory = $WorkingDirectory
    }
    $psi.Environment['GIT_OPTIONAL_LOCKS'] = '0'
    foreach ($argument in $Arguments) {
        [void]$psi.ArgumentList.Add($argument)
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $psi
    try {
        if (-not $process.Start()) {
            throw "PROCESS_START_FAILED: $FilePath"
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $result = [pscustomobject]@{
            exit_code = $process.ExitCode
            stdout = $stdout
            stderr = $stderr
        }
        if ($process.ExitCode -ne 0 -and -not $AllowFailure) {
            $summary = ($stderr + "`n" + $stdout).Trim()
            throw "PROCESS_FAILED($($process.ExitCode)): $FilePath $($Arguments -join ' ')`n$summary"
        }
        return $result
    } finally {
        $process.Dispose()
    }
}

function Invoke-NativeToFile {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$OutputPath,
        [string]$WorkingDirectory = ''
    )
    $parent = Split-Path -Parent $OutputPath
    if ($parent) {
        [IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $FilePath
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    if ($WorkingDirectory) {
        $psi.WorkingDirectory = $WorkingDirectory
    }
    $psi.Environment['GIT_OPTIONAL_LOCKS'] = '0'
    foreach ($argument in $Arguments) {
        [void]$psi.ArgumentList.Add($argument)
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $psi
    $output = [IO.File]::Open($OutputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        if (-not $process.Start()) {
            throw "PROCESS_START_FAILED: $FilePath"
        }
        $copyTask = $process.StandardOutput.BaseStream.CopyToAsync($output)
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        [void]$copyTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $output.Flush($true)
        if ($process.ExitCode -ne 0) {
            throw "PROCESS_FAILED($($process.ExitCode)): $FilePath $($Arguments -join ' ')`n$stderr"
        }
    } finally {
        $output.Dispose()
        $process.Dispose()
    }
}

function Invoke-Git {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )
    return Invoke-NativeText -FilePath 'git.exe' -Arguments $Arguments -AllowFailure:$AllowFailure
}

function Split-OutputLines {
    param([AllowEmptyString()][string]$Text)
    if ([string]::IsNullOrEmpty($Text)) {
        return @()
    }
    return @($Text -split "\r?\n" | Where-Object { $_ -ne '' })
}

function Get-TreeSnapshot {
    param([Parameter(Mandatory)][string]$Root)
    $rootFull = Get-FullPath $Root
    $items = @(Get-ChildItem -LiteralPath $rootFull -Recurse -Force -ErrorAction Stop)
    $reparse = @($items | Where-Object {
        ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    })
    if ($reparse.Count -gt 0) {
        throw "RETIREMENT_PACK_REPARSE_POINT_BLOCKED: $($reparse[0].FullName)"
    }
    return @(
        $items |
            Where-Object { -not $_.PSIsContainer } |
            Sort-Object FullName |
            ForEach-Object {
                [pscustomobject]@{
                    relative_path = Get-NormalizedRelativePath -Root $rootFull -Path $_.FullName
                    length = [long]$_.Length
                    sha256 = Get-Sha256Hex $_.FullName
                    last_write_utc = $_.LastWriteTimeUtc.ToString('o')
                }
            }
    )
}

function Assert-SnapshotEqual {
    param(
        [Parameter(Mandatory)]$Expected,
        [Parameter(Mandatory)]$Actual,
        [Parameter(Mandatory)][string]$Label
    )
    $expectedMap = @{}
    foreach ($entry in @($Expected)) {
        $expectedMap[[string]$entry.relative_path] = "$($entry.length):$($entry.sha256)"
    }
    $actualMap = @{}
    foreach ($entry in @($Actual)) {
        $actualMap[[string]$entry.relative_path] = "$($entry.length):$($entry.sha256)"
    }
    if ($expectedMap.Count -ne $actualMap.Count) {
        throw "RETIREMENT_PACK_SOURCE_DRIFT: $Label file count $($expectedMap.Count) -> $($actualMap.Count)"
    }
    foreach ($key in $expectedMap.Keys) {
        if (-not $actualMap.ContainsKey($key) -or $actualMap[$key] -ne $expectedMap[$key]) {
            throw "RETIREMENT_PACK_SOURCE_DRIFT: $Label changed at $key"
        }
    }
}

function Copy-SnapshotTree {
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$DestinationRoot,
        [Parameter(Mandatory)]$Snapshot,
        [Parameter(Mandatory)][string]$StagingRoot,
        [Parameter(Mandatory)][string]$Kind
    )
    [IO.Directory]::CreateDirectory((Assert-PathInside -Root $StagingRoot -Candidate $DestinationRoot)) | Out-Null
    $records = @()
    foreach ($entry in @($Snapshot)) {
        $source = Join-Path $SourceRoot ([string]$entry.relative_path).Replace('/', '\')
        $destination = Join-Path $DestinationRoot ([string]$entry.relative_path).Replace('/', '\')
        [void](Assert-PathInside -Root $StagingRoot -Candidate $destination)
        [IO.Directory]::CreateDirectory((Split-Path -Parent $destination)) | Out-Null
        [IO.File]::Copy($source, $destination, $false)
        [IO.File]::SetLastWriteTimeUtc($destination, [datetime]$entry.last_write_utc)
        $copiedHash = Get-Sha256Hex $destination
        if ($copiedHash -ne $entry.sha256 -or (Get-Item -LiteralPath $destination).Length -ne $entry.length) {
            throw "RETIREMENT_PACK_COPY_MISMATCH: $source"
        }
        $records += [pscustomobject]@{
            kind = $Kind
            source_path = $source
            payload_relative_path = Get-NormalizedRelativePath -Root $StagingRoot -Path $destination
            length = [long]$entry.length
            sha256 = [string]$entry.sha256
        }
    }
    return $records
}

function Copy-ExactFile {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$StagingRoot,
        [Parameter(Mandatory)][string]$Kind
    )
    $sourceItem = Get-Item -LiteralPath $Source -Force
    if (($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "RETIREMENT_PACK_SOURCE_REPARSE_BLOCKED: $Source"
    }
    [void](Assert-PathInside -Root $StagingRoot -Candidate $Destination)
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Destination)) | Out-Null
    [IO.File]::Copy($Source, $Destination, $false)
    [IO.File]::SetLastWriteTimeUtc($Destination, (Get-Item -LiteralPath $Source).LastWriteTimeUtc)
    $sourceHash = Get-Sha256Hex $Source
    $destinationHash = Get-Sha256Hex $Destination
    if ($sourceHash -ne $destinationHash) {
        throw "RETIREMENT_PACK_COPY_MISMATCH: $Source"
    }
    return [pscustomobject]@{
        kind = $Kind
        source_path = $Source
        payload_relative_path = Get-NormalizedRelativePath -Root $StagingRoot -Path $Destination
        length = [long](Get-Item -LiteralPath $Destination).Length
        sha256 = $destinationHash
    }
}

function Get-Refs {
    param([Parameter(Mandatory)][string[]]$GitPrefix)
    $result = Invoke-Git ($GitPrefix + @(
        'for-each-ref', '--format=%(refname)%09%(objectname)%09%(objecttype)'
    ))
    return @(
        Split-OutputLines $result.stdout | ForEach-Object {
            $parts = $_ -split "`t", 3
            if ($parts.Count -ne 3) {
                throw "RETIREMENT_PACK_REF_PARSE_FAILED: $_"
            }
            [pscustomobject]@{
                refname = $parts[0]
                object_id = $parts[1]
                object_type = $parts[2]
            }
        }
    )
}

function Assert-RefsEqual {
    param($Expected, $Actual)
    $expectedLines = @($Expected | ForEach-Object { "$($_.refname)`t$($_.object_id)`t$($_.object_type)" })
    $actualLines = @($Actual | ForEach-Object { "$($_.refname)`t$($_.object_id)`t$($_.object_type)" })
    if (($expectedLines -join "`n") -cne ($actualLines -join "`n")) {
        throw 'RETIREMENT_PACK_REF_COPY_DRIFT'
    }
}

function Get-UnreachableObjects {
    param([Parameter(Mandatory)][string[]]$GitPrefix)
    $result = Invoke-Git ($GitPrefix + @('fsck', '--full', '--unreachable')) -AllowFailure
    if ($result.exit_code -ne 0) {
        throw "RETIREMENT_PACK_GIT_FSCK_FAILED: $($result.stderr)"
    }
    $combined = $result.stdout + "`n" + $result.stderr
    return @(
        Split-OutputLines $combined |
            ForEach-Object {
                if ($_ -match '^unreachable\s+(blob|tree|commit|tag)\s+([0-9a-fA-F]+)$') {
                    [pscustomobject]@{
                        object_type = $Matches[1].ToLowerInvariant()
                        object_id = $Matches[2].ToLowerInvariant()
                    }
                }
            } |
            Where-Object { $null -ne $_ } |
            Sort-Object object_type, object_id
    )
}

function Assert-UnreachableEqual {
    param($Expected, $Actual)
    $expectedLines = @($Expected | ForEach-Object { "$($_.object_type) $($_.object_id)" })
    $actualLines = @($Actual | ForEach-Object { "$($_.object_type) $($_.object_id)" })
    if (($expectedLines -join "`n") -cne ($actualLines -join "`n")) {
        throw 'RETIREMENT_PACK_UNREACHABLE_COPY_DRIFT'
    }
}

function Get-StashInventory {
    param(
        [Parameter(Mandatory)][string[]]$GitPrefix,
        [Parameter(Mandatory)][string]$PatchRoot,
        [Parameter(Mandatory)][string]$StagingRoot
    )
    $list = Invoke-Git ($GitPrefix + @(
        'stash', 'list', '--format=%gd%x09%H%x09%P%x09%gs'
    ))
    $entries = @()
    $index = 0
    foreach ($line in Split-OutputLines $list.stdout) {
        $parts = $line -split "`t", 4
        if ($parts.Count -ne 4) {
            throw "RETIREMENT_PACK_STASH_PARSE_FAILED: $line"
        }
        $selector = $parts[0]
        $nameStatusResult = Invoke-Git ($GitPrefix + @(
            'stash', 'show', '--include-untracked', '--name-status', $selector
        ))
        $nameStatus = @(Split-OutputLines $nameStatusResult.stdout)
        $patchPath = Join-Path $PatchRoot ("stash-{0:D3}.patch" -f $index)
        [void](Assert-PathInside -Root $StagingRoot -Candidate $patchPath)
        Invoke-NativeToFile -FilePath 'git.exe' -Arguments (
            $GitPrefix + @('stash', 'show', '--include-untracked', '--binary', '--patch', $selector)
        ) -OutputPath $patchPath
        $entries += [pscustomobject]@{
            selector = $selector
            object_id = $parts[1]
            parents = @($parts[2] -split ' ' | Where-Object { $_ })
            subject = $parts[3]
            name_status = $nameStatus
            patch_relative_path = Get-NormalizedRelativePath -Root $StagingRoot -Path $patchPath
            patch_sha256 = Get-Sha256Hex $patchPath
        }
        $index += 1
    }
    return [pscustomobject]@{
        raw_list = $list.stdout
        entries = $entries
    }
}

function Get-Worktrees {
    param([Parameter(Mandatory)][string]$Repository)
    $result = Invoke-Git @('-C', $Repository, 'worktree', 'list', '--porcelain')
    $blocks = @($result.stdout.Trim() -split "(?:\r?\n){2,}" | Where-Object { $_ })
    $worktrees = @()
    foreach ($block in $blocks) {
        $record = [ordered]@{
            path = $null
            head = $null
            branch = $null
            detached = $false
            prunable = $false
        }
        foreach ($line in Split-OutputLines $block) {
            if ($line -like 'worktree *') { $record.path = $line.Substring(9) }
            elseif ($line -like 'HEAD *') { $record.head = $line.Substring(5) }
            elseif ($line -like 'branch *') { $record.branch = $line.Substring(7) }
            elseif ($line -eq 'detached') { $record.detached = $true }
            elseif ($line -like 'prunable*') { $record.prunable = $true }
        }
        if (-not $record.path -or -not $record.head) {
            throw "RETIREMENT_PACK_WORKTREE_PARSE_FAILED: $block"
        }
        $worktrees += [pscustomobject]$record
    }
    return $worktrees
}

function Get-LinkedWorktreeIdentity {
    param(
        [Parameter(Mandatory)][string]$Repository,
        [Parameter(Mandatory)]$Worktrees
    )
    $repositoryFull = Get-FullPath $Repository
    $linked = @()
    foreach ($worktree in @($Worktrees)) {
        $path = Get-FullPath ([string]$worktree.path)
        if ($path.Equals($repositoryFull, [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            throw "RETIREMENT_PACK_LINKED_WORKTREE_MISSING: $path"
        }
        $gitFile = Join-Path $path '.git'
        if (-not (Test-Path -LiteralPath $gitFile -PathType Leaf)) {
            throw "RETIREMENT_PACK_LINKED_WORKTREE_GITFILE_MISSING: $gitFile"
        }
        $statusResult = Invoke-Git @('-C', $path, 'status', '--porcelain=v2', '--untracked-files=all')
        $statusLines = @(Split-OutputLines $statusResult.stdout)
        if ($statusLines.Count -ne 0) {
            throw "RETIREMENT_PACK_LINKED_WORKTREE_DIRTY: $path"
        }
        $files = @(Get-ChildItem -LiteralPath $path -Recurse -Force -File -ErrorAction Stop)
        $linked += [pscustomobject]@{
            path = $path
            head = [string]$worktree.head
            branch = $worktree.branch
            detached = [bool]$worktree.detached
            prunable = [bool]$worktree.prunable
            clean = $true
            gitfile_text = [IO.File]::ReadAllText($gitFile)
            gitfile_sha256 = Get-Sha256Hex $gitFile
            file_count = $files.Count
            byte_count = [long](($files | Measure-Object Length -Sum).Sum)
        }
    }
    return $linked
}

function Test-ProhibitedRelativePath {
    param([Parameter(Mandatory)][string]$RelativePath)
    $segments = @($RelativePath.Replace('\', '/') -split '/')
    foreach ($segment in $segments) {
        if ($segment -in @(
            '.git', '.pytest_cache', '.ruff_cache', '__pycache__', '.venv', 'node_modules',
            'auth', 'auth.json', 'browser', 'browser-data', 'cookie', 'cookies', 'secret',
            'secrets', 'session', 'sessions', 'temp', 'tmp'
        )) {
            return $true
        }
    }
    return $false
}

function Get-ConsumerMap {
    param(
        [Parameter(Mandatory)][string[]]$LiveRoots,
        [Parameter(Mandatory)][string[]]$ColdRoots,
        [Parameter(Mandatory)][string]$Repository
    )
    if ($LiveRoots.Count -eq 0 -or $ColdRoots.Count -eq 0) {
        throw 'RETIREMENT_PACK_CONSUMER_ROOTS_REQUIRED'
    }
    $patterns = @(
        $Repository,
        $Repository.Replace('\', '/'),
        $Repository.Replace('\', '\\')
    ) | Select-Object -Unique
    $textualMatches = @()
    $excluded = [ordered]@{
        prohibited_path = 0
        unsupported_extension = 0
        reparse_point = 0
    }
    $seen = @{}
    foreach ($group in @(
        [pscustomobject]@{ classification = 'live_or_latent_consumer'; roots = $LiveRoots },
        [pscustomobject]@{ classification = 'cold_textual_reference'; roots = $ColdRoots }
    )) {
        foreach ($rootValue in @($group.roots)) {
            $root = [IO.Path]::GetFullPath($rootValue)
            if (-not (Test-Path -LiteralPath $root)) {
                throw "RETIREMENT_PACK_CONSUMER_ROOT_MISSING: $root"
            }
            $rootItem = Get-Item -LiteralPath $root -Force
            $candidates = if ($rootItem.PSIsContainer) {
                @(Get-ChildItem -LiteralPath $root -Recurse -Force -File -ErrorAction Stop)
            } else {
                @($rootItem)
            }
            foreach ($file in $candidates) {
                $relative = if ($rootItem.PSIsContainer) {
                    Get-NormalizedRelativePath -Root $root -Path $file.FullName
                } else {
                    $file.Name
                }
                if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                    $excluded.reparse_point += 1
                    continue
                }
                if (Test-ProhibitedRelativePath $relative) {
                    $excluded.prohibited_path += 1
                    continue
                }
                if (-not $AllowedConsumerExtensions.Contains($file.Extension)) {
                    $excluded.unsupported_extension += 1
                    continue
                }
                $key = "$($group.classification)|$($file.FullName)"
                if ($seen.ContainsKey($key)) {
                    continue
                }
                $seen[$key] = $true
                $lineNumbers = [Collections.Generic.HashSet[int]]::new()
                foreach ($pattern in $patterns) {
                    foreach ($match in @(Select-String -LiteralPath $file.FullName -SimpleMatch -Pattern $pattern -ErrorAction Stop)) {
                        [void]$lineNumbers.Add([int]$match.LineNumber)
                    }
                }
                if ($lineNumbers.Count -gt 0) {
                    $textualMatches += [pscustomobject]@{
                        classification = $group.classification
                        path = $file.FullName
                        length = [long]$file.Length
                        sha256 = Get-Sha256Hex $file.FullName
                        line_numbers = @($lineNumbers | Sort-Object)
                    }
                }
            }
        }
    }

    $ancestorIds = [Collections.Generic.HashSet[uint32]]::new()
    $cursor = [uint32]$PID
    $allProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $byId = @{}
    foreach ($process in $allProcesses) { $byId[[uint32]$process.ProcessId] = $process }
    while ($cursor -ne 0 -and $ancestorIds.Add($cursor)) {
        if (-not $byId.ContainsKey($cursor)) { break }
        $cursor = [uint32]$byId[$cursor].ParentProcessId
    }
    $processHits = @()
    foreach ($process in $allProcesses) {
        if ($ancestorIds.Contains([uint32]$process.ProcessId)) { continue }
        $commandLine = [string]$process.CommandLine
        if (-not $commandLine) { continue }
        $matched = @($patterns | Where-Object {
            $commandLine.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0
        })
        if ($matched.Count -gt 0) {
            $processHits += [pscustomobject]@{
                process_id = [uint32]$process.ProcessId
                parent_process_id = [uint32]$process.ParentProcessId
                name = [string]$process.Name
                command_line_sha256 = Get-TextSha256Hex $commandLine
                raw_command_line_stored = $false
            }
        }
    }
    return [pscustomobject]@{
        scanned_at = (Get-Date).ToUniversalTime().ToString('o')
        repository_patterns = $patterns
        textual_matches = $textualMatches
        process_command_line_hits = $processHits
        process_cwd_scan = 'not_available_in_this_generator'
        excluded_counts = [pscustomobject]$excluded
        raw_consumer_bytes_copied = $false
        raw_process_command_lines_stored = $false
    }
}

function Get-LegacyBundleCoverage {
    param(
        [Parameter(Mandatory)][string[]]$Paths,
        [Parameter(Mandatory)][string]$Repository,
        [Parameter(Mandatory)][string]$SourceHead,
        [Parameter(Mandatory)]$SourceRefs
    )
    $coverage = @()
    foreach ($pathValue in $Paths) {
        $path = [IO.Path]::GetFullPath($pathValue)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $coverage += [pscustomobject]@{
                path = $path
                status = 'missing'
                verified = $false
                sha256 = $null
                length = $null
                heads = @()
                lists_current_head = $false
                covers_current_named_ref_tips = $false
            }
            continue
        }
        $verify = Invoke-Git @('-C', $Repository, 'bundle', 'verify', $path) -AllowFailure
        if ($verify.exit_code -ne 0) {
            throw "RETIREMENT_PACK_LEGACY_BUNDLE_INVALID: $path"
        }
        $headsResult = Invoke-Git @('bundle', 'list-heads', $path)
        $heads = @(Split-OutputLines $headsResult.stdout)
        $headObjectIds = @($heads | ForEach-Object { ($_ -split ' ', 2)[0] })
        $listedRefs = @{}
        foreach ($headLine in $heads) {
            $parts = $headLine -split ' ', 2
            if ($parts.Count -eq 2) { $listedRefs[$parts[1]] = $parts[0] }
        }
        $coversNamedRefTips = $true
        foreach ($sourceRef in @($SourceRefs)) {
            if (-not $listedRefs.ContainsKey($sourceRef.refname) -or
                $listedRefs[$sourceRef.refname] -cne $sourceRef.object_id) {
                $coversNamedRefTips = $false
                break
            }
        }
        $coverage += [pscustomobject]@{
            path = $path
            status = 'present_verified'
            verified = $true
            sha256 = Get-Sha256Hex $path
            length = [long](Get-Item -LiteralPath $path).Length
            heads = $heads
            lists_current_head = $headObjectIds -contains $SourceHead
            covers_current_named_ref_tips = $coversNamedRefTips
        }
    }
    return $coverage
}

function Assert-LocalGitConfigHasNoEmbeddedSecret {
    param([Parameter(Mandatory)][string]$Repository)
    $result = Invoke-Git @('-C', $Repository, 'config', '--local', '--list')
    foreach ($line in Split-OutputLines $result.stdout) {
        $parts = $line -split '=', 2
        $key = $parts[0]
        $value = if ($parts.Count -eq 2) { $parts[1] } else { '' }
        if ($key -match '(?i)(credential|password|token|secret|cookie|auth)') {
            throw "RETIREMENT_PACK_SENSITIVE_GIT_CONFIG_KEY: $key"
        }
        if ($key -match '(?i)(extraheader|askpass)') {
            throw "RETIREMENT_PACK_SENSITIVE_GIT_CONFIG_KEY: $key"
        }
        if ($value -match '(?i)\b(authorization|bearer)\b') {
            throw "RETIREMENT_PACK_SENSITIVE_GIT_CONFIG_VALUE: $key"
        }
        if ($value -match '(?i)://[^/@\s]+@') {
            throw "RETIREMENT_PACK_EMBEDDED_CREDENTIAL_URL: $key"
        }
    }
}

function Assert-GitDirectoryHasNoSensitiveCarrier {
    param([Parameter(Mandatory)][string]$GitDirectory)
    foreach ($file in Get-ChildItem -LiteralPath $GitDirectory -Recurse -Force -File) {
        $relative = Get-NormalizedRelativePath -Root $GitDirectory -Path $file.FullName
        $segments = @($relative -split '/')
        foreach ($segment in $segments) {
            if ($segment -match '(?i)^(auth|auth\.json|browser|browser-data|cookie|cookies|credential|credentials|secret|secrets|session|sessions|temp|tmp)$') {
                throw "RETIREMENT_PACK_SENSITIVE_GIT_CARRIER: $relative"
            }
        }
        if ($relative -like 'hooks/*' -and $file.Name -notlike '*.sample') {
            throw "RETIREMENT_PACK_CUSTOM_GIT_HOOK_BLOCKED: $relative"
        }
    }
}

function Assert-NoSensitiveJsonValue {
    param(
        [Parameter(Mandatory)][AllowNull()]$Value,
        [Parameter(Mandatory)][string]$SourcePath,
        [string]$JsonPath = '$'
    )
    if ($null -eq $Value) { return }
    if ($Value -is [string]) {
        if ($Value -match '(?i)\b(authorization\s*[:=]?\s*(bearer|basic)|bearer\s+[a-z0-9._~-]{12,}|sk-[a-z0-9_-]{16,})') {
            throw "RETIREMENT_PACK_SENSITIVE_JSON_VALUE: $SourcePath $JsonPath"
        }
        return
    }
    if ($Value -is [ValueType]) { return }
    $sensitiveKeyPattern = '(?i)^(api_key|auth|authentication|authorization|cookie|cookies|credential|credentials|password|passwords|refresh_token|secret|secrets|session|sessions|token|tokens|access_token)$'
    if ($Value -is [Collections.IDictionary]) {
        foreach ($key in $Value.Keys) {
            if ([string]$key -match $sensitiveKeyPattern) {
                throw "RETIREMENT_PACK_SENSITIVE_JSON_KEY: $SourcePath $JsonPath.$key"
            }
            Assert-NoSensitiveJsonValue -Value $Value[$key] -SourcePath $SourcePath -JsonPath "$JsonPath.$key"
        }
        return
    }
    if ($Value -is [Collections.IEnumerable] -and $Value -isnot [string]) {
        $index = 0
        foreach ($item in $Value) {
            Assert-NoSensitiveJsonValue -Value $item -SourcePath $SourcePath -JsonPath "$JsonPath[$index]"
            $index += 1
        }
        return
    }
    foreach ($property in @($Value.PSObject.Properties)) {
        if ($property.Name -match $sensitiveKeyPattern) {
            throw "RETIREMENT_PACK_SENSITIVE_JSON_KEY: $SourcePath $JsonPath.$($property.Name)"
        }
        Assert-NoSensitiveJsonValue `
            -Value $property.Value `
            -SourcePath $SourcePath `
            -JsonPath "$JsonPath.$($property.Name)"
    }
}

$sourceRepositoryFull = Get-FullPath $SourceRepository
$stagingFull = Get-FullPath $StagingPath
$artifactStoreFull = Get-FullPath $ArtifactStorePath

if (-not (Test-Path -LiteralPath $sourceRepositoryFull -PathType Container)) {
    throw "RETIREMENT_PACK_SOURCE_REPOSITORY_MISSING: $sourceRepositoryFull"
}
if (-not (Test-Path -LiteralPath $artifactStoreFull -PathType Container)) {
    throw "RETIREMENT_PACK_ARTIFACT_STORE_MISSING: $artifactStoreFull"
}
if (-not (Test-Path -LiteralPath $stagingFull -PathType Container)) {
    throw "RETIREMENT_PACK_EMPTY_STAGING_REQUIRED: $stagingFull"
}
$stagingChildren = @(Get-ChildItem -LiteralPath $stagingFull -Force -ErrorAction Stop)
if ($stagingChildren.Count -ne 0) {
    throw "RETIREMENT_PACK_STAGING_NOT_EMPTY: $stagingFull"
}
Assert-NoReparseAncestor $stagingFull

$preflightWorktrees = @(Get-Worktrees $sourceRepositoryFull)
$protectedDirectories = @($sourceRepositoryFull, $artifactStoreFull)
$protectedDirectories += @($preflightWorktrees | ForEach-Object { [string]$_.path })
foreach ($consumerRoot in @($LiveConsumerRoot) + @($ColdReferenceRoot)) {
    if (Test-Path -LiteralPath $consumerRoot -PathType Container) {
        $protectedDirectories += [IO.Path]::GetFullPath($consumerRoot)
    }
}
foreach ($protectedDirectory in $protectedDirectories | Select-Object -Unique) {
    if ((Test-SameOrDescendantPath -Candidate $stagingFull -Root $protectedDirectory) -or
        (Test-SameOrDescendantPath -Candidate $protectedDirectory -Root $stagingFull)) {
        throw "RETIREMENT_PACK_STAGING_OVERLAPS_SOURCE: $protectedDirectory"
    }
}

$incompletePath = Join-Path $stagingFull '_INCOMPLETE.json'
Write-JsonFile -Path $incompletePath -Value ([ordered]@{
    schema_version = 'xinao.native-cold-retirement-build-status.v1'
    status = 'incomplete'
    started_at = (Get-Date).ToUniversalTime().ToString('o')
    source_repository = $sourceRepositoryFull
    source_deleted = $false
})

try {
    $topLevel = (Invoke-Git @('-C', $sourceRepositoryFull, 'rev-parse', '--show-toplevel')).stdout.Trim()
    if (-not (Get-FullPath $topLevel).Equals($sourceRepositoryFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "RETIREMENT_PACK_NOT_REPOSITORY_ROOT: $sourceRepositoryFull"
    }
    Assert-LocalGitConfigHasNoEmbeddedSecret $sourceRepositoryFull

    $gitDirectory = Join-Path $sourceRepositoryFull '.git'
    if (-not (Test-Path -LiteralPath $gitDirectory -PathType Container)) {
        throw "RETIREMENT_PACK_SEPARATE_GITDIR_UNSUPPORTED: $gitDirectory"
    }
    Assert-GitDirectoryHasNoSensitiveCarrier $gitDirectory

    $head = (Invoke-Git @('-C', $sourceRepositoryFull, 'rev-parse', 'HEAD')).stdout.Trim()
    $branch = (Invoke-Git @('-C', $sourceRepositoryFull, 'branch', '--show-current')).stdout.Trim()
    $objectFormat = (Invoke-Git @('-C', $sourceRepositoryFull, 'rev-parse', '--show-object-format')).stdout.Trim()
    $isShallow = (Invoke-Git @('-C', $sourceRepositoryFull, 'rev-parse', '--is-shallow-repository')).stdout.Trim()
    if ($isShallow -ne 'false') {
        throw 'RETIREMENT_PACK_SHALLOW_REPOSITORY_BLOCKED'
    }

    $statusBefore = (Invoke-Git @(
        '-C', $sourceRepositoryFull, 'status', '--porcelain=v2', '--untracked-files=all'
    )).stdout
    $trackedChanged = @(Split-OutputLines (
        Invoke-Git @('-C', $sourceRepositoryFull, 'diff', '--name-only', 'HEAD', '--')
    ).stdout)
    $untracked = @(Split-OutputLines (
        Invoke-Git @('-C', $sourceRepositoryFull, 'ls-files', '--others', '--exclude-standard')
    ).stdout)
    if ($untracked.Count -ne 0) {
        throw "RETIREMENT_PACK_UNTRACKED_NOT_CAPTURED: $($untracked[0])"
    }
    $unexpectedTracked = @($trackedChanged | Where-Object { $_ -cne 'AGENTS.md' })
    if ($unexpectedTracked.Count -ne 0) {
        throw "RETIREMENT_PACK_DIRTY_PATH_NOT_CAPTURED: $($unexpectedTracked[0])"
    }
    $agentsDirty = $trackedChanged -contains 'AGENTS.md'
    if ($RequireDirtyAgents -and -not $agentsDirty) {
        throw 'RETIREMENT_PACK_EXPECTED_DIRTY_AGENTS_MISSING'
    }
    $agentsSource = Join-Path $sourceRepositoryFull 'AGENTS.md'
    if (-not (Test-Path -LiteralPath $agentsSource -PathType Leaf)) {
        throw "RETIREMENT_PACK_AGENTS_MISSING: $agentsSource"
    }

    $ignored = @(Split-OutputLines (
        Invoke-Git @(
            '-C', $sourceRepositoryFull, 'ls-files', '--others', '--ignored', '--exclude-standard'
        )
    ).stdout)
    $cacheEntries = @()
    foreach ($path in $ignored) {
        $classification = if ($path -match '(^|/)__pycache__/') { '__pycache__' }
            elseif ($path -match '(^|/)\.pytest_cache/') { '.pytest_cache' }
            elseif ($path -match '(^|/)\.ruff_cache/') { '.ruff_cache' }
            else { $null }
        if (-not $classification) {
            throw "RETIREMENT_PACK_NONCACHE_IGNORED_PATH_NOT_CAPTURED: $path"
        }
        $cacheEntries += [pscustomobject]@{
            path = $path
            classification = $classification
            disposition = 'excluded_derived_cache'
        }
    }

    $refsBefore = @(Get-Refs @('-C', $sourceRepositoryFull))
    $unreachableBefore = @(Get-UnreachableObjects @('-C', $sourceRepositoryFull))
    if ($unreachableBefore.Count -lt $MinimumUnreachableObjectCount) {
        throw "RETIREMENT_PACK_UNREACHABLE_MINIMUM_NOT_MET: $($unreachableBefore.Count)"
    }
    $worktreesBefore = @(Get-Worktrees $sourceRepositoryFull)
    $linkedBefore = @(Get-LinkedWorktreeIdentity -Repository $sourceRepositoryFull -Worktrees $worktreesBefore)
    if ($linkedBefore.Count -ne $ExpectedLinkedWorktreeCount) {
        throw "RETIREMENT_PACK_LINKED_WORKTREE_COUNT: expected=$ExpectedLinkedWorktreeCount actual=$($linkedBefore.Count)"
    }
    if ($ExpectedLinkedWorktreePath.Count -gt 0) {
        $expectedPaths = @($ExpectedLinkedWorktreePath | ForEach-Object { Get-FullPath $_ } | Sort-Object)
        $actualPaths = @($linkedBefore.path | Sort-Object)
        if (($expectedPaths -join "`n") -cne ($actualPaths -join "`n")) {
            throw 'RETIREMENT_PACK_LINKED_WORKTREE_PATH_MISMATCH'
        }
    }

    $gitSnapshotBefore = Get-TreeSnapshot $gitDirectory
    $agentsBefore = [pscustomobject]@{
        length = [long](Get-Item -LiteralPath $agentsSource).Length
        sha256 = Get-Sha256Hex $agentsSource
    }

    $payloadRoot = Join-Path $stagingFull 'payload'
    $evidenceRoot = Join-Path $stagingFull 'evidence'
    [IO.Directory]::CreateDirectory($payloadRoot) | Out-Null
    [IO.Directory]::CreateDirectory($evidenceRoot) | Out-Null
    $sourceCopies = @()

    $copiedGitDirectory = Join-Path $payloadRoot 'git-exact\.git'
    $sourceCopies += Copy-SnapshotTree `
        -SourceRoot $gitDirectory `
        -DestinationRoot $copiedGitDirectory `
        -Snapshot $gitSnapshotBefore `
        -StagingRoot $stagingFull `
        -Kind 'exact_git_supplemental'

    $agentsCurrent = Join-Path $payloadRoot 'working-tree\AGENTS.current.md'
    $sourceCopies += Copy-ExactFile `
        -Source $agentsSource `
        -Destination $agentsCurrent `
        -StagingRoot $stagingFull `
        -Kind 'dirty_agents_current_bytes'

    $agentsBlob = (Invoke-Git @(
        '-C', $sourceRepositoryFull, 'rev-parse', 'HEAD:AGENTS.md'
    )).stdout.Trim()
    $agentsBase = Join-Path $payloadRoot 'working-tree\AGENTS.base.md'
    Invoke-NativeToFile -FilePath 'git.exe' -Arguments @(
        '--git-dir', $copiedGitDirectory, 'cat-file', 'blob', $agentsBlob
    ) -OutputPath $agentsBase
    $agentsDiff = Join-Path $payloadRoot 'working-tree\AGENTS.diff'
    Invoke-NativeToFile -FilePath 'git.exe' -Arguments @(
        '-C', $sourceRepositoryFull, 'diff', '--binary', 'HEAD', '--', 'AGENTS.md'
    ) -OutputPath $agentsDiff

    $journalRoot = Join-Path $artifactStoreFull 'journals'
    if (-not (Test-Path -LiteralPath $journalRoot -PathType Container)) {
        throw "RETIREMENT_PACK_ARTIFACT_JOURNAL_ROOT_MISSING: $journalRoot"
    }
    $journalFiles = @(Get-ChildItem -LiteralPath $journalRoot -Recurse -Force -File -Filter '*.jsonl')
    if ($journalFiles.Count -eq 0) {
        throw 'RETIREMENT_PACK_ARTIFACT_JOURNAL_MISSING'
    }
    $artifactSourceBaseline = @()
    $casIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($journal in $journalFiles) {
        $relative = Get-NormalizedRelativePath -Root $artifactStoreFull -Path $journal.FullName
        if (Test-ProhibitedRelativePath $relative) {
            throw "RETIREMENT_PACK_PROHIBITED_ARTIFACT_PATH: $relative"
        }
        $destination = Join-Path $payloadRoot ('artifact-store\' + $relative.Replace('/', '\'))
        $record = Copy-ExactFile `
            -Source $journal.FullName `
            -Destination $destination `
            -StagingRoot $stagingFull `
            -Kind 'artifact_journal'
        $sourceCopies += $record
        $artifactSourceBaseline += [pscustomobject]@{
            path = $journal.FullName
            length = $record.length
            sha256 = $record.sha256
        }
        foreach ($line in [IO.File]::ReadLines($destination)) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            try { $journalEvent = $line | ConvertFrom-Json -Depth 50 }
            catch { throw "RETIREMENT_PACK_ARTIFACT_JOURNAL_INVALID_JSON: $($journal.FullName)" }
            Assert-NoSensitiveJsonValue -Value $journalEvent -SourcePath $journal.FullName
            $cas = [string]$journalEvent.payload.cas_sha256
            if ($cas -notmatch '^[0-9a-fA-F]{64}$') {
                throw "RETIREMENT_PACK_ARTIFACT_CAS_ID_INVALID: $cas"
            }
            [void]$casIds.Add($cas.ToLowerInvariant())
        }
    }
    foreach ($cas in @($casIds | Sort-Object)) {
        $casPath = Join-Path $artifactStoreFull (
            "objects\sha256\$($cas.Substring(0, 2))\$cas.json"
        )
        if (-not (Test-Path -LiteralPath $casPath -PathType Leaf)) {
            throw "RETIREMENT_PACK_ARTIFACT_CAS_MISSING: $casPath"
        }
        try { $casJson = [IO.File]::ReadAllText($casPath) | ConvertFrom-Json -Depth 100 }
        catch { throw "RETIREMENT_PACK_ARTIFACT_CAS_INVALID_JSON: $casPath" }
        Assert-NoSensitiveJsonValue -Value $casJson -SourcePath $casPath
        $relative = Get-NormalizedRelativePath -Root $artifactStoreFull -Path $casPath
        $destination = Join-Path $payloadRoot ('artifact-store\' + $relative.Replace('/', '\'))
        $record = Copy-ExactFile `
            -Source $casPath `
            -Destination $destination `
            -StagingRoot $stagingFull `
            -Kind 'artifact_cas_object'
        $sourceCopies += $record
        $artifactSourceBaseline += [pscustomobject]@{
            path = $casPath
            length = $record.length
            sha256 = $record.sha256
        }
    }

    $gitSnapshotAfterCopy = Get-TreeSnapshot $gitDirectory
    Assert-SnapshotEqual $gitSnapshotBefore $gitSnapshotAfterCopy 'source .git during copy'

    $refsCopied = @(Get-Refs @('--git-dir', $copiedGitDirectory))
    Assert-RefsEqual $refsBefore $refsCopied
    $unreachableCopied = @(Get-UnreachableObjects @('--git-dir', $copiedGitDirectory))
    Assert-UnreachableEqual $unreachableBefore $unreachableCopied
    foreach ($object in $unreachableCopied) {
        $exists = Invoke-Git @(
            '--git-dir', $copiedGitDirectory, 'cat-file', '-e', "$($object.object_id)^{object}"
        ) -AllowFailure
        if ($exists.exit_code -ne 0) {
            throw "RETIREMENT_PACK_UNREACHABLE_OBJECT_MISSING_FROM_COPY: $($object.object_id)"
        }
    }

    $bundlePath = Join-Path $payloadRoot 'git-bundle\xinao-native-research.bundle'
    [IO.Directory]::CreateDirectory((Split-Path -Parent $bundlePath)) | Out-Null
    $bundleCreate = Invoke-Git @(
        '--git-dir', $copiedGitDirectory, 'bundle', 'create', $bundlePath, '--all'
    ) -AllowFailure
    if ($bundleCreate.exit_code -ne 0 -or -not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) {
        throw "RETIREMENT_PACK_BUNDLE_CREATE_FAILED: $($bundleCreate.stderr)"
    }
    $bundleVerify = Invoke-Git @(
        '--git-dir', $copiedGitDirectory, 'bundle', 'verify', $bundlePath
    ) -AllowFailure
    if ($bundleVerify.exit_code -ne 0) {
        throw "RETIREMENT_PACK_BUNDLE_VERIFY_FAILED: $($bundleVerify.stderr)"
    }
    $bundleHeadsResult = Invoke-Git @('bundle', 'list-heads', $bundlePath)
    $bundleHeads = @(Split-OutputLines $bundleHeadsResult.stdout)
    $bundleHeadMap = @{}
    foreach ($line in $bundleHeads) {
        $parts = $line -split ' ', 2
        if ($parts.Count -eq 2) { $bundleHeadMap[$parts[1]] = $parts[0] }
    }
    foreach ($ref in $refsBefore) {
        if (-not $bundleHeadMap.ContainsKey($ref.refname) -or
            $bundleHeadMap[$ref.refname] -cne $ref.object_id) {
            throw "RETIREMENT_PACK_BUNDLE_MISSING_NAMED_REF: $($ref.refname)"
        }
    }

    $stashPatchRoot = Join-Path $payloadRoot 'stash-patches'
    [IO.Directory]::CreateDirectory($stashPatchRoot) | Out-Null
    $stashSource = Get-StashInventory `
        -GitPrefix @('-C', $sourceRepositoryFull) `
        -PatchRoot (Join-Path $evidenceRoot '_source-stash-probe') `
        -StagingRoot $stagingFull
    $stashCopied = Get-StashInventory `
        -GitPrefix @('--git-dir', $copiedGitDirectory) `
        -PatchRoot $stashPatchRoot `
        -StagingRoot $stagingFull
    if ($stashSource.entries.Count -lt $MinimumStashCount) {
        throw "RETIREMENT_PACK_STASH_MINIMUM_NOT_MET: $($stashSource.entries.Count)"
    }
    if ($stashSource.raw_list -cne $stashCopied.raw_list) {
        throw 'RETIREMENT_PACK_STASH_COPY_DRIFT'
    }
    [IO.Directory]::Delete((Join-Path $evidenceRoot '_source-stash-probe'), $true)

    $consumerMap = Get-ConsumerMap `
        -LiveRoots $LiveConsumerRoot `
        -ColdRoots $ColdReferenceRoot `
        -Repository $sourceRepositoryFull

    $desktopHandoffFull = [IO.Path]::GetFullPath($DesktopHandoffPath)
    $desktopHandoff = if (Test-Path -LiteralPath $desktopHandoffFull -PathType Leaf) {
        [pscustomobject]@{
            path = $desktopHandoffFull
            status = 'present_hash_only_not_copied'
            length = [long](Get-Item -LiteralPath $desktopHandoffFull).Length
            sha256 = Get-Sha256Hex $desktopHandoffFull
        }
    } else {
        [pscustomobject]@{
            path = $desktopHandoffFull
            status = 'missing'
            length = $null
            sha256 = $null
        }
    }
    $legacyCoverage = @(Get-LegacyBundleCoverage `
        -Paths $LegacyBundlePath `
        -Repository $sourceRepositoryFull `
        -SourceHead $head `
        -SourceRefs $refsBefore)

    $evidence = [ordered]@{
        git = [ordered]@{
            repository = $sourceRepositoryFull
            head = $head
            branch = $branch
            object_format = $objectFormat
            shallow = $false
            status_porcelain_v2 = @(Split-OutputLines $statusBefore)
            refs = $refsBefore
            named_ref_bundle = [ordered]@{
                relative_path = Get-NormalizedRelativePath -Root $stagingFull -Path $bundlePath
                sha256 = Get-Sha256Hex $bundlePath
                verified = $true
                heads = $bundleHeads
            }
            exact_git_supplemental = [ordered]@{
                relative_path = Get-NormalizedRelativePath -Root $stagingFull -Path $copiedGitDirectory
                file_count = $gitSnapshotBefore.Count
                includes = @('objects', 'refs', 'logs/reflogs', 'index', 'worktrees admin', 'config')
                source_copy_hash_match = $true
            }
            unreachable_objects = $unreachableCopied
        }
        dirty_agents = [ordered]@{
            dirty = $agentsDirty
            current_relative_path = Get-NormalizedRelativePath -Root $stagingFull -Path $agentsCurrent
            current_sha256 = Get-Sha256Hex $agentsCurrent
            base_blob = $agentsBlob
            base_relative_path = Get-NormalizedRelativePath -Root $stagingFull -Path $agentsBase
            base_sha256 = Get-Sha256Hex $agentsBase
            diff_relative_path = Get-NormalizedRelativePath -Root $stagingFull -Path $agentsDiff
            diff_sha256 = Get-Sha256Hex $agentsDiff
        }
        stash = $stashCopied.entries
        artifact_store = [ordered]@{
            source_root = $artifactStoreFull
            journal_count = $journalFiles.Count
            cas_ids = @($casIds | Sort-Object)
            lock_files_copied = $false
        }
        linked_worktrees = $linkedBefore
        consumers = $consumerMap
        cache_exclusions = $cacheEntries
        desktop_handoff = $desktopHandoff
        legacy_bundles = $legacyCoverage
        prohibited_carriers = @('auth', 'session', 'browser', 'tmp', 'secret')
    }
    Write-JsonFile -Path (Join-Path $evidenceRoot 'retirement-evidence.json') -Value $evidence

    $gitSnapshotFinal = Get-TreeSnapshot $gitDirectory
    Assert-SnapshotEqual $gitSnapshotBefore $gitSnapshotFinal 'source .git final readback'
    $copiedGitSnapshotFinal = Get-TreeSnapshot $copiedGitDirectory
    Assert-SnapshotEqual $gitSnapshotBefore $copiedGitSnapshotFinal 'copied exact .git final readback'
    $agentsFinal = [pscustomobject]@{
        length = [long](Get-Item -LiteralPath $agentsSource).Length
        sha256 = Get-Sha256Hex $agentsSource
    }
    if ($agentsFinal.length -ne $agentsBefore.length -or $agentsFinal.sha256 -ne $agentsBefore.sha256) {
        throw 'RETIREMENT_PACK_SOURCE_DRIFT: AGENTS.md final readback'
    }
    $statusFinal = (Invoke-Git @(
        '-C', $sourceRepositoryFull, 'status', '--porcelain=v2', '--untracked-files=all'
    )).stdout
    if ($statusFinal -cne $statusBefore) {
        throw 'RETIREMENT_PACK_SOURCE_DRIFT: worktree status final readback'
    }
    $refsFinal = @(Get-Refs @('-C', $sourceRepositoryFull))
    Assert-RefsEqual $refsBefore $refsFinal
    $unreachableFinal = @(Get-UnreachableObjects @('-C', $sourceRepositoryFull))
    Assert-UnreachableEqual $unreachableBefore $unreachableFinal
    $linkedFinal = @(Get-LinkedWorktreeIdentity `
        -Repository $sourceRepositoryFull `
        -Worktrees @(Get-Worktrees $sourceRepositoryFull))
    if (($linkedBefore | ConvertTo-Json -Depth 20 -Compress) -cne
        ($linkedFinal | ConvertTo-Json -Depth 20 -Compress)) {
        throw 'RETIREMENT_PACK_SOURCE_DRIFT: linked worktrees final readback'
    }
    foreach ($artifact in $artifactSourceBaseline) {
        if (-not (Test-Path -LiteralPath $artifact.path -PathType Leaf) -or
            (Get-Item -LiteralPath $artifact.path).Length -ne $artifact.length -or
            (Get-Sha256Hex $artifact.path) -ne $artifact.sha256) {
            throw "RETIREMENT_PACK_SOURCE_DRIFT: artifact $($artifact.path)"
        }
    }
    foreach ($consumer in $consumerMap.textual_matches) {
        if (-not (Test-Path -LiteralPath $consumer.path -PathType Leaf) -or
            (Get-Item -LiteralPath $consumer.path).Length -ne $consumer.length -or
            (Get-Sha256Hex $consumer.path) -ne $consumer.sha256) {
            throw "RETIREMENT_PACK_SOURCE_DRIFT: consumer $($consumer.path)"
        }
    }
    if ($desktopHandoff.status -ne 'missing' -and
        (Get-Sha256Hex $desktopHandoff.path) -ne $desktopHandoff.sha256) {
        throw 'RETIREMENT_PACK_SOURCE_DRIFT: desktop handoff'
    }
    foreach ($legacy in $legacyCoverage | Where-Object { $_.verified }) {
        if ((Get-Sha256Hex $legacy.path) -ne $legacy.sha256) {
            throw "RETIREMENT_PACK_SOURCE_DRIFT: legacy bundle $($legacy.path)"
        }
    }

    $preManifestFiles = @(
        Get-ChildItem -LiteralPath $stagingFull -Recurse -Force -File |
            Where-Object { $_.FullName -ne $incompletePath } |
            Sort-Object FullName |
            ForEach-Object {
                [pscustomobject]@{
                    relative_path = Get-NormalizedRelativePath -Root $stagingFull -Path $_.FullName
                    length = [long]$_.Length
                    sha256 = Get-Sha256Hex $_.FullName
                }
            }
    )
    foreach ($payloadFile in $preManifestFiles) {
        $path = Join-Path $stagingFull $payloadFile.relative_path.Replace('/', '\')
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-Item -LiteralPath $path).Length -ne $payloadFile.length -or
            (Get-Sha256Hex $path) -ne $payloadFile.sha256) {
            throw "RETIREMENT_PACK_PAYLOAD_READBACK_FAILED: $($payloadFile.relative_path)"
        }
    }

    $manifest = [ordered]@{
        schema_version = 'xinao.native-cold-retirement-pack.v1'
        status = 'payload_verified'
        created_at = (Get-Date).ToUniversalTime().ToString('o')
        source_repository = $sourceRepositoryFull
        source_head = $head
        source_branch = $branch
        source_deleted = $false
        source_mutated = $false
        payload_policy = [ordered]@{
            copy_first = $true
            named_refs_bundle_all_verified = $true
            exact_git_supplemental_verified = $true
            unreachable_objects_preserved = $unreachableCopied.Count
            auth_session_browser_tmp_secret_copied = $false
            consumer_source_bytes_copied = $false
        }
        source_copies = $sourceCopies
        payload_files = $preManifestFiles
        evidence_relative_path = 'evidence/retirement-evidence.json'
        fresh_readback = [ordered]@{
            source_git_unchanged = $true
            source_worktree_unchanged = $true
            artifact_sources_unchanged = $true
            consumer_sources_unchanged = $true
            copied_git_matches_source_snapshot = $true
            payload_hashes_verified = $true
        }
    }
    $manifestPath = Join-Path $stagingFull 'manifest.json'
    Write-JsonFile -Path $manifestPath -Value $manifest -Depth 80
    $manifestHash = Get-Sha256Hex $manifestPath
    [IO.File]::WriteAllText(
        (Join-Path $stagingFull 'manifest.sha256'),
        "$manifestHash  manifest.json`n",
        $Utf8NoBom
    )

    if ((Get-Sha256Hex $manifestPath) -ne $manifestHash) {
        throw 'RETIREMENT_PACK_MANIFEST_READBACK_FAILED'
    }

    $completePath = Join-Path $stagingFull 'BUILD_COMPLETE.json'
    Write-JsonFile -Path $completePath -Value ([ordered]@{
        schema_version = 'xinao.native-cold-retirement-build-status.v1'
        status = 'complete'
        completed_at = (Get-Date).ToUniversalTime().ToString('o')
        manifest_sha256 = $manifestHash
        source_deleted = $false
        source_mutated = $false
    })
    [IO.File]::Delete($incompletePath)
    Write-Output $completePath
} catch {
    Write-JsonFile -Path $incompletePath -Value ([ordered]@{
        schema_version = 'xinao.native-cold-retirement-build-status.v1'
        status = 'failed'
        failed_at = (Get-Date).ToUniversalTime().ToString('o')
        error_type = $_.Exception.GetType().FullName
        error_message = $_.Exception.Message
        source_repository = $sourceRepositoryFull
        source_deleted = $false
    })
    throw
}
