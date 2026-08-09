#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$AgentDir = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSBodyPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Write-PiSBodyJsonIfChanged {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value,
        [int]$Depth = 12
    )
    $expected = ($Value | ConvertTo-Json -Depth $Depth) + [Environment]::NewLine
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $current = [IO.File]::ReadAllText($Path,[Text.UTF8Encoding]::new($false))
        if ($current -ceq $expected) { return $false }
    }
    Write-PiDualEntryJsonAtomic -Path $Path -Value $Value -Depth $Depth
    return $true
}

function Get-PiSBodyJsonPropertyValue {
    param(
        $Object,
        [Parameter(Mandatory)][string]$Name
    )
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

$target = Get-NormalizedPiSBodyPath -Path $AgentDir
$primeSProfileTarget = Get-NormalizedPiSBodyPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s')
$primeBProfileTarget = Get-NormalizedPiSBodyPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-b')
$primeSLabParent = Get-NormalizedPiSBodyPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
$primeBLabParent = Get-NormalizedPiSBodyPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-b')
$activeTargets = @(
    $primeSProfileTarget
    $primeBProfileTarget
)
$labParents = @(
    $primeSLabParent
    $primeBLabParent
)
$targetParent = Get-NormalizedPiSBodyPath -Path (Split-Path -Parent $target)
if ($target -notin $activeTargets -and $targetParent -notin $labParents) {
    throw "PI_BODY_CONFIG_TARGET_OUTSIDE_MANAGED_PROFILE: $target"
}
$isMainPrimeSBody = ($target -eq $primeSProfileTarget -or $targetParent -eq $primeSLabParent)

New-Item -ItemType Directory -Force -Path $target | Out-Null

# Hermes is deliberately reduced to a profile-local retrieval and explicit-memory
# organ. It does not continuously review, infer corrections, write standing rules,
# flush conversations into memory, or run an LLM consolidation behind the user.
$hermesPath = Join-Path $target 'hermes-memory-config.json'
$hermesConfig = [ordered]@{
    memoryMode = 'policy-only'
    memoryPolicyStyle = 'custom'
    memoryPolicyCustomText = 'Persistent memory is non-authoritative candidate context. Search it when prior context is materially relevant. Save only durable user-provided preferences, verified environment facts, or reusable lessons; never save secrets, temporary task state, unverified research claims, or authority. Current user words and live facts always override memory.'
    reviewEnabled = $false
    reviewTransport = 'direct'
    reviewRecentMessages = 0
    flushOnCompact = $false
    flushOnShutdown = $false
    flushRecentMessages = 0
    memoryOverflowStrategy = 'reject'
    autoConsolidate = $false
    correctionDetection = $false
    failureInjectionEnabled = $false
    nudgeInterval = 0
    nudgeToolCalls = 0
    standingInstructionsEnabled = $false
    projectsMemoryDir = 'projects-memory'
    sessionSearch = [ordered]@{variant = 'anchors'}
}
# Main prime keeps a larger explicit global/failure-memory working set. Hermes
# derives the failure limit as 2x memoryCharLimit. User and project memories
# retain the upstream 5k boundary, and the isolated PrimeB snapshot retains its
# byte-for-byte default-derived configuration.
if ($isMainPrimeSBody) {
    $hermesConfig['memoryCharLimit'] = 10000
    $hermesConfig['userCharLimit'] = 5000
    $hermesConfig['projectCharLimit'] = 5000
}
$hermesChanged = Write-PiSBodyJsonIfChanged -Path $hermesPath -Value $hermesConfig

# MCP is installed as a cold connection organ. No ambient host import, server,
# direct schema, script tool, auth flow, sampling, or elicitation is activated.
$mcpPath = Join-Path $target 'mcp.json'
$mcpConfig = [ordered]@{
    settings = [ordered]@{
        hostConfigDiscovery = 'off'
        agentPluginPaths = @()
        directTools = $false
        scriptMode = $false
        autoAuth = $false
        sampling = $false
        samplingAutoApprove = $false
        elicitation = $false
        mcpFooterStatus = 'off'
        showStatusIcon = $false
        idleTimeout = 5
        outputGuard = $true
    }
    mcpServers = [ordered]@{}
}
$mcpChanged = Write-PiSBodyJsonIfChanged -Path $mcpPath -Value $mcpConfig

# The provider model catalog is the authority for a model's real context window. A local
# override above that value suppresses Pi's early compaction and lets a request reach the
# provider only after it is already too large. Remove only this profile-local override;
# preserve every unrelated provider/model customization and let future catalog updates flow.
$modelsPath = Join-Path $target 'models.json'
$unsupportedContextWindowOverrideRemoved = $false
$removedContextWindowValue = $null
$modelsOverrideChanged = $false
if (Test-Path -LiteralPath $modelsPath -PathType Leaf) {
    $models = Get-Content -Raw -LiteralPath $modelsPath -Encoding UTF8 | ConvertFrom-Json
    $providers = Get-PiSBodyJsonPropertyValue -Object $models -Name 'providers'
    $openAiCodex = Get-PiSBodyJsonPropertyValue -Object $providers -Name 'openai-codex'
    $modelOverrides = Get-PiSBodyJsonPropertyValue -Object $openAiCodex -Name 'modelOverrides'
    $solOverride = Get-PiSBodyJsonPropertyValue -Object $modelOverrides -Name 'gpt-5.6-sol'
    $contextProperty = if ($null -ne $solOverride) { $solOverride.PSObject.Properties['contextWindow'] } else { $null }
    if ($null -ne $contextProperty) {
        $removedContextWindowValue = $contextProperty.Value
        $solOverride.PSObject.Properties.Remove('contextWindow')
        $unsupportedContextWindowOverrideRemoved = $true
        $modelsOverrideChanged = $true
    }
    if ($null -ne $solOverride -and @($solOverride.PSObject.Properties).Count -eq 0) {
        $modelOverrides.PSObject.Properties.Remove('gpt-5.6-sol')
        $modelsOverrideChanged = $true
    }
    if ($null -ne $modelOverrides -and @($modelOverrides.PSObject.Properties).Count -eq 0) {
        $openAiCodex.PSObject.Properties.Remove('modelOverrides')
        $modelsOverrideChanged = $true
    }
    if ($null -ne $openAiCodex -and @($openAiCodex.PSObject.Properties).Count -eq 0) {
        $providers.PSObject.Properties.Remove('openai-codex')
        $modelsOverrideChanged = $true
    }
    if ($null -ne $providers -and @($providers.PSObject.Properties).Count -eq 0) {
        $models.PSObject.Properties.Remove('providers')
        $modelsOverrideChanged = $true
    }
    if ($modelsOverrideChanged) {
        if (@($models.PSObject.Properties).Count -eq 0) {
            Remove-Item -LiteralPath $modelsPath -Force
        } else {
            Write-PiDualEntryJsonAtomic -Path $modelsPath -Value $models
        }
    }
}

[pscustomobject]@{
    schema = 'xinao.pi_sparse_body_configuration.v1'
    agent_dir = $target
    hermes_config = $hermesPath
    hermes_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $hermesPath).Hash.ToLowerInvariant()
    hermes_changed = $hermesChanged
    hermes_memory_capacity_scope = $(if ($isMainPrimeSBody) { 'main-prime-s-explicit' } else { 'upstream-default-derived' })
    hermes_memory_char_limit = $(if ($isMainPrimeSBody) { 10000 } else { 5000 })
    hermes_user_char_limit = 5000
    hermes_project_char_limit = 5000
    hermes_failure_char_limit = $(if ($isMainPrimeSBody) { 20000 } else { 10000 })
    mcp_config = $mcpPath
    mcp_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $mcpPath).Hash.ToLowerInvariant()
    mcp_changed = $mcpChanged
    models_override_path = $modelsPath
    unsupported_context_window_override_removed = $unsupportedContextWindowOverrideRemoved
    removed_context_window_value = $removedContextWindowValue
    models_override_changed = $modelsOverrideChanged
    context_window_source = 'provider_model_catalog'
    autonomous_memory_learning_enabled = $false
    ambient_mcp_discovery_enabled = $false
} | ConvertTo-Json -Depth 5
