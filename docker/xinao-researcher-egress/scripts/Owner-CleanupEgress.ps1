#Requires -Version 7.0
<#
.SYNOPSIS
  Exact XINAO-only cleanup/invalidation for researcher egress objects (Windows).
.DESCRIPTION
  Never selects Dify/foreign objects. Never deletes by broad glob or name-only without
  identity checks. Before any remove: resolve ID + name (+ labels when available).
  Receipt reports observed removals only. Invalidates posture and live seal under D-state.
  -PreflightOnly / -WhatIf resolve targets and plan without mutating Docker.
.EXAMPLE
  pwsh -File .\Owner-CleanupEgress.ps1 -WhatIf
  pwsh -File .\Owner-CleanupEgress.ps1 -PreflightOnly
#>
[CmdletBinding()]
param(
    [string]$StateRoot = '',
    [string]$PackageRoot = '',
    [switch]$PreflightOnly,
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'XinaoEgressOwner.Common.ps1')

if ([string]::IsNullOrWhiteSpace($PackageRoot)) { $PackageRoot = Get-XinaoEgressPackageRoot }
if ([string]::IsNullOrWhiteSpace($StateRoot)) { $StateRoot = Get-XinaoDefaultStateRoot }
$paths = Get-XinaoEgressPathContract -PackageRoot $PackageRoot -StateRoot $StateRoot

function Resolve-ContainerTarget {
    param([string]$Name)
    Assert-XinaoNotForbiddenDockerTarget -Name $Name | Out-Null
    if (-not (Test-XinaoCommandAvailable -Name 'docker')) {
        return [ordered]@{
            kind = 'container'
            name = $Name
            id = $null
            exists = $false
            labels = @{}
            eligible = (Test-XinaoExactCleanupCandidate -Name $Name -Kind container)
            reason = 'docker_cli_absent_or_skipped'
        }
    }
    $insp = Invoke-XinaoDocker -ArgumentList @(
        'inspect', $Name, '--format',
        '{{.Id}}|{{.Name}}|{{index .Config.Labels "io.xinao.researcher.chain"}}|{{index .Config.Labels "io.xinao.project"}}'
    ) -AllowNonZero
    if ($insp.ExitCode -ne 0) {
        return [ordered]@{
            kind = 'container'
            name = $Name
            id = $null
            exists = $false
            labels = @{}
            eligible = (Test-XinaoExactCleanupCandidate -Name $Name -Kind container)
            reason = 'absent'
        }
    }
    $parts = $insp.StdOut.Trim() -split '\|', 4
    $id = $parts[0]
    $rawName = if ($parts.Count -gt 1) { $parts[1] } else { $Name }
    $chain = if ($parts.Count -gt 2) { $parts[2] } else { '' }
    $project = if ($parts.Count -gt 3) { $parts[3] } else { '' }
    $labels = @{}
    if (-not [string]::IsNullOrWhiteSpace($chain)) { $labels['io.xinao.researcher.chain'] = $chain }
    if (-not [string]::IsNullOrWhiteSpace($project)) { $labels['io.xinao.project'] = $project }
    $norm = $rawName.TrimStart('/')
    Assert-XinaoNotForbiddenDockerTarget -Name $norm -Id $id | Out-Null
    $eligible = Test-XinaoExactCleanupCandidate -Name $norm -Id $id -Labels $labels -Kind container
    # Exact ID+name dual check: known proxy name must match inspected name.
    if ($Name -eq $paths.proxy_container_name -and $norm -ne $paths.proxy_container_name) {
        $eligible = $false
    }
    return [ordered]@{
        kind = 'container'
        name = $norm
        id = $id
        exists = $true
        labels = $labels
        eligible = [bool]$eligible
        reason = $(if ($eligible) { 'eligible_exact' } else { 'label_or_name_mismatch' })
    }
}

function Resolve-NetworkTarget {
    param([string]$Name)
    Assert-XinaoNotForbiddenDockerTarget -Name $Name | Out-Null
    if (-not (Test-XinaoCommandAvailable -Name 'docker')) {
        return [ordered]@{
            kind = 'network'
            name = $Name
            id = $null
            exists = $false
            eligible = (Test-XinaoExactCleanupCandidate -Name $Name -Kind network)
            reason = 'docker_cli_absent_or_skipped'
        }
    }
    $insp = Invoke-XinaoDocker -ArgumentList @(
        'network', 'inspect', $Name, '--format', '{{.Id}}|{{.Name}}'
    ) -AllowNonZero
    if ($insp.ExitCode -ne 0) {
        return [ordered]@{
            kind = 'network'
            name = $Name
            id = $null
            exists = $false
            eligible = (Test-XinaoExactCleanupCandidate -Name $Name -Kind network)
            reason = 'absent'
        }
    }
    $parts = $insp.StdOut.Trim() -split '\|', 2
    $id = $parts[0]
    $norm = if ($parts.Count -gt 1) { $parts[1] } else { $Name }
    Assert-XinaoNotForbiddenDockerTarget -Name $norm -Id $id | Out-Null
    if ($norm -ne $Name) {
        return [ordered]@{
            kind = 'network'
            name = $norm
            id = $id
            exists = $true
            eligible = $false
            reason = 'name_mismatch'
        }
    }
    $eligible = Test-XinaoExactCleanupCandidate -Name $norm -Id $id -Kind network
    return [ordered]@{
        kind = 'network'
        name = $norm
        id = $id
        exists = $true
        eligible = [bool]$eligible
        reason = $(if ($eligible) { 'eligible_exact' } else { 'not_xinao_network' })
    }
}

function Resolve-LabeledResearcherContainers {
    if (-not (Test-XinaoCommandAvailable -Name 'docker')) {
        return @()
    }
    $list = Invoke-XinaoDocker -ArgumentList @(
        'ps', '-aq', '--filter', "label=$($paths.chain_label)=$($paths.chain_label_value)"
    ) -AllowNonZero
    if ($list.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($list.StdOut)) {
        return @()
    }
    $out = @()
    foreach ($id in ($list.StdOut -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $insp = Invoke-XinaoDocker -ArgumentList @(
            'inspect', $id, '--format',
            '{{.Id}}|{{.Name}}|{{index .Config.Labels "io.xinao.researcher.chain"}}'
        ) -AllowNonZero
        if ($insp.ExitCode -ne 0) { continue }
        $parts = $insp.StdOut.Trim() -split '\|', 3
        $cid = $parts[0]
        $name = if ($parts.Count -gt 1) { $parts[1].TrimStart('/') } else { '' }
        $chain = if ($parts.Count -gt 2) { $parts[2] } else { '' }
        try {
            Assert-XinaoNotForbiddenDockerTarget -Name $name -Id $cid | Out-Null
        } catch {
            continue
        }
        $labels = @{ 'io.xinao.researcher.chain' = $chain }
        $eligible = Test-XinaoExactCleanupCandidate -Name $name -Id $cid -Labels $labels -Kind container
        if (-not $eligible) { continue }
        # Skip proxy if already handled by exact name path (dedupe by name).
        if ($name -eq $paths.proxy_container_name) { continue }
        $out += [ordered]@{
            kind = 'container'
            name = $name
            id = $cid
            exists = $true
            labels = $labels
            eligible = $true
            reason = 'eligible_label_and_name_prefix'
        }
    }
    return $out
}

try {
    Ensure-XinaoDirectory -Path $paths.state_root | Out-Null

    # Static rejection fixtures for foreign names (always evaluated).
    $foreignRejected = @()
    foreach ($foreign in @('ssrf_proxy', 'ssrf_proxy_network', 'docker_ssrf_proxy_network')) {
        try {
            Assert-XinaoNotForbiddenDockerTarget -Name $foreign | Out-Null
            $foreignRejected += [ordered]@{ name = $foreign; rejected = $false; error = 'expected_reject_missing' }
        } catch {
            $foreignRejected += [ordered]@{ name = $foreign; rejected = $true; reason = [string]$_.Exception.Message }
        }
    }

    $targets = @()
    $mutateDocker = -not ($PreflightOnly -or $WhatIf)

    if ($PreflightOnly -and -not (Test-XinaoCommandAvailable -Name 'docker')) {
        # Offline preflight: exact planned set without inspect.
        $targets += [ordered]@{
            kind = 'container'; name = $paths.proxy_container_name; id = $null; exists = $null
            eligible = $true; reason = 'planned_exact_name'; planned_action = 'docker rm -f <id-after-inspect>'
        }
        foreach ($net in @($paths.internal_network_name, $paths.external_network_name)) {
            $targets += [ordered]@{
                kind = 'network'; name = $net; id = $null; exists = $null
                eligible = $true; reason = 'planned_exact_name'; planned_action = 'docker network rm <id-after-inspect>'
            }
        }
    } else {
        $targets += ,(Resolve-ContainerTarget -Name $paths.proxy_container_name)
        $labeled = Resolve-LabeledResearcherContainers
        foreach ($t in $labeled) { $targets += ,$t }
        foreach ($net in @($paths.internal_network_name, $paths.external_network_name)) {
            $targets += ,(Resolve-NetworkTarget -Name $net)
        }
    }

    # Dify left-untouched observation (inspect presence only; never remove).
    $difyObservations = @()
    foreach ($name in @('ssrf_proxy', 'ssrf_proxy_network', 'docker_ssrf_proxy_network')) {
        $present = $false
        if (Test-XinaoCommandAvailable -Name 'docker') {
            $check = Invoke-XinaoDocker -ArgumentList @('inspect', $name) -AllowNonZero
            if ($check.ExitCode -ne 0) {
                $check = Invoke-XinaoDocker -ArgumentList @('network', 'inspect', $name) -AllowNonZero
            }
            $present = ($check.ExitCode -eq 0)
        }
        $difyObservations += [ordered]@{
            name = $name
            present_observed = $present
            touched = $false
            note = 'Dify/foreign object never selected for removal'
        }
    }

    $plannedRemovals = @($targets | Where-Object { $_.eligible -eq $true })
    $rejected = @($targets | Where-Object { $_.eligible -eq $false -and $_.exists -eq $true })

    if ($PreflightOnly -or $WhatIf) {
        $receipt = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_cleanup_receipt.v1' -Status 'planned' -Extra @{
            mode                              = $(if ($WhatIf) { 'whatif' } else { 'preflight_only' })
            resolved_targets                  = $targets
            planned_removals                  = $plannedRemovals
            rejected_targets                  = $rejected
            foreign_name_static_rejections    = $foreignRejected
            dify_objects_touched              = $false
            dify_observations                 = $difyObservations
            proxy_removed_observed            = $false
            removed_networks_observed         = @()
            removed_containers_observed       = @()
            provider_egress_runtime_verified_forced_false = $true
            live_seal_invalidated_planned     = $true
            docker_mutated                    = $false
            note                              = 'Planned exact cleanup only. Absent objects are not claimed removed. No broad glob selection.'
        }
        $written = Write-XinaoJsonFile -Path $paths.cleanup_receipt_path -Object $receipt
        Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                    status                           = 'PLANNED'
                    receipt_path                     = $written
                    planned_count                    = $plannedRemovals.Count
                    provider_egress_runtime_verified = $false
                    dify_objects_touched             = $false
                    docker_mutated                   = $false
                }))
        exit 0
    }

    if (-not (Test-XinaoCommandAvailable -Name 'docker')) {
        throw 'EGRESS_DOCKER_CLI_MISSING'
    }

    $removedContainers = @()
    $removedNetworks = @()
    $proxyRemoved = $false

    foreach ($t in $targets) {
        if (-not $t.exists -or -not $t.eligible) { continue }
        if ([string]::IsNullOrWhiteSpace([string]$t.id)) { continue }
        Assert-XinaoNotForbiddenDockerTarget -Name ([string]$t.name) -Id ([string]$t.id) | Out-Null

        if ($t.kind -eq 'container') {
            # Re-inspect immediately before remove: ID and name must still match.
            $re = Invoke-XinaoDocker -ArgumentList @('inspect', $t.id, '--format', '{{.Id}}|{{.Name}}') -AllowNonZero
            if ($re.ExitCode -ne 0) { continue }
            $rp = $re.StdOut.Trim() -split '\|', 2
            $rid = $rp[0]
            $rname = if ($rp.Count -gt 1) { $rp[1].TrimStart('/') } else { '' }
            if ($rid -ne $t.id -or $rname -ne $t.name) {
                continue
            }
            $rm = Invoke-XinaoDocker -ArgumentList @('rm', '-f', $t.id) -AllowNonZero
            if ($rm.ExitCode -eq 0) {
                $removedContainers += [ordered]@{ name = $t.name; id = $t.id }
                if ($t.name -eq $paths.proxy_container_name) { $proxyRemoved = $true }
            }
        } elseif ($t.kind -eq 'network') {
            $re = Invoke-XinaoDocker -ArgumentList @('network', 'inspect', $t.id, '--format', '{{.Id}}|{{.Name}}') -AllowNonZero
            if ($re.ExitCode -ne 0) { continue }
            $rp = $re.StdOut.Trim() -split '\|', 2
            $rid = $rp[0]
            $rname = if ($rp.Count -gt 1) { $rp[1] } else { '' }
            if ($rid -ne $t.id -or $rname -ne $t.name) { continue }
            $rm = Invoke-XinaoDocker -ArgumentList @('network', 'rm', $t.id) -AllowNonZero
            if ($rm.ExitCode -eq 0) {
                $removedNetworks += $t.name
            }
        }
    }

    # Invalidate live seal if present (delete; do not claim reseal).
    $sealInvalidated = $false
    $sealWasPresent = $false
    if (Test-Path -LiteralPath $paths.live_seal_path -PathType Leaf) {
        $sealWasPresent = $true
        Remove-Item -LiteralPath $paths.live_seal_path -Force
        $sealInvalidated = -not (Test-Path -LiteralPath $paths.live_seal_path -PathType Leaf)
    }

    # Force posture ABSENT / verified false when posture exists.
    if (Test-Path -LiteralPath $paths.posture_path -PathType Leaf) {
        $posture = Read-XinaoJsonFile -Path $paths.posture_path
        $posture.lifecycle_state = 'ABSENT'
        $posture.provider_egress_runtime_verified = $false
        if ($posture.PSObject.Properties.Name -contains 'completion_claim_allowed') {
            $posture.completion_claim_allowed = $false
        }
        Write-XinaoJsonFile -Path $paths.posture_path -Object $posture | Out-Null
    }

    $status = 'observed'
    if (($removedContainers.Count -eq 0) -and ($removedNetworks.Count -eq 0) -and (-not $sealWasPresent)) {
        # Nothing present is still an honest observed cleanup with empty observed lists.
        $status = 'observed'
    }

    $receipt = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_cleanup_receipt.v1' -Status $status -Extra @{
        mode                              = 'execute'
        cleaned_at                        = (New-XinaoUtcNowIso)
        resolved_targets                  = $targets
        rejected_targets                  = $rejected
        foreign_name_static_rejections    = $foreignRejected
        proxy_removed_observed            = [bool]$proxyRemoved
        removed_proxy_name                = $paths.proxy_container_name
        removed_containers_observed       = $removedContainers
        removed_networks_observed         = @($removedNetworks)
        removed_networks_attempted        = @($paths.internal_network_name, $paths.external_network_name)
        dify_objects_touched              = $false
        dify_observations                 = $difyObservations
        provider_egress_runtime_verified_forced_false = $true
        live_seal_was_present             = [bool]$sealWasPresent
        live_seal_invalidated_observed    = [bool]$sealInvalidated
        docker_mutated                    = $true
        note                              = 'Receipt claims only observed removals; absent objects are not reported as removed. Dify untouched.'
    }
    Assert-XinaoNoSecretLeak -Object $receipt
    $written = Write-XinaoJsonFile -Path $paths.cleanup_receipt_path -Object $receipt
    Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                status                           = 'CLEANED'
                provider_egress_runtime_verified = $false
                proxy_removed_observed           = [bool]$proxyRemoved
                removed_networks_observed        = @($removedNetworks)
                removed_containers_observed      = $removedContainers
                dify_objects_touched             = $false
                receipt_path                     = $written
            }))
    exit 0
}
catch {
    $msg = [string]$_.Exception.Message
    $receipt = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_cleanup_receipt.v1' -Status 'failed' -Extra @{
        mode        = 'error'
        reason_code = $msg
        error       = $msg
        dify_objects_touched = $false
        proxy_removed_observed = $false
        removed_networks_observed = @()
    }
    $written = Write-XinaoJsonFile -Path $paths.cleanup_receipt_path -Object $receipt
    Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                status       = 'FAILED'
                reason_code  = $msg
                receipt_path = $written
            }))
    exit 2
}

