#Requires -Version 5.1
<#
.SYNOPSIS
  暴露工具目录：把 scan/sense/GDP 等全部登记为可 invoke 能力面条目。
  共享 Grok+后台；禁止安全面；非新控制面。
.EXAMPLE
  .\Invoke-GrokExposedToolsCatalog.ps1
  .\Invoke-GrokExposedToolsCatalog.ps1 -RefreshRegistry
#>
param(
    [switch]$RefreshRegistry,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\exposed_tools_catalog"
$latestPath = Join-Path $outDir "latest.json"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 18), $utf8)
}

if ($RefreshRegistry) {
    & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet 2>$null | Out-Null
}

$scanBin = "E:\XINAO_EXTERNAL_MATURE\scan-stack\bin"
$senseBin = "E:\XINAO_EXTERNAL_MATURE\state-sense-stack\bin"
$scanPy = "E:\XINAO_EXTERNAL_MATURE\scan-stack\py\.venv\Scripts"
$scanNpm = "E:\XINAO_EXTERNAL_MATURE\scan-stack\npm\node_modules\.bin"

$tools = [System.Collections.Generic.List[object]]::new()

function Add-Tool {
    param(
        [string]$Id,
        [string]$Layer,
        [string]$Role,
        [string]$Path,
        [string]$Invoke,
        [string]$Surface = "shared",
        [bool]$NotBrain = $false
    )
    $on = if ($Path) { Test-Path -LiteralPath $Path } else { $true }
    [void]$tools.Add([ordered]@{
        id = $Id
        layer = $Layer
        role = $Role
        path = $Path
        on_disk = $on
        claim_state = if ($on) { "registered_and_hooked" } else { "missing" }
        invoke = $Invoke
        surface = $Surface
        not_strategy_brain = $NotBrain
        exposed = $on
        security_goal = $false
        control_plane = $false
    })
}

# --- bridge scripts (primary invoke surface) ---
Add-Tool "scan_stack" "bridge" "policy_scan_orchestrator" (Join-Path $bridge "Invoke-GrokScanStack.ps1") "Invoke-GrokScanStack.ps1 -PolicyScan|-List|-Run"
Add-Tool "state_sense_max" "bridge" "extreme_state_perception" (Join-Path $bridge "Invoke-GrokStateSenseMax.ps1") "Invoke-GrokStateSenseMax.ps1"
Add-Tool "local_state_sense" "bridge" "state_snapshot" (Join-Path $bridge "Get-GrokLocalStateSense.ps1") "Get-GrokLocalStateSense.ps1"
Add-Tool "gap_driven_progressor" "bridge" "intent_reality_gap" (Join-Path $bridge "Invoke-GrokGapDrivenProgressor.ps1") "Invoke-GrokGapDrivenProgressor.ps1 -PushQueue"
Add-Tool "loop_guardian" "bridge" "stall_guard" (Join-Path $bridge "Invoke-GrokLoopGuardian.ps1") "Invoke-GrokLoopGuardian.ps1 -ForceProgressor"
Add-Tool "registry_scan" "bridge" "capability_registry" (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") "Invoke-GrokLocalCapabilityRegistryScan.ps1"
Add-Tool "capability_status" "bridge" "self_status" (Join-Path $bridge "Get-GrokLocalCapabilityStatus.ps1") "Get-GrokLocalCapabilityStatus.ps1"
Add-Tool "capability_claim_weld" "bridge" "claim_weld" (Join-Path $bridge "Invoke-GrokCapabilitySurfaceClaimWeld.ps1") "Invoke-GrokCapabilitySurfaceClaimWeld.ps1 -Apply|-Status"
Add-Tool "exposed_tools_catalog" "bridge" "this_catalog" (Join-Path $bridge "Invoke-GrokExposedToolsCatalog.ps1") "Invoke-GrokExposedToolsCatalog.ps1"

# --- scan-stack CLIs ---
$cliMap = @(
    @{ id="opengrep"; p="$scanBin\opengrep.exe"; layer="T0_rule"; inv="Invoke-GrokScanStack.ps1 -Run -Tool opengrep" },
    @{ id="opengrep-core"; p="$scanBin\opengrep-core.exe"; layer="T0_rule"; inv="opengrep-core" },
    @{ id="semgrep"; p="$scanPy\semgrep.exe"; layer="T0_rule"; inv="Invoke-GrokScanStack.ps1 -Run -Tool semgrep" },
    @{ id="ast-grep"; p="$scanBin\ast-grep.exe"; layer="T0_struct"; inv="Invoke-GrokScanStack.ps1 -Run -Tool ast-grep" },
    @{ id="conftest"; p="$scanBin\conftest.exe"; layer="T0_policy"; inv="Invoke-GrokScanStack.ps1 -Run -Tool conftest" },
    @{ id="opa"; p="$scanBin\opa.exe"; layer="T0_policy"; inv="Invoke-GrokScanStack.ps1 -Run -Tool opa" },
    @{ id="regal"; p="$scanBin\regal.exe"; layer="T0_policy"; inv="Invoke-GrokScanStack.ps1 -Run -Tool regal" },
    @{ id="rg"; p="$scanBin\rg.exe"; layer="T0_discovery"; inv="rg"; nb=$true },
    @{ id="ugrep"; p="$scanBin\ugrep.exe"; layer="T0_discovery"; inv="ugrep"; nb=$true },
    @{ id="ugrep-indexer"; p="$scanBin\ugrep-indexer.exe"; layer="T0_discovery"; inv="ugrep-indexer"; nb=$true },
    @{ id="fd"; p="$scanBin\fd.exe"; layer="T0_discovery"; inv="fd"; nb=$true },
    @{ id="scc"; p="$senseBin\scc.exe"; layer="T1_stats"; inv="scc" },
    @{ id="tokei"; p="$senseBin\tokei.exe"; layer="T1_stats"; inv="tokei" },
    @{ id="dive"; p="$senseBin\dive.exe"; layer="T1_docker"; inv="dive" },
    @{ id="watchexec"; p="$senseBin\watchexec.exe"; layer="T1_watch"; inv="watchexec" },
    @{ id="hadolint"; p="$scanBin\hadolint.exe"; layer="T1_hygiene"; inv="hadolint" },
    @{ id="shellcheck"; p="$scanBin\shellcheck.exe"; layer="T1_hygiene"; inv="shellcheck" },
    @{ id="import-linter"; p="$scanPy\lint-imports.exe"; layer="T1_arch"; inv="lint-imports" },
    @{ id="tach"; p="$scanPy\tach.exe"; layer="T1_arch"; inv="tach" },
    @{ id="vulture"; p="$scanPy\vulture.exe"; layer="T1_dead"; inv="vulture" },
    @{ id="ruff"; p="$scanPy\ruff.exe"; layer="T1_hygiene"; inv="ruff" },
    @{ id="check-jsonschema"; p="$scanPy\check-jsonschema.exe"; layer="T1_contract"; inv="check-jsonschema" },
    @{ id="pre-commit"; p="$scanPy\pre-commit.exe"; layer="T1_orch"; inv="pre-commit" },
    @{ id="pydeps"; p="$scanPy\pydeps.exe"; layer="T1_arch"; inv="pydeps" },
    @{ id="knip"; p="$scanNpm\knip.cmd"; layer="T1_dead"; inv="knip" },
    @{ id="depcruise"; p="$scanNpm\depcruise.cmd"; layer="T1_arch"; inv="depcruise" },
    @{ id="spectral"; p="$scanNpm\spectral.cmd"; layer="T1_contract"; inv="spectral" },
    @{ id="repomix"; p="$scanNpm\repomix.cmd"; layer="T1_pack"; inv="repomix" }
)
foreach ($c in $cliMap) {
    Add-Tool $c.id $c.layer "cli" $c.p $c.inv -NotBrain ([bool]$c.nb)
}

# system shared
foreach ($sys in @(
    @{ id="git"; p=(Get-Command git -EA SilentlyContinue).Source },
    @{ id="gh"; p=(Get-Command gh -EA SilentlyContinue).Source },
    @{ id="docker"; p=(Get-Command docker -EA SilentlyContinue).Source }
)) {
    if ($sys.p) { Add-Tool $sys.id "system" "runtime" $sys.p $sys.id }
}

# tools index keys
$idxPath = Join-Path $bridge "grok_operational_tools_index.v1.json"
$idxKeys = @()
if (Test-Path $idxPath) {
    $idx = Get-Content $idxPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $idxKeys = @($idx.tools.PSObject.Properties.Name)
}

$exposed = @($tools | Where-Object { $_.exposed })
$missing = @($tools | Where-Object { -not $_.exposed })

# security blocklist explicit not-exposed
$neverExpose = @("Trivy","Grype","OSV","Gitleaks","TruffleHog","secret_surface_scan")

$result = [ordered]@{
    schema_version = "xinao.exposed_tools_catalog.v1"
    sentinel       = "SENTINEL:EXPOSED_TOOLS_CATALOG"
    generated_at   = (Get-Date).ToString("o")
    purpose_cn     = "能力面暴露目录：全部可 invoke 工具登记；共享；非控制面；非安全目标"
    auth_shape_cn  = "deny_list_not_allow_list"
    shared_capability = $true
    not_control_plane = $true
    never_expose_security = $neverExpose
    tools_index_keys = $idxKeys
    counts = [ordered]@{
        total_catalog = $tools.Count
        exposed_usable = $exposed.Count
        missing = $missing.Count
        tools_index = $idxKeys.Count
    }
    tools = @($tools)
    missing = @($missing | ForEach-Object { $_.id })
    now_can_invoke_cn = @(
        "Invoke-GrokExposedToolsCatalog.ps1",
        "Invoke-GrokScanStack.ps1 -List|-PolicyScan",
        "Invoke-GrokStateSenseMax.ps1",
        "Invoke-GrokGapDrivenProgressor.ps1 -PushQueue",
        "Invoke-GrokLocalCapabilityRegistryScan.ps1",
        ". E:\XINAO_EXTERNAL_MATURE\scan-stack\env.ps1",
        ". E:\XINAO_EXTERNAL_MATURE\state-sense-stack\env.ps1"
    )
    evidence = $latestPath
    completion_claim_allowed = $false
}

Write-JsonFile $latestPath $result
$stamp = Join-Path $outDir ("catalog_{0:yyyyMMdd_HHmmss}.json" -f (Get-Date))
Write-JsonFile $stamp $result

# human readback
$md = Join-Path $runtime "readback\zh\exposed_tools_catalog_latest.md"
New-Item -ItemType Directory -Force -Path (Split-Path $md) | Out-Null
$lines = @(
    "# 暴露工具目录（能力面）",
    "",
    "生成：$((Get-Date).ToString('o'))",
    "",
    "- 可用/登记：**$($exposed.Count)/$($tools.Count)**",
    "- tools_index 键：**$($idxKeys.Count)**",
    "- 共享：Grok + 后台 · 禁止清单 · **非** 333 控制面 · **无** 安全扫描目标",
    "",
    "## 主入口",
    ""
)
foreach ($t in ($tools | Where-Object { $_.layer -eq "bridge" -and $_.exposed })) {
    $lines += "- ``$($t.id)`` → ``$($t.invoke)``"
}
$lines += ""
$lines += "## CLI 引擎（暴露）"
$lines += ""
foreach ($t in ($tools | Where-Object { $_.layer -ne "bridge" -and $_.layer -ne "system" -and $_.exposed })) {
    $lines += "- ``$($t.id)`` [$($t.layer)]"
}
[System.IO.File]::WriteAllText($md, ($lines -join "`n"), $utf8)

if (-not $Quiet) {
    Write-Host "exposed_tools usable=$($exposed.Count)/$($tools.Count) index_keys=$($idxKeys.Count)"
    Write-Host "evidence: $latestPath"
    Write-Host "readback: $md"
}
$result
