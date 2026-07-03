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
    Assert-True ([string]$payload.global_self_prelude.scope -eq "global_always_on_for_codex_s") "global self prelude scope mismatch."
    Assert-True ($payload.global_self_prelude.keyword_required -eq $false) "global self prelude must not require keyword."
    Assert-True ($payload.global_self_prelude.trigger_required -eq $false) "global self prelude must not require trigger."

    $preludeLatest = [string]$payload.output_paths.global_self_prelude_latest
    $preludePrompt = [string]$payload.output_paths.global_self_prelude_prompt
    Assert-True (Test-Path -LiteralPath $preludeLatest -PathType Leaf) "global self prelude latest missing: $preludeLatest"
    Assert-True (Test-Path -LiteralPath $preludePrompt -PathType Leaf) "global self prelude prompt missing: $preludePrompt"
    $prelude = Get-Content -LiteralPath $preludeLatest -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$prelude.schema_version -eq "xinao.codex_s.global_self_prelude.v1") "prelude schema mismatch."
    Assert-True ([string]$prelude.prelude_id -eq "codex_s_global_self_prelude_v1") "prelude id mismatch."
    $promptText = Get-Content -LiteralPath $preludePrompt -Raw -Encoding UTF8
    Assert-True (-not [string]::IsNullOrWhiteSpace($promptText)) "global self prelude prompt is empty."

    Write-Output "metaminute_latest=$latest"
    Write-Output "global_self_prelude_latest=$preludeLatest"
    Write-Output "global_self_prelude_prompt=$preludePrompt"
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    Pop-Location
}
