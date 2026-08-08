#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('prime-b','prime-s')][string[]]$Profile = @('prime-s'),
    [switch]$SkipAuthRefresh,
    [switch]$RunLiveModelProbe,
    [string]$ReceiptPath
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

Assert-PiDualEntryBinary
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
foreach ($profileName in $Profile) {
    $spec = Get-PiDualEntrySpec -Profile $profileName
    $env:PI_CODING_AGENT_DIR = $spec.AgentDir
    $env:PI_CODING_AGENT_SESSION_DIR = $spec.SessionDir
    $env:PI_SKIP_VERSION_CHECK = '1'
    $env:PI_TELEMETRY = '0'
    $env:CODEX_HOME = $spec.CodexHome
    $env:XINAO_ACCOUNT_SLOT = $spec.AccountSlot
    $env:XINAO_PI_ROLE = $spec.Role

    $projection = Sync-PiDualEntryContractProjection -Spec $spec
    $authPath = Join-Path $spec.AgentDir 'auth.json'
    $settingsPath = Join-Path $spec.AgentDir 'settings.json'
    $subagentConfigPath = Join-Path $spec.AgentDir 'extensions\subagent\config.json'
    $agentsPath = Join-Path $spec.AgentDir 'AGENTS.md'
    foreach ($required in @($spec.FamilyContractSource,$spec.SurfaceContractSource,$spec.ContractProjection,$spec.AccountBindingPath,$authPath,$settingsPath,$subagentConfigPath,$agentsPath,$spec.CodexAuthSource)) {
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
    $catalogContextWindow = $null
    $profileContextWindowOverrideAbsent = $null
    if ($profileName -eq 'prime-s') {
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
    }
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

    $authArgs = @('auth','check','--provider','openai-codex','--json')
    if ($SkipAuthRefresh) { $authArgs += '--no-refresh' }
    $authRaw = @(& $script:PiDualEntryCommand @authArgs 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_AUTH_CHECK_FAILED: profile=$profileName output=$($authRaw -join ' ')" }
    $authResult = ($authRaw -join [Environment]::NewLine) | ConvertFrom-Json
    $authReady = ([string]$authResult.status -eq 'ready' -and [string]$authResult.provider -eq 'openai-codex')
    if (-not $authReady) { throw "PI_SURFACE_TEST_AUTH_NOT_READY: profile=$profileName status=$($authResult.status)" }

    $rpcRaw = @('{"type":"get_commands"}') | & $script:PiDualEntryCommand --mode rpc --no-session --offline --provider openai-codex --model gpt-5.6-sol --thinking max --append-system-prompt $spec.ContractProjection
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
    $midTurnCompactionAcceptance = $null
    if ($profileName -eq 'prime-s') {
        $midTurnRaw = @(& (Join-Path $PSScriptRoot 'Apply-PiSMidTurnCompactionCompatibility.ps1') -VerifyOnly 2>&1)
        $midTurnCompactionAcceptance = ($midTurnRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if (
            [string]$midTurnCompactionAcceptance.schema -ne 'xinao.pi_s_midturn_compaction_compatibility.v1' -or
            $midTurnCompactionAcceptance.prime_s_runtime_gate_required -ne $true -or
            $midTurnCompactionAcceptance.completed_tool_boundary_stop -ne $true -or
            $midTurnCompactionAcceptance.compact_and_continue_same_run -ne $true -or
            $midTurnCompactionAcceptance.compaction_failure_stops_before_provider -ne $true
        ) {
            throw "PI_SURFACE_TEST_MIDTURN_PATCH_STATUS_INVALID: $($midTurnRaw -join ' ')"
        }
        $numpadRaw = @(& (Join-Path $PSScriptRoot 'Set-PiSNumpadEnterFollow.ps1') -AgentDir $spec.AgentDir -ValidateOnly 2>&1)
        $numpadStatus = ($numpadRaw -join [Environment]::NewLine) | ConvertFrom-Json
        if ([string]$numpadStatus.status -ne 'ready' -or $numpadStatus.main_enter_unchanged -ne $true -or $numpadStatus.helper_failure_blocks_pi -ne $false) {
            throw "PI_SURFACE_TEST_NUMPAD_STATUS_INVALID: $($numpadRaw -join ' ')"
        }
        $piPackageRoot = Join-Path $script:PiDualEntryToolRoot 'node_modules\@earendil-works\pi-coding-agent'
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
Without using tools, report instructions already present in your current context. Return exactly one minified JSON object and nothing else with these keys and values: global_sentinel="HUMAN_INTENT_CONTINUITY_ROLE_SEPARATION_V1"; family_sentinel="PI_LOCAL_COGNITION_CONTRACT_ISLAND_V1"; surface_sentinel="$($spec.SurfaceSentinel)"; current_surface="$profileName"; surface_role="$($spec.Role)"; runtime_version="0.84.1"; research_and_self_evolution_are_tasks=true; one_session_can_cross_repositories=true; profile_auth_session_and_island_are_independent=true; codex_behavior_and_skills_are_shared_baseline=true; pi_specific_contract_stays_outside_codex_and_s=true; prime_s_is_primary_work_surface=true; prime_b_has_minimum_real_work_ability=true; optimization_investment_is_asymmetric=true; promotion_only_for_proven_delta_with_real_b_consumer=true; owner_eligibility_depends_on_consumed_intent_and_responsibility_not_shell=true; sibling_repository_local_context_must_be_read_before_effects=true; open_external_query_is_seed_not_automatic_boundary=true; external_findings_must_collide_with_live_local_baseline=true; exact_or_explicitly_narrow_lookup_stays_bounded=true; natural_chinese_commentary_without_status_templates=true.
"@.Trim()
        Push-Location -LiteralPath $spec.Workspace
        try {
            $probeRaw = @(& $script:PiDualEntryCommand --print --no-session --no-tools --provider openai-codex --model gpt-5.6-sol --thinking max --append-system-prompt $spec.ContractProjection $probePrompt 2>&1)
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
            $probe.prime_s_is_primary_work_surface -ne $true -or
            $probe.prime_b_has_minimum_real_work_ability -ne $true -or
            $probe.optimization_investment_is_asymmetric -ne $true -or
            $probe.promotion_only_for_proven_delta_with_real_b_consumer -ne $true -or
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
        subagent_config_path = $subagentConfigPath
        subagent_artifact_dir = [string]$subagentConfig.artifactDir
        scheduled_runs_enabled = [bool]$subagentConfig.scheduledRuns.enabled
        missions_enabled = [bool]$subagentConfig.missions.enabled
        provider_catalog_context_window = $catalogContextWindow
        profile_context_window_override_absent = $profileContextWindowOverrideAbsent
        midturn_compaction_compatibility = $midTurnCompactionAcceptance
        numpad_enter_follow = $numpadAcceptance
        live_model_probe = $liveProbe
    }
}

if ($Profile.Count -eq 2) {
    $b = $surfaceResults | Where-Object name -eq 'prime-b'
    $s = $surfaceResults | Where-Object name -eq 'prime-s'
    if ($b.account_binding_path -eq $s.account_binding_path -or $b.session_dir -eq $s.session_dir -or $b.surface_island -eq $s.surface_island) {
        throw 'PI_SURFACE_TEST_ISOLATION_COLLAPSED'
    }
    if ($b.account_slot -ne 'account-b' -or $s.account_slot -ne 'main') {
        throw "PI_SURFACE_TEST_CURRENT_BINDING_UNEXPECTED: prime-b=$($b.account_slot) prime-s=$($s.account_slot)"
    }
}

$bashTool = Join-Path $script:PiDualEntryToolRoot 'node_modules\@earendil-works\pi-coding-agent\dist\core\tools\bash.js'
$nativeWindowsHide = Select-String -LiteralPath $bashTool -Pattern 'windowsHide: true' -SimpleMatch -Quiet
if (-not $nativeWindowsHide) { throw 'PI_SURFACE_TEST_NATIVE_WINDOWS_HIDE_MISSING' }
$node = Get-PiDualEntryNodeInfo
$primeBWrapper = 'C:\Users\xx363\CodexLaunchers\Open-Prime-Agent-Account-B.ps1'
$primeSWrapper = 'C:\Users\xx363\CodexLaunchers\Open-Prime-S.ps1'
$primeSVisibleRestart = Join-Path $PSScriptRoot 'Start-PrimeSInWindowsTerminal.ps1'
$wrapperBText = Get-Content -Raw -LiteralPath $primeBWrapper -Encoding UTF8
$wrapperSText = Get-Content -Raw -LiteralPath $primeSWrapper -Encoding UTF8
if ($wrapperBText -notmatch 'Start-UpstreamPi\.ps1' -or $wrapperBText -notmatch 'Profile prime-b') { throw 'PI_SURFACE_TEST_PRIME_B_WRAPPER_STALE' }
if ($wrapperSText -notmatch 'Start-UpstreamPi\.ps1' -or $wrapperSText -notmatch 'Profile prime-s') { throw 'PI_SURFACE_TEST_PRIME_S_WRAPPER_STALE' }
if (-not (Test-Path -LiteralPath $primeSVisibleRestart -PathType Leaf)) { throw 'PI_SURFACE_TEST_VISIBLE_RESTART_MISSING' }
$visibleRestartText = Get-Content -Raw -LiteralPath $primeSVisibleRestart -Encoding UTF8
foreach ($requiredRestartMarker in @('XINAO prime S','Open-Prime-S.ps1','-Session','PIS_VISIBLE_RESTART_SESSION_NOT_LATEST_FOR_PROFILE','profile-native-continue-after-latest-session-proof','ingress_readback_required')) {
    if ($visibleRestartText -notmatch [regex]::Escape($requiredRestartMarker)) {
        throw "PI_SURFACE_TEST_VISIBLE_RESTART_MARKER_MISSING: $requiredRestartMarker"
    }
}
$terminalSettingsPath = 'C:\Users\xx363\AppData\Local\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json'
$terminalSettings = Get-Content -Raw -LiteralPath $terminalSettingsPath -Encoding UTF8 | ConvertFrom-Json
$primeSProfile = @($terminalSettings.profiles.list | Where-Object { [string]$_.name -eq 'XINAO prime S' })
if (
    $primeSProfile.Count -ne 1 -or
    [string]$primeSProfile[0].commandline -notmatch 'Open-Prime-S\.ps1' -or
    [string]$primeSProfile[0].tabTitle -ne 'prime S' -or
    $primeSProfile[0].suppressApplicationTitle -ne $true -or
    [string]$primeSProfile[0].closeOnExit -ne 'always'
) {
    throw 'PI_SURFACE_TEST_PRIME_S_TERMINAL_PROFILE_STALE'
}
$shortcutPath = 'C:\Users\xx363\Desktop\prime S.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ([string]$shortcut.Arguments -ne '-w new -p "XINAO prime S"') { throw 'PI_SURFACE_TEST_PRIME_S_SHORTCUT_STALE' }
$latestPrimeSSession = Get-ChildItem -LiteralPath (Join-Path $profileRoot 'prime-s\sessions') -File -Filter '*.jsonl' | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if ($null -eq $latestPrimeSSession) { throw 'PI_SURFACE_TEST_VISIBLE_RESTART_SESSION_MISSING' }
$latestPrimeSSessionHeader = Get-Content -LiteralPath $latestPrimeSSession.FullName -TotalCount 1 -Encoding UTF8 | ConvertFrom-Json
$visibleRestartValidationRaw = @(& $primeSVisibleRestart -Session ([string]$latestPrimeSSessionHeader.id) -ValidateOnly 2>&1)
if ($LASTEXITCODE -ne 0) { throw "PI_SURFACE_TEST_VISIBLE_RESTART_VALIDATION_FAILED: $($visibleRestartValidationRaw -join ' ')" }
$visibleRestartValidation = ($visibleRestartValidationRaw -join [Environment]::NewLine) | ConvertFrom-Json
if (
    [string]$visibleRestartValidation.status -ne 'ready' -or
    [string]$visibleRestartValidation.terminal_profile -ne 'XINAO prime S' -or
    [string]$visibleRestartValidation.session_id -ne [string]$latestPrimeSSessionHeader.id -or
    $visibleRestartValidation.same_profile_session_required -ne $true -or
    $visibleRestartValidation.ingress_readback_required -ne $true
) { throw 'PI_SURFACE_TEST_VISIBLE_RESTART_VALIDATION_INVALID' }

$acceptance = [ordered]@{
    schema = 'xinao.pi_stable_leading_surfaces.acceptance.v2'
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
    native_background_child_windows_hidden = $true
    task_topology = 'prime S is the primary work surface; research and self-evolution are tasks inside one active session, never identities or session routes.'
    evolution_topology = 'PrimeB keeps minimum real-work usability while optimization investment remains asymmetric toward prime S; promotion is optional and only for a proven delta with a real B consumer.'
    legacy_prime_0_7_0 = [ordered]@{
        active = $false
        installation_preserved_for_rollback = (Test-Path -LiteralPath 'D:\XINAO_RESEARCH_RUNTIME\tools\prime-agent\0.7.0' -PathType Container)
        contract_snapshot = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island\contracts\evidence\prime-agent-0.7.0-pre-upgrade-20260808'
    }
    desktop_wrappers = @($primeBWrapper,$primeSWrapper)
    prime_s_terminal_profile = 'XINAO prime S'
    prime_s_shortcut = $shortcutPath
    prime_s_visible_restart = $visibleRestartValidation
}
if (-not [string]::IsNullOrWhiteSpace($ReceiptPath)) {
    Write-PiDualEntryJsonAtomic -Path $ReceiptPath -Value $acceptance
}
$acceptance | ConvertTo-Json -Depth 10
