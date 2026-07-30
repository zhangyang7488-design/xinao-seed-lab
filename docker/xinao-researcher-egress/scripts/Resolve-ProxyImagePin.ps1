#Requires -Version 7.0
<#
.SYNOPSIS
  Resolve ubuntu/squid to immutable digest and/or image id (Windows Owner carrier).
.DESCRIPTION
  Never treats floating tags as identity authority. Safe modes:
  -PreflightOnly: validate pin schema fields without Docker mutation
  -ReadbackOnly: report whether pin is already sealed
  -WhatIf: plan pull/inspect steps without mutating
  Default execute mode pulls observational tag then seals image_id/digest into image-pin.v1.json.
  Does not flip runtime verified. Does not use WSL or Git Bash.
.EXAMPLE
  pwsh -File .\Resolve-ProxyImagePin.ps1 -PreflightOnly
  pwsh -File .\Resolve-ProxyImagePin.ps1 -ReadbackOnly
#>
[CmdletBinding()]
param(
    [string]$PinPath = '',
    [string]$StateRoot = '',
    [string]$PackageRoot = '',
    [string]$PythonPath = '',
    [switch]$PreflightOnly,
    [switch]$ReadbackOnly,
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$common = Join-Path $PSScriptRoot 'XinaoEgressOwner.Common.ps1'
. $common

if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
    $PackageRoot = Get-XinaoEgressPackageRoot
}
$paths = Get-XinaoEgressPathContract -PackageRoot $PackageRoot -StateRoot $(
    if ([string]::IsNullOrWhiteSpace($StateRoot)) { Get-XinaoDefaultStateRoot } else { $StateRoot }
)
if ([string]::IsNullOrWhiteSpace($PinPath)) {
    $PinPath = $paths.image_pin_path
}
$PinPath = [System.IO.Path]::GetFullPath($PinPath)
$receiptPath = $paths.image_pin_readback_path

function Write-PinReceipt {
    param($Status, $Extra)
    $receipt = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_image_pin_readback.v1' -Status $Status -Extra $Extra
    $written = Write-XinaoJsonFile -Path $receiptPath -Object $receipt
    $receipt | Add-Member -NotePropertyName receipt_path -NotePropertyValue $written -Force
    return $receipt
}

try {
    if (-not (Test-Path -LiteralPath $PinPath -PathType Leaf)) {
        throw "IMAGE_PIN_FILE_MISSING:$PinPath"
    }
    $pin = Read-XinaoJsonFile -Path $PinPath
    $repo = [string]$pin.image_repository
    $tag = [string]$pin.image_tag_observational
    if ([string]::IsNullOrWhiteSpace($tag)) { $tag = 'latest' }
    $ref = "${repo}:${tag}"
    $resolved = Test-XinaoImagePinResolved -PinObject $pin
    $floatingAsAuthority = $false
    if ($null -ne $pin.floating_tag_as_authority) {
        $floatingAsAuthority = [bool]$pin.floating_tag_as_authority
    }

    if ($floatingAsAuthority) {
        throw 'FLOATING_TAG_AUTHORITY_FORBIDDEN'
    }
    if ([string]$pin.authority -ne 'immutable_digest_or_image_id_only') {
        # Soft fail only when tag is latest without immutable authority marker.
        if ($tag -eq 'latest' -and -not $resolved) {
            throw 'FLOATING_TAG_AUTHORITY_FORBIDDEN'
        }
    }

    $python = $null
    try {
        $python = Resolve-XinaoPythonInterpreter -PackageRoot $PackageRoot -ExplicitPath $PythonPath
    } catch {
        if (-not $PreflightOnly -and -not $ReadbackOnly) {
            throw
        }
    }

    if ($ReadbackOnly -or $PreflightOnly) {
        $status = if ($resolved) { 'observed' } else { 'failed' }
        if ($PreflightOnly -and -not $resolved) {
            $status = 'failed'
        } elseif ($PreflightOnly -and $resolved) {
            $status = 'observed'
        }
        $extra = @{
            mode                         = $(if ($ReadbackOnly) { 'readback_only' } else { 'preflight_only' })
            pin_path                     = $PinPath
            image_repository             = $repo
            image_tag_observational      = $tag
            observational_ref            = $ref
            image_id                     = $pin.image_id
            image_digest                 = $pin.image_digest
            pin_resolved                 = $resolved
            floating_tag_as_authority    = $false
            authority                    = 'immutable_digest_or_image_id_only'
            reason_code                  = $(if ($resolved) { $null } else { 'IMAGE_PIN_UNRESOLVED' })
            note                         = 'Observational tag is never identity authority. Seal image_id and/or repo@sha256 before provision.'
        }
        $receipt = Write-PinReceipt -Status $status -Extra $extra
        Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
        if (-not $resolved) { exit 2 }
        exit 0
    }

    if ($WhatIf) {
        $extra = @{
            mode                      = 'whatif'
            pin_path                  = $PinPath
            observational_ref         = $ref
            pin_resolved              = $resolved
            planned_actions           = @(
                "docker pull $ref",
                "docker image inspect --format {{.Id}} $ref",
                "docker image inspect --format {{index .RepoDigests 0}} $ref",
                "write pin image_id/image_digest to $PinPath"
            )
            note                      = 'WhatIf does not pull or rewrite pin.'
        }
        $receipt = Write-PinReceipt -Status 'planned' -Extra $extra
        Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
        exit 0
    }

    if (-not (Test-XinaoCommandAvailable -Name 'docker')) {
        throw 'EGRESS_DOCKER_CLI_MISSING'
    }

    Write-Host "Pulling observational tag $ref (not authority)..."
    Invoke-XinaoDocker -ArgumentList @('pull', $ref) | Out-Null

    $idResult = Invoke-XinaoDocker -ArgumentList @('image', 'inspect', '--format', '{{.Id}}', $ref)
    $imageId = $idResult.StdOut.Trim()
    if ([string]::IsNullOrWhiteSpace($imageId) -or -not $imageId.StartsWith('sha256:')) {
        throw "IMAGE_ID_INVALID:$imageId"
    }

    $digestResult = Invoke-XinaoDocker -ArgumentList @('image', 'inspect', '--format', '{{index .RepoDigests 0}}', $ref) -AllowNonZero
    $digest = $digestResult.StdOut.Trim()
    if ([string]::IsNullOrWhiteSpace($digest) -or $digest -eq '<no value>') {
        $digest = $null
    } elseif ($digest -notmatch '@sha256:') {
        throw "IMAGE_DIGEST_INVALID:$digest"
    }

    $pin.image_id = $imageId
    $pin.image_digest = $digest
    $pin.floating_tag_as_authority = $false
    $pin.authority = 'immutable_digest_or_image_id_only'
    Write-XinaoJsonFile -Path $PinPath -Object $pin | Out-Null

    # Optional offline assert via renderer helpers if Python available.
    if ($null -ne $python) {
        $assertCode = @'
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from render_squid_config import assert_image_pin
pin = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert_image_pin(pin)
print(json.dumps({"ok": True}))
'@
        $assertResult = Invoke-XinaoPythonJson -PythonPath $python -ArgumentList @('-c', $assertCode, $PackageRoot, $PinPath)
        if ($assertResult.ExitCode -ne 0) {
            throw "IMAGE_PIN_ASSERT_FAILED:$($assertResult.StdErr)"
        }
    }

    $extra = @{
        mode                      = 'execute'
        pin_path                  = $PinPath
        observational_ref         = $ref
        image_id                  = $imageId
        image_digest              = $digest
        pin_resolved              = $true
        floating_tag_as_authority = $false
        authority                 = 'immutable_digest_or_image_id_only'
        note                      = 'Pinned immutable identity. Floating tag remains observational only.'
    }
    $receipt = Write-PinReceipt -Status 'observed' -Extra $extra
    Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                status       = 'PINNED'
                image_id     = $imageId
                image_digest = $digest
                receipt_path = $receipt.receipt_path
                provider_egress_runtime_verified = $false
            }))
    exit 0
}
catch {
    $msg = [string]$_.Exception.Message
    $extra = @{
        mode       = 'error'
        pin_path   = $PinPath
        reason_code = $msg
        error      = $msg
    }
    try {
        $receipt = Write-PinReceipt -Status 'failed' -Extra $extra
        Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
    } catch {
        Write-Error $msg
    }
    exit 2
}

