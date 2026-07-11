#Requires -Version 5.1
<#
.SYNOPSIS
  Secretary preload enforce: verify T0 path pointers exist; write evidence state.
.DESCRIPTION
  Aligns F pack + grok_secretary_preload_enforce.v1.json.
  Check = path existence only (fail-open; does not lock session).
  Does NOT claim platform runtime hook or P0/333 closed.
.PARAMETER Action
  Check | Status
.PARAMETER Quiet
  Suppress console summary.
#>
param(
  [ValidateSet("Check", "Status")]
  [string]$Action = "Check",
  [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$Bridge = $PSScriptRoot
$IslandRoot = Split-Path $Bridge -Parent
$Contract = Join-Path $Bridge "grok_secretary_preload_enforce.v1.json"
$EvidenceRoot = "D:\XINAO_RESEARCH_RUNTIME\state\secretary_preload"
$ReadbackRoot = "D:\XINAO_RESEARCH_RUNTIME\readback\zh"
$SuperLoopNs = "D:\XINAO_RESEARCH_RUNTIME\state\contract_super_loop"

New-Item -ItemType Directory -Force -Path $EvidenceRoot, $ReadbackRoot, $SuperLoopNs | Out-Null

function Write-Json($obj, $path) {
  $json = $obj | ConvertTo-Json -Depth 12
  [System.IO.File]::WriteAllText($path, $json, [System.Text.UTF8Encoding]::new($false))
}

# T0 path pointers (existence check; no full-text load)
$t0 = @(
  [pscustomobject]@{
    id = "checkpoint_4_5"
    path = "D:\XINAO_RESEARCH_RUNTIME\state\grok_4_5\session_context\latest.json"
    required_any_of = "checkpoint"
  }
  [pscustomobject]@{
    id = "checkpoint_admin"
    path = "D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context\latest.json"
    required_any_of = "checkpoint"
  }
  [pscustomobject]@{
    id = "standing"
    path = (Join-Path $Bridge "grok_user_standing_relationship.v1.json")
    required_any_of = $null
  }
  [pscustomobject]@{
    id = "thinking_distill"
    path = (Join-Path $Bridge "grok_external_mature_thinking_distill.v1.json")
    required_any_of = $null
  }
  [pscustomobject]@{
    id = "memory_prefs"
    path = "C:\Users\xx363\.grok\memory\MEMORY.md"
    required_any_of = $null
  }
  [pscustomobject]@{
    id = "l0_rule"
    path = (Join-Path $IslandRoot ".grok\rules\00-grok-l0-bootstrap.md")
    required_any_of = $null
  }
  [pscustomobject]@{
    id = "core_index"
    path = (Join-Path $Bridge "grok_island_core_index.v1.json")
    required_any_of = $null
  }
  [pscustomobject]@{
    id = "preload_enforce_contract"
    path = $Contract
    required_any_of = $null
  }
  [pscustomobject]@{
    id = "skill_secretary"
    path = "C:\Users\xx363\.grok-4.5-lane\skills\user-intent-secretary\SKILL.md"
    required_any_of = $null
  }
  [pscustomobject]@{
    id = "f_pack"
    path = "D:\XINAO_RESEARCH_RUNTIME\state\contract_super_loop\F_preload_stack_for_secretary_latest.json"
    required_any_of = $null
  }
  [pscustomobject]@{
    id = "checkpoint_script"
    path = (Join-Path $Bridge "Invoke-GrokSessionContextCheckpoint.ps1")
    required_any_of = $null
  }
)

$checks = @()
foreach ($item in $t0) {
  $ok = Test-Path -LiteralPath $item.path
  $checks += [ordered]@{
    id = $item.id
    path = $item.path
    exists = [bool]$ok
    required_any_of = $item.required_any_of
  }
}

$checkpointOk = ($checks | Where-Object { $_.required_any_of -eq "checkpoint" -and $_.exists }).Count -gt 0
$hardRequired = $checks | Where-Object { -not $_.required_any_of -and $_.id -ne "f_pack" }
$hardMissing = @($hardRequired | Where-Object { -not $_.exists })
$allHardOk = ($hardMissing.Count -eq 0) -and $checkpointOk

$forbidNote = @(
  "do_not_default_preload_rules_32_35_bodies",
  "do_not_default_preload_333_runbook_full",
  "do_not_stuff_all_rules_into_always_on",
  "t3_only_on_autonomous_continuous_explicit"
)

$result = [ordered]@{
  schema_version = "xinao.secretary_preload_check.v1"
  sentinel = "SENTINEL:SECRETARY_PRELOAD_CHECK"
  generated_at = (Get-Date).ToString("o")
  action = $Action
  contract_ok = (Test-Path -LiteralPath $Contract)
  t0_all_hard_paths_ok = $allHardOk
  checkpoint_any_ok = $checkpointOk
  hard_missing = @($hardMissing | ForEach-Object { $_.id })
  checks = $checks
  enforce_read_order_cn = @(
    "checkpoint -Read",
    "standing essence",
    "distill pointer (A03/A04)",
    "MEMORY prefs",
    "L0 sentinel",
    "skills L1 catalog + core_index pointer"
  )
  mode_gates_short = @{
    T0 = "always_on_dialogue"
    T1 = "session_or_mode"
    T2 = "task_triggered"
    T3 = "autonomous_only_rules_32_35"
  }
  forbid_default_preload = $forbidNote
  fail_open = $true
  completion_claim_allowed = $false
  now_can_do_cn = @(
    "Invoke-GrokSecretaryPreloadCheck.ps1 -Action Check",
    "新会话先 Invoke-GrokSessionContextCheckpoint.ps1 -Read",
    "读 grok_secretary_preload_enforce.v1.json T0 清单",
    "skill user-intent-secretary preload 段"
  )
}

$latest = Join-Path $EvidenceRoot "latest.json"
Write-Json $result $latest

$n2 = [ordered]@{
  schema_version = "xinao.contract_super_loop.N2_secretary_preload_enforce.v1"
  sentinel = "SENTINEL:N2_SECRETARY_PRELOAD_ENFORCE"
  agent_id = "N2"
  written_at = (Get-Date).ToString("o")
  completion_claim_allowed = $false
  contract = "grok_secretary_preload_enforce.v1.json"
  script = "Invoke-GrokSecretaryPreloadCheck.ps1"
  check_snapshot = $result
  files_touched_expected = @(
    "grok-admin-bridge/grok_secretary_preload_enforce.v1.json",
    "grok-admin-bridge/Invoke-GrokSecretaryPreloadCheck.ps1",
    "user-intent-secretary/SKILL.md",
    ".grok/rules/00-grok-l0-bootstrap.md",
    "grok_user_standing_relationship.v1.json",
    "grok_island_core_index.v1.json"
  )
  not_claims = @(
    "platform_hard_hook_not_claimed",
    "p0_333_not_closed",
    "desktop_not_deleted"
  )
}
Write-Json $n2 (Join-Path $SuperLoopNs "N2_secretary_preload_enforce_latest.json")

$rb = @"
# 秘书预载 enforce 检查 · 中文回读

- 时间：$($result.generated_at)
- 合同：``grok_secretary_preload_enforce.v1.json``
- T0 硬路径齐：$($result.t0_all_hard_paths_ok)
- checkpoint 任一存在：$($result.checkpoint_any_ok)
- 缺失：$(($result.hard_missing -join ', '))
- fail-open：是（路径缺不锁会话）
- ``completion_claim_allowed=false``

## 新会话 T0 读序

1. checkpoint -Read
2. standing 精华
3. distill 指针（A03/A04）
4. MEMORY / L0 / skills 名册 / core_index 指针

## 禁止默认预载

- rule 32–35 正文（仅 T3 autonomous）
- 333 runbook 全文
- 整仓 rules / 全 skill 正文

## 证据

- ``$latest``
- ``$SuperLoopNs\N2_secretary_preload_enforce_latest.json``
"@
$rbPath = Join-Path $ReadbackRoot "secretary_preload_enforce_latest.md"
[System.IO.File]::WriteAllText($rbPath, $rb, [System.Text.UTF8Encoding]::new($false))

if (-not $Quiet) {
  Write-Host "secretary_preload: t0_all_hard_paths_ok=$allHardOk checkpoint_any_ok=$checkpointOk"
  Write-Host "evidence: $latest"
  if ($hardMissing.Count -gt 0) {
    Write-Host "hard_missing: $($result.hard_missing -join ', ')"
  }
}

return $result
