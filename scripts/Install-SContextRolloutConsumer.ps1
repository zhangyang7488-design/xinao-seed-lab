[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Remove,
    [switch]$Audit,
    [ValidateSet(1, 2, 5)]
    [int]$Minutes = 2
)

$ErrorActionPreference = 'Stop'

$taskName = 'XINAO-S-Context-Rollout-Consumer-v1'
$taskPath = '\'
$pythonPath = 'D:\XINAO_RESEARCH_RUNTIME\tools\cpython-3.13.14-official\python.exe'
$repositoryRoot = 'E:\XINAO_RESEARCH_WORKSPACES\S'
$consumerScript = 'E:\XINAO_RESEARCH_WORKSPACES\S\scripts\context_rollout_consumer.py'
$expectedArguments = '-I -B "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\context_rollout_consumer.py"'
$requestedActions = @($Apply, $Remove, $Audit).Where({ $_ }).Count
if ($requestedActions -gt 1) {
    throw 'Choose only one of -Apply, -Remove, or -Audit.'
}
if ($requestedActions -eq 0) {
    $Audit = $true
}

function Get-CurrentIdentityName {
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
}

function Test-OrdinalPathEqual {
    param([string]$Actual, [string]$Expected)
    return [string]::Equals($Actual, $Expected, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-ConsumerTaskAudit {
    param([Nullable[int]]$ExpectedMinutes)

    $task = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        return [ordered]@{
            schema_version = 's.context_rollout_consumer.install_audit.v1'
            status = 'absent'
            task_name = $taskName
            task_path = $taskPath
            valid = $false
            authority = $false
        }
    }

    $identity = Get-CurrentIdentityName
    $action = @($task.Actions)
    $trigger = @($task.Triggers)
    $actionValid = $action.Count -eq 1 -and
        (Test-OrdinalPathEqual $action[0].Execute $pythonPath) -and
        [string]::Equals([string]$action[0].Arguments, $expectedArguments, [System.StringComparison]::Ordinal) -and
        (Test-OrdinalPathEqual $action[0].WorkingDirectory $repositoryRoot)
    $principalValid = (Test-OrdinalPathEqual ([string]$task.Principal.UserId) $identity) -and
        [string]::Equals([string]$task.Principal.RunLevel, 'Limited', [System.StringComparison]::OrdinalIgnoreCase) -and
        [string]::Equals([string]$task.Principal.LogonType, 'Interactive', [System.StringComparison]::OrdinalIgnoreCase)
    $settingsValid = [string]::Equals(
            [string]$task.Settings.MultipleInstances,
            'IgnoreNew',
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        [bool]$task.Settings.StartWhenAvailable -and
        -not [bool]$task.Settings.DisallowStartIfOnBatteries -and
        -not [bool]$task.Settings.StopIfGoingOnBatteries -and
        [string]::Equals(
            [string]$task.Settings.ExecutionTimeLimit,
            'PT5M',
            [System.StringComparison]::OrdinalIgnoreCase
        )
    $intervalText = if ($trigger.Count -eq 1) {
        [string]$trigger[0].Repetition.Interval
    } else {
        ''
    }
    $allowedIntervals = @('PT1M', 'PT2M', 'PT5M')
    $triggerValid = $trigger.Count -eq 1 -and $allowedIntervals -contains $intervalText
    if ($null -ne $ExpectedMinutes) {
        $triggerValid = $triggerValid -and $intervalText -eq "PT$($ExpectedMinutes.Value)M"
    }
    $filesValid = (Test-Path -LiteralPath $pythonPath -PathType Leaf) -and
        (Test-Path -LiteralPath $consumerScript -PathType Leaf)
    $enabledValid = -not [string]::Equals(
        [string]$task.State,
        'Disabled',
        [System.StringComparison]::OrdinalIgnoreCase
    )
    $contractValid = $actionValid -and $principalValid -and $settingsValid -and $triggerValid
    $valid = $contractValid -and $filesValid -and $enabledValid

    return [ordered]@{
        schema_version = 's.context_rollout_consumer.install_audit.v1'
        status = if ($valid) { 'installed_valid' } else { 'installed_drifted' }
        task_name = $taskName
        task_path = $taskPath
        valid = $valid
        contract_valid = $contractValid
        action_valid = $actionValid
        principal_valid = $principalValid
        settings_valid = $settingsValid
        trigger_valid = $triggerValid
        files_valid = $filesValid
        enabled_valid = $enabledValid
        execute = if ($action.Count -eq 1) { [string]$action[0].Execute } else { '' }
        arguments = if ($action.Count -eq 1) { [string]$action[0].Arguments } else { '' }
        working_directory = if ($action.Count -eq 1) { [string]$action[0].WorkingDirectory } else { '' }
        interval = $intervalText
        user_id = [string]$task.Principal.UserId
        multiple_instances = [string]$task.Settings.MultipleInstances
        start_when_available = [bool]$task.Settings.StartWhenAvailable
        disallow_start_on_batteries = [bool]$task.Settings.DisallowStartIfOnBatteries
        stop_if_going_on_batteries = [bool]$task.Settings.StopIfGoingOnBatteries
        execution_time_limit = [string]$task.Settings.ExecutionTimeLimit
        authority = $false
    }
}

if ($Apply) {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Official Python is missing: $pythonPath"
    }
    if (-not (Test-Path -LiteralPath $consumerScript -PathType Leaf)) {
        throw "Consumer script is missing from the live repository: $consumerScript"
    }
    $existing = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        $existingAudit = Get-ConsumerTaskAudit -ExpectedMinutes $Minutes
        if (-not $existingAudit.valid) {
            throw 'Refusing to overwrite an existing same-named Scheduled Task whose exact contract has drifted.'
        }
        $existingAudit.status = 'already_installed_valid'
        $existingAudit | ConvertTo-Json -Depth 5
        exit 0
    }
    $identity = Get-CurrentIdentityName
    $action = New-ScheduledTaskAction `
        -Execute $pythonPath `
        -Argument $expectedArguments `
        -WorkingDirectory $repositoryRoot
    $trigger = New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $Minutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    $principal = New-ScheduledTaskPrincipal `
        -UserId $identity `
        -LogonType Interactive `
        -RunLevel Limited
    $definition = New-ScheduledTask `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal
    Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -InputObject $definition | Out-Null
    $result = Get-ConsumerTaskAudit -ExpectedMinutes $Minutes
    if (-not $result.valid) {
        throw 'Scheduled Task readback did not match the exact consumer contract.'
    }
    $result | ConvertTo-Json -Depth 5
    exit 0
}

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        [ordered]@{
            schema_version = 's.context_rollout_consumer.install_audit.v1'
            status = 'already_absent'
            task_name = $taskName
            task_path = $taskPath
            authority = $false
        } | ConvertTo-Json -Depth 5
        exit 0
    }
    $auditResult = Get-ConsumerTaskAudit -ExpectedMinutes $null
    if (-not $auditResult.contract_valid) {
        throw 'Refusing to remove a same-named Scheduled Task whose exact contract has drifted.'
    }
    Unregister-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Confirm:$false
    if ($null -ne (Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue)) {
        throw 'Scheduled Task removal readback failed.'
    }
    [ordered]@{
        schema_version = 's.context_rollout_consumer.install_audit.v1'
        status = 'removed'
        task_name = $taskName
        task_path = $taskPath
        authority = $false
    } | ConvertTo-Json -Depth 5
    exit 0
}

$auditResult = Get-ConsumerTaskAudit -ExpectedMinutes $null
$auditResult | ConvertTo-Json -Depth 5
if ($auditResult.status -eq 'installed_drifted') {
    exit 2
}
exit 0
