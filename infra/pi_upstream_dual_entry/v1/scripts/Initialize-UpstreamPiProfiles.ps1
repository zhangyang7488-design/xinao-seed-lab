#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('prime-b','prime-s')][string[]]$Profile = @('prime-s'),
    [switch]$ForceAuth
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

Assert-PiDualEntryBinary
$receipts = @()
foreach ($profileName in $Profile) {
    Initialize-PiDualEntryAccountBinding -Profile $profileName | Out-Null
    $spec = Get-PiDualEntrySpec -Profile $profileName
    foreach ($directory in @($spec.AgentDir,$spec.SessionDir)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    foreach ($required in @($spec.Workspace,$spec.SurfaceIsland,$spec.CodexHome,$spec.AgentsSource,$spec.FamilyContractSource,$spec.SurfaceContractSource,$spec.AccountBindingPath)) {
        if (-not (Test-Path -LiteralPath $required)) { throw "PI_PROFILE_SOURCE_MISSING: $required" }
    }
    $contractProjection = Sync-PiDualEntryContractProjection -Spec $spec
    $surfaceOverlay = Sync-PiDualEntrySurfaceOverlay -Spec $spec
    $numpadEnterFollow = $null

    $settingsPath = Join-Path $spec.AgentDir 'settings.json'
    $existingPackages = @()
    if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
        try {
            $existing = Get-Content -Raw -LiteralPath $settingsPath -Encoding UTF8 | ConvertFrom-Json
            if ($null -ne $existing.packages) { $existingPackages = @($existing.packages) }
        } catch { throw "PI_PROFILE_SETTINGS_INVALID: $settingsPath" }
    }
    $settings = [ordered]@{
        defaultProvider = 'openai-codex'
        defaultModel = 'gpt-5.6-sol'
        defaultThinkingLevel = 'max'
        tuiMode = 'fullscreen'
        fullscreenScrollbar = 'always'
        quietStartup = $false
        defaultProjectTrust = 'always'
        enableInstallTelemetry = $false
        sessionDir = $spec.SessionDir.Replace('\','/')
        shellPath = 'C:/Program Files/Git/bin/bash.exe'
        retry = [ordered]@{
            enabled = $true
            maxRetries = 3
            provider = [ordered]@{maxRetries=0;maxRetryDelayMs=60000}
        }
        skills = @($spec.CodexHome.Replace('\','/') + '/skills')
        enableSkillCommands = $true
        subagents = [ordered]@{
            disableBuiltins = $true
            defaultThinking = 'max'
            modelScope = [ordered]@{enforce=$true;allow=@('openai-codex/gpt-5.6-*')}
        }
    }
    if ($profileName -eq 'prime-s') {
        # PiS is intentionally observable: the user wants the visible reasoning stream,
        # provided it is natural Chinese. Ctrl+T remains available for a temporary fold.
        $settings['hideThinkingBlock'] = $false
        # DeepSeek is an independent native Pi provider. It expands the Pi-native child
        # model ecology without routing through a Codex WorkerPool or another profile.
        $settings['subagents']['modelScope']['allow'] = @(
            'openai-codex/gpt-5.6-*',
            'deepseek/deepseek-v4-*'
        )
    }
    if ($existingPackages.Count -gt 0) { $settings.packages = $existingPackages }
    Write-PiDualEntryJsonAtomic -Path $settingsPath -Value $settings

    # pi-subagents deliberately splits agent discovery settings from orchestration runtime
    # settings. The latter are read only from extensions/subagent/config.json; keeping them
    # under settings.json/subagents silently falls back to project-local .pi-subagents state.
    $subagentConfigPath = Join-Path $spec.AgentDir 'extensions\subagent\config.json'
    $subagentConfig = [ordered]@{
        maxSubagentDepth = 2
        maxSubagentSpawnsPerSession = 32
        globalConcurrencyLimit = 4
        asyncByDefault = $false
        forceTopLevelAsync = $false
        fleetView = $true
        fleetViewPlacement = 'aboveEditor'
        asyncWidget = $true
        inlineToolDisplay = 'rich'
        toolDescriptionMode = 'compact'
        artifactDir = 'session'
        defaultSessionDir = (Join-Path $spec.SessionDir 'children').Replace('\','/')
        scheduledRuns = [ordered]@{enabled=$false}
        missions = [ordered]@{enabled=$false}
        proactiveSkillSubagents = $false
        parallel = [ordered]@{maxTasks=8;concurrency=4}
    }
    Write-PiDualEntryJsonAtomic -Path $subagentConfigPath -Value $subagentConfig

    if ($profileName -eq 'prime-s') {
        & (Join-Path $PSScriptRoot 'Set-PiSBodyConfiguration.ps1') -AgentDir $spec.AgentDir | Out-Null
        $numpadRaw = & (Join-Path $PSScriptRoot 'Set-PiSNumpadEnterFollow.ps1') -AgentDir $spec.AgentDir
        $numpadEnterFollow = ($numpadRaw -join [Environment]::NewLine) | ConvertFrom-Json
    }

    $agentsPath = Join-Path $spec.AgentDir 'AGENTS.md'
    if (Test-Path -LiteralPath $agentsPath) {
        $item = Get-Item -LiteralPath $agentsPath -Force
        $knownTargets = @(
            'C:\Users\xx363\.codex\AGENTS.md',
            'C:\Users\xx363\.codex-s-hardmode-account-b\AGENTS.md'
        )
        if ($item.LinkType -eq 'SymbolicLink' -and [string]$item.Target -in $knownTargets) {
            if ([string]$item.Target -ne $spec.AgentsSource) {
                Remove-Item -LiteralPath $agentsPath -Force
                New-Item -ItemType SymbolicLink -Path $agentsPath -Target $spec.AgentsSource | Out-Null
            }
        } else {
            throw "PI_PROFILE_AGENTS_PROJECTION_CONFLICT: $agentsPath"
        }
    } else {
        New-Item -ItemType SymbolicLink -Path $agentsPath -Target $spec.AgentsSource | Out-Null
    }

    $agentProjection = Join-Path $spec.AgentDir 'agents'
    New-Item -ItemType Directory -Force -Path $agentProjection | Out-Null
    $agentSources = @(
        Join-Path (Split-Path -Parent $PSScriptRoot) 'agents\shared\probe.md'
        Join-Path (Split-Path -Parent $PSScriptRoot) 'agents\shared\operator.md'
        Join-Path (Split-Path -Parent $PSScriptRoot) 'agents\shared\verifier.md'
        Join-Path (Split-Path -Parent $PSScriptRoot) 'agents\shared\fanout.md'
    )
    if (Test-Path -LiteralPath $spec.OverlayAgentDir -PathType Container) {
        $agentSources += @(Get-ChildItem -LiteralPath $spec.OverlayAgentDir -File -Filter '*.md' | Sort-Object Name | Select-Object -ExpandProperty FullName)
    }
    $duplicateAgentNames = @($agentSources | Group-Object { Split-Path -Leaf $_ } | Where-Object Count -gt 1)
    if ($duplicateAgentNames.Count -gt 0) {
        throw "PI_PROFILE_AGENT_SOURCE_COLLISION: profile=$profileName names=$($duplicateAgentNames.Name -join ',')"
    }
    $expectedAgentNames = @($agentSources | ForEach-Object { Split-Path -Leaf $_ })
    Get-ChildItem -LiteralPath $agentProjection -File -Filter '*.md' | Where-Object { $_.Name -notin $expectedAgentNames } | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force
    }
    $agentHashes = [ordered]@{}
    foreach ($source in $agentSources) {
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "PI_PROFILE_AGENT_SOURCE_MISSING: $source" }
        $target = Join-Path $agentProjection (Split-Path -Leaf $source)
        Copy-Item -LiteralPath $source -Destination $target -Force
        $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash -ne $sourceHash) {
            throw "PI_PROFILE_AGENT_PROJECTION_DRIFT: $target"
        }
        $agentHashes[[IO.Path]::GetFileNameWithoutExtension($source)] = $sourceHash.ToLowerInvariant()
    }

    $receipts += [ordered]@{
        profile = $profileName
        role = $spec.Role
        account_slot = $spec.AccountSlot
        workspace = $spec.Workspace
        agent_dir = $spec.AgentDir
        session_dir = $spec.SessionDir
        settings_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $settingsPath).Hash.ToLowerInvariant()
        subagent_config = $subagentConfigPath
        subagent_config_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $subagentConfigPath).Hash.ToLowerInvariant()
        agents_source = $spec.AgentsSource
        family_contract = $spec.FamilyContractSource
        surface_contract = $spec.SurfaceContractSource
        contract_projection = $contractProjection.Path
        contract_projection_sha256 = $contractProjection.Sha256
        surface_overlay_manifest = $surfaceOverlay.Path
        surface_overlay_manifest_sha256 = $surfaceOverlay.Sha256
        surface_overlay_owned_files = @($surfaceOverlay.OwnedFiles)
        numpad_enter_follow = $numpadEnterFollow
        account_binding = $spec.AccountBindingPath
        agents = $agentHashes
    }
}

& (Join-Path $PSScriptRoot 'Seed-PiCodexAuth.ps1') -Profile $Profile -Force:$ForceAuth | Out-Null
$receipts | ConvertTo-Json -Depth 6
