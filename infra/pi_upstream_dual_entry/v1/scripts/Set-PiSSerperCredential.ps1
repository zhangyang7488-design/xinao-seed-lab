#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$SourcePath = 'C:\Users\xx363\私钥\serper-key.txt',
    [string]$AgentDir = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s',
    [switch]$SkipConnectionTest
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
    throw 'PI_SERPER_CREDENTIAL_SOURCE_MISSING'
}

$activeRoots = [ordered]@{
    'prime-s' = [IO.Path]::GetFullPath((Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s'))
    'prime-b' = [IO.Path]::GetFullPath((Join-Path $script:PiDualEntryStateRoot 'profiles\prime-b'))
}
$labRoot = [IO.Path]::GetFullPath((Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
$targetRoot = [IO.Path]::GetFullPath($AgentDir)
$activeProfile = @($activeRoots.Keys | Where-Object { [string]::Equals($targetRoot,$activeRoots[$_],[StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1)
$isActiveTarget = $activeProfile.Count -eq 1
$isLabTarget = ($targetRoot + [IO.Path]::DirectorySeparatorChar).StartsWith($labRoot,[StringComparison]::OrdinalIgnoreCase)
if (-not $isActiveTarget -and -not $isLabTarget) {
    throw "PI_SERPER_TARGET_OUTSIDE_MANAGED_PROFILE: $targetRoot"
}
if ($SkipConnectionTest -and $isActiveTarget) {
    throw 'PI_SERPER_ACTIVE_PROFILE_REQUIRES_PROVIDER_PROBE'
}
if (-not (Test-Path -LiteralPath $targetRoot -PathType Container)) {
    throw "PI_SERPER_TARGET_MISSING: $targetRoot"
}

$candidateValues = @(
    Get-Content -LiteralPath $SourcePath -Encoding UTF8 |
        ForEach-Object { ([string]$_).Trim() } |
        Where-Object { $_ -match '^[A-Za-z0-9_.-]{32,256}$' }
)
if ($candidateValues.Count -ne 1) {
    throw "PI_SERPER_CREDENTIAL_AMBIGUOUS: candidate_count=$($candidateValues.Count)"
}
$apiKey = [string]$candidateValues[0]

$providerStatus = 'unverified'
$statusCode = $null
if (-not $SkipConnectionTest) {
    try {
        $body = @{ q = 'OpenAI official'; num = 1 } | ConvertTo-Json -Compress
        $response = Invoke-WebRequest -UseBasicParsing -Uri 'https://google.serper.dev/search' -Method Post -Headers @{
            'X-API-KEY' = $apiKey
            'Content-Type' = 'application/json'
        } -Body $body -TimeoutSec 30
        $statusCode = [int]$response.StatusCode
        if ($statusCode -ne 200) {
            throw "PI_SERPER_PROVIDER_UNEXPECTED_STATUS: status=$statusCode"
        }
        $providerStatus = 'accepted'
    } catch {
        if ($_.Exception.Response) {
            try { $statusCode = [int]$_.Exception.Response.StatusCode } catch { $statusCode = $null }
        }
        if ($statusCode -in @(401,403)) { throw "PI_SERPER_AUTH_REJECTED: status=$statusCode" }
        if ($statusCode -in @(402,429)) { throw "PI_SERPER_QUOTA_REJECTED: status=$statusCode" }
        throw "PI_SERPER_PROVIDER_PROBE_FAILED: status=$statusCode"
    }
}

# Probe before persistence so a rejected credential never replaces a working native store.
$credentialPath = Join-Path $targetRoot 'credentials\serper.json'
Write-PiDualEntryJsonAtomic -Path $credentialPath -Value ([ordered]@{
    schema = 'xinao.pi_serper_credential.v1'
    provider = 'serper'
    enabled = $true
    apiKey = $apiKey
})

if ($isLabTarget) {
    $labManifestPath = Join-Path $targetRoot 'pi-s-body-lab.json'
    if (Test-Path -LiteralPath $labManifestPath -PathType Leaf) {
        try { $labManifest = Get-Content -Raw -LiteralPath $labManifestPath -Encoding UTF8 | ConvertFrom-Json }
        catch { throw "PI_SERPER_LAB_MANIFEST_INVALID: $labManifestPath" }
        if (
            [string]$labManifest.schema -ne 'xinao.pi_s_body_lab.v1' -or
            -not [string]::Equals([IO.Path]::GetFullPath([string]$labManifest.agent_dir),$targetRoot,[StringComparison]::OrdinalIgnoreCase)
        ) {
            throw "PI_SERPER_LAB_MANIFEST_IDENTITY_MISMATCH: $labManifestPath"
        }
        $labManifest.serper_credential_stored = $true
        $labManifest.serper_provider_status = $providerStatus
        $labManifest.serper_status_code = $statusCode
        $labManifest | Add-Member -NotePropertyName credential_updated_at -NotePropertyValue ([DateTimeOffset]::Now.ToString('o')) -Force
        Write-PiDualEntryJsonAtomic -Path $labManifestPath -Value $labManifest
    }
}

[pscustomobject]@{
    schema = 'xinao.pi_serper_credential_receipt.v1'
    profile = $(if ($isActiveTarget) { [string]$activeProfile[0] } else { 'prime-s-body-lab' })
    credential_path = $credentialPath
    credential_stored = $true
    credential_length = $apiKey.Length
    provider_status = $providerStatus
    status_code = $statusCode
    source_path_persisted_as_runtime_dependency = $false
}
