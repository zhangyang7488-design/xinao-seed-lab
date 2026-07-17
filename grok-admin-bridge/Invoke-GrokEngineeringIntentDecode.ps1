#Requires -Version 5.1
<#
.SYNOPSIS
  Engineering intent decode land helper — ACI three beats + wire check (thin; no second OS).
.DESCRIPTION
  Aligns grok_live_field_intent_decode.v1.json + rule 36.
  ReadState = beat1 field snapshot (existence alone is NOT success).
  AfterChange = beat3 re-read slots (caller fills notes; script re-snaps).
  LandCheck = verify contract/rule wires + write D evidence.
  Does not replace live local inspection or external research; which one leads is dynamic.
  completion_claim_allowed=false always.
.PARAMETER Action
  ReadState | AfterChange | LandCheck | Status
.PARAMETER NoteCn
  Optional operator note (e.g. what external search found / what changed).
.PARAMETER Quiet
  Suppress console summary.
#>
param(
  [ValidateSet("ReadState", "AfterChange", "LandCheck", "Status")]
  [string]$Action = "LandCheck",
  [string]$NoteCn = "",
  [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$Bridge = $PSScriptRoot
$IslandRoot = Split-Path $Bridge -Parent
$Contract = Join-Path $Bridge "grok_live_field_intent_decode.v1.json"
$Rule36 = Join-Path $IslandRoot ".grok\rules\36-grok-live-field-intent-decode.md"
$CoreIndex = Join-Path $Bridge "grok_island_core_index.v1.json"
$L0 = Join-Path $IslandRoot ".grok\rules\00-grok-l0-bootstrap.md"
$Agents = Join-Path $IslandRoot "AGENTS.md"
$EvidenceRoot = "D:\XINAO_RESEARCH_RUNTIME\state\engineering_intent_decode"
$ReadbackRoot = "D:\XINAO_RESEARCH_RUNTIME\readback\zh"
$AmqRoot = "D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq"
$Checkpoint = "D:\XINAO_RESEARCH_RUNTIME\state\grok_4_5\session_context\latest.json"

New-Item -ItemType Directory -Force -Path $EvidenceRoot, $ReadbackRoot | Out-Null

function Write-JsonFile($obj, $path) {
  $json = $obj | ConvertTo-Json -Depth 14
  [System.IO.File]::WriteAllText($path, $json, [System.Text.UTF8Encoding]::new($false))
}

function Get-FieldSnapshot {
  $gitStatus = ""
  $gitBranch = ""
  try {
    Push-Location $IslandRoot
    $gitBranch = (& git rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
    $gitStatus = (& git status --porcelain 2>$null | Out-String).Trim()
    if ($gitStatus.Length -gt 4000) { $gitStatus = $gitStatus.Substring(0, 4000) + "...(trunc)" }
  } catch {
    $gitStatus = "git_unavailable: $($_.Exception.Message)"
  } finally {
    Pop-Location
  }

  $codexNew = 0
  $codexCur = 0
  $grokNew = 0
  if (Test-Path (Join-Path $AmqRoot "agents\codex\inbox\new")) {
    $codexNew = @(Get-ChildItem (Join-Path $AmqRoot "agents\codex\inbox\new") -File -ErrorAction SilentlyContinue).Count
  }
  if (Test-Path (Join-Path $AmqRoot "agents\codex\inbox\cur")) {
    $codexCur = @(Get-ChildItem (Join-Path $AmqRoot "agents\codex\inbox\cur") -File -ErrorAction SilentlyContinue).Count
  }
  if (Test-Path (Join-Path $AmqRoot "agents\grok\inbox\new")) {
    $grokNew = @(Get-ChildItem (Join-Path $AmqRoot "agents\grok\inbox\new") -File -ErrorAction SilentlyContinue).Count
  }

  $cpAt = $null
  if (Test-Path $Checkpoint) { $cpAt = (Get-Item $Checkpoint).LastWriteTime.ToString("o") }

  $naijiu = $null
  try {
    $c = docker ps --filter "name=naijiu-shiwu" --format "{{.Names}} {{.Status}}" 2>$null
    $naijiu = if ($c) { "$c".Trim() } else { "not_listed" }
  } catch { $naijiu = "docker_unavailable" }

  return [ordered]@{
    at = (Get-Date).ToString("o")
    island_root = $IslandRoot
    git_branch = $gitBranch
    git_porcelain_nonempty = [bool]$gitStatus
    git_porcelain_preview = $gitStatus
    checkpoint_latest_mtime = $cpAt
    amq_codex_inbox_new_count = $codexNew
    amq_codex_inbox_cur_count = $codexCur
    amq_grok_inbox_new_count = $grokNew
    temporal_container_naijiu_shiwu = $naijiu
    honesty_cn = "snapshot only; not completion; send-ok != peer-read; mock-green != live Temporal"
  }
}

function Get-WireCheck {
  $paths = @{
    contract = $Contract
    rule36 = $Rule36
    core_index = $CoreIndex
    l0 = $L0
    agents = $Agents
  }
  $items = @()
  foreach ($k in $paths.Keys) {
    $p = $paths[$k]
    $exists = Test-Path -LiteralPath $p
    $mentions = $false
    if ($exists) {
      $raw = Get-Content -LiteralPath $p -Raw -ErrorAction SilentlyContinue
      if ($raw -match "live_field_intent|ACI|engineering_intent|rule.?36|工程意图解码") { $mentions = $true }
    }
    $items += [ordered]@{
      id = $k
      path = $p
      exists = $exists
      mentions_intent_decode = $mentions
    }
  }
  $contractOk = $false
  if (Test-Path $Contract) {
    try {
      $j = Get-Content $Contract -Raw -Encoding UTF8 | ConvertFrom-Json
      $contractOk = ($j.aci_three_beats_cn -ne $null) -and ($j.agent_posture_cn.external_search_is_dynamic -eq $true)
    } catch { $contractOk = $false }
  }
  $allExist = ($items | Where-Object { -not $_.exists }).Count -eq 0
  return [ordered]@{
    all_paths_exist = $allExist
    contract_has_aci_and_dynamic_research = $contractOk
    items = $items
  }
}

$snap = Get-FieldSnapshot
$wires = Get-WireCheck
$out = [ordered]@{
  schema_version = "xinao.engineering_intent_decode_land.v2"
  sentinel = "SENTINEL:GROK_ENGINEERING_INTENT_DECODE_LAND"
  action = $Action
  generated_at = (Get-Date).ToString("o")
  completion_claim_allowed = $false
  product_closed = $false
  contract_ref = "grok_live_field_intent_decode.v1.json"
  rule_ref = ".grok/rules/36-grok-live-field-intent-decode.md"
  core_definition_cn = "口语=现场增量; 状态题本地live优先; 选型或高影响省略轻量外搜; ACI三拍"
  aci_three_beats_cn = @("读状态", "动手", "再读现象")
  research_selection = "dynamic_by_question_type"
  external_search_note_cn = "本脚本不替代 WebSearch，也不以 WebSearch 替代本地现场"
  note_cn = $NoteCn
  field_snapshot = $snap
  wire_check = $wires
  thin_borrow_cn = @{
    swe_agent = "ACI三拍 observation"
    codified = "热短冷按需"
    voyager = "做-跑-证据-再改"
    aider = "真改仓+git 纪律"
    forbid_install_main = @("SWE-agent整仓", "Aider替主窗", "19 domain agent")
  }
}

switch ($Action) {
  "ReadState" {
    $out.beat = "1_read_state"
    $out.ok = $true
  }
  "AfterChange" {
    $out.beat = "3_reread_phenomena"
    $out.ok = $true
    $out.requires_caller_cn = "调用方应在 NoteCn 写清改了什么; 本快照仅再读现场"
  }
  "LandCheck" {
    $out.beat = "land_wire_and_field"
    $out.ok = [bool]$wires.all_paths_exist -and [bool]$wires.contract_has_aci_and_dynamic_research
  }
  "Status" {
    $out.beat = "status"
    $prev = Join-Path $EvidenceRoot "latest.json"
    $out.previous_latest_exists = Test-Path $prev
    $out.ok = $true
  }
}

$latest = Join-Path $EvidenceRoot "latest.json"
$stamp = Join-Path $EvidenceRoot ("land_{0:yyyyMMdd_HHmmss}.json" -f (Get-Date))
Write-JsonFile $out $latest
Write-JsonFile $out $stamp

$rb = @"
# 工程意图解码落地

- 时间: $($out.generated_at)
- Action: $Action
- ok: $($out.ok)
- completion_claim_allowed: false
- 核心: 动态取证 + ACI 三拍（读状态→动手→再读现象）
- 接线: paths_exist=$($wires.all_paths_exist) contract_aci=$($wires.contract_has_aci_and_dynamic_research)
- 现场: git_dirty=$($snap.git_porcelain_nonempty) codex_inbox_new=$($snap.amq_codex_inbox_new_count) temporal=$($snap.temporal_container_naijiu_shiwu)
- 证据: $latest
- 诚实: 本落地=岛内行为合同+观察入口; 非双脑整包闭合; 非第二 OS

"@
$rbPath = Join-Path $ReadbackRoot "engineering_intent_decode_land_latest.md"
[System.IO.File]::WriteAllText($rbPath, $rb, [System.Text.UTF8Encoding]::new($false))
$out.readback_zh = $rbPath
$out.evidence_latest = $latest
Write-JsonFile $out $latest

if (-not $Quiet) {
  Write-Host ("ENGINEERING_INTENT_DECODE action={0} ok={1} evidence={2}" -f $Action, $out.ok, $latest)
  Write-Host ("  wires paths_exist={0} contract_aci={1}" -f $wires.all_paths_exist, $wires.contract_has_aci_and_dynamic_research)
  Write-Host ("  field git_dirty={0} codex_new={1} temporal={2}" -f $snap.git_porcelain_nonempty, $snap.amq_codex_inbox_new_count, $snap.temporal_container_naijiu_shiwu)
}

$out | ConvertTo-Json -Depth 14
