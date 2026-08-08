#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$SourcePath = 'C:\Users\xx363\私钥\DeepSeek-api-key-active.txt',
    [string]$AgentDir = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSDeepSeekPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

$target = Get-NormalizedPiSDeepSeekPath -Path $AgentDir
$activeTargets = [ordered]@{
    'prime-s' = Get-NormalizedPiSDeepSeekPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s')
    'prime-b' = Get-NormalizedPiSDeepSeekPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-b')
}
$labParents = @(
    Get-NormalizedPiSDeepSeekPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
    Get-NormalizedPiSDeepSeekPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-b')
)
$targetParent = Get-NormalizedPiSDeepSeekPath -Path (Split-Path -Parent $target)
$activeProfile = @($activeTargets.Keys | Where-Object { $target -ieq $activeTargets[$_] } | Select-Object -First 1)
if ($activeProfile.Count -ne 1 -and $targetParent -notin $labParents) {
    throw "PI_DEEPSEEK_TARGET_OUTSIDE_MANAGED_PROFILE: $target"
}
if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
    throw "PI_DEEPSEEK_CREDENTIAL_SOURCE_MISSING: $SourcePath"
}

$apiKey = (Get-Content -Raw -LiteralPath $SourcePath -Encoding UTF8).Trim()
if ([string]::IsNullOrWhiteSpace($apiKey) -or $apiKey -match '\s') {
    throw 'PI_DEEPSEEK_CREDENTIAL_SOURCE_INVALID_SHAPE'
}

try {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri 'https://api.deepseek.com/models' -Headers @{
            Authorization = "Bearer $apiKey"
            Accept = 'application/json'
        } -Method Get -TimeoutSec 30
    } catch {
        $statusCode = $null
        if ($null -ne $_.Exception.Response) {
            try { $statusCode = [int]$_.Exception.Response.StatusCode } catch {}
        }
        if ($statusCode -in @(401,403)) { throw "PI_DEEPSEEK_AUTH_REJECTED: status=$statusCode" }
        if ($statusCode -eq 429) { throw 'PI_DEEPSEEK_QUOTA_REJECTED: status=429' }
        throw "PI_DEEPSEEK_PROVIDER_PROBE_FAILED: status=$statusCode"
    }

    $payload = $response.Content | ConvertFrom-Json
    $modelIds = @($payload.data | ForEach-Object { [string]$_.id } | Sort-Object -Unique)
    foreach ($requiredModel in @('deepseek-v4-flash','deepseek-v4-pro')) {
        if ($requiredModel -notin $modelIds) {
            throw "PI_DEEPSEEK_REQUIRED_MODEL_MISSING: $requiredModel"
        }
    }

    New-Item -ItemType Directory -Force -Path $target | Out-Null
    $authPath = Join-Path $target 'auth.json'
    $merged = [ordered]@{}
    if (Test-Path -LiteralPath $authPath -PathType Leaf) {
        try {
            $existing = Get-Content -Raw -LiteralPath $authPath -Encoding UTF8 | ConvertFrom-Json
        } catch {
            throw "PI_DEEPSEEK_AUTH_STORE_INVALID: $authPath"
        }
        foreach ($property in @($existing.PSObject.Properties)) {
            if ($property.Name -cne 'deepseek') { $merged[$property.Name] = $property.Value }
        }
    }
    $preservedProviders = @($merged.Keys)
    $merged['deepseek'] = [ordered]@{type='api_key';key=$apiKey}
    Write-PiDualEntryJsonAtomic -Path $authPath -Value $merged

    $readback = Get-Content -Raw -LiteralPath $authPath -Encoding UTF8 | ConvertFrom-Json
    if (
        [string]$readback.deepseek.type -cne 'api_key' -or
        [string]$readback.deepseek.key -cne $apiKey
    ) {
        throw 'PI_DEEPSEEK_NATIVE_CREDENTIAL_READBACK_FAILED'
    }
    foreach ($providerName in $preservedProviders) {
        if ($null -eq $readback.PSObject.Properties[$providerName]) {
            throw "PI_DEEPSEEK_EXISTING_PROVIDER_LOST: $providerName"
        }
    }

    [pscustomobject]@{
        schema = 'xinao.pi_s_deepseek_credential.v1'
        profile = $(if ($activeProfile.Count -eq 1) { [string]$activeProfile[0] } else { 'body-lab' })
        agent_dir = $target
        native_auth_store = $authPath
        credential_stored = $true
        provider_status = 'verified'
        status_code = [int]$response.StatusCode
        model_ids = $modelIds
        existing_providers_preserved = @($preservedProviders)
        source_path_persisted_as_runtime_dependency = $false
        secret_values_emitted = $false
    } | ConvertTo-Json -Depth 5
} finally {
    $apiKey = $null
}
