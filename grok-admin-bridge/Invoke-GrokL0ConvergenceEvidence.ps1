[CmdletBinding()]
param(
    [string]$ConvergencePath = (Join-Path $PSScriptRoot "l0_global_convergence.v1.json"),
    [string]$RuntimeRoot = "D:\XINAO_CLEAN_RUNTIME",
    [string]$L0Path = "D:\XINAO_CLEAN_RUNTIME\resources\startup\codex_l0_bootstrap.md",
    [string]$BacklogPath = "D:\XINAO_CLEAN_RUNTIME\resources\continuation\default_backlog.json"
)

$ErrorActionPreference = "Stop"

function Read-JsonFile {
    param([string]$Path, $Default = $null)
    if (-not (Test-Path -LiteralPath $Path)) { return $Default }
    try { return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json } catch { return $Default }
}

function Count-L0MandatoryReads {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    $text = Get-Content -LiteralPath $Path -Raw
    return ([regex]::Matches($text, "latest\.json")).Count
}

$convergence = Read-JsonFile -Path $ConvergencePath
$backlog = Read-JsonFile -Path $BacklogPath
$l0ReadCount = Count-L0MandatoryReads -Path $L0Path
$backlogReadOrderCount = if ($backlog.default_read_order) { @($backlog.default_read_order).Count } else { 0 }

$l8l9Items = @()
if ($backlog.work_items) {
    foreach ($wi in @($backlog.work_items)) {
        $id = [string]$wi.work_item_id
        if ($id -match "L8|L9|S13|canary|CANARY") {
            $l8l9Items += [ordered]@{
                work_item_id = $id
                status = $wi.status
                next_default_action = $wi.next_default_action
            }
        }
    }
}

$hotTarget = if ($convergence.read_tiers.hot_startup_max_items) { [int]$convergence.read_tiers.hot_startup_max_items } else { 8 }
$drift = [System.Collections.Generic.List[string]]::new()
if ($l0ReadCount -gt ($hotTarget * 3)) { $drift.Add("l0_latest_json_refs_excessive:$l0ReadCount") }
if ($backlogReadOrderCount -gt $hotTarget) { $drift.Add("backlog_startup_read_order_excessive:$backlogReadOrderCount") }
if ($l8l9Items.Count -gt 0) { $drift.Add("backlog_l8_l9_canary_items_present:$($l8l9Items.Count)") }

$defaultBinding = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\default_work_binding\latest.json")
$txBoundary = Read-JsonFile -Path (Join-Path $RuntimeRoot "state\codex_default_transaction_boundary\latest.json")

$evidence = [ordered]@{
    schema_version = "xinao.grok_l0_convergence_evidence.v1"
    generated_at = (Get-Date).ToString("o")
    convergence_ref = $ConvergencePath
    progress_question_cn = $convergence.progress_question_cn
    l0_path = $L0Path
    l0_latest_json_ref_count = $l0ReadCount
    backlog_path = $BacklogPath
    backlog_default_read_order_count = $backlogReadOrderCount
    hot_startup_target_max = $hotTarget
    backlog_l8_l9_canary_items = @($l8l9Items)
    default_work_binding_main_chain = if ($defaultBinding.main_chain_default) { $defaultBinding.main_chain_default } else { $null }
    transaction_boundary_status = if ($txBoundary.status) { $txBoundary.status } else { "unknown" }
    drift_signals = @($drift)
    convergence_needed = ($drift.Count -gt 0)
    grok_verdict_hint_cn = if ($drift.Count -gt 0) { "有点偏：L0/规则栈仍奖励开机扫 latest + L8/L9 canary 当下一步，需收敛到唯一事务热路径" } else { "在正路上：开机读已收敛" }
    not_user_completion = $true
}

$stateDir = Join-Path $RuntimeRoot "state\grok_l0_convergence_evidence"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$evidence | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $stateDir "latest.json") -Encoding UTF8
$evidence | ConvertTo-Json -Depth 10