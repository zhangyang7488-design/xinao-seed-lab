#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('account-b','account-s')][string]$Account,
    [string]$PrimeAuthSource
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PrimeParity.Common.ps1')

$conversation = Get-PrimeParityConversationBinding
$live = Get-PrimeParityExactLiveSession -Conversation $conversation
if ($null -ne $live) {
    Assert-PrimeParityIdle -Session $live
    Assert-PrimeParityConversationTreeIdle -Conversation $conversation
    throw 'PRIME_PARITY_ACCOUNT_SWITCH_REQUIRES_CLOSED_TUI: close the idle Prime window, then switch and reopen the same test entry'
}

$bindingPath = Join-Path $script:PrimeParityRuntimeRoot "bindings\$Account.json"
$binding = Read-PrimeParityJson -Path $bindingPath
$authPath = [string]$binding.profile_auth_path
$sessionHashBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath ([string]$conversation.session_file)).Hash

if (-not [string]::IsNullOrWhiteSpace($PrimeAuthSource)) {
    $source = [System.IO.Path]::GetFullPath($PrimeAuthSource)
    if (-not (Test-PrimeParityAuth -Path $source)) { throw 'PRIME_PARITY_SUPPLIED_AUTH_IS_NOT_VALID_PRIME_OPENAI_CODEX_AUTH' }
    $sourceRoot = [System.IO.Path]::GetPathRoot($source)
    $targetRoot = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($authPath))
    if ($sourceRoot -ne $targetRoot) { throw 'PRIME_PARITY_AUTH_HARDLINK_REQUIRES_SAME_VOLUME' }
    if (Test-Path -LiteralPath $authPath -PathType Leaf) {
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $authPath).Hash -ne (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash) {
            throw 'PRIME_PARITY_TARGET_AUTH_ALREADY_EXISTS_WITH_DIFFERENT_IDENTITY'
        }
    } else {
        New-Item -ItemType HardLink -Path $authPath -Target $source | Out-Null
    }
    $binding.auth_source_path = $source
    $binding.auth_transport = 'same-volume-hardlink'
}

if (-not (Test-PrimeParityAuth -Path $authPath)) {
    throw "PRIME_PARITY_ACCOUNT_SLOT_UNCONFIGURED: $Account has no verified Prime-format auth source"
}
if ($Account -eq 'account-s') {
    $accountB = Read-PrimeParityJson -Path (Join-Path $script:PrimeParityRuntimeRoot 'bindings\account-b.json')
    $bIdentity = Get-PrimeParityAuthAccountId -Path ([string]$accountB.profile_auth_path)
    $sIdentity = Get-PrimeParityAuthAccountId -Path $authPath
    if ($sIdentity -eq $bIdentity) { throw 'PRIME_PARITY_ACCOUNT_S_AUTH_RESOLVES_TO_ACCOUNT_B' }
}
$binding.state = 'verified'
$binding.updated_at = (Get-Date).ToString('o')
Write-PrimeParityJsonAtomic -Path $bindingPath -Value $binding
Write-PrimeParityJsonAtomic -Path (Join-Path $script:PrimeParityRuntimeRoot 'active-account.json') -Value ([ordered]@{
    schema = 'xinao.prime_codex_parity.active_account.v1'
    account_id = $Account
    updated_at = (Get-Date).ToString('o')
    effect = 'account_binding_only_no_session_or_behavior_copy'
})

$sessionHashAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath ([string]$conversation.session_file)).Hash
if ($sessionHashAfter -ne $sessionHashBefore) { throw 'PRIME_PARITY_ACCOUNT_SWITCH_MUTATED_CONVERSATION' }
[ordered]@{
    schema = 'xinao.prime_codex_parity.account_switch_receipt.v1'
    status = 'verified'
    active_account = $Account
    durable_session_id = [string]$conversation.durable_session_id
    session_unchanged = $true
    behavior_core_copied = $false
    secret_material_printed = $false
    takes_effect = 'next exact resume through prime S.lnk'
} | ConvertTo-Json -Depth 8
