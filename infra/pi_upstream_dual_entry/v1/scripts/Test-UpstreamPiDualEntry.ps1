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
        $expectedOverlayOwned += @(Get-ChildItem -LiteralPath $overlayKind.Root -Recurse -File | ForEach-Object {
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
    foreach ($sentinel in @('PI_LOCAL_COGNITION_CONTRACT_ISLAND_V1',$spec.SurfaceSentinel)) {
        if ($contractText -notmatch [regex]::Escape($sentinel)) {
            throw "PI_SURFACE_TEST_CONTRACT_SENTINEL_MISSING: profile=$profileName sentinel=$sentinel"
        }
    }

    $settings = Get-Content -Raw -LiteralPath $settingsPath -Encoding UTF8 | ConvertFrom-Json
    $subagentConfig = Get-Content -Raw -LiteralPath $subagentConfigPath -Encoding UTF8 | ConvertFrom-Json
    $hermesConfig = Get-Content -Raw -LiteralPath $hermesConfigPath -Encoding UTF8 | ConvertFrom-Json
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
    if (
        [string]$subagentConfig.artifactDir -ne 'session' -or
        $subagentConfig.scheduledRuns.enabled -ne $false -or
        $subagentConfig.missions.enabled -ne $false -or
        [int]$subagentConfig.maxSubagentDepth -ne 2 -or
        [int]$subagentConfig.globalConcurrencyLimit -ne 4
    ) { throw "PI_SURFACE_TEST_SUBAGENT_RUNTIME_CONFIG_INVALID: profile=$profileName" }
    $expectedPackages = @($spec.Packages)
    $actualPackages = @($settings.packages)
    if (@($expectedPackages | Where-Object { $_ -notin $actualPackages }).Count -gt 0 -or @($actualPackages | Where-Object { $_ -notin $expectedPackages }).Count -gt 0) {
        throw "PI_SURFACE_TEST_PACKAGE_SET_MISMATCH: profile=$profileName actual=$($actualPackages -join ',')"
    }
    $expectedAgentNames = @('probe','operator','verifier','fanout')
    if (Test-Path -LiteralPath $spec.OverlayAgentDir -PathType Container) {
        $expectedAgentNames += @(Get-ChildItem -LiteralPath $spec.OverlayAgentDir -File -Filter '*.md' | ForEach-Object { $_.BaseName })
    }
    foreach ($agentName in $expectedAgentNames) {
        if (-not (Test-Path -LiteralPath (Join-Path $spec.AgentDir "agents\$agentName.md") -PathType Leaf)) {
            throw "PI_SURFACE_TEST_AGENT_MISSING: profile=$profileName agent=$agentName"
        }
    }
    $peerAgentAcceptance = $null
    if ($profileName -eq 'prime-s') {
        $peerAgentPath = Join-Path $spec.AgentDir 'agents\peer.md'
        if (-not (Test-Path -LiteralPath $peerAgentPath -PathType Leaf)) {
            throw "PI_SURFACE_TEST_PEER_AGENT_MISSING: $peerAgentPath"
        }
        $peerAgentText = Get-Content -Raw -LiteralPath $peerAgentPath -Encoding UTF8
        $peerAgentNormalized = ($peerAgentText -replace '\s+', ' ').Trim()
        $peerRequiredFragments = @(
            'name: peer',
            'model: openai-codex/gpt-5.6-terra',
            'acceptanceRole: read-only',
            'maxSubagentDepth: 0',
            'without a fixed profession or preselected local question',
            'A local no-action or route closure does not settle the whole inherited parent',
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
            local_no_action_closes_parent = $false
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
    $requiredSkills = @(
        'skill:productivity',
        'skill:repair-agent-behavior',
        'skill:operate-for-user',
        'skill:research-external-reality',
        'skill:dispatch-grok-worker-pool'
    )
    $missingSkills = @($requiredSkills | Where-Object { $_ -notin $names })
    if ($missingSkills.Count -gt 0) {
        throw "PI_SURFACE_TEST_REQUIRED_SKILLS_MISSING: profile=$profileName skills=$($missingSkills -join ',')"
    }

    $numpadAcceptance = $null
    $activityVisibilityAcceptance = $null
    $midTurnCompactionAcceptance = $null
    $ownerSessionStopCompatibility = $null
    $ownerSessionStopAcceptance = $null
    $ownerSessionStopProcessAcceptance = $null
    $filesystemPolicyCompatibility = $null
    $filesystemPolicyAcceptance = $null
    $supervisorIngressAcceptance = $null
    $nativeContinuationCompatibility = $null
    $nativeContinuationAbsence = $null
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
        $filesystemPolicyAcceptance = Get-Content -Raw -LiteralPath $filesystemPolicyReceiptPath -Encoding UTF8 | ConvertFrom-Json
        $policyBody = $filesystemPolicyAcceptance.body_lab
        $policySecurity = $filesystemPolicyAcceptance.security
        $currentActivePiSubagentsSourceSha256 = Get-PiSubagentsSourceAggregateSha256 -AgentDir $spec.AgentDir
        $primeBSpecForFilesystemReceipt = Get-PiDualEntrySpec -Profile 'prime-b'
        $currentPrimeBPiSubagentsSourceSha256 = Get-PiSubagentsSourceAggregateSha256 -AgentDir $primeBSpecForFilesystemReceipt.AgentDir
        $policySourceFiles = [ordered]@{
            acceptance_wrapper = Join-Path $PSScriptRoot 'Test-PiSFilesystemPolicyAcceptance.ps1'
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
        $transcriptEvidence = @($policyBody.child_tool_result_evidence.PSObject.Properties | ForEach-Object { $_.Value })
        $transcriptHashMismatch = @($transcriptEvidence | Where-Object {
            -not (Test-Path -LiteralPath ([string]$_.transcriptPath) -PathType Leaf) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath ([string]$_.transcriptPath)).Hash.ToLowerInvariant() -cne [string]$_.transcriptSha256 -or
            $null -eq $_.isError
        })
        $transcriptBinding = (@($transcriptEvidence | Sort-Object caseName | ForEach-Object {
            "$($_.caseName)`t$($_.transcriptPath)`t$($_.transcriptSha256)"
        }) -join "`n")
        $securityFailures = @($policySecurity.checks.PSObject.Properties | Where-Object { $_.Value -ne $true })
        if (
            [string]$filesystemPolicyAcceptance.schema -cne 'xinao.pi_s_subagents_filesystem_policy_acceptance.v1' -or
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
            $transcriptEvidence.Count -ne 11 -or
            $transcriptHashMismatch.Count -ne 0 -or
            (Get-PiSurfaceTextSha256 -Text $transcriptBinding) -cne [string]$policyBody.child_tool_transcript_binding_sha256 -or
            $filesystemPolicyAcceptance.transcript_hashes_read_back_equal -ne $true -or
            $filesystemPolicyAcceptance.active_pi_subagents_source_unchanged -ne $true -or
            $filesystemPolicyAcceptance.prime_b_pi_subagents_source_unchanged -ne $true -or
            [string]$filesystemPolicyAcceptance.active_pi_subagents_source_before_sha256 -cne [string]$filesystemPolicyAcceptance.active_pi_subagents_source_after_sha256 -or
            [string]$filesystemPolicyAcceptance.prime_b_pi_subagents_source_before_sha256 -cne [string]$filesystemPolicyAcceptance.prime_b_pi_subagents_source_after_sha256 -or
            [string]$filesystemPolicyAcceptance.active_pi_subagents_source_after_sha256 -cne $currentActivePiSubagentsSourceSha256 -or
            [string]$filesystemPolicyAcceptance.prime_b_pi_subagents_source_after_sha256 -cne $currentPrimeBPiSubagentsSourceSha256
        ) { throw "PI_SURFACE_TEST_FILESYSTEM_POLICY_ACCEPTANCE_INVALID: $filesystemPolicyReceiptPath" }
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
            [string]$returnToParentAcceptance.schema -cne 'xinao.pi_return_to_parent.acceptance.v3' -or
            [string]$returnToParentAcceptance.status -ne 'mechanically_verified' -or
            [string]$returnToParentAcceptance.behavior_selection_status -ne 'pending_live_sol' -or
            $returnToParentAcceptance.root_only_registration -ne $true -or
            $returnToParentAcceptance.abort_fence_runtime_handshake_required -ne $true -or
            $returnToParentAcceptance.missing_handshake_inert -ne $true -or
            $returnToParentAcceptance.normalized_empty_rejected -ne $true -or
            $returnToParentAcceptance.same_run_continuation_after_local_boundary -ne $true -or
            $returnToParentAcceptance.scripted_no_action_path_does_not_auto_continue -ne $true -or
            $returnToParentAcceptance.pre_execute_abort_rejected -ne $true -or
            $returnToParentAcceptance.turn_boundary_abort_prevents_next_provider -ne $true -or
            [int]$returnToParentAcceptance.queued_user_messages -ne 0 -or
            $returnToParentAcceptance.automatic_wake -ne $true -or
            $returnToParentAcceptance.native_one_shot_follow_up -ne $true -or
            $returnToParentAcceptance.next_contact_may_already_be_consumed -ne $true -or
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
            [int]$returnToParentAcceptance.provider_calls_positive -ne 2 -or
            [int]$returnToParentAcceptance.provider_calls_negative -ne 1 -or
            [int]$returnToParentAcceptance.provider_calls_native_continuation -ne 3 -or
            [int]$returnToParentAcceptance.provider_calls_multi_provider_continuation -ne 5
        ) { throw "PI_SURFACE_TEST_RETURN_TO_PARENT_INVALID: $($returnToParentRaw -join ' ')" }
        if ($RequireLiveReturnAcceptance) {
            $returnToParentLiveRaw = @(& node (Join-Path $PSScriptRoot 'Test-PiSReturnToParentLive.mjs') $spec.SessionDir 2>&1)
            if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_RETURN_TO_PARENT_LIVE_FAILED: $($returnToParentLiveRaw -join ' ')" }
            $returnToParentLiveAcceptance = ($returnToParentLiveRaw -join [Environment]::NewLine) | ConvertFrom-Json
            if (
                [string]$returnToParentLiveAcceptance.schema -cne 'xinao.pi_return_to_parent_live_sol_acceptance.v3' -or
                [string]$returnToParentLiveAcceptance.status -ne 'live_sol_native_continuation_abort_fenced_verified' -or
                [string]$returnToParentLiveAcceptance.maturity -ne 'not_yet_mature' -or
                [string]$returnToParentLiveAcceptance.provider -ne 'openai-codex' -or
                [string]$returnToParentLiveAcceptance.model -ne 'gpt-5.6-sol' -or
                $returnToParentLiveAcceptance.actual_provider_tool_call -ne $true -or
                $returnToParentLiveAcceptance.normalized_argument_binding -ne $true -or
                $returnToParentLiveAcceptance.matching_tool_result_unique -ne $true -or
                $returnToParentLiveAcceptance.matching_arm_first_and_unique -ne $true -or
                $returnToParentLiveAcceptance.tool_result_consumed_before_first_run_final -ne $true -or
                $returnToParentLiveAcceptance.first_run_reached_terminal_assistant_before_native_follow_up -ne $true -or
                $returnToParentLiveAcceptance.native_custom_follow_up_triggered_second_provider -ne $true -or
                $returnToParentLiveAcceptance.one_shot -ne $true -or
                [string]::IsNullOrWhiteSpace([string]$returnToParentLiveAcceptance.arm_id) -or
                $returnToParentLiveAcceptance.next_contact_may_already_be_consumed -ne $true -or
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
Without using tools, report instructions already present in your current context. Return exactly one minified JSON object and nothing else with these keys and values: global_sentinel="HUMAN_INTENT_CONTINUITY_ROLE_SEPARATION_V1"; family_sentinel="PI_LOCAL_COGNITION_CONTRACT_ISLAND_V1"; surface_sentinel="$($spec.SurfaceSentinel)"; current_surface="$profileName"; surface_role="$($spec.Role)"; runtime_version="0.84.1"; research_and_self_evolution_are_tasks=true; one_session_can_cross_repositories=true; profile_auth_session_and_island_are_independent=true; codex_behavior_and_skills_are_shared_baseline=true; pi_specific_contract_stays_outside_codex_and_s=true; main_prime_is_default_subject=true; unqualified_pi_means_main_prime=true; prime_s_is_internal_compat_profile=true; account_binding_is_quota_source_not_identity=true; pi_b_is_isolated_cold_snapshot=true; cold_snapshot_preserves_auth_session_child_cognition_isolation=true; cold_snapshot_not_live_sync_peer=true; owner_eligibility_depends_on_consumed_intent_and_responsibility_not_shell=true; sibling_repository_local_context_must_be_read_before_effects=true; open_external_query_is_seed_not_automatic_boundary=true; external_findings_must_collide_with_live_local_baseline=true; exact_or_explicitly_narrow_lookup_stays_bounded=true; natural_chinese_commentary_without_status_templates=true.
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
            [string]$probe.global_sentinel -ne 'HUMAN_INTENT_CONTINUITY_ROLE_SEPARATION_V1' -or
            [string]$probe.family_sentinel -ne 'PI_LOCAL_COGNITION_CONTRACT_ISLAND_V1' -or
            [string]$probe.surface_sentinel -ne $spec.SurfaceSentinel -or
            [string]$probe.current_surface -ne $profileName -or
            [string]$probe.surface_role -ne $spec.Role -or
            [string]$probe.runtime_version -ne '0.84.1' -or
            $probe.research_and_self_evolution_are_tasks -ne $true -or
            $probe.one_session_can_cross_repositories -ne $true -or
            $probe.profile_auth_session_and_island_are_independent -ne $true -or
            $probe.codex_behavior_and_skills_are_shared_baseline -ne $true -or
            $probe.pi_specific_contract_stays_outside_codex_and_s -ne $true -or
            $probe.main_prime_is_default_subject -ne $true -or
            $probe.unqualified_pi_means_main_prime -ne $true -or
            $probe.prime_s_is_internal_compat_profile -ne $true -or
            $probe.account_binding_is_quota_source_not_identity -ne $true -or
            $probe.pi_b_is_isolated_cold_snapshot -ne $true -or
            $probe.cold_snapshot_preserves_auth_session_child_cognition_isolation -ne $true -or
            $probe.cold_snapshot_not_live_sync_peer -ne $true -or
            $probe.owner_eligibility_depends_on_consumed_intent_and_responsibility_not_shell -ne $true -or
            $probe.sibling_repository_local_context_must_be_read_before_effects -ne $true -or
            $probe.open_external_query_is_seed_not_automatic_boundary -ne $true -or
            $probe.external_findings_must_collide_with_live_local_baseline -ne $true -or
            $probe.exact_or_explicitly_narrow_lookup_stays_bounded -ne $true -or
            $probe.natural_chinese_commentary_without_status_templates -ne $true
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
        agents_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $agentsPath).Hash.ToLowerInvariant()
        contract_projection_sha256 = $projection.Sha256
        family_contract_sha256 = $projection.FamilySha256
        surface_contract_sha256 = $projection.SurfaceSha256
        skill_count = @($names | Where-Object { $_ -like 'skill:*' }).Count
        required_skills_loaded = $true
        packages = $actualPackages
        hermes_memory_capacity = $hermesMemoryCapacity
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
        subagents_filesystem_policy = $filesystemPolicyAcceptance
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
    (Test-Path -LiteralPath (Join-Path $primeBSpecForNegative.AgentDir 'extensions\return-to-parent.ts') -PathType Leaf) -or
    'agents/peer.md' -in $primeBManifestOwned -or
    'extensions/return-to-parent.ts' -in $primeBManifestOwned
) { throw 'PI_SURFACE_TEST_COLD_BACKUP_INHERITED_MAIN_ONLY_CAPABILITY' }
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
    shared_behavior_source = Join-Path $script:PiDualEntryBehaviorCodexHome 'AGENTS.md'
    shared_skills_source = Join-Path $script:PiDualEntryBehaviorCodexHome 'skills'
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
