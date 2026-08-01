#Requires -Version 7.0
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false)
$bridge = $PSScriptRoot
$pwsh = (Get-Process -Id $PID).Path
$runtimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
$selectorPointerPath = Join-Path $runtimeRoot "state\grok_supervisor_selector\current.json"
$testRoot = Join-Path "$runtimeRoot\tmp" (
    "grok-prior-reuse-auth-bypass-" + (Get-Date -Format "yyyyMMddTHHmmss") + "-" +
    [guid]::NewGuid().ToString("N").Substring(0, 8)
)
$tempBridge = Join-Path $testRoot "bridge"
$candidateRoot = Join-Path $testRoot "candidate"
$profile = Join-Path $testRoot "missing-auth-profile"
$adapterRoot = Join-Path $testRoot "adapter"
$adapterScript = Join-Path $adapterRoot "services\agent_runtime\direct_worker_pool_common_adapter.py"
$workerMarker = Join-Path $testRoot "worker-started.txt"
$refreshMarker = Join-Path $testRoot "catalog-refresh.txt"
$dispatchLatest = Join-Path $runtimeRoot "state\codex_dispatch_grok_worker_pool\latest.json"
$poolLatest = Join-Path $runtimeRoot "state\grok_worker_pool\latest.json"
$dispatchLatestExisted = Test-Path -LiteralPath $dispatchLatest -PathType Leaf
$poolLatestExisted = Test-Path -LiteralPath $poolLatest -PathType Leaf
$dispatchLatestBytes = if ($dispatchLatestExisted) { [IO.File]::ReadAllBytes($dispatchLatest) } else { $null }
$poolLatestBytes = if ($poolLatestExisted) { [IO.File]::ReadAllBytes($poolLatest) } else { $null }
$cleanupPaths = [Collections.Generic.List[string]]::new()

function Assert-Contract([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "GROK_PRIOR_REUSE_AUTH_BYPASS_TEST_FAILED: $Name" }
}

function Invoke-FreshPowerShell([string[]]$Arguments) {
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $pwsh -NoLogo -NoProfile @Arguments 2>&1 | ForEach-Object { [string]$_ })
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [pscustomobject]@{ exit_code = $exitCode; output = ($output -join "`n") }
}

function Restore-Latest([string]$Path, [bool]$Existed, [byte[]]$Bytes) {
    if ($Existed) {
        [IO.File]::WriteAllBytes($Path, $Bytes)
    }
    elseif (Test-Path -LiteralPath $Path -PathType Leaf) {
        Remove-Item -LiteralPath $Path -Force
    }
}

New-Item -ItemType Directory -Force -Path @(
    $tempBridge,
    $candidateRoot,
    $profile,
    (Split-Path -Parent $adapterScript)
) | Out-Null

try {
    foreach ($name in @(
        "Invoke-CodexDispatchGrokWorkerPool.ps1",
        "Invoke-GrokWorkerPool.ps1",
        "GrokAuthenticatedCatalogRefresh.ps1",
        "GrokAuthenticatedCatalogTime.ps1",
        "GrokSupervisorRootCapability.ps1",
        "GrokWindowsPathIdentity.ps1",
        "GrokWorkerPoolAccounting.ps1",
        "GrokWorkerSelectionReceipt.ps1",
        "resolve_grok_worker_selection_receipt.py"
    )) {
        Copy-Item -LiteralPath (Join-Path $bridge $name) -Destination $tempBridge
    }
    [IO.File]::WriteAllText(
        (Join-Path $tempBridge "Invoke-GrokComposer25Worker.ps1"),
        @'
[IO.File]::WriteAllText(
    $env:XINAO_GROK_REUSE_WORKER_MARKER,
    "worker started",
    [Text.UTF8Encoding]::new($false)
)
throw "MODEL_WORKER_MUST_NOT_START_DURING_PRIOR_REUSE"
'@,
        $utf8
    )
    $selectionProbe = Join-Path $testRoot "selection-probe.ps1"
    [IO.File]::WriteAllText(
        $selectionProbe,
        @'
[IO.File]::AppendAllText(
    $env:XINAO_GROK_REUSE_REFRESH_MARKER,
    "refresh attempted`n",
    [Text.UTF8Encoding]::new($false)
)
exit 91
'@,
        $utf8
    )

    $selectorPointer = Get-Content -LiteralPath $selectorPointerPath -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    $selectorManifest = Get-Content -LiteralPath ([string]$selectorPointer.release_manifest_ref) -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    $selectorRoot = [string]$selectorPointer.release_root
    $selectorPython = [string]$selectorManifest.python_executable
    $selectorSha256 = [string]$selectorManifest.selector_source_sha256
    $resolver = Join-Path $tempBridge "resolve_grok_worker_selection_receipt.py"
    $seedSelection = Join-Path $testRoot "seed-selection.json"
    $resolverOutput = @(
        & $selectorPython -I -B $resolver `
            --supervisor-root $selectorRoot `
            --runtime-root $runtimeRoot `
            --model "grok-4.5" `
            --output $seedSelection `
            --expected-selector-sha256 $selectorSha256 2>&1 |
            ForEach-Object { [string]$_ }
    )
    Assert-Contract ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $seedSelection -PathType Leaf)) (
        "seed_selection:" + ($resolverOutput -join "|")
    )

    $promptPath = Join-Path $testRoot "prompt.md"
    $rulesPath = Join-Path $testRoot "rules.md"
    [IO.File]::WriteAllText($promptPath, "identical reuse fixture", $utf8)
    [IO.File]::WriteAllText($rulesPath, "bounded reuse fixture rules", $utf8)
    $rulesSha256 = (Get-FileHash -LiteralPath $rulesPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $subjectSha256 = "1" * 64
    $contextSha256 = "2" * 64
    $contractPath = Join-Path $testRoot "common-logical-contract.json"
    $prepareReceiptPath = Join-Path $testRoot "contract-prepare-receipt.json"
    $prepareScript = Join-Path $selectorRoot "scripts\prepare_direct_worker_pool_common_contract.py"
    $prepareOutput = @(
        & $selectorPython -I -B $prepareScript `
            --prompt-file $promptPath `
            --selection-receipt $seedSelection `
            --rules-file $rulesPath `
            --frozen-context-sha256 $contextSha256 `
            --subject-manifest-sha256 $subjectSha256 `
            --work-key "reuse-auth-bypass-fixture" `
            --operation-id "reuse-auth-bypass-op" `
            --min-result-chars 1 `
            --deadline-seconds 30 `
            --output $contractPath `
            --receipt-output $prepareReceiptPath 2>&1 |
            ForEach-Object { [string]$_ }
    )
    Assert-Contract ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $contractPath -PathType Leaf)) (
        "prepare_contract:" + ($prepareOutput -join "|")
    )

    $priorRoot = Join-Path $testRoot "prior"
    New-Item -ItemType Directory -Force -Path $priorRoot | Out-Null
    $priorAttempt = Join-Path $priorRoot "common_attempt_receipt.json"
    [IO.File]::WriteAllText(
        $priorAttempt,
        '{"schema_version":"xinao.execution.attempt_receipt.v1","terminal_state":"accepted"}',
        $utf8
    )
    $priorAttemptSha256 = (Get-FileHash -LiteralPath $priorAttempt -Algorithm SHA256).Hash.ToLowerInvariant()
    $contractSha256 = (Get-FileHash -LiteralPath $contractPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $adapterSource = @"
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--logical-contract", required=True, type=Path)
parser.add_argument("--prior-attempt-receipt", required=True, type=Path)
parser.add_argument("--classify-prior-only", action="store_true")
args, _ = parser.parse_known_args()

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

identical = (
    args.classify_prior_only
    and sha(args.logical_contract) == "$contractSha256"
    and sha(args.prior_attempt_receipt) == "$priorAttemptSha256"
)
print(json.dumps({
    "ok": identical,
    "skip_execution": identical,
    "disposition": "ACCEPTED_IDENTICAL_REUSE" if identical else "REJECTED_PRIOR_MISMATCH",
}, separators=(",", ":")))
"@
    [IO.File]::WriteAllText($adapterScript, $adapterSource, $utf8)

    $env:XINAO_GROK_REUSE_WORKER_MARKER = $workerMarker
    $env:XINAO_GROK_REUSE_REFRESH_MARKER = $refreshMarker
    $positiveSuffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $positiveDispatchId = "cdx_20000101T000000_$positiveSuffix"
    $positivePoolId = "gwp_20000101T000000_$positiveSuffix"
    $positiveDispatchMeta = Join-Path $runtimeRoot "state\codex_dispatch_grok_worker_pool\$positiveDispatchId.json"
    $positivePoolDir = Join-Path $runtimeRoot "state\grok_worker_pool\$positivePoolId"
    $positiveSelectionDir = Join-Path $runtimeRoot "state\grok_worker_selection\$positiveDispatchId"
    foreach ($path in @($positiveDispatchMeta, $positivePoolDir, $positiveSelectionDir)) {
        $cleanupPaths.Add($path)
    }
    $positive = Invoke-FreshPowerShell @(
        "-File", (Join-Path $tempBridge "Invoke-CodexDispatchGrokWorkerPool.ps1"),
        "-N", "1",
        "-PromptFile", $promptPath,
        "-Cwd", $candidateRoot,
        "-Model", "grok-4.5",
        "-GrokHome", $profile,
        "-SelectionProbeGrokExe", $selectionProbe,
        "-SupervisorRoot", $selectorRoot,
        "-SelectorReleasePointer", $selectorPointerPath,
        "-RuntimeRoot", $runtimeRoot,
        "-DispatchId", $positiveDispatchId,
        "-PoolId", $positivePoolId,
        "-TimeoutSec", "30",
        "-MinResultChars", "1",
        "-CommonLogicalContractPath", $contractPath,
        "-CommonSubjectManifestSha256", $subjectSha256,
        "-CommonFrozenContextSha256", $contextSha256,
        "-CommonRulesFile", $rulesPath,
        "-CommonRulesSha256", $rulesSha256,
        "-CommonPhase", "VERIFY",
        "-CommonPriorAttemptReceiptPath", $priorAttempt,
        "-CommonAdapterRoot", $adapterRoot,
        "-CommonPythonExe", $selectorPython,
        "-Quiet"
    )
    Assert-Contract ($positive.exit_code -eq 0) ("positive_dispatch:" + $positive.output)
    $positiveSummaryPath = Join-Path $positivePoolDir "pool_summary.json"
    Assert-Contract (Test-Path -LiteralPath $positiveSummaryPath -PathType Leaf) "positive_pool_summary_present"
    $positiveSummary = Get-Content -LiteralPath $positiveSummaryPath -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    Assert-Contract ($positiveSummary.reuse_skipped_execution -eq $true) "positive_identical_reuse"
    Assert-Contract ([int64]$positiveSummary.usage.attempt_count -eq 0) "positive_attempt_count_zero"
    Assert-Contract ([int64]$positiveSummary.usage.total_tokens -eq 0) "positive_total_tokens_zero"
    Assert-Contract (-not (Test-Path -LiteralPath $refreshMarker)) "positive_catalog_refresh_count_zero"
    Assert-Contract (-not (Test-Path -LiteralPath $workerMarker)) "positive_worker_start_count_zero"

    $mismatchPrior = Join-Path $priorRoot "mismatch_attempt_receipt.json"
    [IO.File]::WriteAllText(
        $mismatchPrior,
        '{"schema_version":"xinao.execution.attempt_receipt.v1","terminal_state":"different"}',
        $utf8
    )
    $negativeSuffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $negativeDispatchId = "cdx_20000101T000000_$negativeSuffix"
    $negativePoolId = "gwp_20000101T000000_$negativeSuffix"
    $negativeDispatchMeta = Join-Path $runtimeRoot "state\codex_dispatch_grok_worker_pool\$negativeDispatchId.json"
    $negativePoolDir = Join-Path $runtimeRoot "state\grok_worker_pool\$negativePoolId"
    $negativeSelectionDir = Join-Path $runtimeRoot "state\grok_worker_selection\$negativeDispatchId"
    foreach ($path in @($negativeDispatchMeta, $negativePoolDir, $negativeSelectionDir)) {
        $cleanupPaths.Add($path)
    }
    $negative = Invoke-FreshPowerShell @(
        "-File", (Join-Path $tempBridge "Invoke-CodexDispatchGrokWorkerPool.ps1"),
        "-N", "1",
        "-PromptFile", $promptPath,
        "-Cwd", $candidateRoot,
        "-Model", "grok-4.5",
        "-GrokHome", $profile,
        "-SelectionProbeGrokExe", $selectionProbe,
        "-SupervisorRoot", $selectorRoot,
        "-SelectorReleasePointer", $selectorPointerPath,
        "-RuntimeRoot", $runtimeRoot,
        "-DispatchId", $negativeDispatchId,
        "-PoolId", $negativePoolId,
        "-TimeoutSec", "30",
        "-MinResultChars", "1",
        "-CommonLogicalContractPath", $contractPath,
        "-CommonSubjectManifestSha256", $subjectSha256,
        "-CommonFrozenContextSha256", $contextSha256,
        "-CommonRulesFile", $rulesPath,
        "-CommonRulesSha256", $rulesSha256,
        "-CommonPhase", "VERIFY",
        "-CommonPriorAttemptReceiptPath", $mismatchPrior,
        "-CommonAdapterRoot", $adapterRoot,
        "-CommonPythonExe", $selectorPython,
        "-Quiet"
    )
    Assert-Contract ($negative.exit_code -ne 0) "negative_prior_mismatch_rejected"
    Assert-Contract ($negative.output -match "GROK_WORKER_POOL_COMMON_PRIOR_RECEIPT_NOT_REUSABLE") "negative_prior_mismatch_reason"
    Assert-Contract (-not (Test-Path -LiteralPath $refreshMarker)) "negative_catalog_refresh_count_zero"
    Assert-Contract (-not (Test-Path -LiteralPath $workerMarker)) "negative_worker_never_started"

    [ordered]@{
        status = "verified"
        identical_reuse_attempt_count = [int64]$positiveSummary.usage.attempt_count
        identical_reuse_total_tokens = [int64]$positiveSummary.usage.total_tokens
        catalog_refresh_count = 0
        worker_start_count = 0
        prior_mismatch_fell_through_to_worker = $false
    } | ConvertTo-Json -Depth 4
}
finally {
    Remove-Item Env:\XINAO_GROK_REUSE_WORKER_MARKER -ErrorAction SilentlyContinue
    Remove-Item Env:\XINAO_GROK_REUSE_REFRESH_MARKER -ErrorAction SilentlyContinue
    foreach ($path in $cleanupPaths) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
    Restore-Latest -Path $dispatchLatest -Existed $dispatchLatestExisted -Bytes $dispatchLatestBytes
    Restore-Latest -Path $poolLatest -Existed $poolLatestExisted -Bytes $poolLatestBytes
    if (Test-Path -LiteralPath $testRoot -PathType Container) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}

exit 0
