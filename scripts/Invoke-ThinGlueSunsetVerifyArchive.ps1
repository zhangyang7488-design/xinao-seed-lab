# 用户授权 sunset：8 条 verify 马拉松 → _retired + thin redirect stub
param([switch]$WhatIf)

$ErrorActionPreference = "Stop"
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
Set-Location $RepoRoot
$archive = Join-Path $RepoRoot "scripts\_retired\verify_marathon"
New-Item -ItemType Directory -Force -Path $archive | Out-Null
$map = @(
    @{ Name = "verify_current_task_source_intake.ps1"; Layer = "L0_intake"; Cli = "thin-glue-intake" },
    @{ Name = "verify_codex_s_light_research_loop.ps1"; Layer = "L4_search"; Cli = "thin-glue" },
    @{ Name = "verify_codex_native_provider_scheduler_phase4.ps1"; Layer = "L9_gateway"; Cli = "thin-glue-provider" },
    @{ Name = "verify_worker_dispatch_ledger.ps1"; Layer = "L9_ledger"; Cli = "thin-glue-status" },
    @{ Name = "verify_modular_dynamic_worker_pool_phase1.ps1"; Layer = "L9_worker_pool"; Cli = "thin-glue-worker-pool" },
    @{ Name = "verify_root_intent_loop_driver.ps1"; Layer = "L2_root_intent"; Cli = "thin-glue-root-intent" },
    @{ Name = "verify_pre_pass_audit_loop.ps1"; Layer = "L6_self_heal"; Cli = "thin-glue-l6-self-heal" },
    @{ Name = "verify_v4pro_mature_bind_execution_controller.ps1"; Layer = "L3_execute"; Cli = "thin-glue-l3-execute" }
)
$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
foreach ($item in $map) {
    $src = Join-Path $RepoRoot "scripts" $item.Name
    $dst = Join-Path $archive $item.Name
    if ($WhatIf) {
        Write-Host "WHATIF move $src -> $dst"
        continue
    }
    if (Test-Path $src) {
        $head = Get-Content $src -TotalCount 1 -ErrorAction SilentlyContinue
        if ($head -notmatch "SUNSET:") {
            Move-Item -Force $src $dst
        }
    }
    $stub = @(
        "# SUNSET: $($item.Layer) — archived to scripts/_retired/verify_marathon/$($item.Name)",
        "param([string]`$RuntimeRoot = `"D:\XINAO_RESEARCH_RUNTIME`")",
        "`$ErrorActionPreference = `"Stop`"",
        "`$RepoRoot = `"$RepoRoot`"",
        "`$py = `"$py`"",
        "& `$py -m xinao_seedlab.cli.__main__ $($item.Cli) --runtime-root `$RuntimeRoot --repo-root `$RepoRoot",
        "if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }",
        "& `$py -m xinao_seedlab.cli.__main__ thin-glue-status --runtime-root `$RuntimeRoot --repo-root `$RepoRoot",
        "exit `$LASTEXITCODE"
    ) -join "`n"
    Set-Content -Path $src -Value ($stub + "`n") -Encoding UTF8
}
Write-Host "thin-glue verify sunset archive OK"
exit 0