#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PrimeParity.Common.ps1')

$conversation = Get-PrimeParityConversationBinding
$account = Get-PrimeParityActiveAccount
$liveSessions = @(Get-PrimeParityTopLevelSessions)
if ($liveSessions.Count -gt 1) { throw "PRIME_PARITY_UNEXPECTED_DAEMON_SESSION_COUNT: $($liveSessions.Count)" }
if ($liveSessions.Count -eq 1) {
    $live = Get-PrimeParityExactLiveSession -Conversation $conversation
    if ($null -eq $live) { throw 'PRIME_PARITY_SOCKET_OWNS_A_DIFFERENT_CONVERSATION' }
    if ([System.IO.Path]::GetFullPath([string]$live.cwd) -eq [System.IO.Path]::GetFullPath($script:PrimeParitySRoot)) {
        Write-Host "Prime Codex parity test is already open on account $($account.account_id); no second TUI was started." -ForegroundColor Yellow
        exit 73
    }
    Assert-PrimeParityIdle -Session $live
    Assert-PrimeParityConversationTreeIdle -Conversation $conversation
    Write-Host 'The exact Prime conversation is idle; switching its shell from the current island to the Codex-compatible test.' -ForegroundColor Cyan
    Stop-PrimeParityExactDaemon
}

$mutex = New-PrimeParityMutex
$held = $true
try {
    Clear-PrimeParityInheritedEnvironment
    $shared = Join-Path $script:PrimeParityRuntimeRoot 'shared'
    $profile = [string]$account.profile_path
    $kernelVenv = Join-Path $shared 'kernel-venv'
    $kernelPython = Join-Path $kernelVenv 'Scripts\python.exe'
    $windowsCompat = Join-Path $shared 'windows-compat.cjs'
    $modelCatalogCompat = Join-Path $shared 'rlm-model-catalog-compat.cjs'
    $extension = Join-Path $script:PrimeParityRuntimeRoot 'extension\index.ts'
    foreach ($required in @($profile,$kernelPython,$windowsCompat,$modelCatalogCompat,$extension,[string]$conversation.session_file)) {
        if (-not (Test-Path -LiteralPath $required)) { throw "PRIME_PARITY_LAUNCH_REQUIRED_PATH_MISSING: $required" }
    }

    $env:PRIME_AGENT_CODING_AGENT_DIR = $profile
    $env:PRIME_AGENT_SESSION_DIR = [string]$conversation.session_dir
    $env:PRIME_AGENT_KERNEL_PYTHON = $kernelPython
    $env:PRIME_AGENT_KERNEL_VENV = $kernelVenv
    $env:PRIME_AGENT_CANDIDATE_OUTPUT_ROOT = Join-Path $script:PrimeParityRuntimeRoot 'candidate-output'
    $env:PRIME_AGENT_ISLAND_ID = 'codex-compatible-parity-test'
    $env:PRIME_AGENT_TRUST_EPOCH = '1'
    $env:PRIME_CODEX_PARITY_RUNTIME_ROOT = $script:PrimeParityRuntimeRoot
    $env:PRIME_CODEX_PARITY_OVERLAY_ROOT = Join-Path $script:PrimeParityRuntimeRoot 'overlay'
    $env:PRIME_CODEX_PARITY_CODEX_ROOT = [string]$account.canonical_codex_root
    $env:PRIME_CODEX_PARITY_ACCOUNT_HOME = [string]$account.codex_home
    $env:PRIME_CODEX_PARITY_S_ROOT = $script:PrimeParitySRoot
    $env:PRIME_CODEX_PARITY_PROBE = Join-Path $script:PrimeParityRuntimeRoot 'validation\before-agent-start-live.json'
    $env:CODEX_HOME = [string]$account.codex_home
    $env:RLM_DEPTH = '0'
    $env:RLM_MAX_DEPTH = '2'
    $env:PRIME_AGENT_ENABLE_RLM_CODEX_CATALOG_FALLBACK = '1'
    $env:NODE_OPTIONS = "--require=$windowsCompat --require=$modelCatalogCompat"
    $env:UV_LINK_MODE = 'copy'
    $env:PI_SKIP_VERSION_CHECK = '1'
    $env:PI_FULLSCREEN = '1'
    $env:XINAO_ACCOUNT_SLOT = [string]$account.account_id
    $env:XINAO_REPO = $script:PrimeParitySRoot
    $env:XINAO_RUNTIME = 'D:\XINAO_RESEARCH_RUNTIME'
    $env:Path = (@($script:PrimeParityPrimeRoot,'C:\Program Files\Git\bin') + @(
        $env:Path -split ';' | Where-Object { $_ -and $_ -ine $script:PrimeParityPrimeRoot -and $_ -ine 'C:\Program Files\Git\bin' }
    )) -join ';'

    $launchReceipt = [ordered]@{
        schema = 'xinao.prime_codex_parity.launch.v1'
        status = 'starting'
        durable_session_id = [string]$conversation.durable_session_id
        session_file = [string]$conversation.session_file
        session_copy_created = $false
        cwd = $script:PrimeParitySRoot
        account_id = [string]$account.account_id
        codex_home = [string]$account.codex_home
        profile = $profile
        provider = 'openai-codex'
        model = 'gpt-5.6-sol'
        thinking = 'max'
        daemon_socket = $script:PrimeParitySocket
        approval_review_agent_added = $false
        source_direction = 'codex_and_s_to_prime_private_overlay_only'
        started_at = (Get-Date).ToString('o')
    }
    Write-PrimeParityJsonAtomic -Path (Join-Path $script:PrimeParityRuntimeRoot 'launch\latest.json') -Value $launchReceipt

    Clear-Host
    Write-Host "Prime Codex-compatible test | $($account.display_name) | same durable conversation" -ForegroundColor Cyan
    Write-Host "Session: $($conversation.durable_session_id)" -ForegroundColor DarkGray
    Write-Host "Behavior: live Codex core + account hooks/memory + S + private Prime overlay" -ForegroundColor Green
    Write-Host 'Account binding is replaceable; conversation and behavior core are not copied.' -ForegroundColor Yellow
    Write-Host ''

    Set-Location -LiteralPath $script:PrimeParitySRoot
    & $script:PrimeParityPrimeCommand --daemon-socket $script:PrimeParitySocket --cwd $script:PrimeParitySRoot --session-dir ([string]$conversation.session_dir) --resume ([string]$conversation.session_file) --provider openai-codex --model gpt-5.6-sol --thinking max --no-extensions --extension $extension
    exit $LASTEXITCODE
} finally {
    try {
        $exact = Get-PrimeParityExactLiveSession -Conversation $conversation
        if ($null -ne $exact) { Stop-PrimeParityExactDaemon }
    } catch { Write-Warning $_.Exception.Message }
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
