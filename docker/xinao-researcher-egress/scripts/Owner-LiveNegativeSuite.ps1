#Requires -Version 7.0
<#
.SYNOPSIS
  Owner live negative suite for XINAO egress (Windows Docker Desktop carrier).
.DESCRIPTION
  Probes unauthorized domains, private/metadata/loopback, non-443, cleartext, IP literals,
  and Dify non-attachment. Writes exact-object-bound receipt under D-state.
  -PreflightOnly emits planned case list without docker run mutations.
  Execute requires immutable -ClientImageId (sha256:<64hex>); floating tags rejected.
  Seal-eligible receipts match owner_seal_live_egress.py NEGATIVE_* key sets exactly.
  Never flips verified=true. Never reads credentials. Not research().
.EXAMPLE
  pwsh -File .\Owner-LiveNegativeSuite.ps1 -PreflightOnly
#>
[CmdletBinding()]
param(
    [string]$StateRoot = '',
    [string]$PackageRoot = '',
    [string]$InternalNetwork = '',
    [string]$ProxyUrl = '',
    [string]$ClientImageId = '',
    [string]$ClientImage = '',
    [string]$ResultsPath = '',
    [switch]$PreflightOnly,
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'XinaoEgressOwner.Common.ps1')

if ([string]::IsNullOrWhiteSpace($ClientImageId) -and -not [string]::IsNullOrWhiteSpace($ClientImage)) {
    $ClientImageId = $ClientImage
}

if ([string]::IsNullOrWhiteSpace($PackageRoot)) { $PackageRoot = Get-XinaoEgressPackageRoot }
if ([string]::IsNullOrWhiteSpace($StateRoot)) { $StateRoot = Get-XinaoDefaultStateRoot }
$paths = Get-XinaoEgressPathContract -PackageRoot $PackageRoot -StateRoot $StateRoot
if ([string]::IsNullOrWhiteSpace($InternalNetwork)) { $InternalNetwork = $paths.internal_network_name }
if ([string]::IsNullOrWhiteSpace($ProxyUrl)) { $ProxyUrl = "http://$($paths.proxy_container_name):3128" }
if ([string]::IsNullOrWhiteSpace($ResultsPath)) { $ResultsPath = $paths.negative_suite_receipt_path }

$caseCatalog = @(
    [ordered]@{ id = 'N1'; title = 'direct_no_route_or_timeout'; expect = 'no_route_or_timeout'; mode = 'direct'; target = 'https://example.com/' }
    [ordered]@{ id = 'N3'; title = 'proxy_arbitrary_domain'; expect = '403_or_denied'; mode = 'proxy'; target = 'https://example.com/' }
    [ordered]@{ id = 'N4'; title = 'proxy_rfc1918'; expect = 'denied'; mode = 'proxy'; target = 'https://10.0.0.1/' }
    [ordered]@{ id = 'N5'; title = 'metadata'; expect = 'denied'; mode = 'proxy'; target = 'https://169.254.169.254/' }
    [ordered]@{ id = 'N6'; title = 'loopback'; expect = 'denied'; mode = 'proxy'; target = 'https://127.0.0.1/' }
    [ordered]@{ id = 'N7'; title = 'connect_non_443'; expect = 'denied'; mode = 'proxy'; target = 'https://example.com:8443/' }
    [ordered]@{ id = 'N8'; title = 'cleartext_80'; expect = 'denied'; mode = 'proxy'; target = 'http://example.com/' }
    [ordered]@{ id = 'N9'; title = 'proxy_env_unset_internal_only'; expect = 'no_external'; mode = 'direct'; target = 'https://example.com/' }
    [ordered]@{ id = 'N15'; title = 'no_dify_attach'; expect = 'isolated'; mode = 'inspect_proxy_networks'; target = 'xinao-researcher-egress-proxy' }
    [ordered]@{ id = 'N17'; title = 'ip_literal'; expect = 'denied'; mode = 'proxy'; target = 'https://1.1.1.1/' }
    [ordered]@{ id = 'N17b'; title = 'decimal_ip_literal'; expect = 'denied'; mode = 'proxy'; target = 'https://2130706433/' }
    [ordered]@{ id = 'N17c'; title = 'trailing_dot'; expect = 'denied'; mode = 'proxy'; target = 'https://example.com./' }
    [ordered]@{ id = 'N17d'; title = 'ipv6_literal'; expect = 'denied'; mode = 'proxy'; target = 'https://[::1]/' }
)

function Test-DeniedOutput {
    param([string]$Out, [string[]]$Patterns)
    foreach ($p in $Patterns) {
        if ($Out -match $p) { return $true }
    }
    return $false
}

function Resolve-ClientImageId {
    param(
        [string]$ImageRef,
        [switch]$Preflight
    )
    if ([string]::IsNullOrWhiteSpace($ImageRef)) {
        if ($Preflight) {
            return [ordered]@{ ok = $false; reason_code = 'CLIENT_IMAGE_ID_MISSING'; image_id = $null }
        }
        throw 'EGRESS_CLIENT_IMAGE_ID_REQUIRED'
    }
    if (-not (Test-XinaoImmutableImageIdFormat -ImageId $ImageRef)) {
        if ($Preflight) {
            return [ordered]@{ ok = $false; reason_code = 'CLIENT_IMAGE_ID_NOT_IMMUTABLE'; image_id = $null }
        }
        throw 'EGRESS_CLIENT_IMAGE_ID_NOT_IMMUTABLE'
    }
    $canonical = ConvertTo-XinaoCanonicalImageId -ImageId $ImageRef
    if ($Preflight) {
        return [ordered]@{ ok = $true; reason_code = $null; image_id = $canonical }
    }
    $insp = Invoke-XinaoDocker -ArgumentList @('image', 'inspect', $canonical, '--format', '{{.Id}}') -AllowNonZero
    if ($insp.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($insp.StdOut.Trim())) {
        throw 'EGRESS_CLIENT_IMAGE_NOT_LOCAL'
    }
    return [ordered]@{
        ok          = $true
        reason_code = $null
        image_id    = (ConvertTo-XinaoCanonicalImageId -ImageId $insp.StdOut.Trim())
    }
}

function Invoke-ClientProbe {
    param(
        [string]$Target,
        [string]$Mode,
        [string]$ImageId
    )
    $envArgs = @()
    if ($Mode -eq 'proxy') {
        $envArgs = @(
            '-e', "http_proxy=$ProxyUrl",
            '-e', "https_proxy=$ProxyUrl",
            '-e', "HTTP_PROXY=$ProxyUrl",
            '-e', "HTTPS_PROXY=$ProxyUrl"
        )
    } else {
        $envArgs = @(
            '-e', 'http_proxy=',
            '-e', 'https_proxy=',
            '-e', 'HTTP_PROXY=',
            '-e', 'HTTPS_PROXY='
        )
    }
    $args = @('run', '--rm', '--network', $InternalNetwork) + $envArgs + @(
        $ImageId, 'wget', '-S', '-O', '/dev/null', '-T', '8', $Target
    )
    $result = Invoke-XinaoDocker -ArgumentList $args -AllowNonZero
    return ($result.StdOut + "`n" + $result.StdErr)
}

try {
    Ensure-XinaoDirectory -Path $paths.state_root | Out-Null

    $clientPre = Resolve-ClientImageId -ImageRef $ClientImageId -Preflight
    $objectIds = [ordered]@{
        internal_network_name = $InternalNetwork
        proxy_url             = $ProxyUrl
        proxy_container_name  = $paths.proxy_container_name
        client_image_id       = $clientPre.image_id
        client_image_reason_code = $clientPre.reason_code
    }

    if (Test-Path -LiteralPath $paths.posture_path -PathType Leaf) {
        $posture = Read-XinaoJsonFile -Path $paths.posture_path
        $objectIds.internal_network_id = $posture.internal_network_id
        $objectIds.proxy_container_id = $posture.proxy_container_id
        $objectIds.proxy_image_id = $posture.proxy_image_id
        $objectIds.allowlist_sha256 = $posture.allowlist_sha256
        $objectIds.proxy_config_sha256 = $posture.proxy_config_sha256
    }

    if ($PreflightOnly -or $WhatIf) {
        $cases = @()
        foreach ($c in $caseCatalog) {
            $cases += [ordered]@{
                id      = $c.id
                title   = $c.title
                expect  = $c.expect
                mode    = $c.mode
                target  = $c.target
                result  = 'planned'
                ok      = $null
            }
        }
        $receipt = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_negative_suite_receipt.v1' -Status 'planned' -Extra @{
            mode                 = $(if ($WhatIf) { 'whatif' } else { 'preflight_only' })
            path_class           = 'negative_suite'
            pass_count           = 0
            fail_count           = 0
            cases                = $cases
            object_identities    = $objectIds
            docker_mutated       = $false
            suite_passed         = $false
            all_cases_passed     = $false
            unauthorized_domain_reachable = $null
            direct_no_proxy_escape = $null
            observed_at          = (New-XinaoUtcNowIso)
            note                 = 'Planned negative suite only; no docker run executed. Execute requires immutable ClientImageId. Live execute binds exact object/config identities from posture when available.'
        }
        $written = Write-XinaoJsonFile -Path $ResultsPath -Object $receipt
        Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                    status                           = 'PLANNED'
                    receipt_path                     = $written
                    case_count                       = $cases.Count
                    client_image_id                  = $clientPre.image_id
                    client_image_reason_code         = $clientPre.reason_code
                    provider_egress_runtime_verified = $false
                    docker_mutated                   = $false
                }))
        exit 0
    }

    if (-not (Test-XinaoCommandAvailable -Name 'docker')) {
        throw 'EGRESS_DOCKER_CLI_MISSING'
    }

    $clientLive = Resolve-ClientImageId -ImageRef $ClientImageId
    $objectIds.client_image_id = $clientLive.image_id
    $objectIds.client_image_reason_code = $null

    $pass = 0
    $fail = 0
    $caseResults = @()

    foreach ($c in $caseCatalog) {
        $ok = $false
        $got = ''
        if ($c.mode -eq 'inspect_proxy_networks') {
            $insp = Invoke-XinaoDocker -ArgumentList @(
                'inspect', $paths.proxy_container_name, '--format', '{{json .NetworkSettings.Networks}}'
            ) -AllowNonZero
            $got = $insp.StdOut + $insp.StdErr
            if ($insp.ExitCode -ne 0) {
                $ok = $false
                $got = "inspect_failed:$got"
            } elseif ($got -match 'ssrf_proxy') {
                $ok = $false
            } else {
                $ok = $true
            }
        } else {
            $out = Invoke-ClientProbe -Target $c.target -Mode $c.mode -ImageId $clientLive.image_id
            $got = $out
            if ($c.expect -eq 'no_route_or_timeout' -or $c.expect -eq 'no_external') {
                $ok = Test-DeniedOutput -Out $out -Patterns @(
                    'bad address', "can'?t connect", 'timed out', 'network is unreachable', 'no route', 'wget:'
                )
            } elseif ($c.expect -eq '403_or_denied' -or $c.expect -eq 'denied') {
                $ok = Test-DeniedOutput -Out $out -Patterns @(
                    '403', 'denied', 'Forbidden', "can'?t connect", 'bad port', 'bad address', 'invalid'
                )
            }
        }
        if ($ok) { $pass++ } else { $fail++ }
        $caseResults += [ordered]@{
            id         = $c.id
            title      = $c.title
            expect     = $c.expect
            mode       = $c.mode
            target     = $c.target
            ok         = [bool]$ok
            got_signal = ($(if ($ok) { 'match_expected_fail_closed' } else { 'unexpected_or_open' }))
        }
    }

    # Pure builder emits only sealer-allowed keys for seal-eligible shape.
    $receipt = New-XinaoNegativeSuiteSealReceipt -Cases $caseResults -ObjectIdentities $objectIds
    Assert-XinaoNoSecretLeak -Object $receipt
    $written = Write-XinaoJsonFile -Path $ResultsPath -Object $receipt
    Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                status                           = ([string]$receipt.status).ToUpperInvariant()
                pass_count                       = [int]$receipt.pass_count
                fail_count                       = [int]$receipt.fail_count
                suite_passed                     = [bool]$receipt.suite_passed
                all_cases_passed                 = [bool]$receipt.all_cases_passed
                unauthorized_domain_reachable    = [bool]$receipt.unauthorized_domain_reachable
                direct_no_proxy_escape           = [bool]$receipt.direct_no_proxy_escape
                client_image_id                  = $clientLive.image_id
                receipt_path                     = $written
                provider_egress_runtime_verified = $false
            }))
    if ($fail -ne 0 -or -not $receipt.suite_passed) { exit 1 }
    exit 0
}
catch {
    $msg = [string]$_.Exception.Message
    if ($msg -match 'EGRESS_CLIENT_IMAGE') {
        $safe = ($msg -split ':')[0]
    } else {
        $safe = $msg
    }
    $receipt = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_negative_suite_receipt.v1' -Status 'failed' -Extra @{
        mode        = 'error'
        path_class  = 'negative_suite'
        reason_code = $safe
        pass_count  = 0
        fail_count  = 0
        suite_passed = $false
        all_cases_passed = $false
        cases       = @()
        unauthorized_domain_reachable = $true
        direct_no_proxy_escape = $true
        observed_at = (New-XinaoUtcNowIso)
        note        = 'Negative suite failed before completion.'
    }
    $written = Write-XinaoJsonFile -Path $ResultsPath -Object $receipt
    Write-Output (ConvertTo-XinaoStrictJson -InputObject ([ordered]@{
                status       = 'FAILED'
                reason_code  = $safe
                receipt_path = $written
            }))
    exit 2
}
