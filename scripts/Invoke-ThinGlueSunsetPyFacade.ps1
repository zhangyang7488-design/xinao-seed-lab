# 档2 sunset：手搓 .py 正文 → _retired + live 薄 facade（用户授权 2026-07-08）
param([switch]$WhatIf, [switch]$ArchiveOnly])

$ErrorActionPreference = "Stop"
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
Set-Location $RepoRoot
$archive = Join-Path $RepoRoot "services\agent_runtime\_retired"
New-Item -ItemType Directory -Force -Path $archive | Out-Null

$stubHeader = @'
"""SUNSET facade — handroll body archived to _retired; thin-glue bypass in archive entry."""
from services.agent_runtime._retired.{0} import *  # noqa: F401,F403
'@

# facade: live module -> archive name
$facadeMap = @(
    @{ Live = "current_task_source_intake.py"; Archive = "current_task_source_intake_handroll_v1.py" },
    @{ Live = "codex_native_provider_scheduler_phase4.py"; Archive = "codex_native_provider_scheduler_phase4_handroll_v1.py" },
    @{ Live = "codex_s_light_research_loop.py"; Archive = "codex_s_light_research_loop_handroll_v1.py" },
    @{ Live = "worker_dispatch_ledger.py"; Archive = "worker_dispatch_ledger_handroll_v1.py" },
    @{ Live = "pre_pass_audit_loop.py"; Archive = "pre_pass_audit_loop_handroll_v1.py" }
)

# archive-only (import 太深，live 保留委托入口)
$archiveOnly = @(
    @{ Live = "root_intent_loop_driver.py"; Archive = "root_intent_loop_driver_handroll_v1.py" },
    @{ Live = "modular_dynamic_worker_pool_phase1.py"; Archive = "modular_dynamic_worker_pool_phase1_handroll_v1.py" },
    @{ Live = "v4pro_mature_bind_execution_controller.py"; Archive = "v4pro_mature_bind_execution_controller_handroll_v1.py" }
)

function Copy-HandrollArchive($liveName, $archiveName) {
    $src = Join-Path (Join-Path $RepoRoot "services\agent_runtime") $liveName
    $dst = Join-Path $archive $archiveName
    if (-not (Test-Path $src)) {
        Write-Warning "skip missing $src"
        return $false
    }
    if ($WhatIf) {
        Write-Host "WHATIF copy $src -> $dst"
        return $true
    }
    Copy-Item -Force $src $dst
    return $true
}

function Write-FacadeStub($liveName, $archiveModule) {
    $livePath = Join-Path (Join-Path $RepoRoot "services\agent_runtime") $liveName
    $stub = $stubHeader -f $archiveModule
    if ($WhatIf) {
        Write-Host "WHATIF facade $livePath ($archiveModule)"
        return
    }
    [System.IO.File]::WriteAllText($livePath, $stub.TrimEnd() + "`n", [System.Text.UTF8Encoding]::new($false))
}

foreach ($item in $facadeMap) {
    $archiveModule = [System.IO.Path]::GetFileNameWithoutExtension($item.Archive)
    if (-not (Copy-HandrollArchive $item.Live $item.Archive)) { continue }
    if (-not $ArchiveOnly) {
        Write-FacadeStub $item.Live $archiveModule
    }
}

foreach ($item in $archiveOnly) {
    Copy-HandrollArchive $item.Live $item.Archive | Out-Null
}

Write-Host "thin-glue py sunset facade OK (facade=$(-not $ArchiveOnly))"
exit 0