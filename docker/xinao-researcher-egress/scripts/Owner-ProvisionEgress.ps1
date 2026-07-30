#Requires -Version 7.0
<#
.SYNOPSIS
  Owner-only provision of XINAO researcher egress networks/proxy on Windows Docker Desktop.
.DESCRIPTION
  Preflight: pin assert, allowlist load/render, compose safety (no host ports, no Dify reuse).
  Execute: docker compose up -d and write current_posture.v1.json with verified=false.
  -PreflightOnly / -WhatIf never mutate Docker. Empty allowlist is valid fail-closed topology.
  Does not seal live verification. Does not call research(). No WSL/Git Bash.
.EXAMPLE
  pwsh -File .\Owner-ProvisionEgress.ps1 -PreflightOnly
  pwsh -File .\Owner-ProvisionEgress.ps1 -WhatIf
#>
[CmdletBinding()]
param(
    [string]$StateRoot = '',
    [string]$TempRoot = '',
    [string]$PackageRoot = '',
    [string]$AllowlistPath = '',
    [string]$PythonPath = '',
    [switch]$PreflightOnly,
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'XinaoEgressOwner.Common.ps1')

if ([string]::IsNullOrWhiteSpace($PackageRoot)) { $PackageRoot = Get-XinaoEgressPackageRoot }
if ([string]::IsNullOrWhiteSpace($StateRoot)) { $StateRoot = Get-XinaoDefaultStateRoot }
if ([string]::IsNullOrWhiteSpace($TempRoot)) { $TempRoot = Get-XinaoDefaultTempRoot }
$paths = Get-XinaoEgressPathContract -PackageRoot $PackageRoot -StateRoot $StateRoot -TempRoot $TempRoot
if ([string]::IsNullOrWhiteSpace($AllowlistPath)) { $AllowlistPath = $paths.allowlist_path }
$AllowlistPath = [System.IO.Path]::GetFullPath($AllowlistPath)

function Write-ProvisionReceipt {
    param($Status, $Extra)
    $receipt = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_provision_receipt.v1' -Status $Status -Extra $Extra
    $written = Write-XinaoJsonFile -Path $paths.provision_receipt_path -Object $receipt
    $receipt | Add-Member -NotePropertyName receipt_path -NotePropertyValue $written -Force
    return $receipt
}

try {
    Ensure-XinaoDirectory -Path $paths.state_root | Out-Null
    Ensure-XinaoDirectory -Path $paths.temp_root | Out-Null

    $python = Resolve-XinaoPythonInterpreter -PackageRoot $PackageRoot -ExplicitPath $PythonPath
    $pin = Read-XinaoJsonFile -Path $paths.image_pin_path
    $pinResolved = Test-XinaoImagePinResolved -PinObject $pin
    if (-not $pinResolved) {
        throw 'IMAGE_PIN_UNRESOLVED'
    }
    $imageRef = Get-XinaoImageAuthorityRef -PinObject $pin

    if (-not (Test-Path -LiteralPath $AllowlistPath -PathType Leaf)) {
        throw "ALLOWLIST_MISSING:$AllowlistPath"
    }
    if (-not (Test-Path -LiteralPath $paths.compose_path -PathType Leaf)) {
        throw "COMPOSE_MISSING:$($paths.compose_path)"
    }
    $composeText = [System.IO.File]::ReadAllText($paths.compose_path)
    $composeIssues = Test-XinaoComposeSafetyText -ComposeText $composeText
    if ($composeIssues.Count -gt 0) {
        throw ("COMPOSE_SAFETY_FAILED:" + ($composeIssues -join ','))
    }

    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
    $renderOut = Join-Path $paths.temp_root "squid.rendered.$stamp.conf"
    $renderReceipt = Join-Path $paths.temp_root "render.receipt.$stamp.json"

    $renderArgs = @(
        $paths.render_script_path,
        '--allowlist', $AllowlistPath,
        '--template', $paths.template_path,
        '--output', $renderOut,
        '--receipt', $renderReceipt
    )
    $renderResult = Invoke-XinaoPythonJson -PythonPath $python -ArgumentList $renderArgs
    $renderMeta = $renderResult.StdOut | ConvertFrom-Json
    $aclReceipt = Read-XinaoJsonFile -Path $renderReceipt
    $acl = [string]$aclReceipt.provider_dstdomain_acl
    $domainCount = @($aclReceipt.domains).Count

    $planned = @(
        "set XINAO_EGRESS_PROXY_IMAGE=$imageRef",
        "set XINAO_EGRESS_PROVIDER_DSTDOMAIN_ACL=<single-line acl>",
        "docker compose -f $($paths.compose_path) up -d",
        "inspect network $($paths.internal_network_name) Internal==true",
        "write posture $($paths.posture_path) verified=false"
    )

    if ($PreflightOnly -or $WhatIf) {
        $status = if ($WhatIf) { 'planned' } else { 'observed' }
        $extra = @{
            mode                    = $(if ($WhatIf) { 'whatif' } else { 'preflight_only' })
            pin_resolved            = $true
            image_authority_ref     = $imageRef
            allowlist_path          = $AllowlistPath
            allowlist_sha256        = [string]$aclReceipt.allowlist_sha256
            proxy_config_sha256     = [string]$aclReceipt.proxy_config_sha256
            domain_count            = $domainCount
            empty_allowlist         = ($domainCount -eq 0)
            compose_path            = $paths.compose_path
            compose_safety_ok       = $true
            rendered_conf_path      = $renderOut
            render_receipt_path     = $renderReceipt
            planned_actions         = $planned
            docker_mutated          = $false
            note                    = 'Preflight/WhatIf does not create networks or start proxy. Empty allowlist remains fail-closed deny-all.'
        }
        $receipt = Write-ProvisionReceipt -Status $status -Extra $extra
        Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                    status                           = $(if ($WhatIf) { 'PLANNED' } else { 'PREFLIGHT_OK' })
                    provider_egress_runtime_verified = $false
                    domain_count                     = $domainCount
                    allowlist_sha256                 = [string]$aclReceipt.allowlist_sha256
                    proxy_config_sha256              = [string]$aclReceipt.proxy_config_sha256
                    receipt_path                     = $receipt.receipt_path
                    docker_mutated                   = $false
                }))
        exit 0
    }

    if (-not (Test-XinaoCommandAvailable -Name 'docker')) {
        throw 'EGRESS_DOCKER_CLI_MISSING'
    }

    $env:XINAO_EGRESS_PROXY_IMAGE = $imageRef
    $env:XINAO_EGRESS_PROVIDER_DSTDOMAIN_ACL = $acl

    $composeDir = Split-Path -Parent $paths.compose_path
    Push-Location -LiteralPath $composeDir
    try {
        Invoke-XinaoDocker -ArgumentList @('compose', '-f', $paths.compose_path, 'up', '-d') | Out-Null
    }
    finally {
        Pop-Location
    }

    $netIdResult = Invoke-XinaoDocker -ArgumentList @('network', 'inspect', $paths.internal_network_name, '--format', '{{.Id}}')
    $netId = $netIdResult.StdOut.Trim()
    $internalResult = Invoke-XinaoDocker -ArgumentList @('network', 'inspect', $paths.internal_network_name, '--format', '{{.Internal}}')
    $internal = $internalResult.StdOut.Trim().ToLowerInvariant()
    if ($internal -ne 'true') {
        throw 'EGRESS_NETWORK_NOT_INTERNAL'
    }
    $proxyIdResult = Invoke-XinaoDocker -ArgumentList @('inspect', $paths.proxy_container_name, '--format', '{{.Id}}')
    $proxyId = $proxyIdResult.StdOut.Trim()
    $proxyRunningResult = Invoke-XinaoDocker -ArgumentList @(
        'inspect', $paths.proxy_container_name, '--format', '{{.State.Running}}'
    ) -AllowNonZero
    if (
        $proxyRunningResult.ExitCode -ne 0 -or
        $proxyRunningResult.StdOut.Trim().ToLowerInvariant() -ne 'true'
    ) {
        throw 'EGRESS_PROXY_NOT_RUNNING'
    }
    $proxyImageResult = Invoke-XinaoDocker -ArgumentList @('inspect', $paths.proxy_container_name, '--format', '{{.Image}}')
    $proxyImageId = $proxyImageResult.StdOut.Trim()

    $posture = [ordered]@{
        schema_version                   = 'xinao.provider_egress_posture.v1'
        lifecycle_state                  = 'HEALTHY'
        internal_network_name            = $paths.internal_network_name
        internal_network_id              = $netId
        external_network_name            = $paths.external_network_name
        proxy_container_name             = $paths.proxy_container_name
        proxy_container_id               = $proxyId
        proxy_image_id                   = $proxyImageId
        proxy_endpoint                   = "http://$($paths.proxy_container_name):3128"
        proxy_listen_port                = 3128
        allowlist_sha256                 = [string]$aclReceipt.allowlist_sha256
        proxy_config_sha256              = [string]$aclReceipt.proxy_config_sha256
        provider_domains                 = @($aclReceipt.domains)
        host_port_published              = $false
        dify_cross_project               = $false
        tls_interception                 = $false
        provider_egress_runtime_verified = $false
        verification_evidence            = [ordered]@{
            negative_suite = $null
            positive_canary = $null
            note = 'Owner must run live negative suite + engineering canary before any live-seal consumer seals verified.'
        }
        created_at                       = (New-XinaoUtcNowIso)
        secrets_present                  = $false
        completion_claim_allowed         = $false
        carrier                          = 'windows_powershell7_docker_desktop'
    }
    Assert-XinaoNoSecretLeak -Object $posture
    Write-XinaoJsonFile -Path $paths.posture_path -Object $posture | Out-Null

    $extra = @{
        mode                    = 'execute'
        pin_resolved            = $true
        image_authority_ref     = $imageRef
        allowlist_sha256        = [string]$aclReceipt.allowlist_sha256
        proxy_config_sha256     = [string]$aclReceipt.proxy_config_sha256
        domain_count            = $domainCount
        internal_network_id     = $netId
        proxy_container_id      = $proxyId
        proxy_image_id          = $proxyImageId
        posture_path            = $paths.posture_path
        docker_mutated          = $true
        note                    = 'Provision complete. provider_egress_runtime_verified remains false until Owner evidence + separate live-seal consumer.'
    }
    $receipt = Write-ProvisionReceipt -Status 'observed' -Extra $extra
    Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                status                           = 'PROVISIONED'
                posture_path                     = $paths.posture_path
                provider_egress_runtime_verified = $false
                receipt_path                     = $receipt.receipt_path
            }))
    exit 0
}
catch {
    $msg = [string]$_.Exception.Message
    try {
        $receipt = Write-ProvisionReceipt -Status 'failed' -Extra @{
            mode        = 'error'
            reason_code = $msg
            error       = $msg
            docker_mutated = $false
        }
        Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
    } catch {
        Write-Error $msg
    }
    exit 2
}
