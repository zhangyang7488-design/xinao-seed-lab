#Requires -Version 5.1
param()

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$helper = Join-Path $bridge "GrokWorkerSelectionReceipt.ps1"
$resolver = Join-Path $bridge "resolve_grok_worker_selection_receipt.py"
$dispatch = Join-Path $bridge "Invoke-CodexDispatchGrokWorkerPool.ps1"
$pool = Join-Path $bridge "Invoke-GrokWorkerPool.ps1"
$temporalHost = Join-Path $bridge "Invoke-GrokHostWorkerPoolFromTemporal.ps1"
$temporalAlias = Join-Path $bridge "Invoke-GrokTemporalHostPoolTrigger.ps1"
$thinLauncher = "C:\Users\xx363\CodexLaunchers\Invoke-Codex-GrokWorkerPool.ps1"
$pwsh = (Get-Process -Id $PID).Path

function Assert-True([bool]$Condition, [string]$Label) {
    if (-not $Condition) { throw "ASSERT_FAIL: $Label" }
}

function New-TestReceipt {
    param(
        [string]$Field = "",
        [string]$Value = "",
        [string]$DecisionSha256 = "ad76b3d15a404a8b724d1f2231ae67759c909c85ea28855e111e5eaa12acfc2b"
    )
    $candidate = [ordered]@{
        provider_id = "grok_acpx_headless"
        profile_ref = "grok.com.cached_profile"
        model_id = "grok-4.5"
        transport_id = "direct-grok-worker-pool"
        declared_active = $true
        healthy = $true
        positive_benefit = $true
        context_capable = $false
    }
    if ($Field) { $candidate[$Field] = $Value }
    return [ordered]@{
        schema_version = "xinao.supervisor_worker_decision_receipt.v1"
        decision = "selected"
        selected_candidate = $candidate
        eligible_candidates = @()
        excluded_reasons = @()
        decision_reason = "explicit_supervisor_choice"
        policy_ref = "D:\XINAO_RESEARCH_RUNTIME\agent_runtime\routing_policy.json"
        policy_sha256 = ("a" * 64)
        policy_version = "xinao.routing-policy.v4-positive-benefit-dynamic"
        decision_sha256 = $DecisionSha256
    }
}

function Write-JsonFile([string]$Path, [object]$Value) {
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 12), $utf8)
}

function Invoke-FreshPowerShell([string[]]$Arguments) {
    $output = @(& $pwsh -NoLogo -NoProfile @Arguments 2>&1 | ForEach-Object { [string]$_ })
    return [pscustomobject]@{
        exit_code = $LASTEXITCODE
        output = ($output -join "`n")
    }
}

Assert-True (Test-Path -LiteralPath $helper -PathType Leaf) "selection_helper_present"
Assert-True (Test-Path -LiteralPath $resolver -PathType Leaf) "selection_resolver_present"
Assert-True (Test-Path -LiteralPath $dispatch -PathType Leaf) "dispatch_present"
Assert-True (Test-Path -LiteralPath $pool -PathType Leaf) "pool_present"
Assert-True (Test-Path -LiteralPath $temporalHost -PathType Leaf) "temporal_host_present"
Assert-True (Test-Path -LiteralPath $temporalAlias -PathType Leaf) "temporal_alias_present"
Assert-True (Test-Path -LiteralPath $thinLauncher -PathType Leaf) "thin_launcher_present"
. $helper

$root = Join-Path ([IO.Path]::GetTempPath()) ("grok-selection-contract-" + [guid]::NewGuid().ToString("N"))
$tempBridge = Join-Path $root "bridge"
$dispatchLatest = "D:\XINAO_RESEARCH_RUNTIME\state\codex_dispatch_grok_worker_pool\latest.json"
$dispatchLatestExisted = Test-Path -LiteralPath $dispatchLatest -PathType Leaf
$dispatchLatestBytes = if ($dispatchLatestExisted) { [IO.File]::ReadAllBytes($dispatchLatest) } else { $null }
New-Item -ItemType Directory -Force -Path $tempBridge | Out-Null

try {
    Copy-Item -LiteralPath $helper -Destination $tempBridge
    Copy-Item -LiteralPath $resolver -Destination $tempBridge
    Copy-Item -LiteralPath $dispatch -Destination $tempBridge

    $stubPool = @'
param(
    [int]$N,
    [string]$Prompt,
    [string]$PromptFile,
    [string]$Cwd,
    [string]$Model,
    [string]$SelectionPath,
    [string]$ExpectedSelectionDecisionSha256,
    [string]$MaxTurns,
    [int]$TimeoutSec,
    [string]$GrokHome,
    [int]$MinResultChars,
    [string[]]$RequiredResultMarkers,
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath,
    [string]$PoolId,
    [switch]$SkipPauseGate,
    [switch]$Quiet
)
$record = [ordered]@{
    model = $Model
    cwd = $Cwd
    selection_path = $SelectionPath
    expected_selection_decision_sha256 = $ExpectedSelectionDecisionSha256
    pool_id = $PoolId
}
[IO.File]::WriteAllText(
    $env:XINAO_GROK_SELECTION_STUB_CALL,
    ($record | ConvertTo-Json -Depth 4),
    (New-Object Text.UTF8Encoding $false)
)
$poolDir = Join-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool" $PoolId
New-Item -ItemType Directory -Force -Path $poolDir | Out-Null
[IO.File]::WriteAllText(
    (Join-Path $poolDir "pool_summary.json"),
    (([ordered]@{
        pool_id = $PoolId
        all_ok = $true
        acceptance_contract_ok = $true
        model = $Model
        cwd = $Cwd
        selection_decision_sha256 = $ExpectedSelectionDecisionSha256
        selected_provider_id = "grok_acpx_headless"
        selected_profile_ref = "grok.com.cached_profile"
        selected_transport_id = "direct-grok-worker-pool"
    }) | ConvertTo-Json),
    (New-Object Text.UTF8Encoding $false)
)
$global:LASTEXITCODE = 0
'@
    [IO.File]::WriteAllText(
        (Join-Path $tempBridge "Invoke-GrokWorkerPool.ps1"),
        $stubPool,
        $utf8
    )

    $validReceipt = Join-Path $root "valid.json"
    Write-JsonFile $validReceipt (New-TestReceipt)
    $stubCall = Join-Path $root "stub-call.json"
    $env:XINAO_GROK_SELECTION_STUB_CALL = $stubCall
    $selectionProbe = Join-Path $root "selection-probe.ps1"
    [IO.File]::WriteAllText(
        $selectionProbe,
        @'
param([string]$Command)
if ($Command -ne "models") { exit 7 }
Write-Output "- grok-4.5"
exit 0
'@,
        $utf8
    )

    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $dispatchId = "cdx_20000101T000000_$suffix"
    $poolId = "gwp_20000101T000000_$suffix"
    $dispatchMeta = "D:\XINAO_RESEARCH_RUNTIME\state\codex_dispatch_grok_worker_pool\$dispatchId.json"
    $poolDir = "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool\$poolId"

    $launcherCopy = Join-Path $root "Invoke-Codex-GrokWorkerPool.ps1"
    $launcherText = Get-Content -LiteralPath $thinLauncher -Raw
    $launcherText = $launcherText.Replace(
        "C:\Users\xx363\Grok_Admin_Isolated\workspace\grok-admin-bridge\Invoke-CodexDispatchGrokWorkerPool.ps1",
        (Join-Path $tempBridge "Invoke-CodexDispatchGrokWorkerPool.ps1")
    )
    [IO.File]::WriteAllText($launcherCopy, $launcherText, $utf8)

    $positive = Invoke-FreshPowerShell @(
        "-File", $launcherCopy,
        "-N", "1",
        "-Prompt", "fixture-only",
        "-Cwd", $root,
        "-Model", "grok-4.5",
        "-SelectionPath", $validReceipt,
        "-DispatchId", $dispatchId,
        "-PoolId", $poolId,
        "-Quiet"
    )
    Assert-True ($positive.exit_code -eq 0) ("valid_receipt_fresh_process: " + $positive.output)
    Assert-True (Test-Path -LiteralPath $stubCall -PathType Leaf) "valid_receipt_reaches_stub_pool"
    $call = Get-Content -LiteralPath $stubCall -Raw | ConvertFrom-Json
    Assert-True ([string]$call.model -eq "grok-4.5") "selected_model_forwarded_exactly"
    Assert-True ([IO.Path]::GetFullPath([string]$call.cwd) -eq [IO.Path]::GetFullPath($root)) "explicit_cwd_forwarded_exactly"
    Assert-True ([IO.Path]::GetFullPath([string]$call.selection_path) -eq [IO.Path]::GetFullPath($validReceipt)) "selection_path_forwarded_exactly"
    Assert-True ([string]$call.expected_selection_decision_sha256 -eq "ad76b3d15a404a8b724d1f2231ae67759c909c85ea28855e111e5eaa12acfc2b") "decision_hash_bound_to_pool"

    Remove-Item -LiteralPath $stubCall -Force
    $autoSuffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $autoDispatch = "cdx_20000101T000000_$autoSuffix"
    $autoPool = "gwp_20000101T000000_$autoSuffix"
    $autoDispatchMeta = "D:\XINAO_RESEARCH_RUNTIME\state\codex_dispatch_grok_worker_pool\$autoDispatch.json"
    $autoPoolDir = "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool\$autoPool"
    $autoSelectionDir = "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_selection\$autoDispatch"
    $auto = Invoke-FreshPowerShell @(
        "-File", (Join-Path $tempBridge "Invoke-CodexDispatchGrokWorkerPool.ps1"),
        "-N", "1",
        "-Prompt", "fixture-only",
        "-Cwd", $root,
        "-Model", "grok-4.5",
        "-SelectionProbeGrokExe", $selectionProbe,
        "-SupervisorRoot", "D:\XINAO_RESEARCH_RUNTIME\worktrees\s-origin-main-20260717",
        "-RuntimeRoot", "D:\XINAO_RESEARCH_RUNTIME",
        "-DispatchId", $autoDispatch,
        "-PoolId", $autoPool,
        "-Quiet"
    )
    Assert-True ($auto.exit_code -eq 0) ("automatic_selection_fresh_process: " + $auto.output)
    Assert-True (Test-Path -LiteralPath $stubCall -PathType Leaf) "automatic_selection_reaches_stub_pool"
    $autoCall = Get-Content -LiteralPath $stubCall -Raw | ConvertFrom-Json
    $autoReceipt = Join-Path $autoSelectionDir "selection.receipt.json"
    Assert-True (Test-Path -LiteralPath $autoReceipt -PathType Leaf) "automatic_selection_receipt_created"
    Assert-True ([IO.Path]::GetFullPath([string]$autoCall.selection_path) -eq [IO.Path]::GetFullPath($autoReceipt)) "automatic_selection_receipt_forwarded"
    Assert-True ([string]$autoCall.expected_selection_decision_sha256 -match '^[0-9a-f]{64}$') "automatic_selection_hash_bound"

    Remove-Item -LiteralPath $stubCall -Force
    $datedReceipt = New-TestReceipt
    $datedReceipt["provider_preference"] = [ordered]@{
        strategy = "stable_default_reconciled_with_current_capacity"
        capacity_signals = @(
            [ordered]@{
                provider_id = "codex_subagent"
                remaining_percent = 15.0
                reset_at = "2026-07-23T09:14:29.000Z"
            },
            [ordered]@{
                provider_id = "grok_acpx_headless"
                remaining_percent = 94.0
                reset_at = "2026-07-19T02:52:23.712Z"
            }
        )
    }
    $datedReceipt.Remove("decision_sha256")
    $datedCanonical = ConvertTo-GrokCanonicalJson $datedReceipt
    Assert-True ($datedCanonical -match '"remaining_percent":15\.0') (
        "whole_float_matches_python_json_number_shape"
    )
    $datedReceipt["decision_sha256"] = Get-GrokUtf8Sha256Hex $datedCanonical
    $datedReceiptPath = Join-Path $root "dated-capacity.json"
    Write-JsonFile $datedReceiptPath $datedReceipt
    $datedSuffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $datedDispatch = "cdx_20000101T000000_$datedSuffix"
    $datedPool = "gwp_20000101T000000_$datedSuffix"
    $datedResult = Invoke-FreshPowerShell @(
        "-File", $launcherCopy,
        "-N", "1",
        "-Prompt", "fixture-only",
        "-Cwd", $root,
        "-Model", "grok-4.5",
        "-SelectionPath", $datedReceiptPath,
        "-DispatchId", $datedDispatch,
        "-PoolId", $datedPool,
        "-Quiet"
    )
    Assert-True ($datedResult.exit_code -eq 0) (
        "dated_capacity_receipt_fresh_process: " + $datedResult.output
    )
    Assert-True (Test-Path -LiteralPath $stubCall -PathType Leaf) (
        "dated_capacity_receipt_reaches_stub_pool"
    )
    Remove-Item -LiteralPath $stubCall -Force
    $negativeCases = @(
        [pscustomobject]@{
            name = "hash_mismatch"
            receipt = (New-TestReceipt -DecisionSha256 ("0" * 64))
            expected = "GROK_SELECTION_DECISION_HASH_MISMATCH"
        },
        [pscustomobject]@{
            name = "provider_mismatch"
            receipt = (New-TestReceipt -Field "provider_id" -Value "other" -DecisionSha256 "c8e7c62f6c03ae3ec8c1462a7f0496b9eef2fc3af138d6f483bb04ebdd74269b")
            expected = "GROK_SELECTION_PROVIDER_MISMATCH"
        },
        [pscustomobject]@{
            name = "profile_mismatch"
            receipt = (New-TestReceipt -Field "profile_ref" -Value "other" -DecisionSha256 "914dc1561251d537bdef0d5a4330fe99b1ae886339a42849e89035afbf0fa179")
            expected = "GROK_SELECTION_PROFILE_MISMATCH"
        },
        [pscustomobject]@{
            name = "transport_mismatch"
            receipt = (New-TestReceipt -Field "transport_id" -Value "other" -DecisionSha256 "0822ea0753e9b2caf00a39a946fe92bea35efe30c957462cd6c7e83788e533df")
            expected = "GROK_SELECTION_TRANSPORT_MISMATCH"
        },
        [pscustomobject]@{
            name = "model_mismatch"
            receipt = (New-TestReceipt -Field "model_id" -Value "grok-composer-2.5-fast" -DecisionSha256 "41c4aef83702724613f8746720f641d98a05caeff04916951230ceab48fb867e")
            expected = "GROK_SELECTION_MODEL_MISMATCH"
        }
    )
    foreach ($case in $negativeCases) {
        $receiptPath = Join-Path $root ($case.name + ".json")
        Write-JsonFile $receiptPath $case.receipt
        $caseSuffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
        $caseDispatch = "cdx_20000101T000000_$caseSuffix"
        $casePool = "gwp_20000101T000000_$caseSuffix"
        $caseMeta = "D:\XINAO_RESEARCH_RUNTIME\state\codex_dispatch_grok_worker_pool\$caseDispatch.json"
        $result = Invoke-FreshPowerShell @(
            "-File", (Join-Path $tempBridge "Invoke-CodexDispatchGrokWorkerPool.ps1"),
            "-N", "1",
            "-Prompt", "fixture-only",
            "-Cwd", $root,
            "-Model", "grok-4.5",
            "-SelectionPath", $receiptPath,
            "-DispatchId", $caseDispatch,
            "-PoolId", $casePool,
            "-Quiet"
        )
        Assert-True ($result.exit_code -ne 0) ($case.name + "_must_fail")
        Assert-True ($result.output -match [regex]::Escape($case.expected)) ($case.name + "_reason")
        Assert-True (-not (Test-Path -LiteralPath $stubCall)) ($case.name + "_fails_before_pool")
        Assert-True (-not (Test-Path -LiteralPath $caseMeta)) ($case.name + "_fails_before_dispatch_meta")
    }

    foreach ($missing in @("Model", "Cwd")) {
        $caseSuffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
        $argList = [Collections.Generic.List[string]]::new()
        foreach ($value in @(
            "-File", (Join-Path $tempBridge "Invoke-CodexDispatchGrokWorkerPool.ps1"),
            "-N", "1", "-Prompt", "fixture-only",
            "-Cwd", $root, "-Model", "grok-4.5", "-SelectionPath", $validReceipt,
            "-DispatchId", "cdx_20000101T000000_$caseSuffix",
            "-PoolId", "gwp_20000101T000000_$caseSuffix", "-Quiet"
        )) { [void]$argList.Add($value) }
        $parameterIndex = $argList.IndexOf("-$missing")
        $argList.RemoveAt($parameterIndex + 1)
        $argList.RemoveAt($parameterIndex)
        $result = Invoke-FreshPowerShell $argList.ToArray()
        Assert-True ($result.exit_code -ne 0) ("missing_" + $missing + "_must_fail")
        Assert-True ($result.output -match ("CODEX_GROK_" + $missing.ToUpperInvariant() + "_REQUIRED")) ("missing_" + $missing + "_reason")
        Assert-True (-not (Test-Path -LiteralPath $stubCall)) ("missing_" + $missing + "_fails_before_pool")
    }

    $unhealthySuffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $unhealthy = Invoke-FreshPowerShell @(
        "-File", (Join-Path $tempBridge "Invoke-CodexDispatchGrokWorkerPool.ps1"),
        "-N", "1", "-Prompt", "fixture-only",
        "-Cwd", $root, "-Model", "grok-not-observed",
        "-SelectionProbeGrokExe", $selectionProbe,
        "-DispatchId", "cdx_20000101T000000_$unhealthySuffix",
        "-PoolId", "gwp_20000101T000000_$unhealthySuffix", "-Quiet"
    )
    Assert-True ($unhealthy.exit_code -ne 0) "automatic_selection_unhealthy_model_must_fail"
    Assert-True ($unhealthy.output -match "CODEX_GROK_SELECTED_MODEL_UNHEALTHY") "automatic_selection_unhealthy_reason"
    Assert-True (-not (Test-Path -LiteralPath $stubCall)) "automatic_selection_unhealthy_fails_before_pool"

    $changedSuffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $changedDispatch = "cdx_20000101T000000_$changedSuffix"
    $changedMeta = "D:\XINAO_RESEARCH_RUNTIME\state\codex_dispatch_grok_worker_pool\$changedDispatch.json"
    $changed = Invoke-FreshPowerShell @(
        "-File", (Join-Path $tempBridge "Invoke-CodexDispatchGrokWorkerPool.ps1"),
        "-N", "1", "-Prompt", "fixture-only",
        "-Cwd", $root, "-Model", "grok-4.5", "-SelectionPath", $validReceipt,
        "-ExpectedSelectionDecisionSha256", ("0" * 64),
        "-DispatchId", $changedDispatch,
        "-PoolId", "gwp_20000101T000000_$changedSuffix", "-Quiet"
    )
    Assert-True ($changed.exit_code -ne 0) "dispatch_rejects_changed_decision"
    Assert-True ($changed.output -match "CODEX_GROK_SELECTION_DECISION_CHANGED") "dispatch_changed_decision_reason"
    Assert-True (-not (Test-Path -LiteralPath $stubCall)) "dispatch_changed_decision_fails_before_pool"
    Assert-True (-not (Test-Path -LiteralPath $changedMeta)) "dispatch_changed_decision_fails_before_meta"

    $directPoolRoot = Join-Path $root "direct-pool-evidence"
    $directPool = Invoke-FreshPowerShell @(
        "-File", $pool,
        "-N", "1", "-Prompt", "fixture-only",
        "-Cwd", $root, "-Model", "grok-4.5",
        "-EvidenceRoot", $directPoolRoot,
        "-PoolId", "gwp_20000101T000000_1234abcd",
        "-Quiet"
    )
    Assert-True ($directPool.exit_code -ne 0) "direct_pool_requires_selection"
    Assert-True ($directPool.output -match "GROK_WORKER_POOL_SELECTIONPATH_REQUIRED") "direct_pool_missing_selection_reason"
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $directPoolRoot "gwp_20000101T000000_1234abcd"))) "direct_pool_fails_before_evidence_or_worker"
    $directChanged = Invoke-FreshPowerShell @(
        "-File", $pool,
        "-N", "1", "-Prompt", "fixture-only",
        "-Cwd", $root, "-Model", "grok-4.5", "-SelectionPath", $validReceipt,
        "-ExpectedSelectionDecisionSha256", ("0" * 64),
        "-EvidenceRoot", $directPoolRoot,
        "-PoolId", "gwp_20000101T000000_5678abcd",
        "-Quiet"
    )
    Assert-True ($directChanged.exit_code -ne 0) "direct_pool_rejects_changed_decision"
    Assert-True ($directChanged.output -match "GROK_WORKER_POOL_SELECTION_DECISION_CHANGED") "direct_pool_changed_decision_reason"
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $directPoolRoot "gwp_20000101T000000_5678abcd"))) "direct_pool_changed_decision_fails_before_evidence_or_worker"

    $hostNegative = Invoke-FreshPowerShell @(
        "-File", $temporalHost,
        "-N", "1", "-Prompt", "fixture-only",
        "-Cwd", $root, "-Model", "grok-4.5", "-Quiet"
    )
    Assert-True ($hostNegative.exit_code -ne 0) "temporal_host_requires_selection"
    Assert-True ($hostNegative.output -match "TEMPORAL_HOST_GROK_SELECTIONPATH_REQUIRED") "temporal_host_missing_selection_reason"
    $aliasNegative = Invoke-FreshPowerShell @(
        "-File", $temporalAlias,
        "-N", "1", "-Prompt", "fixture-only",
        "-Cwd", $root, "-Model", "grok-4.5", "-Quiet"
    )
    Assert-True ($aliasNegative.exit_code -ne 0) "temporal_alias_requires_selection"
    Assert-True ($aliasNegative.output -match "TEMPORAL_HOST_GROK_SELECTIONPATH_REQUIRED") "temporal_alias_missing_selection_reason"

    $dispatchText = Get-Content -LiteralPath $dispatch -Raw
    $poolText = Get-Content -LiteralPath $pool -Raw
    $temporalHostText = Get-Content -LiteralPath $temporalHost -Raw
    $temporalAliasText = Get-Content -LiteralPath $temporalAlias -Raw
    $thinText = Get-Content -LiteralPath $thinLauncher -Raw
    foreach ($entry in ([ordered]@{
        dispatch = $dispatchText
        pool = $poolText
        temporal_host = $temporalHostText
        temporal_alias = $temporalAliasText
        thin = $thinText
    }).GetEnumerator()) {
        Assert-True ($entry.Value -notmatch '\[string\]\$Model\s*=\s*"grok-composer-2[.]5-fast"') ($entry.Key + "_has_no_default_composer")
        Assert-True ($entry.Value -notmatch 'if\s*\(-not\s+\$Cwd\)\s*\{\s*\$Cwd\s*=\s*\(Get-Location\)') ($entry.Key + "_has_no_get_location_cwd")
        Assert-True ($entry.Value -match '\[string\]\$SelectionPath') ($entry.Key + "_accepts_selection_path")
    }
    Assert-True ($thinText -match 'SelectionPath\s*=\s*\$SelectionPath') "thin_launcher_forwards_selection_path"
    Assert-True ($temporalHostText -match 'SelectionPath\s*=\s*\$SelectionPath') "temporal_host_forwards_selection_path"
    Assert-True ($temporalAliasText -match 'SelectionPath\s*=\s*\$SelectionPath') "temporal_alias_forwards_selection_path"

    [ordered]@{
        schema_version = "xinao.grok_worker_selection_contract_test.v1"
        ok = $true
        positive_fresh_process = $true
        automatic_selection_fresh_process = $true
        negative_cases = @($negativeCases.name) + @(
            "missing_model",
            "missing_cwd",
            "automatic_selection_unhealthy_model",
            "dispatch_changed_decision",
            "direct_pool_missing_selection",
            "direct_pool_changed_decision",
            "temporal_host_missing_selection",
            "temporal_alias_missing_selection"
        )
        model_invocation_performed = $false
    } | ConvertTo-Json -Depth 5
}
finally {
    Remove-Item Env:\XINAO_GROK_SELECTION_STUB_CALL -ErrorAction SilentlyContinue
    foreach ($path in @($dispatchMeta, $poolDir, $autoDispatchMeta, $autoPoolDir, $autoSelectionDir)) {
        if ($path -and (Test-Path -LiteralPath $path)) { Remove-Item -LiteralPath $path -Force -Recurse }
    }
    if ($dispatchLatestExisted) {
        [IO.File]::WriteAllBytes($dispatchLatest, $dispatchLatestBytes)
    }
    elseif (Test-Path -LiteralPath $dispatchLatest) {
        Remove-Item -LiteralPath $dispatchLatest -Force
    }
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Force -Recurse }
}
