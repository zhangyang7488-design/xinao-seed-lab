param(
    [switch]$WriteRuntime,
    [switch]$Enforce,
    [string]$CodexHome = "C:\Users\xx363\.codex-seed-cortex",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"

function Read-TextOrEmpty {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    }
    return ""
}

function New-Check {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Observed,
        [bool]$BlocksStartup = $false
    )
    [pscustomobject]@{
        name = $Name
        status = if ($Passed) { "pass" } else { "fail" }
        observed = $Observed
        blocks_startup = ($BlocksStartup -and -not $Passed)
    }
}

function Get-HookCommands {
    param([string]$HooksPath)
    $commands = @()
    if (-not (Test-Path -LiteralPath $HooksPath -PathType Leaf)) {
        return $commands
    }
    $parsed = Get-Content -LiteralPath $HooksPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $parsed.hooks) {
        return $commands
    }
    foreach ($eventProp in $parsed.hooks.PSObject.Properties) {
        foreach ($entry in @($eventProp.Value)) {
            foreach ($hook in @($entry.hooks)) {
                if ($hook.command) {
                    $commands += [pscustomobject]@{
                        event = $eventProp.Name
                        command = [string]$hook.command
                    }
                }
            }
        }
    }
    return $commands
}

function Read-JsonOrNull {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Test-JsonPropertyPresent {
    param(
        $Object,
        [string]$Name
    )
    return ($null -ne $Object) -and ($Object.PSObject.Properties.Name -contains $Name)
}

function Get-JsonPropertyString {
    param(
        $Object,
        [string]$Name
    )
    if (-not (Test-JsonPropertyPresent $Object $Name)) {
        return ""
    }
    return [string]$Object.$Name
}

$configPath = Join-Path $CodexHome "config.toml"
$hooksPath = Join-Path $CodexHome "hooks.json"
$rulesPath = Join-Path $CodexHome "rules\default.rules"
$globalOverridePath = Join-Path $CodexHome "AGENTS.override.md"
$globalAgentsPath = Join-Path $CodexHome "AGENTS.md"
$openResearchAgentPath = Join-Path $CodexHome "agents\open-external-researcher.toml"
$openAuditAgentPath = Join-Path $CodexHome "agents\open-intent-side-auditor.toml"
$repoL0Path = Join-Path $RepoRoot "CODEX_S_L0.md"
$repoAgentsPath = Join-Path $RepoRoot "AGENTS.md"
$mcpServerPath = Join-Path $RepoRoot "services\mcp\xinao_mcp_server.py"
$situationBridgeScriptPath = Join-Path $RepoRoot "scripts\hardmode\Invoke-CodexSSituationBridge.ps1"
$situationBridgeStatePath = Join-Path $RuntimeRoot "state\codex_s_situation_bridge\latest.json"
$intentFunctionalObjectsStatePath = Join-Path $RuntimeRoot "state\codex_s_intent_functional_objects\latest.json"
$globalSelfPreludeStatePath = Join-Path $RuntimeRoot "state\codex_s_global_self_prelude\latest.json"
$globalSelfPreludePromptPath = Join-Path $RuntimeRoot "state\codex_s_global_self_prelude\latest.prompt.md"
$metaminuteVerifierPath = Join-Path $RepoRoot "scripts\verify_metaminute_preflight_reflection.ps1"

$configRaw = Read-TextOrEmpty -Path $configPath
$hooksRaw = Read-TextOrEmpty -Path $hooksPath
$globalOverrideRaw = Read-TextOrEmpty -Path $globalOverridePath
$mcpServerRaw = Read-TextOrEmpty -Path $mcpServerPath
$hookCommands = @()
$hooksJsonValid = $true
try {
    $hookCommands = Get-HookCommands -HooksPath $hooksPath
}
catch {
    $hooksJsonValid = $false
}

$oldHookPattern = "codex_lifecycle_hook_guard|CodexWorkspaces\\B|D:\\XINAO_CLEAN_RUNTIME\\resources\\startup\\codex_l0_bootstrap|current_task_owner_stop_gate|completion_claim_forced_default_path"
$oldHookMatches = @($hookCommands | Where-Object { $_.command -match $oldHookPattern })
$sScopedHookMatches = @($hookCommands | Where-Object { $_.command -match "Invoke-CodexSSideAuditHook.ps1" })
$sMetaMinuteHookMatches = @($hookCommands | Where-Object { $_.command -match "Invoke-CodexSMetaMinutePreflight.ps1" })
$sMetaMinuteSessionStartMatches = @($sMetaMinuteHookMatches | Where-Object { $_.event -eq "SessionStart" -and $_.command -match "window_start_first_hop" })
$sMetaMinuteUserPromptSubmitMatches = @($sMetaMinuteHookMatches | Where-Object { $_.event -eq "UserPromptSubmit" -and $_.command -match "user_prompt_submit" })
$sMetaMinuteStopMatches = @($sMetaMinuteHookMatches | Where-Object { $_.event -eq "Stop" -and $_.command -match "before_final_pass_report" })
$sSituationBridgeHookMatches = @($hookCommands | Where-Object { $_.command -match "Invoke-CodexSSituationBridge.ps1" })
$memoryDisabled = (
    $configRaw -match "\[memories\]" -and
    $configRaw -match "use_memories\s*=\s*false" -and
    $configRaw -match "generate_memories\s*=\s*false" -and
    $configRaw -match "disable_on_external_context\s*=\s*true"
)
$mcpServerNames = @()
foreach ($line in ($configRaw -split "\r?\n")) {
    $trimmed = $line.TrimStart()
    if ($trimmed.StartsWith("#")) {
        continue
    }
    $match = [regex]::Match($line, "^\s*\[mcp_servers\.([A-Za-z0-9_-]+)\]\s*$")
    if ($match.Success) {
        $mcpServerNames += $match.Groups[1].Value
    }
}
$mcpRuntimeCommand = ""
$mcpRuntimeServerMatch = [regex]::Match($configRaw, "(?s)\[mcp_servers\.xinao_runtime\](?<body>.*?)(?=\r?\n\[|$)")
if ($mcpRuntimeServerMatch.Success) {
    $mcpRuntimeCommandMatch = [regex]::Match($mcpRuntimeServerMatch.Groups["body"].Value, "command\s*=\s*'(?<command>[^']+)'")
    if ($mcpRuntimeCommandMatch.Success) {
        $mcpRuntimeCommand = $mcpRuntimeCommandMatch.Groups["command"].Value
    }
}
$mcpRuntimeCommandIsSScoped = (
    $mcpRuntimeCommand -ieq "D:\XINAO_RESEARCH_RUNTIME\tool_envs\mature-runtime-py\Scripts\python.exe"
)
$mcpLegacyHotpathDisabled = (
    $configRaw -notmatch "XINAO_MCP_LEGACY_REFERENCE_ONLY\s*=\s*'0'" -and
    $configRaw -match "XINAO_COMPAT_RUNTIME_ROLE\s*=\s*'reference_only_explicit_compat_input'" -and
    $configRaw -match "XINAO_MCP_LEGACY_HOTPATH_ENABLED\s*=\s*'0'"
)
$mcpSScoped = (
    ($mcpServerNames -contains "xinao_runtime") -and
    $configRaw -match "XINAO_ROUTE_PROFILE\s*=\s*'seed_cortex_phase0'" -and
    $configRaw -match "XINAO_RUNTIME_ROOT\s*=\s*'D:\\XINAO_RESEARCH_RUNTIME'"
)
$mcpFailClosedForS = (
    $mcpServerRaw -match "XINAO_SEED_CORTEX_MCP_RUNTIME_ROOT_REQUIRED" -and
    $mcpServerRaw -match "XINAO_SEED_CORTEX_MCP_CLEAN_RUNTIME_REQUIRES_REFERENCE_ONLY" -and
    $mcpServerRaw -match "SEED_CORTEX_ROUTE_PROFILE\s*=\s*`"seed_cortex_phase0`""
)
$openResearchAgentRaw = Read-TextOrEmpty -Path $openResearchAgentPath
$openAuditAgentRaw = Read-TextOrEmpty -Path $openAuditAgentPath
$openIntentAgentMachineFieldsPresent = (
    $openResearchAgentRaw -match "min_source_families\s*=\s*2" -and
    $openResearchAgentRaw -match "must_call_external_search\s*=\s*true" -and
    $openResearchAgentRaw -match "required_output_schema\s*=\s*(`"?)ClaimCard\[\]" -and
    $openAuditAgentRaw -match "must_check_fan_in\s*=\s*true" -and
    $openAuditAgentRaw -match "must_check_tool_evidence\s*=\s*true" -and
    $openAuditAgentRaw -match "min_source_families_for_open_research\s*=\s*2"
)
$codexAppsFeatureDisabled = (
    $configRaw -match "\[features\]" -and
    $configRaw -match "apps\s*=\s*false"
)
$codexAppsMcpAbsent = ($mcpServerNames -notcontains "codex_apps")

$parallelCapacityPath = Join-Path $RuntimeRoot "state\parallel_capacity\latest.json"
$parallelFanoutPlanPath = Join-Path $RuntimeRoot "state\parallel_fanout_plan\latest.json"
$parallelFanInAcceptancePath = Join-Path $RuntimeRoot "state\parallel_fan_in_acceptance\latest.json"
$parallelCapacity = Read-JsonOrNull -Path $parallelCapacityPath
$parallelFanoutPlan = Read-JsonOrNull -Path $parallelFanoutPlanPath
$parallelFanInAcceptance = Read-JsonOrNull -Path $parallelFanInAcceptancePath
$parallelStatePresent = (($null -ne $parallelCapacity) -and ($null -ne $parallelFanoutPlan) -and ($null -ne $parallelFanInAcceptance))
$fanInRequired = $false
if (Test-JsonPropertyPresent $parallelFanoutPlan "fan_in_required") {
    $fanInRequired = ($parallelFanoutPlan.fan_in_required -eq $true)
}
$fanInAcceptanceSignal = $false
if ($null -ne $parallelFanInAcceptance) {
    $fanInAcceptanceSignal = (
        (-not [string]::IsNullOrWhiteSpace((Get-JsonPropertyString $parallelFanInAcceptance "status"))) -or
        (-not [string]::IsNullOrWhiteSpace((Get-JsonPropertyString $parallelFanInAcceptance "acceptance_id"))) -or
        (
            (Test-JsonPropertyPresent $parallelFanInAcceptance "accepted_edges") -and
            (@($parallelFanInAcceptance.accepted_edges).Count -gt 0)
        )
    )
}
$fanInAcceptancePresentWhenParallel = (
    $parallelStatePresent -and
    ((-not $fanInRequired) -or $fanInAcceptanceSignal)
)
$situationBridgeState = Read-JsonOrNull -Path $situationBridgeStatePath
$intentFunctionalObjectsState = Read-JsonOrNull -Path $intentFunctionalObjectsStatePath
$globalSelfPreludeState = Read-JsonOrNull -Path $globalSelfPreludeStatePath
$globalSelfPreludeReady = (
    ($null -ne $globalSelfPreludeState) -and
    ([string]$globalSelfPreludeState.scope -eq "global_always_on_for_codex_s") -and
    ($globalSelfPreludeState.keyword_required -eq $false) -and
    (Test-Path -LiteralPath $globalSelfPreludePromptPath -PathType Leaf)
)

$agentCandidates = @(
    $globalOverridePath,
    $globalAgentsPath,
    (Join-Path (Split-Path -Parent $RepoRoot) "AGENTS.override.md"),
    (Join-Path (Split-Path -Parent $RepoRoot) "AGENTS.md"),
    (Join-Path $RepoRoot "AGENTS.override.md"),
    $repoAgentsPath
) | ForEach-Object {
    [pscustomobject]@{
        path = $_
        exists = Test-Path -LiteralPath $_ -PathType Leaf
    }
}

$checks = @(
    (New-Check -Name "codex_home_is_s" -Passed ($CodexHome -ieq "C:\Users\xx363\.codex-seed-cortex") -Observed $CodexHome -BlocksStartup $true),
    (New-Check -Name "repo_root_is_s" -Passed ($RepoRoot -ieq "E:\XINAO_RESEARCH_WORKSPACES\S") -Observed $RepoRoot -BlocksStartup $true),
    (New-Check -Name "s_l0_exists" -Passed (Test-Path -LiteralPath $repoL0Path -PathType Leaf) -Observed $repoL0Path -BlocksStartup $true),
    (New-Check -Name "s_global_override_exists" -Passed (Test-Path -LiteralPath $globalOverridePath -PathType Leaf) -Observed $globalOverridePath -BlocksStartup $true),
    (New-Check -Name "config_present" -Passed (Test-Path -LiteralPath $configPath -PathType Leaf) -Observed $configPath -BlocksStartup $true),
    (New-Check -Name "hooks_json_valid" -Passed $hooksJsonValid -Observed $hooksPath -BlocksStartup $true),
    (New-Check -Name "hooks_are_s_scoped" -Passed (($oldHookMatches.Count -eq 0) -and ($sScopedHookMatches.Count -ge 1)) -Observed (($hookCommands | ForEach-Object { "$($_.event):$($_.command)" }) -join " | ") -BlocksStartup $true),
    (New-Check -Name "metaminute_session_start_hotpath_present" -Passed ($sMetaMinuteSessionStartMatches.Count -ge 1) -Observed (($hookCommands | ForEach-Object { "$($_.event):$($_.command)" }) -join " | ") -BlocksStartup $false),
    (New-Check -Name "metaminute_user_prompt_submit_hotpath_present" -Passed ($sMetaMinuteUserPromptSubmitMatches.Count -ge 1) -Observed (($hookCommands | ForEach-Object { "$($_.event):$($_.command)" }) -join " | ") -BlocksStartup $false),
    (New-Check -Name "metaminute_stop_hotpath_present" -Passed ($sMetaMinuteStopMatches.Count -ge 1) -Observed (($hookCommands | ForEach-Object { "$($_.event):$($_.command)" }) -join " | ") -BlocksStartup $false),
    (New-Check -Name "memory_injection_disabled" -Passed $memoryDisabled -Observed $configPath -BlocksStartup $true),
    (New-Check -Name "mcp_runtime_is_s_scoped" -Passed $mcpSScoped -Observed (($mcpServerNames -join ",")) -BlocksStartup $true),
    (New-Check -Name "mcp_runtime_command_is_research_scoped" -Passed $mcpRuntimeCommandIsSScoped -Observed $mcpRuntimeCommand -BlocksStartup $true),
    (New-Check -Name "mcp_legacy_hotpath_disabled" -Passed $mcpLegacyHotpathDisabled -Observed "compat_role_and_legacy_hotpath_flag" -BlocksStartup $true),
    (New-Check -Name "mcp_seed_cortex_missing_runtime_env_fails_closed" -Passed $mcpFailClosedForS -Observed $mcpServerPath -BlocksStartup $true),
    (New-Check -Name "open_intent_agent_machine_fields_present" -Passed $openIntentAgentMachineFieldsPresent -Observed "$openResearchAgentPath | $openAuditAgentPath" -BlocksStartup $false),
    (New-Check -Name "codex_apps_feature_disabled" -Passed $codexAppsFeatureDisabled -Observed $configPath -BlocksStartup $false),
    (New-Check -Name "codex_apps_mcp_not_configured" -Passed $codexAppsMcpAbsent -Observed (($mcpServerNames -join ",")) -BlocksStartup $false),
    (New-Check -Name "parallel_state_files_present" -Passed $parallelStatePresent -Observed "$parallelCapacityPath | $parallelFanoutPlanPath | $parallelFanInAcceptancePath" -BlocksStartup $false),
    (New-Check -Name "fan_in_acceptance_present_when_parallel" -Passed $fanInAcceptancePresentWhenParallel -Observed $parallelFanInAcceptancePath -BlocksStartup $false),
    (New-Check -Name "situation_bridge_hook_present" -Passed ($sSituationBridgeHookMatches.Count -ge 1) -Observed (($hookCommands | ForEach-Object { "$($_.event):$($_.command)" }) -join " | ") -BlocksStartup $false),
    (New-Check -Name "situation_bridge_script_exists" -Passed (Test-Path -LiteralPath $situationBridgeScriptPath -PathType Leaf) -Observed $situationBridgeScriptPath -BlocksStartup $false),
    (New-Check -Name "situation_bridge_state_present" -Passed ($null -ne $situationBridgeState) -Observed $situationBridgeStatePath -BlocksStartup $false),
    (New-Check -Name "intent_functional_objects_state_present" -Passed ($null -ne $intentFunctionalObjectsState) -Observed $intentFunctionalObjectsStatePath -BlocksStartup $false),
    (New-Check -Name "global_override_self_prelude_present" -Passed ($globalOverrideRaw -match "Global Codex self-prelude" -and $globalOverrideRaw -match "not a keyword trigger") -Observed $globalOverridePath -BlocksStartup $false),
    (New-Check -Name "global_self_prelude_state_present" -Passed $globalSelfPreludeReady -Observed "$globalSelfPreludeStatePath | $globalSelfPreludePromptPath" -BlocksStartup $false),
    (New-Check -Name "global_self_prelude_verifier_exists" -Passed (Test-Path -LiteralPath $metaminuteVerifierPath -PathType Leaf) -Observed $metaminuteVerifierPath -BlocksStartup $false),
    (New-Check -Name "rules_default_absent_or_auditable" -Passed $true -Observed $rulesPath -BlocksStartup $false)
)

$blocking = @($checks | Where-Object { $_.blocks_startup -eq $true })
$status = if ($blocking.Count -eq 0) { "codex_s_self_identity_preflight_pass" } else { "codex_s_self_identity_preflight_blocked" }
$payload = [ordered]@{
    schema_version = "xinao.codex_s_self_identity_preflight.v1"
    status = $status
    checked_at = (Get-Date).ToUniversalTime().ToString("o")
    codex_home = $CodexHome
    repo_root = $RepoRoot
    runtime_root = $RuntimeRoot
    config_path = $configPath
    hooks_path = $hooksPath
    rules_path = $rulesPath
    mcp_servers = $mcpServerNames
    hook_commands = @($hookCommands)
    old_hook_matches = @($oldHookMatches)
    agent_source_candidates = @($agentCandidates)
    checks = @($checks)
    not_user_completion = $true
    not_completion_decision = $true
    not_execution_controller = $true
}

if ($WriteRuntime) {
    $outDir = Join-Path $RuntimeRoot "state\codex_s_self_identity_preflight"
    New-Item -ItemType Directory -Force $outDir | Out-Null
    $outPath = Join-Path $outDir "latest.json"
    $payload["written_path"] = $outPath
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($outPath, (($payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine), $utf8NoBom)
}

$payload | ConvertTo-Json -Depth 8

if ($Enforce -and $blocking.Count -gt 0) {
    throw "CODEX_S_SELF_IDENTITY_PREFLIGHT_BLOCKED"
}
