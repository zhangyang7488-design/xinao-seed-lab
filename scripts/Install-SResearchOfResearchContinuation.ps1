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

$managedMarker = 'XINAO.S.RoR.ContinuationDetect.v0'
$taskPath = '\'
$expectedTaskFullName = "\$TaskName"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$bundleBase = Join-Path $env:LOCALAPPDATA 'XINAO\SResearchOfResearchContinuation'
$mutationMutexName = 'Global\XINAO.S.ResearchOfResearchContinuation.Mutation.v0'
$bundleSchema = 'xinao.s.ror-continuation-task-bundle.v0'
$manifestName = 'bundle_manifest.json'

$appFiles = @(
    'scripts/research_of_research_continuation.py',
    'services/__init__.py',
    'services/research_of_research/__init__.py',
    'services/research_of_research/continuation.py',
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
        [Parameter(Mandatory = $true)][object]$Plan
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
    if ($manifest.schema -ne $bundleSchema -or $manifest.content_id -ne $Plan.ContentId) {
        throw "BUNDLE_MANIFEST_IDENTITY_MISMATCH: $manifestPath"
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
    $arguments = "-I -B `"$script`" --runtime-root `"$runtimeFull`" reconcile"
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

function Assert-ManagedTask {
    param([Parameter(Mandatory = $true)][object]$Task)
    if (-not $Task.Description.StartsWith(
        $managedMarker + '|',
        [System.StringComparison]::Ordinal
    )) {
        throw "TASK_NOT_MANAGED_BY_THIS_INSTALLER: $expectedTaskFullName"
    }
}

function Test-TaskContract {
    param(
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][object]$Contract
    )
    Assert-ManagedTask -Task $Task
    if (@($Task.Actions).Count -ne 1) {
        throw 'TASK_ACTION_COUNT_INVALID'
    }
    $action = @($Task.Actions)[0]
    foreach ($pair in @(
        @('Execute', $action.Execute, $Contract.Execute),
        @('Arguments', $action.Arguments, $Contract.Arguments),
        @('WorkingDirectory', $action.WorkingDirectory, $Contract.WorkingDirectory),
        @('Description', $Task.Description, $Contract.Description)
    )) {
        if (-not [string]::Equals(
            [string]$pair[1],
            [string]$pair[2],
            [System.StringComparison]::OrdinalIgnoreCase
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
    $interval = [string](@($Task.Triggers)[0].Repetition.Interval)
    if ($interval -ne 'PT15M') {
        throw "TASK_RECOVERY_INTERVAL_INVALID: $interval"
    }
    [void](Test-Bundle -BundleRoot (Split-Path -Parent (Split-Path -Parent $Contract.Execute)) -Plan $script:sourcePlan)
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
            schema = 'xinao.s.ror-continuation-task-audit.v0'
            outcome = 'NOT_INSTALLED'
            task_full_name = $expectedTaskFullName
            expected_content_id = $Plan.ContentId
            authority = $false
            completion_claim_allowed = $false
        }
    }
    [void](Test-TaskContract -Task $task -Contract $Contract)
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $taskPath
    return [ordered]@{
        schema = 'xinao.s.ror-continuation-task-audit.v0'
        outcome = 'HEALTHY'
        task_full_name = $expectedTaskFullName
        state = [string]$task.State
        content_id = $Plan.ContentId
        action_execute = [string]@($task.Actions)[0].Execute
        action_arguments = [string]@($task.Actions)[0].Arguments
        working_directory = [string]@($task.Actions)[0].WorkingDirectory
        multiple_instances = [string]$task.Settings.MultipleInstances
        start_when_available = [bool]$task.Settings.StartWhenAvailable
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

    if ($operation -eq 'Remove') {
        $task = Get-CurrentTask
        if ($null -eq $task) {
            $result = [ordered]@{
                schema = 'xinao.s.ror-continuation-task-operation.v0'
                outcome = 'ALREADY_ABSENT'
                operation = $operation
                task_full_name = $expectedTaskFullName
                authority = $false
                completion_claim_allowed = $false
            }
        }
        else {
            Assert-ManagedTask -Task $task
            Unregister-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -Confirm:$false
            if ($null -ne (Get-CurrentTask)) {
                throw 'TASK_REMOVE_READBACK_FAILED'
            }
            $result = [ordered]@{
                schema = 'xinao.s.ror-continuation-task-operation.v0'
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
            [void](Test-TaskContract -Task $task -Contract $contract)
            Start-ScheduledTask -TaskName $TaskName -TaskPath $taskPath
            $result = [ordered]@{
                schema = 'xinao.s.ror-continuation-task-operation.v0'
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
            $existing = Get-CurrentTask
            if ($operation -eq 'Apply' -and $null -ne $existing) {
                throw "TASK_ALREADY_EXISTS: $expectedTaskFullName"
            }
            if ($operation -eq 'Upgrade' -and $null -eq $existing) {
                throw "TASK_NOT_INSTALLED: $expectedTaskFullName"
            }
            $priorXml = $null
            if ($null -ne $existing) {
                Assert-ManagedTask -Task $existing
                $priorXml = Export-ScheduledTask -TaskName $TaskName -TaskPath $taskPath
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
                [void](Test-TaskContract -Task $live -Contract $contract)
            }
            catch {
                if ($operation -eq 'Upgrade' -and $null -ne $priorXml) {
                    Register-ScheduledTask `
                        -TaskName $TaskName `
                        -TaskPath $taskPath `
                        -Xml $priorXml `
                        -Force | Out-Null
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
                schema = 'xinao.s.ror-continuation-task-operation.v0'
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
        schema = 'xinao.s.ror-continuation-task-operation.v0'
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
