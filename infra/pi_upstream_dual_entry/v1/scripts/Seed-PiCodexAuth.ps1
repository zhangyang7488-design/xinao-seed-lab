#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('prime-b','prime-s')][string[]]$Profile = @('prime-b','prime-s'),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-JwtExpiryMilliseconds {
    param([Parameter(Mandatory)][string]$Token)
    try {
        $part = $Token.Split('.')[1].Replace('-','+').Replace('_','/')
        while (($part.Length % 4) -ne 0) { $part += '=' }
        $payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($part)) | ConvertFrom-Json
        if ($null -ne $payload.exp) { return [long]$payload.exp * 1000 }
    } catch {}
    return 0L
}

function Get-NativeProviderFromCodexAuthPath {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "CODEX_AUTH_SOURCE_MISSING: $Path"
    }
    $source = Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json
    if (
        [string]::IsNullOrWhiteSpace([string]$source.tokens.access_token) -or
        [string]::IsNullOrWhiteSpace([string]$source.tokens.refresh_token) -or
        [string]::IsNullOrWhiteSpace([string]$source.tokens.account_id)
    ) {
        throw "CODEX_AUTH_SOURCE_INVALID: $Path"
    }
    [ordered]@{
        type = 'oauth'
        access = [string]$source.tokens.access_token
        refresh = [string]$source.tokens.refresh_token
        expires = Get-JwtExpiryMilliseconds -Token ([string]$source.tokens.access_token)
        accountId = [string]$source.tokens.account_id
    }
}

Assert-PiDualEntryBinary
$receipts = @()
foreach ($profileName in $Profile) {
    Initialize-PiDualEntryAccountBinding -Profile $profileName | Out-Null
    $spec = Get-PiDualEntrySpec -Profile $profileName
    $target = Join-Path $spec.AgentDir 'auth.json'

    $provider = Get-NativeProviderFromCodexAuthPath -Path $spec.CodexAuthSource
    $sourceKind = "$($spec.AccountSlot)-codex-native-oauth"

    $status = 'seeded-new-profile'
    if (Test-PiDualEntryAuth -Path $target) {
        $existingAccount = Get-PiDualEntryAuthAccountId -Path $target
        if ($existingAccount -eq [string]$provider.accountId) {
            $status = if ($Force) { 'refreshed-from-selected-codex' } else { 'kept-pi-owned-auth' }
        } else {
            $status = 'rebound-to-selected-account'
        }
    }

    if ($Force -or $status -in @('seeded-new-profile','rebound-to-selected-account')) {
        Write-PiDualEntryJsonAtomic -Path $target -Value ([ordered]@{'openai-codex' = $provider})
    }
    if (-not (Test-PiDualEntryAuth -Path $target)) {
        throw "PI_PROFILE_AUTH_WRITE_FAILED: profile=$profileName"
    }

    $accountHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes([string]$provider.accountId))).ToLowerInvariant()
    $receipts += [ordered]@{
        profile = $profileName
        account_slot = $spec.AccountSlot
        status = $status
        source_kind = $sourceKind
        target = $target
        auth_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
        account_id_sha256 = $accountHash
        secret_values_emitted = $false
    }
}
$receipts | ConvertTo-Json -Depth 6
