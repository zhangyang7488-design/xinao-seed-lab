#Requires -Version 7.0
<#
.SYNOPSIS
  Bounded engineering provider canary for XINAO egress (not research()).
.DESCRIPTION
  Explicitly NOT scientific research, NOT research() adoption, NOT parent completion.

  Default / CONNECT path (no -RealProviderCall):
    Unauthenticated CONNECT-style HTTPS probe through the dual-homed proxy on the
    internal network. Transport evidence only. NEVER seal-eligible; always
    real_provider_call=false and provider_effect_verified=false.

  -RealProviderCall path (Owner-only; worker must not execute):
    Requires explicit -AuthFilePath and -CanaryImageId (immutable active dedicated
    researcher release image ID — not the unlabeled extraction donor). Binds against
    protocol-v2 researcher-container current pointer + release manifest, validates
    source-identity donor against runtime-lock, and on execute validates live image
    labels. Creates one disposable container on xinao_researcher_internal only with
    hardened OCI posture, invokes packaged Grok CLI headless JSON contract, parses
    redacted metadata, deletes exact temporary raw output after seal, reports
    observed cleanup only in allowed receipt fields.

  -ResearcherContainerStateRoot is the researcher-container state root that holds
    current.json and releases/ (default from runtime-lock state_root / fixed D: path).
    Distinct from -StateRoot (egress posture evidence root). Absolute override for
    tests/Owner operation; never an opaque hidden field.

  -PreflightOnly validates eligibility without Docker mutation. If active v2 release
    is absent (legacy pointer / missing pointer), reports deterministic failed reason
    and never pretends the donor image is a valid canary.
  Empty allowlist cannot produce a positive canary PASS (honest failed/partial).
  Seal-eligible receipts match owner_seal_live_egress.py CANARY_* key sets exactly;
  canary_image_id is the active researcher image ID (donor remains provenance only).
.EXAMPLE
  pwsh -File .\Owner-EngineeringCanary.ps1 -PreflightOnly
.EXAMPLE
  pwsh -File .\Owner-EngineeringCanary.ps1 -RealProviderCall -AuthFilePath 'C:\path\auth.json' -CanaryImageId 'sha256:<active researcher image id>'
#>
[CmdletBinding()]
param(
    [string]$StateRoot = '',
    [string]$PackageRoot = '',
    [string]$TempRoot = '',
    [string]$AllowlistPath = '',
    [string]$InternalNetwork = '',
    [string]$ProxyUrl = '',
    # Execute CONNECT/negative requires immutable sha256:<64hex>; preflight may omit.
    [string]$ClientImageId = '',
    # Legacy alias; floating tags rejected on execute.
    [string]$ClientImage = '',
    [string]$ModelHint = 'grok-4.5',
    [string]$EndpointHint = 'https://cli-chat-proxy.grok.com',
    [string]$ResultsPath = '',
    [string]$AuthFilePath = '',
    # Immutable active dedicated researcher release image ID (not extraction donor).
    [string]$CanaryImageId = '',
    # Researcher-container state root (current.json + releases/); not egress StateRoot.
    [string]$ResearcherContainerStateRoot = '',
    [int]$ProviderTimeoutSeconds = 120,
    [switch]$PreflightOnly,
    [switch]$WhatIf,
    [switch]$RealProviderCall,
    # Legacy alias retained for older runbooks; same as -RealProviderCall.
    [switch]$AllowRealProviderCall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'XinaoEgressOwner.Common.ps1')

if ($AllowRealProviderCall -and -not $RealProviderCall) { $RealProviderCall = $true }
if ([string]::IsNullOrWhiteSpace($ClientImageId) -and -not [string]::IsNullOrWhiteSpace($ClientImage)) {
    $ClientImageId = $ClientImage
}

if ([string]::IsNullOrWhiteSpace($PackageRoot)) { $PackageRoot = Get-XinaoEgressPackageRoot }
if ([string]::IsNullOrWhiteSpace($StateRoot)) { $StateRoot = Get-XinaoDefaultStateRoot }
if ([string]::IsNullOrWhiteSpace($TempRoot)) { $TempRoot = Get-XinaoDefaultTempRoot }
if ([string]::IsNullOrWhiteSpace($ResearcherContainerStateRoot)) {
    $ResearcherContainerStateRoot = Get-XinaoDefaultResearcherContainerStateRoot -PackageRoot $PackageRoot
} else {
    $ResearcherContainerStateRoot = [System.IO.Path]::GetFullPath($ResearcherContainerStateRoot)
}
$paths = Get-XinaoEgressPathContract -PackageRoot $PackageRoot -StateRoot $StateRoot -TempRoot $TempRoot
if ([string]::IsNullOrWhiteSpace($AllowlistPath)) { $AllowlistPath = $paths.allowlist_path }
if ([string]::IsNullOrWhiteSpace($InternalNetwork)) { $InternalNetwork = $paths.internal_network_name }
if ([string]::IsNullOrWhiteSpace($ProxyUrl)) { $ProxyUrl = "http://$($paths.proxy_container_name):3128" }
if ([string]::IsNullOrWhiteSpace($ResultsPath)) { $ResultsPath = $paths.engineering_canary_receipt_path }

function Write-CanaryReceipt {
    param($Status, $Extra)
    $receipt = New-XinaoBaseReceipt -SchemaVersion 'xinao.provider_egress_engineering_canary_receipt.v1' -Status $Status -Extra $Extra
    $receipt.research_invoked = $false
    $receipt.is_research_call = $false
    $receipt.scientific_research = $false
    $receipt.masquerades_as_research = $false
    $receipt.scientific_adoption = $false
    $receipt.science_restored = $false
    $receipt.parent_complete = $false
    $receipt.authority = $false
    $receipt.completion_claim_allowed = $false
    $receipt.secrets_present = $false
    $receipt.provider_egress_runtime_verified = $false
    $receipt.provider_egress_live_verified = $false
    if (-not $receipt.PSObject.Properties['path_class']) {
        $receipt | Add-Member -NotePropertyName path_class -NotePropertyValue 'engineering_canary' -Force
    } else {
        $receipt.path_class = 'engineering_canary'
    }
    if (-not $receipt.PSObject.Properties['observed_at']) {
        $receipt | Add-Member -NotePropertyName observed_at -NotePropertyValue (New-XinaoUtcNowIso) -Force
    }
    Assert-XinaoNoSecretLeak -Object $receipt
    $written = Write-XinaoJsonFile -Path $ResultsPath -Object $receipt
    $receipt | Add-Member -NotePropertyName receipt_path -NotePropertyValue $written -Force
    return $receipt
}

function Get-PostureIdentities {
    param($Paths)
    $ids = [ordered]@{
        internal_network_id = $null
        proxy_container_id  = $null
        proxy_image_id      = $null
        allowlist_sha256    = $null
        proxy_config_sha256 = $null
    }
    if (Test-Path -LiteralPath $Paths.posture_path -PathType Leaf) {
        $posture = Read-XinaoJsonFile -Path $Paths.posture_path
        $ids.internal_network_id = $posture.internal_network_id
        $ids.proxy_container_id = $posture.proxy_container_id
        $ids.proxy_image_id = $posture.proxy_image_id
        $ids.allowlist_sha256 = $posture.allowlist_sha256
        $ids.proxy_config_sha256 = $posture.proxy_config_sha256
    }
    return $ids
}

function Test-PostureIdentitiesComplete {
    param($Ids)
    foreach ($k in @('internal_network_id', 'proxy_container_id', 'proxy_image_id', 'allowlist_sha256', 'proxy_config_sha256')) {
        if ([string]::IsNullOrWhiteSpace([string]$Ids[$k])) { return $false }
    }
    return $true
}

function Resolve-ClientImageForExecute {
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
    $insp = Invoke-XinaoDocker -ArgumentList @(
        'image', 'inspect', $canonical, '--format', '{{.Id}}'
    ) -AllowNonZero
    if ($insp.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($insp.StdOut.Trim())) {
        throw 'EGRESS_CLIENT_IMAGE_NOT_LOCAL'
    }
    $observed = ConvertTo-XinaoCanonicalImageId -ImageId $insp.StdOut.Trim()
    if ($observed -ne $canonical -and -not $observed.EndsWith($canonical.Replace('sha256:', ''))) {
        # Prefer local observed Id; must remain immutable form.
        $canonical = $observed
    } else {
        $canonical = $observed
    }
    return [ordered]@{ ok = $true; reason_code = $null; image_id = $canonical }
}

function Resolve-CanaryImageAgainstRuntimeLock {
    # Thin wrapper: CanaryImageId is the active dedicated researcher release image,
    # bound to protocol-v2 pointer/manifest + runtime-lock donor provenance.
    param(
        [string]$ImageRef,
        [string]$PackageRoot,
        [string]$ResearcherContainerStateRoot,
        [switch]$Preflight
    )
    return (Resolve-XinaoCanaryImageAgainstActiveResearcherRelease `
        -ImageRef $ImageRef `
        -PackageRoot $PackageRoot `
        -ResearcherContainerStateRoot $ResearcherContainerStateRoot `
        -Preflight:$Preflight)
}

function Invoke-ConnectTransportProbe {
    param(
        [string]$InternalNetwork,
        [string]$ProxyUrl,
        [string]$ClientImageId,
        [string]$Target
    )
    $args = @(
        'run', '--rm', '--network', $InternalNetwork,
        '-e', "http_proxy=$ProxyUrl",
        '-e', "https_proxy=$ProxyUrl",
        '-e', "HTTP_PROXY=$ProxyUrl",
        '-e', "HTTPS_PROXY=$ProxyUrl",
        '-e', 'NO_PROXY=',
        '-e', 'ALL_PROXY=',
        $ClientImageId, 'wget', '-S', '-O', '/dev/null', '-T', '12', $Target
    )
    $result = Invoke-XinaoDocker -ArgumentList $args -AllowNonZero
    $out = $result.StdOut + "`n" + $result.StdErr
    if (Test-XinaoSecretLeakText -Text $out) {
        throw 'EGRESS_CANARY_OUTPUT_SECRET_LEAK'
    }
    $httpClass = $null
    if ($out -match 'HTTP/\S+\s+([0-9]{3})') {
        $code = [int]$Matches[1]
        $httpClass = [string]([Math]::Floor($code / 100) * 100)
    }
    $denied = $out -match '403|denied|Forbidden'
    $transportFail = $out -match "bad address|can'?t connect|timed out|network is unreachable|no route"
    $ok = (-not $denied) -and (-not $transportFail) -and ($result.ExitCode -eq 0 -or $null -ne $httpClass)
    return [ordered]@{
        ok                       = [bool]$ok
        exit_code                = $result.ExitCode
        http_status_class        = $httpClass
        real_provider_call       = $false
        provider_effect_verified = $false
        seal_eligible            = $false
        client_image_id          = $ClientImageId
        note                     = 'CONNECT transport subcheck only; not seal-eligible.'
    }
}

function Get-RealProviderCreateArgs {
    param(
        [string]$ContainerName,
        [string]$CanaryImageId,
        [string]$InternalNetwork,
        [string]$ProxyUrl,
        [string]$AuthHostPath,
        [string]$Prompt
    )
    return @(
        'create',
        '--name', $ContainerName,
        '--read-only',
        '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true',
        '--pids-limit', '128',
        '--memory', '2g',
        '--cpus', '2',
        '--network', $InternalNetwork,
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m,mode=1777',
        '--tmpfs', '/grok-home:rw,nosuid,nodev,size=256m,mode=0700',
        '--env', 'HOME=/grok-home',
        '--env', 'GROK_HOME=/grok-home/.grok',
        '--env', "HTTP_PROXY=$ProxyUrl",
        '--env', "HTTPS_PROXY=$ProxyUrl",
        '--env', "http_proxy=$ProxyUrl",
        '--env', "https_proxy=$ProxyUrl",
        '--env', 'NO_PROXY=',
        '--env', 'ALL_PROXY=',
        '--env', 'XINAO_CHAIN_CLASS=engineering_canary',
        '--label', 'io.xinao.researcher.chain=dedicated-xinao-science',
        '--label', 'io.xinao.project=xinao-researcher-egress',
        '--label', 'io.xinao.canary.class=engineering_canary',
        '--mount', "type=bind,source=$AuthHostPath,target=$($script:XinaoCanaryAuthContainerPath),readonly",
        '--entrypoint', '/usr/local/bin/grok',
        $CanaryImageId,
        '--no-auto-update',
        '-p', $Prompt,
        '-m', $script:XinaoCanaryRequestedModel,
        '--output-format', 'json',
        '--cwd', '/tmp',
        '--max-turns', '1',
        '--permission-mode', 'dontAsk',
        '--tools', '',
        '--no-subagents',
        '--no-memory',
        '--disable-web-search'
    )
}

try {
    Ensure-XinaoDirectory -Path $paths.state_root | Out-Null
    $allowlist = Read-XinaoJsonFile -Path $AllowlistPath
    $domains = @()
    if ($null -ne $allowlist.domains) {
        $domains = @($allowlist.domains | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }
    $firstDomain = $null
    if ($domains.Count -gt 0) {
        $exact = @($domains | Where-Object { -not $_.StartsWith('.') } | Sort-Object)
        if ($exact.Count -gt 0) {
            $firstDomain = $exact[0]
        } else {
            $firstDomain = $domains[0].TrimStart('.')
        }
    }

    $postureIds = Get-PostureIdentities -Paths $paths
    $clientPre = Resolve-ClientImageForExecute -ImageRef $ClientImageId -Preflight
    $objectIds = [ordered]@{
        internal_network_name = $InternalNetwork
        proxy_url             = $ProxyUrl
        proxy_container_name  = $paths.proxy_container_name
        allowlist_path        = [System.IO.Path]::GetFullPath($AllowlistPath)
        domain_count          = $domains.Count
        internal_network_id   = $postureIds.internal_network_id
        proxy_container_id    = $postureIds.proxy_container_id
        proxy_image_id        = $postureIds.proxy_image_id
        allowlist_sha256      = $postureIds.allowlist_sha256
        proxy_config_sha256   = $postureIds.proxy_config_sha256
        client_image_id       = $clientPre.image_id
    }

    $evidenceTemplate = [ordered]@{
        positive_token_present_observed = $false
        positive_token_value            = $null
        model_hint                      = $ModelHint
        model_observed                  = $null
        endpoint_hint                   = $EndpointHint
        endpoint_host_targeted          = $firstDomain
        connect_probe_target            = $(if ($firstDomain) { "https://$firstDomain/" } else { $null })
        http_status_class_observed      = $null
        client_image_id                 = $clientPre.image_id
        client_image_reason_code        = $clientPre.reason_code
        redaction                       = [ordered]@{
            authorization_headers_stripped = $true
            api_keys_forbidden             = $true
            auth_json_bytes_forbidden      = $true
            token_values_forbidden         = $true
            model_text_forbidden           = $true
            auth_host_path_forbidden       = $true
        }
    }

    # ---------- Empty allowlist: fail closed ----------
    if ($domains.Count -eq 0) {
        $receipt = Write-CanaryReceipt -Status 'failed' -Extra @{
            mode                         = $(if ($PreflightOnly -or $WhatIf) { 'preflight_only' } else { 'execute' })
            reason_code                  = 'EMPTY_ALLOWLIST_NO_POSITIVE_CANARY'
            object_identities            = $objectIds
            engineering_evidence         = $evidenceTemplate
            real_provider_call           = $false
            provider_effect_verified     = $false
            allow_real_provider_call_requested = [bool]$RealProviderCall
            note                         = 'Empty allowlist is fail-closed; engineering positive canary cannot PASS. Not research().'
            docker_mutated               = $false
            connect_only                 = (-not $RealProviderCall)
        }
        Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
        exit 2
    }

    # ---------- Real provider path validation (preflight + execute) ----------
    if ($RealProviderCall) {
        try {
            if ([string]::IsNullOrWhiteSpace($CanaryImageId)) { throw 'CANARY_IMAGE_ID_REQUIRED' }
            if (-not (Test-XinaoImmutableImageIdFormat -ImageId $CanaryImageId)) { throw 'CANARY_IMAGE_ID_NOT_IMMUTABLE' }
            $resolvedAuth = Assert-XinaoAuthFilePathLiteral -AuthFilePath $AuthFilePath
            $imagePlan = Resolve-CanaryImageAgainstRuntimeLock `
                -ImageRef $CanaryImageId `
                -PackageRoot $PackageRoot `
                -ResearcherContainerStateRoot $ResearcherContainerStateRoot `
                -Preflight
        } catch {
            $code = [string]$_.Exception.Message
            if ($code -match 'EGRESS_AUTH_PATH_|CANARY_IMAGE_|EGRESS_RUNTIME_LOCK|ACTIVE_RESEARCHER_|RELEASE_SOURCE_|EGRESS_CANARY_') {
                $reason = $code
            } else {
                $reason = 'EGRESS_AUTH_OR_IMAGE_ADMISSION_FAILED'
            }
            $receipt = Write-CanaryReceipt -Status 'failed' -Extra @{
                mode                     = 'error'
                reason_code              = $reason
                real_provider_call       = $false
                provider_effect_verified = $false
                note                     = 'RealProviderCall requires explicit existing auth file (no path/content in receipt) and CanaryImageId equal to the active protocol-v2 dedicated researcher release image (not the unlabeled extraction donor).'
                docker_mutated           = $false
                researcher_container_state_root = $ResearcherContainerStateRoot
            }
            Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
            exit 2
        }

        $plannedCreateRedacted = @(
            'create', '--name', 'xinao-researcher-eng-canary',
            '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--pids-limit', '128', '--memory', '2g', '--cpus', '2',
            '--network', $InternalNetwork,
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m,mode=1777',
            '--tmpfs', '/grok-home:rw,nosuid,nodev,size=256m,mode=0700',
            '--env', 'HOME=/grok-home', '--env', 'GROK_HOME=/grok-home/.grok',
            '--env', "HTTP_PROXY=$ProxyUrl", '--env', "HTTPS_PROXY=$ProxyUrl",
            '--env', "http_proxy=$ProxyUrl", '--env', "https_proxy=$ProxyUrl",
            '--env', 'NO_PROXY=', '--env', 'ALL_PROXY=',
            '--mount', 'type=bind,source=<REDACTED_AUTH_HOST_PATH>,target=<CLI_AUTH_MOUNT>,readonly',
            '--entrypoint', '/usr/local/bin/grok', $imagePlan.canary_image_id,
            '--no-auto-update', '-p', '<FIXED_NON_SCIENTIFIC_PROMPT>', '-m', $script:XinaoCanaryRequestedModel,
            '--output-format', 'json', '--cwd', '/tmp', '--max-turns', '1',
            '--permission-mode', 'dontAsk', '--tools', '', '--no-subagents', '--no-memory', '--disable-web-search'
        )

        if ($PreflightOnly -or $WhatIf) {
            $evidenceTemplate.planned_actions = @(
                "docker $($plannedCreateRedacted -join ' ')"
                'docker start -a <container> (async stdout/stderr + timeout)'
                'parse CLI JSON to redacted metadata; delete exact temp raw file'
                'docker rm -f <container> (observed cleanup only)'
            )
            $receipt = Write-CanaryReceipt -Status 'planned' -Extra @{
                mode                               = $(if ($WhatIf) { 'whatif' } else { 'preflight_only' })
                object_identities                  = $objectIds
                engineering_evidence               = $evidenceTemplate
                real_provider_call                 = $false
                provider_effect_verified           = $false
                allow_real_provider_call_requested = $true
                canary_image_id                    = $imagePlan.canary_image_id
                active_researcher_image_id         = $imagePlan.active_researcher_image_id
                pinned_donor_image_id              = $imagePlan.pinned_donor_image_id
                release_id                         = $imagePlan.release_id
                researcher_container_state_root    = $imagePlan.researcher_container_state_root
                labels_verified                    = [bool]$imagePlan.labels_verified
                auth_mounted_read_only             = $true
                auth_content_persisted             = $false
                endpoint_host                      = $script:XinaoCanaryEndpointHost
                requested_model                    = $script:XinaoCanaryRequestedModel
                note                               = 'Real provider canary preflight only. CanaryImageId is the active dedicated researcher release image (donor is provenance only). Worker must not execute. Auth host path and contents not loaded into receipt. CONNECT remains separate transport subcheck.'
                docker_mutated                     = $false
                connect_only                       = $false
            }
            Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
            exit 0
        }

        # ---------- Execute real provider call (Owner only) ----------
        if (-not (Test-XinaoCommandAvailable -Name 'docker')) {
            throw 'EGRESS_DOCKER_CLI_MISSING'
        }
        if (-not (Test-PostureIdentitiesComplete -Ids $postureIds)) {
            $receipt = Write-CanaryReceipt -Status 'failed' -Extra @{
                mode                     = 'execute'
                reason_code              = 'POSTURE_IDENTITIES_INCOMPLETE'
                object_identities        = $objectIds
                real_provider_call       = $false
                provider_effect_verified = $false
                note                     = 'Seal-eligible real canary requires complete posture identities.'
                docker_mutated           = $false
            }
            Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
            exit 2
        }

        $imageLive = Resolve-CanaryImageAgainstRuntimeLock `
            -ImageRef $CanaryImageId `
            -PackageRoot $PackageRoot `
            -ResearcherContainerStateRoot $ResearcherContainerStateRoot
        $canonicalCanaryImage = [string]$imageLive.canary_image_id
        if ($canonicalCanaryImage -eq [string]$imageLive.pinned_donor_image_id -and `
            $canonicalCanaryImage -ne [string]$imageLive.active_researcher_image_id) {
            throw 'CANARY_IMAGE_IS_DONOR_NOT_RESEARCHER'
        }

        # CONNECT transport subcheck requires immutable local client image.
        $clientLive = Resolve-ClientImageForExecute -ImageRef $ClientImageId
        $objectIds.client_image_id = $clientLive.image_id
        $evidenceTemplate.client_image_id = $clientLive.image_id
        $connectTarget = "https://$firstDomain/"
        $connectResult = Invoke-ConnectTransportProbe -InternalNetwork $InternalNetwork -ProxyUrl $ProxyUrl -ClientImageId $clientLive.image_id -Target $connectTarget

        # Re-admit auth immediately before bind (still no content read).
        $resolvedAuth = Assert-XinaoAuthFilePathLiteral -AuthFilePath $AuthFilePath

        Ensure-XinaoDirectory -Path $paths.temp_root | Out-Null
        $rawDir = Join-Path $paths.temp_root 'engineering_canary_raw'
        Ensure-XinaoDirectory -Path $rawDir | Out-Null
        $rawFile = Join-Path $rawDir ("canary_{0}.stdout.json" -f [guid]::NewGuid().ToString('N'))
        $rawFile = Assert-XinaoRawCleanupTargetContained -RawPath $rawFile -OwnedTempRoot $paths.temp_root

        $containerName = 'xinao-researcher-eng-canary-' + ([guid]::NewGuid().ToString('N').Substring(0, 12))
        $containerId = $null
        $containerRemoved = $false
        $rawPersisted = $true
        $meta = $null
        $dockerExit = $null

        try {
            $createArgs = Get-RealProviderCreateArgs `
                -ContainerName $containerName `
                -CanaryImageId $canonicalCanaryImage `
                -InternalNetwork $InternalNetwork `
                -ProxyUrl $ProxyUrl `
                -AuthHostPath $resolvedAuth `
                -Prompt $script:XinaoCanaryFixedPrompt
            $created = Invoke-XinaoDocker -ArgumentList $createArgs -AllowNonZero
            if ($created.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($created.StdOut.Trim())) {
                throw 'EGRESS_CANARY_CONTAINER_CREATE_FAILED'
            }
            $containerId = $created.StdOut.Trim()

            $insp = Invoke-XinaoDocker -ArgumentList @('inspect', $containerId, '--format', '{{json .}}') -AllowNonZero
            if ($insp.ExitCode -ne 0) { throw 'EGRESS_CANARY_CONTAINER_INSPECT_FAILED' }
            $inspectBefore = $insp.StdOut | ConvertFrom-Json -Depth 50
            $hostCfg = $inspectBefore.HostConfig
            $netKeys = @($inspectBefore.NetworkSettings.Networks.PSObject.Properties.Name)
            $internalOnly = ($netKeys.Count -eq 1 -and $netKeys[0] -eq $InternalNetwork)
            $authRo = $false
            foreach ($m in @($inspectBefore.Mounts)) {
                if ([string]$m.Destination -eq $script:XinaoCanaryAuthContainerPath -and $m.RW -eq $false) {
                    $authRo = $true
                }
            }
            if (-not $internalOnly) { throw 'EGRESS_CANARY_NETWORK_NOT_INTERNAL_ONLY' }
            if (-not $authRo) { throw 'EGRESS_CANARY_AUTH_NOT_READONLY_MOUNT' }
            if ($hostCfg.ReadonlyRootfs -ne $true) { throw 'EGRESS_CANARY_ROOTFS_NOT_READONLY' }
            if ($hostCfg.NetworkMode -ne $InternalNetwork) { throw 'EGRESS_CANARY_NETWORK_MODE_INVALID' }

            # Start with async stdout/stderr drain + host timeout (no redirected-pipe deadlock).
            $start = Invoke-XinaoNativeProcess `
                -FilePath (Get-XinaoDockerCli) `
                -ArgumentList @('start', '-a', $containerId) `
                -AllowNonZero `
                -TimeoutSeconds ([Math]::Max(1, $ProviderTimeoutSeconds))
            $dockerExit = $start.ExitCode
            $stdout = $start.StdOut
            $stderr = $start.StdErr
            if (Test-XinaoSecretLeakText -Text ($stdout + "`n" + $stderr)) {
                throw 'EGRESS_CANARY_OUTPUT_SECRET_LEAK'
            }
            if ($dockerExit -ne 0) {
                throw 'EGRESS_CANARY_DOCKER_EXIT_NONZERO'
            }
            $utf8 = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText($rawFile, $stdout, $utf8)
            $meta = ConvertFrom-XinaoGrokCliJsonText -JsonText $stdout
        }
        catch {
            if ([string]$_.Exception.Message -match 'EGRESS_PROCESS_TIMEOUT') {
                if (-not [string]::IsNullOrWhiteSpace($containerId)) {
                    Invoke-XinaoDocker -ArgumentList @('kill', $containerId) -AllowNonZero | Out-Null
                }
                $meta = [ordered]@{
                    ok = $false
                    reason_code = 'EGRESS_CANARY_PROVIDER_TIMEOUT'
                    stop_reason = $null
                    observed_backend_model = $null
                    output_tokens = 0
                    input_tokens = 0
                    total_tokens = 0
                    usage_accounting_complete = $false
                    raw_sha256 = $null
                }
            } elseif ($null -eq $meta) {
                $meta = [ordered]@{
                    ok = $false
                    reason_code = [string]$_.Exception.Message
                    stop_reason = $null
                    observed_backend_model = $null
                    output_tokens = 0
                    input_tokens = 0
                    total_tokens = 0
                    usage_accounting_complete = $false
                    raw_sha256 = $null
                }
            }
        }
        finally {
            # Always remove only the exact disposable container; re-inspect must prove absence.
            if (-not [string]::IsNullOrWhiteSpace($containerId)) {
                $rm = Invoke-XinaoDocker -ArgumentList @('rm', '--force', $containerId) -AllowNonZero
                $containerRemoved = ($rm.ExitCode -eq 0)
                if ($containerRemoved) {
                    $re = Invoke-XinaoDocker -ArgumentList @('inspect', $containerId, '--format', '{{.Id}}') -AllowNonZero
                    # Absence: inspect must fail closed (nonzero or empty). If still present, fail closed.
                    if ($re.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($re.StdOut.Trim())) {
                        $containerRemoved = $false
                    }
                }
            } elseif (-not [string]::IsNullOrWhiteSpace($containerName)) {
                $rm = Invoke-XinaoDocker -ArgumentList @('rm', '--force', $containerName) -AllowNonZero
                $containerRemoved = ($rm.ExitCode -eq 0)
                if ($containerRemoved) {
                    $re = Invoke-XinaoDocker -ArgumentList @('inspect', $containerName, '--format', '{{.Id}}') -AllowNonZero
                    if ($re.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($re.StdOut.Trim())) {
                        $containerRemoved = $false
                    }
                }
            }
            # Always delete exact raw file when present (never a directory).
            if (Test-Path -LiteralPath $rawFile -PathType Leaf) {
                try {
                    Remove-XinaoExactRawFile -RawPath $rawFile -OwnedTempRoot $paths.temp_root | Out-Null
                } catch { }
            }
            $rawPersisted = Test-Path -LiteralPath $rawFile -PathType Leaf
        }

        $effectOk = (
            $null -ne $meta -and
            $meta.ok -eq $true -and
            $dockerExit -eq 0 -and
            $meta.stop_reason -eq 'EndTurn' -and
            $meta.observed_backend_model -eq $script:XinaoCanaryObservedBackendModel -and
            [bool]$meta.usage_accounting_complete -and
            [int]$meta.output_tokens -gt 0 -and
            [bool]$containerRemoved
        )

        if ($effectOk -and -not $rawPersisted -and $containerRemoved) {
            $sealReceipt = New-XinaoEngineeringCanarySealReceipt `
                -Meta $meta `
                -PostureIds $postureIds `
                -CanaryImageId $canonicalCanaryImage `
                -ConnectProbeOk ([bool]$connectResult.ok) `
                -CanaryContainerId $containerId `
                -CanaryContainerRemoved $containerRemoved `
                -RawOutputSha256 $(if ($meta.raw_sha256) { [string]$meta.raw_sha256 } else { '' }) `
                -ObjectIdentities $objectIds
            # Write seal-eligible receipt with only allowed keys (builder already filtered).
            $written = Write-XinaoJsonFile -Path $ResultsPath -Object $sealReceipt
            $sealReceipt | Add-Member -NotePropertyName receipt_path -NotePropertyValue $written -Force
            Write-Output (ConvertTo-XinaoStrictJson -InputObject $sealReceipt)
            exit 0
        }

        $reason = if ($null -ne $meta -and $meta.reason_code) { [string]$meta.reason_code } else { 'PROVIDER_EFFECT_NOT_VERIFIED' }
        if ($rawPersisted) { $reason = 'EGRESS_CANARY_RAW_NOT_DELETED' }
        if (-not $containerRemoved) { $reason = 'EGRESS_CANARY_CONTAINER_NOT_REMOVED' }
        $receipt = Write-CanaryReceipt -Status 'failed' -Extra @{
            mode                       = 'execute_real_provider'
            path_class                 = 'engineering_canary'
            reason_code                = $reason
            real_provider_call         = $true
            provider_effect_verified   = $false
            requested_model            = $script:XinaoCanaryRequestedModel
            observed_backend_model     = $(if ($null -ne $meta) { $meta.observed_backend_model } else { $null })
            stop_reason                = $(if ($null -ne $meta) { $meta.stop_reason } else { $null })
            output_tokens              = $(if ($null -ne $meta) { [int]$meta.output_tokens } else { 0 })
            usage_accounting_complete  = $(if ($null -ne $meta) { [bool]$meta.usage_accounting_complete } else { $false })
            endpoint_host              = $script:XinaoCanaryEndpointHost
            canary_image_id            = $canonicalCanaryImage
            internal_network_id        = [string]$postureIds.internal_network_id
            proxy_container_id         = [string]$postureIds.proxy_container_id
            proxy_image_id             = [string]$postureIds.proxy_image_id
            allowlist_sha256           = [string]$postureIds.allowlist_sha256
            proxy_config_sha256        = [string]$postureIds.proxy_config_sha256
            internal_network_only      = $true
            auth_mounted_read_only     = $true
            auth_content_persisted     = $false
            raw_output_persisted       = [bool]$rawPersisted
            connect_probe_ok           = [bool]$connectResult.ok
            canary_container_id        = $containerId
            canary_container_removed   = [bool]$containerRemoved
            probe_exit_code            = $dockerExit
            docker_mutated             = $true
            note                       = 'Real provider call did not satisfy positive-effect contract. Not research().'
        }
        Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
        exit 1
    }

    # ---------- CONNECT-only path (default; never seal-eligible) ----------
    if ($PreflightOnly -or $WhatIf) {
        $receipt = Write-CanaryReceipt -Status 'planned' -Extra @{
            mode                     = $(if ($WhatIf) { 'whatif' } else { 'preflight_only' })
            object_identities        = $objectIds
            engineering_evidence     = $evidenceTemplate
            real_provider_call       = $false
            provider_effect_verified = $false
            allow_real_provider_call_requested = $false
            connect_only             = $true
            note                     = 'CONNECT transport preflight only. Not seal-eligible. Use -RealProviderCall with explicit AuthFilePath and active dedicated researcher CanaryImageId (protocol-v2 release image, not extraction donor) for positive provider effect. Execute requires immutable -ClientImageId.'
            docker_mutated           = $false
        }
        Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
        exit 0
    }

    if (-not (Test-XinaoCommandAvailable -Name 'docker')) {
        throw 'EGRESS_DOCKER_CLI_MISSING'
    }
    $clientLive = Resolve-ClientImageForExecute -ImageRef $ClientImageId
    $objectIds.client_image_id = $clientLive.image_id
    $evidenceTemplate.client_image_id = $clientLive.image_id

    $target = "https://$firstDomain/"
    $connectResult = Invoke-ConnectTransportProbe -InternalNetwork $InternalNetwork -ProxyUrl $ProxyUrl -ClientImageId $clientLive.image_id -Target $target
    $evidence = $evidenceTemplate
    $evidence.http_status_class_observed = $connectResult.http_status_class
    $evidence.endpoint_host_targeted = $firstDomain
    $evidence.connect_probe_target = $target
    $evidence.model_observed = $null
    $evidence.positive_token_present_observed = $false

    $status = if ($connectResult.ok) { 'observed' } else { 'failed' }
    $receipt = Write-CanaryReceipt -Status $status -Extra @{
        mode                       = 'execute_connect_only'
        object_identities          = $objectIds
        engineering_evidence       = $evidence
        probe_exit_code            = $connectResult.exit_code
        probe_ok                   = [bool]$connectResult.ok
        connect_probe_ok           = [bool]$connectResult.ok
        real_provider_call         = $false
        provider_effect_verified   = $false
        connect_only               = $true
        docker_mutated             = $true
        note                       = 'CONNECT-only engineering transport canary. Not seal-eligible. Not research(); not scientific adoption. Use -RealProviderCall for positive provider effect.'
    }
    Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
    if (-not $connectResult.ok) { exit 1 }
    exit 0
}
catch {
    $msg = [string]$_.Exception.Message
    # Never put host auth paths into receipts.
    if ($msg -match '[A-Za-z]:\\' -or $msg -match 'auth\.json') {
        if ($msg -match 'EGRESS_AUTH_') {
            $safe = ($msg -split ':')[0]
        } else {
            $safe = 'EGRESS_CANARY_FAILED'
        }
    } else {
        $safe = $msg
    }
    $receipt = Write-CanaryReceipt -Status 'failed' -Extra @{
        mode                     = 'error'
        reason_code              = $safe
        real_provider_call       = $false
        provider_effect_verified = $false
        docker_mutated           = $false
        connect_only             = (-not $RealProviderCall)
    }
    Write-Output (ConvertTo-XinaoStrictJson -InputObject $receipt)
    exit 2
}
