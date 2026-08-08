#Requires -Version 5.1

$script:PrimeParitySourceRoot = Split-Path -Parent $PSScriptRoot
$script:PrimeParityRuntimeRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\prime-agent\parity-test\codex-compatible'
$script:PrimeParityPrimeRoot = 'D:\XINAO_RESEARCH_RUNTIME\tools\prime-agent\0.7.0'
$script:PrimeParityPrimeCommand = Join-Path $script:PrimeParityPrimeRoot 'prime-agent.cmd'
$script:PrimeParitySocket = '\\.\pipe\prime-agent-local-cognition-account-b'
$script:PrimeParitySRoot = 'E:\XINAO_RESEARCH_WORKSPACES\S'
$script:PrimeParityOldIsland = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island'
$script:PrimeParityOldProfile = 'D:\XINAO_RESEARCH_RUNTIME\state\prime-agent\profiles\account-b'
$script:PrimeParityMutexName = 'Local\XinaoPrimeLocalCognitionAccountB'
$script:PrimeParityNode = (Get-Command node.exe -ErrorAction Stop).Source
$script:PrimeParityDaemonCommand = Join-Path $PSScriptRoot 'prime-daemon-command.mjs'
$script:PrimeParityDaemonStop = Join-Path $PSScriptRoot 'Stop-PrimeParityDaemon.mjs'

function Read-PrimeParityJson {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "PRIME_PARITY_JSON_MISSING: $Path"
    }
    Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json
}

function Write-PrimeParityJsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value,
        [int]$Depth = 12
    )
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Path.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()).tmp"
    $Value | ConvertTo-Json -Depth $Depth | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Get-PrimeParityDaemonSessions {
    $output = @(& $script:PrimeParityNode $script:PrimeParityDaemonCommand list --socket $script:PrimeParitySocket 2>$null)
    if ($LASTEXITCODE -ne 0 -or $output.Count -eq 0) { return @() }
    $response = ($output -join [Environment]::NewLine) | ConvertFrom-Json
    if ($response.success -ne $true) { return @() }
    @($response.data.sessions)
}

function Get-PrimeParityTopLevelSessions {
    @(Get-PrimeParityDaemonSessions | Where-Object {
        [string]$_.runtimeKind -eq 'top-level' -or [string]::IsNullOrWhiteSpace([string]$_.parentSessionId)
    })
}

function Get-PrimeParityConversationBinding {
    $path = Join-Path $script:PrimeParityRuntimeRoot 'conversation-binding.json'
    $binding = Read-PrimeParityJson -Path $path
    $sessionFile = [System.IO.Path]::GetFullPath([string]$binding.session_file)
    if (-not (Test-Path -LiteralPath $sessionFile -PathType Leaf)) {
        throw "PRIME_PARITY_SESSION_FILE_MISSING: $sessionFile"
    }
    $header = (Get-Content -LiteralPath $sessionFile -TotalCount 1 -Encoding UTF8) | ConvertFrom-Json
    if ($header.type -ne 'session' -or [string]$header.id -ne [string]$binding.durable_session_id) {
        throw "PRIME_PARITY_SESSION_IDENTITY_MISMATCH: $sessionFile"
    }
    $binding
}

function Get-PrimeParityExactLiveSession {
    param([Parameter(Mandatory)]$Conversation)
    $matches = @(Get-PrimeParityTopLevelSessions | Where-Object {
        [string]$_.sessionId -eq [string]$Conversation.durable_session_id -and
        [System.IO.Path]::GetFullPath([string]$_.sessionFile) -eq [System.IO.Path]::GetFullPath([string]$Conversation.session_file)
    })
    if ($matches.Count -gt 1) { throw 'PRIME_PARITY_DUPLICATE_LIVE_SESSION_IDENTITY' }
    if ($matches.Count -eq 1) { return $matches[0] }
    $null
}

function Assert-PrimeParityIdle {
    param([Parameter(Mandatory)]$Session)
    $queued = [int]($Session.sessionActions.queuedCount)
    $busy = (
        [string]$Session.activity -ne 'idle' -or
        $Session.isStreaming -eq $true -or
        $Session.isCompacting -eq $true -or
        $Session.isBashRunning -eq $true -or
        $Session.hasRunningRlmChildren -eq $true -or
        $Session.isRunningTools -eq $true -or
        [int]$Session.unfinishedActionCount -gt 0 -or
        $queued -gt 0
    )
    if ($busy) {
        throw "PRIME_PARITY_SESSION_NOT_IDLE: activity=$($Session.activity) streaming=$($Session.isStreaming) tools=$($Session.isRunningTools) children=$($Session.hasRunningRlmChildren) queued=$queued unfinished=$($Session.unfinishedActionCount)"
    }
}

function Assert-PrimeParityConversationTreeIdle {
    param([Parameter(Mandatory)]$Conversation)
    $sessions = @(Get-PrimeParityDaemonSessions)
    $top = @($sessions | Where-Object {
        [string]$_.runtimeKind -eq 'top-level' -or [string]::IsNullOrWhiteSpace([string]$_.parentSessionId)
    })
    if ($top.Count -gt 0) {
        $exactTop = @($top | Where-Object {
            [string]$_.sessionId -eq [string]$Conversation.durable_session_id -and
            [System.IO.Path]::GetFullPath([string]$_.sessionFile) -eq [System.IO.Path]::GetFullPath([string]$Conversation.session_file)
        })
        if ($exactTop.Count -ne 1) { throw 'PRIME_PARITY_DAEMON_TREE_IDENTITY_MISMATCH' }
    }
    $busy = @($sessions | Where-Object {
        [string]$_.activity -ne 'idle' -or
        $_.isStreaming -eq $true -or
        $_.isCompacting -eq $true -or
        $_.isBashRunning -eq $true -or
        $_.hasRunningRlmChildren -eq $true -or
        $_.isRunningTools -eq $true -or
        [int]$_.unfinishedActionCount -gt 0 -or
        [int]$_.sessionActions.queuedCount -gt 0
    })
    if ($busy.Count -gt 0) {
        $summary = @($busy | ForEach-Object { "$($_.id):$($_.runtimeKind):$($_.activity):stream=$($_.isStreaming):tools=$($_.isRunningTools)" }) -join ','
        throw "PRIME_PARITY_CONVERSATION_TREE_NOT_IDLE: $summary"
    }
}

function Stop-PrimeParityExactDaemon {
    $output = @(& $script:PrimeParityNode $script:PrimeParityDaemonStop $script:PrimeParityPrimeRoot $script:PrimeParitySocket 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "PRIME_PARITY_DAEMON_STOP_FAILED: $($output -join ' ')"
    }
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        if (@(Get-PrimeParityDaemonSessions).Count -eq 0) { return }
        Start-Sleep -Milliseconds 125
    }
    throw 'PRIME_PARITY_DAEMON_DID_NOT_STOP'
}

function Test-PrimeParityAuth {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        $auth = Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json
        $provider = $auth.'openai-codex'
        return (
            $null -ne $provider -and
            [string]$provider.type -eq 'oauth' -and
            -not [string]::IsNullOrWhiteSpace([string]$provider.access) -and
            -not [string]::IsNullOrWhiteSpace([string]$provider.refresh) -and
            -not [string]::IsNullOrWhiteSpace([string]$provider.accountId)
        )
    } catch { return $false }
}

function Get-PrimeParityAuthAccountId {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-PrimeParityAuth -Path $Path)) { return $null }
    $auth = Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json
    [string]$auth.'openai-codex'.accountId
}

function Get-PrimeParityActiveAccount {
    $pointer = Read-PrimeParityJson -Path (Join-Path $script:PrimeParityRuntimeRoot 'active-account.json')
    $bindingPath = Join-Path $script:PrimeParityRuntimeRoot ("bindings\{0}.json" -f [string]$pointer.account_id)
    $binding = Read-PrimeParityJson -Path $bindingPath
    if ([string]$binding.account_id -ne [string]$pointer.account_id) {
        throw 'PRIME_PARITY_ACTIVE_ACCOUNT_BINDING_MISMATCH'
    }
    if ([string]$binding.state -ne 'verified') {
        throw "PRIME_PARITY_ACCOUNT_UNCONFIGURED: $($binding.account_id)"
    }
    if (-not (Test-PrimeParityAuth -Path ([string]$binding.profile_auth_path))) {
        throw "PRIME_PARITY_ACCOUNT_AUTH_INVALID: $($binding.account_id)"
    }
    $binding
}

function New-PrimeParityMutex {
    param([int]$TimeoutMilliseconds = 20000)
    $mutex = [System.Threading.Mutex]::new($false,$script:PrimeParityMutexName)
    try {
        $held = $mutex.WaitOne($TimeoutMilliseconds)
    } catch [System.Threading.AbandonedMutexException] {
        $held = $true
    }
    if (-not $held) {
        $mutex.Dispose()
        throw 'PRIME_PARITY_EXISTING_TUI_DID_NOT_RELEASE_LIFETIME_MUTEX'
    }
    $mutex
}

function Clear-PrimeParityInheritedEnvironment {
    Get-ChildItem Env: | Where-Object { $_.Name -like 'PRIME_AGENT_INTERNAL_*' } | ForEach-Object {
        Remove-Item -LiteralPath ("Env:\" + $_.Name) -ErrorAction SilentlyContinue
    }
    foreach ($name in @('OPENAI_API_KEY','ANTHROPIC_API_KEY','PRIME_API_KEY','DEEPSEEK_API_KEY','GEMINI_API_KEY','OPENROUTER_API_KEY')) {
        Remove-Item -LiteralPath "Env:\$name" -ErrorAction SilentlyContinue
    }
}

function Get-PrimeParityFileRecord {
    param([Parameter(Mandatory)][string]$Path)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    [ordered]@{
        path = $item.FullName
        length = $item.Length
        last_write_time_utc = $item.LastWriteTimeUtc.ToString('o')
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $item.FullName).Hash
    }
}
