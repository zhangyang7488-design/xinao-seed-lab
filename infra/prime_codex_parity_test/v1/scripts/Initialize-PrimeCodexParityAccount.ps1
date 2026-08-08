#Requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory)][ValidateSet('account-s')][string]$Account)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PrimeParity.Common.ps1')

$conversation = Get-PrimeParityConversationBinding
$exactLive = Get-PrimeParityExactLiveSession -Conversation $conversation
if ($null -ne $exactLive) {
    Assert-PrimeParityConversationTreeIdle -Conversation $conversation
    throw 'PRIME_PARITY_ACCOUNT_LOGIN_REQUIRES_CLOSED_TUI'
}
$bindingPath = Join-Path $script:PrimeParityRuntimeRoot "bindings\$Account.json"
$binding = Read-PrimeParityJson -Path $bindingPath
$profile = [string]$binding.profile_path
$authPath = [string]$binding.profile_auth_path
if (Test-PrimeParityAuth -Path $authPath) {
    Write-Host 'This Prime account slot is already authenticated; no login TUI was started.' -ForegroundColor Green
    exit 0
}

Clear-PrimeParityInheritedEnvironment
$shared = Join-Path $script:PrimeParityRuntimeRoot 'shared'
$env:PRIME_AGENT_CODING_AGENT_DIR = $profile
$env:PRIME_AGENT_KERNEL_PYTHON = Join-Path $shared 'kernel-venv\Scripts\python.exe'
$env:PRIME_AGENT_KERNEL_VENV = Join-Path $shared 'kernel-venv'
$env:PRIME_AGENT_ISLAND_ID = 'codex-compatible-account-login'
$env:PI_SKIP_VERSION_CHECK = '1'
$env:NODE_OPTIONS = "--require=$(Join-Path $shared 'windows-compat.cjs') --require=$(Join-Path $shared 'rlm-model-catalog-compat.cjs')"
$env:CODEX_HOME = [string]$binding.codex_home

Write-Host 'Prime Account S authentication setup' -ForegroundColor Cyan
Write-Host 'Run /login, choose ChatGPT Plus/Pro (Codex), finish browser OAuth, then exit this no-session TUI.' -ForegroundColor Yellow
Write-Host 'No conversation or behavior core will be created or copied.' -ForegroundColor DarkGray
Set-Location -LiteralPath $script:PrimeParitySRoot
$loginSocket = '\\.\pipe\prime-codex-parity-account-login'
try {
    & $script:PrimeParityPrimeCommand --daemon-socket $loginSocket --cwd $script:PrimeParitySRoot --no-session --provider openai-codex --model gpt-5.6-sol --thinking max --no-extensions
} finally {
    try { $null = & $script:PrimeParityNode $script:PrimeParityDaemonStop $script:PrimeParityPrimeRoot $loginSocket 2>&1 } catch {}
}
if (-not (Test-PrimeParityAuth -Path $authPath)) { throw 'PRIME_PARITY_ACCOUNT_LOGIN_DID_NOT_PRODUCE_VALID_PRIME_AUTH' }

$accountB = Read-PrimeParityJson -Path (Join-Path $script:PrimeParityRuntimeRoot 'bindings\account-b.json')
if ((Get-PrimeParityAuthAccountId -Path $authPath) -eq (Get-PrimeParityAuthAccountId -Path ([string]$accountB.profile_auth_path))) {
    throw 'PRIME_PARITY_ACCOUNT_S_LOGIN_RESOLVES_TO_ACCOUNT_B'
}
$binding.auth_source_path = $authPath
$binding.auth_transport = 'profile-native-oauth'
$binding.state = 'verified'
$binding.updated_at = (Get-Date).ToString('o')
Write-PrimeParityJsonAtomic -Path $bindingPath -Value $binding
Write-Host 'Account S Prime authentication verified. The active binding is unchanged until Set-PrimeCodexParityAccount.ps1 is run.' -ForegroundColor Green
