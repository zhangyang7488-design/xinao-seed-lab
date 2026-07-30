#Requires -Version 7.0
<#
.SYNOPSIS
  Credential-safe provider endpoint discovery scaffold (Windows Owner carrier).
.DESCRIPTION
  Writes a redacted scaffold receipt and README under the state/discovery directory.
  Never reads auth.json or API keys. Never sets verified=true. Never calls research().
#>
[CmdletBinding()]
param(
    [string]$OutDir = '',
    [string]$StateRoot = '',
    [string]$PackageRoot = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'XinaoEgressOwner.Common.ps1')

if ([string]::IsNullOrWhiteSpace($PackageRoot)) { $PackageRoot = Get-XinaoEgressPackageRoot }
if ([string]::IsNullOrWhiteSpace($StateRoot)) { $StateRoot = Get-XinaoDefaultStateRoot }
$paths = Get-XinaoEgressPathContract -PackageRoot $PackageRoot -StateRoot $StateRoot
if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $OutDir = Join-Path $paths.state_root 'discovery_capture'
}
$OutDir = [System.IO.Path]::GetFullPath($OutDir)
Ensure-XinaoDirectory -Path $OutDir | Out-Null

$readme = @'
1. From a non-researcher network, run one minimal authenticated grok call: --model grok-4.5, tool-free, max-turns 1.
2. Capture CONNECT host:443 targets via temporary logging proxy or engine flow log.
3. Redact Authorization, cookies, API keys, auth.json bytes before any file lands on disk.
4. Record DNS question names and CNAME chains; seal names, not transient IPs.
5. Build minimal dstdomain list; write allowlist.v1.json domains; re-run Owner-ProvisionEgress.ps1 -PreflightOnly.
6. Re-render squid config; run Owner-EngineeringCanary.ps1; only then consider live-seal.
7. Never set provider_egress_runtime_verified=true from this script.
8. Windows path: PowerShell 7 + Docker CLI + repository Python. No WSL distro required.
'@
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText((Join-Path $OutDir 'README.txt'), ($readme.TrimEnd() + [Environment]::NewLine), $utf8)

$scaffold = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_discovery_receipt.v1' -Status 'planned' -Extra @{
    mode                     = 'scaffold_only'
    observed_connect_hosts   = @()
    observed_ports           = @(443)
    websocket_upgrade_observed = $null
    redaction                = [ordered]@{
        authorization_headers_stripped = $true
        auth_json_bytes_forbidden      = $true
        api_keys_forbidden             = $true
    }
    next_step                = 'Owner fills observed_connect_hosts after redacted lab capture'
    docker_mutated           = $false
}
$receiptPath = Join-Path $OutDir 'discovery_receipt.v1.json'
Write-XinaoJsonFile -Path $receiptPath -Object $scaffold | Out-Null
Write-XinaoJsonFile -Path $paths.discovery_receipt_path -Object $scaffold | Out-Null

Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
            status                           = 'SCAFFOLD_READY'
            path                             = $OutDir
            receipt_path                     = $receiptPath
            provider_egress_runtime_verified = $false
            completion_claim_allowed         = $false
        }))
exit 0
