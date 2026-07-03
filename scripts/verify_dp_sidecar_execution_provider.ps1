param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeRoot = "",
    [switch]$KeepRuntime
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$createdTemp = $false
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("xinao-dp-sidecar-provider-" + [System.Guid]::NewGuid().ToString("N"))
    $createdTemp = $true
}

Push-Location $RepoRoot
try {
    python -m pytest -q tests\seedcortex\test_dp_sidecar_execution_provider.py
    Assert-True ($LASTEXITCODE -eq 0) "focused pytest failed."

    $modes = @(
        @{ mode = "search"; expected = "search_ready" },
        @{ mode = "draft"; expected = "draft_ready" },
        @{ mode = "eval"; expected = "model_ready" }
    )

    foreach ($item in $modes) {
        $mode = [string]$item.mode
        $expected = [string]$item.expected
        $invocationId = "verify-dp-sidecar-$mode"
        python services\agent_runtime\dp_sidecar_execution_port.py `
            --runtime-root $RuntimeRoot `
            --task-id "verify_dp_sidecar_execution_provider" `
            --request-id "verify-dp-sidecar-$mode" `
            --invocation-id $invocationId `
            --episode-id "verify-dp-sidecar-provider" `
            --mode $mode `
            --objective "verify DP sidecar non-probe dispatch" `
            --input-text "DP sidecar provider must write result_path and raw_response_ref without completion claim." `
            --max-results 3 | Out-Null
        Assert-True ($LASTEXITCODE -eq 0) "dp sidecar port failed for mode $mode."

        $recordPath = Join-Path $RuntimeRoot "state\dp_sidecar_execution_provider\records\$invocationId.json"
        Assert-True (Test-Path -LiteralPath $recordPath -PathType Leaf) "provider record missing for mode $mode."
        $payload = Get-Content -LiteralPath $recordPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-True ($payload.mode_invocation_status -eq $expected) "mode $mode status mismatch."
        Assert-True ($payload.mode_dispatch_attempted -eq $true) "mode $mode did not attempt dispatch."
        Assert-True ($payload.provider_invocation_performed -eq $true) "mode $mode provider invocation missing."
        Assert-True (-not [string]::IsNullOrWhiteSpace([string]$payload.selected_carrier_provider_id)) "mode $mode missing carrier provider."
        Assert-True (-not [string]::IsNullOrWhiteSpace([string]$payload.result_path)) "mode $mode missing result_path."
        Assert-True (Test-Path -LiteralPath ([string]$payload.result_path) -PathType Leaf) "mode $mode result_path does not exist."
        Assert-True (-not [string]::IsNullOrWhiteSpace([string]$payload.raw_response_ref)) "mode $mode missing raw_response_ref."
        Assert-True (Test-Path -LiteralPath ([string]$payload.raw_response_ref) -PathType Leaf) "mode $mode raw_response_ref does not exist."
        Assert-True ([string]::IsNullOrWhiteSpace([string]$payload.named_blocker)) "mode $mode unexpectedly blocked."
        Assert-True ($payload.completion_claim_allowed -eq $false) "mode $mode allowed completion claim."
    }

    python services\agent_runtime\dp_sidecar_execution_port.py `
        --runtime-root $RuntimeRoot `
        --task-id "verify_dp_sidecar_execution_provider" `
        --request-id "verify-dp-sidecar-provider-probe" `
        --invocation-id "verify-dp-sidecar-provider-probe" `
        --episode-id "verify-dp-sidecar-provider" `
        --mode provider_probe `
        --objective "verify provider probe remains probe only" `
        --input-text "provider_probe cannot count as bulk progress" | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) "provider probe invocation failed."
    $probePath = Join-Path $RuntimeRoot "state\dp_sidecar_execution_provider\records\verify-dp-sidecar-provider-probe.json"
    $probe = Get-Content -LiteralPath $probePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($probe.mode_dispatch_attempted -eq $false) "provider_probe attempted dispatch."
    Assert-True ($probe.provider_invocation_performed -eq $false) "provider_probe counted as provider progress."

    Write-Output "dp_sidecar_execution_provider_verified_runtime=$RuntimeRoot"
    Write-Output "dp_sidecar_execution_provider_modes=search,draft,eval"
    Write-Output "provider_probe_progress_allowed=false"
}
finally {
    Pop-Location
    if ($createdTemp -and -not $KeepRuntime -and (Test-Path -LiteralPath $RuntimeRoot)) {
        Remove-Item -LiteralPath $RuntimeRoot -Recurse -Force
    }
}
