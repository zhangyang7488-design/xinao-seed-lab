#Requires -Version 7.2
[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet('ensure', 'submit', 'run', 'status', 'cancel', 'history', 'close', 'raw')]
    [string]$Action = 'status',
    [string]$Session = 'xinao-main',
    [string]$Cwd = '',
    [string]$Prompt = '',
    [string]$PromptFile = '',
    [ValidateSet('approve-reads', 'approve-all', 'deny-all')]
    [string]$Permissions = 'approve-reads',
    [int]$TimeoutSeconds = 1800,
    [int]$TtlSeconds = 300,
    [int]$HistoryLimit = 20,
    [string]$AcpxHome = 'D:\XINAO_RESEARCH_RUNTIME\state\acpx-grok-brain',
    [string]$GrokHome = 'C:\Users\xx363\.grok-4.5-lane',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RawArgs = @()
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$AcpxLauncher = Join-Path $ProjectRoot 'provisioning\Invoke-XinaoAcpxManaged.ps1'
$ConfigSource = Join-Path $ProjectRoot 'provisioning\acpx-grok-config.json'
$AcpxHome = [IO.Path]::GetFullPath($AcpxHome)
$Cwd = if ($Cwd -eq '') { Join-Path $AcpxHome 'work' } else { $Cwd }
$Cwd = [IO.Path]::GetFullPath($Cwd)

if (-not (Test-Path -LiteralPath $GrokHome -PathType Container)) {
    throw "XINAO_GROK_HOME_MISSING: $GrokHome"
}
if (-not (Test-Path -LiteralPath $Cwd -PathType Container)) {
    if ($Cwd.StartsWith($AcpxHome.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        [void][IO.Directory]::CreateDirectory($Cwd)
    }
    else {
        throw "XINAO_GROK_CWD_MISSING: $Cwd"
    }
}

$configDir = Join-Path $AcpxHome '.acpx'
$configPath = Join-Path $configDir 'config.json'
[void][IO.Directory]::CreateDirectory($configDir)
$sourceHash = (Get-FileHash -LiteralPath $ConfigSource -Algorithm SHA256).Hash
$targetHash = if (Test-Path -LiteralPath $configPath -PathType Leaf) {
    (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
} else { '' }
if ($sourceHash -ne $targetHash) {
    $temp = Join-Path $configDir ('.config.{0}.{1}.tmp' -f $PID, [guid]::NewGuid().ToString('N'))
    Copy-Item -LiteralPath $ConfigSource -Destination $temp
    Move-Item -LiteralPath $temp -Destination $configPath -Force
}

# Capability gate (not name-history theater): Grok 0.2.x shell surface is shell_terminal.
# Both observed tool ids must be denied; lone "Bash" is a wrong-agent alias and fails open.
$requiredShellDenyCsv = 'run_terminal_cmd,run_terminal_command'
$configProbe = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$agentArgs = @($configProbe.agents.'grok-build'.args)
$denyIdx = [Array]::IndexOf($agentArgs, '--disallowed-tools')
$denyToken = if ($denyIdx -ge 0 -and ($denyIdx + 1) -lt $agentArgs.Count) { [string]$agentArgs[$denyIdx + 1] } else { '' }
if ($denyToken -ne $requiredShellDenyCsv) {
    throw ("XINAO_GROK_ACP_SHELL_CAPABILITY_DENY_MISMATCH: expected={0} actual={1} config={2}" -f `
        $requiredShellDenyCsv, $denyToken, $configPath)
}

$env:USERPROFILE = $AcpxHome
$env:HOME = $AcpxHome
$env:GROK_HOME = [IO.Path]::GetFullPath($GrokHome)
$env:XINAO_COORD_ROLE = 'grok_4_5'

$permissionFlag = switch ($Permissions) {
    'approve-all' { '--approve-all' }
    'deny-all' { '--deny-all' }
    default { '--approve-reads' }
}
$common = @(
    '--cwd', $Cwd,
    $permissionFlag,
    '--auth-policy', 'skip',
    '--non-interactive-permissions', 'fail',
    '--format', 'json',
    '--json-strict',
    '--timeout', [string]$TimeoutSeconds,
    '--ttl', [string]$TtlSeconds
)
$safePromptCommon = @(
    '--cwd', $Cwd,
    $permissionFlag,
    '--auth-policy', 'skip',
    '--non-interactive-permissions', 'fail',
    '--format', 'quiet',
    '--suppress-reads',
    '--timeout', [string]$TimeoutSeconds,
    '--ttl', [string]$TtlSeconds
)

function Test-AcpxQuietMetadataLine {
    param([Parameter(Mandatory)][string]$Line)
    $plain = $Line -replace '\x1B\[[0-?]*[ -/]*[@-~]', ''
    return (
        $plain -match '^\s*\[acpx\]\s+tokens:\s+.+$' -or
        $plain -match '^\s*\[acpx\]\s+cost:\s+.+$'
    )
}

function Invoke-Acpx {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$FilterQuietMetadata
    )
    if (-not $FilterQuietMetadata) {
        & $AcpxLauncher -Target acpx -TargetArgs $Arguments
        return
    }

    # acpx quiet mode intentionally writes token/cost accounting metadata to
    # stderr. Merge once so callers see a single final answer, suppress only
    # those two exact upstream metadata shapes, and keep every other error.
    $priorErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $records = @(& $AcpxLauncher -Target acpx -TargetArgs $Arguments 2>&1)
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    }
    finally {
        $ErrorActionPreference = $priorErrorAction
    }

    $realStderr = [Collections.Generic.List[string]]::new()
    foreach ($record in $records) {
        if ($record -is [Management.Automation.ErrorRecord]) {
            $line = [string]$record
            if (-not (Test-AcpxQuietMetadataLine -Line $line)) { $realStderr.Add($line) }
            continue
        }
        Write-Output $record
    }
    if ($exitCode -ne 0) {
        $detail = if ($realStderr.Count -gt 0) { $realStderr -join ' | ' } else { 'no stderr detail' }
        throw "XINAO_GROK_ACP_QUIET_FAILED: exit=$exitCode detail=$detail"
    }
    foreach ($line in $realStderr) { [Console]::Error.WriteLine($line) }
}

function Ensure-Session {
    $result = Invoke-Acpx -Arguments ($common + @('grok-build', 'sessions', 'ensure', '--name', $Session))
    if ($LASTEXITCODE -ne 0) { throw "XINAO_GROK_ACP_ENSURE_FAILED: $LASTEXITCODE" }
    return $result
}

function Invoke-PromptTurn {
    if ($PromptFile -eq '' -and $Prompt -eq '') {
        throw 'XINAO_GROK_ACP_PROMPT_REQUIRED'
    }
    [void](Ensure-Session)
    $ownedPrompt = $false
    $resolvedPrompt = $PromptFile
    if ($resolvedPrompt -eq '') {
        $promptDir = Join-Path $AcpxHome 'prompts'
        [void][IO.Directory]::CreateDirectory($promptDir)
        $resolvedPrompt = Join-Path $promptDir (([guid]::NewGuid().ToString('N')) + '.txt')
        [IO.File]::WriteAllText($resolvedPrompt, $Prompt, [Text.UTF8Encoding]::new($false))
        $ownedPrompt = $true
    }
    $resolvedPrompt = [IO.Path]::GetFullPath($resolvedPrompt)
    if (-not (Test-Path -LiteralPath $resolvedPrompt -PathType Leaf)) {
        throw "XINAO_GROK_ACP_PROMPT_FILE_MISSING: $resolvedPrompt"
    }
    try {
        $arguments = $safePromptCommon + @('grok-build', '-s', $Session, '--file', $resolvedPrompt)
        Invoke-Acpx -Arguments $arguments -FilterQuietMetadata
    }
    finally {
        if ($ownedPrompt) { Remove-Item -LiteralPath $resolvedPrompt -Force -ErrorAction SilentlyContinue }
    }
}

switch ($Action) {
    'ensure' {
        Ensure-Session
        break
    }
    'submit' {
        Invoke-PromptTurn
        break
    }
    'run' {
        Invoke-PromptTurn
        break
    }
    'status' {
        Invoke-Acpx -Arguments ($common + @('grok-build', '-s', $Session, 'status'))
        break
    }
    'cancel' {
        Invoke-Acpx -Arguments ($common + @('grok-build', '-s', $Session, 'cancel'))
        break
    }
    'history' {
        Invoke-Acpx -Arguments ($common + @('grok-build', 'sessions', 'history', $Session, '--limit', [string]$HistoryLimit))
        break
    }
    'close' {
        Invoke-Acpx -Arguments ($common + @('grok-build', 'sessions', 'close', $Session))
        break
    }
    'raw' {
        Invoke-Acpx -Arguments ($common + $RawArgs)
        break
    }
}
