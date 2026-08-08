#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PrimeParity.Common.ps1')

$conversation = Get-PrimeParityConversationBinding
$liveSessions = @(Get-PrimeParityTopLevelSessions)
if ($liveSessions.Count -gt 1) { throw "PRIME_PARITY_UNEXPECTED_DAEMON_SESSION_COUNT: $($liveSessions.Count)" }
if ($liveSessions.Count -eq 1) {
    $live = Get-PrimeParityExactLiveSession -Conversation $conversation
    if ($null -eq $live) { throw 'PRIME_PARITY_SOCKET_OWNS_A_DIFFERENT_CONVERSATION' }
    if ([System.IO.Path]::GetFullPath([string]$live.cwd) -eq [System.IO.Path]::GetFullPath([string]$conversation.original_cwd)) {
        Write-Host 'The original Prime mode is already open; no second TUI was started.' -ForegroundColor Yellow
        exit 73
    }
    Assert-PrimeParityIdle -Session $live
    Assert-PrimeParityConversationTreeIdle -Conversation $conversation
    Write-Host 'The exact conversation is idle; restoring its original Prime island shell.' -ForegroundColor Cyan
    Stop-PrimeParityExactDaemon
}

$mutex = New-PrimeParityMutex
$held = $true
try {
    Clear-PrimeParityInheritedEnvironment
    $profile = [string]$conversation.original_profile
    $workdir = [string]$conversation.original_cwd
    $kernelVenv = Join-Path $profile 'kernel-venv'
    $kernelPython = Join-Path $kernelVenv 'Scripts\python.exe'
    $windowsCompat = Join-Path $profile 'windows-compat.cjs'
    $modelCatalogCompat = Join-Path $profile 'rlm-model-catalog-compat.cjs'
    foreach ($required in @($profile,$workdir,$kernelPython,$windowsCompat,$modelCatalogCompat,[string]$conversation.session_file)) {
        if (-not (Test-Path -LiteralPath $required)) { throw "PRIME_PARITY_RESTORE_REQUIRED_PATH_MISSING: $required" }
    }

    $env:PRIME_AGENT_CODING_AGENT_DIR = $profile
    $env:PRIME_AGENT_SESSION_DIR = [string]$conversation.session_dir
    $env:PRIME_AGENT_KERNEL_PYTHON = $kernelPython
    $env:PRIME_AGENT_KERNEL_VENV = $kernelVenv
    $env:PRIME_AGENT_CANDIDATE_OUTPUT_ROOT = 'D:\XINAO_RESEARCH_RUNTIME\state\prime-agent\candidate-output\local-cognition-account-b'
    $env:PRIME_AGENT_ISLAND_ID = 'local-cognition-account-b'
    $env:PRIME_AGENT_TRUST_EPOCH = '2'
    $env:RLM_DEPTH = '0'
    $env:RLM_MAX_DEPTH = '2'
    $env:PRIME_AGENT_ENABLE_RLM_CODEX_CATALOG_FALLBACK = '1'
    $env:NODE_OPTIONS = "--require=$windowsCompat --require=$modelCatalogCompat"
    $env:UV_LINK_MODE = 'copy'
    $env:PI_SKIP_VERSION_CHECK = '1'
    $env:PI_FULLSCREEN = '1'
    $env:XINAO_ACCOUNT_SLOT = 'account-b-local-cognition'
    $env:XINAO_REPO = $workdir
    $env:XINAO_RUNTIME = 'D:\XINAO_RESEARCH_RUNTIME'
    $env:Path = (@($script:PrimeParityPrimeRoot,'C:\Program Files\Git\bin') + @(
        $env:Path -split ';' | Where-Object { $_ -and $_ -ine $script:PrimeParityPrimeRoot -and $_ -ine 'C:\Program Files\Git\bin' }
    )) -join ';'

    Write-PrimeParityJsonAtomic -Path (Join-Path $script:PrimeParityRuntimeRoot 'launch\restore-latest.json') -Value ([ordered]@{
        schema = 'xinao.prime_codex_parity.restore.v1'
        status = 'starting_original_mode'
        durable_session_id = [string]$conversation.durable_session_id
        session_file = [string]$conversation.session_file
        session_copy_created = $false
        cwd = $workdir
        profile = $profile
        account_id = 'account-b'
        started_at = (Get-Date).ToString('o')
    })

    Clear-Host
    Write-Host 'Prime current mode restored | Account B | same durable conversation' -ForegroundColor Cyan
    Write-Host "Session: $($conversation.durable_session_id)" -ForegroundColor DarkGray
    Write-Host "Workspace: $workdir"
    Write-Host ''
    Set-Location -LiteralPath $workdir
    & $script:PrimeParityPrimeCommand --daemon-socket $script:PrimeParitySocket --cwd $workdir --session-dir ([string]$conversation.session_dir) --resume ([string]$conversation.session_file) --provider openai-codex --model gpt-5.6-sol --thinking max
    exit $LASTEXITCODE
} finally {
    try {
        $exact = Get-PrimeParityExactLiveSession -Conversation $conversation
        if ($null -ne $exact) { Stop-PrimeParityExactDaemon }
    } catch { Write-Warning $_.Exception.Message }
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
