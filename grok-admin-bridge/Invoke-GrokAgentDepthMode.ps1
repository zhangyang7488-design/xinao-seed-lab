#Requires -Version 5.1
<#
.SYNOPSIS
  Agent Depth + Reflexion mode: status, progressive S context load, self-critique evidence.
.DESCRIPTION
  Mature thin-bind of ReAct / Reflexion / progressive disclosure / anti fake-completion.
  Does NOT dump full S repo. Does NOT claim P0/333 closed.
#>
param(
  [switch]$Status,
  [ValidateSet(0,1,2,3)]
  [int]$LoadTier = -1,
  [switch]$SelfCritique,
  [string]$SummaryCn = "",
  [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$EvidenceRoot = "D:\XINAO_RESEARCH_RUNTIME\state\agent_depth_mode"
$ReadbackRoot = "D:\XINAO_RESEARCH_RUNTIME\readback\zh"
$SRoot = "E:\XINAO_RESEARCH_WORKSPACES\S"
$Contract = Join-Path $PSScriptRoot "grok_agent_depth_reflexion_mode.v1.json"

New-Item -ItemType Directory -Force -Path $EvidenceRoot, $ReadbackRoot | Out-Null

function Write-Json($obj, $path) {
  $json = $obj | ConvertTo-Json -Depth 10
  [System.IO.File]::WriteAllText($path, $json, [System.Text.UTF8Encoding]::new($false))
}

$tierFiles = @{
  0 = @(
    "C:\Users\xx363\Grok_Admin_Isolated\workspace-grok-4.5-island\grok-admin-bridge\grok_island_core_index.v1.json"
  )
  1 = @(
    (Join-Path $SRoot "SEED_CORTEX_MUST_READ_FIRST.md"),
    (Join-Path $SRoot "CODEX_S_L0.md")
  )
  2 = @(
    (Join-Path $SRoot "contracts\schemas\meta_rsi_wave.v1.json"),
    (Join-Path $SRoot "scripts\hardmode\Write-MetaRsiWave.ps1")
  )
  3 = @(
    (Join-Path $SRoot "AGENTS.md"),
    (Join-Path $SRoot "docs")
  )
}

$loaded = @()
$missing = @()
$excerpts = @()

if ($LoadTier -ge 0) {
  for ($t = 0; $t -le $LoadTier; $t++) {
    foreach ($p in $tierFiles[$t]) {
      if (Test-Path -LiteralPath $p) {
        $item = Get-Item -LiteralPath $p
        if ($item.PSIsContainer) {
          $loaded += [pscustomobject]@{ tier = $t; path = $p; kind = "dir"; note = "list_only_progressive" }
        } else {
          $raw = Get-Content -LiteralPath $p -Raw -ErrorAction SilentlyContinue
          $head = if ($raw) { $raw.Substring(0, [Math]::Min(1200, $raw.Length)) } else { "" }
          $loaded += [pscustomobject]@{ tier = $t; path = $p; kind = "file"; bytes = $item.Length }
          $excerpts += [pscustomobject]@{ path = $p; head = $head }
        }
      } else {
        $missing += [pscustomobject]@{ tier = $t; path = $p }
      }
    }
  }
}

$skillPath = "C:\Users\xx363\.grok-4.5-lane\skills\agent-depth-reflexion\SKILL.md"
$rulePath = "C:\Users\xx363\Grok_Admin_Isolated\workspace-grok-4.5-island\.grok\rules\29-grok-agent-depth-reflexion.md"

$critique = $null
if ($SelfCritique) {
  $critique = @{
    at = (Get-Date).ToString("o")
    summary_cn = $SummaryCn
    checklist = @(
      "react_tools_used_not_only_language",
      "external_mature_searched_if_platform",
      "s_context_progressive_not_full_dump",
      "claims_have_evidence_or_admitted_gap",
      "completion_claim_allowed_false_if_open"
    )
    note_cn = "自批清单；真实批判须绑定当轮命令输出/文件证据"
  }
}

$result = [ordered]@{
  schema_version = "xinao.agent_depth_mode.invoke.v1"
  sentinel = "SENTINEL:AGENT_DEPTH_MODE"
  generated_at = (Get-Date).ToString("o")
  contract_ok = (Test-Path $Contract)
  skill_ok = (Test-Path $skillPath)
  rule_ok = (Test-Path $rulePath)
  load_tier = $LoadTier
  loaded = $loaded
  missing = $missing
  self_critique = $critique
  prior_art_short = @("ReAct", "Reflexion", "agentskills progressive disclosure", "tool-grounded critique")
  temperature_honesty_cn = "窗内未暴露 temperature；不声称最优温区"
  completion_claim_allowed = $false
  not_333_mainline = $true
  now_can_do_cn = @(
    "读 skill agent-depth-reflexion",
    "Invoke-GrokAgentDepthMode.ps1 -LoadTier 1|2",
    "平台任务走 mature-first + ReAct 工具环",
    "交付前 verification；能力不足承认+外搜"
  )
}

$latest = Join-Path $EvidenceRoot "latest.json"
Write-Json $result $latest

# optional excerpt file for agents (not full dump)
if ($excerpts.Count -gt 0) {
  $exPath = Join-Path $EvidenceRoot "tier_excerpts_latest.json"
  Write-Json @{ generated_at = $result.generated_at; excerpts = $excerpts } $exPath
  $result.excerpts_ref = $exPath
  Write-Json $result $latest
}

$md = @"
# Agent Depth Mode · 状态

- 时间: $($result.generated_at)
- contract: $($result.contract_ok) skill: $($result.skill_ok) rule: $($result.rule_ok)
- LoadTier: $LoadTier
- loaded: $($loaded.Count) missing: $($missing.Count)
- completion_claim_allowed: false

## Prior art
ReAct · Reflexion · agentskills progressive disclosure · tool-grounded critique

## now_can_do
$($result.now_can_do_cn -join "`n")
"@
[System.IO.File]::WriteAllText((Join-Path $ReadbackRoot "agent_depth_mode_latest.md"), $md, [System.Text.UTF8Encoding]::new($true))

if (-not $Quiet) {
  $result | ConvertTo-Json -Depth 8
}

exit 0
