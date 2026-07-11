#Requires -Version 5.1
<#
.SYNOPSIS
  任务入口：多样投递 → 单一认领（333 intake）→ 诚实 durable 探针；分解留给波内。
.NOT_333_MAINLINE false — 这是 333 默认入口壳；Grok/Codex 不当 Temporal owner。
#>
[CmdletBinding(DefaultParameterSetName = "Sentence")]
param(
    [Parameter(ParameterSetName = "Sentence")]
    [string]$Intent,

    [Parameter(ParameterSetName = "Text")]
    [string]$InputText,

    [Parameter(ParameterSetName = "Path")]
    [string]$InputFile,

    [Parameter(ParameterSetName = "Dir")]
    [string]$InputDir,

    [Parameter(ParameterSetName = "TaskFile")]
    [string]$TaskFile,

    [string]$ConfigPath = "",
    [ValidateSet("auto", "sentence", "text", "path", "dir", "taskfile", "cli")]
    [string]$EntryKind = "auto",
    [ValidateSet("grok", "codex", "cli")]
    [string]$DeliveryShell = "grok",
    [switch]$TryDurableClaim,
    [switch]$TryCodexProxy,
    [switch]$NoWrite,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $ConfigPath
$stateRoot = Join-Path $runtime "state\task_entry"
$intakeDir = Join-Path $stateRoot "intake"
$l0Dir = Join-Path $stateRoot "l0_material"
$l1Dir = Join-Path $stateRoot "l1_structured"
New-Item -ItemType Directory -Force -Path $intakeDir, $l0Dir, $l1Dir | Out-Null

function New-TaskId {
    "task-entry-{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
}

function Get-FileSha256([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $h = [System.Security.Cryptography.SHA256]::Create()
    try {
        $fs = [System.IO.File]::OpenRead($Path)
        try { return ([BitConverter]::ToString($h.ComputeHash($fs)) -replace "-", "").ToLowerInvariant() }
        finally { $fs.Dispose() }
    }
    finally { $h.Dispose() }
}

function Parse-BlockBTaskFile([string]$Path) {
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $parsed = [ordered]@{
        intent      = ""
        entry       = ""
        source      = ""
        acceptance  = @()
        constraints = @()
        body        = ""
        raw_path    = $Path
    }
    if ($raw -match '(?m)^intent:\s*(.+)$') { $parsed.intent = $Matches[1].Trim() }
    if ($raw -match '(?m)^entry:\s*(.+)$') { $parsed.entry = $Matches[1].Trim().ToLowerInvariant() }
    if ($raw -match '(?m)^source:\s*(.+)$') { $parsed.source = $Matches[1].Trim() }
    $acc = [regex]::Matches($raw, '(?m)^acceptance:\s*$([\s\S]*?)(?=^约束:|^正文|\z)')
    if ($acc.Count -gt 0) {
        $parsed.acceptance = @($acc[0].Groups[1].Value -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^-' })
    }
    if ($raw -match '(?m)正文[^:]*:\s*([\s\S]+)$') { $parsed.body = $Matches[1].Trim() }
    return [pscustomobject]$parsed
}

function Get-SRepoPython([string]$RepoRoot) {
    $py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $py -PathType Leaf) { return $py }
    return $null
}

function Invoke-MatureThinGlueL0Path {
    param([string]$RepoRoot, [string]$TargetPath)
    $py = Get-SRepoPython -RepoRoot $RepoRoot
    if (-not $py) { return @{ ok = $false; named_blocker = "S_VENV_PYTHON_MISSING" } }
    $oldPy = $env:PYTHONPATH
    $oldWarn = $env:PYTHONWARNINGS
    $env:PYTHONPATH = "$RepoRoot\src;$RepoRoot"
    $env:PYTHONWARNINGS = "ignore"
    try {
        $escaped = $TargetPath.Replace("'", "''")
        $code = "import json; from pathlib import Path; from services.agent_runtime.thin_glue_stack import l0_intake_markdown; print(json.dumps(l0_intake_markdown(Path(r'''$escaped''')), ensure_ascii=False))"
        $raw = & $py -c $code 2>$null | Out-String
        if ($LASTEXITCODE -ne 0) { return @{ ok = $false; named_blocker = "THIN_GLUE_L0_INVOKE_FAILED"; stderr = $raw } }
        $jsonLine = ($raw -split "`n" | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1)
        if (-not $jsonLine) { return @{ ok = $false; named_blocker = "THIN_GLUE_L0_JSON_MISSING"; stderr = $raw } }
        return @{ ok = $true; payload = ($jsonLine.Trim() | ConvertFrom-Json) }
    }
    finally {
        $env:PYTHONPATH = $oldPy
        $env:PYTHONWARNINGS = $oldWarn
    }
}

function Invoke-MatureThinGlueL0Dir {
    param([string]$RepoRoot, [string]$RuntimeRoot, [string]$TargetDir)
    $py = Get-SRepoPython -RepoRoot $RepoRoot
    if (-not $py) { return @{ ok = $false; named_blocker = "S_VENV_PYTHON_MISSING" } }
    $oldPy = $env:PYTHONPATH
    $env:PYTHONPATH = "$RepoRoot\src;$RepoRoot"
    try {
        & $py -m xinao_seedlab.cli.__main__ thin-glue-intake `
            --runtime-root $RuntimeRoot --repo-root $RepoRoot --materials-dir $TargetDir 2>&1 | Out-Null
        $thinLatest = Join-Path $RuntimeRoot "state\thin_glue_intake\latest.json"
        if (-not (Test-Path -LiteralPath $thinLatest)) {
            return @{ ok = $false; named_blocker = "THIN_GLUE_INTAKE_EVIDENCE_MISSING" }
        }
        return @{ ok = $true; payload = (Get-Content $thinLatest -Raw -Encoding UTF8 | ConvertFrom-Json); evidence_ref = $thinLatest }
    }
    finally { $env:PYTHONPATH = $oldPy }
}

function Read-L0Material {
    param(
        [string]$Kind,
        [string]$IntentLine,
        [string]$Text,
        [string]$File,
        [string]$Dir,
        $BlockB,
        [string]$RepoRoot,
        [string]$RuntimeRoot,
        [string]$StagingDir
    )
    $l0 = [ordered]@{
        schema_version     = "xinao.task_entry.l0_intake.v1"
        read_at            = (Get-Date).ToString("o")
        entry_kind         = $Kind
        intent_one_liner   = $IntentLine
        material_refs      = @()
        raw_text_excerpt   = ""
        dir_manifest       = @()
        byte_count         = 0
        markitdown_used    = $false
        mature_glue_ref    = "S/services/agent_runtime/thin_glue_stack.py::l0_intake_markdown"
        thin_glue_evidence = $null
        named_blocker      = $null
    }
    $targetPath = $null
    if ($Kind -eq "path") {
        $targetPath = if ($BlockB -and $BlockB.source -and (Test-Path -LiteralPath $BlockB.source)) { $BlockB.source } else { $File }
    }
    elseif ($Kind -eq "taskfile") {
        if ($BlockB -and $BlockB.source -and (Test-Path -LiteralPath $BlockB.source -PathType Leaf)) { $targetPath = $BlockB.source }
        elseif ($BlockB -and $BlockB.entry -eq "path" -and $BlockB.source) { $targetPath = $BlockB.source }
    }
    if ($targetPath) {
        if (-not (Test-Path -LiteralPath $targetPath)) {
            $l0.named_blocker = "L0_PATH_NOT_FOUND"
            return $l0
        }
        $mg = Invoke-MatureThinGlueL0Path -RepoRoot $RepoRoot -TargetPath $targetPath
        if (-not $mg.ok) { $l0.named_blocker = $mg.named_blocker; return $l0 }
        $p = $mg.payload
        $l0.markitdown_used = ($p.adapter -eq "markitdown")
        $l0.raw_text_excerpt = [string]$p.content_md
        $l0.byte_count = [int]$p.char_count
        $l0.material_refs = @($targetPath)
        $l0.thin_glue_evidence = $p
        $l0 | Add-Member -NotePropertyName file_sha256 -NotePropertyValue (Get-FileSha256 $targetPath)
        return $l0
    }
    if ($Kind -eq "dir" -or ($Kind -eq "taskfile" -and $BlockB -and $BlockB.entry -eq "dir")) {
        $targetDir = if ($Dir) { $Dir } else { $BlockB.source }
        if (-not (Test-Path -LiteralPath $targetDir -PathType Container)) {
            $l0.named_blocker = "L0_DIR_NOT_FOUND"
            return $l0
        }
        $mg = Invoke-MatureThinGlueL0Dir -RepoRoot $RepoRoot -RuntimeRoot $RuntimeRoot -TargetDir $targetDir
        if (-not $mg.ok) { $l0.named_blocker = $mg.named_blocker; return $l0 }
        $l0.markitdown_used = $true
        $l0.material_refs = @($targetDir)
        $l0.thin_glue_evidence = $mg.evidence_ref
        $l0.raw_text_excerpt = "thin_glue_intake entries=$($mg.payload.source_ledger.entry_count)"
        if ($mg.payload.source_ledger.entries) {
            foreach ($e in $mg.payload.source_ledger.entries) {
                $l0.dir_manifest += [ordered]@{ path = $e.source_path; excerpt = $e.content_excerpt }
            }
        }
        return $l0
    }
    # sentence/text/taskfile-body: staging txt → mature l0_intake_markdown（禁手搓 Get-Content 当 L0 默认）
    $body = switch ($Kind) {
        "text" { if ($BlockB -and $BlockB.body) { $BlockB.body } else { $Text } }
        "taskfile" { if ($BlockB -and $BlockB.body) { $BlockB.body } else { $IntentLine } }
        default { $IntentLine }
    }
    New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null
    $stageFile = Join-Path $StagingDir ("staging_{0}.txt" -f (Get-Date -Format "yyyyMMdd_HHmmss_fff"))
    [System.IO.File]::WriteAllText($stageFile, [string]$body, $utf8)
    $mg = Invoke-MatureThinGlueL0Path -RepoRoot $RepoRoot -TargetPath $stageFile
    if ($mg.ok) {
        $p = $mg.payload
        $l0.markitdown_used = ($p.adapter -eq "markitdown")
        $l0.raw_text_excerpt = [string]$p.content_md
        $l0.byte_count = [int]$p.char_count
        $l0.material_refs = @($stageFile)
        $l0.thin_glue_evidence = $p
    }
    else {
        $l0.named_blocker = $mg.named_blocker
        $l0.raw_text_excerpt = if ($body.Length -gt 4000) { $body.Substring(0, 4000) + "..." } else { $body }
        $l0.byte_count = [Text.Encoding]::UTF8.GetByteCount([string]$body)
        $l0.material_refs = @($stageFile)
    }
    return $l0
}

function Build-L1Structured {
    param($L0, [string]$IntentLine, $BlockB, [string]$AcceptanceHint)
    $accept = @()
    if ($BlockB -and $BlockB.acceptance) { $accept = @($BlockB.acceptance) }
    elseif ($AcceptanceHint) { $accept = @("- $AcceptanceHint") }
    else {
        $accept = @(
            "- 333 已认领（workflow/run 或等价 durable 证据）",
            "- 分解在波内（非前台步骤清单）",
            "- D:\XINAO_RESEARCH_RUNTIME 有本任务证据"
        )
    }
    return [ordered]@{
        schema_version   = "xinao.task_entry.l1_structured.v1"
        structured_at    = (Get-Date).ToString("o")
        intent           = $IntentLine
        entry_kind       = $L0.entry_kind
        acceptance       = $accept
        constraints_cn   = @(
            "多样投递，单一认领，系统内分解",
            "Grok/Codex 可代投，不可当 Temporal 耐久 owner",
            "禁止前台预分解当主链"
        )
        decomposition_owner = "langgraph_wave_internal"
        plan_truth_stores   = @("temporal_event_history", "system_state")
        l0_ref              = $L0
    }
}

function Get-TemporalDevServerStatus([string]$RuntimeRoot) {
    $p = Join-Path $RuntimeRoot "state\temporal_dev_server\latest.json"
    if (-not (Test-Path -LiteralPath $p)) { return @{ ok = $false; source = "no_evidence" } }
    $j = Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json
    $ok = ($j.status -in @("running", "already_running"))
    return @{ ok = $ok; source = "mature_glue_latest"; path = $p; status = $j.status }
}

function Test-IngressHealth([string]$BaseUrl) {
    try {
        $r = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd("/") + "/health") -UseBasicParsing -TimeoutSec 4
        return ($r.StatusCode -eq 200)
    }
    catch { return $false }
}

# --- resolve inputs ---
$blockB = $null
$kind = $EntryKind
$intentLine = $Intent
$acceptanceHint = ""

if ($PSCmdlet.ParameterSetName -eq "TaskFile" -or ($kind -eq "taskfile") -or $TaskFile) {
    if (-not $TaskFile) { throw "TaskFile required for taskfile entry" }
    $blockB = Parse-BlockBTaskFile -Path $TaskFile
    $kind = "taskfile"
    if (-not $intentLine) { $intentLine = $blockB.intent }
    if ($blockB.entry -eq "path" -and $blockB.source) { $InputFile = $blockB.source; $kind = "path" }
    elseif ($blockB.entry -eq "text") { $kind = "text"; $InputText = $blockB.body }
}
elseif ($PSCmdlet.ParameterSetName -eq "Dir" -or $InputDir) { $kind = "dir" }
elseif ($PSCmdlet.ParameterSetName -eq "Path" -or $InputFile) { $kind = "path" }
elseif ($PSCmdlet.ParameterSetName -eq "Text" -or $InputText) { $kind = "text" }
elseif ($Intent) { $kind = "sentence" }
else { throw "No task material: use -Intent, -InputText, -InputFile, -InputDir, or -TaskFile" }

if ($kind -eq "auto") { $kind = "sentence" }
if (-not $intentLine) {
    if ($kind -eq "path" -and $InputFile) { $intentLine = "处理材料: $InputFile" }
    elseif ($kind -eq "dir" -and $InputDir) { $intentLine = "处理目录: $InputDir" }
    else { $intentLine = "未命名任务" }
}

$sRepo = [string]$config.repo_root
$stagingDir = Join-Path $stateRoot "staging"
$taskId = New-TaskId
$l0 = Read-L0Material -Kind $kind -IntentLine $intentLine -Text $InputText -File $InputFile -Dir $InputDir -BlockB $blockB -RepoRoot $sRepo -RuntimeRoot $runtime -StagingDir $stagingDir
$l1 = Build-L1Structured -L0 $l0 -IntentLine $intentLine -BlockB $blockB -AcceptanceHint $acceptanceHint

$temporalEv = Get-TemporalDevServerStatus -RuntimeRoot $runtime
$temporalOk = $temporalEv.ok
$blockers = [System.Collections.Generic.List[string]]::new()
$optionalGaps = [System.Collections.Generic.List[string]]::new()
$needsIngressProbe = ($TryCodexProxy -or ($DeliveryShell -eq "codex"))
$ingressOk = $null
if ($needsIngressProbe) {
    $ingressOk = Test-IngressHealth -BaseUrl ([string]$config.ingress_base_url)
}
else {
    [void]$optionalGaps.Add("INGRESS_DEPRECATED_NOT_SPINE")
}
if (-not $l0.markitdown_used) { [void]$optionalGaps.Add("MARKITDOWN_DEFAULT_VENV_MISSING") }
if (-not $temporalOk) { [void]$optionalGaps.Add("LANGGRAPH_NO_LIVE_WAVE") }
if (-not $temporalOk) { [void]$blockers.Add("TEMPORAL_7233_DOWN") }
if ($l0.named_blocker) { [void]$blockers.Add($l0.named_blocker) }

$claimState = "intake_staged"
$durableEvidenceRef = ""
$deliveryResult = $null

if ($TryDurableClaim) {
    try {
        $claimScript = Join-Path $bridge "Invoke-GrokTaskEntryClaimDurable.ps1"
        if (Test-Path -LiteralPath $claimScript) {
            & $claimScript -IntakeTaskId $taskId -Quiet | Out-Null
            $claimEv = Join-Path $runtime "state\task_entry\durable_claim\latest.json"
            if (Test-Path -LiteralPath $claimEv) {
                $cj = Get-Content $claimEv -Raw -Encoding UTF8 | ConvertFrom-Json
                $claimState = [string]$cj.claim_state
                $durableEvidenceRef = [string]$cj.durable_evidence_ref
                if ($cj.named_blockers) { foreach ($b in $cj.named_blockers) { if ($b) { [void]$blockers.Add([string]$b) } } }
            }
        }
    } catch {
        [void]$blockers.Add("DURABLE_CLAIM_INVOKE_FAILED")
    }
}

if ($TryCodexProxy -or ($DeliveryShell -eq "codex")) {
    if ($ingressOk) {
        try {
            $sendScript = Join-Path $bridge "Send-GrokIntentToCodexA.ps1"
            $deliveryResult = & $sendScript -UserIntentCn $intentLine -IntentOneLiner $intentLine `
                -SemanticObject ($l1.l0_ref.material_refs | Select-Object -First 1) `
                -BackendOnly -SkipVisible 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) { [void]$blockers.Add("CODEX_PROXY_SEND_FAILED") }
        }
        catch {
            [void]$blockers.Add("CODEX_PROXY_SEND_FAILED")
            $deliveryResult = $_.Exception.Message
        }
    }
    else {
        [void]$blockers.Add("INGRESS_19102_DOWN")
        $claimState = "delivery_shell_only"
    }
}

if (-not $temporalOk) { $claimState = "intake_staged" }

$readbackThree = [ordered]@{
    entry_read_ok     = ($l0.named_blocker -ne "L0_PATH_NOT_FOUND" -and $l0.named_blocker -ne "L0_DIR_NOT_FOUND")
    durable_claim_ref = $durableEvidenceRef
    blockers          = @($blockers)
}

$record = [ordered]@{
    schema_version    = "xinao.task_entry.intake_record.v1"
    sentinel          = "SENTINEL:GROK_TASK_ENTRY_INTAKE"
    task_id           = $taskId
    generated_at      = (Get-Date).ToString("o")
    frozen_policy_cn  = "多样投递，单一认领，系统内分解"
    entry_kind        = $kind
    delivery_shell    = $DeliveryShell
    intent_one_liner  = $intentLine
    claim_state       = $claimState
    temporal_7233_ok  = $temporalOk
    ingress_19102_ok  = $ingressOk
    named_blockers    = @($blockers)
    optional_gaps     = $optionalGaps
    readback_three_cn = @(
        "①入口读$(if ($readbackThree.entry_read_ok) { '到' } else { '失败' })：$kind / $intentLine",
        "②durable认领证据：$(if ($durableEvidenceRef) { $durableEvidenceRef } else { '无（' + ($claimState) + '）' })",
        "③blocker：$(if ($blockers.Count) { ($blockers -join '；') } else { '无' })"
    )
    l0_intake         = $l0
    l1_structured     = $l1
    delivery_proxy    = $deliveryResult
    evidence_refs     = [ordered]@{
        intake_record = Join-Path $intakeDir "$taskId.json"
        l0_copy       = Join-Path $l0Dir "$taskId.json"
        l1_copy       = Join-Path $l1Dir "$taskId.json"
        latest        = Join-Path $stateRoot "latest.json"
        readback_zh   = Join-Path $runtime "readback\zh\task_entry_latest.md"
    }
    completion_claim_allowed = $false
    not_user_completion      = $true
    not_frontend_plan        = $true
}

if (-not $NoWrite) {
    $json = $record | ConvertTo-Json -Depth 12
    $paths = @(
        $record.evidence_refs.intake_record,
        $record.evidence_refs.l0_copy,
        $record.evidence_refs.l1_copy
    )
    # 多样投递：新 intake 写 intake/l0/l1；已 durable_claimed 的 latest 不被 SelfRotate 覆盖
    $skipLatestWrite = $false
    $claimLatestPath = Join-Path $stateRoot "durable_claim\latest.json"
    if (Test-Path -LiteralPath $claimLatestPath) {
        try {
            $existingClaim = Get-Content -LiteralPath $claimLatestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ([string]$existingClaim.claim_state -eq "durable_claimed" -and [string]$existingClaim.intake_task_id -ne $taskId) {
                $skipLatestWrite = $true
                $record | Add-Member -NotePropertyName "latest_preserved_task_id" -NotePropertyValue ([string]$existingClaim.intake_task_id) -Force
                $record | Add-Member -NotePropertyName "latest_write_skipped_reason" -NotePropertyValue "durable_claimed_latest_preserved" -Force
            }
        } catch { }
    }
    if (-not $skipLatestWrite) { $paths += $record.evidence_refs.latest }
    foreach ($p in $paths) {
        [System.IO.File]::WriteAllText($p, $json, $utf8)
    }
    if (-not $skipLatestWrite) {
        $three = ($record.readback_three_cn | ForEach-Object { "- $_" }) -join "`n"
        $md = @(
            "# task_entry readback",
            "",
            "task_id: **$taskId**",
            "claim_state: **$claimState**",
            "",
            "## three_lines",
            $three,
            "",
            "## now_can_invoke",
            "- Invoke-GrokTaskEntry.ps1 -Intent '...'",
            "- Invoke-GrokTaskEntry.ps1 -TaskFile '...'",
            "- Get-GrokTaskEntryStatus.ps1",
            "",
            "## honest",
            "- decompose inside wave; this script does not front-plan",
            ("- Temporal:7233=" + $(if ($temporalOk) { "up" } else { "down" }))
        ) -join "`n"
        [System.IO.File]::WriteAllText($record.evidence_refs.readback_zh, $md, $utf8)
    }
}

if (-not $Quiet) {
    $record | ConvertTo-Json -Depth 8
}