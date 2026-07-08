# Full disk cleanup — CLEAN legacy + RESEARCH artifacts + C Temp (2026-07-08).
# Does NOT touch Desktop 新系统 authority txt.
$ErrorActionPreference = "Continue"
function Size-GB($path) {
    if (-not (Test-Path $path)) { return 0 }
    $s = (Get-ChildItem $path -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    return [math]::Round($s / 1GB, 2)
}
function Remove-Tree($path, [string]$label) {
    if (-not (Test-Path $path)) { return }
    $before = Size-GB $path
    Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "REMOVED $label (~${before} GB): $path"
}

$beforeD = [math]::Round((Get-PSDrive D).Free / 1GB, 2)
$beforeC = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
Write-Host "=== BEFORE: C free ${beforeC} GB | D free ${beforeD} GB ==="

$clean = "D:\XINAO_CLEAN_RUNTIME"
$research = "D:\XINAO_RESEARCH_RUNTIME"

# --- D:\XINAO_CLEAN_RUNTIME (legacy compat, ~163GB) ---
# Keep: tools\ (UCP bridge), specs\, resources\ (small)
$cleanRemove = @(
    "machine_state",
    "build",
    "quarantine",
    "artifacts",
    "state",
    "tool_envs",
    "external",
    "services",
    "poc",
    "cache",
    "source_cache",
    "logs",
    "tmp",
    "checkpoints",
    "source_worktrees",
    "backups",
    "third_party",
    "public_ingress_adapter",
    "project_templates",
    "projections",
    "projectors",
    "runtime",
    "rollback",
    "runner",
    "project_registry",
    "schemas",
    "scripts",
    "supervisor",
    "reports",
    "project_onboarding",
    "platform_handoff",
    "policy_inputs",
    "action_queue",
    "agent_runtime",
    "archive",
    "autonomy",
    "bin",
    "catalog",
    "console",
    "contexts",
    "control_panel",
    "docs",
    "drafts",
    "evals",
    "event_store",
    "handoff",
    "ingress",
    "ledger_workspace",
    "lineage",
    "migrations",
    "panel",
    "policies",
    "policy",
    "private",
    "action_contract"
)
foreach ($rel in $cleanRemove) {
    Remove-Tree (Join-Path $clean $rel) "CLEAN/$rel"
}

# --- D:\XINAO_RESEARCH_RUNTIME leftovers ---
$researchRemove = @(
    "artifacts",
    "tools",
    "tool_envs",
    "runs",
    "temporal",
    "tmp",
    "logs"
)
foreach ($rel in $researchRemove) {
    Remove-Tree (Join-Path $research $rel) "RESEARCH/$rel"
}

# --- C:\Users\xx363\AppData\Local\Temp (user temp, not system) ---
$temp = "$env:LOCALAPPDATA\Temp"
if (Test-Path $temp) {
    $tb = Size-GB $temp
    Get-ChildItem $temp -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "CLEARED C Temp (~${tb} GB): $temp"
}

# --- S repo pycache again ---
$repo = "E:\XINAO_RESEARCH_WORKSPACES\S"
Get-ChildItem $repo -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$afterD = [math]::Round((Get-PSDrive D).Free / 1GB, 2)
$afterC = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
Write-Host "=== AFTER: C free ${afterC} GB (+$([math]::Round($afterC-$beforeC,2))) | D free ${afterD} GB (+$([math]::Round($afterD-$beforeD,2))) ==="
Write-Host "CLEAN_RUNTIME remaining GB: $(Size-GB $clean)"
Write-Host "RESEARCH_RUNTIME remaining GB: $(Size-GB $research)"
Write-Host "=== Full disk cleanup done ==="