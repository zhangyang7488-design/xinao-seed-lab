# Grok L0 pre-start gate — read-only, fail-open evidence only. Never blocks session or tools.
param(
    [string]$BootstrapPath = (Join-Path $PSScriptRoot "GROK_L0_BOOTSTRAP.md"),
    [string]$BridgeConfigPath = (Join-Path $PSScriptRoot "bridge.config.json")
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$status = "grok_l0_bootstrap_ready"
$namedBlocker = $null
$missing = @()

if (-not (Test-Path -LiteralPath $BootstrapPath -PathType Leaf)) {
    $status = "grok_l0_bootstrap_missing"
    $namedBlocker = "GROK_L0_BOOTSTRAP_MISSING"
}
else {
    $text = Get-Content -LiteralPath $BootstrapPath -Raw -Encoding UTF8
    $required = @(
        "SENTINEL:GROK_L0_BOOTSTRAP_V1",
        "SENTINEL:GROK_L0_BOOTSTRAP_READY",
        "Send-GrokIntentToCodexA.ps1",
        "Invoke-CodexAManagedVisibleInject.ps1",
        "dual_delivery_policy"
    )
    $missing = @($required | Where-Object { $text -notmatch [regex]::Escape($_) })
    if ($missing.Count -gt 0) {
        $status = "grok_l0_bootstrap_degraded"
        $namedBlocker = "GROK_L0_BOOTSTRAP_SENTINEL_OR_ANCHOR_MISSING"
    }
}

$bridgeOk = $false
$l0Contract = $false
if (Test-Path -LiteralPath $BridgeConfigPath -PathType Leaf) {
    try {
        $bridge = Get-Content -LiteralPath $BridgeConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $bridgeOk = [bool]$bridge.dual_delivery_policy.enabled_default
        if ($bridge.grok_l0_bootstrap) {
            $l0Contract = [bool]$bridge.grok_l0_bootstrap.required_before_any_action
        }
    }
    catch {
        $status = "grok_l0_bootstrap_degraded"
        $namedBlocker = "GROK_BRIDGE_CONFIG_PARSE_FAILED"
    }
}

$sentinel = if ($status -eq "grok_l0_bootstrap_ready") {
    "SENTINEL:GROK_L0_BOOTSTRAP_GATE_PASS"
} else {
    "SENTINEL:GROK_L0_BOOTSTRAP_GATE_DEGRADED"
}

@{
    schema_version = "xinao.grok_l0_bootstrap_gate.v1"
    status = $status
    generated_at = (Get-Date).ToString("o")
    bootstrap_path = $BootstrapPath
    bridge_config_path = $BridgeConfigPath
    bridge_dual_delivery_enabled = $bridgeOk
    l0_behavioral_contract = $l0Contract
    pre_start_read_contract = $true
    anti_self_lock = $true
    blocks_session = $false
    blocks_tools = $false
    blocks_delivery = $false
    fail_open = $true
    no_runtime_state_prerequisite = $true
    no_ingress_probe = $true
    named_blocker = $namedBlocker
    missing_anchors = $missing
    reminder_layers = @(
        "AGENTS.md L0 section",
        ".grok/rules/00-grok-l0-bootstrap.md",
        ".grok/rules/02-grok-newsys-seed-cortex-route.md",
        ".grok/rules/03-grok-codex-progress-truth-lens.md",
        "SessionStart hook evidence only"
    )
    read_before = @(
        "GROK_L0_BOOTSTRAP.md",
        "GROK_CODEX_PROGRESS_TRUTH_LENS.md",
        "GROK_NEWSYS_INDEPENDENT_PARALLEL.md",
        "grok_newsys_independent_parallel_anchor.v1.json",
        "grok_codex_progress_truth_lens.v1.json",
        "AGENTS.md dual_delivery_policy section",
        "bridge.config.json dual_delivery_policy"
    )
    newsys_parallel_route = @{
        short_kernel = "GROK_NEWSYS_INDEPENDENT_PARALLEL.md"
        anchor_json = "grok_newsys_independent_parallel_anchor.v1.json"
        anchor_present = (Test-Path -LiteralPath (Join-Path $PSScriptRoot "GROK_NEWSYS_INDEPENDENT_PARALLEL.md") -PathType Leaf)
        phase0_smoke_is_not_full_completion = $true
    }
    default_delivery_script = "Send-GrokIntentToCodexA.ps1"
    default_visible_script = "Invoke-CodexAManagedVisibleInject.ps1"
    not_task_owner = $true
    not_user_completion = $true
    not_execution_lock = $true
    sentinel = $sentinel
} | ConvertTo-Json -Depth 6

exit 0