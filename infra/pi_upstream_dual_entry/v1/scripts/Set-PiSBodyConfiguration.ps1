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

$target = Get-NormalizedPiSBodyPath -Path $AgentDir
$activeTarget = Get-NormalizedPiSBodyPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s')
$labParent = Get-NormalizedPiSBodyPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
$targetParent = Get-NormalizedPiSBodyPath -Path (Split-Path -Parent $target)
if ($target -ine $activeTarget -and $targetParent -ine $labParent) {
    throw "PI_S_BODY_CONFIG_TARGET_OUTSIDE_PRIME_S: $target"
}

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

[pscustomobject]@{
    schema = 'xinao.pi_s_sparse_body_configuration.v1'
    agent_dir = $target
    hermes_config = $hermesPath
    hermes_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $hermesPath).Hash.ToLowerInvariant()
    hermes_changed = $hermesChanged
    mcp_config = $mcpPath
    mcp_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $mcpPath).Hash.ToLowerInvariant()
    mcp_changed = $mcpChanged
    autonomous_memory_learning_enabled = $false
    ambient_mcp_discovery_enabled = $false
} | ConvertTo-Json -Depth 5
