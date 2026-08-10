#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('prime-b','prime-s')][string[]]$Profile = @('prime-s'),
    [switch]$SkipAuthRefresh,
    [switch]$RunLiveModelProbe,
    [switch]$RequireLiveReturnAcceptance,
    [string]$ReceiptPath
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-PiSurfaceTextSha256 {
    param([Parameter(Mandatory)][string]$Text)
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
    } finally {
        if ($null -ne $sha) { $sha.Dispose() }
    }
}

function Get-PiSurfaceBytesSha256 {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant()
    } finally {
        if ($null -ne $sha) { $sha.Dispose() }
    }
}

function Get-PiSubagentsSourceAggregateSha256 {
    param([Parameter(Mandatory)][string]$AgentDir)
    $sourceRoot = Join-Path $AgentDir 'npm\node_modules\pi-subagents\src'
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) { return 'absent' }
    $prefix = [IO.Path]::GetFullPath($sourceRoot).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    $lines = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
        $relative = [IO.Path]::GetFullPath($_.FullName).Substring($prefix.Length).Replace('\','/')
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        "$relative`t$($_.Length)`t$hash"
    })
    Get-PiSurfaceTextSha256 -Text ($lines -join "`n")
}

$profileRoot = Join-Path $script:PiDualEntryStateRoot 'profiles'
$actualProfileNames = @(Get-ChildItem -LiteralPath $profileRoot -Directory | Select-Object -ExpandProperty Name | Sort-Object)
$unexpectedProfiles = @($actualProfileNames | Where-Object { $_ -notin @('prime-b','prime-s') })
if ($unexpectedProfiles.Count -gt 0) {
    throw "PI_SURFACE_TEST_OBSOLETE_PROFILE_PRESENT: $($unexpectedProfiles -join ',')"
}
$legacyLivePaths = @(
    'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island\contracts\IDENTITY_AND_TRUST.md',
    'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island\contracts\USER_RULES_AND_COMPLETION.md',
    'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island\scripts\Start-Prime-Local-Cognition.ps1'
)
$legacyLivePresent = @($legacyLivePaths | Where-Object { Test-Path -LiteralPath $_ })
if ($legacyLivePresent.Count -gt 0) { throw "PI_SURFACE_TEST_LEGACY_0_7_LIVE_CARRIER_PRESENT: $($legacyLivePresent -join ',')" }
$legacyRetired = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island\contracts\evidence\prime-agent-0.7.0-pre-upgrade-20260808\RETIRED.md'
if (-not (Select-String -LiteralPath $legacyRetired -Pattern 'PRIME_AGENT_0_7_ISLAND_EPOCH_RETIRED_V1' -SimpleMatch -Quiet)) {
    throw 'PI_SURFACE_TEST_LEGACY_0_7_RETIREMENT_SENTINEL_MISSING'
}
$surfaceResults = @()
$allNativeWindowsHide = $true
foreach ($profileName in $Profile) {
    $spec = Get-PiDualEntrySpec -Profile $profileName
    Assert-PiDualEntryBinary -Spec $spec
    Clear-PiSubagentCapacityEnvironment
    $env:PI_CODING_AGENT_DIR = $spec.AgentDir
    $env:PI_CODING_AGENT_SESSION_DIR = $spec.SessionDir
    $env:PI_SKIP_VERSION_CHECK = '1'
    $env:PI_TELEMETRY = '0'
    $env:CODEX_HOME = $spec.CodexHome
    $env:XINAO_ACCOUNT_SLOT = $spec.AccountSlot
    $env:XINAO_PI_ROLE = $spec.Role

    $projection = Sync-PiDualEntryContractProjection -Spec $spec
    $overlayProjection = Sync-PiDualEntrySurfaceOverlay -Spec $spec
    $expectedOverlayOwned = @()
    foreach ($overlayKind in @(
        [pscustomobject]@{ Name = 'agents'; Root = $spec.OverlayAgentDir },
        [pscustomobject]@{ Name = 'extensions'; Root = $spec.OverlayExtensionDir },
        [pscustomobject]@{ Name = 'skills'; Root = $spec.OverlaySkillDir }
    )) {
        if (-not (Test-Path -LiteralPath $overlayKind.Root -PathType Container)) { continue }
        $overlayKindPrefix = [IO.Path]::GetFullPath($overlayKind.Root).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
        $expectedOverlayOwned += @(Get-ChildItem -LiteralPath $overlayKind.Root -Recurse -File | Where-Object {
            $overlayKind.Name -cne 'agents' -or $_.Name -notin @($spec.ExcludedOverlayAgentNames)
        } | ForEach-Object {
            "$($overlayKind.Name)/$([IO.Path]::GetFullPath($_.FullName).Substring($overlayKindPrefix.Length).Replace('\','/'))"
        })
    }
    $actualOverlayOwned = @($overlayProjection.OwnedFiles | ForEach-Object { [string]$_ })
    if (
        @($expectedOverlayOwned | Where-Object { $_ -notin $actualOverlayOwned }).Count -ne 0 -or
        @($actualOverlayOwned | Where-Object { $_ -notin $expectedOverlayOwned }).Count -ne 0
    ) { throw "PI_SURFACE_TEST_OVERLAY_OWNERSHIP_MISMATCH: profile=$profileName" }
    if ($profileName -eq 'prime-s' -and 'agents/peer.md' -notin $actualOverlayOwned) {
        throw 'PI_SURFACE_TEST_PEER_NOT_OWNED_BY_OVERLAY'
    }
    $authPath = Join-Path $spec.AgentDir 'auth.json'
    $settingsPath = Join-Path $spec.AgentDir 'settings.json'
    $subagentConfigPath = Join-Path $spec.AgentDir 'extensions\subagent\config.json'
    $agentsPath = Join-Path $spec.AgentDir 'AGENTS.md'
    $hermesConfigPath = Join-Path $spec.AgentDir 'hermes-memory-config.json'
    foreach ($required in @($spec.FamilyContractSource,$spec.SurfaceContractSource,$spec.ContractProjection,$spec.AccountBindingPath,$authPath,$settingsPath,$subagentConfigPath,$agentsPath,$hermesConfigPath,$spec.CodexAuthSource)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "PI_SURFACE_TEST_REQUIRED_FILE_MISSING: profile=$profileName path=$required"
        }
    }
    if (-not (Test-PiDualEntryAuth -Path $authPath)) { throw "PI_SURFACE_TEST_AUTH_INVALID: $profileName" }
    $sourceAuth = Get-Content -Raw -LiteralPath $spec.CodexAuthSource -Encoding UTF8 | ConvertFrom-Json
    if ([string]$sourceAuth.tokens.account_id -ne (Get-PiDualEntryAuthAccountId -Path $authPath)) {
        throw "PI_SURFACE_TEST_ACCOUNT_BINDING_MISMATCH: profile=$profileName slot=$($spec.AccountSlot)"
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $agentsPath).Hash -ne (Get-FileHash -Algorithm SHA256 -LiteralPath $spec.AgentsSource).Hash) {
        throw "PI_SURFACE_TEST_AGENTS_DRIFT: $profileName"
    }
    $contractText = Get-Content -Raw -LiteralPath $spec.ContractProjection -Encoding UTF8
    foreach ($sentinel in @('PI_LOCAL_COMPATIBILITY_BOUNDARY_V3',$spec.SurfaceSentinel)) {
        if ($contractText -notmatch [regex]::Escape($sentinel)) {
            throw "PI_SURFACE_TEST_CONTRACT_SENTINEL_MISSING: profile=$profileName sentinel=$sentinel"
        }
    }

    $settings = Get-Content -Raw -LiteralPath $settingsPath -Encoding UTF8 | ConvertFrom-Json
    $subagentConfig = Get-Content -Raw -LiteralPath $subagentConfigPath -Encoding UTF8 | ConvertFrom-Json
    $hermesConfig = Get-Content -Raw -LiteralPath $hermesConfigPath -Encoding UTF8 | ConvertFrom-Json
    if (@($settings.skills).Count -ne 0) {
        throw "PI_SURFACE_TEST_CODEX_SKILL_TREE_INJECTED: profile=$profileName"
    }
    if ([string]$hermesConfig.memoryOverflowStrategy -cne 'reject' -or $hermesConfig.failureInjectionEnabled -ne $false) {
        throw "PI_SURFACE_TEST_HERMES_MEMORY_POLICY_INVALID: profile=$profileName"
    }
    $hermesLimitNames = @('memoryCharLimit','userCharLimit','projectCharLimit')
    $hermesMemoryCapacity = $null
    if ($profileName -eq 'prime-s') {
        if (
            [int]$hermesConfig.memoryCharLimit -ne 10000 -or
            [int]$hermesConfig.userCharLimit -ne 5000 -or
            [int]$hermesConfig.projectCharLimit -ne 5000
        ) { throw 'PI_SURFACE_TEST_MAIN_HERMES_MEMORY_CAPACITY_INVALID' }
        $hermesMemoryCapacity = [ordered]@{
            scope = 'main-prime-s-explicit'
            memory_char_limit = 10000
            user_char_limit = 5000
            project_char_limit = 5000
            failure_char_limit = 20000
            overflow_strategy = [string]$hermesConfig.memoryOverflowStrategy
        }
    } else {
        $unexpectedHermesLimits = @($hermesLimitNames | Where-Object { $null -ne $hermesConfig.PSObject.Properties[$_] })
        if ($unexpectedHermesLimits.Count -ne 0) {
            throw "PI_SURFACE_TEST_COLD_BACKUP_INHERITED_HERMES_MEMORY_CAPACITY: $($unexpectedHermesLimits -join ',')"
        }
        $hermesMemoryCapacity = [ordered]@{
            scope = 'upstream-default-derived'
            explicit_limits = $false
        }
    }
    $catalogContextWindow = $null
    $profileContextWindowOverrideAbsent = $null
    $modelsStorePath = Join-Path $spec.AgentDir 'models-store.json'
        if (-not (Test-Path -LiteralPath $modelsStorePath -PathType Leaf)) {
            throw "PI_SURFACE_TEST_PROVIDER_MODEL_CATALOG_MISSING: $modelsStorePath"
        }
        $modelsStore = Get-Content -Raw -LiteralPath $modelsStorePath -Encoding UTF8 | ConvertFrom-Json
        $providerProperty = $modelsStore.PSObject.Properties['openai-codex']
        $catalogModels = if ($null -ne $providerProperty) { @($providerProperty.Value.models) } else { @() }
        $catalogSol = @($catalogModels | Where-Object { [string]$_.id -ceq 'gpt-5.6-sol' })
        if ($catalogSol.Count -ne 1 -or [int64]$catalogSol[0].contextWindow -le 0) {
            throw 'PI_SURFACE_TEST_SOL_CONTEXT_WINDOW_CATALOG_INVALID'
        }
        $catalogContextWindow = [int64]$catalogSol[0].contextWindow

        $modelsOverridePath = Join-Path $spec.AgentDir 'models.json'
        if (Test-Path -LiteralPath $modelsOverridePath -PathType Leaf) {
            $modelsOverride = Get-Content -Raw -LiteralPath $modelsOverridePath -Encoding UTF8 | ConvertFrom-Json
            $providersProperty = $modelsOverride.PSObject.Properties['providers']
            $codexProperty = if ($null -ne $providersProperty) { $providersProperty.Value.PSObject.Properties['openai-codex'] } else { $null }
            $modelOverridesProperty = if ($null -ne $codexProperty) { $codexProperty.Value.PSObject.Properties['modelOverrides'] } else { $null }
            $solOverrideProperty = if ($null -ne $modelOverridesProperty) { $modelOverridesProperty.Value.PSObject.Properties['gpt-5.6-sol'] } else { $null }
            $contextOverrideProperty = if ($null -ne $solOverrideProperty) { $solOverrideProperty.Value.PSObject.Properties['contextWindow'] } else { $null }
            if ($null -ne $contextOverrideProperty) {
                throw "PI_SURFACE_TEST_UNSUPPORTED_SOL_CONTEXT_WINDOW_OVERRIDE: $($contextOverrideProperty.Value)"
            }
        }
    $profileContextWindowOverrideAbsent = $true
    $highCapacityMain = $profileName -eq 'prime-s'
    if (
        [string]$subagentConfig.artifactDir -ne 'session' -or
        $subagentConfig.scheduledRuns.enabled -ne $false -or
        $subagentConfig.missions.enabled -ne $false
    ) { throw "PI_SURFACE_TEST_SUBAGENT_RUNTIME_CONFIG_INVALID: profile=$profileName" }
    $subagentCapacity = Assert-PiSubagentCapacityProjection -Profile $profileName -AgentDir $spec.AgentDir
    $subagentCapacityStaticPolicy = Get-PiSubagentCapacityStaticPolicy -Profile $profileName
    if ($highCapacityMain) {
        if (
            -not $subagentCapacityStaticPolicy.enabled -or
            [string]$subagentCapacityStaticPolicy.schema -cne 'xinao.pi.subagent.capacity.v1' -or
            [string]$subagentCapacityStaticPolicy.sha256 -cne 'bf6ba259cf937cf9b5bd0d9afd89243206ea15b759bbebf96c27fb651231a1dc' -or
            [int]$subagentCapacityStaticPolicy.max_subagent_depth -ne 3 -or
            [int]$subagentCapacityStaticPolicy.max_fanout_width -ne 10 -or
            [int]$subagentCapacityStaticPolicy.max_concurrent_providers -ne 6 -or
            [int]$subagentCapacityStaticPolicy.max_tree_spawns -ne 40 -or
            [int]$subagentCapacityStaticPolicy.turn_min -ne 10 -or
            [int]$subagentCapacityStaticPolicy.turn_max -ne 30
        ) { throw 'PI_SURFACE_TEST_CAPACITY_STATIC_POLICY_INVALID' }
    } elseif (
        $subagentCapacityStaticPolicy.enabled -or
        -not [string]::IsNullOrWhiteSpace([string]$subagentCapacityStaticPolicy.raw) -or
        -not [string]::IsNullOrWhiteSpace([string]$subagentCapacityStaticPolicy.sha256)
    ) {
        throw 'PI_SURFACE_TEST_PRIME_B_INHERITED_CAPACITY_STATIC_POLICY'
    }
    $expectedPackages = @($spec.Packages)
    $actualPackages = @($settings.packages)
    if (@($expectedPackages | Where-Object { $_ -notin $actualPackages }).Count -gt 0 -or @($actualPackages | Where-Object { $_ -notin $expectedPackages }).Count -gt 0) {
        throw "PI_SURFACE_TEST_PACKAGE_SET_MISMATCH: profile=$profileName actual=$($actualPackages -join ',')"
    }
    $expectedAgentNames = @('probe','operator','verifier','fanout')
    if (Test-Path -LiteralPath $spec.OverlayAgentDir -PathType Container) {
        $expectedAgentNames += @(Get-ChildItem -LiteralPath $spec.OverlayAgentDir -File -Filter '*.md' | Where-Object {
            $_.Name -notin @($spec.ExcludedOverlayAgentNames)
        } | ForEach-Object { $_.BaseName })
    }
    foreach ($agentName in $expectedAgentNames) {
        if (-not (Test-Path -LiteralPath (Join-Path $spec.AgentDir "agents\$agentName.md") -PathType Leaf)) {
            throw "PI_SURFACE_TEST_AGENT_MISSING: profile=$profileName agent=$agentName"
        }
    }
    $peerAgentAcceptance = $null
    $recursivePeerAcceptance = $null
    if ($profileName -eq 'prime-s') {
        $peerAgentPath = Join-Path $spec.AgentDir 'agents\peer.md'
        $peerAgentSourcePath = Join-Path $spec.OverlayAgentDir 'peer.md'
        if (-not (Test-Path -LiteralPath $peerAgentPath -PathType Leaf)) {
            throw "PI_SURFACE_TEST_PEER_AGENT_MISSING: $peerAgentPath"
        }
        if (-not (Test-Path -LiteralPath $peerAgentSourcePath -PathType Leaf)) {
            throw "PI_SURFACE_TEST_PEER_AGENT_SOURCE_MISSING: $peerAgentSourcePath"
        }
        $peerAgentSourceSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $peerAgentSourcePath).Hash.ToLowerInvariant()
        $peerAgentActiveSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $peerAgentPath).Hash.ToLowerInvariant()
        $peerOverlayManifest = Get-Content -Raw -LiteralPath $spec.OverlayProjectionManifest -Encoding UTF8 | ConvertFrom-Json
        $peerAgentManifestSha256 = [string]$peerOverlayManifest.sha256.'agents/peer.md'
        if (
            $peerAgentSourceSha256 -cne $peerAgentActiveSha256 -or
            $peerAgentSourceSha256 -cne $peerAgentManifestSha256
        ) { throw 'PI_SURFACE_TEST_PEER_AGENT_SOURCE_ACTIVE_MANIFEST_DRIFT' }
        $peerAgentText = Get-Content -Raw -LiteralPath $peerAgentPath -Encoding UTF8
        $peerAgentNormalized = ($peerAgentText -replace '\s+', ' ').Trim()
        $peerRequiredFragments = @(
            'name: peer',
            'model: openai-codex/gpt-5.6-terra',
            'acceptanceRole: read-only',
            'maxSubagentDepth: 0',
            'without a permanent profession',
            'Work directly on the exact object, evidence, and requested result',
            'do not modify repositories or external state'
        )
        $peerMissingFragments = @($peerRequiredFragments | Where-Object { $peerAgentNormalized.IndexOf($_, [StringComparison]::Ordinal) -lt 0 })
        if ($peerMissingFragments.Count -gt 0 -or $peerAgentText -match '(?m)^tools:.*\b(edit|write|subagent)\b') {
            throw "PI_SURFACE_TEST_PEER_AGENT_CONTRACT_INVALID: missing=$($peerMissingFragments -join ',')"
        }
        $peerAgentAcceptance = [ordered]@{
            name = 'peer'
            fixed_profession = $false
            default_model = 'openai-codex/gpt-5.6-terra'
            per_run_model_override_allowed = $true
            repository_effects_allowed = $false
            candidate_only = $true
            lifecycle_decision_encoded = $false
            source_sha256 = $peerAgentSourceSha256
            active_sha256 = $peerAgentActiveSha256
            manifest_sha256 = $peerAgentManifestSha256
        }
        $recursivePeerPath = Join-Path $spec.AgentDir 'agents\recursive-peer.md'
        if (-not (Test-Path -LiteralPath $recursivePeerPath -PathType Leaf)) {
            throw "PI_SURFACE_TEST_RECURSIVE_PEER_MISSING: $recursivePeerPath"
        }
        $recursivePeerText = Get-Content -Raw -LiteralPath $recursivePeerPath -Encoding UTF8
        $recursivePeerNormalized = ($recursivePeerText -replace '\s+', ' ').Trim()
        $recursivePeerRequiredFragments = @(
            'name: recursive-peer',
            'thinking: max',
            'tools: subagent',
            'inheritProjectContext: false',
            'inheritSkills: false',
            'defaultContext: fresh',
            'acceptanceRole: read-only',
            'async: true',
            'maxSubagentDepth: 3',
            'turnBudget: {"maxTurns":30,"graceTurns":0}',
            'Fresh candidate computation',
            'Keep doing your own synthesis while children run',
            'Recursion expands candidate computation, not authority'
        )
        $recursivePeerMissing = @($recursivePeerRequiredFragments | Where-Object {
            $recursivePeerNormalized.IndexOf($_, [StringComparison]::Ordinal) -lt 0
        })
        if (
            $recursivePeerMissing.Count -gt 0 -or
            $recursivePeerText -match '(?m)^model:' -or
            $recursivePeerText -match '(?m)^tools:.*\b(read|grep|find|ls|bash|edit|write|web_search)\b'
        ) {
            throw "PI_SURFACE_TEST_RECURSIVE_PEER_CONTRACT_INVALID: missing=$($recursivePeerMissing -join ',')"
        }
        $recursivePeerAcceptance = [ordered]@{
            name = 'recursive-peer'
            model_policy = 'inherit-current-root-or-explicit-task-override'
            fixed_model = $false
            thinking = 'max'
            max_subagent_depth = 3
            max_turns = 30
            grace_turns = 0
            async = $true
            recursive_tool = 'subagent'
            file_shell_network_tools = $false
            candidate_only = $true
        }
        $bodyFrictionPath = Join-Path $spec.AgentDir 'agents\body-friction-auditor.md'
        if (Test-Path -LiteralPath $bodyFrictionPath -PathType Leaf) {
            throw "PI_SURFACE_TEST_EXCLUDED_BODY_FRICTION_AGENT_PRESENT: $bodyFrictionPath"
        }
    }

    $authArgs = @('auth','check','--provider','openai-codex','--json')
    if ($SkipAuthRefresh) { $authArgs += '--no-refresh' }
    $authRaw = @(& $spec.PiCommand @authArgs 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_AUTH_CHECK_FAILED: profile=$profileName output=$($authRaw -join ' ')" }
    $authResult = ($authRaw -join [Environment]::NewLine) | ConvertFrom-Json
    $authReady = ([string]$authResult.status -eq 'ready' -and [string]$authResult.provider -eq 'openai-codex')
    if (-not $authReady) { throw "PI_SURFACE_TEST_AUTH_NOT_READY: profile=$profileName status=$($authResult.status)" }

    $rpcRaw = @('{"type":"get_commands"}') | & $spec.PiCommand --mode rpc --no-session --offline --provider openai-codex --model gpt-5.6-sol --thinking max --append-system-prompt $spec.ContractProjection
    if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_RPC_FAILED: $profileName" }
    $rpcObjects = @($rpcRaw | ForEach-Object { try { $_ | ConvertFrom-Json } catch {} })
    $commandResponse = $rpcObjects | Where-Object { $_.type -eq 'response' -and $_.command -eq 'get_commands' -and $_.success -eq $true } | Select-Object -Last 1
    if ($null -eq $commandResponse) { throw "PI_SURFACE_TEST_COMMAND_CATALOG_MISSING: $profileName" }
    $names = @($commandResponse.data.commands | ForEach-Object { [string]$_.name })
    $codexOnlySkills = @(
        'skill:productivity',
        'skill:repair-agent-behavior',
        'skill:operate-for-user',
        'skill:research-external-reality',
        'skill:dispatch-grok-worker-pool'
    )
    $injectedSkills = @($codexOnlySkills | Where-Object { $_ -in $names })
    if ($injectedSkills.Count -gt 0) {
        throw "PI_SURFACE_TEST_CODEX_SKILLS_VISIBLE: profile=$profileName skills=$($injectedSkills -join ',')"
    }

    $numpadAcceptance = $null
    $activityVisibilityAcceptance = $null
    $midTurnCompactionAcceptance = $null
    $ownerSessionStopCompatibility = $null
    $ownerSessionStopAcceptance = $null
    $ownerSessionStopProcessAcceptance = $null
    $filesystemPolicyCompatibility = $null
    $filesystemPolicyAcceptance = $null
    $filesystemPolicyReceiptIdentity = $null
    $supervisorIngressAcceptance = $null
    $nativeContinuationCompatibility = $null
    $nativeContinuationAbsence = $null
    $highCapacityCompatibility = $null
    $highCapacityAcceptance = $null
    $highCapacityActiveProjectionReceiptIdentity = $null
    $highCapacityReplayAcceptance = $null
    $highCapacityReplayReceiptIdentity = $null
    $highCapacityAbsence = $null
    $midTurnRaw = @(& (Join-Path $PSScriptRoot 'Apply-PiSMidTurnCompactionCompatibility.ps1') -PiToolRoot $spec.PiToolRoot -VerifyOnly 2>&1)
    $midTurnCompactionAcceptance = ($midTurnRaw -join [Environment]::NewLine) | ConvertFrom-Json
    if (
        [string]$midTurnCompactionAcceptance.schema -ne 'xinao.pi_midturn_compaction_compatibility.v2' -or
        $midTurnCompactionAcceptance.profile_scoped_runtime_gate_required -ne $true -or
        @($midTurnCompactionAcceptance.managed_profiles | Where-Object { $_ -in @('prime-s','prime-b') }).Count -ne 2 -or
        $midTurnCompactionAcceptance.completed_tool_boundary_stop -ne $true -or
        $midTurnCompactionAcceptance.compact_and_continue_same_run -ne $true -or
        $midTurnCompactionAcceptance.compaction_failure_stops_before_provider -ne $true
    ) {
        throw "PI_SURFACE_TEST_MIDTURN_PATCH_STATUS_INVALID: $($midTurnRaw -join ' ')"
    }
    $piPackageRoot = Join-Path $spec.PiToolRoot 'node_modules\@earendil-works\pi-coding-agent'
    if ($profileName -eq 'prime-s') {
        $nativeRaw = @(& (Join-Path $PSScriptRoot 'Apply-PiSNativeContinuationCompatibility.ps1') -PiToolRoot $spec.PiToolRoot -VerifyOnly 2>&1)
        $nativeContinuationCompatibility = ($nativeRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if (
            [string]$nativeContinuationCompatibility.schema -cne 'xinao.pi_native_continuation_compatibility.v1' -or
            $nativeContinuationCompatibility.extension_abort_epoch -ne $true -or
            $nativeContinuationCompatibility.post_agent_queue_fence -ne $true -or
            $nativeContinuationCompatibility.agent_start_abort_fence -ne $true -or
            $nativeContinuationCompatibility.pre_provider_abort_fence -ne $true -or
            $nativeContinuationCompatibility.public_agent_session_abort_unchanged -ne $true -or
            $nativeContinuationCompatibility.clear_pending_messages_api_added -ne $false -or
            $midTurnCompactionAcceptance.native_continuation_downstream_composed -ne $true
        ) { throw "PI_SURFACE_TEST_NATIVE_CONTINUATION_PATCH_INVALID: $($nativeRaw -join ' ')" }
    } else {
        $nativeAbsentExpected = [ordered]@{
            'dist\core\agent-session.js' = '3d42e3311f1b7b5b72aa81dd745cf7a8e089e9b7708abe5e33b9b553651739e6'
            'dist\core\agent-session.d.ts' = 'c18a61cf0952d19b2d7dfebcfbc0850d5103bcf53e867e466c6d69bcc1b618f6'
            'node_modules\@earendil-works\pi-agent-core\dist\agent-loop.js' = '43cc779ddaf90df41768d3d2d0f7d7ba8b8bce7bedc9dc6062ca8b4de84ae880'
        }
        $nativeAbsentActual = [ordered]@{}
        foreach ($relative in $nativeAbsentExpected.Keys) {
            $nativeAbsentActual[$relative] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $piPackageRoot $relative)).Hash.ToLowerInvariant()
            if ($nativeAbsentActual[$relative] -cne $nativeAbsentExpected[$relative]) {
                throw "PI_SURFACE_TEST_COLD_BACKUP_NATIVE_CONTINUATION_PRESENT_OR_MIXED: file=$relative actual=$($nativeAbsentActual[$relative])"
            }
        }
        if ($midTurnCompactionAcceptance.native_continuation_downstream_composed -ne $false) {
            throw 'PI_SURFACE_TEST_COLD_BACKUP_MIDTURN_WRONGLY_REPORTS_NATIVE_COMPOSITION'
        }
        $nativeContinuationAbsence = [pscustomobject]@{
            schema = 'xinao.pi_native_continuation_cold_negative.v1'
            native_continuation_absent = $true
            exact_midturn_underlay_sha256 = $nativeAbsentActual
        }
        $coldPackageCapacityRuntime = Join-Path $spec.AgentDir 'npm\node_modules\pi-subagents\src\runs\shared\xinao-pi-subagent-capacity-runtime.js'
        $coldCoreCapacityRuntime = Join-Path $piPackageRoot 'dist\core\xinao-pi-subagent-capacity-runtime.js'
        $coldCoreSdk = Join-Path $piPackageRoot 'dist\core\sdk.js'
        $coldCoreSdkSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $coldCoreSdk).Hash.ToLowerInvariant()
        if (
            (Test-Path -LiteralPath $coldPackageCapacityRuntime) -or
            (Test-Path -LiteralPath $coldCoreCapacityRuntime) -or
            $coldCoreSdkSha256 -cne 'f6e72f33f44c708249c8d74931d816c36fe27175f7fa1639cba0a3d988592821'
        ) { throw 'PI_SURFACE_TEST_COLD_BACKUP_HIGH_CAPACITY_PRESENT_OR_MIXED' }
        $highCapacityAbsence = [pscustomobject]@{
            schema = 'xinao.pi_high_capacity_cold_negative.v1'
            high_capacity_absent = $true
            package_runtime_absent = $true
            core_runtime_absent = $true
            core_sdk_sha256 = $coldCoreSdkSha256
            static_handshake_absent = -not $subagentCapacityStaticPolicy.enabled
        }
    }
    $post0841UpstreamAcceptance = $null
    if ($profileName -eq 'prime-s') {
        $ownerStopRaw = @(& (Join-Path $PSScriptRoot 'Apply-PiSSubagentsSessionStopCompatibility.ps1') -AgentDir $spec.AgentDir -VerifyOnly 2>&1)
        $ownerSessionStopCompatibility = ($ownerStopRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if (
            [string]$ownerSessionStopCompatibility.schema -ne 'xinao.pi_s_subagents_owner_session_stop_compatibility.v2' -or
            $ownerSessionStopCompatibility.owner_session_stop_rpc -ne $true -or
            $ownerSessionStopCompatibility.exact_owner_union -ne $true -or
            $ownerSessionStopCompatibility.new_launch_fence -ne $true -or
            $ownerSessionStopCompatibility.detached_process_terminal_observation -ne $true -or
            $ownerSessionStopCompatibility.windows_stop_owns_child_process_tree -ne $true -or
            $ownerSessionStopCompatibility.cold_backup_modified -ne $false
        ) { throw "PI_SURFACE_TEST_OWNER_SESSION_STOP_PATCH_INVALID: $($ownerStopRaw -join ' ')" }
        $filesystemPolicyRaw = @(& (Join-Path $PSScriptRoot 'Apply-PiSSubagentsFilesystemPolicy.ps1') -AgentDir $spec.AgentDir -VerifyOnly 2>&1)
        $filesystemPolicyCompatibility = ($filesystemPolicyRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if (
            [string]$filesystemPolicyCompatibility.schema -cne 'xinao.pi_s_subagents_filesystem_policy_compatibility.v1' -or
            [string]$filesystemPolicyCompatibility.patch_id -cne 'pi-subagents-0.44.0-task-filesystem-policy-v1' -or
            [int]$filesystemPolicyCompatibility.source_file_count -ne 15 -or
            $filesystemPolicyCompatibility.v1_fresh_single_child_only -ne $true -or
            $filesystemPolicyCompatibility.bash_fixed_deny -ne $true -or
            $filesystemPolicyCompatibility.project_context_and_skills_forced_off -ne $true -or
            [int]$filesystemPolicyCompatibility.restricted_max_subagent_depth -ne 0 -or
            $filesystemPolicyCompatibility.async_resume_requires_consistent_durable_policy -ne $true -or
            $filesystemPolicyCompatibility.prime_b_modified -ne $false
        ) { throw "PI_SURFACE_TEST_FILESYSTEM_POLICY_PATCH_INVALID: $($filesystemPolicyRaw -join ' ')" }
        $highCapacityRaw = @(& (Join-Path $PSScriptRoot 'Apply-PiSHighCapacityCompatibility.ps1') -AgentDir $spec.AgentDir -PiToolRoot $spec.PiToolRoot -VerifyOnly 2>&1)
        $highCapacityCompatibility = ($highCapacityRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if (
            [string]$highCapacityCompatibility.schema -cne 'xinao.pi_s_high_capacity_compatibility.v1' -or
            $highCapacityCompatibility.changed -ne $false -or
            $highCapacityCompatibility.handshake_written -ne $false
        ) { throw "PI_SURFACE_TEST_HIGH_CAPACITY_PATCH_INVALID: $($highCapacityRaw -join ' ')" }
        $highCapacityProjectionReceiptPath = Join-Path $script:PiDualEntryStateRoot 'acceptance\pi-high-capacity-active-projection-v1.json'
        $highCapacityProjectionRaw = @(& (Join-Path $PSScriptRoot 'Test-PiSHighCapacityReplay.ps1') -AgentDir $spec.AgentDir -PiToolRoot $spec.PiToolRoot -ProjectionOnly -ReceiptPath $highCapacityProjectionReceiptPath 2>&1)
        $highCapacityAcceptance = ($highCapacityProjectionRaw -join [Environment]::NewLine) | ConvertFrom-Json
        $currentPeerSourceSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $spec.OverlayAgentDir 'peer.md')).Hash.ToLowerInvariant()
        $highCapacityManifestPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'patches\pi-s-high-capacity-v4.2-manifest.json'
        $currentHighCapacityManifestSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $highCapacityManifestPath).Hash.ToLowerInvariant()
        $filesystemApplyPath = Join-Path $PSScriptRoot 'Apply-PiSSubagentsFilesystemPolicy.ps1'
        $currentFilesystemApplySha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $filesystemApplyPath).Hash.ToLowerInvariant()
        $filesystemResumeScriptPath = Join-Path $PSScriptRoot 'Test-PiSHighCapacityFilesystemResume.ps1'
        $currentFilesystemResumeScriptSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $filesystemResumeScriptPath).Hash.ToLowerInvariant()
        $bodyLabHarnessPath = Join-Path $PSScriptRoot 'Test-PiSubagentFilesystemPolicyBodyLab.mjs'
        $currentBodyLabHarnessSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $bodyLabHarnessPath).Hash.ToLowerInvariant()
        if (
            [string]$highCapacityAcceptance.schema -cne 'xinao.pi_s_high_capacity_active_projection_acceptance.v1' -or
            [string]$highCapacityAcceptance.status -cne 'active_projection_verified' -or
            $highCapacityAcceptance.projection_only -ne $true -or
            [int]$highCapacityAcceptance.tests.expected -ne 48 -or
            [int]$highCapacityAcceptance.tests.observed -ne 48 -or
            [int]$highCapacityAcceptance.tests.passed -ne 48 -or
            [int]$highCapacityAcceptance.tests.failed -ne 0 -or
            [string]$highCapacityAcceptance.strict_typescript.status -cne 'pass' -or
            $highCapacityAcceptance.strict_typescript.strict -ne $true -or
            $highCapacityAcceptance.strict_typescript.no_unchecked_indexed_access -ne $true -or
            $highCapacityAcceptance.strict_typescript.skip_lib_check -ne $false -or
            $highCapacityAcceptance.runtime_projection.byte_equal -ne $true -or
            [int64]$highCapacityAcceptance.runtime_projection.bytes -ne 47259 -or
            [string]$highCapacityAcceptance.runtime_projection.sha256 -cne 'ba5614b01ee3b2c15194d1006596bef50134fdd4f86125713cf61987f7be76b2' -or
            [string]$highCapacityAcceptance.candidate_manifest.sha256 -cne $currentHighCapacityManifestSha256 -or
            [string]$highCapacityAcceptance.compatibility_inputs.filesystem_apply_sha256 -cne $currentFilesystemApplySha256 -or
            [string]$highCapacityAcceptance.acceptance_sources.kind -cne 'relative-path-bytes-sha256-v1' -or
            [int]$highCapacityAcceptance.acceptance_sources.count -ne 11 -or
            [string]$highCapacityAcceptance.peer.sha256 -cne $currentPeerSourceSha256 -or
            $highCapacityAcceptance.temp_cleanup -ne $true
        ) { throw "PI_SURFACE_TEST_HIGH_CAPACITY_ACTIVE_PROJECTION_INVALID: $highCapacityProjectionReceiptPath" }
        $highCapacityProjectionReceiptFile = Get-Item -LiteralPath $highCapacityProjectionReceiptPath
        $highCapacityActiveProjectionReceiptIdentity = [ordered]@{
            path = $highCapacityProjectionReceiptPath
            bytes = [int64]$highCapacityProjectionReceiptFile.Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $highCapacityProjectionReceiptPath).Hash.ToLowerInvariant()
            schema = [string]$highCapacityAcceptance.schema
            status = [string]$highCapacityAcceptance.status
            projection_only = [bool]$highCapacityAcceptance.projection_only
            tests_passed = [int]$highCapacityAcceptance.tests.passed
            runtime_projection = [ordered]@{
                bytes = [int64]$highCapacityAcceptance.runtime_projection.bytes
                sha256 = [string]$highCapacityAcceptance.runtime_projection.sha256
            }
            acceptance_sources = [ordered]@{
                kind = [string]$highCapacityAcceptance.acceptance_sources.kind
                count = [int]$highCapacityAcceptance.acceptance_sources.count
                aggregate_sha256 = [string]$highCapacityAcceptance.acceptance_sources.aggregate_sha256
            }
            candidate_manifest_sha256 = [string]$highCapacityAcceptance.candidate_manifest.sha256
            filesystem_apply_sha256 = [string]$highCapacityAcceptance.compatibility_inputs.filesystem_apply_sha256
            peer_sha256 = [string]$highCapacityAcceptance.peer.sha256
            temp_cleanup = [bool]$highCapacityAcceptance.temp_cleanup
        }

        # The active profile proves only its projected bytes. Provider, resume, hostile-environment,
        # owner-stop, and filesystem recovery run in a disposable paired body-lab and are accepted
        # only when that receipt is bound to the exact current acceptance sources and inputs above.
        $highCapacityReplayReceiptPath = Join-Path $script:PiDualEntryStateRoot 'acceptance\pi-high-capacity-current-lab-replay-v1.json'
        if (-not (Test-Path -LiteralPath $highCapacityReplayReceiptPath -PathType Leaf)) {
            throw "PI_SURFACE_TEST_HIGH_CAPACITY_LAB_REPLAY_RECEIPT_MISSING: $highCapacityReplayReceiptPath"
        }
        $highCapacityReplayAcceptance = Get-Content -Raw -LiteralPath $highCapacityReplayReceiptPath -Encoding UTF8 | ConvertFrom-Json
        $activeAcceptanceSourceRows = @($highCapacityAcceptance.acceptance_sources.members | ForEach-Object {
            "$([string]$_.path)`t$([int64]$_.bytes)`t$([string]$_.sha256)"
        } | Sort-Object)
        $replayAcceptanceSourceRows = @($highCapacityReplayAcceptance.acceptance_sources.members | ForEach-Object {
            "$([string]$_.path)`t$([int64]$_.bytes)`t$([string]$_.sha256)"
        } | Sort-Object)
        $bodyLabRoot = [IO.Path]::GetFullPath((Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')).TrimEnd('\','/')
        $replayAgentDir = [IO.Path]::GetFullPath([string]$highCapacityReplayAcceptance.agent_dir).TrimEnd('\','/')
        $replayPiToolRoot = [IO.Path]::GetFullPath([string]$highCapacityReplayAcceptance.pi_tool_root).TrimEnd('\','/')
        $expectedReplayPiToolRoot = [IO.Path]::GetFullPath((Join-Path $replayAgentDir 'pi-tool-root')).TrimEnd('\','/')
        if (
            [string]$highCapacityReplayAcceptance.schema -cne 'xinao.pi_s_high_capacity_replay_acceptance.v1' -or
            [string]$highCapacityReplayAcceptance.status -cne 'verified' -or
            $highCapacityReplayAcceptance.projection_only -ne $false -or
            -not $replayAgentDir.StartsWith($bodyLabRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
            $replayPiToolRoot -cne $expectedReplayPiToolRoot -or
            [int]$highCapacityReplayAcceptance.tests.expected -ne 48 -or
            [int]$highCapacityReplayAcceptance.tests.observed -ne 48 -or
            [int]$highCapacityReplayAcceptance.tests.passed -ne 48 -or
            [int]$highCapacityReplayAcceptance.tests.failed -ne 0 -or
            [string]$highCapacityReplayAcceptance.strict_typescript.status -cne 'pass' -or
            $highCapacityReplayAcceptance.strict_typescript.strict -ne $true -or
            $highCapacityReplayAcceptance.strict_typescript.no_unchecked_indexed_access -ne $true -or
            $highCapacityReplayAcceptance.strict_typescript.skip_lib_check -ne $false -or
            $highCapacityReplayAcceptance.runtime_projection.byte_equal -ne $true -or
            [int64]$highCapacityReplayAcceptance.runtime_projection.bytes -ne 47259 -or
            [string]$highCapacityReplayAcceptance.runtime_projection.sha256 -cne 'ba5614b01ee3b2c15194d1006596bef50134fdd4f86125713cf61987f7be76b2' -or
            [string]$highCapacityReplayAcceptance.candidate_manifest.sha256 -cne $currentHighCapacityManifestSha256 -or
            [string]$highCapacityReplayAcceptance.compatibility_inputs.filesystem_apply_sha256 -cne $currentFilesystemApplySha256 -or
            [string]$highCapacityReplayAcceptance.acceptance_sources.kind -cne 'relative-path-bytes-sha256-v1' -or
            [int]$highCapacityReplayAcceptance.acceptance_sources.count -ne 11 -or
            [string]$highCapacityReplayAcceptance.acceptance_sources.aggregate_sha256 -cne [string]$highCapacityAcceptance.acceptance_sources.aggregate_sha256 -or
            ($replayAcceptanceSourceRows -join "`n") -cne ($activeAcceptanceSourceRows -join "`n") -or
            [string]$highCapacityReplayAcceptance.peer.sha256 -cne $currentPeerSourceSha256 -or
            [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.schema -cne 'xinao.pi_s_high_capacity_filesystem_resume_acceptance.v1' -or
            [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.status -cne 'verified' -or
            [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.script_sha256 -cne $currentFilesystemResumeScriptSha256 -or
            [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.canonical_harness_sha256 -cne $currentBodyLabHarnessSha256 -or
            $highCapacityReplayAcceptance.filesystem_resume_cross_product.paired_pi_tool_root -ne $true -or
            $highCapacityReplayAcceptance.filesystem_resume_cross_product.core_paths_no_reparse -ne $true -or
            $highCapacityReplayAcceptance.filesystem_resume_cross_product.owner_stop_process_terminated -ne $true -or
            $highCapacityReplayAcceptance.filesystem_resume_cross_product.candidate_mutable_files_restored -ne $true -or
            $highCapacityReplayAcceptance.filesystem_resume_cross_product.candidate_child_sessions_restored -ne $true -or
            $highCapacityReplayAcceptance.filesystem_resume_cross_product.work_root_cleanup.removed -ne $true -or
            $highCapacityReplayAcceptance.filesystem_resume_cross_product.hostile_root_cleanup.removed -ne $true -or
            $highCapacityReplayAcceptance.temp_cleanup -ne $true
        ) { throw "PI_SURFACE_TEST_HIGH_CAPACITY_LAB_REPLAY_INVALID: $highCapacityReplayReceiptPath" }
        $highCapacityReplayReceiptFile = Get-Item -LiteralPath $highCapacityReplayReceiptPath
        $highCapacityReplayReceiptIdentity = [ordered]@{
            path = $highCapacityReplayReceiptPath
            bytes = [int64]$highCapacityReplayReceiptFile.Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $highCapacityReplayReceiptPath).Hash.ToLowerInvariant()
            schema = [string]$highCapacityReplayAcceptance.schema
            status = [string]$highCapacityReplayAcceptance.status
            projection_only = [bool]$highCapacityReplayAcceptance.projection_only
            agent_dir = [string]$highCapacityReplayAcceptance.agent_dir
            pi_tool_root = [string]$highCapacityReplayAcceptance.pi_tool_root
            tests_passed = [int]$highCapacityReplayAcceptance.tests.passed
            runtime_projection = [ordered]@{
                bytes = [int64]$highCapacityReplayAcceptance.runtime_projection.bytes
                sha256 = [string]$highCapacityReplayAcceptance.runtime_projection.sha256
            }
            acceptance_sources = [ordered]@{
                kind = [string]$highCapacityReplayAcceptance.acceptance_sources.kind
                count = [int]$highCapacityReplayAcceptance.acceptance_sources.count
                aggregate_sha256 = [string]$highCapacityReplayAcceptance.acceptance_sources.aggregate_sha256
            }
            candidate_manifest = [ordered]@{
                sha256 = [string]$highCapacityReplayAcceptance.candidate_manifest.sha256
                generation = [string]$highCapacityReplayAcceptance.candidate_manifest.generation
                package_files = [int]$highCapacityReplayAcceptance.candidate_manifest.package_files
                core_files = [int]$highCapacityReplayAcceptance.candidate_manifest.core_files
            }
            compatibility_inputs = [ordered]@{
                filesystem_apply_bytes = [int64]$highCapacityReplayAcceptance.compatibility_inputs.filesystem_apply_bytes
                filesystem_apply_sha256 = [string]$highCapacityReplayAcceptance.compatibility_inputs.filesystem_apply_sha256
            }
            filesystem_resume = [ordered]@{
                schema = [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.schema
                status = [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.status
                script_sha256 = [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.script_sha256
                receipt_sha256 = [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.receipt_sha256
                receipt_bytes = [int64]$highCapacityReplayAcceptance.filesystem_resume_cross_product.receipt_bytes
                canonical_harness_sha256 = [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.canonical_harness_sha256
                projected_harness_sha256 = [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.projected_harness_sha256
                capacity_config_sha256 = [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.capacity_config_sha256
                filesystem_policy_digest = [string]$highCapacityReplayAcceptance.filesystem_resume_cross_product.filesystem_policy_digest
                resume_reached_provider = [bool]$highCapacityReplayAcceptance.filesystem_resume_cross_product.resume_reached_provider
                no_policy_resume_reached_provider = [bool]$highCapacityReplayAcceptance.filesystem_resume_cross_product.no_policy_resume_reached_provider
                owner_stop_process_terminated = [bool]$highCapacityReplayAcceptance.filesystem_resume_cross_product.owner_stop_process_terminated
                candidate_mutable_files_restored = [bool]$highCapacityReplayAcceptance.filesystem_resume_cross_product.candidate_mutable_files_restored
                candidate_child_sessions_restored = [bool]$highCapacityReplayAcceptance.filesystem_resume_cross_product.candidate_child_sessions_restored
                work_root_removed = [bool]$highCapacityReplayAcceptance.filesystem_resume_cross_product.work_root_cleanup.removed
                hostile_root_removed = [bool]$highCapacityReplayAcceptance.filesystem_resume_cross_product.hostile_root_cleanup.removed
            }
            peer_sha256 = [string]$highCapacityReplayAcceptance.peer.sha256
            temp_cleanup = [bool]$highCapacityReplayAcceptance.temp_cleanup
        }
        $ownerStopBehaviorRaw = @(& node (Join-Path $PSScriptRoot 'Test-PiSubagentSessionStop.mjs') 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_OWNER_SESSION_STOP_FAILED: $($ownerStopBehaviorRaw -join ' ')" }
        $ownerSessionStopAcceptance = ($ownerStopBehaviorRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if (
            [string]$ownerSessionStopAcceptance.status -ne 'module_mechanically_verified' -or
            $ownerSessionStopAcceptance.exact_owner_union -ne $true -or
            $ownerSessionStopAcceptance.foreign_session_untouched -ne $true -or
            $ownerSessionStopAcceptance.pending_proof_is_partial -ne $true -or
            $ownerSessionStopAcceptance.launch_fence_present_at_entry_and_commit -ne $true -or
            $ownerSessionStopAcceptance.windows_stop_owns_child_process_tree -ne $true -or
            $ownerSessionStopAcceptance.owner_mismatch_fails_closed_and_retry_recovers -ne $true -or
            [string]$ownerSessionStopAcceptance.real_process_termination_status -ne 'pending_isolated_process' -or
            [string]$ownerSessionStopAcceptance.launch_fence_race_status -ne 'pending_isolated_process'
        ) { throw "PI_SURFACE_TEST_OWNER_SESSION_STOP_BEHAVIOR_INVALID: $($ownerStopBehaviorRaw -join ' ')" }
        $subagentsPackageRoot = Join-Path $spec.AgentDir 'npm\node_modules\pi-subagents'
        $filesystemPolicyReceiptPath = Join-Path $script:PiDualEntryStateRoot 'acceptance\pi-subagents-filesystem-policy-v1.json'
        if (-not (Test-Path -LiteralPath $filesystemPolicyReceiptPath -PathType Leaf)) {
            throw "PI_SURFACE_TEST_FILESYSTEM_POLICY_RECEIPT_MISSING: $filesystemPolicyReceiptPath"
        }
        $filesystemPolicyReceiptBytes = [IO.File]::ReadAllBytes($filesystemPolicyReceiptPath)
        if ($filesystemPolicyReceiptBytes.Length -le 0 -or $filesystemPolicyReceiptBytes.Length -gt 2097152) {
            throw "PI_SURFACE_TEST_FILESYSTEM_POLICY_RECEIPT_SIZE_INVALID: $($filesystemPolicyReceiptBytes.Length)"
        }
        $filesystemPolicyReceiptSha256 = Get-PiSurfaceBytesSha256 -Bytes $filesystemPolicyReceiptBytes
        try {
            $filesystemPolicyReceiptRaw = [Text.UTF8Encoding]::new($false,$true).GetString($filesystemPolicyReceiptBytes)
        } catch {
            throw 'PI_SURFACE_TEST_FILESYSTEM_POLICY_RECEIPT_UTF8_INVALID'
        }
        $filesystemPolicyAcceptance = $filesystemPolicyReceiptRaw | ConvertFrom-Json
        $policyBody = $filesystemPolicyAcceptance.body_lab
        $policySecurity = $filesystemPolicyAcceptance.security
        $currentActivePiSubagentsSourceSha256 = Get-PiSubagentsSourceAggregateSha256 -AgentDir $spec.AgentDir
        $primeBSpecForFilesystemReceipt = Get-PiDualEntrySpec -Profile 'prime-b'
        $currentPrimeBPiSubagentsSourceSha256 = Get-PiSubagentsSourceAggregateSha256 -AgentDir $primeBSpecForFilesystemReceipt.AgentDir
        $policySourceFiles = [ordered]@{
            acceptance_wrapper = Join-Path $PSScriptRoot 'Test-PiSFilesystemPolicyAcceptance.ps1'
            common = Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1'
            apply = Join-Path $PSScriptRoot 'Apply-PiSSubagentsFilesystemPolicy.ps1'
            windows = Join-Path $PSScriptRoot 'Apply-PiSSubagentsWindowsCompatibility.ps1'
            owner_stop = Join-Path $PSScriptRoot 'Apply-PiSSubagentsSessionStopCompatibility.ps1'
            start = Join-Path $PSScriptRoot 'Start-UpstreamPi.ps1'
            install = Join-Path $PSScriptRoot 'Install-UpstreamPiCapabilities.ps1'
            body_lab_factory = Join-Path $PSScriptRoot 'New-PiSBodyLab.ps1'
            dual_entry_acceptance = $PSCommandPath
            readme = Join-Path (Split-Path -Parent $PSScriptRoot) 'README.md'
            patch = Join-Path (Split-Path -Parent $PSScriptRoot) 'patches\pi-subagents-0.44.0-filesystem-policy.patch'
            security_harness = Join-Path $PSScriptRoot 'Test-PiSubagentFilesystemPolicy.mjs'
            body_harness = Join-Path $PSScriptRoot 'Test-PiSubagentFilesystemPolicyBodyLab.mjs'
            owner_stop_harness = Join-Path $PSScriptRoot 'Test-PiSubagentSessionStopProcess.mjs'
            owner_stop_extension = Join-Path $PSScriptRoot 'fixtures\pi-owner-stop-autolaunch.ts'
            owner_stop_fixture = Join-Path $PSScriptRoot 'fixtures\pi-owner-stop-child.mjs'
        }
        $policySourceHashMismatch = @($policySourceFiles.GetEnumerator() | Where-Object {
            $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.Value).Hash.ToLowerInvariant()
            [string]$filesystemPolicyAcceptance.source_sha256.($_.Key) -cne $actual
        })
        $packageSourceHashMismatch = @($policyBody.filesystem_policy_source_sha256.PSObject.Properties | Where-Object {
            $sourcePath = Join-Path $subagentsPackageRoot ([string]$_.Name).Replace('/','\')
            -not (Test-Path -LiteralPath $sourcePath -PathType Leaf) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant() -cne [string]$_.Value
        })
        $expectedTranscriptCases = @(
            'CASE_BASH_DENY','CASE_BROAD_GREP','CASE_DENIED_READ','CASE_DETACHED_SAFE',
            'CASE_FOREGROUND_SAFE','CASE_JUNCTION_READ','CASE_NO_POLICY_BASH',
            'CASE_NO_POLICY_DETACHED_SAFE','CASE_NO_POLICY_RESUME_SAFE','CASE_RESUME_SAFE',
            'CASE_SAFE_GREP'
        )
        $transcriptEvidenceProperties = @($policyBody.child_tool_result_evidence.PSObject.Properties)
        $transcriptEvidence = @($transcriptEvidenceProperties | ForEach-Object { $_.Value })
        $actualTranscriptCases = @($transcriptEvidenceProperties | ForEach-Object { [string]$_.Name } | Sort-Object)
        $transcriptCaseSetValid =
            $transcriptEvidence.Count -eq $expectedTranscriptCases.Count -and
            ($actualTranscriptCases -join "`n") -ceq (@($expectedTranscriptCases | Sort-Object) -join "`n") -and
            @($transcriptEvidenceProperties | Where-Object { [string]$_.Name -cne [string]$_.Value.caseName }).Count -eq 0
        $transcriptHashMismatch = @()
        $transcriptTotalBytes = [int64]0
        foreach ($evidence in $transcriptEvidence) {
            $transcriptBytes = $null
            $declaredTranscriptBytes = [int64]$evidence.transcriptBytes
            $encodedTranscript = [string]$evidence.transcriptBase64
            $expectedEncodedLength = if ($declaredTranscriptBytes -gt 0 -and $declaredTranscriptBytes -le 65536) {
                [int64](4 * [Math]::Ceiling($declaredTranscriptBytes / 3.0))
            } else { -1 }
            if ($expectedEncodedLength -lt 0 -or [int64]$encodedTranscript.Length -ne $expectedEncodedLength) {
                $transcriptHashMismatch += $evidence
                continue
            }
            try {
                $transcriptBytes = [Convert]::FromBase64String($encodedTranscript)
            } catch {
                $transcriptHashMismatch += $evidence
                continue
            }
            if (
                [int64]$transcriptBytes.Length -ne $declaredTranscriptBytes -or
                [Convert]::ToBase64String($transcriptBytes) -cne $encodedTranscript -or
                (Get-PiSurfaceBytesSha256 -Bytes $transcriptBytes) -cne [string]$evidence.transcriptSha256 -or
                $null -eq $evidence.isError
            ) { $transcriptHashMismatch += $evidence }
            $transcriptTotalBytes += [int64]$transcriptBytes.Length
        }
        $transcriptBinding = (@($transcriptEvidence | Sort-Object caseName | ForEach-Object {
            "$($_.caseName)`t$($_.transcriptBytes)`t$($_.transcriptSha256)"
        }) -join "`n")
        $securityFailures = @($policySecurity.checks.PSObject.Properties | Where-Object { $_.Value -ne $true })
        if (
            [string]$filesystemPolicyAcceptance.schema -cne 'xinao.pi_s_subagents_filesystem_policy_acceptance.v2' -or
            [string]$filesystemPolicyAcceptance.status -cne 'verified' -or
            [string]$policySecurity.schema -cne 'xinao.pi_subagents_filesystem_policy_security_acceptance.v1' -or
            $securityFailures.Count -ne 0 -or
            [string]$policyBody.schema -cne 'xinao.pi_subagents_filesystem_policy_body_lab.v1' -or
            [string]$policyBody.status -cne 'verified' -or
            $policyBody.foreground_safe_read -ne $true -or
            $policyBody.denied_read_blocked -ne $true -or
            $policyBody.junction_escape_blocked_without_sentinel -ne $true -or
            $policyBody.broad_grep_blocked -ne $true -or
            $policyBody.safe_sibling_grep -ne $true -or
            $policyBody.bash_processes_created -ne $false -or
            $policyBody.pre_context_sentinel_absent_from_child_provider -ne $true -or
            $policyBody.no_policy_bash_unchanged -ne $true -or
            $policyBody.no_policy_detached_resume_unchanged -ne $true -or
            $policyBody.resume_retained_policy -ne $true -or
            [int]$policyBody.resume_max_subagent_depth -ne 0 -or
            $policyBody.stale_repair_retained_markers -ne $true -or
            $policyBody.stale_result_only_resume_rejected -ne $true -or
            $policyBody.owner_stop_process_verified -ne $true -or
            $policyBody.owner_stop_process_terminated -ne $true -or
            $policyBody.owner_stop_commit_fence_rejected -ne $true -or
            $policyBody.allowed_source_tree_unchanged -ne $true -or
            $policyBody.project_artifacts_written -ne $false -or
            $filesystemPolicyAcceptance.wiring.start_patch_order -ne $true -or
            $filesystemPolicyAcceptance.wiring.start_prime_s_only -ne $true -or
            $filesystemPolicyAcceptance.wiring.start_disable_midturn_keeps_subagent_prerequisites -ne $true -or
            $filesystemPolicyAcceptance.wiring.install_patch_order -ne $true -or
            $filesystemPolicyAcceptance.wiring.install_prime_s_only -ne $true -or
            $filesystemPolicyAcceptance.wiring.body_lab_patch_order -ne $true -or
            $filesystemPolicyAcceptance.wiring.body_lab_prime_s_only -ne $true -or
            $filesystemPolicyAcceptance.wiring.dual_entry_prime_b_negative -ne $true -or
            $filesystemPolicyAcceptance.wiring.readme_one_home_and_path_policy_limit -ne $true -or
            $filesystemPolicyAcceptance.wiring.prime_b_active_module_absent -ne $true -or
            $filesystemPolicyAcceptance.wiring.prime_b_manifest_absent -ne $true -or
            $filesystemPolicyAcceptance.wiring.prime_b_source_overlay_absent -ne $true -or
            $policySourceHashMismatch.Count -ne 0 -or
            $packageSourceHashMismatch.Count -ne 0 -or
            $transcriptCaseSetValid -ne $true -or
            $transcriptEvidence.Count -ne 11 -or
            [int]$filesystemPolicyAcceptance.transcript_count -ne $transcriptEvidence.Count -or
            $transcriptHashMismatch.Count -ne 0 -or
            $transcriptTotalBytes -ne [int64]$filesystemPolicyAcceptance.transcript_total_bytes -or
            $transcriptTotalBytes -gt 1048576 -or
            [string]$policyBody.child_tool_transcript_binding_kind -cne 'case-bytes-sha256-v2' -or
            (Get-PiSurfaceTextSha256 -Text $transcriptBinding) -cne [string]$policyBody.child_tool_transcript_binding_sha256 -or
            $filesystemPolicyAcceptance.transcript_hashes_read_back_equal -ne $true -or
            $filesystemPolicyAcceptance.active_pi_subagents_source_unchanged -ne $true -or
            $filesystemPolicyAcceptance.prime_b_pi_subagents_source_unchanged -ne $true -or
            [string]$filesystemPolicyAcceptance.active_pi_subagents_source_before_sha256 -cne [string]$filesystemPolicyAcceptance.active_pi_subagents_source_after_sha256 -or
            [string]$filesystemPolicyAcceptance.prime_b_pi_subagents_source_before_sha256 -cne [string]$filesystemPolicyAcceptance.prime_b_pi_subagents_source_after_sha256 -or
            [string]$filesystemPolicyAcceptance.active_pi_subagents_source_after_sha256 -cne $currentActivePiSubagentsSourceSha256 -or
            [string]$filesystemPolicyAcceptance.prime_b_pi_subagents_source_after_sha256 -cne $currentPrimeBPiSubagentsSourceSha256
        ) { throw "PI_SURFACE_TEST_FILESYSTEM_POLICY_ACCEPTANCE_INVALID: $filesystemPolicyReceiptPath" }
        if (
            (Get-Item -LiteralPath $filesystemPolicyReceiptPath).Length -ne $filesystemPolicyReceiptBytes.Length -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $filesystemPolicyReceiptPath).Hash.ToLowerInvariant() -cne $filesystemPolicyReceiptSha256
        ) { throw 'PI_SURFACE_TEST_FILESYSTEM_POLICY_RECEIPT_CHANGED_DURING_VALIDATION' }
        $filesystemPolicyReceiptIdentity = [ordered]@{
            path = $filesystemPolicyReceiptPath
            bytes = [int64]$filesystemPolicyReceiptBytes.Length
            sha256 = $filesystemPolicyReceiptSha256
            schema = [string]$filesystemPolicyAcceptance.schema
            status = [string]$filesystemPolicyAcceptance.status
            generated_at = [string]$filesystemPolicyAcceptance.generated_at
            transcript_count = [int]$filesystemPolicyAcceptance.transcript_count
            transcript_total_bytes = [int64]$filesystemPolicyAcceptance.transcript_total_bytes
            transcript_binding = [ordered]@{
                kind = [string]$policyBody.child_tool_transcript_binding_kind
                sha256 = [string]$policyBody.child_tool_transcript_binding_sha256
            }
            source_bound_embedded_transcripts = $true
            source_paths_required_for_readback = $false
            active_pi_subagents_source_sha256 = [string]$filesystemPolicyAcceptance.active_pi_subagents_source_after_sha256
            prime_b_pi_subagents_source_sha256 = [string]$filesystemPolicyAcceptance.prime_b_pi_subagents_source_after_sha256
            security_schema = [string]$policySecurity.schema
            body_schema = [string]$policyBody.schema
        }
        $ownerStopProcessReceiptPath = $filesystemPolicyReceiptPath
        $ownerSessionStopProcessAcceptance = $policyBody.owner_stop_process_receipt
        $ownerStopProcessSourceHashes = [ordered]@{
            rpc = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $subagentsPackageRoot 'src\extension\rpc.ts')).Hash.ToLowerInvariant()
            executor = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $subagentsPackageRoot 'src\runs\foreground\subagent-executor.ts')).Hash.ToLowerInvariant()
            process_guard = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $subagentsPackageRoot 'src\shared\post-exit-stdio-guard.ts')).Hash.ToLowerInvariant()
            runner = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $subagentsPackageRoot 'src\runs\background\subagent-runner.ts')).Hash.ToLowerInvariant()
            test_extension = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PSScriptRoot 'fixtures\pi-owner-stop-autolaunch.ts')).Hash.ToLowerInvariant()
            fixture = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PSScriptRoot 'fixtures\pi-owner-stop-child.mjs')).Hash.ToLowerInvariant()
            harness = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PSScriptRoot 'Test-PiSubagentSessionStopProcess.mjs')).Hash.ToLowerInvariant()
        }
        $ownerStopProcessHashMismatch = @($ownerStopProcessSourceHashes.GetEnumerator() | Where-Object {
            [string]$ownerSessionStopProcessAcceptance.source_sha256.($_.Key) -cne [string]$_.Value
        })
        if (
            [string]$ownerSessionStopProcessAcceptance.schema -ne 'xinao.pi_subagent_owner_session_stop_process_acceptance.v2' -or
            [string]$ownerSessionStopProcessAcceptance.status -ne 'verified' -or
            $ownerSessionStopProcessAcceptance.real_detached_process_started -ne $true -or
            $ownerSessionStopProcessAcceptance.real_detached_process_terminated -ne $true -or
            $ownerSessionStopProcessAcceptance.process_terminal_observed -ne $true -or
            $ownerSessionStopProcessAcceptance.status_stopped -ne $true -or
            $ownerSessionStopProcessAcceptance.launch_commit_fence_rejected_race -ne $true -or
            $ownerStopProcessHashMismatch.Count -ne 0
        ) { throw "PI_SURFACE_TEST_OWNER_SESSION_STOP_PROCESS_INVALID: $ownerStopProcessReceiptPath" }
        $supervisorRaw = @(& node (Join-Path $PSScriptRoot 'Test-PiSupervisorIngress.mjs') 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_SUPERVISOR_INGRESS_FAILED: $($supervisorRaw -join ' ')" }
        $supervisorIngressAcceptance = ($supervisorRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if (
            [string]$supervisorIngressAcceptance.status -ne 'verified' -or
            $supervisorIngressAcceptance.stop_fences_and_settles_owner_session_children -ne $true -or
            $supervisorIngressAcceptance.stop_reasserts_abort_on_agent_restart -ne $true -or
            $supervisorIngressAcceptance.stop_cleanup_failure_still_schedules_shutdown -ne $true -or
            $supervisorIngressAcceptance.duplicate_stop_is_idempotent -ne $true -or
            $supervisorIngressAcceptance.child_stop_timeout_precedes_default_client_timeout -ne $true -or
            $supervisorIngressAcceptance.stop_request_not_misreported_as_process_exit -ne $true
        ) { throw "PI_SURFACE_TEST_SUPERVISOR_INGRESS_INVALID: $($supervisorRaw -join ' ')" }
        $post0841Raw = @(& (Join-Path $PSScriptRoot 'Apply-PiSPost0841UpstreamCompatibility.ps1') -PiToolRoot $spec.PiToolRoot -VerifyOnly 2>&1)
        $post0841UpstreamAcceptance = ($post0841Raw -join [Environment]::NewLine) | ConvertFrom-Json
        if (
            [string]$post0841UpstreamAcceptance.schema -ne 'xinao.pi_post_0841_upstream_compatibility.v1' -or
            $post0841UpstreamAcceptance.deepseek_builtin_and_custom_send_max_tokens -ne $true -or
            $post0841UpstreamAcceptance.fullscreen_visible_output_preserved -ne $true -or
            $post0841UpstreamAcceptance.shared_cold_backup_core_allowed -ne $false
        ) { throw "PI_SURFACE_TEST_POST0841_PATCH_STATUS_INVALID: $($post0841Raw -join ' ')" }
        $post0841BehaviorRaw = @(& node (Join-Path $PSScriptRoot 'Test-PiSPost0841UpstreamCompatibility.mjs') --pi-root $spec.PiToolRoot 2>&1)
        if ($LASTEXITCODE -ne 0 -or ($post0841BehaviorRaw -join [Environment]::NewLine) -notmatch 'PIS_POST_0841_UPSTREAM_COMPATIBILITY_V1') {
            throw "PI_SURFACE_TEST_POST0841_BEHAVIOR_FAILED: $($post0841BehaviorRaw -join ' ')"
        }
    }
    $activityRaw = @(& node (Join-Path $PSScriptRoot 'Test-PiSActivityVisibility.mjs') $piPackageRoot 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_ACTIVITY_VISIBILITY_FAILED: $($activityRaw -join ' ')" }
    $activityVisibilityAcceptance = ($activityRaw -join [Environment]::NewLine) | ConvertFrom-Json
    if (
        [string]$activityVisibilityAcceptance.status -ne 'verified' -or
        $activityVisibilityAcceptance.natural_chinese_activity -ne $true -or
        $activityVisibilityAcceptance.native_working_visibility_unchanged -ne $true -or
        $activityVisibilityAcceptance.native_working_indicator_unchanged -ne $true -or
        $activityVisibilityAcceptance.native_tool_cards_unmodified -ne $true -or
        [int]$activityVisibilityAcceptance.secondary_model_calls -ne 0
    ) {
        throw "PI_SURFACE_TEST_ACTIVITY_VISIBILITY_INVALID: $($activityRaw -join ' ')"
    }
    $returnToParentAcceptance = $null
    $returnToParentLiveAcceptance = $null
    if ($profileName -eq 'prime-s') {
        $returnToParentRaw = @(& node (Join-Path $PSScriptRoot 'Test-PiSReturnToParent.mjs') $piPackageRoot 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_RETURN_TO_PARENT_FAILED: $($returnToParentRaw -join ' ')" }
        $returnToParentAcceptance = ($returnToParentRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if (
            [string]$returnToParentAcceptance.schema -cne 'xinao.pi_return_to_parent.acceptance.v5' -or
            [string]$returnToParentAcceptance.status -ne 'mechanically_verified' -or
            [string]$returnToParentAcceptance.live_transport_status -ne 'pending_live_consumer' -or
            $returnToParentAcceptance.root_only_registration -ne $true -or
            $returnToParentAcceptance.abort_fence_runtime_handshake_required -ne $true -or
            $returnToParentAcceptance.missing_handshake_inert -ne $true -or
            $returnToParentAcceptance.normalized_empty_rejected -ne $true -or
            $returnToParentAcceptance.same_run_continuation_after_local_boundary -ne $true -or
            $returnToParentAcceptance.unarmed_run_does_not_follow_up -ne $true -or
            $returnToParentAcceptance.pre_execute_abort_rejected -ne $true -or
            $returnToParentAcceptance.turn_boundary_abort_prevents_next_provider -ne $true -or
            [int]$returnToParentAcceptance.queued_user_messages -ne 0 -or
            $returnToParentAcceptance.one_shot_follow_up_armed -ne $true -or
            $returnToParentAcceptance.native_one_shot_follow_up -ne $true -or
            $returnToParentAcceptance.activity_context_ref_bound -ne $true -or
            $returnToParentAcceptance.returned_fact_bound -ne $true -or
            $returnToParentAcceptance.repeated_calls_single_follow_up -ne $true -or
            $returnToParentAcceptance.abort_error_stop_shutdown_suppress_follow_up -ne $true -or
            $returnToParentAcceptance.strict_clean_stop_reason_allowlist -ne $true -or
            [int]$returnToParentAcceptance.post_enqueue_stop_provider_delta -ne 0 -or
            $returnToParentAcceptance.tui_and_print_abort_paths_fenced -ne $true -or
            $returnToParentAcceptance.agent_start_abort_fence -ne $true -or
            $returnToParentAcceptance.pre_provider_abort_fence -ne $true -or
            $returnToParentAcceptance.async_auth_abort_fence -ne $true -or
            $returnToParentAcceptance.continuation_run_signal_lifecycle_bound -ne $true -or
            $returnToParentAcceptance.tagged_context_same_continuation_run_all_providers -ne $true -or
            $returnToParentAcceptance.tagged_context_single_current_arm_per_provider -ne $true -or
            $returnToParentAcceptance.tagged_context_future_prompt_zero -ne $true -or
            $returnToParentAcceptance.tagged_context_resume_zero -ne $true -or
            $returnToParentAcceptance.arm_id_prevents_resume_sequence_collision -ne $true -or
            $returnToParentAcceptance.ordinary_follow_up_preserved -ne $true -or
            [int]$returnToParentAcceptance.stop_during_continuation_provider_delta -ne 0 -or
            $returnToParentAcceptance.live_parser_normalized_argument_binding -ne $true -or
            $returnToParentAcceptance.live_parser_matching_tool_result_unique -ne $true -or
            $returnToParentAcceptance.live_parser_matching_arm_first_and_unique -ne $true -or
            $returnToParentAcceptance.live_parser_ambiguity_rejected -ne $true -or
            $returnToParentAcceptance.no_residual_continuation_queue -ne $true -or
            [int]$returnToParentAcceptance.provider_calls_armed -ne 2 -or
            [int]$returnToParentAcceptance.provider_calls_unarmed -ne 1 -or
            [int]$returnToParentAcceptance.provider_calls_native_continuation -ne 3 -or
            [int]$returnToParentAcceptance.provider_calls_multi_provider_continuation -ne 5
        ) { throw "PI_SURFACE_TEST_RETURN_TO_PARENT_INVALID: $($returnToParentRaw -join ' ')" }
        if ($RequireLiveReturnAcceptance) {
            $returnToParentLiveRaw = @(& node (Join-Path $PSScriptRoot 'Test-PiSReturnToParentLive.mjs') $spec.SessionDir 2>&1)
            if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_RETURN_TO_PARENT_LIVE_FAILED: $($returnToParentLiveRaw -join ' ')" }
            $returnToParentLiveAcceptance = ($returnToParentLiveRaw -join [Environment]::NewLine) | ConvertFrom-Json
            if (
                [string]$returnToParentLiveAcceptance.schema -cne 'xinao.pi_return_to_parent_live_transport_acceptance.v5' -or
                [string]$returnToParentLiveAcceptance.status -ne 'live_sol_native_continuation_abort_fenced_verified' -or
                [string]$returnToParentLiveAcceptance.maturity -ne 'not_yet_mature' -or
                [string]$returnToParentLiveAcceptance.provider -ne 'openai-codex' -or
                [string]$returnToParentLiveAcceptance.model -ne 'gpt-5.6-sol' -or
                $returnToParentLiveAcceptance.actual_provider_tool_call -ne $true -or
                $returnToParentLiveAcceptance.normalized_argument_binding -ne $true -or
                $returnToParentLiveAcceptance.matching_tool_result_unique -ne $true -or
                $returnToParentLiveAcceptance.matching_arm_first_and_unique -ne $true -or
                $returnToParentLiveAcceptance.activity_context_ref_bound -ne $true -or
                $returnToParentLiveAcceptance.returned_fact_bound -ne $true -or
                $returnToParentLiveAcceptance.tool_result_consumed_before_first_run_final -ne $true -or
                $returnToParentLiveAcceptance.first_run_reached_terminal_assistant_before_native_follow_up -ne $true -or
                $returnToParentLiveAcceptance.native_custom_follow_up_triggered_second_provider -ne $true -or
                $returnToParentLiveAcceptance.one_shot -ne $true -or
                [string]::IsNullOrWhiteSpace([string]$returnToParentLiveAcceptance.arm_id) -or
                $returnToParentLiveAcceptance.abort_fenced -ne $true -or
                [string]$returnToParentLiveAcceptance.provider_context_visibility -cne 'single_current_arm'
            ) { throw "PI_SURFACE_TEST_RETURN_TO_PARENT_LIVE_INVALID: $($returnToParentLiveRaw -join ' ')" }
        }
        $numpadRaw = @(& (Join-Path $PSScriptRoot 'Set-PiSNumpadEnterFollow.ps1') -AgentDir $spec.AgentDir -ValidateOnly 2>&1)
        $numpadStatus = ($numpadRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if ([string]$numpadStatus.status -ne 'ready' -or $numpadStatus.main_enter_unchanged -ne $true -or $numpadStatus.helper_failure_blocks_pi -ne $false) {
            throw "PI_SURFACE_TEST_NUMPAD_STATUS_INVALID: $($numpadRaw -join ' ')"
        }
        $numpadProbeRaw = @(& node (Join-Path $PSScriptRoot 'Test-PiSNumpadEnterFollow.mjs') $spec.AgentDir $piPackageRoot 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_NUMPAD_KEYBINDINGS_FAILED: $($numpadProbeRaw -join ' ')" }
        $numpadAcceptance = ($numpadProbeRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if ([string]$numpadAcceptance.status -ne 'verified') {
            throw "PI_SURFACE_TEST_NUMPAD_KEYBINDINGS_NOT_VERIFIED: $($numpadProbeRaw -join ' ')"
        }
    }

    $liveProbe = $null
    if ($RunLiveModelProbe) {
        $probePrompt = @"
Without using tools, report instructions already present in your current context. Return exactly one minified JSON object and nothing else with these keys and values: global_sentinel="HUMAN_WORDS_BEFORE_ARTIFACTS_V2"; family_sentinel="PI_LOCAL_COMPATIBILITY_BOUNDARY_V3"; surface_sentinel="$($spec.SurfaceSentinel)"; current_surface="$profileName"; runtime_version="$($script:PiDualEntryVersion)"; local_contract_does_not_define_pi=true; official_live_capability_precedes_overlay=true; main_prime_default_handle=true; prime_s_internal_profile=true; account_binding_not_identity=true; prime_b_isolated=true; owner_scope_not_product=true; repository_context_is_local=true; supervisor_mode_is_codex_side_candidate=true.
"@.Trim()
        Push-Location -LiteralPath $spec.Workspace
        try {
            $probeRaw = @(& $spec.PiCommand --print --no-session --no-tools --provider openai-codex --model gpt-5.6-sol --thinking max --append-system-prompt $spec.ContractProjection $probePrompt 2>&1)
            if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_LIVE_MODEL_FAILED: profile=$profileName output=$($probeRaw -join ' ')" }
        } finally {
            Pop-Location
        }
        $probeText = ($probeRaw -join [Environment]::NewLine).Trim()
        try { $probe = $probeText | ConvertFrom-Json } catch { throw "PI_SURFACE_TEST_LIVE_MODEL_JSON_INVALID: profile=$profileName text=$probeText" }
        if (
            [string]$probe.global_sentinel -ne 'HUMAN_WORDS_BEFORE_ARTIFACTS_V2' -or
            [string]$probe.family_sentinel -ne 'PI_LOCAL_COMPATIBILITY_BOUNDARY_V3' -or
            [string]$probe.surface_sentinel -ne $spec.SurfaceSentinel -or
            [string]$probe.current_surface -ne $profileName -or
            [string]$probe.runtime_version -ne $script:PiDualEntryVersion -or
            $probe.local_contract_does_not_define_pi -ne $true -or
            $probe.official_live_capability_precedes_overlay -ne $true -or
            $probe.main_prime_default_handle -ne $true -or
            $probe.prime_s_internal_profile -ne $true -or
            $probe.account_binding_not_identity -ne $true -or
            $probe.pi_b_isolated -ne $true -or
            $probe.owner_scope_not_product -ne $true -or
            $probe.repository_context_is_local -ne $true -or
            $probe.supervisor_mode_is_codex_side_candidate -ne $true
        ) { throw "PI_SURFACE_TEST_LIVE_MODEL_BEHAVIOR_MISMATCH: profile=$profileName text=$probeText" }
        $liveProbe = $probe
    }

    $surfaceResults += [ordered]@{
        name = $profileName
        role = $spec.Role
        pi_tool_root = $spec.PiToolRoot
        runtime_version = $script:PiDualEntryVersion
        account_slot = $spec.AccountSlot
        account_binding_path = $spec.AccountBindingPath
        auth_ready = $authReady
        auth_type = [string]$authResult.authType
        agent_dir = $spec.AgentDir
        session_dir = $spec.SessionDir
        starting_workspace = $spec.Workspace
        surface_island = $spec.SurfaceIsland
        agents_source = $spec.AgentsSource
        agents_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $agentsPath).Hash.ToLowerInvariant()
        contract_projection_sha256 = $projection.Sha256
        family_contract_sha256 = $projection.FamilySha256
        surface_contract_sha256 = $projection.SurfaceSha256
        skill_count = @($names | Where-Object { $_ -like 'skill:*' }).Count
        codex_skills_injected = $false
        packages = $actualPackages
        hermes_memory_capacity = $hermesMemoryCapacity
        subagent_capacity = $subagentCapacity
        subagent_capacity_static_policy = $subagentCapacityStaticPolicy
        recursive_peer = $recursivePeerAcceptance
        subagent_config_path = $subagentConfigPath
        subagent_artifact_dir = [string]$subagentConfig.artifactDir
        scheduled_runs_enabled = [bool]$subagentConfig.scheduledRuns.enabled
        missions_enabled = [bool]$subagentConfig.missions.enabled
        provider_catalog_context_window = $catalogContextWindow
        profile_context_window_override_absent = $profileContextWindowOverrideAbsent
        midturn_compaction_compatibility = $midTurnCompactionAcceptance
        native_continuation_compatibility = $nativeContinuationCompatibility
        native_continuation_absence = $nativeContinuationAbsence
        subagents_owner_session_stop_compatibility = $ownerSessionStopCompatibility
        subagents_owner_session_stop = $ownerSessionStopAcceptance
        subagents_owner_session_stop_process = $ownerSessionStopProcessAcceptance
        subagents_filesystem_policy_compatibility = $filesystemPolicyCompatibility
        subagents_filesystem_policy = $filesystemPolicyReceiptIdentity
        high_capacity_compatibility = $highCapacityCompatibility
        high_capacity_active_projection = $highCapacityActiveProjectionReceiptIdentity
        high_capacity_replay = $highCapacityReplayReceiptIdentity
        high_capacity_absence = $highCapacityAbsence
        supervisor_ingress = $supervisorIngressAcceptance
        post_0841_upstream_compatibility = $post0841UpstreamAcceptance
        numpad_enter_follow = $numpadAcceptance
        activity_visibility = $activityVisibilityAcceptance
        return_to_parent = $returnToParentAcceptance
        return_to_parent_live = $returnToParentLiveAcceptance
        peer_cognition = $peerAgentAcceptance
        overlay_projection_sha256 = $overlayProjection.Sha256
        live_model_probe = $liveProbe
    }

    $bashTool = Join-Path $spec.PiToolRoot 'node_modules\@earendil-works\pi-coding-agent\dist\core\tools\bash.js'
    $nativeWindowsHide = Select-String -LiteralPath $bashTool -Pattern 'windowsHide: true' -SimpleMatch -Quiet
    if (-not $nativeWindowsHide) {
        $allNativeWindowsHide = $false
        throw "PI_SURFACE_TEST_NATIVE_WINDOWS_HIDE_MISSING: profile=$profileName path=$bashTool"
    }
}

$primeBSpecForNegative = Get-PiDualEntrySpec -Profile 'prime-b'
$primeBHermesConfigPath = Join-Path $primeBSpecForNegative.AgentDir 'hermes-memory-config.json'
if (-not (Test-Path -LiteralPath $primeBHermesConfigPath -PathType Leaf)) {
    throw "PI_SURFACE_TEST_COLD_BACKUP_HERMES_CONFIG_MISSING: $primeBHermesConfigPath"
}
$primeBHermesConfig = Get-Content -Raw -LiteralPath $primeBHermesConfigPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$primeBHermesConfig.memoryOverflowStrategy -cne 'reject' -or $primeBHermesConfig.failureInjectionEnabled -ne $false) {
    throw 'PI_SURFACE_TEST_COLD_BACKUP_HERMES_MEMORY_POLICY_INVALID'
}
$primeBExplicitHermesLimits = @(@('memoryCharLimit','userCharLimit','projectCharLimit') | Where-Object {
    $null -ne $primeBHermesConfig.PSObject.Properties[$_]
})
if ($primeBExplicitHermesLimits.Count -ne 0) {
    throw "PI_SURFACE_TEST_COLD_BACKUP_INHERITED_HERMES_MEMORY_CAPACITY: $($primeBExplicitHermesLimits -join ',')"
}
$primeBManifestOwned = @()
if (Test-Path -LiteralPath $primeBSpecForNegative.OverlayProjectionManifest -PathType Leaf) {
    $primeBManifestOwned = @((Get-Content -Raw -LiteralPath $primeBSpecForNegative.OverlayProjectionManifest -Encoding UTF8 | ConvertFrom-Json).owned_files | ForEach-Object { [string]$_ })
}
if (
    (Test-Path -LiteralPath (Join-Path $primeBSpecForNegative.AgentDir 'agents\peer.md') -PathType Leaf) -or
    (Test-Path -LiteralPath (Join-Path $primeBSpecForNegative.AgentDir 'agents\recursive-peer.md') -PathType Leaf) -or
    (Test-Path -LiteralPath (Join-Path $primeBSpecForNegative.AgentDir 'extensions\return-to-parent.ts') -PathType Leaf) -or
    'agents/peer.md' -in $primeBManifestOwned -or
    'agents/recursive-peer.md' -in $primeBManifestOwned -or
    'extensions/return-to-parent.ts' -in $primeBManifestOwned
) { throw 'PI_SURFACE_TEST_COLD_BACKUP_INHERITED_MAIN_ONLY_CAPABILITY' }
$primeBCapacityStaticPolicy = Get-PiSubagentCapacityStaticPolicy -Profile 'prime-b'
$primeBCapacityPackageRuntime = Join-Path $primeBSpecForNegative.AgentDir 'npm\node_modules\pi-subagents\src\runs\shared\xinao-pi-subagent-capacity-runtime.js'
$primeBCapacityCoreRoot = Join-Path $primeBSpecForNegative.PiToolRoot 'node_modules\@earendil-works\pi-coding-agent\dist\core'
$primeBCapacityCoreRuntime = Join-Path $primeBCapacityCoreRoot 'xinao-pi-subagent-capacity-runtime.js'
$primeBCapacityCoreSdk = Join-Path $primeBCapacityCoreRoot 'sdk.js'
if (
    $primeBCapacityStaticPolicy.enabled -or
    (Test-Path -LiteralPath $primeBCapacityPackageRuntime) -or
    (Test-Path -LiteralPath $primeBCapacityCoreRuntime) -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $primeBCapacityCoreSdk).Hash.ToLowerInvariant() -cne 'f6e72f33f44c708249c8d74931d816c36fe27175f7fa1639cba0a3d988592821'
) { throw 'PI_SURFACE_TEST_COLD_BACKUP_INHERITED_HIGH_CAPACITY' }
$primeBPolicyModule = Join-Path $primeBSpecForNegative.AgentDir 'npm\node_modules\pi-subagents\src\runs\shared\filesystem-policy.ts'
$primeBManifestText = if (Test-Path -LiteralPath $primeBSpecForNegative.OverlayProjectionManifest -PathType Leaf) {
    Get-Content -Raw -LiteralPath $primeBSpecForNegative.OverlayProjectionManifest -Encoding UTF8
} else { '' }
$primeBOverlayPolicyMatches = @()
if (Test-Path -LiteralPath $primeBSpecForNegative.OverlayRoot -PathType Container) {
    $primeBOverlayPolicyMatches = @(Get-ChildItem -LiteralPath $primeBSpecForNegative.OverlayRoot -File -Recurse | Where-Object {
        $_.FullName -match 'filesystem[-_]?policy' -or
        (Select-String -LiteralPath $_.FullName -Pattern 'filesystemPolicy','filesystem-policy' -SimpleMatch -Quiet)
    })
}
if (
    (Test-Path -LiteralPath $primeBPolicyModule -PathType Leaf) -or
    $primeBManifestText -match 'filesystemPolicy|filesystem-policy' -or
    $primeBOverlayPolicyMatches.Count -ne 0
) {
    throw 'PI_SURFACE_TEST_COLD_BACKUP_INHERITED_FILESYSTEM_POLICY'
}

if ($Profile.Count -eq 2) {
    $b = $surfaceResults | Where-Object name -eq 'prime-b'
    $s = $surfaceResults | Where-Object name -eq 'prime-s'
    if ($b.account_binding_path -eq $s.account_binding_path -or $b.session_dir -eq $s.session_dir -or $b.surface_island -eq $s.surface_island) {
        throw 'PI_SURFACE_TEST_ISOLATION_COLLAPSED'
    }
    if ($b.account_slot -ne 'account-b' -or $s.account_slot -notin @('main','account-b')) {
        throw "PI_SURFACE_TEST_CURRENT_BINDING_UNEXPECTED: prime-b=$($b.account_slot) prime-s=$($s.account_slot)"
    }
}

$node = Get-PiDualEntryNodeInfo
$primeBWrapper = 'C:\Users\xx363\CodexLaunchers\Open-Prime-Agent-Account-B.ps1'
$primeSWrapper = 'C:\Users\xx363\CodexLaunchers\Open-Prime.ps1'
$primeSVisibleRestart = Join-Path $PSScriptRoot 'Start-PrimeSInWindowsTerminal.ps1'
$wrapperBText = Get-Content -Raw -LiteralPath $primeBWrapper -Encoding UTF8
$wrapperSText = Get-Content -Raw -LiteralPath $primeSWrapper -Encoding UTF8
if ($wrapperBText -notmatch 'Start-UpstreamPi\.ps1' -or $wrapperBText -notmatch 'Profile prime-b') { throw 'PI_SURFACE_TEST_PRIME_B_WRAPPER_STALE' }
if ($wrapperSText -notmatch 'Start-UpstreamPi\.ps1' -or $wrapperSText -notmatch 'Profile prime-s') { throw 'PI_SURFACE_TEST_PRIME_S_WRAPPER_STALE' }
if (-not (Test-Path -LiteralPath $primeSVisibleRestart -PathType Leaf)) { throw 'PI_SURFACE_TEST_VISIBLE_RESTART_MISSING' }
$visibleRestartText = Get-Content -Raw -LiteralPath $primeSVisibleRestart -Encoding UTF8
foreach ($requiredRestartMarker in @("`$terminalProfileName = 'prime'",'Open-Prime.ps1','-Session','PIS_VISIBLE_RESTART_SESSION_NOT_LATEST_FOR_PROFILE','profile-native-continue-after-latest-session-proof','ingress_readback_required')) {
    if ($visibleRestartText -notmatch [regex]::Escape($requiredRestartMarker)) {
        throw "PI_SURFACE_TEST_VISIBLE_RESTART_MARKER_MISSING: $requiredRestartMarker"
    }
}
$terminalSettingsPath = 'C:\Users\xx363\AppData\Local\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json'
$terminalSettings = Get-Content -Raw -LiteralPath $terminalSettingsPath -Encoding UTF8 | ConvertFrom-Json
$primeSProfile = @($terminalSettings.profiles.list | Where-Object { [string]$_.name -eq 'prime' })
if (
    $primeSProfile.Count -ne 1 -or
    [string]$primeSProfile[0].commandline -notmatch 'Open-Prime\.ps1' -or
    [string]$primeSProfile[0].tabTitle -ne 'prime' -or
    $primeSProfile[0].suppressApplicationTitle -ne $true -or
    [string]$primeSProfile[0].closeOnExit -ne 'always'
) {
    throw 'PI_SURFACE_TEST_PRIME_S_TERMINAL_PROFILE_STALE'
}
$shortcutPath = 'C:\Users\xx363\Desktop\prime.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ([string]$shortcut.Arguments -ne '-w new -p "prime"') { throw 'PI_SURFACE_TEST_PRIME_S_SHORTCUT_STALE' }
$latestPrimeSSession = Get-ChildItem -LiteralPath (Join-Path $profileRoot 'prime-s\sessions') -File -Filter '*.jsonl' | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if ($null -eq $latestPrimeSSession) { throw 'PI_SURFACE_TEST_VISIBLE_RESTART_SESSION_MISSING' }
$latestPrimeSSessionHeader = Get-Content -LiteralPath $latestPrimeSSession.FullName -TotalCount 1 -Encoding UTF8 | ConvertFrom-Json
$visibleRestartValidationRaw = @(& $primeSVisibleRestart -Session ([string]$latestPrimeSSessionHeader.id) -ValidateOnly 2>&1)
if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_VISIBLE_RESTART_VALIDATION_FAILED: $($visibleRestartValidationRaw -join ' ')" }
$visibleRestartValidation = ($visibleRestartValidationRaw -join [Environment]::NewLine) | ConvertFrom-Json
if (
    [string]$visibleRestartValidation.status -ne 'ready' -or
    [string]$visibleRestartValidation.terminal_profile -ne 'prime' -or
    [string]$visibleRestartValidation.session_id -ne [string]$latestPrimeSSessionHeader.id -or
    $visibleRestartValidation.same_profile_session_required -ne $true -or
    $visibleRestartValidation.ingress_readback_required -ne $true
) { throw 'PI_SURFACE_TEST_VISIBLE_RESTART_VALIDATION_INVALID' }

$acceptance = [ordered]@{
    schema = 'xinao.pi_main_with_cold_snapshot.acceptance.v4'
    status = 'verified'
    upstream_pi_version = $script:PiDualEntryVersion
    node_version = $node.RawVersion
    node_path = $node.Path
    node_minimum = [string]$node.Minimum
    node_minimum_satisfied = $node.MinimumSatisfied
    surfaces = $surfaceResults
    family_contract = $script:PiDualEntryFamilyContract
    profile_instruction_sources = @($surfaceResults | ForEach-Object { $_.agents_source })
    codex_skill_tree_injected = $false
    native_background_child_windows_hidden = $allNativeWindowsHide
    prime_b_memory_capacity_explicit_limits_absent = $true
    task_topology = 'prime is the one default active subject; prime-s is only its internal compatibility profile and account binding is a quota source.'
    evolution_topology = 'PiB is a one-time isolated full-body cold snapshot; after fresh verification it is not routinely maintained, tested, reported, mentioned, or synchronized.'
    legacy_prime_0_7_0 = [ordered]@{
        active = $false
        installation_preserved_for_rollback = (Test-Path -LiteralPath 'D:\XINAO_RESEARCH_RUNTIME\tools\prime-agent\0.7.0' -PathType Container)
        contract_snapshot = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island\contracts\evidence\prime-agent-0.7.0-pre-upgrade-20260808'
    }
    desktop_wrappers = @($primeBWrapper,$primeSWrapper)
    prime_s_terminal_profile = 'prime'
    prime_s_shortcut = $shortcutPath
    prime_s_visible_restart = $visibleRestartValidation
}
if (-not [string]::IsNullOrWhiteSpace($ReceiptPath)) {
    Write-PiDualEntryJsonAtomic -Path $ReceiptPath -Value $acceptance
}
$acceptance | ConvertTo-Json -Depth 10
