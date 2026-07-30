#Requires -Version 7.0
<#
.SYNOPSIS
  Fresh-process readback of stable D: egress receipts for a later live-seal validator.
.DESCRIPTION
  Reads posture/negative/canary/cleanup/pin receipts under the state root, hashes them,
  and writes fresh_process_readback.v1.json. With -FreshProcess, re-launches this script
  in a new pwsh process (no WSL). Never mutates Docker. Never claims verified/completion.
.EXAMPLE
  pwsh -File .\Owner-FreshProcessReadback.ps1
  pwsh -File .\Owner-FreshProcessReadback.ps1 -FreshProcess
#>
[CmdletBinding()]
param(
    [string]$StateRoot = '',
    [string]$PackageRoot = '',
    [string]$ResultsPath = '',
    [switch]$FreshProcess,
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'XinaoEgressOwner.Common.ps1')

if ([string]::IsNullOrWhiteSpace($PackageRoot)) { $PackageRoot = Get-XinaoEgressPackageRoot }
if ([string]::IsNullOrWhiteSpace($StateRoot)) { $StateRoot = Get-XinaoDefaultStateRoot }
$paths = Get-XinaoEgressPathContract -PackageRoot $PackageRoot -StateRoot $StateRoot
if ([string]::IsNullOrWhiteSpace($ResultsPath)) { $ResultsPath = $paths.fresh_process_readback_path }

if ($FreshProcess) {
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $self = $MyInvocation.MyCommand.Path
    if ([string]::IsNullOrWhiteSpace($self)) {
        $self = Join-Path $PSScriptRoot 'Owner-FreshProcessReadback.ps1'
    }
    $argList = @(
        '-NoProfile',
        '-File', $self,
        '-StateRoot', $StateRoot,
        '-PackageRoot', $PackageRoot,
        '-ResultsPath', $ResultsPath
    )
    if ($PreflightOnly) { $argList += '-PreflightOnly' }
    $tmpOut = Join-Path $paths.temp_root ("fresh_readback_stdout_{0}.json" -f [Guid]::NewGuid().ToString('N'))
    Ensure-XinaoDirectory -Path $paths.temp_root | Out-Null
    $proc = Start-Process -FilePath $pwsh -ArgumentList $argList -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $tmpOut -RedirectStandardError ($tmpOut + '.err')
    if (Test-Path -LiteralPath $tmpOut -PathType Leaf) {
        Get-Content -LiteralPath $tmpOut -Raw | Write-Output
    }
    exit $proc.ExitCode
}

try {
    Ensure-XinaoDirectory -Path $paths.state_root | Out-Null

    $watch = @(
        [ordered]@{ key = 'posture'; path = $paths.posture_path }
        [ordered]@{ key = 'live_seal'; path = $paths.live_seal_path }
        [ordered]@{ key = 'negative_suite_receipt'; path = $paths.negative_suite_receipt_path }
        [ordered]@{ key = 'engineering_canary_receipt'; path = $paths.engineering_canary_receipt_path }
        [ordered]@{ key = 'cleanup_receipt'; path = $paths.cleanup_receipt_path }
        [ordered]@{ key = 'image_pin_readback'; path = $paths.image_pin_readback_path }
        [ordered]@{ key = 'provision_receipt'; path = $paths.provision_receipt_path }
        [ordered]@{ key = 'image_pin'; path = $paths.image_pin_path }
        [ordered]@{ key = 'allowlist'; path = $paths.allowlist_path }
    )

    $artifacts = [ordered]@{}
    $missing = @()
    $present = @()
    foreach ($item in $watch) {
        $p = [System.IO.Path]::GetFullPath([string]$item.path)
        $exists = Test-Path -LiteralPath $p -PathType Leaf
        $entry = [ordered]@{
            path   = $p
            exists = $exists
            sha256 = $null
            bytes  = $null
            status = $null
        }
        if ($exists) {
            $entry.sha256 = Get-XinaoFileSha256Hex -Path $p
            $entry.bytes = (Get-Item -LiteralPath $p).Length
            try {
                $obj = Read-XinaoJsonFile -Path $p
                if ($obj.PSObject.Properties.Name -contains 'status') {
                    $entry.status = [string]$obj.status
                }
                if ($obj.PSObject.Properties.Name -contains 'provider_egress_runtime_verified') {
                    $entry.provider_egress_runtime_verified = [bool]$obj.provider_egress_runtime_verified
                }
                if ($obj.PSObject.Properties.Name -contains 'completion_claim_allowed') {
                    $entry.completion_claim_allowed = [bool]$obj.completion_claim_allowed
                }
                $blob = ConvertTo-XinaoStrictJson -InputObject $obj
                if (Test-XinaoSecretLeakText -Text $blob) {
                    throw "SECRET_LEAK_IN_ARTIFACT:$($item.key)"
                }
            } catch {
                if ([string]$_.Exception.Message -like 'SECRET_LEAK*') { throw }
                $entry.parse_error = [string]$_.Exception.Message
            }
            $present += $item.key
        } else {
            $missing += $item.key
        }
        $artifacts[[string]$item.key] = $entry
    }

    $status = if ($PreflightOnly) {
        'planned'
    } elseif ($present.Count -eq 0) {
        'partial'
    } else {
        'observed'
    }

    $receipt = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_fresh_process_readback.v1' -Status $status -Extra @{
        mode                    = $(if ($PreflightOnly) { 'preflight_only' } else { 'readback' })
        state_root              = $paths.state_root
        package_root            = $paths.package_root
        path_contract           = $paths
        artifacts               = $artifacts
        present_keys            = $present
        missing_keys            = $missing
        process_id              = $PID
        process_path            = [Environment]::ProcessPath
        powershell_version      = $PSVersionTable.PSVersion.ToString()
        docker_mutated          = $false
        live_seal_consumer_ready_claim = $false
        note                    = 'Fresh-process readback for a separate platform-neutral live-seal validator. Does not seal verified=true.'
    }
    Assert-XinaoNoSecretLeak -Object $receipt
    $written = Write-XinaoJsonFile -Path $ResultsPath -Object $receipt
    Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                status                           = $status.ToUpperInvariant()
                receipt_path                     = $written
                present_keys                     = $present
                missing_keys                     = $missing
                provider_egress_runtime_verified = $false
                completion_claim_allowed         = $false
                docker_mutated                   = $false
            }))
    exit 0
}
catch {
    $msg = [string]$_.Exception.Message
    $receipt = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_fresh_process_readback.v1' -Status 'failed' -Extra @{
        mode        = 'error'
        reason_code = $msg
        error       = $msg
        docker_mutated = $false
    }
    $written = Write-XinaoJsonFile -Path $ResultsPath -Object $receipt
    Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                status       = 'FAILED'
                reason_code  = $msg
                receipt_path = $written
            }))
    exit 2
}
