#Requires -Version 5.1

$script:PiDualEntryVersion = '0.84.1'
$script:PiDualEntryBackupToolRoot = 'D:\XINAO_RESEARCH_RUNTIME\tools\pi\0.84.1'
$script:PiDualEntryMainToolRoot = 'D:\XINAO_RESEARCH_RUNTIME\tools\pi\prime\0.84.1'
$script:PiDualEntryStateRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1'
$script:PiDualEntryMinimumNodeVersion = [version]'22.19.0'
$script:PiDualEntryBehaviorCodexHome = 'C:\Users\xx363\.codex'
$script:PiDualEntryFamilyContract = 'E:\XINAO_RESEARCH_WORKSPACES\pi-local-cognition-contract-island\AGENTS.md'
$script:PiDualEntrySourceRoot = Split-Path -Parent $PSScriptRoot

function Resolve-PiDualEntryAccountBinding {
    param([Parameter(Mandatory)][ValidateSet('main','account-b')][string]$Slot)

    if ($Slot -eq 'main') {
        return [pscustomobject]@{
            Slot = 'main'
            DisplayName = 'Main Codex'
            CodexHome = 'C:\Users\xx363\.codex'
        }
    }
    [pscustomobject]@{
        Slot = 'account-b'
        DisplayName = 'Codex Account B'
        CodexHome = 'C:\Users\xx363\.codex-s-hardmode-account-b'
    }
}

function Get-PiDualEntryDefaultAccountSlot {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)
    if ($Profile -eq 'prime-b') { 'account-b' } else { 'main' }
}

function Get-PiDualEntryAccountBindingPath {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)
    Join-Path $script:PiDualEntryStateRoot "profiles\$Profile\account-binding.json"
}

function Get-PiDualEntryActiveAccountSlot {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)

    $path = Get-PiDualEntryAccountBindingPath -Profile $Profile
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return Get-PiDualEntryDefaultAccountSlot -Profile $Profile
    }
    try {
        $binding = Get-Content -Raw -LiteralPath $path -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "PI_ACCOUNT_BINDING_INVALID: $path"
    }
    $slot = [string]$binding.active_slot
    if ($slot -notin @('main','account-b')) {
        throw "PI_ACCOUNT_BINDING_SLOT_INVALID: profile=$Profile slot=$slot"
    }
    $slot
}

function Get-PiDualEntryAccountBinding {
    param(
        [Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile,
        [ValidateSet('main','account-b')][string]$Slot
    )
    if ([string]::IsNullOrWhiteSpace($Slot)) {
        $Slot = Get-PiDualEntryActiveAccountSlot -Profile $Profile
    }
    Resolve-PiDualEntryAccountBinding -Slot $Slot
}

function Get-PiSubagentCapacityProfile {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)

    if ($Profile -eq 'prime-s') {
        return [pscustomobject]@{
            Scope = 'main-high-capacity'
            HighCapacity = $true
            MaxSubagentDepth = 3
            MaxSubagentSpawnsPerSession = 40
            GlobalConcurrencyLimit = 6
            AsyncByDefault = $false
            ForceTopLevelAsync = $false
            ParallelMaxTasks = 10
            ParallelConcurrency = 6
            DynamicFanoutMaxItems = 10
            ProactiveSkillSubagents = $false
            TurnBudget = [ordered]@{maxTurns=30;graceTurns=0}
            TaskTurnMinimum = 10
            TaskTurnMaximum = 30
        }
    }

    [pscustomobject]@{
        Scope = 'cold-backup-conservative'
        HighCapacity = $false
        MaxSubagentDepth = 2
        MaxSubagentSpawnsPerSession = 32
        GlobalConcurrencyLimit = 4
        AsyncByDefault = $false
        ForceTopLevelAsync = $false
        ParallelMaxTasks = 8
        ParallelConcurrency = 4
        DynamicFanoutMaxItems = $null
        ProactiveSkillSubagents = $false
        TurnBudget = $null
    }
}

function New-PiSubagentCapacityConfig {
    param(
        [Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile,
        [Parameter(Mandatory)][string]$DefaultSessionDir
    )

    $capacity = Get-PiSubagentCapacityProfile -Profile $Profile
    $config = [ordered]@{
        maxSubagentDepth = $capacity.MaxSubagentDepth
        maxSubagentSpawnsPerSession = $capacity.MaxSubagentSpawnsPerSession
        globalConcurrencyLimit = $capacity.GlobalConcurrencyLimit
        asyncByDefault = $capacity.AsyncByDefault
        forceTopLevelAsync = $capacity.ForceTopLevelAsync
        fleetView = $true
        fleetViewPlacement = 'aboveEditor'
        asyncWidget = $true
        inlineToolDisplay = 'rich'
        toolDescriptionMode = 'compact'
        artifactDir = 'session'
        defaultSessionDir = $DefaultSessionDir.Replace('\','/')
        scheduledRuns = [ordered]@{enabled=$false}
        missions = [ordered]@{enabled=$false}
        proactiveSkillSubagents = $capacity.ProactiveSkillSubagents
        parallel = [ordered]@{
            maxTasks = $capacity.ParallelMaxTasks
            concurrency = $capacity.ParallelConcurrency
        }
    }
    if ($null -ne $capacity.TurnBudget) {
        $config['turnBudget'] = $capacity.TurnBudget
    }
    if ($null -ne $capacity.DynamicFanoutMaxItems) {
        $config['chain'] = [ordered]@{
            dynamicFanout = [ordered]@{maxItems=$capacity.DynamicFanoutMaxItems}
        }
    }
    $config
}

function Get-PiSubagentCapacityStaticPolicy {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)

    if ($Profile -ne 'prime-s') {
        return [pscustomobject]@{
            enabled = $false
            schema = $null
            raw = $null
            sha256 = $null
            registry_root = $null
        }
    }

    # Field order is part of the runtime handshake. Keep this byte-for-byte
    # aligned with createStaticCapacityPayload() in the capacity runtime.
    $payload = [ordered]@{
        schema = 'xinao.pi.subagent.capacity.v1'
        profile = 'prime-s'
        registryRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\capacity\prime-s'
        maxSubagentDepth = 3
        maxFanoutWidth = 10
        maxConcurrentProviders = 6
        maxTreeSpawns = 40
        turnMin = 10
        turnMax = 30
        turnDefaultMax = 30
        turnDefaultGrace = 0
        scheduledRuns = $false
        missions = $false
        asyncByDefault = $false
        providerScope = 'recursive-descendant-native-pi-streams'
        fanoutScope = 'per-launching-parent'
        spawnScope = 'durable-root-session-descendants'
        spawnAccounting = 'committed-launches'
        externalCli = $false
    }
    $raw = $payload | ConvertTo-Json -Compress -Depth 4
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $digestBytes = $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($raw))
    } finally {
        $hasher.Dispose()
    }
    $sha256 = ([BitConverter]::ToString($digestBytes)).Replace('-','').ToLowerInvariant()
    $expectedSha256 = 'bf6ba259cf937cf9b5bd0d9afd89243206ea15b759bbebf96c27fb651231a1dc'
    if ($sha256 -cne $expectedSha256) {
        throw "PI_SUBAGENT_CAPACITY_STATIC_POLICY_DRIFT: expected=$expectedSha256 actual=$sha256"
    }

    [pscustomobject]@{
        enabled = $true
        schema = [string]$payload.schema
        raw = $raw
        sha256 = $sha256
        registry_root = [string]$payload.registryRoot
        max_subagent_depth = [int]$payload.maxSubagentDepth
        max_fanout_width = [int]$payload.maxFanoutWidth
        max_concurrent_providers = [int]$payload.maxConcurrentProviders
        max_tree_spawns = [int]$payload.maxTreeSpawns
        turn_min = [int]$payload.turnMin
        turn_max = [int]$payload.turnMax
        turn_default_max = [int]$payload.turnDefaultMax
        turn_default_grace = [int]$payload.turnDefaultGrace
    }
}

function Clear-PiSubagentCapacityEnvironment {
    foreach ($name in @(
        'XINAO_PI_SUBAGENT_CAPACITY_V1',
        'XINAO_PI_SUBAGENT_CAPACITY_SHA256_V1',
        'PI_SUBAGENT_ROOT_OWNER_SESSION',
        'PI_SUBAGENT_ROOT_OWNER_SESSION_SHA256',
        'XINAO_PI_SUBAGENT_LAUNCH_TICKET_V1',
        'XINAO_PI_SUBAGENT_LAUNCH_TICKET_SHA256_V1'
    )) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
}

function Enable-PiSubagentCapacityEnvironment {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)

    Clear-PiSubagentCapacityEnvironment
    $policy = Get-PiSubagentCapacityStaticPolicy -Profile $Profile
    if (-not $policy.enabled) {
        return $policy
    }
    Set-Item -LiteralPath 'Env:XINAO_PI_SUBAGENT_CAPACITY_V1' -Value $policy.raw
    Set-Item -LiteralPath 'Env:XINAO_PI_SUBAGENT_CAPACITY_SHA256_V1' -Value $policy.sha256
    $policy
}

function Assert-PiSubagentCapacityProjection {
    param(
        [Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile,
        [Parameter(Mandatory)][string]$AgentDir
    )

    $expected = Get-PiSubagentCapacityProfile -Profile $Profile
    $configPath = Join-Path $AgentDir 'extensions\subagent\config.json'
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "PI_SUBAGENT_CAPACITY_CONFIG_MISSING: profile=$Profile path=$configPath"
    }
    try { $config = Get-Content -Raw -LiteralPath $configPath -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "PI_SUBAGENT_CAPACITY_CONFIG_INVALID: profile=$Profile path=$configPath" }

    if (
        [int]$config.maxSubagentDepth -ne [int]$expected.MaxSubagentDepth -or
        [int]$config.maxSubagentSpawnsPerSession -ne [int]$expected.MaxSubagentSpawnsPerSession -or
        [int]$config.globalConcurrencyLimit -ne [int]$expected.GlobalConcurrencyLimit -or
        [bool]$config.asyncByDefault -ne [bool]$expected.AsyncByDefault -or
        [bool]$config.forceTopLevelAsync -ne [bool]$expected.ForceTopLevelAsync -or
        [int]$config.parallel.maxTasks -ne [int]$expected.ParallelMaxTasks -or
        [int]$config.parallel.concurrency -ne [int]$expected.ParallelConcurrency -or
        $config.scheduledRuns.enabled -ne $false -or
        $config.missions.enabled -ne $false
    ) {
        throw "PI_SUBAGENT_CAPACITY_PROFILE_DRIFT: profile=$Profile path=$configPath"
    }

    if ($expected.HighCapacity) {
        if (
            $config.proactiveSkillSubagents -ne $false -or
            [int]$config.turnBudget.maxTurns -ne 30 -or
            [int]$config.turnBudget.graceTurns -ne 0 -or
            [int]$config.chain.dynamicFanout.maxItems -ne [int]$expected.DynamicFanoutMaxItems
        ) { throw "PI_SUBAGENT_CAPACITY_MAIN_POLICY_DRIFT: path=$configPath" }
    } elseif (
        $config.proactiveSkillSubagents -ne $false -or
        $null -ne $config.PSObject.Properties['turnBudget'] -or
        $null -ne $config.PSObject.Properties['chain']
    ) {
        throw "PI_SUBAGENT_CAPACITY_COLD_BACKUP_INHERITED_MAIN_POLICY: path=$configPath"
    }

    [pscustomobject]@{
        scope = $expected.Scope
        config_path = $configPath
        config_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $configPath).Hash.ToLowerInvariant()
        max_subagent_depth = [int]$config.maxSubagentDepth
        max_subagent_spawns_per_session = [int]$config.maxSubagentSpawnsPerSession
        global_concurrency_limit = [int]$config.globalConcurrencyLimit
        async_by_default = [bool]$config.asyncByDefault
        force_top_level_async = [bool]$config.forceTopLevelAsync
        parallel_max_tasks = [int]$config.parallel.maxTasks
        parallel_concurrency = [int]$config.parallel.concurrency
        dynamic_fanout_max_items = $(if ($expected.HighCapacity) { [int]$config.chain.dynamicFanout.maxItems } else { $null })
        turn_max = $(if ($expected.HighCapacity) { [int]$config.turnBudget.maxTurns } else { $null })
        turn_grace = $(if ($expected.HighCapacity) { [int]$config.turnBudget.graceTurns } else { $null })
        task_turn_minimum = $(if ($expected.HighCapacity) { [int]$expected.TaskTurnMinimum } else { $null })
        task_turn_maximum = $(if ($expected.HighCapacity) { [int]$expected.TaskTurnMaximum } else { $null })
        proactive_skill_subagents = $false
        scheduled_runs_enabled = [bool]$config.scheduledRuns.enabled
        missions_enabled = [bool]$config.missions.enabled
    }
}

function Initialize-PiDualEntryAccountBinding {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)

    $path = Get-PiDualEntryAccountBindingPath -Profile $Profile
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        [void](Get-PiDualEntryActiveAccountSlot -Profile $Profile)
        return $path
    }
    $slot = Get-PiDualEntryDefaultAccountSlot -Profile $Profile
    $account = Resolve-PiDualEntryAccountBinding -Slot $slot
    Write-PiDualEntryJsonAtomic -Path $path -Value ([ordered]@{
        schema = 'xinao.pi_surface_account_binding.v1'
        profile = $Profile
        active_slot = $slot
        selected_codex_home = $account.CodexHome
        updated_at = [DateTimeOffset]::Now.ToString('o')
    })
    $path
}

function Get-PiDualEntryNodeInfo {
    $nodeCommand = Get-Command node.exe -ErrorAction Stop
    $rawVersion = ([string](& $nodeCommand.Source --version | Select-Object -First 1)).Trim()
    $versionText = $rawVersion.TrimStart('v')
    try { $version = [version]$versionText } catch { throw "PI_NODE_VERSION_UNREADABLE: $rawVersion" }

    [pscustomobject]@{
        Path = $nodeCommand.Source
        RawVersion = $rawVersion
        Version = $version
        Minimum = $script:PiDualEntryMinimumNodeVersion
        MinimumSatisfied = ($version -ge $script:PiDualEntryMinimumNodeVersion)
    }
}

function Get-PiDualEntrySpec {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)

    $account = Get-PiDualEntryAccountBinding -Profile $Profile
    $toolRoot = if ($Profile -eq 'prime-b') {
        $script:PiDualEntryBackupToolRoot
    } else {
        $script:PiDualEntryMainToolRoot
    }
    $agentDir = Join-Path $script:PiDualEntryStateRoot "profiles\$Profile"
    $overlayRoot = Join-Path $script:PiDualEntrySourceRoot "surface-overlays\$Profile"
    $common = [ordered]@{
        Profile = $Profile
        PiToolRoot = $toolRoot
        PiCommand = Join-Path $toolRoot 'node_modules\.bin\pi.cmd'
        AccountSlot = $account.Slot
        AccountDisplayName = $account.DisplayName
        AccountBindingPath = Get-PiDualEntryAccountBindingPath -Profile $Profile
        AgentDir = $agentDir
        SessionDir = Join-Path $agentDir 'sessions'
        CodexHome = $script:PiDualEntryBehaviorCodexHome
        CodexAuthSource = Join-Path $account.CodexHome 'auth.json'
        FamilyContractSource = $script:PiDualEntryFamilyContract
        ContractProjection = Join-Path $agentDir 'PI_CONTRACT.md'
        OverlayRoot = $overlayRoot
        OverlayAgentDir = Join-Path $overlayRoot 'agents'
        OverlayContractDir = Join-Path $overlayRoot 'contract'
        OverlayExtensionDir = Join-Path $overlayRoot 'extensions'
        OverlaySkillDir = Join-Path $overlayRoot 'skills'
        OverlayProjectionManifest = Join-Path $agentDir 'xinao-surface-overlay-manifest.json'
        SupervisorPipe = "\\.\pipe\xinao-pi-supervisor-$Profile-v1"
    }
    if ($Profile -eq 'prime-b') {
        return [pscustomobject]($common + [ordered]@{
            Role = 'cold-backup-snapshot'
            DisplayName = 'PrimeB'
            Workspace = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island'
            SurfaceIsland = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island'
            AgentsSource = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island\AGENTS.md'
            SurfaceContractSource = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island\AGENTS.md'
            SurfaceSentinel = 'PI_SURFACE_PRIME_B_V3'
            Packages = @('npm:pi-subagents@0.44.0','npm:pi-autoresearch@1.6.2','npm:pi-hermes-memory@0.9.4','npm:pi-mcp-adapter@2.21.1')
            ExcludedOverlayAgentNames = @()
            ExcludedTools = @('skill_manage','mcp','mcpScript')
            MutexName = 'Local\XinaoUpstreamPi0841B'
        })
    }
    [pscustomobject]($common + [ordered]@{
        Role = 'primary'
        DisplayName = 'prime'
        Workspace = 'E:\XINAO_RESEARCH_WORKSPACES\S'
        SurfaceIsland = 'E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island'
        AgentsSource = 'E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island\AGENTS.md'
        SurfaceContractSource = 'E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island\AGENTS.md'
        SurfaceSentinel = 'PI_SURFACE_PRIME_S_VERSIONED_V2'
        Packages = @('npm:pi-subagents@0.44.0','npm:pi-hermes-memory@0.9.4','npm:pi-mcp-adapter@2.21.1')
        ExcludedOverlayAgentNames = @('body-friction-auditor.md')
        ExcludedTools = @('skill_manage','mcp','mcpScript')
        MutexName = 'Local\XinaoUpstreamPi0841S'
    })
}

function Exit-PiDualEntryMaintenanceLocks {
    param($Handle)
    if ($null -eq $Handle) { return }
    $locks = @($Handle.Locks)
    for ($index = $locks.Count - 1; $index -ge 0; $index--) {
        $entry = $locks[$index]
        if ($null -eq $entry) { continue }
        try {
            if ([bool]$entry.Held) { $entry.Mutex.ReleaseMutex() }
        } finally {
            if ($null -ne $entry.Mutex) { $entry.Mutex.Dispose() }
        }
    }
}

function Enter-PiDualEntryMaintenanceLocks {
    param(
        [Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string[]]$Profile,
        [switch]$IncludeHighCapacity
    )

    $names = New-Object Collections.Generic.List[string]
    foreach ($profileName in @($Profile | Sort-Object -Unique)) {
        $names.Add([string](Get-PiDualEntrySpec -Profile $profileName).MutexName)
    }
    if ($IncludeHighCapacity -and 'prime-s' -in @($Profile)) {
        $names.Add('Global\XinaoPiSHighCapacityCompatibilityV1')
    }

    $locks = New-Object Collections.Generic.List[object]
    try {
        foreach ($name in @($names)) {
            $mutex = [Threading.Mutex]::new($false,$name)
            $held = $false
            try { $held = $mutex.WaitOne(0) }
            catch [Threading.AbandonedMutexException] { $held = $true }
            if (-not $held) {
                $mutex.Dispose()
                throw "PI_DUAL_ENTRY_MAINTENANCE_TARGET_ACTIVE_OR_BUSY: mutex=$name"
            }
            $locks.Add([pscustomobject]@{ Name = $name; Mutex = $mutex; Held = $true })
        }
        [pscustomobject]@{ Locks = [object[]]$locks.ToArray() }
    } catch {
        Exit-PiDualEntryMaintenanceLocks -Handle ([pscustomobject]@{ Locks = [object[]]$locks.ToArray() })
        throw
    }
}

function Sync-PiDualEntryContractProjection {
    param([Parameter(Mandatory)]$Spec)

    $contractSources = @($Spec.FamilyContractSource,$Spec.SurfaceContractSource)
    if (Test-Path -LiteralPath $Spec.OverlayContractDir -PathType Container) {
        $contractSources += @(Get-ChildItem -LiteralPath $Spec.OverlayContractDir -File -Filter '*.md' | Sort-Object Name | Select-Object -ExpandProperty FullName)
    }
    foreach ($source in $contractSources) {
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "PI_CONTRACT_SOURCE_MISSING: $source"
        }
    }
    New-Item -ItemType Directory -Force -Path $Spec.AgentDir | Out-Null
    $contentParts = @(
        '# GENERATED ACTIVE PI CONTRACT - DO NOT EDIT THIS PROJECTION'
        "# family_source: $($Spec.FamilyContractSource)"
        "# surface_source: $($Spec.SurfaceContractSource)"
    )
    foreach ($source in $contractSources) {
        $contentParts += @('',"# source: $source",'',(Get-Content -Raw -LiteralPath $source -Encoding UTF8).TrimEnd(),'','---')
    }
    $content = (($contentParts -join [Environment]::NewLine).TrimEnd('-',[char]13,[char]10)) + [Environment]::NewLine
    [IO.File]::WriteAllText($Spec.ContractProjection,$content,[Text.UTF8Encoding]::new($false))
    [pscustomobject]@{
        Path = $Spec.ContractProjection
        Sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Spec.ContractProjection).Hash.ToLowerInvariant()
        FamilySha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Spec.FamilyContractSource).Hash.ToLowerInvariant()
        SurfaceSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Spec.SurfaceContractSource).Hash.ToLowerInvariant()
        Sources = @($contractSources)
    }
}

function Sync-PiDualEntrySurfaceOverlay {
    param([Parameter(Mandatory)]$Spec)

    New-Item -ItemType Directory -Force -Path $Spec.AgentDir | Out-Null
    $previousOwned = @()
    if (Test-Path -LiteralPath $Spec.OverlayProjectionManifest -PathType Leaf) {
        try {
            $previous = Get-Content -Raw -LiteralPath $Spec.OverlayProjectionManifest -Encoding UTF8 | ConvertFrom-Json
        } catch {
            throw "PI_PROFILE_OVERLAY_MANIFEST_INVALID: $($Spec.OverlayProjectionManifest)"
        }
        if ([string]$previous.schema -ne 'xinao.pi_surface_overlay_projection.v1' -or [string]$previous.profile -ne [string]$Spec.Profile) {
            throw "PI_PROFILE_OVERLAY_MANIFEST_IDENTITY_MISMATCH: $($Spec.OverlayProjectionManifest)"
        }
        $previousOwned = @($previous.owned_files | ForEach-Object { [string]$_ })
    }

    $sourceKinds = [ordered]@{
        agents = $Spec.OverlayAgentDir
        extensions = $Spec.OverlayExtensionDir
        skills = $Spec.OverlaySkillDir
    }
    $owned = @()
    $hashes = [ordered]@{}
    foreach ($kind in $sourceKinds.Keys) {
        $sourceRoot = [string]$sourceKinds[$kind]
        if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) { continue }
        $sourcePrefix = [IO.Path]::GetFullPath($sourceRoot).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
        foreach ($source in @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | Sort-Object FullName)) {
            if ($kind -eq 'agents' -and $source.Name -in @($Spec.ExcludedOverlayAgentNames)) { continue }
            $sourceFull = [IO.Path]::GetFullPath($source.FullName)
            if (-not $sourceFull.StartsWith($sourcePrefix,[StringComparison]::OrdinalIgnoreCase)) {
                throw "PI_PROFILE_OVERLAY_SOURCE_ESCAPE: $sourceFull"
            }
            $relative = $sourceFull.Substring($sourcePrefix.Length).Replace('\','/')
            if ([string]::IsNullOrWhiteSpace($relative) -or $relative -match '(^|/)\.\.(/|$)') {
                throw "PI_PROFILE_OVERLAY_RELATIVE_PATH_INVALID: $relative"
            }
            $ownedRelative = "$kind/$relative"
            if ($ownedRelative -in $owned) { throw "PI_PROFILE_OVERLAY_SOURCE_COLLISION: $ownedRelative" }
            $destination = Join-Path $Spec.AgentDir $ownedRelative.Replace('/','\')
            $destinationParent = Split-Path -Parent $destination
            New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
            $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceFull).Hash.ToLowerInvariant()
            if ((Test-Path -LiteralPath $destination -PathType Leaf) -and $ownedRelative -notin $previousOwned) {
                $existingHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
                if ($existingHash -ne $sourceHash) {
                    throw "PI_PROFILE_OVERLAY_PROJECTION_CONFLICT: $destination"
                }
            }
            Copy-Item -LiteralPath $sourceFull -Destination $destination -Force
            $destinationHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
            if ($destinationHash -ne $sourceHash) { throw "PI_PROFILE_OVERLAY_PROJECTION_DRIFT: $destination" }
            $owned += $ownedRelative
            $hashes[$ownedRelative] = $sourceHash
        }
    }

    $agentPrefix = [IO.Path]::GetFullPath($Spec.AgentDir).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    foreach ($stale in @($previousOwned | Where-Object { $_ -notin $owned })) {
        if ($stale -notmatch '^(agents|extensions|skills)/' -or $stale -match '(^|/)\.\.(/|$)') {
            throw "PI_PROFILE_OVERLAY_STALE_PATH_INVALID: $stale"
        }
        $stalePath = [IO.Path]::GetFullPath((Join-Path $Spec.AgentDir $stale.Replace('/','\')))
        if (-not $stalePath.StartsWith($agentPrefix,[StringComparison]::OrdinalIgnoreCase)) {
            throw "PI_PROFILE_OVERLAY_STALE_PATH_ESCAPE: $stalePath"
        }
        if (Test-Path -LiteralPath $stalePath -PathType Leaf) {
            Remove-Item -LiteralPath $stalePath -Force
        }
    }

    Write-PiDualEntryJsonAtomic -Path $Spec.OverlayProjectionManifest -Value ([ordered]@{
        schema = 'xinao.pi_surface_overlay_projection.v1'
        profile = $Spec.Profile
        source_root = $Spec.OverlayRoot
        owned_files = @($owned)
        sha256 = $hashes
    })
    [pscustomobject]@{
        Path = $Spec.OverlayProjectionManifest
        Sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Spec.OverlayProjectionManifest).Hash.ToLowerInvariant()
        OwnedFiles = @($owned)
        Hashes = $hashes
    }
}

function Assert-PiDualEntryBinary {
    param([Parameter(Mandatory)]$Spec)

    $node = Get-PiDualEntryNodeInfo
    if (-not $node.MinimumSatisfied) {
        throw "PI_NODE_VERSION_TOO_OLD: required=$($node.Minimum) actual=$($node.Version) path=$($node.Path)"
    }
    if (-not (Test-Path -LiteralPath $Spec.PiCommand -PathType Leaf)) {
        throw "PI_0841_BINARY_MISSING: profile=$($Spec.Profile) path=$($Spec.PiCommand)"
    }
    $versionOutput = @(& $Spec.PiCommand --version 2>$null)
    $actual = ([string]($versionOutput | Select-Object -First 1)).Trim()
    if (-not [string]::Equals($actual, $script:PiDualEntryVersion, [StringComparison]::Ordinal)) {
        throw "PI_VERSION_MISMATCH: profile=$($Spec.Profile) expected=$script:PiDualEntryVersion actual=$actual"
    }
}

function Invoke-PiDualEntryNativeCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw "PI_NATIVE_COMMAND_NOT_FOUND: $FilePath"
    }

    $previousErrorActionPreference = $ErrorActionPreference
    $nativeOutput = @()
    $nativeExitCode = $null
    try {
        # Windows PowerShell 5.1 turns redirected native stderr into a terminating
        # NativeCommandError when the caller uses Stop, even when the process exits 0.
        # Capture both streams here and let the real native exit code decide success.
        $ErrorActionPreference = 'Continue'
        $nativeOutput = @(& $FilePath @ArgumentList 2>&1)
        $nativeExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($null -eq $nativeExitCode) {
        throw "PI_NATIVE_COMMAND_EXIT_CODE_MISSING: $FilePath"
    }

    [pscustomobject]@{
        exit_code = [int]$nativeExitCode
        output = @($nativeOutput | ForEach-Object { [string]$_ })
    }
}

function Test-PiDualEntryAuth {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        $auth = Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json
        $provider = $auth.'openai-codex'
        return (
            $null -ne $provider -and
            [string]$provider.type -eq 'oauth' -and
            -not [string]::IsNullOrWhiteSpace([string]$provider.access) -and
            -not [string]::IsNullOrWhiteSpace([string]$provider.refresh) -and
            -not [string]::IsNullOrWhiteSpace([string]$provider.accountId)
        )
    } catch { return $false }
}

function Get-PiDualEntryAuthAccountId {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-PiDualEntryAuth -Path $Path)) { return $null }
    $auth = Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json
    [string]$auth.'openai-codex'.accountId
}

function Write-PiDualEntryJsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value,
        [int]$Depth = 12
    )
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Path.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()).tmp"
    $json = $Value | ConvertTo-Json -Depth $Depth
    [IO.File]::WriteAllText($temporary,$json + [Environment]::NewLine,[Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}
