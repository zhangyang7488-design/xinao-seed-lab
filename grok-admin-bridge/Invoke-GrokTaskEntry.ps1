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

function Read-L0Material {
    param(
        [string]$Kind,
        [string]$IntentLine,
        [string]$Text,
        [string]$File,
        [string]$Dir,
        $BlockB
    )
    $l0 = [ordered]@{
        schema_version = "xinao.task_entry.l0_intake.v1"
        read_at        = (Get-Date).ToString("o")
        entry_kind     = $Kind
        intent_one_liner = $IntentLine
        material_refs  = @()
        raw_text_excerpt = ""
        dir_manifest   = @()
        byte_count     = 0
        markitdown_used = $false
        named_blocker  = $null
    }
    switch ($Kind) {
        "sentence" {
            $l0.raw_text_excerpt = $IntentLine
            $l0.byte_count = [Text.Encoding]::UTF8.GetByteCount($IntentLine)
        }
        "text" {
            $body = if ($BlockB -and $BlockB.body) { $BlockB.body } else { $Text }
            $l0.raw_text_excerpt = if ($body.Length -gt 4000) { $body.Substring(0, 4000) + "…" } else { $body }
            $l0.byte_count = [Text.Encoding]::UTF8.GetByteCount($body)
        }
        "path" {
            $target = if ($BlockB -and $BlockB.source -and (Test-Path -LiteralPath $BlockB.source)) { $BlockB.source } else { $File }
            if (-not (Test-Path -LiteralPath $target)) {
                $l0.named_blocker = "L0_PATH_NOT_FOUND"
                return $l0
            }
            $ext = [IO.Path]::GetExtension($target).ToLowerInvariant()
            if ($ext -in @(".txt", ".md", ".json", ".yaml", ".yml", ".ps1", ".py", ".csv", ".log")) {
                $content = Get-Content -LiteralPath $target -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
                if (-not $content) { $content = Get-Content -LiteralPath $target -Raw -ErrorAction SilentlyContinue }
                $l0.raw_text_excerpt = if ($content.Length -gt 4000) { $content.Substring(0, 4000) + "…" } else { $content }
                $l0.byte_count = if ($content) { [Text.Encoding]::UTF8.GetByteCount($content) } else { 0 }
            }
            else {
                $l0.raw_text_excerpt = "[binary_or_unread_ext:$ext]"
                $fi = Get-Item -LiteralPath $target
                $l0.byte_count = $fi.Length
            }
            $l0.material_refs = @($target)
            $l0 | Add-Member -NotePropertyName file_sha256 -NotePropertyValue (Get-FileSha256 $target)
        }
        "dir" {
            if (-not (Test-Path -LiteralPath $Dir -PathType Container)) {
                $l0.named_blocker = "L0_DIR_NOT_FOUND"
                return $l0
            }
            $items = Get-ChildItem -LiteralPath $Dir -File -ErrorAction SilentlyContinue | Select-Object -First 200
            foreach ($it in $items) {
                $l0.dir_manifest += [ordered]@{
                    name = $it.Name
                    path = $it.FullName
                    bytes = $it.Length
                    mtime = $it.LastWriteTimeUtc.ToString("o")
                }
            }
            $l0.material_refs = @($Dir)
            $l0.raw_text_excerpt = "dir:$Dir files=$($l0.dir_manifest.Count)"
        }
        default {
            $l0.raw_text_excerpt = $IntentLine
        }
    }
    $l0.markitdown_used = $false
    if ($l0.named_blocker -eq "L0_PATH_NOT_FOUND" -or $l0.named_blocker -eq "L0_DIR_NOT_FOUND") {
        return $l0
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

function Test-TemporalPort([int]$Port = 7233) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $ar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $ar.AsyncWaitHandle.WaitOne(1200, $false)
        if ($ok -and $c.Connected) { $c.EndConnect($ar); $c.Close(); return $true }
        $c.Close()
    }
    catch {}
    return $false
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

$taskId = New-TaskId
$l0 = Read-L0Material -Kind $kind -IntentLine $intentLine -Text $InputText -File $InputFile -Dir $InputDir -BlockB $blockB
$l1 = Build-L1Structured -L0 $l0 -IntentLine $intentLine -BlockB $blockB -AcceptanceHint $acceptanceHint

$temporalOk = Test-TemporalPort
$ingressOk = Test-IngressHealth -BaseUrl ([string]$config.ingress_base_url)
$blockers = [System.Collections.Generic.List[string]]::new()
$optionalGaps = @("MARKITDOWN_DEFAULT_VENV_MISSING", "LANGGRAPH_NO_LIVE_WAVE")
if (-not $temporalOk) { [void]$blockers.Add("TEMPORAL_7233_DOWN") }
if ($l0.named_blocker) { [void]$blockers.Add($l0.named_blocker) }

$claimState = "intake_staged"
$durableEvidenceRef = ""
$deliveryResult = $null

if ($TryDurableClaim -and $temporalOk) {
    $claimState = "durable_claim_pending_bind"
    $blockers.Add("TEMPORAL_BIND_NOT_WIRED_P0")
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

if (-not $temporalOk) { $claimState = "intake_staged_pending_durable_owner" }

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
        $record.evidence_refs.l1_copy,
        $record.evidence_refs.latest
    )
    foreach ($p in $paths) {
        [System.IO.File]::WriteAllText($p, $json, $utf8)
    }
    $md = @(
        "# 任务入口 readback",
        "",
        "task_id: **$taskId**",
        "claim_state: **$claimState**",
        "",
        "## 三句（块C）",
        $(foreach ($line in $record.readback_three_cn) { "- $line" }),
        "",
        "## now_can_invoke",
        "- ``Invoke-GrokTaskEntry.ps1 -Intent '...'``",
        "- ``Invoke-GrokTaskEntry.ps1 -TaskFile '...'``",
        "- ``Get-GrokTaskEntryStatus.ps1``",
        "",
        "## 诚实",
        "- 分解在波内；本脚本不做前台步骤清单",
        "- Temporal:7233=$(if ($temporalOk) { 'up' } else { 'down' })"
    ) -join "`n"
    [System.IO.File]::WriteAllText($record.evidence_refs.readback_zh, $md, $utf8)
}

if (-not $Quiet) {
    $record | ConvertTo-Json -Depth 8
}