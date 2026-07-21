#Requires -Version 5.1
<#
.SYNOPSIS
  Codex -> N x Grok headless worker pool (CREATE_NO_WINDOW).
.DESCRIPTION
  Bounded dynamic lane: a caller dispatches Grok Composer workers on the
  Windows host when selected by task fit or an existing leg-A route receipt.
  This is normal bounded leg A, not a fallback or unconditional default. It is
  not TUI inject, not Docker desktop .lnk, and not a second owner beside Codex.
.EXAMPLE
  .\Invoke-GrokWorkerPool.ps1 -N 2 -Prompt "Reply only: POOL_OK" -Cwd E:\repo -Model grok-4.5 -SelectionPath D:\decision.json -MaxTurns 1 -MinResultChars 1 -RequiredResultMarkers POOL_OK
  .\Invoke-GrokWorkerPool.ps1 -N 4 -PromptFile .\task.md -Cwd E:\repo -Model grok-4.5 -SelectionPath D:\decision.json
#>
param(
    [ValidateRange(1, 32)]
    [int]$N = 2,
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "",
    [string]$SelectionPath = "",
    [string]$ExpectedSelectionDecisionSha256 = "",
    [string]$MaxTurns = "auto",
    [int]$TimeoutSec = 600,
    [string]$GrokHome = "C:\Users\xx363\.grok-bg-workers",
    [string]$EvidenceRoot = "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool",
    [string]$PoolId = "",
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [string]$CommonLogicalContractPath = "",
    [string]$CommonSubjectManifestSha256 = "",
    [string]$CommonFrozenContextSha256 = "",
    [string]$CommonRulesFile = "",
    [string]$CommonRulesSha256 = "",
    [string]$CommonCandidateOutputRoot = "",
    [string]$CommonPhase = "",
    [string[]]$CommonWriteDomains = @(),
    [string[]]$CommonDependsOn = @(),
    [string]$CommonPriorAttemptReceiptPath = "",
    [string]$CommonAdapterRoot = "",
    [string]$CommonPythonExe = "python",
    [switch]$SkipPauseGate,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
. (Join-Path $PSScriptRoot "GrokWorkerPoolAccounting.ps1")

function Stop-ExactProcessTree([int]$RootProcessId) {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Select-Object ProcessId, ParentProcessId)
    $ids = [System.Collections.Generic.List[int]]::new()
    [void]$ids.Add($RootProcessId)
    do {
        $added = $false
        foreach ($entry in $processes) {
            $childId = [int]$entry.ProcessId
            if ($ids.Contains([int]$entry.ParentProcessId) -and -not $ids.Contains($childId)) {
                [void]$ids.Add($childId)
                $added = $true
            }
        }
    } while ($added)
    $ordered = $ids.ToArray()
    [array]::Reverse($ordered)
    foreach ($processId in $ordered) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    return @($ordered)
}
$bridge = $PSScriptRoot
$workerScript = Join-Path $bridge "Invoke-GrokComposer25Worker.ps1"
if (-not (Test-Path -LiteralPath $workerScript)) {
    throw "WORKER_SCRIPT_MISSING: $workerScript"
}
$selectionHelper = Join-Path $bridge "GrokWorkerSelectionReceipt.ps1"
if (-not (Test-Path -LiteralPath $selectionHelper -PathType Leaf)) {
    throw "GROK_WORKER_POOL_SELECTION_HELPER_MISSING: $selectionHelper"
}
. $selectionHelper
$selection = Read-GrokWorkerSelectionReceipt `
    -SelectionPath $SelectionPath `
    -Model $Model `
    -Cwd $Cwd `
    -RequiredPrefix "GROK_WORKER_POOL"
$SelectionPath = [string]$selection.selection_path
$Model = [string]$selection.model_id
$Cwd = [string]$selection.cwd
if (
    -not [string]::IsNullOrWhiteSpace($ExpectedSelectionDecisionSha256) -and
    -not [string]::Equals(
        $ExpectedSelectionDecisionSha256,
        [string]$selection.decision_sha256,
        [StringComparison]::Ordinal
    )
) {
    throw "GROK_WORKER_POOL_SELECTION_DECISION_CHANGED"
}

# Pause gate: reconnect path requires explicit skip or cleared PAUSED_ALL
$pausePath = "D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\user_pause_all_latest.json"
if (-not $SkipPauseGate -and (Test-Path -LiteralPath $pausePath)) {
    try {
        $pause = Get-Content -LiteralPath $pausePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($pause.status -eq "PAUSED_ALL" -and $pause.subagent_spawn -eq $false) {
            throw "PAUSED_ALL: clear pause or pass -SkipPauseGate for grok_worker_pool reconnect"
        }
    } catch {
        if ("$_" -match "PAUSED_ALL") { throw }
    }
}

if ($PromptFile) {
    if (-not (Test-Path -LiteralPath $PromptFile)) { throw "PromptFile missing: $PromptFile" }
    $Prompt = Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8
}
if ([string]::IsNullOrWhiteSpace($Prompt)) {
    throw "Prompt or PromptFile required"
}

$commonMode = (
    -not [string]::IsNullOrWhiteSpace($CommonLogicalContractPath) -or
    -not [string]::IsNullOrWhiteSpace($CommonSubjectManifestSha256) -or
    -not [string]::IsNullOrWhiteSpace($CommonFrozenContextSha256) -or
    -not [string]::IsNullOrWhiteSpace($CommonRulesFile) -or
    -not [string]::IsNullOrWhiteSpace($CommonRulesSha256) -or
    -not [string]::IsNullOrWhiteSpace($CommonCandidateOutputRoot) -or
    -not [string]::IsNullOrWhiteSpace($CommonPhase) -or
    @($CommonWriteDomains).Count -gt 0 -or
    @($CommonDependsOn).Count -gt 0 -or
    -not [string]::IsNullOrWhiteSpace($CommonPriorAttemptReceiptPath) -or
    -not [string]::IsNullOrWhiteSpace($CommonAdapterRoot)
)
$commonContract = $null
$commonPreflight = $null
$commonAdapterScript = ""
$commonOutputContract = $null

function Assert-CommonSha256([string]$Value, [string]$Field) {
    if ($Value -notmatch '^[0-9a-f]{64}$') {
        throw "GROK_WORKER_POOL_COMMON_SHA256_INVALID: $Field"
    }
}

function Assert-CommonEqual([string]$Observed, [string]$Expected, [string]$Field) {
    if (-not [string]::Equals($Observed, $Expected, [StringComparison]::Ordinal)) {
        throw "GROK_WORKER_POOL_COMMON_CONTRACT_MISMATCH: $Field"
    }
}

if ($commonMode) {
    if ($N -ne 1) { throw "GROK_WORKER_POOL_COMMON_REQUIRES_SINGLE_LANE" }
    $commonRequired = [ordered]@{
        logical_contract_path = $CommonLogicalContractPath
        subject_manifest_sha256 = $CommonSubjectManifestSha256
        frozen_context_sha256 = $CommonFrozenContextSha256
        rules_file = $CommonRulesFile
        rules_sha256 = $CommonRulesSha256
        phase = $CommonPhase
        adapter_root = $CommonAdapterRoot
        python_exe = $CommonPythonExe
    }
    foreach ($entry in $commonRequired.GetEnumerator()) {
        if ([string]::IsNullOrWhiteSpace([string]$entry.Value)) {
            throw "GROK_WORKER_POOL_COMMON_REQUIRED: $($entry.Key)"
        }
    }
    $CommonPhase = $CommonPhase.Trim().ToUpperInvariant()
    if ($CommonPhase -notin @("EXPLORE", "CONSTRUCT", "VERIFY", "LAND")) {
        throw "GROK_WORKER_POOL_COMMON_PHASE_INVALID: $CommonPhase"
    }
    if ($CommonPhase -eq "LAND" -and @($CommonWriteDomains).Count -eq 0) {
        throw "GROK_WORKER_POOL_COMMON_LAND_REQUIRES_WRITE_DOMAIN"
    }
    Assert-CommonSha256 $CommonSubjectManifestSha256 "subject_manifest_sha256"
    Assert-CommonSha256 $CommonFrozenContextSha256 "frozen_context_sha256"
    Assert-CommonSha256 $CommonRulesSha256 "rules_sha256"

    $CommonLogicalContractPath = [IO.Path]::GetFullPath($CommonLogicalContractPath)
    if (-not (Test-Path -LiteralPath $CommonLogicalContractPath -PathType Leaf)) {
        throw "GROK_WORKER_POOL_COMMON_CONTRACT_MISSING: $CommonLogicalContractPath"
    }
    try { $CommonRulesFile = [IO.Path]::GetFullPath($CommonRulesFile) }
    catch { throw "GROK_WORKER_POOL_COMMON_RULES_FILE_INVALID: $CommonRulesFile" }
    if (-not (Test-Path -LiteralPath $CommonRulesFile -PathType Leaf)) {
        throw "GROK_WORKER_POOL_COMMON_RULES_MISSING: $CommonRulesFile"
    }
    $observedRulesFileSha256 = (Get-FileHash -LiteralPath $CommonRulesFile -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-CommonEqual $observedRulesFileSha256 $CommonRulesSha256 "rules_file.sha256"
    if (-not [string]::IsNullOrWhiteSpace($CommonCandidateOutputRoot)) {
        try { $CommonCandidateOutputRoot = [IO.Path]::GetFullPath($CommonCandidateOutputRoot) }
        catch { throw "GROK_WORKER_POOL_COMMON_CANDIDATE_OUTPUT_ROOT_INVALID: $CommonCandidateOutputRoot" }
        if (-not (Test-Path -LiteralPath $CommonCandidateOutputRoot -PathType Container)) {
            throw "GROK_WORKER_POOL_COMMON_CANDIDATE_OUTPUT_ROOT_MISSING: $CommonCandidateOutputRoot"
        }
        $resolvedCwd = [IO.Path]::GetFullPath($Cwd)
        if (-not [string]::Equals($CommonCandidateOutputRoot, $resolvedCwd, [StringComparison]::OrdinalIgnoreCase)) {
            throw "GROK_WORKER_POOL_COMMON_CANDIDATE_OUTPUT_ROOT_CWD_MISMATCH"
        }
        $expectedCandidateWriteDomain = "candidate_output_root:" + ($CommonCandidateOutputRoot.Replace('\', '/').TrimEnd('/').ToLowerInvariant())
        if (
            @($CommonWriteDomains).Count -ne 1 -or
            -not [string]::Equals([string]$CommonWriteDomains[0], $expectedCandidateWriteDomain, [StringComparison]::Ordinal)
        ) {
            throw "GROK_WORKER_POOL_COMMON_CANDIDATE_WRITE_DOMAIN_MISMATCH"
        }
    }
    $CommonAdapterRoot = [IO.Path]::GetFullPath($CommonAdapterRoot)
    if (-not (Test-Path -LiteralPath $CommonAdapterRoot -PathType Container)) {
        throw "GROK_WORKER_POOL_COMMON_ADAPTER_ROOT_MISSING: $CommonAdapterRoot"
    }
    $commonAdapterScript = Join-Path $CommonAdapterRoot "services\agent_runtime\direct_worker_pool_common_adapter.py"
    if (-not (Test-Path -LiteralPath $commonAdapterScript -PathType Leaf)) {
        throw "GROK_WORKER_POOL_COMMON_ADAPTER_MISSING: $commonAdapterScript"
    }
    if (-not (Get-Command $CommonPythonExe -ErrorAction SilentlyContinue)) {
        throw "GROK_WORKER_POOL_COMMON_PYTHON_MISSING: $CommonPythonExe"
    }
    if (-not [string]::IsNullOrWhiteSpace($CommonPriorAttemptReceiptPath)) {
        $CommonPriorAttemptReceiptPath = [IO.Path]::GetFullPath($CommonPriorAttemptReceiptPath)
        if (-not (Test-Path -LiteralPath $CommonPriorAttemptReceiptPath -PathType Leaf)) {
            throw "GROK_WORKER_POOL_COMMON_PRIOR_RECEIPT_MISSING: $CommonPriorAttemptReceiptPath"
        }
    }

    try {
        $commonContract = Get-Content -LiteralPath $CommonLogicalContractPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "GROK_WORKER_POOL_COMMON_CONTRACT_INVALID_JSON: $CommonLogicalContractPath"
    }
    Assert-CommonEqual ([string]$commonContract.schema_version) "xinao.execution.logical_contract.v1" "schema_version"
    Assert-CommonEqual ([string]$commonContract.selection.provider_id) ([string]$selection.provider_id) "selection.provider_id"
    Assert-CommonEqual ([string]$commonContract.selection.profile_ref) ([string]$selection.profile_ref) "selection.profile_ref"
    Assert-CommonEqual ([string]$commonContract.selection.model_id) $Model "selection.model_id"
    Assert-CommonEqual ([string]$commonContract.selection.transport_id) ([string]$selection.transport_id) "selection.transport_id"

    $promptSha256 = Get-GrokUtf8Sha256Hex -Text $Prompt
    $rulesSha256 = $observedRulesFileSha256
    $schemaSha256 = ""
    if (-not [string]::IsNullOrWhiteSpace($JsonSchemaPath)) {
        $resolvedSchema = [IO.Path]::GetFullPath($JsonSchemaPath)
        if (-not (Test-Path -LiteralPath $resolvedSchema -PathType Leaf)) {
            throw "GROK_WORKER_POOL_COMMON_SCHEMA_MISSING: $resolvedSchema"
        }
        $schemaSha256 = (Get-FileHash -LiteralPath $resolvedSchema -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $commonOutputContract = [ordered]@{
        min_result_chars = [int]$MinResultChars
        required_result_markers = @($RequiredResultMarkers | ForEach-Object { [string]$_ })
        require_json_object = [bool]($RequireJsonObject -or $schemaSha256)
        json_schema_sha256 = $schemaSha256
    }
    $outputContractSha256 = Get-GrokUtf8Sha256Hex -Text (ConvertTo-GrokCanonicalJson $commonOutputContract)
    $contextBinding = [ordered]@{
        frozen_context_sha256 = $CommonFrozenContextSha256
        subject_manifest_sha256 = $CommonSubjectManifestSha256
    }
    $contextSha256 = Get-GrokUtf8Sha256Hex -Text (ConvertTo-GrokCanonicalJson $contextBinding)
    $capabilityBinding = [ordered]@{
        consumer_id = "direct_grok_worker_pool"
        contract_mode = "provider_v1_then_common_adapter"
        lane_count = 1
        selection_decision_sha256 = [string]$selection.decision_sha256
        output_contract_sha256 = $outputContractSha256
    }
    $capabilityBindingSha256 = Get-GrokUtf8Sha256Hex -Text (ConvertTo-GrokCanonicalJson $capabilityBinding)

    Assert-CommonEqual ([string]$commonContract.input_sha256) $promptSha256 "input_sha256"
    Assert-CommonEqual ([string]$commonContract.context_sha256) $contextSha256 "context_sha256"
    Assert-CommonEqual ([string]$commonContract.rules_sha256) $rulesSha256 "rules_sha256"
    Assert-CommonEqual ([string]$commonContract.output_contract_sha256) $outputContractSha256 "output_contract_sha256"
    Assert-CommonEqual ([string]$commonContract.selection.capability_binding_sha256) $capabilityBindingSha256 "selection.capability_binding_sha256"
    $expectedEffectMode = if (@($CommonWriteDomains).Count -gt 0) { "authorized_write" } else { "read_only" }
    Assert-CommonEqual ([string]$commonContract.effect_mode) $expectedEffectMode "effect_mode"

    $logicalContractSha256 = Get-GrokUtf8Sha256Hex -Text (ConvertTo-GrokCanonicalJson $commonContract)
    $commonPreflight = [ordered]@{
        validated = $true
        logical_contract_sha256 = $logicalContractSha256
        frozen_context_sha256 = $CommonFrozenContextSha256
        subject_manifest_sha256 = $CommonSubjectManifestSha256
        input_sha256 = $promptSha256
        context_sha256 = $contextSha256
        rules_sha256 = $rulesSha256
        rules_file = $CommonRulesFile
        candidate_output_root = $CommonCandidateOutputRoot
        effect_mode = $expectedEffectMode
        output_contract_sha256 = $outputContractSha256
        capability_binding_sha256 = $capabilityBindingSha256
    }
}
$poolId = if ([string]::IsNullOrWhiteSpace($PoolId)) {
    "gwp_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
} else {
    $PoolId
}
if ($poolId -notmatch '^gwp_[0-9]{8}T[0-9]{6}_[0-9a-f]{8}$') {
    throw "GROK_WORKER_POOL_ID_INVALID: $poolId"
}
$poolDir = Join-Path $EvidenceRoot $poolId
New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
if (Test-Path -LiteralPath $poolDir) {
    throw "GROK_WORKER_POOL_ID_ALREADY_EXISTS: $poolId"
}
New-Item -ItemType Directory -Path $poolDir | Out-Null
$latest = Join-Path $EvidenceRoot "latest.json"

function Invoke-CommonAdapterProcess([string[]]$Arguments) {
    $priorPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($priorPythonPath)) {
            $CommonAdapterRoot
        } else {
            $CommonAdapterRoot + [IO.Path]::PathSeparator + $priorPythonPath
        }
        $adapterLines = @(& $CommonPythonExe @Arguments 2>&1)
        $adapterExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    } finally {
        $env:PYTHONPATH = $priorPythonPath
    }
    $adapterText = ($adapterLines | ForEach-Object { "$_" }) -join [Environment]::NewLine
    if ($adapterExit -ne 0) {
        throw "GROK_WORKER_POOL_COMMON_ADAPTER_FAILED: exit=$adapterExit output=$adapterText"
    }
    try { return ($adapterText | ConvertFrom-Json -ErrorAction Stop) }
    catch { throw "GROK_WORKER_POOL_COMMON_ADAPTER_INVALID_JSON: $adapterText" }
}

if ($commonMode -and -not [string]::IsNullOrWhiteSpace($CommonPriorAttemptReceiptPath)) {
    $reuseArgs = @(
        $commonAdapterScript,
        "--logical-contract", $CommonLogicalContractPath,
        "--subject-manifest-sha256", $CommonSubjectManifestSha256,
        "--frozen-context-sha256", $CommonFrozenContextSha256,
        "--phase", $CommonPhase,
        "--prior-attempt-receipt", $CommonPriorAttemptReceiptPath,
        "--classify-prior-only",
        "--output-root", $poolDir
    )
    foreach ($domain in @($CommonWriteDomains)) { $reuseArgs += @("--write-domain", [string]$domain) }
    foreach ($dependency in @($CommonDependsOn)) { $reuseArgs += @("--depends-on", [string]$dependency) }
    $reuse = Invoke-CommonAdapterProcess -Arguments $reuseArgs
    if ($reuse.ok -ne $true -or $reuse.skip_execution -ne $true -or $reuse.disposition -ne "ACCEPTED_IDENTICAL_REUSE") {
        throw "GROK_WORKER_POOL_COMMON_PRIOR_RECEIPT_NOT_REUSABLE"
    }
    $reuseSummary = [ordered]@{
        schema_version = "xinao.grok_worker_pool.v2"
        execution_contract_version = "xinao.grok.shared_execution_contract.v1"
        sentinel = "SENTINEL:GROK_WORKER_POOL"
        generated_at = (Get-Date).ToString("o")
        pool_id = $poolId
        n = 1
        model = $Model
        selection_path = $SelectionPath
        selection_decision_sha256 = [string]$selection.decision_sha256
        selected_provider_id = [string]$selection.provider_id
        selected_profile_ref = [string]$selection.profile_ref
        selected_transport_id = [string]$selection.transport_id
        cwd = $Cwd
        common_contract_mode = "provider_v1_then_common_adapter"
        common_contract_preflight = $commonPreflight
        common_phase = $CommonPhase
        common_write_domains = @($CommonWriteDomains)
        common_rules_file = $CommonRulesFile
        common_rules_sha256 = $CommonRulesSha256
        common_candidate_output_root = $CommonCandidateOutputRoot
        common_depends_on = @($CommonDependsOn)
        reuse_skipped_execution = $true
        reuse_disposition = $reuse
        outcome_counts = [ordered]@{ accepted = 0; rejected = 0; timeout = 0; incomplete = 0; reuse = 1 }
        usage = [ordered]@{
            provider_id = [string]$selection.provider_id
            profile_ref = [string]$selection.profile_ref
            transport_id = [string]$selection.transport_id
            model = $Model
            attempt_count = 0
            total_tokens = 0
        }
        usage_accounting_complete = $true
        all_ok = $false
        acceptance_contract_ok = $true
        pool_dir = $poolDir
        results = @()
        completion_claim_allowed = $false
        route_role = "normal_leg_a_bounded_online_current_tui"
        route_selection = "selected_by_task_fit_or_existing_route_receipt"
        route_continuity = "continuous_or_resume_does_not_switch_leg"
    }
    $reuseSummaryPath = Join-Path $poolDir "pool_summary.json"
    [System.IO.File]::WriteAllText($reuseSummaryPath, ($reuseSummary | ConvertTo-Json -Depth 12), $utf8)
    [System.IO.File]::WriteAllText($latest, ($reuseSummary | ConvertTo-Json -Depth 12), $utf8)
    if (-not $Quiet) { $reuseSummary | ConvertTo-Json -Depth 12 }
    exit 0
}

$workers = New-Object System.Collections.Generic.List[object]
$jobs = @()

for ($i = 0; $i -lt $N; $i++) {
    $lane = $i
    $laneDir = Join-Path $poolDir ("lane_{0:D2}" -f $lane)
    New-Item -ItemType Directory -Force -Path $laneDir | Out-Null
    $promptLane = Join-Path $laneDir "prompt.md"
    $lanePrompt = @"
[grok_worker_pool]
pool_id=$poolId
lane=$lane
n=$N
model=$Model
selection_decision_sha256=$($selection.decision_sha256)

$Prompt
"@
    [System.IO.File]::WriteAllText($promptLane, $lanePrompt, $utf8)

    # Each lane: separate process CreateNoWindow via worker script (sync wait inside job would flash job host).
    # Use runspace + call worker -Quiet so N workers run truly parallel without Start-Job conhost.
    $rs = [runspacefactory]::CreateRunspace()
    $rs.Open()
    $ps = [powershell]::Create()
    $ps.Runspace = $rs
    $script = {
        param(
            $WorkerScript, $PromptFile, $Cwd, $Model, $MaxTurns, $GrokHome,
            $EvidenceDir, $MinChars, $Markers, $RequireJson, $JsonSchemaPath, $TimeoutSec,
            $RulesFile, $RulesSha256
        )
        $ErrorActionPreference = "Continue"
        $workerArgs = @{
            PromptFile = $PromptFile
            Cwd = $Cwd
            Model = $Model
            MaxTurns = $MaxTurns
            GrokHome = $GrokHome
            EvidenceDir = $EvidenceDir
            MinResultChars = $MinChars
            RequiredResultMarkers = @($Markers)
            TimeoutSec = $TimeoutSec
            RulesFile = $RulesFile
            RulesSha256 = $RulesSha256
            Quiet = $true
        }
        if ($RequireJson) { $workerArgs.RequireJsonObject = $true }
        if ($JsonSchemaPath) { $workerArgs.JsonSchemaPath = $JsonSchemaPath }
        & $WorkerScript @workerArgs
        return @{
            exit_code = $LASTEXITCODE
            evidence_dir = $EvidenceDir
        }
    }
    [void]$ps.AddScript($script).AddArgument($workerScript).AddArgument($promptLane).AddArgument($Cwd).AddArgument($Model).AddArgument($MaxTurns).AddArgument($GrokHome).AddArgument($laneDir).AddArgument($MinResultChars).AddArgument(@($RequiredResultMarkers)).AddArgument([bool]$RequireJsonObject).AddArgument($JsonSchemaPath).AddArgument($TimeoutSec).AddArgument($CommonRulesFile).AddArgument($CommonRulesSha256)
    $handle = $ps.BeginInvoke()
    $jobs += [pscustomobject]@{
        lane   = $lane
        ps     = $ps
        rs     = $rs
        handle = $handle
        dir    = $laneDir
        started_at = (Get-Date).ToString("o")
    }
    $workers.Add([ordered]@{
        lane = $lane
        evidence_dir = $laneDir
        prompt_file = $promptLane
        status = "started"
    }) | Out-Null
}

$deadline = (Get-Date).AddSeconds($TimeoutSec + 30)
$results = @()
foreach ($j in $jobs) {
    $remaining = [math]::Max(1, ($deadline - (Get-Date)).TotalMilliseconds)
    $ok = $j.handle.AsyncWaitHandle.WaitOne([int]$remaining)
    $item = [ordered]@{
        lane = $j.lane
        evidence_dir = $j.dir
        timed_out = (-not $ok)
    }
    if ($ok) {
        try {
            $out = $j.ps.EndInvoke($j.handle)
            $item.exit_code = $out.exit_code
            $item.status = if ($out.exit_code -eq 0) { "ok" } else { "failed" }
            $item.raw = $out
        } catch {
            $item.status = "invoke_error"
            $item.error = "$_"
        }
    } else {
        $item.status = "timeout"
        $laneLatest = Join-Path $j.dir "latest.json"
        if (Test-Path -LiteralPath $laneLatest) {
            try {
                $pending = Get-Content -LiteralPath $laneLatest -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($pending.pid) {
                    $item.outer_terminated_process_ids = @(Stop-ExactProcessTree -RootProcessId ([int]$pending.pid))
                }
            } catch { }
        }
        try { $j.ps.Stop() } catch { }
    }
    try { $j.ps.Dispose() } catch { }
    try { $j.rs.Close(); $j.rs.Dispose() } catch { }

    # Pull lane latest meta if any
    $laneLatest = Join-Path $j.dir "latest.json"
    if (-not (Test-Path -LiteralPath $laneLatest)) {
        $cand = Get-ChildItem -LiteralPath $j.dir -Filter "c25_*.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($cand) { $laneLatest = $cand.FullName }
    }
    if (Test-Path -LiteralPath $laneLatest) {
        $item.meta_path = $laneLatest
        try {
            $m = Get-Content -LiteralPath $laneLatest -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($commonMode) {
                $observedRulesSha256 = [string]$m.observed_rules_sha256
                $rulesIdentityOk = [string]::Equals(
                    $observedRulesSha256,
                    $CommonRulesSha256,
                    [StringComparison]::Ordinal
                )
                $m | Add-Member -NotePropertyName "observed_capability_binding_sha256" -NotePropertyValue ([string]$commonPreflight.capability_binding_sha256) -Force
                $m | Add-Member -NotePropertyName "common_contract_preflight" -NotePropertyValue ([pscustomobject]$commonPreflight) -Force
                $m | Add-Member -NotePropertyName "expected_rules_sha256" -NotePropertyValue $CommonRulesSha256 -Force
                $m | Add-Member -NotePropertyName "rules_identity_ok" -NotePropertyValue $rulesIdentityOk -Force
                if (-not $rulesIdentityOk) {
                    $m.status = "rejected"
                    $m.effective_output_accepted = $false
                    $m | Add-Member -NotePropertyName "contract_failure" -NotePropertyValue "GROK_WORKER_POOL_OBSERVED_RULES_MISMATCH" -Force
                }
                [System.IO.File]::WriteAllText(
                    $laneLatest,
                    ($m | ConvertTo-Json -Depth 20),
                    $utf8
                )
            }
            $item.run_id = $m.run_id
            $item.pid = $m.pid
            $item.worker_status = $m.status
            $item.create_no_window = $m.create_no_window
            $item.effective_output_accepted = $m.effective_output_accepted -eq $true
            $item.requested_model = [string]$m.requested_model
            $item.observed_models = @($m.observed_models)
            $item.observed_backend_models = @($m.observed_backend_models)
            $item.observed_session_models = @($m.observed_session_models)
            $item.session_model = [string]$m.session_model
            $item.backend_model_identity_ok = $m.backend_model_identity_ok -eq $true
            $item.session_model_identity_ok = $m.session_model_identity_ok -eq $true
            $item.session_turn_model_identity_ok = $m.session_turn_model_identity_ok -eq $true
            $item.session_evidence_ok = $m.session_evidence_ok -eq $true
            $item.model_identity_ok = $m.model_identity_ok -eq $true
            $item.stop_reason = [string]$m.stop_reason
            $item.usage = $m.usage
            $item.usage_is_incomplete = $m.usage_is_incomplete -eq $true
            $item.usage_accounting_complete = $m.usage_accounting_complete -eq $true
            $item.result_text_chars = [int]$m.result_text_chars
            $item.max_turns_cli_applied = $m.max_turns_cli_applied -eq $true
            $item.worker_timed_out = $m.timed_out -eq $true
            $item.json_schema_path = [string]$m.json_schema_path
            $item.json_schema_source_path = [string]$m.json_schema_source_path
            $item.json_schema_snapshot_path = [string]$m.json_schema_snapshot_path
            $item.json_schema_sha256 = [string]$m.json_schema_sha256
            $item.json_schema_expected_sha256 = [string]$m.json_schema_expected_sha256
            $item.json_schema_observed_sha256 = [string]$m.json_schema_observed_sha256
            $item.json_schema_validator = [string]$m.json_schema_validator
            $item.schema_instance_valid = $m.schema_instance_valid -eq $true
            $item.effective_output_source = [string]$m.effective_output_source
            $item.structured_output_present = $m.structured_output_present -eq $true
            if ($commonMode) {
                $item.observed_capability_binding_sha256 = [string]$m.observed_capability_binding_sha256
                $item.observed_rules_sha256 = [string]$m.observed_rules_sha256
                $item.expected_rules_sha256 = [string]$m.expected_rules_sha256
                $item.rules_identity_ok = $m.rules_identity_ok -eq $true
                $item.common_contract_preflight = $m.common_contract_preflight
            }
            $item.status = if ($item.timed_out -or $item.worker_timed_out) {
                "timeout"
            } elseif (
                $item.exit_code -eq 0 -and
                $item.worker_status -eq "accepted" -and
                $item.effective_output_accepted -and
                (-not $commonMode -or $item.rules_identity_ok)
            ) { "accepted" } else { "rejected" }
        } catch { }
    }
    $item.provider_id = [string]$selection.provider_id
    $item.profile_ref = [string]$selection.profile_ref
    $item.transport_id = [string]$selection.transport_id
    $item.model = $Model
    $results += [pscustomobject]$item
}

$accounting = Get-GrokWorkerPoolUsageAccounting `
    -Results @($results) -Selection $selection -Model $Model
$okCount = [int]$accounting.outcome_counts.accepted
$summary = [ordered]@{
    schema_version = "xinao.grok_worker_pool.v2"
    execution_contract_version = "xinao.grok.shared_execution_contract.v1"
    sentinel = "SENTINEL:GROK_WORKER_POOL"
    generated_at = (Get-Date).ToString("o")
    pool_id = $poolId
    hot_path_cn = "Codex->N Grok headless workers (CREATE_NO_WINDOW)"
    not_cn = @(
        "visible TUI typeahead inject as default",
        "Docker integrated_bus reading Desktop .lnk",
        "Dify docker-worker-1"
    )
    n = $N
    model = $Model
    selection_path = $SelectionPath
    selection_decision_sha256 = [string]$selection.decision_sha256
    selected_provider_id = [string]$selection.provider_id
    selected_profile_ref = [string]$selection.profile_ref
    selected_transport_id = [string]$selection.transport_id
    cwd = $Cwd
    max_turns = $MaxTurns
    timeout_sec = $TimeoutSec
    min_result_chars = $MinResultChars
    required_result_markers = @($RequiredResultMarkers)
    require_json_object = [bool]($RequireJsonObject -or -not [string]::IsNullOrWhiteSpace($JsonSchemaPath))
    json_schema_path = $JsonSchemaPath
    ok_count = $okCount
    fail_count = [int]$accounting.fail_count
    outcome_counts = $accounting.outcome_counts
    usage = $accounting.usage
    usage_accounting_complete = $accounting.usage_accounting_complete
    all_ok = ($okCount -eq $N)
    acceptance_contract_ok = (($okCount -eq $N) -and -not $commonMode)
    pool_dir = $poolDir
    results = $results
    completion_claim_allowed = $false
    route_role = "normal_leg_a_bounded_online_current_tui"
    route_selection = "selected_by_task_fit_or_existing_route_receipt"
    route_continuity = "continuous_or_resume_does_not_switch_leg"
    invoke_cn = ".\Invoke-GrokWorkerPool.ps1 -N $N -Prompt '...' -Cwd '<explicit>' -Model '$Model' -SelectionPath '<decision-receipt.json>' -MaxTurns auto"
}
if ($commonMode) {
    $summary["common_contract_mode"] = "provider_v1_then_common_adapter"
    $summary["common_contract_preflight"] = $commonPreflight
    $summary["common_phase"] = $CommonPhase
    $summary["common_write_domains"] = @($CommonWriteDomains)
    $summary["common_rules_file"] = $CommonRulesFile
    $summary["common_rules_sha256"] = $CommonRulesSha256
    $summary["common_candidate_output_root"] = $CommonCandidateOutputRoot
    $summary["common_depends_on"] = @($CommonDependsOn)
    $summary["reuse_skipped_execution"] = $false
    $summary["common_adapter_ok"] = $false
}

$summaryPath = Join-Path $poolDir "pool_summary.json"
[System.IO.File]::WriteAllText($summaryPath, ($summary | ConvertTo-Json -Depth 10), $utf8)
[System.IO.File]::WriteAllText($latest, ($summary | ConvertTo-Json -Depth 10), $utf8)

if ($commonMode -and $okCount -eq $N) {
    try {
        $postArgs = @(
            $commonAdapterScript,
            "--logical-contract", $CommonLogicalContractPath,
            "--subject-manifest-sha256", $CommonSubjectManifestSha256,
            "--frozen-context-sha256", $CommonFrozenContextSha256,
            "--phase", $CommonPhase,
            "--pool-summary", $summaryPath,
            "--lane-index", "0",
            "--attempt", "1",
            "--output-root", ([string]$results[0].evidence_dir)
        )
        foreach ($domain in @($CommonWriteDomains)) { $postArgs += @("--write-domain", [string]$domain) }
        foreach ($dependency in @($CommonDependsOn)) { $postArgs += @("--depends-on", [string]$dependency) }
        $commonAdapterResult = Invoke-CommonAdapterProcess -Arguments $postArgs
        $commonReceiptPath = Join-Path ([string]$results[0].evidence_dir) "common_adapter_receipt.json"
        if (-not (Test-Path -LiteralPath $commonReceiptPath -PathType Leaf)) {
            throw "GROK_WORKER_POOL_COMMON_RECEIPT_MISSING: $commonReceiptPath"
        }
        $commonReceipt = Get-Content -LiteralPath $commonReceiptPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
        if (
            $commonReceipt.authority -ne $false -or
            $commonReceipt.completion_claim_allowed -ne $false -or
            $commonReceipt.common_receipt_accepted -ne $true
        ) {
            throw "GROK_WORKER_POOL_COMMON_RECEIPT_REJECTED"
        }
        $summary["common_adapter_ok"] = $true
        $summary["common_adapter_result"] = $commonAdapterResult
        $summary["common_adapter_receipt_path"] = $commonReceiptPath
        $summary["common_adapter_receipt_sha256"] =
            (Get-FileHash -LiteralPath $commonReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $summary["acceptance_contract_ok"] = $true
    } catch {
        $summary["common_adapter_error"] = "$_"
        $summary["acceptance_contract_ok"] = $false
    }
    [System.IO.File]::WriteAllText($summaryPath, ($summary | ConvertTo-Json -Depth 14), $utf8)
    [System.IO.File]::WriteAllText($latest, ($summary | ConvertTo-Json -Depth 14), $utf8)
}

$zhDir = "D:\XINAO_RESEARCH_RUNTIME\readback\zh"
New-Item -ItemType Directory -Force -Path $zhDir | Out-Null
$zh = @"
# Grok worker pool $poolId

- hot_path: Codex -> N Grok headless (CREATE_NO_WINDOW)
- n=$N ok=$okCount fail=$($N - $okCount) all_ok=$($okCount -eq $N)
- model=$Model
- pool_dir=$poolDir
- latest=$latest
- completion_claim_allowed=false

## lanes
$($results | ForEach-Object { "- lane=$($_.lane) status=$($_.status) exit=$($_.exit_code) pid=$($_.pid)" } | Out-String)
"@
$zhPath = Join-Path $zhDir "grok_worker_pool_latest.md"
[System.IO.File]::WriteAllText($zhPath, $zh, $utf8)

if (-not $Quiet) {
    $summary | ConvertTo-Json -Depth 10
}

if ($summary.acceptance_contract_ok -eq $true) {
    exit 0
} elseif ($commonMode -and $okCount -eq $N) {
    exit 3
} else {
    exit 2
}
