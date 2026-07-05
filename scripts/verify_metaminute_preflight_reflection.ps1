[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$repoRoot = if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    (Get-Location).Path
}
else {
    $RepoRoot
}
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = "$repoRoot\src;$repoRoot"

try {
    Push-Location $repoRoot
    $modulePath = Join-Path $repoRoot "services\agent_runtime\metaminute_preflight_reflection.py"
    $output = & $Python $modulePath `
        --trigger window_start_first_hop `
        --current-user-object "Codex S global self prelude verifier" `
        --latest-user-delta "ordinary task without productivity keyword" `
        --repo-root $repoRoot `
        --runtime-root $RuntimeRoot 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $output | Write-Output
    }
    Assert-True ($exitCode -eq 0) "metaminute preflight writer failed."

    $latest = Join-Path $RuntimeRoot "state\metaminute_preflight_reflection\latest.json"
    Assert-True (Test-Path -LiteralPath $latest -PathType Leaf) "metaminute latest missing: $latest"
    $payload = Get-Content -LiteralPath $latest -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$payload.schema_version -eq "xinao.codex_s.metaminute_preflight_reflection.v1") "schema_version mismatch."
    Assert-True ($payload.validation.passed -eq $true) "validation did not pass."
    Assert-True ($payload.validation.checks.global_self_prelude_present -eq $true) "global self prelude validation missing."
    Assert-True ($payload.validation.checks.intent_decode_index_present -eq $true) "intent decode index validation missing."
    Assert-True ([string]$payload.global_self_prelude.scope -eq "global_always_on_for_codex_s") "global self prelude scope mismatch."
    Assert-True ($payload.global_self_prelude.keyword_required -eq $false) "global self prelude must not require keyword."
    Assert-True ($payload.global_self_prelude.trigger_required -eq $false) "global self prelude must not require trigger."
    Assert-True ([string]$payload.global_self_prelude.classification_gate.classes -match "human_dialogue") "classification gate missing human_dialogue."
    Assert-True ([string]$payload.global_self_prelude.classification_gate.classes -match "execution") "classification gate missing execution."
    Assert-True ([string]$payload.global_self_prelude.classification_gate.classes -match "watch") "classification gate missing watch."
    Assert-True ($payload.global_self_prelude.foreground_mirror_watch.not_execution_controller -eq $true) "foreground mirror watch must not be execution controller."
    Assert-True ($payload.global_self_prelude.mandatory_default_mainline_hardening.default -eq $true) "default mainline hardening default missing."

    $preludeLatest = [string]$payload.output_paths.global_self_prelude_latest
    $preludePrompt = [string]$payload.output_paths.global_self_prelude_prompt
    $intentDecodeIndex = [string]$payload.output_paths.intent_decode_index_latest
    $repoIntentDecodeIndex = [string]$payload.output_paths.repo_intent_decode_index
    Assert-True (Test-Path -LiteralPath $preludeLatest -PathType Leaf) "global self prelude latest missing: $preludeLatest"
    Assert-True (Test-Path -LiteralPath $preludePrompt -PathType Leaf) "global self prelude prompt missing: $preludePrompt"
    Assert-True (Test-Path -LiteralPath $intentDecodeIndex -PathType Leaf) "intent decode index missing: $intentDecodeIndex"
    Assert-True (Test-Path -LiteralPath $repoIntentDecodeIndex -PathType Leaf) "repo intent decode index missing: $repoIntentDecodeIndex"
    $prelude = Get-Content -LiteralPath $preludeLatest -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$prelude.schema_version -eq "xinao.codex_s.global_self_prelude.v1") "prelude schema mismatch."
    Assert-True ([string]$prelude.prelude_id -eq "codex_s_global_self_prelude_v1") "prelude id mismatch."
    $promptText = Get-Content -LiteralPath $preludePrompt -Raw -Encoding UTF8
    Assert-True (-not [string]::IsNullOrWhiteSpace($promptText)) "global self prelude prompt is empty."
    Assert-True ($promptText.Contains("human_dialogue / diagnosis / execution / watch")) "prelude prompt missing intake classes."
    Assert-True ($promptText.Contains("foreground mirror watch")) "prelude prompt missing foreground mirror watch."
    $decodeIndex = Get-Content -LiteralPath $intentDecodeIndex -Raw -Encoding UTF8 | ConvertFrom-Json
    $watchEntry = @($decodeIndex.entries | Where-Object { $_.entry_id -eq "foreground_mirror_watch_aliases" })[0]
    $durableEntry = @($decodeIndex.entries | Where-Object { $_.entry_id -eq "default_durable_transaction_333" })[0]
    Assert-True ($null -ne $watchEntry) "decode index missing foreground mirror watch entry."
    Assert-True ($null -ne $durableEntry) "decode index missing 333 durable transaction entry."
    Assert-True ((@($watchEntry.match_terms) -contains "watch backend") -and (@($watchEntry.match_terms) -contains "keep watching")) "decode index missing watch aliases."
    Assert-True ((@($durableEntry.match_terms) -contains "333") -and ([string]$durableEntry.decode_cn -match "RootIntentLoop")) "decode index missing 333 mapping."

    Write-Output "metaminute_latest=$latest"
    Write-Output "intent_decode_index_latest=$intentDecodeIndex"
    Write-Output "repo_intent_decode_index=$repoIntentDecodeIndex"
    Write-Output "global_self_prelude_latest=$preludeLatest"
    Write-Output "global_self_prelude_prompt=$preludePrompt"
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    Pop-Location
}
