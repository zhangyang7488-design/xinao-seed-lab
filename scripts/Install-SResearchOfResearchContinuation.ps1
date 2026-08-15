[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Upgrade,
    [switch]$Audit,
    [switch]$RunOnce,
    [switch]$Remove,
    [string]$RuntimeRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\research_of_research',
    [string]$OfficialPythonRoot = 'D:\XINAO_RESEARCH_RUNTIME\tools\cpython-3.13.14-official',
    [string]$TaskName = 'XINAO-S-RoR-Continuation-Detect-v0'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$managedMarker = 'XINAO.S.RoR.ContinuityConsumer.v1'
$managedTaskName = 'XINAO-S-RoR-Continuation-Detect-v0'
$managedPredecessorMarker = 'XINAO.S.RoR.ContinuationDetect.v0'
$managedPredecessorBundleSchema = 'xinao.s.ror-continuation-task-bundle.v0'
# These two hashes bind -Upgrade to the one live managed predecessor observed
# before this carrier revision.  A marker-shaped substitute is not admissible.
$managedPredecessorContentId = 'afc31aff0a26100087fb3f6553543b10f0a570033c8ec3e1644e9acd1d08866d'
$managedPredecessorXmlSha256 = '6118096d19799f9c6917750d6d79dad595820a62b20ec70161cbb3e61b1ab00f'
$managedPredecessorRuntimeRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\research_of_research'
$managedPredecessorTaskName = $managedTaskName
$taskPath = '\'
$expectedTaskFullName = "\$managedTaskName"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$bundleBase = Join-Path $env:LOCALAPPDATA 'XINAO\SResearchOfResearchContinuation'
$mutationMutexName = 'Global\XINAO.S.ResearchOfResearchContinuation.Mutation.v0'
$bundleSchema = 'xinao.s.ror-continuity-consumer-task-bundle.v1'
$manifestName = 'bundle_manifest.json'

$appFiles = @(
    'scripts/research_of_research_continuation.py',
    'services/__init__.py',
    'services/research_of_research/__init__.py',
    'services/research_of_research/continuation.py',
    'services/research_of_research/ongoing.py',
    'services/research_of_research/windows_job.py',
    'services/research_of_research/cell.py',
    'services/xinao_perpetual_world_compute/__init__.py',
    'services/xinao_perpetual_world_compute/controller.py'
)

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    return (Get-FileHash -LiteralPath $LiteralPath -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-BytesSha256Hex {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function ConvertTo-CanonicalJsonBytes {
    param([Parameter(Mandatory = $true)][object]$Value)
    $json = $Value | ConvertTo-Json -Depth 12 -Compress
    return [System.Text.UTF8Encoding]::new($false).GetBytes($json + "`n")
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][string]$Text
    )
    [System.IO.File]::WriteAllText(
        $LiteralPath,
        $Text,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Assert-RegularTree {
    param([Parameter(Mandatory = $true)][string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "TREE_MISSING: $Root"
    }
    foreach ($item in Get-ChildItem -LiteralPath $Root -Recurse -Force) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "TREE_REPARSE_POINT_FORBIDDEN: $($item.FullName)"
        }
    }
}

function Get-SourcePlan {
    Assert-RegularTree -Root $OfficialPythonRoot
    $rows = [System.Collections.Generic.List[object]]::new()
    foreach ($relative in $appFiles) {
        $source = Join-Path $repoRoot ($relative -replace '/', '\')
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "APP_SOURCE_MISSING: $source"
        }
        $rows.Add([ordered]@{
            relative_path = "app/$relative"
            sha256 = Get-Sha256Hex -LiteralPath $source
            source_path = [System.IO.Path]::GetFullPath($source)
        })
    }
    $pythonRootFull = [System.IO.Path]::GetFullPath($OfficialPythonRoot).TrimEnd('\')
    foreach ($file in Get-ChildItem -LiteralPath $pythonRootFull -File -Recurse -Force | Sort-Object FullName) {
        $relative = $file.FullName.Substring($pythonRootFull.Length).TrimStart('\').Replace('\', '/')
        $rows.Add([ordered]@{
            relative_path = "python/$relative"
            sha256 = Get-Sha256Hex -LiteralPath $file.FullName
            source_path = $file.FullName
        })
    }
    $identity = [ordered]@{
        schema = $bundleSchema
        runtime_root = [System.IO.Path]::GetFullPath($RuntimeRoot)
        files = @($rows | ForEach-Object {
            [ordered]@{ relative_path = $_.relative_path; sha256 = $_.sha256 }
        })
    }
    $contentId = Get-BytesSha256Hex -Bytes (ConvertTo-CanonicalJsonBytes -Value $identity)
    return [pscustomobject]@{
        ContentId = $contentId
        Rows = @($rows)
        Identity = $identity
    }
}

function Test-PathWithinBase {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Base
    )
    $candidateFull = [System.IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    $baseFull = [System.IO.Path]::GetFullPath($Base).TrimEnd('\')
    return $candidateFull.StartsWith(
        $baseFull + '\',
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Remove-OwnedStagingTree {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    if (-not (Test-PathWithinBase -Candidate $LiteralPath -Base $bundleBase)) {
        throw "STAGING_PATH_OUTSIDE_BUNDLE_BASE: $LiteralPath"
    }
    if ((Split-Path -Leaf $LiteralPath) -notlike '.staging-*') {
        throw "STAGING_PATH_IDENTITY_INVALID: $LiteralPath"
    }
    if (Test-Path -LiteralPath $LiteralPath) {
        Remove-Item -LiteralPath $LiteralPath -Recurse -Force
    }
}

function Test-Bundle {
    param(
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [Parameter(Mandatory = $true)][object]$Plan,
        [string]$ExpectedSchema = $bundleSchema
    )
    if (-not (Test-Path -LiteralPath $BundleRoot -PathType Container)) {
        throw "BUNDLE_MISSING: $BundleRoot"
    }
    Assert-RegularTree -Root $BundleRoot
    $manifestPath = Join-Path $BundleRoot $manifestName
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "BUNDLE_MANIFEST_MISSING: $manifestPath"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.schema -ne $ExpectedSchema -or $manifest.content_id -ne $Plan.ContentId) {
        throw "BUNDLE_MANIFEST_IDENTITY_MISMATCH: $manifestPath"
    }
    if (-not [string]::Equals(
        [string]$manifest.task_full_name,
        $expectedTaskFullName,
        [System.StringComparison]::Ordinal
    )) {
        throw "BUNDLE_TASK_IDENTITY_MISMATCH: $manifestPath"
    }
    if (-not [string]::Equals(
        [string]$manifest.runtime_root,
        [System.IO.Path]::GetFullPath($RuntimeRoot),
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "BUNDLE_RUNTIME_ROOT_MISMATCH: $manifestPath"
    }
    $expectedFiles = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($row in $Plan.Rows) {
        [void]$expectedFiles.Add(($row.relative_path -replace '/', '\'))
    }
    [void]$expectedFiles.Add($manifestName)
    $bundleRootFull = [System.IO.Path]::GetFullPath($BundleRoot).TrimEnd('\')
    $actualFiles = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($file in Get-ChildItem -LiteralPath $bundleRootFull -File -Recurse -Force) {
        $relative = $file.FullName.Substring($bundleRootFull.Length).TrimStart('\')
        [void]$actualFiles.Add($relative)
    }
    $missingFiles = @($expectedFiles | Where-Object { -not $actualFiles.Contains($_) })
    $extraFiles = @($actualFiles | Where-Object { -not $expectedFiles.Contains($_) })
    if ($missingFiles.Count -gt 0 -or $extraFiles.Count -gt 0) {
        throw "BUNDLE_FILE_SET_MISMATCH: missing=$($missingFiles -join ','); extra=$($extraFiles -join ',')"
    }
    foreach ($row in $Plan.Rows) {
        $target = Join-Path $BundleRoot ($row.relative_path -replace '/', '\')
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
            throw "BUNDLE_FILE_MISSING: $target"
        }
        if ((Get-Sha256Hex -LiteralPath $target) -ne $row.sha256) {
            throw "BUNDLE_FILE_HASH_MISMATCH: $target"
        }
    }
    return $true
}

function Ensure-Bundle {
    param([Parameter(Mandatory = $true)][object]$Plan)
    New-Item -ItemType Directory -Path $bundleBase -Force | Out-Null
    $bundleRoot = Join-Path $bundleBase $Plan.ContentId
    if (Test-Path -LiteralPath $bundleRoot) {
        [void](Test-Bundle -BundleRoot $bundleRoot -Plan $Plan)
        return $bundleRoot
    }

    $staging = Join-Path $bundleBase ('.staging-' + [guid]::NewGuid().ToString('N'))
    try {
        New-Item -ItemType Directory -Path $staging -Force | Out-Null
        $pythonDestination = Join-Path $staging 'python'
        Copy-Item -LiteralPath $OfficialPythonRoot -Destination $pythonDestination -Recurse -Force
        foreach ($row in $Plan.Rows | Where-Object { $_.relative_path -like 'app/*' }) {
            $target = Join-Path $staging ($row.relative_path -replace '/', '\')
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            Copy-Item -LiteralPath $row.source_path -Destination $target -Force
        }
        $manifest = [ordered]@{
            schema = $bundleSchema
            content_id = $Plan.ContentId
            task_full_name = $expectedTaskFullName
            runtime_root = [System.IO.Path]::GetFullPath($RuntimeRoot)
            files = @($Plan.Identity.files)
        }
        Write-Utf8NoBom -LiteralPath (Join-Path $staging $manifestName) -Text (
            ($manifest | ConvertTo-Json -Depth 12) + "`n"
        )
        [void](Test-Bundle -BundleRoot $staging -Plan $Plan)
        try {
            Move-Item -LiteralPath $staging -Destination $bundleRoot
        }
        catch {
            if (-not (Test-Path -LiteralPath $bundleRoot -PathType Container)) {
                throw
            }
        }
        if (Test-Path -LiteralPath $staging) {
            Remove-OwnedStagingTree -LiteralPath $staging
        }
        [void](Test-Bundle -BundleRoot $bundleRoot -Plan $Plan)
        return $bundleRoot
    }
    catch {
        if (Test-Path -LiteralPath $staging) {
            Remove-OwnedStagingTree -LiteralPath $staging
        }
        throw
    }
}

function Get-ExpectedTaskContract {
    param(
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [Parameter(Mandatory = $true)][string]$ContentId
    )
    $pythonw = Join-Path $BundleRoot 'python\pythonw.exe'
    $script = Join-Path $BundleRoot 'app\scripts\research_of_research_continuation.py'
    $workingDirectory = Join-Path $BundleRoot 'app'
    $runtimeFull = [System.IO.Path]::GetFullPath($RuntimeRoot)
    $arguments = "-I -B `"$script`" --runtime-root `"$runtimeFull`" reconcile-all"
    $runtimeHash = Get-BytesSha256Hex -Bytes (
        [System.Text.UTF8Encoding]::new($false).GetBytes($runtimeFull.ToLowerInvariant())
    )
    return [pscustomobject]@{
        Execute = $pythonw
        Arguments = $arguments
        WorkingDirectory = $workingDirectory
        Description = "$managedMarker|content_id=$ContentId|runtime_root_sha256=$runtimeHash"
        ContentId = $ContentId
    }
}

function New-ExpectedTaskDefinition {
    param([Parameter(Mandatory = $true)][object]$Contract)
    $action = New-ScheduledTaskAction `
        -Execute $Contract.Execute `
        -Argument $Contract.Arguments `
        -WorkingDirectory $Contract.WorkingDirectory
    $trigger = New-ScheduledTaskTrigger `
        -Once `
        -At ((Get-Date).AddMinutes(15)) `
        -RepetitionInterval (New-TimeSpan -Minutes 15) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    # This bounds the receipt/freeze/spawn tick; the detached runner owns the model timeout.
    $settings = New-ScheduledTaskSettingsSet `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal `
        -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited
    return New-ScheduledTask `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $Contract.Description
}

function Get-CurrentTask {
    return Get-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -ErrorAction SilentlyContinue
}

function Get-RuntimeRootSha256 {
    $runtimeFull = [System.IO.Path]::GetFullPath($RuntimeRoot)
    return Get-BytesSha256Hex -Bytes (
        [System.Text.UTF8Encoding]::new($false).GetBytes($runtimeFull.ToLowerInvariant())
    )
}

function Get-NormalizedTaskXmlSha256 {
    param([Parameter(Mandatory = $true)][string]$Xml)
    $document = [System.Xml.XmlDocument]::new()
    $document.PreserveWhitespace = $false
    $document.XmlResolver = $null
    $document.LoadXml($Xml)
    return Get-BytesSha256Hex -Bytes (
        [System.Text.UTF8Encoding]::new($false).GetBytes($document.OuterXml)
    )
}

function Get-TaskDefinitionIdentitySha256 {
    param([Parameter(Mandatory = $true)][object]$Task)
    $identity = [ordered]@{
        task_name = [string]$Task.TaskName
        task_path = [string]$Task.TaskPath
        description = [string]$Task.Description
        actions = @($Task.Actions | ForEach-Object {
            [ordered]@{
                execute = [string]$_.Execute
                arguments = [string]$_.Arguments
                working_directory = [string]$_.WorkingDirectory
            }
        })
        settings = [ordered]@{
            multiple_instances = [string]$Task.Settings.MultipleInstances
            start_when_available = [bool]$Task.Settings.StartWhenAvailable
            execution_time_limit = [string]$Task.Settings.ExecutionTimeLimit
            restart_count = [int]$Task.Settings.RestartCount
            restart_interval = [string]$Task.Settings.RestartInterval
            disallow_start_if_on_batteries = [bool]$Task.Settings.DisallowStartIfOnBatteries
            stop_if_going_on_batteries = [bool]$Task.Settings.StopIfGoingOnBatteries
        }
        principal = [ordered]@{
            user_id = [string]$Task.Principal.UserId
            logon_type = [string]$Task.Principal.LogonType
            run_level = [string]$Task.Principal.RunLevel
        }
        triggers = @($Task.Triggers | ForEach-Object {
            [ordered]@{
                class_name = [string]$_.CimClass.CimClassName
                enabled = [bool]$_.Enabled
                start_boundary = [string]$_.StartBoundary
                end_boundary = [string]$_.EndBoundary
                repetition_interval = [string]$_.Repetition.Interval
                repetition_duration = [string]$_.Repetition.Duration
                stop_at_duration_end = [bool]$_.Repetition.StopAtDurationEnd
            }
        })
    }
    return Get-BytesSha256Hex -Bytes (ConvertTo-CanonicalJsonBytes -Value $identity)
}

function Get-ManagedBundlePlan {
    param(
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [Parameter(Mandatory = $true)][string]$ContentId,
        [Parameter(Mandatory = $true)][string]$ExpectedSchema,
        [Parameter(Mandatory = $true)][string]$ExpectedRuntimeRoot,
        [Parameter(Mandatory = $true)][string[]]$RequiredFiles,
        [Parameter(Mandatory = $true)][string]$ErrorPrefix,
        [string]$PinnedContentId = ''
    )
    if ($PinnedContentId -and $ContentId -ne $PinnedContentId) {
        throw "${ErrorPrefix}_CONTENT_ID_INVALID: $ContentId"
    }
    $manifestPath = Join-Path $BundleRoot $manifestName
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "${ErrorPrefix}_MANIFEST_MISSING: $manifestPath"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if (
        [string]$manifest.schema -ne $ExpectedSchema -or
        [string]$manifest.content_id -ne $ContentId -or
        -not [string]::Equals(
            [string]$manifest.task_full_name,
            $expectedTaskFullName,
            [System.StringComparison]::Ordinal
        ) -or
        -not [string]::Equals(
            [System.IO.Path]::GetFullPath([string]$manifest.runtime_root),
            [System.IO.Path]::GetFullPath($ExpectedRuntimeRoot),
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "${ErrorPrefix}_MANIFEST_IDENTITY_INVALID: $manifestPath"
    }
    $rows = [System.Collections.Generic.List[object]]::new()
    $relativePaths = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($file in @($manifest.files)) {
        $relative = [string]$file.relative_path
        $sha256 = [string]$file.sha256
        if (
            $relative -notmatch '^(app|python)/[^/\\:]+(?:/[^/\\:]+)*$' -or
            $relative -match '(^|/)\.\.?(?:/|$)' -or
            $sha256 -notmatch '^[0-9a-f]{64}$' -or
            -not $relativePaths.Add($relative)
        ) {
            throw "${ErrorPrefix}_MANIFEST_FILE_INVALID: $relative"
        }
        $rows.Add([ordered]@{ relative_path = $relative; sha256 = $sha256 })
    }
    if ($rows.Count -eq 0) {
        throw "${ErrorPrefix}_MANIFEST_EMPTY: $manifestPath"
    }
    foreach ($required in $RequiredFiles) {
        if (-not $relativePaths.Contains($required)) {
            throw "${ErrorPrefix}_REQUIRED_FILE_MISSING: $required"
        }
    }
    $identity = [ordered]@{
        schema = $ExpectedSchema
        runtime_root = [System.IO.Path]::GetFullPath($ExpectedRuntimeRoot)
        files = @($rows | ForEach-Object {
            [ordered]@{ relative_path = $_.relative_path; sha256 = $_.sha256 }
        })
    }
    $observedContentId = Get-BytesSha256Hex -Bytes (ConvertTo-CanonicalJsonBytes -Value $identity)
    if ($observedContentId -ne $ContentId) {
        throw "${ErrorPrefix}_CONTENT_ID_MISMATCH: $observedContentId"
    }
    $plan = [pscustomobject]@{
        ContentId = $ContentId
        Rows = @($rows)
        Identity = $identity
    }
    [void](Test-Bundle `
        -BundleRoot $BundleRoot `
        -Plan $plan `
        -ExpectedSchema $ExpectedSchema)
    return $plan
}

function Test-ManagedPredecessorBundle {
    param(
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [Parameter(Mandatory = $true)][string]$ContentId
    )
    [void](Get-ManagedBundlePlan `
        -BundleRoot $BundleRoot `
        -ContentId $ContentId `
        -ExpectedSchema $managedPredecessorBundleSchema `
        -ExpectedRuntimeRoot $managedPredecessorRuntimeRoot `
        -RequiredFiles @(
            'app/scripts/research_of_research_continuation.py',
            'app/services/research_of_research/continuation.py',
            'python/pythonw.exe'
        ) `
        -ErrorPrefix 'TASK_UPGRADE_PREDECESSOR' `
        -PinnedContentId $managedPredecessorContentId)
}

function Assert-ManagedPredecessorTask {
    param(
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][System.Text.RegularExpressions.Match]$DescriptionMatch
    )
    if (
        $TaskName -ne $managedPredecessorTaskName -or
        [string]$Task.TaskName -ne $managedPredecessorTaskName -or
        [string]$Task.TaskPath -ne '\' -or
        [string]$Task.State -ne 'Ready'
    ) {
        throw "TASK_UPGRADE_PREDECESSOR_IDENTITY_INVALID: $expectedTaskFullName"
    }
    if (-not [string]::Equals(
        [System.IO.Path]::GetFullPath($RuntimeRoot),
        [System.IO.Path]::GetFullPath($managedPredecessorRuntimeRoot),
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "TASK_UPGRADE_PREDECESSOR_RUNTIME_INVALID: $RuntimeRoot"
    }
    $contentId = $DescriptionMatch.Groups['content_id'].Value
    $runtimeHash = $DescriptionMatch.Groups['runtime_hash'].Value
    if ($runtimeHash -ne (Get-RuntimeRootSha256)) {
        throw "TASK_UPGRADE_PREDECESSOR_RUNTIME_HASH_INVALID: $runtimeHash"
    }
    $predecessorXml = Export-ScheduledTask -TaskName $TaskName -TaskPath $taskPath
    if ((Get-NormalizedTaskXmlSha256 -Xml $predecessorXml) -ne $managedPredecessorXmlSha256) {
        throw 'TASK_UPGRADE_PREDECESSOR_XML_IDENTITY_INVALID'
    }
    $bundleRoot = Join-Path $bundleBase $contentId
    [void](Test-ManagedPredecessorBundle -BundleRoot $bundleRoot -ContentId $contentId)

    if (@($Task.Actions).Count -ne 1) {
        throw 'TASK_UPGRADE_PREDECESSOR_ACTION_COUNT_INVALID'
    }
    $action = @($Task.Actions)[0]
    $expectedExecute = Join-Path $bundleRoot 'python\pythonw.exe'
    $expectedScript = Join-Path $bundleRoot 'app\scripts\research_of_research_continuation.py'
    $expectedWorkingDirectory = Join-Path $bundleRoot 'app'
    $expectedArguments = "-I -B `"$expectedScript`" --runtime-root `"$managedPredecessorRuntimeRoot`" reconcile"
    foreach ($pair in @(
        @(
            'EXECUTE',
            [string]$action.Execute,
            $expectedExecute,
            [System.StringComparison]::OrdinalIgnoreCase
        ),
        @(
            'ARGUMENTS',
            [string]$action.Arguments,
            $expectedArguments,
            [System.StringComparison]::Ordinal
        ),
        @(
            'WORKING_DIRECTORY',
            [string]$action.WorkingDirectory,
            $expectedWorkingDirectory,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    )) {
        if (-not [string]::Equals(
            [string]$pair[1],
            [string]$pair[2],
            [System.StringComparison]$pair[3]
        )) {
            throw "TASK_UPGRADE_PREDECESSOR_$($pair[0])_INVALID"
        }
    }
    if (
        [string]$Task.Settings.MultipleInstances -ne 'IgnoreNew' -or
        -not [bool]$Task.Settings.StartWhenAvailable -or
        [string]$Task.Settings.ExecutionTimeLimit -ne 'PT5M' -or
        [int]$Task.Settings.RestartCount -ne 0 -or
        -not [string]::IsNullOrEmpty([string]$Task.Settings.RestartInterval) -or
        [bool]$Task.Settings.DisallowStartIfOnBatteries -or
        [bool]$Task.Settings.StopIfGoingOnBatteries
    ) {
        throw 'TASK_UPGRADE_PREDECESSOR_SETTINGS_INVALID'
    }
    $expectedUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $expectedUserLeaf = ($expectedUser -split '\\')[-1]
    $observedUser = [string]$Task.Principal.UserId
    if (
        -not (
            [string]::Equals(
                $observedUser,
                $expectedUser,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or [string]::Equals(
                $observedUser,
                $expectedUserLeaf,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) -or
        [string]$Task.Principal.LogonType -notin @('Interactive', 'InteractiveToken') -or
        [string]$Task.Principal.RunLevel -ne 'Limited'
    ) {
        throw 'TASK_UPGRADE_PREDECESSOR_PRINCIPAL_INVALID'
    }
    if (@($Task.Triggers).Count -ne 1) {
        throw 'TASK_UPGRADE_PREDECESSOR_TRIGGER_COUNT_INVALID'
    }
    $trigger = @($Task.Triggers)[0]
    if (
        [string]$trigger.CimClass.CimClassName -ne 'MSFT_TaskTimeTrigger' -or
        -not [bool]$trigger.Enabled -or
        [string]$trigger.Repetition.Interval -ne 'PT15M' -or
        [string]$trigger.Repetition.Duration -ne 'P3650D' -or
        -not [bool]$trigger.Repetition.StopAtDurationEnd
    ) {
        throw 'TASK_UPGRADE_PREDECESSOR_TRIGGER_INVALID'
    }
}

function Assert-ManagedCurrentTask {
    param(
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][System.Text.RegularExpressions.Match]$DescriptionMatch,
        [switch]$RequireQuiescent
    )
    if (
        $TaskName -ne $managedTaskName -or
        [string]$Task.TaskName -ne $managedTaskName -or
        [string]$Task.TaskPath -ne $taskPath
    ) {
        throw "TASK_CURRENT_IDENTITY_INVALID: $expectedTaskFullName"
    }
    if ($RequireQuiescent -and [string]$Task.State -ne 'Ready') {
        throw "TASK_CURRENT_INSTANCE_ACTIVE: $($Task.State)"
    }
    $contentId = $DescriptionMatch.Groups['content_id'].Value
    $runtimeHash = $DescriptionMatch.Groups['runtime_hash'].Value
    if ($runtimeHash -ne (Get-RuntimeRootSha256)) {
        throw "TASK_CURRENT_RUNTIME_HASH_INVALID: $runtimeHash"
    }
    $runtimeFull = [System.IO.Path]::GetFullPath($RuntimeRoot)
    $bundleRoot = Join-Path $bundleBase $contentId
    $plan = Get-ManagedBundlePlan `
        -BundleRoot $bundleRoot `
        -ContentId $contentId `
        -ExpectedSchema $bundleSchema `
        -ExpectedRuntimeRoot $runtimeFull `
        -RequiredFiles @(
            'app/scripts/research_of_research_continuation.py',
            'app/services/research_of_research/continuation.py',
            'app/services/research_of_research/ongoing.py',
            'app/services/research_of_research/windows_job.py',
            'python/pythonw.exe'
        ) `
        -ErrorPrefix 'TASK_CURRENT'
    $contract = Get-ExpectedTaskContract -BundleRoot $bundleRoot -ContentId $contentId
    [void](Test-TaskContract -Task $Task -Contract $contract -Plan $plan)
}

function Assert-ManagedTask {
    param(
        [Parameter(Mandatory = $true)][object]$Task,
        [switch]$AllowUpgradePredecessor,
        [switch]$RequireQuiescent
    )
    $description = [string]$Task.Description
    $suffixPattern = '\|content_id=(?<content_id>[0-9a-f]{64})\|runtime_root_sha256=(?<runtime_hash>[0-9a-f]{64})'
    $currentPattern = '^' + [regex]::Escape($managedMarker) + $suffixPattern + '$'
    $currentMatch = [regex]::Match($description, $currentPattern)
    if ($currentMatch.Success) {
        Assert-ManagedCurrentTask `
            -Task $Task `
            -DescriptionMatch $currentMatch `
            -RequireQuiescent:$RequireQuiescent
        return
    }
    if ($AllowUpgradePredecessor) {
        $predecessorPattern = '^' + [regex]::Escape($managedPredecessorMarker) + $suffixPattern + '$'
        $predecessorMatch = [regex]::Match($description, $predecessorPattern)
        if ($predecessorMatch.Success) {
            Assert-ManagedPredecessorTask -Task $Task -DescriptionMatch $predecessorMatch
            return
        }
    }
    throw "TASK_NOT_MANAGED_BY_THIS_INSTALLER: $expectedTaskFullName"
}

function Test-TaskContract {
    param(
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][object]$Contract,
        [object]$Plan = $script:sourcePlan
    )
    if (
        [string]$Task.TaskName -ne $managedTaskName -or
        [string]$Task.TaskPath -ne $taskPath
    ) {
        throw "TASK_IDENTITY_MISMATCH: $expectedTaskFullName"
    }
    if (@($Task.Actions).Count -ne 1) {
        throw 'TASK_ACTION_COUNT_INVALID'
    }
    $action = @($Task.Actions)[0]
    foreach ($pair in @(
        @(
            'Execute',
            $action.Execute,
            $Contract.Execute,
            [System.StringComparison]::OrdinalIgnoreCase
        ),
        @(
            'Arguments',
            $action.Arguments,
            $Contract.Arguments,
            [System.StringComparison]::Ordinal
        ),
        @(
            'WorkingDirectory',
            $action.WorkingDirectory,
            $Contract.WorkingDirectory,
            [System.StringComparison]::OrdinalIgnoreCase
        ),
        @(
            'Description',
            $Task.Description,
            $Contract.Description,
            [System.StringComparison]::Ordinal
        )
    )) {
        if (-not [string]::Equals(
            [string]$pair[1],
            [string]$pair[2],
            [System.StringComparison]$pair[3]
        )) {
            throw "TASK_$($pair[0].ToUpperInvariant())_MISMATCH"
        }
    }
    if ([string]$Task.Settings.MultipleInstances -ne 'IgnoreNew') {
        throw 'TASK_MULTIPLE_INSTANCES_INVALID'
    }
    if (-not [bool]$Task.Settings.StartWhenAvailable) {
        throw 'TASK_START_WHEN_AVAILABLE_DISABLED'
    }
    if ([string]$Task.Settings.ExecutionTimeLimit -ne 'PT5M') {
        throw "TASK_EXECUTION_TIME_LIMIT_INVALID: $($Task.Settings.ExecutionTimeLimit)"
    }
    if (
        [int]$Task.Settings.RestartCount -ne 0 -or
        -not [string]::IsNullOrEmpty([string]$Task.Settings.RestartInterval)
    ) {
        throw 'TASK_RESTART_POLICY_INVALID'
    }
    if (
        [bool]$Task.Settings.DisallowStartIfOnBatteries -or
        [bool]$Task.Settings.StopIfGoingOnBatteries
    ) {
        throw 'TASK_BATTERY_POLICY_INVALID'
    }
    $expectedUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $expectedUserLeaf = ($expectedUser -split '\\')[-1]
    $observedUser = [string]$Task.Principal.UserId
    $principalMatches = [string]::Equals(
        $observedUser,
        $expectedUser,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or [string]::Equals(
        $observedUser,
        $expectedUserLeaf,
        [System.StringComparison]::OrdinalIgnoreCase
    )
    if (-not $principalMatches) {
        throw "TASK_PRINCIPAL_INVALID: $($Task.Principal.UserId)"
    }
    if ([string]$Task.Principal.LogonType -notin @('Interactive', 'InteractiveToken')) {
        throw "TASK_LOGON_TYPE_INVALID: $($Task.Principal.LogonType)"
    }
    if ([string]$Task.Principal.RunLevel -ne 'Limited') {
        throw "TASK_RUN_LEVEL_INVALID: $($Task.Principal.RunLevel)"
    }
    if (@($Task.Triggers).Count -ne 1) {
        throw 'TASK_TRIGGER_COUNT_INVALID'
    }
    $trigger = @($Task.Triggers)[0]
    $interval = [string]$trigger.Repetition.Interval
    if ($interval -ne 'PT15M') {
        throw "TASK_RECOVERY_INTERVAL_INVALID: $interval"
    }
    if (
        [string]$trigger.CimClass.CimClassName -ne 'MSFT_TaskTimeTrigger' -or
        -not [bool]$trigger.Enabled -or
        [string]$trigger.Repetition.Duration -ne 'P3650D' -or
        -not [bool]$trigger.Repetition.StopAtDurationEnd
    ) {
        throw 'TASK_RECOVERY_TRIGGER_INVALID'
    }
    [void](Test-Bundle `
        -BundleRoot (Split-Path -Parent (Split-Path -Parent $Contract.Execute)) `
        -Plan $Plan)
    return $true
}

function Get-AuditReceipt {
    param(
        [Parameter(Mandatory = $true)][object]$Contract,
        [Parameter(Mandatory = $true)][object]$Plan
    )
    $task = Get-CurrentTask
    if ($null -eq $task) {
        return [ordered]@{
            schema = 'xinao.s.ror-continuity-consumer-task-audit.v1'
            outcome = 'NOT_INSTALLED'
            task_full_name = $expectedTaskFullName
            expected_content_id = $Plan.ContentId
            authority = $false
            completion_claim_allowed = $false
        }
    }
    [void](Test-TaskContract -Task $task -Contract $Contract -Plan $Plan)
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $taskPath
    return [ordered]@{
        schema = 'xinao.s.ror-continuity-consumer-task-audit.v1'
        outcome = 'HEALTHY'
        task_full_name = $expectedTaskFullName
        state = [string]$task.State
        content_id = $Plan.ContentId
        action_execute = [string]@($task.Actions)[0].Execute
        action_arguments = [string]@($task.Actions)[0].Arguments
        working_directory = [string]@($task.Actions)[0].WorkingDirectory
        multiple_instances = [string]$task.Settings.MultipleInstances
        start_when_available = [bool]$task.Settings.StartWhenAvailable
        execution_time_limit = [string]$task.Settings.ExecutionTimeLimit
        restart_count = [int]$task.Settings.RestartCount
        recovery_interval = [string]@($task.Triggers)[0].Repetition.Interval
        last_run_time = $info.LastRunTime
        last_task_result = $info.LastTaskResult
        next_run_time = $info.NextRunTime
        authority = $false
        completion_claim_allowed = $false
    }
}

$operations = @(@(
    [pscustomobject]@{ Name = 'Apply'; Enabled = [bool]$Apply },
    [pscustomobject]@{ Name = 'Upgrade'; Enabled = [bool]$Upgrade },
    [pscustomobject]@{ Name = 'Audit'; Enabled = [bool]$Audit },
    [pscustomobject]@{ Name = 'RunOnce'; Enabled = [bool]$RunOnce },
    [pscustomobject]@{ Name = 'Remove'; Enabled = [bool]$Remove }
) | Where-Object { $_.Enabled })
if ($operations.Count -gt 1) {
    throw 'CHOOSE_EXACTLY_ONE_OPERATION'
}
$operation = if ($operations.Count -eq 0) { 'Audit' } else { [string]$operations[0].Name }

$mutex = [System.Threading.Mutex]::new($false, $mutationMutexName)
$hasMutex = $false
try {
    $hasMutex = $mutex.WaitOne([TimeSpan]::FromSeconds(30))
    if (-not $hasMutex) {
        throw 'INSTALLER_MUTATION_LOCK_TIMEOUT'
    }
    if ($TaskName -ne $managedTaskName) {
        throw "TASK_NAME_OVERRIDE_FORBIDDEN: $TaskName"
    }

    if ($operation -eq 'Remove') {
        $task = Get-CurrentTask
        if ($null -eq $task) {
            $result = [ordered]@{
                schema = 'xinao.s.ror-continuity-consumer-task-operation.v1'
                outcome = 'ALREADY_ABSENT'
                operation = $operation
                task_full_name = $expectedTaskFullName
                authority = $false
                completion_claim_allowed = $false
            }
        }
        else {
            [void](Assert-ManagedTask -Task $task -RequireQuiescent)
            Unregister-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -Confirm:$false
            if ($null -ne (Get-CurrentTask)) {
                throw 'TASK_REMOVE_READBACK_FAILED'
            }
            $result = [ordered]@{
                schema = 'xinao.s.ror-continuity-consumer-task-operation.v1'
                outcome = 'REMOVED'
                operation = $operation
                task_full_name = $expectedTaskFullName
                bundle_retained = $true
                authority = $false
                completion_claim_allowed = $false
            }
        }
    }
    else {
        $existingForMutation = $null
        $priorXml = $null
        $priorXmlBytesSha256 = $null
        $priorXmlSha256 = $null
        $priorTaskIdentitySha256 = $null
        if ($operation -in @('Apply', 'Upgrade')) {
            $existingForMutation = Get-CurrentTask
            if ($operation -eq 'Apply' -and $null -ne $existingForMutation) {
                throw "TASK_ALREADY_EXISTS: $expectedTaskFullName"
            }
            if ($operation -eq 'Upgrade' -and $null -eq $existingForMutation) {
                throw "TASK_NOT_INSTALLED: $expectedTaskFullName"
            }
            if ($null -ne $existingForMutation) {
                [void](Assert-ManagedTask `
                    -Task $existingForMutation `
                    -AllowUpgradePredecessor:($operation -eq 'Upgrade') `
                    -RequireQuiescent:($operation -eq 'Upgrade'))
                $priorXml = Export-ScheduledTask -TaskName $TaskName -TaskPath $taskPath
                $priorXmlBytesSha256 = Get-BytesSha256Hex -Bytes (
                    [System.Text.UTF8Encoding]::new($false).GetBytes($priorXml)
                )
                $priorXmlSha256 = Get-NormalizedTaskXmlSha256 -Xml $priorXml
                $priorTaskIdentitySha256 = Get-TaskDefinitionIdentitySha256 `
                    -Task $existingForMutation
            }
        }
        $script:sourcePlan = Get-SourcePlan
        $bundleRoot = Join-Path $bundleBase $script:sourcePlan.ContentId
        if ($operation -in @('Apply', 'Upgrade')) {
            $bundleRoot = Ensure-Bundle -Plan $script:sourcePlan
        }
        $contract = Get-ExpectedTaskContract -BundleRoot $bundleRoot -ContentId $script:sourcePlan.ContentId

        if ($operation -eq 'Audit') {
            $result = Get-AuditReceipt -Contract $contract -Plan $script:sourcePlan
        }
        elseif ($operation -eq 'RunOnce') {
            $task = Get-CurrentTask
            if ($null -eq $task) {
                throw "TASK_NOT_INSTALLED: $expectedTaskFullName"
            }
            [void](Assert-ManagedTask -Task $task)
            [void](Test-TaskContract `
                -Task $task `
                -Contract $contract `
                -Plan $script:sourcePlan)
            Start-ScheduledTask -TaskName $TaskName -TaskPath $taskPath
            $result = [ordered]@{
                schema = 'xinao.s.ror-continuity-consumer-task-operation.v1'
                outcome = 'RUN_REQUESTED'
                operation = $operation
                task_full_name = $expectedTaskFullName
                content_id = $script:sourcePlan.ContentId
                schedule_unchanged = $true
                authority = $false
                completion_claim_allowed = $false
            }
        }
        else {
            if ($operation -eq 'Upgrade') {
                $beforeRegister = Get-CurrentTask
                if ($null -eq $beforeRegister) {
                    throw 'TASK_UPGRADE_PRECONDITION_MISSING'
                }
                [void](Assert-ManagedTask `
                    -Task $beforeRegister `
                    -AllowUpgradePredecessor `
                    -RequireQuiescent)
                $beforeRegisterXml = Export-ScheduledTask `
                    -TaskName $TaskName `
                    -TaskPath $taskPath
                if (
                    (Get-BytesSha256Hex -Bytes (
                        [System.Text.UTF8Encoding]::new($false).GetBytes($beforeRegisterXml)
                    )) -ne $priorXmlBytesSha256 -or
                    (Get-TaskDefinitionIdentitySha256 -Task $beforeRegister) -ne (
                        $priorTaskIdentitySha256
                    )
                ) {
                    throw 'TASK_UPGRADE_PRECONDITION_CHANGED'
                }
            }
            $definition = New-ExpectedTaskDefinition -Contract $contract
            $registered = $false
            try {
                if ($operation -eq 'Upgrade') {
                    Register-ScheduledTask `
                        -TaskName $TaskName `
                        -TaskPath $taskPath `
                        -InputObject $definition `
                        -Force | Out-Null
                }
                else {
                    Register-ScheduledTask `
                        -TaskName $TaskName `
                        -TaskPath $taskPath `
                        -InputObject $definition | Out-Null
                }
                $registered = $true
                $live = Get-CurrentTask
                if ($null -eq $live) {
                    throw 'TASK_REGISTER_READBACK_MISSING'
                }
                [void](Test-TaskContract `
                    -Task $live `
                    -Contract $contract `
                    -Plan $script:sourcePlan)
            }
            catch {
                if ($operation -eq 'Upgrade' -and $null -ne $priorXml) {
                    Register-ScheduledTask `
                        -TaskName $TaskName `
                        -TaskPath $taskPath `
                        -Xml $priorXml `
                        -Force | Out-Null
                    $restored = Get-CurrentTask
                    if ($null -eq $restored) {
                        throw 'TASK_UPGRADE_ROLLBACK_READBACK_MISSING'
                    }
                    [void](Assert-ManagedTask -Task $restored -AllowUpgradePredecessor)
                    $restoredXml = Export-ScheduledTask -TaskName $TaskName -TaskPath $taskPath
                    if (
                        (Get-BytesSha256Hex -Bytes (
                            [System.Text.UTF8Encoding]::new($false).GetBytes($restoredXml)
                        )) -ne $priorXmlBytesSha256 -or
                        (Get-NormalizedTaskXmlSha256 -Xml $restoredXml) -ne $priorXmlSha256 -or
                        (Get-TaskDefinitionIdentitySha256 -Task $restored) -ne $priorTaskIdentitySha256
                    ) {
                        throw 'TASK_UPGRADE_ROLLBACK_IDENTITY_MISMATCH'
                    }
                }
                elseif ($registered) {
                    $candidate = Get-CurrentTask
                    if ($null -ne $candidate -and $candidate.Description -eq $contract.Description) {
                        Unregister-ScheduledTask `
                            -TaskName $TaskName `
                            -TaskPath $taskPath `
                            -Confirm:$false
                    }
                }
                throw
            }
            $result = [ordered]@{
                schema = 'xinao.s.ror-continuity-consumer-task-operation.v1'
                outcome = if ($operation -eq 'Upgrade') { 'UPGRADED' } else { 'APPLIED' }
                operation = $operation
                task_full_name = $expectedTaskFullName
                content_id = $script:sourcePlan.ContentId
                bundle_root = $bundleRoot
                authority = $false
                completion_claim_allowed = $false
            }
        }
    }

    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $result | ConvertTo-Json -Depth 10
}
catch {
    $errorResult = [ordered]@{
        schema = 'xinao.s.ror-continuity-consumer-task-operation.v1'
        outcome = 'ERROR'
        operation = $operation
        task_full_name = $expectedTaskFullName
        error = $_.Exception.Message
        authority = $false
        completion_claim_allowed = $false
    }
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $errorResult | ConvertTo-Json -Depth 10
    exit 1
}
finally {
    if ($hasMutex) {
        [void]$mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
