[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$Python = "",
    [string]$WaveId = "verify-light-research-loop-20260706"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

if (-not $Python) {
    $repoPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $repoPython -PathType Leaf) {
        $Python = $repoPython
    } else {
        $Python = "python"
    }
}

$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$RepoRoot\src;$RepoRoot"
    Push-Location $RepoRoot
    try {
        & $Python -m py_compile `
            services\agent_runtime\codex_s_light_research_loop.py `
            src\xinao_seedlab\cli\__main__.py `
            src\xinao_seedlab\application\seed_cortex.py
        Assert-True ($LASTEXITCODE -eq 0) "py_compile failed."

        $output = & $Python -m xinao_seedlab.cli.__main__ light-research-loop `
            --runtime-root $RuntimeRoot `
            --repo-root $RepoRoot `
            --mode external_light `
            --wave-id $WaveId `
            --objective "Verify foreground light research loop without burning worker quota." `
            --local-query "SourceLedger|direct_worker_lane|dp_sidecar|qwen" `
            --source-url "https://docs.litellm.ai/docs/routing" `
            --source-url "https://github.com/lm-sys/RouteLLM" `
            --external-note "Mature model routing source for light research SourceLedger." `
            --worker-policy skip `
            --max-results 6
        Assert-True ($LASTEXITCODE -eq 0) "light-research-loop CLI failed."
        $payload = $output | ConvertFrom-Json

        Assert-True ([string]$payload.schema_version -eq "xinao.codex_s.light_research_loop.v1") "schema mismatch."
        Assert-True ([string]$payload.status -eq "light_research_loop_ready") "light loop not ready."
        Assert-True ($payload.validation.passed -eq $true) "validation did not pass."
        Assert-True ($payload.not_333_mainline -eq $true) "light loop was marked as 333 mainline."
        Assert-True ($payload.completion_claim_allowed -eq $false) "completion claim allowed."
        Assert-True ([int]$payload.source_ledger.entry_count -ge 1) "SourceLedger entries missing."
        Assert-True ([int]$payload.claim_cards.claim_card_count -ge 1) "ClaimCards missing."
        Assert-True ($payload.artifact_acceptance_queue.claim_card_requires_source_ledger -eq $true) "AAQ did not require SourceLedger."

        $latestPath = Join-Path $RuntimeRoot "state\codex_s_light_research_loop\latest.json"
        $manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.light_research_loop\manifest.json"
        $readbackPath = Join-Path $RuntimeRoot "readback\zh\codex_s_light_research_loop.md"
        Assert-True (Test-Path -LiteralPath $latestPath -PathType Leaf) "latest.json missing."
        Assert-True (Test-Path -LiteralPath $manifestPath -PathType Leaf) "capability manifest missing."
        Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "readback missing."

        $absoluteRoot = Join-Path $RuntimeRoot "tmp\verify_light_research_loop_absolute_root"
        New-Item -ItemType Directory -Force -Path $absoluteRoot | Out-Null
        $absoluteSource = Join-Path $absoluteRoot "legacy_control_plane.txt"
        "result_wait keeps foreground watch from becoming manual polling." |
            Set-Content -LiteralPath $absoluteSource -Encoding UTF8

        $absoluteOutput = & $Python -m xinao_seedlab.cli.__main__ light-research-loop `
            --runtime-root $RuntimeRoot `
            --repo-root $RepoRoot `
            --mode local_only `
            --wave-id "$WaveId-absolute-local-root" `
            --objective "Verify absolute local root search for old runtime/package paths." `
            --local-query "result_wait" `
            --local-root $absoluteRoot `
            --worker-policy skip `
            --max-results 3
        Assert-True ($LASTEXITCODE -eq 0) "absolute local-root light-research-loop CLI failed."
        $absolutePayload = $absoluteOutput | ConvertFrom-Json
        Assert-True ([string]$absolutePayload.status -eq "light_research_loop_ready") "absolute local-root scan not ready."
        Assert-True ($absolutePayload.validation.passed -eq $true) "absolute local-root validation did not pass."
        Assert-True ([int]$absolutePayload.source_ledger.entry_count -ge 1) "absolute local-root SourceLedger missing."
        $firstEntry = $absolutePayload.source_ledger.entries[0]
        Assert-True ([string]$firstEntry.source_family -eq "local_repo_search") "absolute local-root source family mismatch."
        Assert-True ([string]$firstEntry.source_url -like "file:$absoluteSource*") "absolute local-root source_url mismatch."

        Write-Output "PASS codex_s_light_research_loop"
        Write-Output "latest=$latestPath"
        Write-Output "manifest=$manifestPath"
        Write-Output "readback=$readbackPath"
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PYTHONPATH = $oldPythonPath
}
