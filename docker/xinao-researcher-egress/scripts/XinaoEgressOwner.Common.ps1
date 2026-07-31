#Requires -Version 7.0
<#
.SYNOPSIS
  Shared pure helpers for XINAO researcher egress Windows Owner carriers.
.DESCRIPTION
  Dot-source only. Loading this file never mutates Docker, never reads credentials,
  and never claims completion. Safe for static import and offline tests.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:XinaoEgressSchemaStatuses = @('planned', 'observed', 'verified', 'partial', 'failed')

$script:XinaoEgressProxyContainerName = 'xinao-researcher-egress-proxy'
$script:XinaoEgressInternalNetworkName = 'xinao_researcher_internal'
$script:XinaoEgressExternalNetworkName = 'xinao_provider_egress_ext'
$script:XinaoEgressChainLabel = 'io.xinao.researcher.chain'
$script:XinaoEgressChainLabelValue = 'dedicated-xinao-science'
$script:XinaoEgressProjectLabel = 'io.xinao.project'
$script:XinaoEgressProjectLabelValue = 'xinao-researcher-egress'

$script:XinaoEgressForbiddenExactNames = @(
    'ssrf_proxy',
    'ssrf_proxy_network',
    'docker_ssrf_proxy_network',
    '/ssrf_proxy'
)

$script:XinaoEgressForbiddenNameSubstrings = @(
    'ssrf_proxy',
    'dify'
)

$script:XinaoEgressSecretTokenPatterns = @(
    'authorization\s*[:=]',
    'bearer\s+[A-Za-z0-9\-\._~\+/]+=*',
    'api[_-]?key\s*[:=]',
    'auth\.json',
    'password\s*[:=]',
    'sk-[A-Za-z0-9]{8,}',
    'xai-[A-Za-z0-9]{8,}'
)

function Get-XinaoEgressScriptRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false)]
        [string]$AnchorPath = $PSScriptRoot
    )
    if ([string]::IsNullOrWhiteSpace($AnchorPath)) {
        throw 'EGRESS_SCRIPT_ROOT_UNRESOLVED'
    }
    return [System.IO.Path]::GetFullPath($AnchorPath)
}

function Get-XinaoEgressPackageRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false)]
        [string]$ScriptsRoot = (Get-XinaoEgressScriptRoot)
    )
    return [System.IO.Path]::GetFullPath((Join-Path $ScriptsRoot '..'))
}

function Get-XinaoDefaultStateRoot {
    [CmdletBinding()]
    param()
    if (-not [string]::IsNullOrWhiteSpace($env:XINAO_EGRESS_STATE_ROOT)) {
        return [System.IO.Path]::GetFullPath($env:XINAO_EGRESS_STATE_ROOT)
    }
    return [System.IO.Path]::GetFullPath('D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\researcher_container\egress')
}

function Get-XinaoDefaultTempRoot {
    [CmdletBinding()]
    param()
    if (-not [string]::IsNullOrWhiteSpace($env:XINAO_EGRESS_TEMP_ROOT)) {
        return [System.IO.Path]::GetFullPath($env:XINAO_EGRESS_TEMP_ROOT)
    }
    return [System.IO.Path]::GetFullPath('D:\XINAO_RESEARCH_RUNTIME\tmp\xinao_egress_owner')
}

function Get-XinaoEgressPathContract {
    [CmdletBinding()]
    param(
        [string]$StateRoot = (Get-XinaoDefaultStateRoot),
        [string]$TempRoot = (Get-XinaoDefaultTempRoot),
        [string]$PackageRoot = (Get-XinaoEgressPackageRoot)
    )
    $state = [System.IO.Path]::GetFullPath($StateRoot)
    $temp = [System.IO.Path]::GetFullPath($TempRoot)
    $pkg = [System.IO.Path]::GetFullPath($PackageRoot)
    return [ordered]@{
        schema_version                    = 'xinao.provider_egress_windows_path_contract.v1'
        package_root                      = $pkg
        state_root                        = $state
        temp_root                         = $temp
        image_pin_path                    = (Join-Path $pkg 'image-pin.v1.json')
        allowlist_path                    = (Join-Path $pkg 'allowlist.v1.json')
        template_path                     = (Join-Path $pkg 'squid.conf.template')
        compose_path                      = (Join-Path $pkg 'docker-compose.yaml')
        render_script_path                = (Join-Path $pkg 'render_squid_config.py')
        posture_path                      = (Join-Path $state 'current_posture.v1.json')
        live_seal_path                    = (Join-Path $state 'current_live_seal.v1.json')
        negative_suite_receipt_path       = (Join-Path $state 'negative_suite_receipt.v1.json')
        engineering_canary_receipt_path   = (Join-Path $state 'engineering_canary_receipt.v1.json')
        cleanup_receipt_path              = (Join-Path $state 'cleanup_receipt.v1.json')
        image_pin_readback_path           = (Join-Path $state 'image_pin_readback.v1.json')
        provision_receipt_path            = (Join-Path $state 'provision_receipt.v1.json')
        fresh_process_readback_path       = (Join-Path $state 'fresh_process_readback.v1.json')
        discovery_receipt_path            = (Join-Path $state 'discovery_receipt.v1.json')
        proxy_container_name              = $script:XinaoEgressProxyContainerName
        internal_network_name             = $script:XinaoEgressInternalNetworkName
        external_network_name             = $script:XinaoEgressExternalNetworkName
        chain_label                       = $script:XinaoEgressChainLabel
        chain_label_value                 = $script:XinaoEgressChainLabelValue
        completion_claim_allowed          = $false
        authority                         = $false
        wsl_required                      = $false
        git_bash_required                 = $false
        platform                          = 'windows_docker_desktop_powershell7'
    }
}

function Assert-XinaoReceiptStatus {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Status
    )
    if ($script:XinaoEgressSchemaStatuses -notcontains $Status) {
        throw "EGRESS_RECEIPT_STATUS_INVALID:$Status"
    }
}

function New-XinaoUtcNowIso {
    [CmdletBinding()]
    param()
    return [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
}

function ConvertTo-XinaoStrictJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $InputObject,
        [int]$Depth = 40
    )
    # Depth-stable, UTF-8 friendly; avoid trailing-space quirks from ConvertTo-Json -Compress alone.
    return ($InputObject | ConvertTo-Json -Depth $Depth -Compress:$false)
}

function Write-XinaoJsonFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        $Object
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    $dir = Split-Path -Parent $full
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $json = ConvertTo-XinaoStrictJson -InputObject $Object
    # Ensure trailing newline; UTF-8 no BOM for platform-neutral validators.
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($full, ($json.TrimEnd() + [Environment]::NewLine), $utf8)
    return $full
}

function Read-XinaoJsonFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        throw "EGRESS_JSON_MISSING:$full"
    }
    $raw = [System.IO.File]::ReadAllText($full)
    return ($raw | ConvertFrom-Json -Depth 100)
}

function Test-XinaoSecretLeakText {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Text
    )
    $lower = $Text.ToLowerInvariant()
    foreach ($pattern in $script:XinaoEgressSecretTokenPatterns) {
        if ([regex]::IsMatch($lower, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Assert-XinaoNoSecretLeak {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $Object
    )
    $blob = ConvertTo-XinaoStrictJson -InputObject $Object
    if (Test-XinaoSecretLeakText -Text $blob) {
        throw 'EGRESS_RECEIPT_SECRET_LEAK'
    }
}

function Resolve-XinaoPythonInterpreter {
    [CmdletBinding()]
    param(
        [string]$PackageRoot = (Get-XinaoEgressPackageRoot),
        [string]$ExplicitPath = ''
    )
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $candidate = [System.IO.Path]::GetFullPath($ExplicitPath)
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "EGRESS_PYTHON_MISSING:$candidate"
        }
        return $candidate
    }
    if (-not [string]::IsNullOrWhiteSpace($env:XINAO_PYTHON)) {
        $envPy = [System.IO.Path]::GetFullPath($env:XINAO_PYTHON)
        if (Test-Path -LiteralPath $envPy -PathType Leaf) {
            return $envPy
        }
    }
    # Prefer repository interpreter if present (worktree or monorepo root layouts).
    $repoCandidates = @(
        (Join-Path $PackageRoot '..\..\..\.venv\Scripts\python.exe'),
        (Join-Path $PackageRoot '..\..\..\..\.venv\Scripts\python.exe'),
        (Join-Path (Get-Location) '.venv\Scripts\python.exe')
    )
    foreach ($rel in $repoCandidates) {
        try {
            $full = [System.IO.Path]::GetFullPath($rel)
            if (Test-Path -LiteralPath $full -PathType Leaf) {
                return $full
            }
        } catch {
            continue
        }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $cmd -and -not [string]::IsNullOrWhiteSpace($cmd.Source)) {
        return [string]$cmd.Source
    }
    throw 'EGRESS_PYTHON_NOT_FOUND'
}

function Invoke-XinaoNativeProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,
        [switch]$AllowNonZero,
        [int]$TimeoutSeconds = 0
    )
    # System.Diagnostics.Process avoids Start-Process pipe identity issues on Windows.
    # Always drain stdout/stderr asynchronously while waiting to avoid redirected-pipe deadlock.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    foreach ($arg in $ArgumentList) {
        [void]$psi.ArgumentList.Add([string]$arg)
    }
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $timedOut = $false
    if ($TimeoutSeconds -gt 0) {
        $exited = $proc.WaitForExit([Math]::Max(1, $TimeoutSeconds) * 1000)
        if (-not $exited) {
            $timedOut = $true
            try { $proc.Kill($true) } catch { }
            try { [void]$proc.WaitForExit(5000) } catch { }
        }
    } else {
        $proc.WaitForExit()
    }
    # Bound post-exit/post-kill pipe drain so a pathological child cannot hang forever.
    $drainTimeoutMs = if ($timedOut) { 5000 } else { 30000 }
    $stdout = ''
    $stderr = ''
    try {
        if ($stdoutTask.Wait($drainTimeoutMs)) {
            $stdout = $stdoutTask.GetAwaiter().GetResult()
        } else {
            $stdout = ''
        }
    } catch { $stdout = '' }
    try {
        if ($stderrTask.Wait($drainTimeoutMs)) {
            $stderr = $stderrTask.GetAwaiter().GetResult()
        } else {
            $stderr = ''
        }
    } catch { $stderr = '' }
    if ($timedOut) {
        throw "EGRESS_PROCESS_TIMEOUT:file=$([System.IO.Path]::GetFileName($FilePath))"
    }
    $code = $proc.ExitCode
    if (($code -ne 0) -and (-not $AllowNonZero)) {
        throw "EGRESS_PROCESS_FAILED:exit=$code file=$([System.IO.Path]::GetFileName($FilePath))"
    }
    return [pscustomobject]@{
        ExitCode = $code
        StdOut   = $stdout
        StdErr   = $stderr
        Planned  = $null
        TimedOut = $false
    }
}

function Invoke-XinaoPythonJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,
        [switch]$AllowNonZero
    )
    return Invoke-XinaoNativeProcess -FilePath $PythonPath -ArgumentList $ArgumentList -AllowNonZero:$AllowNonZero
}

function Test-XinaoImagePinResolved {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $PinObject
    )
    if ($null -eq $PinObject) {
        return $false
    }
    $digest = $PinObject.image_digest
    $imageId = $PinObject.image_id
    $hasDigest = -not [string]::IsNullOrWhiteSpace([string]$digest)
    $hasId = -not [string]::IsNullOrWhiteSpace([string]$imageId)
    return ($hasDigest -or $hasId)
}

function Get-XinaoImageAuthorityRef {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $PinObject
    )
    if (-not [string]::IsNullOrWhiteSpace([string]$PinObject.image_digest)) {
        return [string]$PinObject.image_digest
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$PinObject.image_id)) {
        return [string]$PinObject.image_id
    }
    throw 'IMAGE_PIN_UNRESOLVED'
}

function Test-XinaoComposeSafetyText {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ComposeText
    )
    $issues = [System.Collections.Generic.List[string]]::new()
    foreach ($line in ($ComposeText -split "`r?`n")) {
        $stripped = $line.Trim()
        if ($stripped -match '^\s*ports\s*:') {
            $issues.Add('HOST_PORT_PUBLISH_FORBIDDEN') | Out-Null
        }
        if ($stripped -match '^\s*container_name\s*:\s*ssrf_proxy\s*$') {
            $issues.Add('DIFY_CONTAINER_REUSE_FORBIDDEN') | Out-Null
        }
        if ($stripped -match '^\s*ssrf_proxy_network\s*:') {
            $issues.Add('DIFY_NETWORK_REUSE_FORBIDDEN') | Out-Null
        }
        if ($stripped -match '^\s*ssrf_proxy\s*:') {
            $issues.Add('DIFY_SERVICE_REUSE_FORBIDDEN') | Out-Null
        }
    }
    return , @($issues.ToArray())
}

function Assert-XinaoNotForbiddenDockerTarget {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Name,
        [string]$Id = ''
    )
    $normalized = $Name.Trim()
    if ($normalized.StartsWith('/')) {
        $normalized = $normalized.Substring(1)
    }
    $lower = $normalized.ToLowerInvariant()
    foreach ($exact in $script:XinaoEgressForbiddenExactNames) {
        $exactNorm = $exact.TrimStart('/').ToLowerInvariant()
        if ($lower -eq $exactNorm) {
            throw "EGRESS_FOREIGN_OR_DIFY_TARGET_REJECTED:$normalized"
        }
    }
    foreach ($sub in $script:XinaoEgressForbiddenNameSubstrings) {
        if ($lower.Contains($sub.ToLowerInvariant())) {
            throw "EGRESS_FOREIGN_OR_DIFY_TARGET_REJECTED:$normalized"
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($Id) -and $Id.ToLowerInvariant().Contains('ssrf')) {
        throw "EGRESS_FOREIGN_OR_DIFY_TARGET_REJECTED_ID:$Id"
    }
    return $true
}

function Test-XinaoExactCleanupCandidate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [string]$Id = '',
        [hashtable]$Labels = @{},
        [ValidateSet('container', 'network')]
        [string]$Kind = 'container'
    )
    # Exact allowlist of removable object identities. Never broad glob selection.
    Assert-XinaoNotForbiddenDockerTarget -Name $Name -Id $Id | Out-Null
    $normalized = $Name.Trim().TrimStart('/')
    $allowedContainers = @($script:XinaoEgressProxyContainerName)
    $allowedNetworks = @(
        $script:XinaoEgressInternalNetworkName,
        $script:XinaoEgressExternalNetworkName
    )
    if ($Kind -eq 'network') {
        if ($allowedNetworks -notcontains $normalized) {
            return $false
        }
        return $true
    }
    if ($allowedContainers -contains $normalized) {
        return $true
    }
    # Researcher chain containers: require exact chain label AND name prefix.
    $chainOk = $false
    if ($Labels.ContainsKey($script:XinaoEgressChainLabel)) {
        $chainOk = [string]$Labels[$script:XinaoEgressChainLabel] -eq $script:XinaoEgressChainLabelValue
    }
    if ($chainOk -and ($normalized -like 'xinao-researcher-*')) {
        return $true
    }
    return $false
}

function Test-XinaoCommandAvailable {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-XinaoDockerCli {
    [CmdletBinding()]
    param()
    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        throw 'EGRESS_DOCKER_CLI_MISSING'
    }
    return [string]$cmd.Source
}

function Invoke-XinaoDocker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,
        [switch]$AllowNonZero,
        [switch]$WhatIfPlan
    )
    if ($WhatIfPlan) {
        return [pscustomobject]@{
            ExitCode = 0
            StdOut   = ''
            StdErr   = ''
            Planned  = @('docker') + $ArgumentList
        }
    }
    $docker = Get-XinaoDockerCli
    try {
        return Invoke-XinaoNativeProcess -FilePath $docker -ArgumentList $ArgumentList -AllowNonZero:$AllowNonZero
    } catch {
        throw "EGRESS_DOCKER_FAILED:args=$($ArgumentList -join ' ') err=$([string]$_.Exception.Message)"
    }
}

function New-XinaoBaseReceipt {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$SchemaVersion,
        [Parameter(Mandatory = $true)]
        [ValidateSet('planned', 'observed', 'verified', 'partial', 'failed')]
        [string]$Status,
        [hashtable]$Extra = @{}
    )
    Assert-XinaoReceiptStatus -Status $Status
    $receipt = [ordered]@{
        schema_version                     = $SchemaVersion
        status                             = $Status
        executed_at                        = (New-XinaoUtcNowIso)
        provider_egress_runtime_verified   = $false
        provider_egress_live_verified      = $false
        secrets_present                    = $false
        completion_claim_allowed           = $false
        authority                          = $false
        science_restored                   = $false
        parent_complete                    = $false
        scientific_research                = $false
        research_invoked                   = $false
        wsl_used                           = $false
        git_bash_used                      = $false
        carrier                            = 'windows_powershell7_docker_desktop'
    }
    foreach ($key in $Extra.Keys) {
        $receipt[$key] = $Extra[$key]
    }
    Assert-XinaoNoSecretLeak -Object $receipt
    return $receipt
}

function Ensure-XinaoDirectory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $full -PathType Container)) {
        New-Item -ItemType Directory -Path $full -Force | Out-Null
    }
    return $full
}

function Get-XinaoFileSha256Hex {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        throw "EGRESS_HASH_TARGET_MISSING:$full"
    }
    return (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Format-XinaoQuotedArgument {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )
    # PowerShell-safe single-argument quoting for paths with spaces.
    if ($Value -match '[\s"]') {
        $escaped = $Value.Replace('"', '`"')
        return "`"$escaped`""
    }
    return $Value
}

# --- Engineering canary CLI/event helpers (pure; no Docker, no auth readback) ---
# Exact key sets mirror owner_seal_live_egress.py / xinao_runtime.py consumers.

$script:XinaoCanaryRequestedModel = 'grok-4.5'
$script:XinaoCanaryObservedBackendModel = 'grok-4.5-build'
$script:XinaoCanaryEndpointHost = 'cli-chat-proxy.grok.com'
$script:XinaoCanaryAuthContainerPath = '/grok-home/.grok/auth.json'
$script:XinaoCanaryFixedPrompt = 'ENGINEERING_CANARY_NON_SCIENTIFIC: reply with exactly the token engineering_canary_ok. No tools. Not research. Not scientific adoption.'
$script:XinaoRequiredNegativeCaseIds = @(
    'N1', 'N3', 'N4', 'N5', 'N6', 'N7', 'N8', 'N9', 'N15', 'N17', 'N17b', 'N17c', 'N17d'
)
$script:XinaoCanaryRequiredKeys = @(
    'schema_version',
    'path_class',
    'status',
    'real_provider_call',
    'provider_effect_verified',
    'requested_model',
    'observed_backend_model',
    'stop_reason',
    'output_tokens',
    'usage_accounting_complete',
    'usage',
    'endpoint_host',
    'internal_network_id',
    'proxy_container_id',
    'proxy_image_id',
    'allowlist_sha256',
    'proxy_config_sha256',
    'canary_image_id',
    'internal_network_only',
    'auth_mounted_read_only',
    'auth_content_persisted',
    'raw_output_persisted',
    'research_invoked',
    'is_research_call',
    'scientific_research',
    'masquerades_as_research',
    'scientific_adoption',
    'science_restored',
    'parent_complete',
    'authority',
    'completion_claim_allowed',
    'secrets_present',
    'provider_egress_runtime_verified',
    'provider_egress_live_verified',
    'observed_at'
)
$script:XinaoCanaryAllowedKeys = $script:XinaoCanaryRequiredKeys + @(
    'executed_at',
    'object_identities',
    'mode',
    'note',
    'docker_mutated',
    'carrier',
    'wsl_used',
    'git_bash_used',
    'probe_ok',
    'probe_exit_code',
    'connect_probe_ok',
    'canary_container_id',
    'canary_container_removed',
    'endpoint_hint',
    'model_hint',
    'positive_token_present_observed',
    'positive_token_value',
    'engineering_evidence',
    'redaction',
    'allow_real_provider_call_requested',
    'raw_output_sha256',
    'reason_code',
    'connect_only',
    'http_only'
)
# Back-compat alias used by older tests.
$script:XinaoCanarySealReceiptKeys = $script:XinaoCanaryRequiredKeys
$script:XinaoNegativeRequiredKeys = @(
    'schema_version',
    'path_class',
    'status',
    'suite_passed',
    'all_cases_passed',
    'cases',
    'pass_count',
    'fail_count',
    'internal_network_id',
    'proxy_container_id',
    'proxy_image_id',
    'allowlist_sha256',
    'proxy_config_sha256',
    'unauthorized_domain_reachable',
    'direct_no_proxy_escape',
    'provider_egress_runtime_verified',
    'provider_egress_live_verified',
    'secrets_present',
    'completion_claim_allowed',
    'authority',
    'science_restored',
    'parent_complete',
    'scientific_research',
    'observed_at'
)
$script:XinaoNegativeAllowedKeys = $script:XinaoNegativeRequiredKeys + @(
    'executed_at',
    'object_identities',
    'mode',
    'note',
    'docker_mutated',
    'carrier',
    'wsl_used',
    'git_bash_used',
    'research_invoked',
    'path_class'
)

function Test-XinaoImmutableImageIdFormat {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ImageId
    )
    if ([string]::IsNullOrWhiteSpace($ImageId)) { return $false }
    # Accept only sha256:<64hex> or raw 64-hex; reject floating tags and digests with repo prefix.
    if ($ImageId -match '^(sha256:)?[0-9a-fA-F]{64}$') { return $true }
    return $false
}

function ConvertTo-XinaoCanonicalImageId {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ImageId
    )
    if (-not (Test-XinaoImmutableImageIdFormat -ImageId $ImageId)) {
        throw 'EGRESS_IMAGE_ID_NOT_IMMUTABLE'
    }
    $raw = $ImageId.Trim().ToLowerInvariant()
    if ($raw.StartsWith('sha256:')) { return $raw }
    return "sha256:$raw"
}

function Get-XinaoResearcherRuntimeLockPath {
    [CmdletBinding()]
    param(
        [string]$PackageRoot = (Get-XinaoEgressPackageRoot)
    )
    $pkg = [System.IO.Path]::GetFullPath($PackageRoot)
    $candidates = @(
        (Join-Path $pkg '..\..\skills\xinao\references\researcher-runtime-lock.v1.json'),
        (Join-Path $pkg '..\..\..\skills\xinao\references\researcher-runtime-lock.v1.json')
    )
    foreach ($rel in $candidates) {
        try {
            $full = [System.IO.Path]::GetFullPath($rel)
            if (Test-Path -LiteralPath $full -PathType Leaf) { return $full }
        } catch {
            continue
        }
    }
    throw 'EGRESS_RUNTIME_LOCK_MISSING'
}

function Get-XinaoResearcherRuntimeLock {
    [CmdletBinding()]
    param(
        [string]$PackageRoot = (Get-XinaoEgressPackageRoot),
        [string]$LockPath = ''
    )
    $path = if ([string]::IsNullOrWhiteSpace($LockPath)) {
        Get-XinaoResearcherRuntimeLockPath -PackageRoot $PackageRoot
    } else {
        [System.IO.Path]::GetFullPath($LockPath)
    }
    return (Read-XinaoJsonFile -Path $path)
}

# Protocol-v2 researcher-container state (sibling of egress state; not the egress posture root).
# Identity/journal rules mirror skills/xinao/scripts/xinao.py active-ref + runtime-entry-locked
# (PowerShell state root IS the researcher_container directory).
$script:XinaoResearcherCurrentPointerSchemaV2 = 'xinao.researcher_current_pointer.v2'
$script:XinaoResearcherCurrentPointerSchemaV1 = 'xinao.researcher_current_pointer.v1'
$script:XinaoResearcherReleaseSchemaV2 = 'xinao.researcher_release.v2'
$script:XinaoResearcherActivationJournalSchemaV1 = 'xinao.researcher_activation_journal.v1'
$script:XinaoResearcherReleaseIdPattern = '^researcher-[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{16}$'
$script:XinaoResearcherTxnIdPattern = '^xra_[0-9]{8}T[0-9]{6}_[0-9a-f]{16}$'
$script:XinaoResearcherSemverPattern = '^[0-9]+\.[0-9]+\.[0-9]+$'
$script:XinaoResearcherHexSha256Pattern = '^[0-9a-f]{64}$'
$script:XinaoResearcherCapabilityId = 'researcher-container'
$script:XinaoResearcherStateNamespace = 'xinao_skill/researcher_container'
$script:XinaoResearcherRunNamespace = 'xinao_researcher'
$script:XinaoResearcherLabelChain = 'io.xinao.researcher.chain'
$script:XinaoResearcherLabelChainValue = 'dedicated-xinao-science'
$script:XinaoResearcherLabelGenericWorkerRoute = 'io.xinao.researcher.generic-worker-route'
$script:XinaoResearcherLabelGenericWorkerRouteValue = 'forbidden'
$script:XinaoResearcherLabelDonorImageId = 'io.xinao.researcher.grok-donor-image-id'
$script:XinaoResearcherLabelDonorBinarySha = 'io.xinao.researcher.grok-donor-binary.sha256'
$script:XinaoResearcherLabelRequestedModel = 'io.xinao.researcher.requested-model'

function Get-XinaoDefaultResearcherContainerStateRoot {
    [CmdletBinding()]
    param(
        [string]$PackageRoot = (Get-XinaoEgressPackageRoot)
    )
    if (-not [string]::IsNullOrWhiteSpace($env:XINAO_RESEARCHER_CONTAINER_STATE_ROOT)) {
        return [System.IO.Path]::GetFullPath($env:XINAO_RESEARCHER_CONTAINER_STATE_ROOT)
    }
    try {
        $lock = Get-XinaoResearcherRuntimeLock -PackageRoot $PackageRoot
        $fromLock = [string]$lock.state_root
        if (-not [string]::IsNullOrWhiteSpace($fromLock)) {
            return [System.IO.Path]::GetFullPath($fromLock)
        }
    } catch {
        # Fall through to hard default.
    }
    return [System.IO.Path]::GetFullPath('D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\researcher_container')
}

function Get-XinaoResearcherContainerPointerPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResearcherContainerStateRoot
    )
    $root = [System.IO.Path]::GetFullPath($ResearcherContainerStateRoot)
    return (Join-Path $root 'current.json')
}

function Get-XinaoNormalizedPathKey {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Path
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'ACTIVE_RESEARCHER_PATH_EMPTY'
    }
    if (-not [System.IO.Path]::IsPathRooted($Path)) {
        throw 'ACTIVE_RESEARCHER_PATH_NOT_ABSOLUTE'
    }
    try {
        $full = [System.IO.Path]::GetFullPath($Path)
    } catch {
        throw 'ACTIVE_RESEARCHER_PATH_INVALID'
    }
    if (-not [System.IO.Path]::IsPathRooted($full)) {
        throw 'ACTIVE_RESEARCHER_PATH_NOT_ABSOLUTE'
    }
    # Windows path identity: normcase + fullpath (matches Python os.path.normcase(abspath)).
    return $full.ToLowerInvariant()
}

function Test-XinaoHexSha256 {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )
    return ($Value -match $script:XinaoResearcherHexSha256Pattern)
}

function Assert-XinaoActiveResearcherRefShape {
    <#
      .SYNOPSIS
        Validate protocol-v2 active ref (pointer.active / journal.to) against researcher_container root.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $Ref,
        [Parameter(Mandatory = $true)]
        [string]$ResearcherContainerStateRoot,
        [string]$ReasonCode = 'ACTIVE_RESEARCHER_POINTER_ACTIVE_INVALID'
    )
    if ($null -eq $Ref) {
        throw $ReasonCode
    }
    $releaseId = [string]$Ref.release_id
    $txnId = [string]$Ref.activation_txn_id
    $manifestPathRaw = [string]$Ref.release_manifest_path
    $manifestSha = [string]$Ref.release_manifest_sha256
    $bundleManifestSha = [string]$Ref.skill_bundle_manifest_sha256
    $bundleTreeSha = [string]$Ref.skill_bundle_tree_sha256
    $capabilityVersion = [string]$Ref.capability_version
    $packageVersion = [string]$Ref.package_version
    $bootstrap = $Ref.required_bootstrap_protocol

    if ([string]::IsNullOrWhiteSpace($releaseId) -or $releaseId -notmatch $script:XinaoResearcherReleaseIdPattern) {
        throw 'ACTIVE_RESEARCHER_RELEASE_IDENTITY_INVALID'
    }
    if ([string]::IsNullOrWhiteSpace($txnId) -or $txnId -notmatch $script:XinaoResearcherTxnIdPattern) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_TRANSACTION_ID_INVALID'
    }
    if ([string]::IsNullOrWhiteSpace($manifestPathRaw)) {
        throw 'ACTIVE_RESEARCHER_RELEASE_MANIFEST_PATH_MISSING'
    }
    if (-not [System.IO.Path]::IsPathRooted($manifestPathRaw)) {
        throw 'ACTIVE_RESEARCHER_RELEASE_MANIFEST_PATH_INVALID'
    }
    $root = [System.IO.Path]::GetFullPath($ResearcherContainerStateRoot)
    $expectedManifest = [System.IO.Path]::GetFullPath(
        (Join-Path $root (Join-Path 'releases' (Join-Path $releaseId 'release.json')))
    )
    try {
        $declaredKey = Get-XinaoNormalizedPathKey -Path $manifestPathRaw
        $expectedKey = Get-XinaoNormalizedPathKey -Path $expectedManifest
    } catch {
        throw 'ACTIVE_RESEARCHER_RELEASE_MANIFEST_PATH_INVALID'
    }
    if ($declaredKey -ne $expectedKey) {
        throw 'ACTIVE_RESEARCHER_RELEASE_MANIFEST_PATH_INVALID'
    }
    if (-not (Test-XinaoHexSha256 -Value $manifestSha.ToLowerInvariant())) {
        throw 'ACTIVE_RESEARCHER_RELEASE_MANIFEST_HASH_REQUIRED'
    }
    if (-not (Test-XinaoHexSha256 -Value $bundleManifestSha.ToLowerInvariant())) {
        throw 'ACTIVE_RESEARCHER_POINTER_ACTIVE_INVALID'
    }
    if (-not (Test-XinaoHexSha256 -Value $bundleTreeSha.ToLowerInvariant())) {
        throw 'ACTIVE_RESEARCHER_POINTER_ACTIVE_INVALID'
    }
    if ($capabilityVersion -notmatch $script:XinaoResearcherSemverPattern) {
        throw 'ACTIVE_RESEARCHER_POINTER_ACTIVE_INVALID'
    }
    if ($packageVersion -notmatch $script:XinaoResearcherSemverPattern) {
        throw 'ACTIVE_RESEARCHER_POINTER_ACTIVE_INVALID'
    }
    # Protocol release identity rule: researcher-<capability_version>-<16hex>
    $expectedPrefix = "researcher-$capabilityVersion-"
    if (-not $releaseId.StartsWith($expectedPrefix) -or $releaseId.Length -ne ($expectedPrefix.Length + 16)) {
        throw 'ACTIVE_RESEARCHER_RELEASE_IDENTITY_INVALID'
    }
    if ($bootstrap -ne 2 -and [string]$bootstrap -ne '2') {
        throw 'ACTIVE_RESEARCHER_RELEASE_V2_ABSENT'
    }
    return [ordered]@{
        release_id                      = $releaseId
        release_manifest_path           = $expectedManifest
        release_manifest_sha256         = $manifestSha.ToLowerInvariant()
        skill_bundle_manifest_sha256    = $bundleManifestSha.ToLowerInvariant()
        skill_bundle_tree_sha256        = $bundleTreeSha.ToLowerInvariant()
        capability_version              = $capabilityVersion
        package_version                 = $packageVersion
        required_bootstrap_protocol     = 2
        activation_txn_id               = $txnId
    }
}

function Test-XinaoActiveResearcherRefEqual {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $Left,
        [Parameter(Mandatory = $true)]
        $Right
    )
    $keys = @(
        'release_id',
        'release_manifest_path',
        'release_manifest_sha256',
        'skill_bundle_manifest_sha256',
        'skill_bundle_tree_sha256',
        'capability_version',
        'package_version',
        'required_bootstrap_protocol',
        'activation_txn_id'
    )
    foreach ($k in $keys) {
        $lv = $Left.$k
        $rv = $Right.$k
        if ($k -eq 'required_bootstrap_protocol') {
            $li = 0; $ri = 0
            try { $li = [int]$lv } catch { return $false }
            try { $ri = [int]$rv } catch { return $false }
            if ($li -ne $ri) { return $false }
            continue
        }
        if ($k -eq 'release_manifest_path') {
            try {
                $lk = Get-XinaoNormalizedPathKey -Path ([string]$lv)
                $rk = Get-XinaoNormalizedPathKey -Path ([string]$rv)
                if ($lk -ne $rk) { return $false }
            } catch {
                return $false
            }
            continue
        }
        if ($k -match 'sha256$') {
            if ([string]$lv.ToLowerInvariant() -ne [string]$rv.ToLowerInvariant()) { return $false }
            continue
        }
        if ([string]$lv -ne [string]$rv) { return $false }
    }
    return $true
}

function Assert-XinaoActiveResearcherActivationJournal {
    <#
      .SYNOPSIS
        Require the protocol activation journal bound to the active pointer (VERIFIED terminal only).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResearcherContainerStateRoot,
        [Parameter(Mandatory = $true)]
        $ActiveRef,
        [Parameter(Mandatory = $true)]
        [int]$PointerGeneration,
        [Parameter(Mandatory = $true)]
        [string]$PointerSha256
    )
    $root = [System.IO.Path]::GetFullPath($ResearcherContainerStateRoot)
    $txnId = [string]$ActiveRef.activation_txn_id
    if ([string]::IsNullOrWhiteSpace($txnId) -or $txnId -notmatch $script:XinaoResearcherTxnIdPattern) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_TRANSACTION_ID_INVALID'
    }
    $journalPath = [System.IO.Path]::GetFullPath(
        (Join-Path $root (Join-Path 'transactions' (Join-Path $txnId 'activation.v1.json')))
    )
    if (Test-XinaoPathHasReparseChain -Path $journalPath) {
        throw 'ACTIVE_RESEARCHER_STATE_REPARSE_FORBIDDEN'
    }
    if (-not (Test-Path -LiteralPath $journalPath -PathType Leaf)) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_JOURNAL_ABSENT'
    }
    if (-not (Test-XinaoRegularNonHardlinkedFile -Path $journalPath)) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_JOURNAL_INVALID'
    }
    $journal = Read-XinaoJsonFile -Path $journalPath
    if ([string]$journal.schema_version -ne $script:XinaoResearcherActivationJournalSchemaV1) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_JOURNAL_SCHEMA_INVALID'
    }
    if ([string]$journal.txn_id -ne $txnId) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_TRANSACTION_BINDING_MISMATCH'
    }
    $op = [string]$journal.operation
    # Terminal journals from ACTIVATE, ROLLBACK, MIGRATE, or FORWARD_UPGRADE may
    # witness the active release. Unknown operations remain fail-closed.
    if ($op -notin @('ACTIVATE', 'ROLLBACK', 'MIGRATE', 'FORWARD_UPGRADE')) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_OPERATION_INVALID'
    }
    $state = [string]$journal.state
    # Canary admission requires verified terminal activation (not pending / rolled-back / conflict).
    if ($state -ne 'VERIFIED') {
        if ($state -in @('PREPARED', 'POINTER_SWITCHED', 'CANARY_STARTED', 'ROLLBACK_POINTER_SWITCHED', 'ROLLBACK_CANARY_STARTED', 'RECOVERY_CONFLICT')) {
            throw 'ACTIVE_RESEARCHER_ACTIVATION_NOT_TERMINAL'
        }
        if ($state -eq 'ROLLED_BACK') {
            throw 'ACTIVE_RESEARCHER_ACTIVATION_ROLLED_BACK'
        }
        throw 'ACTIVE_RESEARCHER_ACTIVATION_NOT_VERIFIED'
    }
    $expectedGen = Get-XinaoJsonIntField -Obj $journal -Name 'expected_generation'
    if ($null -eq $expectedGen -or $expectedGen -ne $PointerGeneration) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_GENERATION_BINDING_MISMATCH'
    }
    $toRef = $journal.to
    if ($null -eq $toRef) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_TARGET_BINDING_MISMATCH'
    }
    # Shape-check journal.to against the same canonical containment rules.
    $toNormalized = Assert-XinaoActiveResearcherRefShape `
        -Ref $toRef `
        -ResearcherContainerStateRoot $root `
        -ReasonCode 'ACTIVE_RESEARCHER_ACTIVATION_TARGET_BINDING_MISMATCH'
    if (-not (Test-XinaoActiveResearcherRefEqual -Left $ActiveRef -Right $toNormalized)) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_TARGET_BINDING_MISMATCH'
    }
    if ($null -ne $journal.requested_to) {
        $reqNormalized = Assert-XinaoActiveResearcherRefShape `
            -Ref $journal.requested_to `
            -ResearcherContainerStateRoot $root `
            -ReasonCode 'ACTIVE_RESEARCHER_ACTIVATION_TARGET_BINDING_MISMATCH'
        if ([string]$reqNormalized.activation_txn_id -ne $txnId) {
            throw 'ACTIVE_RESEARCHER_ACTIVATION_TRANSACTION_BINDING_MISMATCH'
        }
    }
    $terminalSha = [string]$journal.terminal_pointer_sha256
    if (-not (Test-XinaoHexSha256 -Value $terminalSha.ToLowerInvariant())) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_POINTER_BINDING_MISMATCH'
    }
    if ($terminalSha.ToLowerInvariant() -ne $PointerSha256.ToLowerInvariant()) {
        throw 'ACTIVE_RESEARCHER_ACTIVATION_POINTER_BINDING_MISMATCH'
    }
    return [ordered]@{
        journal_path = $journalPath
        txn_id       = $txnId
        state        = $state
        operation    = $op
    }
}

function Get-XinaoActiveResearcherReleaseAdmission {
    <#
      .SYNOPSIS
        Load protocol-v2 active researcher release from researcher-container state
        (pointer + canonical release.json + verified activation journal).
      .DESCRIPTION
        Does not require Docker. Rejects legacy v1 pointer/release, path escape,
        missing/non-terminal journals, and identity/namespace/source violations.
        Does not claim the donor image is executable.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResearcherContainerStateRoot
    )
    $root = [System.IO.Path]::GetFullPath($ResearcherContainerStateRoot)
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw 'ACTIVE_RESEARCHER_STATE_ROOT_ABSENT'
    }
    if (Test-XinaoPathHasReparseChain -Path $root) {
        throw 'ACTIVE_RESEARCHER_STATE_REPARSE_FORBIDDEN'
    }

    $pointerPath = Get-XinaoResearcherContainerPointerPath -ResearcherContainerStateRoot $root
    if (Test-XinaoPathHasReparseChain -Path $pointerPath) {
        throw 'ACTIVE_RESEARCHER_STATE_REPARSE_FORBIDDEN'
    }
    if (-not (Test-Path -LiteralPath $pointerPath -PathType Leaf)) {
        throw 'ACTIVE_RESEARCHER_POINTER_ABSENT'
    }
    if (-not (Test-XinaoRegularNonHardlinkedFile -Path $pointerPath)) {
        throw 'ACTIVE_RESEARCHER_POINTER_INVALID'
    }

    $pointerSha = Get-XinaoFileSha256Hex -Path $pointerPath
    $pointer = Read-XinaoJsonFile -Path $pointerPath
    $schema = [string]$pointer.schema_version
    if ($schema -eq $script:XinaoResearcherCurrentPointerSchemaV1 -or $schema -like 'xinao.researcher_current_pointer.v1*') {
        throw 'ACTIVE_RESEARCHER_RELEASE_V2_ABSENT'
    }
    if ($schema -ne $script:XinaoResearcherCurrentPointerSchemaV2) {
        throw 'ACTIVE_RESEARCHER_POINTER_SCHEMA_INVALID'
    }

    $generation = Get-XinaoJsonIntField -Obj $pointer -Name 'generation'
    if ($null -eq $generation -or $generation -lt 1) {
        throw 'ACTIVE_RESEARCHER_POINTER_GENERATION_INVALID'
    }

    $active = $pointer.active
    $activeRef = Assert-XinaoActiveResearcherRefShape `
        -Ref $active `
        -ResearcherContainerStateRoot $root `
        -ReasonCode 'ACTIVE_RESEARCHER_POINTER_ACTIVE_INVALID'

    $releaseId = [string]$activeRef.release_id
    $manifestFull = [string]$activeRef.release_manifest_path
    $manifestSha = [string]$activeRef.release_manifest_sha256

    if (Test-XinaoPathHasReparseChain -Path $manifestFull) {
        throw 'ACTIVE_RESEARCHER_STATE_REPARSE_FORBIDDEN'
    }
    if (-not (Test-Path -LiteralPath $manifestFull -PathType Leaf)) {
        throw 'ACTIVE_RESEARCHER_RELEASE_MANIFEST_ABSENT'
    }
    if (-not (Test-XinaoRegularNonHardlinkedFile -Path $manifestFull)) {
        throw 'ACTIVE_RESEARCHER_RELEASE_MANIFEST_INVALID'
    }

    $observedSha = Get-XinaoFileSha256Hex -Path $manifestFull
    if ($observedSha -ne $manifestSha) {
        throw 'ACTIVE_RESEARCHER_RELEASE_MANIFEST_HASH_MISMATCH'
    }

    $manifest = Read-XinaoJsonFile -Path $manifestFull
    $releaseSchema = [string]$manifest.schema_version
    if ($releaseSchema -ne $script:XinaoResearcherReleaseSchemaV2) {
        throw 'ACTIVE_RESEARCHER_RELEASE_SCHEMA_INVALID'
    }
    if ([string]$manifest.release_id -ne $releaseId) {
        throw 'ACTIVE_RESEARCHER_RELEASE_ID_MISMATCH'
    }

    # Protocol identity composition: researcher-<capability_version>-<release_identity_sha256[:16]>
    $capabilityVersion = [string]$manifest.capability_version
    $packageVersion = [string]$manifest.package_version
    $charterVersion = [string]$manifest.charter_version
    $runtimeVersion = [string]$manifest.runtime_version
    if ($capabilityVersion -notmatch $script:XinaoResearcherSemverPattern) {
        throw 'ACTIVE_RESEARCHER_RELEASE_IDENTITY_INVALID'
    }
    if ($capabilityVersion -ne $activeRef.capability_version) {
        throw 'ACTIVE_RESEARCHER_RELEASE_POINTER_IDENTITY_MISMATCH'
    }
    if ($packageVersion -ne $activeRef.package_version) {
        throw 'ACTIVE_RESEARCHER_RELEASE_POINTER_IDENTITY_MISMATCH'
    }
    if ($charterVersion -ne $capabilityVersion -or $runtimeVersion -ne $capabilityVersion) {
        throw 'ACTIVE_RESEARCHER_RELEASE_IDENTITY_INVALID'
    }
    $identitySha = [string]$manifest.release_identity_sha256
    if (-not (Test-XinaoHexSha256 -Value $identitySha.ToLowerInvariant())) {
        throw 'ACTIVE_RESEARCHER_RELEASE_IDENTITY_INVALID'
    }
    $identitySha = $identitySha.ToLowerInvariant()
    $expectedReleaseId = "researcher-$capabilityVersion-$($identitySha.Substring(0, 16))"
    if ($releaseId -ne $expectedReleaseId) {
        throw 'ACTIVE_RESEARCHER_RELEASE_IDENTITY_INVALID'
    }

    if ([string]$manifest.capability_id -ne $script:XinaoResearcherCapabilityId) {
        throw 'ACTIVE_RESEARCHER_RELEASE_CAPABILITY_IDENTITY_INVALID'
    }
    if ([string]$manifest.state_namespace -ne $script:XinaoResearcherStateNamespace -or
        [string]$manifest.run_namespace -ne $script:XinaoResearcherRunNamespace) {
        throw 'ACTIVE_RESEARCHER_CROSS_CHAIN_NAMESPACE_FORBIDDEN'
    }
    if ($manifest.generic_worker_route_allowed -ne $false) {
        throw 'ACTIVE_RESEARCHER_RELEASE_CHAIN_INVALID'
    }
    if ($manifest.required_bootstrap_protocol -ne 2 -and [string]$manifest.required_bootstrap_protocol -ne '2') {
        throw 'ACTIVE_RESEARCHER_RELEASE_V2_ABSENT'
    }

    # Cross-object hash binding (pointer active ↔ manifest).
    $manBundleManifestSha = [string]$manifest.skill_bundle_manifest_sha256
    $manBundleTreeSha = [string]$manifest.skill_bundle_tree_sha256
    if (-not (Test-XinaoHexSha256 -Value $manBundleManifestSha.ToLowerInvariant()) -or
        -not (Test-XinaoHexSha256 -Value $manBundleTreeSha.ToLowerInvariant())) {
        throw 'ACTIVE_RESEARCHER_RELEASE_BUNDLE_HASH_INVALID'
    }
    if ($manBundleManifestSha.ToLowerInvariant() -ne $activeRef.skill_bundle_manifest_sha256 -or
        $manBundleTreeSha.ToLowerInvariant() -ne $activeRef.skill_bundle_tree_sha256) {
        throw 'ACTIVE_RESEARCHER_RELEASE_POINTER_IDENTITY_MISMATCH'
    }

    $imageIdRaw = [string]$manifest.image_id
    if (-not (Test-XinaoImmutableImageIdFormat -ImageId $imageIdRaw)) {
        throw 'ACTIVE_RESEARCHER_RELEASE_IMAGE_ID_INVALID'
    }
    $imageId = ConvertTo-XinaoCanonicalImageId -ImageId $imageIdRaw
    $source = $manifest.source_identity
    if ($null -eq $source) {
        throw 'ACTIVE_RESEARCHER_RELEASE_SOURCE_IDENTITY_MISSING'
    }
    if ($source.source_dirty -ne $false) {
        throw 'ACTIVE_RESEARCHER_DIRTY_RELEASE_FORBIDDEN'
    }
    $sourceCommit = [string]$source.source_commit
    $sourceTree = [string]$source.source_tree
    if ($sourceCommit -notmatch '^[0-9a-f]{40,64}$' -or $sourceTree -notmatch '^[0-9a-f]{40,64}$') {
        throw 'ACTIVE_RESEARCHER_RELEASE_SOURCE_IDENTITY_INVALID'
    }
    $sourceDonor = [string]$source.grok_donor_image_id
    $sourceBinary = [string]$source.grok_donor_binary_sha256
    if (-not (Test-XinaoImmutableImageIdFormat -ImageId $sourceDonor)) {
        throw 'ACTIVE_RESEARCHER_RELEASE_SOURCE_DONOR_INVALID'
    }
    $sourceDonorCanon = ConvertTo-XinaoCanonicalImageId -ImageId $sourceDonor
    if (-not (Test-XinaoHexSha256 -Value $sourceBinary.ToLowerInvariant())) {
        throw 'ACTIVE_RESEARCHER_RELEASE_SOURCE_BINARY_INVALID'
    }
    $sourceBinary = $sourceBinary.ToLowerInvariant()
    $labels = $manifest.image_labels

    $journalInfo = Assert-XinaoActiveResearcherActivationJournal `
        -ResearcherContainerStateRoot $root `
        -ActiveRef $activeRef `
        -PointerGeneration $generation `
        -PointerSha256 $pointerSha

    return [ordered]@{
        researcher_container_state_root = $root
        pointer_path                    = $pointerPath
        pointer_schema_version          = $schema
        pointer_generation              = $generation
        pointer_sha256                  = $pointerSha
        release_id                      = $releaseId
        release_manifest_path           = $manifestFull
        release_manifest_sha256         = $manifestSha
        active_image_id                 = $imageId
        source_donor_image_id           = $sourceDonorCanon
        source_donor_binary_sha256      = $sourceBinary
        image_labels                    = $labels
        capability_version              = $capabilityVersion
        package_version                 = $packageVersion
        required_bootstrap_protocol     = 2
        activation_txn_id               = [string]$activeRef.activation_txn_id
        activation_journal_path         = [string]$journalInfo.journal_path
        activation_state                = [string]$journalInfo.state
    }
}

function Resolve-XinaoCanaryImageAgainstActiveResearcherRelease {
    <#
      .SYNOPSIS
        Admit CanaryImageId as the active dedicated researcher release image (not the extraction donor).
      .DESCRIPTION
        Preflight: pointer + release + runtime-lock provenance only (no Docker).
        Execute: also requires live docker image inspect labels matching release/runtime-lock.
        canary_image_id in the result is always the active researcher image ID.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ImageRef,
        [string]$PackageRoot = (Get-XinaoEgressPackageRoot),
        [string]$ResearcherContainerStateRoot = '',
        [switch]$Preflight
    )
    if ([string]::IsNullOrWhiteSpace($ImageRef)) {
        throw 'CANARY_IMAGE_ID_REQUIRED'
    }
    if (-not (Test-XinaoImmutableImageIdFormat -ImageId $ImageRef)) {
        throw 'CANARY_IMAGE_ID_NOT_IMMUTABLE'
    }
    $want = ConvertTo-XinaoCanonicalImageId -ImageId $ImageRef
    $lock = Get-XinaoResearcherRuntimeLock -PackageRoot $PackageRoot
    $pinnedDonor = ConvertTo-XinaoCanonicalImageId -ImageId ([string]$lock.grok_donor_image_id)
    $expectedModel = [string]$lock.model
    if ([string]::IsNullOrWhiteSpace($expectedModel)) { $expectedModel = $script:XinaoCanaryRequestedModel }

    $stateRoot = if ([string]::IsNullOrWhiteSpace($ResearcherContainerStateRoot)) {
        Get-XinaoDefaultResearcherContainerStateRoot -PackageRoot $PackageRoot
    } else {
        [System.IO.Path]::GetFullPath($ResearcherContainerStateRoot)
    }

    $admission = Get-XinaoActiveResearcherReleaseAdmission -ResearcherContainerStateRoot $stateRoot
    $activeImageId = [string]$admission.active_image_id
    $sourceDonor = [string]$admission.source_donor_image_id
    $sourceBinary = [string]$admission.source_donor_binary_sha256

    if ($sourceDonor -ne $pinnedDonor) {
        throw 'RELEASE_SOURCE_DONOR_MISMATCH'
    }
    if ($want -eq $pinnedDonor -and $want -ne $activeImageId) {
        throw 'CANARY_IMAGE_IS_DONOR_NOT_RESEARCHER'
    }
    if ($want -ne $activeImageId) {
        throw 'CANARY_IMAGE_ID_NOT_ACTIVE_RELEASE'
    }

    $base = [ordered]@{
        canary_image_id                 = $activeImageId
        active_researcher_image_id      = $activeImageId
        pinned_donor_image_id           = $pinnedDonor
        source_donor_image_id           = $sourceDonor
        source_donor_binary_sha256      = $sourceBinary
        requested_model                 = $expectedModel
        release_id                      = [string]$admission.release_id
        release_manifest_path           = [string]$admission.release_manifest_path
        researcher_container_state_root = [string]$admission.researcher_container_state_root
        labels_verified                 = $false
        provenance_note                 = 'canary_image_id is active dedicated researcher release image; donor is provenance only'
    }

    if ($Preflight) {
        return $base
    }

    $insp = Invoke-XinaoDocker -ArgumentList @(
        'image', 'inspect', $want, '--format',
        (
            '{{.Id}}|' +
            '{{index .Config.Labels "' + $script:XinaoResearcherLabelDonorImageId + '"}}|' +
            '{{index .Config.Labels "' + $script:XinaoResearcherLabelDonorBinarySha + '"}}|' +
            '{{index .Config.Labels "' + $script:XinaoResearcherLabelRequestedModel + '"}}|' +
            '{{index .Config.Labels "' + $script:XinaoResearcherLabelChain + '"}}|' +
            '{{index .Config.Labels "' + $script:XinaoResearcherLabelGenericWorkerRoute + '"}}'
        )
    ) -AllowNonZero
    if ($insp.ExitCode -ne 0) {
        throw 'EGRESS_CANARY_IMAGE_INSPECT_FAILED'
    }
    $parts = ($insp.StdOut.Trim() -split '\|', 6)
    $observedImageId = if ($parts.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($parts[0])) {
        ConvertTo-XinaoCanonicalImageId -ImageId $parts[0].Trim()
    } else { '' }
    $donorImageLabel = if ($parts.Count -gt 1) { $parts[1].Trim() } else { '' }
    $donorBinaryLabel = if ($parts.Count -gt 2) { $parts[2].Trim() } else { '' }
    $requestedModelLabel = if ($parts.Count -gt 3) { $parts[3].Trim() } else { '' }
    $chainLabel = if ($parts.Count -gt 4) { $parts[4].Trim() } else { '' }
    $genericRouteLabel = if ($parts.Count -gt 5) { $parts[5].Trim() } else { '' }

    if ([string]::IsNullOrWhiteSpace($observedImageId)) {
        throw 'EGRESS_CANARY_IMAGE_ID_MISSING'
    }
    if ($observedImageId -ne $activeImageId) {
        throw 'EGRESS_CANARY_IMAGE_ID_MISMATCH'
    }
    if ([string]::IsNullOrWhiteSpace($donorImageLabel)) {
        throw 'EGRESS_CANARY_DONOR_LABEL_MISSING'
    }
    $donorLabelCanon = ConvertTo-XinaoCanonicalImageId -ImageId $donorImageLabel
    if ($donorLabelCanon -ne $pinnedDonor) {
        throw 'EGRESS_CANARY_DONOR_LABEL_MISMATCH'
    }
    if ([string]::IsNullOrWhiteSpace($donorBinaryLabel) -or $donorBinaryLabel -notmatch '^[0-9a-fA-F]{64}$') {
        throw 'EGRESS_CANARY_DONOR_BINARY_LABEL_MISSING'
    }
    if ($donorBinaryLabel.ToLowerInvariant() -ne $sourceBinary) {
        throw 'EGRESS_CANARY_DONOR_BINARY_LABEL_MISMATCH'
    }
    if ([string]::IsNullOrWhiteSpace($requestedModelLabel)) {
        throw 'EGRESS_CANARY_MODEL_LABEL_MISSING'
    }
    if ($requestedModelLabel -ne $expectedModel) {
        throw 'EGRESS_CANARY_IMAGE_MODEL_LABEL_MISMATCH'
    }
    if ([string]::IsNullOrWhiteSpace($chainLabel)) {
        throw 'EGRESS_CANARY_CHAIN_LABEL_MISSING'
    }
    if ($chainLabel -ne $script:XinaoResearcherLabelChainValue) {
        throw 'EGRESS_CANARY_CHAIN_LABEL_MISMATCH'
    }
    if ([string]::IsNullOrWhiteSpace($genericRouteLabel)) {
        throw 'EGRESS_CANARY_GENERIC_WORKER_ROUTE_LABEL_MISSING'
    }
    if ($genericRouteLabel -ne $script:XinaoResearcherLabelGenericWorkerRouteValue) {
        throw 'EGRESS_CANARY_GENERIC_WORKER_ROUTE_LABEL_MISMATCH'
    }

    $base.canary_image_id = $observedImageId
    $base.active_researcher_image_id = $observedImageId
    $base.labels_verified = $true
    return $base
}

function Get-XinaoJsonIntField {
    [CmdletBinding()]
    param(
        $Obj,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    if ($null -eq $Obj) { return $null }
    $prop = $Obj.PSObject.Properties[$Name]
    if ($null -eq $prop -or $null -eq $prop.Value) { return $null }
    if ($prop.Value -is [bool]) { return $null }
    try { return [int]$prop.Value } catch { return $null }
}

function Test-XinaoPathHasReparseChain {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $current = [System.IO.Path]::GetFullPath($Path)
    $guard = 0
    while (-not [string]::IsNullOrWhiteSpace($current) -and $guard -lt 64) {
        $guard++
        if (Test-Path -LiteralPath $current) {
            try {
                $item = Get-Item -LiteralPath $current -Force
                if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                    return $true
                }
                $linkType = $null
                try { $linkType = $item.LinkType } catch { $linkType = $null }
                if ($linkType -in @('Junction', 'SymbolicLink')) {
                    return $true
                }
            } catch {
                # Missing intermediate is fine; continue walk.
            }
        }
        $parent = [System.IO.Path]::GetDirectoryName($current)
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    return $false
}

function Test-XinaoRegularNonHardlinkedFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::Directory) -ne 0) { return $false }
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return $false }
    $linkType = $null
    try { $linkType = $item.LinkType } catch { $linkType = $null }
    if ($linkType -in @('HardLink', 'Junction', 'SymbolicLink')) { return $false }
    return $true
}

function Assert-XinaoAuthFilePathLiteral {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$AuthFilePath
    )
    # Never include host path text in thrown reason codes (receipt/error redaction).
    if ([string]::IsNullOrWhiteSpace($AuthFilePath)) {
        throw 'EGRESS_AUTH_PATH_REQUIRED'
    }
    $raw = [string]$AuthFilePath
    if ($raw -match '%[^%]+%' -or $raw -match '\$env:' -or $raw -match '\$\{') {
        throw 'EGRESS_AUTH_PATH_UNRESOLVED_VARIABLE'
    }
    if ($raw -match '^[\\/]{2}\.' -or $raw -match '\\\\\.\\') {
        throw 'EGRESS_AUTH_PATH_DEVICE_FORM_FORBIDDEN'
    }
    # Reject ADS / stream syntax beyond drive letter (C:...).
    if ($raw -match '^[A-Za-z]:') {
        $afterDrive = $raw.Substring(2)
        if ($afterDrive -match ':') { throw 'EGRESS_AUTH_PATH_ADS_FORBIDDEN' }
    } elseif ($raw -match ':') {
        throw 'EGRESS_AUTH_PATH_ADS_FORBIDDEN'
    }
    if (-not [System.IO.Path]::IsPathRooted($raw)) {
        throw 'EGRESS_AUTH_PATH_NOT_ABSOLUTE'
    }
    try {
        $full = [System.IO.Path]::GetFullPath($raw)
    } catch {
        throw 'EGRESS_AUTH_PATH_INVALID'
    }
    if (-not [System.IO.Path]::IsPathRooted($full)) {
        throw 'EGRESS_AUTH_PATH_NOT_ABSOLUTE'
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        throw 'EGRESS_AUTH_PATH_MISSING'
    }
    if (Test-XinaoPathHasReparseChain -Path $full) {
        throw 'EGRESS_AUTH_PATH_REPARSE_FORBIDDEN'
    }
    if (-not (Test-XinaoRegularNonHardlinkedFile -Path $full)) {
        throw 'EGRESS_AUTH_PATH_NOT_REGULAR_FILE'
    }
    # Return full path only for bind mount construction; never emit into receipts.
    return $full
}

function Assert-XinaoRawCleanupTargetContained {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RawPath,
        [Parameter(Mandatory = $true)]
        [string]$OwnedTempRoot,
        [switch]$RequireExistingRegularFile
    )
    $rawFull = [System.IO.Path]::GetFullPath($RawPath)
    $tempFull = [System.IO.Path]::GetFullPath($OwnedTempRoot).TrimEnd('\', '/')
    # Strict child path with separator: reject prefix siblings such as D:\tmp-root-evil.
    $prefix = $tempFull + [System.IO.Path]::DirectorySeparatorChar
    if (-not $rawFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'EGRESS_RAW_CLEANUP_TARGET_OUTSIDE_OWNED_TEMP'
    }
    if ($rawFull.Equals($tempFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'EGRESS_RAW_CLEANUP_TARGET_IS_ROOT'
    }
    $leaf = Split-Path -Leaf $rawFull
    if ([string]::IsNullOrWhiteSpace($leaf) -or $leaf -in @('.', '..')) {
        throw 'EGRESS_RAW_CLEANUP_TARGET_INVALID'
    }
    # Never delete a directory; only an exact file leaf under owned temp.
    if (Test-Path -LiteralPath $rawFull -PathType Container) {
        throw 'EGRESS_RAW_CLEANUP_TARGET_IS_DIRECTORY'
    }
    if (Test-XinaoPathHasReparseChain -Path $rawFull) {
        throw 'EGRESS_RAW_CLEANUP_REPARSE_FORBIDDEN'
    }
    if ($RequireExistingRegularFile -or (Test-Path -LiteralPath $rawFull -PathType Leaf)) {
        if (-not (Test-XinaoRegularNonHardlinkedFile -Path $rawFull)) {
            throw 'EGRESS_RAW_CLEANUP_NOT_REGULAR_FILE'
        }
    }
    return $rawFull
}

function Remove-XinaoExactRawFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RawPath,
        [Parameter(Mandatory = $true)]
        [string]$OwnedTempRoot
    )
    $full = Assert-XinaoRawCleanupTargetContained -RawPath $RawPath -OwnedTempRoot $OwnedTempRoot -RequireExistingRegularFile
    if (Test-Path -LiteralPath $full -PathType Container) {
        throw 'EGRESS_RAW_CLEANUP_TARGET_IS_DIRECTORY'
    }
    Remove-Item -LiteralPath $full -Force
    if (Test-Path -LiteralPath $full) {
        throw 'EGRESS_RAW_CLEANUP_DELETE_FAILED'
    }
    return $true
}

function ConvertTo-XinaoCanonicalCanaryStopReason {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [AllowNull()]
        [string]$StopReason
    )
    # Closed, auditable EndTurn orthography only. Live Grok CLI headless JSON has
    # been observed to emit stopReason=end_turn while fixtures/historical receipts
    # use EndTurn; camel/lower forms are admitted as the same terminal class.
    # Does NOT casefold-accept arbitrary strings (e.g. cancelled / max_tokens stay reject).
    if ($null -eq $StopReason -or [string]::IsNullOrWhiteSpace($StopReason)) {
        return $null
    }
    switch -Exact -CaseSensitive ($StopReason.Trim()) {
        'EndTurn' { return 'EndTurn' }
        'endTurn' { return 'EndTurn' }
        'end_turn' { return 'EndTurn' }
        'endturn' { return 'EndTurn' }
        default { return $null }
    }
}

function ConvertFrom-XinaoGrokCliJsonText {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$JsonText
    )
    # Parse headless Grok CLI JSON/event contract into redacted metadata only.
    # Never returns model text body, auth, or non-aggregate secrets.
    # Primary usage.* is authoritative: never backfill zero/missing primary token
    # fields from modelUsage (W9D-B01). modelUsage is used only for backend model
    # identity, positive modelCalls, and optional consistency with primary usage.
    if ([string]::IsNullOrWhiteSpace($JsonText)) {
        return [ordered]@{
            ok                        = $false
            reason_code               = 'CLI_OUTPUT_EMPTY'
            stop_reason               = $null
            observed_backend_model    = $null
            output_tokens             = 0
            input_tokens              = 0
            total_tokens              = 0
            usage_accounting_complete = $false
            model_calls               = 0
            session_id_present        = $false
            request_id_present        = $false
            text_chars                = 0
            raw_sha256                = $null
            text_persisted            = $false
        }
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($JsonText)
    $shaAlg = [System.Security.Cryptography.SHA256]::Create()
    try {
        $sha = ([BitConverter]::ToString($shaAlg.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
    } finally {
        $shaAlg.Dispose()
    }
    if (Test-XinaoSecretLeakText -Text $JsonText) {
        return [ordered]@{
            ok                        = $false
            reason_code               = 'CLI_OUTPUT_SECRET_LEAK'
            stop_reason               = $null
            observed_backend_model    = $null
            output_tokens             = 0
            input_tokens              = 0
            total_tokens              = 0
            usage_accounting_complete = $false
            model_calls               = 0
            session_id_present        = $false
            request_id_present        = $false
            text_chars                = 0
            raw_sha256                = $sha
            text_persisted            = $false
        }
    }
    try {
        $payload = $JsonText | ConvertFrom-Json -Depth 100
    } catch {
        return [ordered]@{
            ok                        = $false
            reason_code               = 'CLI_OUTPUT_JSON_INVALID'
            stop_reason               = $null
            observed_backend_model    = $null
            output_tokens             = 0
            input_tokens              = 0
            total_tokens              = 0
            usage_accounting_complete = $false
            model_calls               = 0
            session_id_present        = $false
            request_id_present        = $false
            text_chars                = 0
            raw_sha256                = $sha
            text_persisted            = $false
        }
    }
    if ($null -eq $payload -or $payload -is [System.Array]) {
        return [ordered]@{
            ok                        = $false
            reason_code               = 'CLI_OUTPUT_NOT_OBJECT'
            stop_reason               = $null
            observed_backend_model    = $null
            output_tokens             = 0
            input_tokens              = 0
            total_tokens              = 0
            usage_accounting_complete = $false
            model_calls               = 0
            session_id_present        = $false
            request_id_present        = $false
            text_chars                = 0
            raw_sha256                = $sha
            text_persisted            = $false
        }
    }

    $stopReasonRaw = $null
    if ($null -ne $payload.PSObject.Properties['stopReason']) {
        $stopReasonRaw = [string]$payload.stopReason
    } elseif ($null -ne $payload.PSObject.Properties['stop_reason']) {
        # Defensive: some event shapes use snake_case key; value still closed-mapped.
        $stopReasonRaw = [string]$payload.stop_reason
    }
    $stopReasonCanonical = ConvertTo-XinaoCanonicalCanaryStopReason -StopReason $stopReasonRaw
    # Receipt/meta expose canonical EndTurn on accept; raw non-EndTurn values stay visible on reject.
    $stopReason = if ($null -ne $stopReasonCanonical) {
        $stopReasonCanonical
    } elseif ([string]::IsNullOrWhiteSpace($stopReasonRaw)) {
        $null
    } else {
        $stopReasonRaw.Trim()
    }
    $sessionPresent = $false
    if ($null -ne $payload.PSObject.Properties['sessionId'] -and -not [string]::IsNullOrWhiteSpace([string]$payload.sessionId)) {
        $sessionPresent = $true
    }
    $requestPresent = $false
    if ($null -ne $payload.PSObject.Properties['requestId'] -and -not [string]::IsNullOrWhiteSpace([string]$payload.requestId)) {
        $requestPresent = $true
    }
    $textChars = 0
    if ($null -ne $payload.PSObject.Properties['text'] -and $null -ne $payload.text) {
        $textChars = ([string]$payload.text).Length
    }

    $usage = $null
    if ($null -ne $payload.PSObject.Properties['usage']) { $usage = $payload.usage }
    $inputTokens = 0
    $outputTokens = 0
    $totalTokens = 0
    $usageComplete = $false
    $inF = $null
    $outF = $null
    $totF = $null
    if ($null -ne $usage) {
        $inF = Get-XinaoJsonIntField -Obj $usage -Name 'input_tokens'
        $outF = Get-XinaoJsonIntField -Obj $usage -Name 'output_tokens'
        $totF = Get-XinaoJsonIntField -Obj $usage -Name 'total_tokens'
        if ($null -ne $inF) { $inputTokens = $inF }
        if ($null -ne $outF) { $outputTokens = $outF }
        if ($null -ne $totF) { $totalTokens = $totF }
        # Complete accounting from primary usage only: all integer fields present,
        # output_tokens > 0, and total >= input + output. Never promote modelUsage.
        $usageComplete = (
            ($null -ne $inF) -and
            ($null -ne $outF) -and
            ($null -ne $totF) -and
            ($inputTokens -ge 0) -and
            ($outputTokens -gt 0) -and
            ($totalTokens -gt 0) -and
            ($totalTokens -ge ($inputTokens + $outputTokens))
        )
    }

    $observedBackend = $null
    $modelCalls = 0
    $muOut = $null
    $muIn = $null
    $modelUsage = $null
    if ($null -ne $payload.PSObject.Properties['modelUsage']) { $modelUsage = $payload.modelUsage }
    if ($null -ne $modelUsage) {
        $props = @($modelUsage.PSObject.Properties | Where-Object { $_.MemberType -eq 'NoteProperty' })
        foreach ($p in $props) {
            $stats = $p.Value
            $calls = Get-XinaoJsonIntField -Obj $stats -Name 'modelCalls'
            if ($null -eq $calls) { $calls = 0 }
            if ($calls -gt 0) {
                $observedBackend = [string]$p.Name
                $modelCalls = $calls
                # Read modelUsage token fields for consistency only — never backfill primary.
                $muOut = Get-XinaoJsonIntField -Obj $stats -Name 'outputTokens'
                $muIn = Get-XinaoJsonIntField -Obj $stats -Name 'inputTokens'
                break
            }
        }
        if ($props.Count -eq 1 -and [string]::IsNullOrWhiteSpace($observedBackend)) {
            $observedBackend = [string]$props[0].Name
            $stats = $props[0].Value
            $calls = Get-XinaoJsonIntField -Obj $stats -Name 'modelCalls'
            if ($null -ne $calls) { $modelCalls = $calls }
            $muOut = Get-XinaoJsonIntField -Obj $stats -Name 'outputTokens'
            $muIn = Get-XinaoJsonIntField -Obj $stats -Name 'inputTokens'
        }
    }

    $reason = $null
    $ok = $true
    if ($stopReasonCanonical -ne 'EndTurn') {
        $ok = $false
        $reason = 'STOP_REASON_NOT_ENDTURN'
    } elseif ($observedBackend -ne $script:XinaoCanaryObservedBackendModel) {
        $ok = $false
        $reason = 'OBSERVED_BACKEND_MODEL_MISMATCH'
    } elseif (-not $usageComplete) {
        $ok = $false
        # Prefer specific reason when primary output is present but non-positive.
        if (($null -ne $outF) -and ($outputTokens -le 0) -and ($null -ne $inF) -and ($null -ne $totF)) {
            $reason = 'OUTPUT_TOKENS_NOT_POSITIVE'
        } else {
            $reason = 'USAGE_ACCOUNTING_INCOMPLETE'
        }
    } elseif ($modelCalls -lt 1) {
        $ok = $false
        $reason = 'MODEL_CALLS_NOT_POSITIVE'
    } elseif (($null -ne $muOut) -and ($muOut -ne $outputTokens)) {
        # Fail closed on primary vs modelUsage output inconsistency.
        $ok = $false
        $reason = 'MODELUSAGE_OUTPUT_MISMATCH'
    } elseif (($null -ne $muIn) -and ($muIn -ne $inputTokens)) {
        $ok = $false
        $reason = 'MODELUSAGE_INPUT_MISMATCH'
    }

    return [ordered]@{
        ok                        = [bool]$ok
        reason_code               = $reason
        stop_reason               = $(if ([string]::IsNullOrWhiteSpace($stopReason)) { $null } else { $stopReason })
        observed_backend_model    = $observedBackend
        output_tokens             = [int]$outputTokens
        input_tokens              = [int]$inputTokens
        total_tokens              = [int]$totalTokens
        usage_accounting_complete = [bool]$usageComplete
        model_calls               = [int]$modelCalls
        session_id_present        = [bool]$sessionPresent
        request_id_present        = [bool]$requestPresent
        text_chars                = [int]$textChars
        raw_sha256                = $sha
        # Explicitly never persist model text.
        text_persisted            = $false
    }
}

function Get-XinaoReceiptPropertyNames {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $Receipt
    )
    if ($Receipt -is [hashtable] -or $Receipt -is [System.Collections.Specialized.OrderedDictionary]) {
        return @($Receipt.Keys | ForEach-Object { [string]$_ })
    }
    return @($Receipt.PSObject.Properties | ForEach-Object { $_.Name })
}

function Get-XinaoReceiptPropertyValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $Receipt,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    if ($Receipt -is [hashtable] -or $Receipt -is [System.Collections.Specialized.OrderedDictionary]) {
        if ($Receipt.Contains($Name)) { return $Receipt[$Name] }
        return $null
    }
    $prop = $Receipt.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Limit-XinaoBoundedProbeText {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [string]$Text,
        [int]$MaxChars = 400
    )
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $t = $Text -replace '[\r\n]+', ' '
    $t = $t.Trim()
    if ($t.Length -le $MaxChars) { return $t }
    return $t.Substring(0, $MaxChars)
}

function Test-XinaoNegativeInfrastructureSignal {
    [CmdletBinding()]
    param(
        [int]$ExitCode,
        [AllowEmptyString()]
        [string]$Combined
    )
    # Docker client / runtime / tool absence — never policy denial.
    if ($ExitCode -in @(125, 126, 127)) { return $true }
    $infraPatterns = @(
        'applet not found',
        'executable file not found',
        'command not found',
        'not found in \$PATH',
        'no such file or directory',
        'invalid reference format',
        'invalid reference',
        'unknown flag',
        'unknown option',
        'flag provided but not defined',
        'invalid argument',
        'Cannot connect to the Docker daemon',
        'Is the docker daemon running',
        'Error response from daemon',
        'No such image',
        'network .+ not found',
        'Unable to find image',
        'permission denied while trying to connect',
        'docker: ''run'' requires',
        'requires at least'
    )
    foreach ($p in $infraPatterns) {
        if ($Combined -match $p) { return $true }
    }
    return $false
}

function Test-XinaoNegativeProxyPolicyDenial {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [string]$Combined
    )
    # Concrete proxy/policy denial signals only (not generic connect failures).
    $denyPatterns = @(
        'HTTP/1\.[01]\s+403',
        '\b403\s+Forbidden\b',
        '\b403 Forbidden\b',
        'Access Denied',
        'access denied',
        'Proxy Deny',
        'proxy deny',
        'TCP_DENIED',
        'TAG_NONE/403',
        'ERR_ACCESS_DENIED',
        'Forbidden by proxy',
        'proxy authorization required',
        'squid.*denied',
        'CONNECT denied',
        'cache_peer.*denied',
        'Request Denied'
    )
    foreach ($p in $denyPatterns) {
        if ($Combined -match $p) { return $true }
    }
    # Bare "403" only when not part of a successful/other status line noise is weak;
    # require digit-bounded 403 with denial context or HTTP status class.
    if ($Combined -match '(?i)\bHTTP/[0-9.]+\s+403\b') { return $true }
    if ($Combined -match '(?i)\b403\b' -and $Combined -match '(?i)(denied|forbidden|reject|block)') { return $true }
    return $false
}

function Test-XinaoNegativeDirectNoRouteSignal {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [string]$Combined
    )
    # Concrete isolation/no-route classes for direct-no-proxy cases.
    # Accept only explicit no-route / network-unreachable / DNS-resolution /
    # contract-permitted timeout classes.
    # Deliberately excludes:
    #   - bare connection-refused / connection-reset (may occur after a route was reached)
    #   - generic "can't connect" without an accepted network class above
    #   - bare 'wget:' and tool-missing prefixes
    #   - TLS/HTTP reachability signals (handled as escape/open or ambiguous elsewhere)
    $patterns = @(
        'Network is unreachable',
        'network is unreachable',
        'No route to host',
        'no route to host',
        'bad address',
        'Name or service not known',
        'Temporary failure in name resolution',
        'Could not resolve host',
        "can'?t resolve",
        'Connection timed out',
        'connection timed out',
        'Operation timed out',
        'connect timed out',
        'failed: Network is unreachable',
        'failed: No route to host',
        'wget: download timed out',
        'wget: bad address'
    )
    foreach ($p in $patterns) {
        if ($Combined -match $p) { return $true }
    }
    return $false
}

function Test-XinaoDockerMissingContainerSignal {
    <#
      .SYNOPSIS
        Pure offline: true only when docker inspect output is a missing-object signal
        bound to the exact container id-or-name that was inspected.
      .DESCRIPTION
        Exit 0 (including empty stdout) never proves absence.
        Empty nonzero output, daemon/connectivity/timeout/permission noise, or a
        missing-object signal naming a different identifier are all unproven.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Identifier,
        [int]$ExitCode,
        [AllowEmptyString()]
        [string]$StdOut = '',
        [AllowEmptyString()]
        [string]$StdErr = ''
    )
    if ([string]::IsNullOrWhiteSpace($Identifier)) { return $false }
    # Presence or empty success: never prove removal.
    if ($ExitCode -eq 0) { return $false }

    $combined = ((([string]$StdOut) + "`n" + ([string]$StdErr)) -replace '[\r\n]+', ' ').Trim()
    if ([string]::IsNullOrWhiteSpace($combined)) { return $false }

    # Extract every No such object/container reference named in the output.
    $missingRefs = [System.Collections.Generic.List[string]]::new()
    foreach ($m in [regex]::Matches(
            $combined,
            '(?i)No such (?:object|container):\s*(\S+)'
        )) {
        $missingRefs.Add($m.Groups[1].Value.Trim().TrimEnd('.', ',', ';', ')', ']')) | Out-Null
    }
    if ($missingRefs.Count -eq 0) {
        # Nonzero without a recognized missing-object class: infrastructure/ambiguous.
        return $false
    }

    $want = $Identifier.Trim()
    $exactHit = $false
    foreach ($ref in $missingRefs) {
        if ([string]::Equals($ref, $want, [System.StringComparison]::OrdinalIgnoreCase)) {
            $exactHit = $true
        } else {
            # A missing signal for a different object does not prove our target is gone.
            return $false
        }
    }
    return $exactHit
}

function Get-XinaoContainerCleanupObservation {
    <#
      .SYNOPSIS
        Pure offline oracle: container removal is proven only when rm succeeded and
        follow-up exact inspect fails with a missing-object signal for that same id/name.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Identifier,
        [int]$RmExitCode,
        [int]$InspectExitCode,
        [AllowEmptyString()]
        [string]$InspectStdOut = '',
        [AllowEmptyString()]
        [string]$InspectStdErr = ''
    )
    $result = [ordered]@{
        proven_removed = $false
        reason_code    = 'CLEANUP_UNPROVEN'
        identifier     = $(if ([string]::IsNullOrWhiteSpace($Identifier)) { $null } else { $Identifier.Trim() })
    }
    if ([string]::IsNullOrWhiteSpace($Identifier)) {
        $result.reason_code = 'CLEANUP_IDENTIFIER_EMPTY'
        return $result
    }
    if ($RmExitCode -ne 0) {
        $result.reason_code = 'CLEANUP_RM_FAILED'
        return $result
    }
    if ($InspectExitCode -eq 0) {
        # Exit 0 with or without body means inspect did not prove absence.
        if ([string]::IsNullOrWhiteSpace((([string]$InspectStdOut) + ([string]$InspectStdErr)).Trim())) {
            $result.reason_code = 'CLEANUP_INSPECT_EXIT0_EMPTY'
        } else {
            $result.reason_code = 'CLEANUP_INSPECT_STILL_PRESENT'
        }
        return $result
    }
    $combined = ((([string]$InspectStdOut) + "`n" + ([string]$InspectStdErr))).Trim()
    if ([string]::IsNullOrWhiteSpace($combined)) {
        $result.reason_code = 'CLEANUP_INSPECT_EMPTY_NONZERO'
        return $result
    }
    if (Test-XinaoDockerMissingContainerSignal `
            -Identifier $Identifier `
            -ExitCode $InspectExitCode `
            -StdOut $InspectStdOut `
            -StdErr $InspectStdErr) {
        $result.proven_removed = $true
        $result.reason_code = 'CLEANUP_ABSENCE_PROVEN'
        return $result
    }
    # Distinguish wrong-object missing signals from generic infra/timeout/permission.
    if ($combined -match '(?i)No such (?:object|container):\s*(\S+)') {
        $result.reason_code = 'CLEANUP_MISSING_SIGNAL_WRONG_OBJECT'
        return $result
    }
    if ($combined -match '(?i)(Cannot connect to the Docker daemon|Is the docker daemon running|permission denied|context deadline exceeded|i/o timeout|Client\.Timeout|TLS handshake|connection reset)') {
        $result.reason_code = 'CLEANUP_INSPECT_INFRA_OR_TIMEOUT'
        return $result
    }
    $result.reason_code = 'CLEANUP_ABSENCE_NOT_PROVEN'
    return $result
}

function Test-XinaoNegativeHttpSuccessSignal {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [string]$Combined
    )
    if ($Combined -match '(?i)\bHTTP/[0-9.]+\s+200\b') { return $true }
    if ($Combined -match '(?i)\bHTTP/[0-9.]+\s+2\d\d\b') { return $true }
    return $false
}

function Classify-XinaoNegativeProbeOutcome {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Expect,
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Mode,
        [int]$ExitCode = 0,
        [AllowEmptyString()]
        [string]$StdOut = '',
        [AllowEmptyString()]
        [string]$StdErr = ''
    )
    # Shared execution oracle for live negative suite + offline pure tests.
    # Returns structured class/reason; never reduces solely to substring pass.
    $combined = (([string]$StdOut) + "`n" + ([string]$StdErr))
    $bounded = Limit-XinaoBoundedProbeText -Text $combined -MaxChars 400
    $base = [ordered]@{
        ok           = $false
        result_class = 'ambiguous'
        reason       = 'AMBIGUOUS_OR_EMPTY'
        exit_code    = [int]$ExitCode
        got_signal   = $bounded
    }

    if ($Mode -eq 'inspect_proxy_networks') {
        if ($ExitCode -ne 0) {
            $base.result_class = 'infrastructure_failure'
            $base.reason = 'PROXY_INSPECT_FAILED'
            return $base
        }
        if (Test-XinaoNegativeInfrastructureSignal -ExitCode $ExitCode -Combined $combined) {
            $base.result_class = 'infrastructure_failure'
            $base.reason = 'PROXY_INSPECT_INFRA'
            return $base
        }
        if ($combined -match 'ssrf_proxy') {
            $base.result_class = 'escape_or_open'
            $base.reason = 'DIFY_OR_SSRF_ATTACHED'
            return $base
        }
        if ([string]::IsNullOrWhiteSpace($combined)) {
            $base.result_class = 'ambiguous'
            $base.reason = 'PROXY_NETWORKS_EMPTY'
            return $base
        }
        $base.ok = $true
        $base.result_class = 'policy_isolation'
        $base.reason = 'NO_DIFY_ATTACH'
        $base.got_signal = 'inspect_no_ssrf_proxy'
        return $base
    }

    if (Test-XinaoNegativeInfrastructureSignal -ExitCode $ExitCode -Combined $combined) {
        $base.result_class = 'infrastructure_failure'
        $base.reason = 'INFRA_OR_TOOL_MISSING'
        return $base
    }

    if (Test-XinaoNegativeHttpSuccessSignal -Combined $combined) {
        $base.result_class = 'escape_or_open'
        $base.reason = 'HTTP_SUCCESS_OBSERVED'
        return $base
    }

    if ([string]::IsNullOrWhiteSpace($combined) -and $ExitCode -eq 0) {
        $base.result_class = 'ambiguous'
        $base.reason = 'EMPTY_OUTPUT_ZERO_EXIT'
        return $base
    }
    if ([string]::IsNullOrWhiteSpace($combined)) {
        $base.result_class = 'ambiguous'
        $base.reason = 'EMPTY_OUTPUT'
        return $base
    }

    if ($Expect -eq 'no_route_or_timeout' -or $Expect -eq 'no_external') {
        if (Test-XinaoNegativeDirectNoRouteSignal -Combined $combined) {
            # Prefer nonzero client exit for direct isolation, but accept concrete
            # network-class signals even when busybox wget exit codes vary.
            $base.ok = $true
            $base.result_class = 'direct_no_route'
            $base.reason = 'DIRECT_NO_ROUTE_OR_TIMEOUT'
            return $base
        }
        # Generic command prefix alone is never enough.
        if ($combined -match '(?i)^wget:' -or $combined -match '(?i)\bwget:\s*$') {
            $base.result_class = 'ambiguous'
            $base.reason = 'GENERIC_WGET_PREFIX_ONLY'
            return $base
        }
        $base.result_class = 'ambiguous'
        $base.reason = 'DIRECT_SIGNAL_NOT_CONCRETE'
        return $base
    }

    if ($Expect -eq '403_or_denied' -or $Expect -eq 'denied') {
        $policyDeny = Test-XinaoNegativeProxyPolicyDenial -Combined $combined
        if ($policyDeny -and $ExitCode -ne 0) {
            $base.ok = $true
            $base.result_class = 'policy_denial'
            $base.reason = 'PROXY_POLICY_DENIAL'
            return $base
        }
        if ($policyDeny -and $ExitCode -eq 0) {
            $base.result_class = 'ambiguous'
            $base.reason = 'POLICY_SIGNAL_BUT_ZERO_EXIT'
            return $base
        }
        # Generic connect / bare invalid must not pass as policy denial.
        if ($combined -match '(?i)\binvalid\b' -and -not $policyDeny) {
            $base.result_class = 'infrastructure_failure'
            $base.reason = 'INVALID_ARG_OR_REFERENCE_NOT_POLICY'
            return $base
        }
        if (Test-XinaoNegativeDirectNoRouteSignal -Combined $combined) {
            $base.result_class = 'ambiguous'
            $base.reason = 'GENERIC_CONNECT_NOT_POLICY_DENIAL'
            return $base
        }
        $base.result_class = 'ambiguous'
        $base.reason = 'POLICY_DENIAL_NOT_PROVEN'
        return $base
    }

    $base.result_class = 'ambiguous'
    $base.reason = 'UNKNOWN_EXPECT'
    return $base
}

function Test-XinaoEngineeringCanarySealReceipt {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $Receipt
    )
    # Shape-only local helper: key/field contract only. Does NOT enforce observation
    # freshness or live posture binding equality (strict sealer/runtime do).
    # Not a seal-readiness proof by itself.
    $names = @(Get-XinaoReceiptPropertyNames -Receipt $Receipt)
    $missing = [System.Collections.Generic.List[string]]::new()
    foreach ($k in $script:XinaoCanaryRequiredKeys) {
        if ($names -notcontains $k) { $missing.Add($k) | Out-Null }
    }
    if ($missing.Count -gt 0) {
        return [ordered]@{ seal_eligible = $false; missing_keys = @($missing.ToArray()); reason_code = 'SEAL_RECEIPT_KEYS_MISSING' }
    }
    $unknown = @($names | Where-Object { $script:XinaoCanaryAllowedKeys -notcontains $_ })
    if ($unknown.Count -gt 0) {
        return [ordered]@{ seal_eligible = $false; missing_keys = @(); unknown_keys = $unknown; reason_code = 'SEAL_RECEIPT_UNKNOWN_KEY' }
    }
    $checks = @(
        @{ k = 'schema_version'; expect = 'xinao.provider_egress_engineering_canary_receipt.v1' },
        @{ k = 'status'; expect = 'observed' },
        @{ k = 'path_class'; expect = 'engineering_canary' },
        @{ k = 'requested_model'; expect = $script:XinaoCanaryRequestedModel },
        @{ k = 'observed_backend_model'; expect = $script:XinaoCanaryObservedBackendModel },
        @{ k = 'stop_reason'; expect = 'EndTurn' },
        @{ k = 'endpoint_host'; expect = $script:XinaoCanaryEndpointHost }
    )
    foreach ($c in $checks) {
        if ([string](Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name $c.k) -ne [string]$c.expect) {
            return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = "SEAL_FIELD_MISMATCH:$($c.k)" }
        }
    }
    $boolTrue = @(
        'real_provider_call', 'provider_effect_verified', 'usage_accounting_complete',
        'internal_network_only', 'auth_mounted_read_only'
    )
    foreach ($k in $boolTrue) {
        if ((Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name $k) -ne $true) {
            return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = "SEAL_BOOL_TRUE_REQUIRED:$k" }
        }
    }
    $boolFalse = @(
        'auth_content_persisted', 'raw_output_persisted', 'research_invoked', 'is_research_call',
        'scientific_research', 'masquerades_as_research', 'scientific_adoption', 'science_restored',
        'parent_complete', 'authority', 'completion_claim_allowed', 'secrets_present',
        'provider_egress_runtime_verified', 'provider_egress_live_verified'
    )
    foreach ($k in $boolFalse) {
        if ((Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name $k) -ne $false) {
            return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = "SEAL_BOOL_FALSE_REQUIRED:$k" }
        }
    }
    if ((Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'connect_only') -eq $true) {
        return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = 'SEAL_CONNECT_ONLY_REJECTED' }
    }
    if ((Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'http_only') -eq $true) {
        return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = 'SEAL_HTTP_ONLY_REJECTED' }
    }
    $ot = Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'output_tokens'
    if ($ot -is [bool] -or $null -eq $ot) {
        return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = 'SEAL_OUTPUT_TOKENS_INVALID' }
    }
    try { $otInt = [int]$ot } catch {
        return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = 'SEAL_OUTPUT_TOKENS_INVALID' }
    }
    if ($otInt -le 0) {
        return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = 'SEAL_OUTPUT_TOKENS_INVALID' }
    }
    $usage = Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'usage'
    if ($null -eq $usage) {
        return [ordered]@{ seal_eligible = $false; missing_keys = @('usage'); reason_code = 'SEAL_USAGE_MISSING' }
    }
    $usageNames = @(Get-XinaoReceiptPropertyNames -Receipt $usage)
    foreach ($uk in @('input_tokens', 'output_tokens', 'total_tokens')) {
        if ($usageNames -notcontains $uk) {
            return [ordered]@{ seal_eligible = $false; missing_keys = @("usage.$uk"); reason_code = 'SEAL_USAGE_INCOMPLETE' }
        }
    }
    $unknownUsage = @($usageNames | Where-Object { $_ -notin @('input_tokens', 'output_tokens', 'total_tokens') })
    if ($unknownUsage.Count -gt 0) {
        return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = 'SEAL_USAGE_UNKNOWN_KEY' }
    }
    $uOut = Get-XinaoReceiptPropertyValue -Receipt $usage -Name 'output_tokens'
    $uIn = Get-XinaoReceiptPropertyValue -Receipt $usage -Name 'input_tokens'
    $uTot = Get-XinaoReceiptPropertyValue -Receipt $usage -Name 'total_tokens'
    try {
        $uOutI = [int]$uOut; $uInI = [int]$uIn; $uTotI = [int]$uTot
    } catch {
        return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = 'SEAL_USAGE_INVALID' }
    }
    if ($uOutI -le 0 -or $uOutI -ne $otInt -or $uTotI -le 0 -or $uTotI -lt ($uInI + $uOutI) -or $uInI -lt 0) {
        return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = 'SEAL_USAGE_INVALID' }
    }
    foreach ($idKey in @('internal_network_id', 'proxy_container_id', 'proxy_image_id', 'allowlist_sha256', 'proxy_config_sha256', 'canary_image_id')) {
        if ([string]::IsNullOrWhiteSpace([string](Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name $idKey))) {
            return [ordered]@{ seal_eligible = $false; missing_keys = @($idKey); reason_code = "SEAL_IDENTITY_MISSING:$idKey" }
        }
    }
    $canaryImage = [string](Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'canary_image_id')
    if ($canaryImage -notmatch '^sha256:[0-9a-f]{64}$') {
        return [ordered]@{ seal_eligible = $false; missing_keys = @(); reason_code = 'SEAL_CANARY_IMAGE_ID_INVALID' }
    }
    if ([string]::IsNullOrWhiteSpace([string](Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'observed_at'))) {
        return [ordered]@{ seal_eligible = $false; missing_keys = @('observed_at'); reason_code = 'SEAL_OBSERVED_AT_MISSING' }
    }
    return [ordered]@{ seal_eligible = $true; missing_keys = @(); unknown_keys = @(); reason_code = $null }
}

function New-XinaoEngineeringCanarySealReceipt {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $Meta,
        [Parameter(Mandatory = $true)]
        $PostureIds,
        [Parameter(Mandatory = $true)]
        [string]$CanaryImageId,
        [bool]$ConnectProbeOk = $false,
        [string]$CanaryContainerId = '',
        [bool]$CanaryContainerRemoved = $false,
        [string]$RawOutputSha256 = '',
        [string]$ObservedAt = '',
        [hashtable]$ObjectIdentities = $null,
        [string]$Note = 'Real bounded engineering provider canary. Not research(); not scientific adoption; not parent completion.'
    )
    if ($null -eq $Meta -or $Meta.ok -ne $true) {
        throw 'EGRESS_CANARY_META_NOT_OK'
    }
    # Carrier/builder invariant: seal-eligible only when disposable container cleanup
    # was observed (rm + re-inspect absence). Do not weaken strict consumer schema.
    if ($CanaryContainerRemoved -ne $true) {
        throw 'EGRESS_CANARY_CONTAINER_NOT_REMOVED'
    }
    $canonicalImage = ConvertTo-XinaoCanonicalImageId -ImageId $CanaryImageId
    $observedAtValue = if ([string]::IsNullOrWhiteSpace($ObservedAt)) { New-XinaoUtcNowIso } else { $ObservedAt }
    $usage = [ordered]@{
        input_tokens  = [int]$Meta.input_tokens
        output_tokens = [int]$Meta.output_tokens
        total_tokens  = [int]$Meta.total_tokens
    }
    $receipt = [ordered]@{
        schema_version                   = 'xinao.provider_egress_engineering_canary_receipt.v1'
        path_class                       = 'engineering_canary'
        status                           = 'observed'
        real_provider_call               = $true
        provider_effect_verified         = $true
        requested_model                  = $script:XinaoCanaryRequestedModel
        observed_backend_model           = [string]$Meta.observed_backend_model
        stop_reason                      = [string]$Meta.stop_reason
        output_tokens                    = [int]$Meta.output_tokens
        usage_accounting_complete        = [bool]$Meta.usage_accounting_complete
        usage                            = $usage
        endpoint_host                    = $script:XinaoCanaryEndpointHost
        internal_network_id              = [string]$PostureIds.internal_network_id
        proxy_container_id               = [string]$PostureIds.proxy_container_id
        proxy_image_id                   = [string]$PostureIds.proxy_image_id
        allowlist_sha256                 = [string]$PostureIds.allowlist_sha256
        proxy_config_sha256              = [string]$PostureIds.proxy_config_sha256
        canary_image_id                  = $canonicalImage
        internal_network_only            = $true
        auth_mounted_read_only           = $true
        auth_content_persisted           = $false
        raw_output_persisted             = $false
        research_invoked                 = $false
        is_research_call                 = $false
        scientific_research              = $false
        masquerades_as_research          = $false
        scientific_adoption              = $false
        science_restored                 = $false
        parent_complete                  = $false
        authority                        = $false
        completion_claim_allowed         = $false
        secrets_present                  = $false
        provider_egress_runtime_verified = $false
        provider_egress_live_verified    = $false
        observed_at                      = $observedAtValue
        executed_at                      = $observedAtValue
        mode                             = 'execute_real_provider'
        connect_probe_ok                 = [bool]$ConnectProbeOk
        canary_container_removed         = [bool]$CanaryContainerRemoved
        docker_mutated                   = $true
        carrier                          = 'windows_powershell7_docker_desktop'
        wsl_used                         = $false
        git_bash_used                    = $false
        note                             = $Note
        connect_only                     = $false
        http_only                        = $false
        positive_token_value             = $null
        allow_real_provider_call_requested = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($CanaryContainerId)) {
        $receipt.canary_container_id = [string]$CanaryContainerId
    }
    if (-not [string]::IsNullOrWhiteSpace($RawOutputSha256)) {
        $receipt.raw_output_sha256 = [string]$RawOutputSha256
    }
    if ($null -ne $ObjectIdentities) {
        $receipt.object_identities = $ObjectIdentities
    }
    # Validate observed metadata fields (never constants-only for model/stop/usage).
    if ($receipt.observed_backend_model -ne $script:XinaoCanaryObservedBackendModel) {
        throw 'EGRESS_CANARY_BACKEND_MODEL_MISMATCH'
    }
    $receiptStopCanonical = ConvertTo-XinaoCanonicalCanaryStopReason -StopReason ([string]$receipt.stop_reason)
    if ($receiptStopCanonical -ne 'EndTurn') {
        throw 'EGRESS_CANARY_STOP_REASON_INVALID'
    }
    # Seal receipt always carries the single canonical token for strict consumers.
    $receipt.stop_reason = 'EndTurn'
    if ($receipt.usage_accounting_complete -ne $true -or [int]$receipt.output_tokens -le 0) {
        throw 'EGRESS_CANARY_USAGE_INCOMPLETE'
    }
    $probe = Test-XinaoEngineeringCanarySealReceipt -Receipt $receipt
    if ($probe.seal_eligible -ne $true) {
        throw "EGRESS_CANARY_SEAL_FIELDS_INCOMPLETE:$($probe.reason_code)"
    }
    return $receipt
}

function Get-XinaoNegativeSuiteSealFields {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $ObjectIdentities,
        [Parameter(Mandatory = $true)]
        [int]$PassCount,
        [Parameter(Mandatory = $true)]
        [int]$FailCount,
        [Parameter(Mandatory = $true)]
        [int]$CaseCount,
        [bool]$UnauthorizedDomainReachable = $true,
        [bool]$DirectNoProxyEscape = $true
    )
    $idsOk = $true
    $required = @('internal_network_id', 'proxy_container_id', 'proxy_image_id', 'allowlist_sha256', 'proxy_config_sha256')
    $top = [ordered]@{}
    foreach ($k in $required) {
        $v = $null
        if ($ObjectIdentities -is [hashtable] -or $ObjectIdentities -is [System.Collections.Specialized.OrderedDictionary]) {
            if ($ObjectIdentities.Contains($k)) { $v = $ObjectIdentities[$k] }
        } else {
            $prop = $ObjectIdentities.PSObject.Properties[$k]
            if ($null -ne $prop) { $v = $prop.Value }
        }
        $top[$k] = $v
        if ([string]::IsNullOrWhiteSpace([string]$v)) { $idsOk = $false }
    }
    $exactCaseCount = $script:XinaoRequiredNegativeCaseIds.Count
    $allPassed = (
        $FailCount -eq 0 -and
        $PassCount -eq $CaseCount -and
        $CaseCount -eq $exactCaseCount -and
        $PassCount -eq $exactCaseCount
    )
    $escapesClosed = (-not $UnauthorizedDomainReachable) -and (-not $DirectNoProxyEscape)
    $suitePassed = $allPassed -and $idsOk -and $escapesClosed
    $status = if ($suitePassed) { 'observed' } elseif ($PassCount -gt 0) { 'partial' } else { 'failed' }
    if ($allPassed -and (-not $idsOk -or -not $escapesClosed)) { $status = 'partial' }
    return [ordered]@{
        status                         = $status
        suite_passed                   = [bool]$suitePassed
        all_cases_passed               = [bool]$allPassed
        identities_complete            = [bool]$idsOk
        unauthorized_domain_reachable  = [bool]$UnauthorizedDomainReachable
        direct_no_proxy_escape         = [bool]$DirectNoProxyEscape
        internal_network_id            = $top.internal_network_id
        proxy_container_id             = $top.proxy_container_id
        proxy_image_id                 = $top.proxy_image_id
        allowlist_sha256               = $top.allowlist_sha256
        proxy_config_sha256            = $top.proxy_config_sha256
    }
}

function New-XinaoNegativeSuiteSealReceipt {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $Cases,
        [Parameter(Mandatory = $true)]
        $ObjectIdentities,
        [string]$ObservedAt = '',
        [string]$Note = 'Negative suite receipt for strict seal consumption when suite_passed and identities complete. verified remains false.'
    )
    $caseList = @($Cases)
    $infraOrAmbiguous = $false
    $pass = 0
    foreach ($c in $caseList) {
        $cok = $false
        $cls = $null
        if ($c -is [hashtable] -or $c -is [System.Collections.Specialized.OrderedDictionary]) {
            $cok = [bool]$c['ok']
            if ($c.Contains('result_class')) { $cls = [string]$c['result_class'] }
        } else {
            $cok = [bool]$c.ok
            $prop = $c.PSObject.Properties['result_class']
            if ($null -ne $prop) { $cls = [string]$prop.Value }
        }
        if ($cok) { $pass++ }
        if ($cls -in @('infrastructure_failure', 'ambiguous')) {
            $infraOrAmbiguous = $true
        }
    }
    $fail = $caseList.Count - $pass
    $n3Ok = $false
    $n1Ok = $false
    $n9Ok = $false
    foreach ($c in $caseList) {
        $cid = if ($c -is [hashtable] -or $c -is [System.Collections.Specialized.OrderedDictionary]) { [string]$c['id'] } else { [string]$c.id }
        $cok = if ($c -is [hashtable] -or $c -is [System.Collections.Specialized.OrderedDictionary]) { [bool]$c['ok'] } else { [bool]$c.ok }
        if ($cid -eq 'N3' -and $cok) { $n3Ok = $true }
        if ($cid -eq 'N1' -and $cok) { $n1Ok = $true }
        if ($cid -eq 'N9' -and $cok) { $n9Ok = $true }
    }
    # ok=true for deny cases means unauthorized domain / direct escape was NOT observed.
    $unauthorized = -not $n3Ok
    $directEscape = -not ($n1Ok -and $n9Ok)
    $sealFields = Get-XinaoNegativeSuiteSealFields `
        -ObjectIdentities $ObjectIdentities `
        -PassCount $pass `
        -FailCount $fail `
        -CaseCount $caseList.Count `
        -UnauthorizedDomainReachable $unauthorized `
        -DirectNoProxyEscape $directEscape
    # Any infrastructure/ambiguous typed outcome makes receipt non-seal-eligible.
    if ($infraOrAmbiguous -and [bool]$sealFields.suite_passed) {
        $sealFields.suite_passed = $false
        $sealFields.status = 'failed'
        $sealFields.all_cases_passed = $false
    } elseif ($infraOrAmbiguous -and [string]$sealFields.status -eq 'observed') {
        $sealFields.status = 'failed'
        $sealFields.suite_passed = $false
    }
    $observedAtValue = if ([string]::IsNullOrWhiteSpace($ObservedAt)) { New-XinaoUtcNowIso } else { $ObservedAt }
    $receipt = [ordered]@{
        schema_version                   = 'xinao.provider_egress_negative_suite_receipt.v1'
        path_class                       = 'negative_suite'
        status                           = [string]$sealFields.status
        suite_passed                     = [bool]$sealFields.suite_passed
        all_cases_passed                 = [bool]$sealFields.all_cases_passed
        cases                            = $caseList
        pass_count                       = [int]$pass
        fail_count                       = [int]$fail
        internal_network_id              = $sealFields.internal_network_id
        proxy_container_id               = $sealFields.proxy_container_id
        proxy_image_id                   = $sealFields.proxy_image_id
        allowlist_sha256                 = $sealFields.allowlist_sha256
        proxy_config_sha256              = $sealFields.proxy_config_sha256
        unauthorized_domain_reachable    = [bool]$sealFields.unauthorized_domain_reachable
        direct_no_proxy_escape           = [bool]$sealFields.direct_no_proxy_escape
        provider_egress_runtime_verified = $false
        provider_egress_live_verified    = $false
        secrets_present                  = $false
        completion_claim_allowed         = $false
        authority                        = $false
        science_restored                 = $false
        parent_complete                  = $false
        scientific_research              = $false
        observed_at                      = $observedAtValue
        executed_at                      = $observedAtValue
        object_identities                = $ObjectIdentities
        mode                             = 'execute'
        docker_mutated                   = $true
        carrier                          = 'windows_powershell7_docker_desktop'
        wsl_used                         = $false
        git_bash_used                    = $false
        research_invoked                 = $false
        note                             = $Note
    }
    return $receipt
}

function Test-XinaoNegativeSuiteSealReceipt {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $Receipt
    )
    # Shape-only local helper: key/field/case-id contract only. Does NOT enforce
    # observation freshness or live posture binding (strict sealer/runtime do).
    $names = @(Get-XinaoReceiptPropertyNames -Receipt $Receipt)
    $missing = @($script:XinaoNegativeRequiredKeys | Where-Object { $names -notcontains $_ })
    if ($missing.Count -gt 0) {
        return [ordered]@{ seal_eligible = $false; reason_code = 'NEGATIVE_RECEIPT_MISSING_KEY'; missing_keys = $missing }
    }
    $unknown = @($names | Where-Object { $script:XinaoNegativeAllowedKeys -notcontains $_ })
    if ($unknown.Count -gt 0) {
        return [ordered]@{ seal_eligible = $false; reason_code = 'NEGATIVE_RECEIPT_UNKNOWN_KEY'; unknown_keys = $unknown }
    }
    if ((Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'status') -ne 'observed') {
        return [ordered]@{ seal_eligible = $false; reason_code = 'NEGATIVE_SUITE_STATUS_INVALID' }
    }
    if ((Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'suite_passed') -ne $true) {
        return [ordered]@{ seal_eligible = $false; reason_code = 'NEGATIVE_SUITE_NOT_PASSED' }
    }
    if ((Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'unauthorized_domain_reachable') -ne $false) {
        return [ordered]@{ seal_eligible = $false; reason_code = 'NEGATIVE_SUITE_UNAUTHORIZED_DOMAIN' }
    }
    if ((Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'direct_no_proxy_escape') -ne $false) {
        return [ordered]@{ seal_eligible = $false; reason_code = 'NEGATIVE_SUITE_DIRECT_ESCAPE' }
    }
    $cases = @(Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'cases')
    $ids = @()
    foreach ($c in $cases) {
        $cid = if ($c -is [hashtable] -or $c -is [System.Collections.Specialized.OrderedDictionary]) { [string]$c['id'] } else { [string]$c.id }
        $ids += $cid
    }
    $required = @($script:XinaoRequiredNegativeCaseIds)
    $missingCases = @($required | Where-Object { $ids -notcontains $_ })
    if ($missingCases.Count -gt 0) {
        return [ordered]@{ seal_eligible = $false; reason_code = 'NEGATIVE_SUITE_MISSING_CASE'; missing_keys = $missingCases }
    }
    $unknownCases = @($ids | Where-Object { $required -notcontains $_ })
    if ($unknownCases.Count -gt 0) {
        return [ordered]@{ seal_eligible = $false; reason_code = 'NEGATIVE_SUITE_UNKNOWN_CASE' }
    }
    if ([int](Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'pass_count') -ne $required.Count) {
        return [ordered]@{ seal_eligible = $false; reason_code = 'NEGATIVE_SUITE_COUNT_INVALID' }
    }
    if ([int](Get-XinaoReceiptPropertyValue -Receipt $Receipt -Name 'fail_count') -ne 0) {
        return [ordered]@{ seal_eligible = $false; reason_code = 'NEGATIVE_SUITE_COUNT_INVALID' }
    }
    return [ordered]@{ seal_eligible = $true; reason_code = $null }
}

# Export-like marker for static tests (dot-sourced script, not a module).
$script:XinaoEgressOwnerCommonLoaded = $true
