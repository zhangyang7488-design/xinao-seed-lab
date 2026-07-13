[CmdletBinding()]
param(
    [ValidateSet('verify', 'fresh')]
    [string]$Mode = 'verify',
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$InputRoot = 'C:\Users\xx363\Desktop\主线\新澳数据包',
    [string]$ProjectRoot = $(Join-Path (Split-Path -Parent $PSScriptRoot) 'projects\xinao-market-lab'),
    [string]$P2EvidenceRun,
    [string]$P3EvidenceRun
)

$ErrorActionPreference = 'Stop'
$runId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$canonicalEvidenceRoot = Join-Path $RuntimeRoot 'state\xinao-market-lab\runs'
$resultRoot = Join-Path $RuntimeRoot "state\human-capabilities\evals\domain-self-evolution\$runId"
$summaryPath = Join-Path $resultRoot 'summary.json'
$previousUvCache = $env:UV_CACHE_DIR

foreach ($required in @($InputRoot, $ProjectRoot, $canonicalEvidenceRoot)) {
    if (-not (Test-Path -LiteralPath $required -PathType Container)) {
        throw "Required domain self-evolution path is missing: $required"
    }
}
New-Item -ItemType Directory -Path $resultRoot -Force | Out-Null
$env:UV_CACHE_DIR = Join-Path $RuntimeRoot 'cache\xinao-market-lab\uv'

function Resolve-LatestEvidenceRun {
    param([Parameter(Mandatory)][string]$Prefix)
    $candidate = Get-ChildItem -LiteralPath $canonicalEvidenceRoot -Directory |
        Where-Object { $_.Name -like "$Prefix*" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw "No accepted evidence run matches: $Prefix"
    }
    return $candidate.FullName
}

function Resolve-LatestP3EvidenceRun {
    $candidate = Get-ChildItem -LiteralPath $canonicalEvidenceRoot -Directory |
        Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName 'research_protocol.json') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName 'trials.jsonl') -PathType Leaf)
        } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw 'No replayable P3 evidence run is available.'
    }
    return $candidate.FullName
}

function Invoke-MarketLab {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$LogName
    )
    Push-Location $ProjectRoot
    try {
        $lines = & uv run --frozen xinao-market-lab @Arguments 2>&1
        $code = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    $logPath = Join-Path $resultRoot $LogName
    $lines | Set-Content -LiteralPath $logPath -Encoding utf8NoBOM
    if ($code -ne 0) {
        throw "Market Lab command failed with exit code $code; see $logPath"
    }
    return (($lines | Out-String).Trim() | ConvertFrom-Json)
}

try {
    if (-not $P2EvidenceRun) {
        $P2EvidenceRun = Resolve-LatestEvidenceRun -Prefix 'p2-rule-catalog-acceptance-'
    }
    if (-not (Test-Path -LiteralPath $P2EvidenceRun -PathType Container)) {
        throw "P2 evidence run is missing: $P2EvidenceRun"
    }

    if ($Mode -eq 'fresh') {
        $freshName = "p3-dual-loop-$runId"
        $null = Invoke-MarketLab -LogName 'fresh-run.json' -Arguments @(
            'p3-research-protocol-judge',
            '--input-root', $InputRoot,
            '--evidence-root', $canonicalEvidenceRoot,
            '--p2-evidence-run', $P2EvidenceRun,
            '--run-name', $freshName
        )
        $P3EvidenceRun = Join-Path $canonicalEvidenceRoot $freshName
    }
    elseif (-not $P3EvidenceRun) {
        $P3EvidenceRun = Resolve-LatestP3EvidenceRun
    }

    if (-not (Test-Path -LiteralPath $P3EvidenceRun -PathType Container)) {
        throw "P3 evidence run is missing: $P3EvidenceRun"
    }
    $verification = Invoke-MarketLab -LogName 'verification.json' -Arguments @(
        'p3-verify', '--input-root', $InputRoot, '--run-dir', $P3EvidenceRun
    )

    $protocolPath = Join-Path $P3EvidenceRun 'research_protocol.json'
    $judgePath = Join-Path $P3EvidenceRun 'judge_gate.json'
    $ledgerPath = Join-Path $P3EvidenceRun 'trials.jsonl'
    foreach ($artifact in @($protocolPath, $judgePath, $ledgerPath)) {
        if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
            throw "P3 evidence artifact is missing: $artifact"
        }
    }
    $protocol = Get-Content -LiteralPath $protocolPath -Raw | ConvertFrom-Json
    $judge = Get-Content -LiteralPath $judgePath -Raw | ConvertFrom-Json
    $trialRows = [int](Get-Content -LiteralPath $ledgerPath | Measure-Object -Line).Lines
    $evaluatorFiles = @(
        'src\xinao_market_lab\catalog.py',
        'src\xinao_market_lab\research.py'
    )
    $evaluatorPins = @(
        foreach ($relative in $evaluatorFiles) {
            $path = Join-Path $ProjectRoot $relative
            [ordered]@{
                path = $path
                sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    )
    $summary = [ordered]@{
        schema_version = 'xinao.domain_self_evolution_run.v1'
        run_id = $runId
        mode = $Mode
        status = if ($verification.status -eq 'verified') { 'verified' } else { 'unverified' }
        search_space_s = [int]$protocol.spec.candidates.Count
        schedule_r_cells = [int]$protocol.spec.declared_cell_budget
        protocol_p_sha256 = (Get-FileHash -LiteralPath $protocolPath -Algorithm SHA256).Hash.ToLowerInvariant()
        metrics_m = @($protocol.spec.metrics)
        trial_ledger = $ledgerPath
        trial_rows = $trialRows
        mechanics_status = $judge.mechanics_status
        economic_claim_status = $judge.economic_claim_status
        evaluator_pins = $evaluatorPins
        p2_evidence_run = $P2EvidenceRun
        p3_evidence_run = $P3EvidenceRun
        project_git_sha = (& git -C $ProjectRoot rev-parse HEAD 2>$null).Trim()
        project_git_dirty = (@(& git -C $ProjectRoot status --porcelain=v1 2>$null).Count -gt 0)
        behavior_loop_completion_implied = $false
        not_authority = $true
    }
    if (
        $summary.status -ne 'verified' -or
        $summary.schedule_r_cells -ne 32 -or
        $summary.trial_rows -ne 38528 -or
        $summary.mechanics_status -ne 'MECHANICS_ACCEPTED' -or
        $summary.economic_claim_status -ne 'ECONOMIC_CLAIM_BLOCKED'
    ) {
        throw 'Domain self-evolution evidence failed the frozen P3 acceptance shape.'
    }
    $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding utf8NoBOM
    $latestPath = Join-Path $RuntimeRoot 'state\human-capabilities\evals\domain-self-evolution\latest.json'
    [ordered]@{
        schema_version = 'xinao.domain_self_evolution_latest.v1'
        run_id = $runId
        summary = $summaryPath
        status = $summary.status
        finished_at = (Get-Date).ToString('o')
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $latestPath -Encoding utf8NoBOM
    Write-Output $summaryPath
}
finally {
    $env:UV_CACHE_DIR = $previousUvCache
}
