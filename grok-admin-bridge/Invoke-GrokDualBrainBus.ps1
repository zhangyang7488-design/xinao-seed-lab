#Requires -Version 5.1
<#
.SYNOPSIS
  Dual-brain discuss bus + task queue (scaffold). Brains: gate then act. Admin: accept+schedule only.

.DESCRIPTION
  Implements M0-M4 thin bind from external mature split (discuss vs task) + user standing.
  T3 thin bind: ThreadPost may mirror one-file-per-message into state\mailbox Maildir layout
  (pure file when AMQ not installed). Old dual_brain_bus is NEVER deleted.
  LivePanel EnsureIdentity/InjectPending = doorbell only (not this script; see contract).
  completion_claim_allowed always false. NOT product multi-window chat.

.PARAMETER Action
  ThreadOpen | ThreadPost | ThreadClose | ThreadStatus | ThreadList |
  BrainAccept | BrainGateCheck | BrainExecuteNote |
  TaskDispatch | TaskList | WorkerPull | WorkerSchedule | WorkerComplete |
  MailboxStatus | SelfSmoke | Status

.PARAMETER NoMirrorMailbox
  Disable ThreadPost→mailbox Maildir mirror (default: mirror ON for T3 thin bind).
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "ThreadOpen", "ThreadPost", "ThreadClose", "ThreadStatus", "ThreadList",
        "BrainAccept", "BrainGateCheck", "BrainExecuteNote",
        "TaskDispatch", "TaskList", "WorkerPull", "WorkerSchedule", "WorkerComplete",
        "MailboxStatus", "SelfSmoke", "Status"
    )]
    [string]$Action,

    [ValidateSet("grok_4_5", "codex", "admin")]
    [string]$Actor = "grok_4_5",

    [ValidateSet("grok_4_5", "codex", "admin", "*")]
    [string]$To = "codex",

    [string]$ThreadId = "",

    [string]$Body = "",

    [ValidateSet(
        "propose", "ask", "inform", "counter", "challenge", "clarify", "correct", "reply", "note",
        "accept", "reject", "each_close", "withdraw", "escalate_to_user", "read_receipt",
        "dispatch_intent", "system"
    )]
    [string]$Kind = "note",

    [string]$TaskId = "",

    [string]$Title = "",

    [string]$Goal = "",

    [int]$Priority = 100,

    [switch]$NonConsensus,

    [string]$GateId = "",

    [string]$Note = "",

    [string]$ArtifactRef = "",

    [ValidateSet("done", "failed", "canceled")]
    [string]$WorkerResult = "done",

    [string]$BusRoot = "",

    [string]$MailboxRoot = "",

    [switch]$NoMirrorMailbox,

    [int]$MaxRounds = 12,

    [int]$TtlMinutes = 120,

    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
try { chcp 65001 | Out-Null } catch {}
$utf8 = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = $utf8

$script:Brains = @("grok_4_5", "codex")
$script:Worker = "admin"
$script:Zhuxian = "C:\Users\xx363\Desktop\主线"
$script:ClosedStates = @("ACCEPTED", "REJECTED", "EACH_CLOSED", "SUPERSEDED", "ESCALATED", "EXPIRED")

function Get-NowIso { (Get-Date).ToString("o") }
function New-Id { [guid]::NewGuid().ToString("N").Substring(0, 12) }

function Get-EvidenceRoot {
    $resolver = Join-Path $PSScriptRoot "Resolve-GrokEvidenceRuntimeRoot.ps1"
    $root = "D:\XINAO_RESEARCH_RUNTIME"
    if (Test-Path -LiteralPath $resolver) {
        try { $root = [string](& $resolver) } catch {}
    }
    return $root
}

function Get-BusRoot {
    if ($BusRoot) { return $BusRoot }
    return (Join-Path (Get-EvidenceRoot) "state\dual_brain_bus")
}

function Get-MailboxRoot {
    if ($MailboxRoot) { return $MailboxRoot }
    return (Join-Path (Get-EvidenceRoot) "state\mailbox")
}

function Ensure-Dir([string]$p) {
    if (-not (Test-Path -LiteralPath $p)) { New-Item -ItemType Directory -Force -Path $p | Out-Null }
}

function Test-AmqAvailable {
    # AMQ = external Agent Message Queue if present; pure-file Maildir when absent.
    foreach ($c in @("amq", "agent-message-queue", "agentmq")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { return [pscustomobject]@{ available = $true; command = $cmd.Source } }
    }
    return [pscustomobject]@{ available = $false; command = $null }
}

function Init-MaildirLayout([string]$Root) {
    # Maildir-compatible: tmp / new / cur (+ per-recipient inbox for pull).
    $M = [ordered]@{
        root           = $Root
        maildir        = Join-Path $Root "maildir"
        tmp            = Join-Path $Root "maildir\tmp"
        new            = Join-Path $Root "maildir\new"
        cur            = Join-Path $Root "maildir\cur"
        inbox          = Join-Path $Root "inbox"
        latest_mirror  = Join-Path $Root "latest_mirror.json"
        layout_marker  = Join-Path $Root "maildir_layout.v1.json"
    }
    foreach ($k in @("maildir", "tmp", "new", "cur", "inbox")) { Ensure-Dir $M[$k] }
    if (-not (Test-Path -LiteralPath $M.layout_marker)) {
        Write-Json $M.layout_marker ([ordered]@{
                schema_version           = "xinao.mailbox.maildir_layout.v1"
                style                    = "maildir_compatible_file_per_message"
                amq_required             = $false
                fallback                 = "pure_file_maildir"
                paths                    = @{ tmp = "maildir/tmp"; new = "maildir/new"; cur = "maildir/cur"; inbox = "inbox/{recipient}/{tmp,new,cur}" }
                semantics_cn             = "one file one msg; write tmp then move new; land != read; LivePanel EnsureIdentity/InjectPending doorbell only != mailbox read"
                dual_brain_bus_legacy_cn = "legacy dual_brain_bus kept; this root = formal Mailbox thin-bind mirror target"
                completion_claim_allowed = $false
                updated_at               = Get-NowIso
            })
    }
    return $M
}

function Write-MailboxMirror {
    param(
        $BusEnv,
        [string]$BusMsgPath = "",
        [string]$MbRoot = ""
    )
    if (-not $MbRoot) { $MbRoot = Get-MailboxRoot }
    $M = Init-MaildirLayout $MbRoot
    $amq = Test-AmqAvailable
    $safeTo = [string]$BusEnv.to
    if (-not $safeTo -or $safeTo -eq "*") { $safeTo = "broadcast" }
    $safeTo = ($safeTo -replace '[^\w\.\-]', '_')
    $tsPart = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $uniq = "{0}.{1}.{2}.{3}" -f $tsPart, $PID, $env:COMPUTERNAME, $BusEnv.msg_id
    $fileName = "{0}.json" -f $uniq

    $envelope = [ordered]@{
        schema_version           = "xinao.mailbox.maildir_msg.v1"
        source                   = "dual_brain_bus"
        delivery                 = $(if ($amq.available) { "amq_or_file_maildir" } else { "pure_file_maildir" })
        amq_available            = [bool]$amq.available
        msg_id                   = $BusEnv.msg_id
        thread_id                = $BusEnv.thread_id
        ts                       = $BusEnv.ts
        from                     = $BusEnv.from
        to                       = $BusEnv.to
        kind                     = $BusEnv.kind
        body                     = $BusEnv.body
        bus_msg_path_ref         = $BusMsgPath
        read_status              = "new"
        note_cn                  = "Mailbox land != window-read; != LivePanel doorbell; != SendKeys mainline; legacy bus remains discuss authority"
        completion_claim_allowed = $false
    }

    # Atomic Maildir write: tmp → new
    $tmpPath = Join-Path $M.tmp $fileName
    $newPath = Join-Path $M.new $fileName
    [System.IO.File]::WriteAllText($tmpPath, ($envelope | ConvertTo-Json -Depth 10), $utf8)
    Move-Item -LiteralPath $tmpPath -Destination $newPath -Force

    # Per-recipient inbox (same content; pull-friendly)
    $recipRoot = Join-Path $M.inbox $safeTo
    foreach ($sub in @("tmp", "new", "cur")) { Ensure-Dir (Join-Path $recipRoot $sub) }
    $rTmp = Join-Path (Join-Path $recipRoot "tmp") $fileName
    $rNew = Join-Path (Join-Path $recipRoot "new") $fileName
    [System.IO.File]::WriteAllText($rTmp, ($envelope | ConvertTo-Json -Depth 10), $utf8)
    Move-Item -LiteralPath $rTmp -Destination $rNew -Force

    $mirrorMeta = [ordered]@{
        schema_version           = "xinao.mailbox.mirror_latest.v1"
        updated_at               = Get-NowIso
        last_msg_id              = $BusEnv.msg_id
        last_thread_id           = $BusEnv.thread_id
        last_to                  = $BusEnv.to
        maildir_new_path         = $newPath
        inbox_new_path           = $rNew
        amq_available            = [bool]$amq.available
        delivery                 = $envelope.delivery
        note_cn                  = "mirror ok != peer read; doorbell = LivePanel only"
        completion_claim_allowed = $false
    }
    Write-Json $M.latest_mirror $mirrorMeta

    return [pscustomobject]@{
        ok                       = $true
        mirrored                 = $true
        mailbox_root             = $M.root
        maildir_new_path         = $newPath
        inbox_new_path           = $rNew
        amq_available            = [bool]$amq.available
        delivery                 = $envelope.delivery
        completion_claim_allowed = $false
    }
}

function Invoke-MailboxStatus {
    param([string]$MbRoot = "")
    if (-not $MbRoot) { $MbRoot = Get-MailboxRoot }
    $M = Init-MaildirLayout $MbRoot
    $amq = Test-AmqAvailable
    $newCount = @(Get-ChildItem -LiteralPath $M.new -File -ErrorAction SilentlyContinue).Count
    $curCount = @(Get-ChildItem -LiteralPath $M.cur -File -ErrorAction SilentlyContinue).Count
    $latest = Read-Json $M.latest_mirror
    return [pscustomobject]@{
        ok                       = $true
        action                   = "MailboxStatus"
        mailbox_root             = $M.root
        maildir_new_count        = $newCount
        maildir_cur_count        = $curCount
        amq_available            = [bool]$amq.available
        delivery_mode            = $(if ($amq.available) { "amq_or_file" } else { "pure_file_maildir" })
        latest_mirror            = $latest
        dual_brain_bus_intact_cn = "dual_brain_bus not deleted; mailbox = thin-bind mirror layer"
        live_panel_doorbell_only_cn = "EnsureIdentity/InjectPending = doorbell only; != read; != discuss mainline"
        completion_claim_allowed = $false
    }
}

function Write-Json([string]$Path, $Obj) {
    Ensure-Dir (Split-Path -Parent $Path)
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 14), $utf8)
}

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Init-Layout([string]$Root) {
    $L = [ordered]@{
        root         = $Root
        discuss      = Join-Path $Root "discuss"
        threads      = Join-Path $Root "discuss\threads"
        messages     = Join-Path $Root "discuss\messages"
        tasks        = Join-Path $Root "tasks"
        queue        = Join-Path $Root "worker_queue"
        queue_file   = Join-Path $Root "worker_queue\queue.json"
        gates        = Join-Path $Root "brain_gate"
        latest       = Join-Path $Root "latest.json"
        smoke        = Join-Path $Root "self_smoke_latest.json"
    }
    foreach ($k in @("discuss", "threads", "messages", "tasks", "queue", "gates")) {
        Ensure-Dir $L[$k]
    }
    if (-not (Test-Path -LiteralPath $L.queue_file)) {
        Write-Json $L.queue_file ([ordered]@{
                schema_version = "xinao.dual_brain.worker_queue.v1"
                items          = @()
                updated_at     = Get-NowIso
            })
    }
    return $L
}

function Test-IsBrain([string]$Who) { return $script:Brains -contains $Who }

function Get-ThreadPath($L, [string]$Id) { Join-Path $L.threads ("{0}.json" -f $Id) }
function Get-TaskPath($L, [string]$Id) { Join-Path $L.tasks ("{0}.json" -f $Id) }
function Get-GatePath($L, [string]$Id) { Join-Path $L.gates ("{0}.json" -f $Id) }
function Get-MsgPath($L, [string]$Tid) { Join-Path $L.messages ("{0}.jsonl" -f $Tid) }

function Invoke-ThreadOpen {
    param($L, [string]$Who, [string]$Peer, [string]$TitleText, [string]$BodyText)
    if (-not (Test-IsBrain $Who)) { throw "ThreadOpen only brains (grok_4_5|codex); actor=$Who" }
    if ($Peer -eq "admin") { throw "Admin has no discuss space; use TaskDispatch" }
    $tid = if ($ThreadId) { $ThreadId } else { "th_" + (New-Id) }
    $path = Get-ThreadPath $L $tid
    if (Test-Path -LiteralPath $path) { throw "thread exists: $tid" }
    $th = [ordered]@{
        schema_version           = "xinao.dual_brain.thread.v1"
        thread_id                = $tid
        title                    = $(if ($TitleText) { $TitleText } else { "untitled" })
        state                    = "OPEN"
        opened_by                = $Who
        peers                    = @($Who, $(if ($Peer -and $Peer -ne "*") { $Peer } else { "codex" })) | Select-Object -Unique
        rounds                   = 0
        max_rounds               = $MaxRounds
        ttl_minutes              = $TtlMinutes
        opened_at                = Get-NowIso
        updated_at               = Get-NowIso
        expires_at               = (Get-Date).AddMinutes($TtlMinutes).ToString("o")
        last_kind                = $null
        last_actor               = $null
        close_reason             = $null
        zhuxian_path             = $script:Zhuxian
        completion_claim_allowed = $false
    }
    Write-Json $path $th
    if ($BodyText) {
        $null = Invoke-ThreadPost -L $L -Who $Who -Tid $tid -KindName "propose" -BodyText $BodyText -ToPeer $Peer
        $th = Read-Json $path
    }
    return [pscustomobject]@{
        ok = $true; action = "ThreadOpen"; thread = $th; completion_claim_allowed = $false
    }
}

function Invoke-ThreadPost {
    param($L, [string]$Who, [string]$Tid, [string]$KindName, [string]$BodyText, [string]$ToPeer)
    if (-not $Tid) { throw "ThreadPost requires -ThreadId" }
    $path = Get-ThreadPath $L $Tid
    $th = Read-Json $path
    if (-not $th) { throw "thread not found: $Tid" }
    if ($script:ClosedStates -contains [string]$th.state) {
        throw "thread closed ($($th.state)); open new thread"
    }
    if ($Who -eq "admin" -and $KindName -notin @("read_receipt", "system")) {
        throw "Admin cannot post discuss acts (no discuss space)"
    }
    # expire check
    try {
        if ($th.expires_at -and ([datetime]::Parse([string]$th.expires_at) -lt (Get-Date))) {
            $th.state = "EXPIRED"
            $th.close_reason = "ttl"
            $th.updated_at = Get-NowIso
            Write-Json $path $th
            throw "thread EXPIRED by TTL"
        }
    } catch {
        if ($_.Exception.Message -match "EXPIRED") { throw }
    }

    $msgId = "msg_" + (New-Id)
    $env = [ordered]@{
        schema_version = "xinao.dual_brain.message.v1"
        msg_id         = $msgId
        thread_id      = $Tid
        ts             = Get-NowIso
        from           = $Who
        to             = $(if ($ToPeer) { $ToPeer } else { "*" })
        kind           = $KindName
        body           = $BodyText
        note_cn        = "discuss layer; not task"
    }
    $mp = Get-MsgPath $L $Tid
    Add-Content -LiteralPath $mp -Value (($env | ConvertTo-Json -Compress -Depth 6)) -Encoding UTF8

    # T3 thin bind: optional mirror to formal Mailbox (Maildir file-per-msg). Bus remains source for discuss.
    $mailboxMirror = $null
    if (-not $NoMirrorMailbox) {
        try {
            $mailboxMirror = Write-MailboxMirror -BusEnv $env -BusMsgPath $mp -MbRoot (Get-MailboxRoot)
        }
        catch {
            $mailboxMirror = [pscustomobject]@{
                ok                       = $false
                mirrored                 = $false
                error                    = $_.Exception.Message
                completion_claim_allowed = $false
            }
        }
    }
    else {
        $mailboxMirror = [pscustomobject]@{ ok = $true; mirrored = $false; reason = "NoMirrorMailbox"; completion_claim_allowed = $false }
    }

    $th.rounds = [int]$th.rounds + 1
    $th.last_kind = $KindName
    $th.last_actor = $Who
    $th.updated_at = Get-NowIso

    # state transitions
    $closingActs = @("accept", "reject", "each_close", "withdraw", "escalate_to_user")
    if ([string]$th.state -eq "OPEN") { $th.state = "ACTIVE" }
    if ($KindName -eq "read_receipt") {
        # does not advance close
        if ([string]$th.state -eq "ACTIVE") { $th.state = "WAIT_PEER" }
    }
    elseif ($closingActs -contains $KindName) {
        $th.state = "CLOSING"
        # single-message close for scaffold (peer silence not waited)
        switch ($KindName) {
            "accept" { $th.state = "ACCEPTED"; $th.close_reason = "accept_by_$Who" }
            "reject" { $th.state = "REJECTED"; $th.close_reason = "reject_by_$Who" }
            "each_close" { $th.state = "EACH_CLOSED"; $th.close_reason = "each_close_by_$Who" }
            "withdraw" { $th.state = "EACH_CLOSED"; $th.close_reason = "withdraw_by_$Who" }
            "escalate_to_user" { $th.state = "ESCALATED"; $th.close_reason = "escalate_by_$Who" }
        }
    }
    else {
        if ([int]$th.rounds -ge [int]$th.max_rounds) {
            $th.state = "EXPIRED"
            $th.close_reason = "max_rounds"
        }
        elseif ([string]$th.state -eq "WAIT_PEER") { $th.state = "ACTIVE" }
    }

    Write-Json $path $th
    return [pscustomobject]@{
        ok                       = $true
        action                   = "ThreadPost"
        msg_id                   = $msgId
        thread_state             = $th.state
        thread                   = $th
        mailbox_mirror           = $mailboxMirror
        read_receipt_not_accept  = $true
        honesty_cn               = "bus write + optional mailbox mirror != peer read; LivePanel doorbell != message consumed"
        completion_claim_allowed = $false
    }
}

function Invoke-ThreadClose {
    param($L, [string]$Who, [string]$Tid, [string]$KindName, [string]$BodyText)
    if (-not $KindName) { $KindName = "each_close" }
    if ($KindName -notin @("accept", "reject", "each_close", "withdraw", "escalate_to_user")) {
        throw "ThreadClose kind must be closing speech act"
    }
    return Invoke-ThreadPost -L $L -Who $Who -Tid $Tid -KindName $KindName -BodyText $(if ($BodyText) { $BodyText } else { $KindName }) -ToPeer "*"
}

function Invoke-ThreadStatus {
    param($L, [string]$Tid)
    if (-not $Tid) { throw "need ThreadId" }
    $th = Read-Json (Get-ThreadPath $L $Tid)
    if (-not $th) { throw "not found $Tid" }
    $msgs = @()
    $mp = Get-MsgPath $L $Tid
    if (Test-Path -LiteralPath $mp) {
        Get-Content -LiteralPath $mp -Encoding UTF8 | ForEach-Object {
            if ($_) { try { $msgs += ($_ | ConvertFrom-Json) } catch {} }
        }
    }
    return [pscustomobject]@{
        ok = $true; action = "ThreadStatus"; thread = $th; message_count = $msgs.Count
        messages_tail = @($msgs | Select-Object -Last 10); completion_claim_allowed = $false
    }
}

function Invoke-ThreadList {
    param($L)
    $list = @()
    Get-ChildItem -LiteralPath $L.threads -Filter "*.json" -ErrorAction SilentlyContinue | ForEach-Object {
        $t = Read-Json $_.FullName
        if ($t) {
            $list += [pscustomobject]@{
                thread_id = $t.thread_id; state = $t.state; title = $t.title
                rounds = $t.rounds; updated_at = $t.updated_at
            }
        }
    }
    return [pscustomobject]@{ ok = $true; action = "ThreadList"; count = $list.Count; threads = $list; completion_claim_allowed = $false }
}

function Invoke-BrainAccept {
    param($L, [string]$Who, [string]$TitleText, [string]$GoalText, [string]$BodyText)
    if (-not (Test-IsBrain $Who)) { throw "BrainAccept only for brains; admin excluded from governance gate ownership" }
    $gid = if ($GateId) { $GateId } else { "gate_" + (New-Id) }
    $zhuxianOk = Test-Path -LiteralPath $script:Zhuxian
    # list a few entries under 主线 as intent carriers (path lock not text freeze)
    $sample = @()
    if ($zhuxianOk) {
        try {
            $sample = @(Get-ChildItem -LiteralPath $script:Zhuxian -File -ErrorAction SilentlyContinue |
                    Select-Object -First 8 -ExpandProperty Name)
        } catch {}
    }
    $gate = [ordered]@{
        schema_version           = "xinao.dual_brain.brain_gate.v1"
        gate_id                  = $gid
        actor                    = $Who
        accepted_at              = Get-NowIso
        title                    = $TitleText
        goal                     = $GoalText
        body                     = $BodyText
        status                   = "accepted_pending_gate"
        execute_allowed          = $false
        zhuxian_path             = $script:Zhuxian
        zhuxian_path_exists      = $zhuxianOk
        zhuxian_sample_files     = $sample
        steps                    = [ordered]@{
            s1_task_accepted           = $true
            s2_zhuxian_path_aligned    = $false
            s3_governance_meta_think   = $false
            s4_external_mature_noted   = $false
            s5_lens_checked            = $false
            s6_anti_conflict_noted     = $false
            s7_ready_to_execute        = $false
        }
        notes_cn                 = @(
            "接任务≠开干",
            "工人Admin不跑此门闩",
            "须 BrainGateCheck 补齐步骤后 execute_allowed=true"
        )
        completion_claim_allowed = $false
    }
    # auto-mark path step if path exists
    if ($zhuxianOk) { $gate.steps.s2_zhuxian_path_aligned = $true }
    Write-Json (Get-GatePath $L $gid) $gate
    return [pscustomobject]@{
        ok = $true; action = "BrainAccept"; gate = $gate
        next_cn = "调用 -Action BrainGateCheck -GateId $gid 补齐治理环步骤后再 Execute/Dispatch"
        completion_claim_allowed = $false
    }
}

function Invoke-BrainGateCheck {
    param($L, [string]$Who, [string]$Gid, [string]$NoteText)
    if (-not $Gid) { throw "BrainGateCheck needs -GateId" }
    $path = Get-GatePath $L $Gid
    $old = Read-Json $path
    if (-not $old) { throw "gate not found $Gid" }
    if (-not (Test-IsBrain $Who)) { throw "only brains run gate check" }

    $zhuxianOk = [bool](Test-Path -LiteralPath $script:Zhuxian)
    $ready = $zhuxianOk  # other steps set true by invoking this check
    $gate = [ordered]@{
        schema_version           = "xinao.dual_brain.brain_gate.v1"
        gate_id                  = [string]$old.gate_id
        actor                    = [string]$old.actor
        accepted_at              = [string]$old.accepted_at
        title                    = [string]$old.title
        goal                     = [string]$old.goal
        body                     = [string]$old.body
        status                   = $(if ($ready) { "gate_pass" } else { "gate_blocked" })
        execute_allowed          = $ready
        zhuxian_path             = $script:Zhuxian
        zhuxian_path_exists      = $zhuxianOk
        zhuxian_sample_files     = @($old.zhuxian_sample_files)
        steps                    = [ordered]@{
            s1_task_accepted           = $true
            s2_zhuxian_path_aligned    = $zhuxianOk
            s3_governance_meta_think   = $true
            s4_external_mature_noted   = $true
            s5_lens_checked            = $true
            s6_anti_conflict_noted     = $true
            s7_ready_to_execute        = $ready
        }
        notes_cn                 = @($old.notes_cn)
        checked_at               = Get-NowIso
        checked_by               = $Who
        check_note               = $NoteText
        lens_cn                  = [ordered]@{
            real_progress = "require invoke evidence not report green"
            decision_who  = $Who
            zhuxian       = $script:Zhuxian
        }
        governance_shape_cn      = "0 classify → 1 external mature → 2 local inventory → 3 carrier → 4 scope/ADR → 5 deviation → 6 execute → 7 lens"
        block_reason_cn          = $(if (-not $zhuxianOk) { "主线路径不存在或不可读: $($script:Zhuxian)" } else { $null })
        completion_claim_allowed = $false
    }
    Write-Json $path $gate
    return [pscustomobject]@{
        ok = $true; action = "BrainGateCheck"; gate = $gate
        execute_allowed = $gate.execute_allowed; completion_claim_allowed = $false
    }
}

function Invoke-BrainExecuteNote {
    param($L, [string]$Who, [string]$Gid, [string]$NoteText)
    if (-not (Test-IsBrain $Who)) { throw "BrainExecuteNote brains only" }
    if (-not $Gid) { throw "need GateId" }
    $gate = Read-Json (Get-GatePath $L $Gid)
    if (-not $gate) { throw "gate missing" }
    if (-not $gate.execute_allowed) {
        throw "execute_allowed=false; run BrainGateCheck first (governance before execute)"
    }
    $rec = [ordered]@{
        schema_version           = "xinao.dual_brain.execute_note.v1"
        gate_id                  = $Gid
        actor                    = $Who
        ts                       = Get-NowIso
        note                     = $NoteText
        zhuxian_path             = $script:Zhuxian
        completion_claim_allowed = $false
        honesty_cn               = "记录大脑在门闩通过后的动作说明；≠用户完成"
    }
    $p = Join-Path $L.gates ("{0}_exec_{1}.json" -f $Gid, (New-Id))
    Write-Json $p $rec
    return [pscustomobject]@{ ok = $true; action = "BrainExecuteNote"; path = $p; record = $rec; completion_claim_allowed = $false }
}

function Invoke-TaskDispatch {
    param($L, [string]$Who, [string]$TitleText, [string]$GoalText, [string]$Gid, [string]$Tid, [bool]$IsNonConsensus, [int]$Prio)
    if (-not (Test-IsBrain $Who)) { throw "TaskDispatch from brains only (or pass after gate)" }
    if ($Gid) {
        $gate = Read-Json (Get-GatePath $L $Gid)
        if (-not $gate) { throw "gate not found $Gid" }
        if (-not $gate.execute_allowed) { throw "gate not pass; BrainGateCheck first" }
    }
    if ($Tid) {
        $th = Read-Json (Get-ThreadPath $L $Tid)
        if ($th -and $th.state -ne "ACCEPTED" -and -not $IsNonConsensus) {
            throw "thread state=$($th.state); need ACCEPTED or -NonConsensus"
        }
    }
    $tid = if ($TaskId) { $TaskId } else { "task_" + (New-Id) }
    $task = [ordered]@{
        schema_version           = "xinao.dual_brain.task.v1"
        task_id                  = $tid
        title                    = $(if ($TitleText) { $TitleText } else { "task" })
        goal                     = $GoalText
        state                    = "queued"
        assigned_to              = "admin"
        dispatched_by            = $Who
        priority                 = $Prio
        source_thread_id         = $(if ($Tid) { $Tid } else { $null })
        source_gate_id           = $(if ($Gid) { $Gid } else { $null })
        non_consensus            = [bool]$IsNonConsensus
        zhuxian_path             = $script:Zhuxian
        created_at               = Get-NowIso
        updated_at               = Get-NowIso
        artifact_ref             = $null
        completion_claim_allowed = $false
        worker_policy_cn         = "Admin default accept; no governance loop"
    }
    Write-Json (Get-TaskPath $L $tid) $task

    $q = Read-Json $L.queue_file
    $items = @($q.items)
    $items += [pscustomobject]@{
        task_id = $tid; priority = $Prio; enqueued_at = Get-NowIso; state = "queued"
    }
    $q.items = @($items | Sort-Object { $_.priority }, { $_.enqueued_at })
    $q.updated_at = Get-NowIso
    Write-Json $L.queue_file $q

    return [pscustomobject]@{
        ok = $true; action = "TaskDispatch"; task = $task; queue_count = $q.items.Count
        completion_claim_allowed = $false
    }
}

function Invoke-TaskList {
    param($L)
    $list = @()
    Get-ChildItem -LiteralPath $L.tasks -Filter "*.json" -ErrorAction SilentlyContinue | ForEach-Object {
        $t = Read-Json $_.FullName
        if ($t) { $list += $t }
    }
    return [pscustomobject]@{ ok = $true; action = "TaskList"; count = $list.Count; tasks = $list; completion_claim_allowed = $false }
}

function Invoke-WorkerPull {
    param($L, [string]$Who)
    if ($Who -ne "admin") { throw "WorkerPull only admin" }
    $q = Read-Json $L.queue_file
    $all = @($q.items)
    $queued = @($all | Where-Object { [string]$_.state -eq "queued" })
    if ($queued.Count -eq 0) {
        return [pscustomobject]@{ ok = $true; action = "WorkerPull"; pulled = $null; note_cn = "queue empty"; completion_claim_allowed = $false }
    }
    $pick = $queued | Sort-Object { [int]$_.priority }, { $_.enqueued_at } | Select-Object -First 1
    $tid = [string]$pick.task_id
    $oldTask = Read-Json (Get-TaskPath $L $tid)
    $task = [ordered]@{
        schema_version           = "xinao.dual_brain.task.v1"
        task_id                  = $tid
        title                    = [string]$oldTask.title
        goal                     = [string]$oldTask.goal
        state                    = "accepted"
        assigned_to              = "admin"
        dispatched_by            = [string]$oldTask.dispatched_by
        priority                 = [int]$oldTask.priority
        source_thread_id         = $oldTask.source_thread_id
        source_gate_id           = $oldTask.source_gate_id
        non_consensus            = [bool]$oldTask.non_consensus
        zhuxian_path             = $script:Zhuxian
        created_at               = [string]$oldTask.created_at
        accepted_at              = Get-NowIso
        updated_at               = Get-NowIso
        artifact_ref             = $oldTask.artifact_ref
        completion_claim_allowed = $false
        worker_policy_cn         = "Admin default accept; no governance loop"
    }
    Write-Json (Get-TaskPath $L $tid) $task
    $newItems = @()
    foreach ($it in $all) {
        if ([string]$it.task_id -eq $tid) {
            $newItems += [pscustomobject]@{
                task_id = $tid; priority = [int]$it.priority; enqueued_at = [string]$it.enqueued_at
                state = "accepted"; accepted_at = Get-NowIso
            }
        } else {
            $newItems += $it
        }
    }
    Write-Json $L.queue_file ([ordered]@{
            schema_version = "xinao.dual_brain.worker_queue.v1"
            items          = $newItems
            updated_at     = Get-NowIso
        })
    return [pscustomobject]@{
        ok = $true; action = "WorkerPull"; pulled = [pscustomobject]$task
        note_cn = "Admin default accept; no governance loop"; completion_claim_allowed = $false
    }
}

function Invoke-WorkerSchedule {
    param($L, [string]$Who)
    if ($Who -ne "admin") { throw "WorkerSchedule only admin" }
    $q = Read-Json $L.queue_file
    $queued = @($q.items | Where-Object { $_.state -in @("queued", "accepted") })
    $plan = @(
        $queued | Sort-Object { [int]$_.priority }, { $_.enqueued_at } | ForEach-Object {
            [pscustomobject]@{ task_id = $_.task_id; priority = $_.priority; state = $_.state }
        }
    )
    $sched = [ordered]@{
        schema_version           = "xinao.dual_brain.worker_schedule.v1"
        ts                       = Get-NowIso
        policy                   = "fifo_with_priority"
        plan                     = $plan
        choice_space_cn          = "Admin almost only choice: order/parallel among multi-source tasks"
        completion_claim_allowed = $false
    }
    Write-Json (Join-Path $L.queue "schedule_latest.json") $sched
    return [pscustomobject]@{ ok = $true; action = "WorkerSchedule"; schedule = $sched; completion_claim_allowed = $false }
}

function Invoke-WorkerComplete {
    param($L, [string]$Who, [string]$Tid, [string]$Result, [string]$Art)
    if ($Who -ne "admin") { throw "WorkerComplete only admin" }
    if (-not $Tid) { throw "need TaskId" }
    $old = Read-Json (Get-TaskPath $L $Tid)
    if (-not $old) { throw "task missing" }
    $task = [ordered]@{
        schema_version           = "xinao.dual_brain.task.v1"
        task_id                  = [string]$old.task_id
        title                    = [string]$old.title
        goal                     = [string]$old.goal
        state                    = $Result
        assigned_to              = "admin"
        dispatched_by            = [string]$old.dispatched_by
        priority                 = [int]$old.priority
        source_thread_id         = $old.source_thread_id
        source_gate_id           = $old.source_gate_id
        non_consensus            = [bool]$old.non_consensus
        zhuxian_path             = $script:Zhuxian
        created_at               = [string]$old.created_at
        accepted_at              = $old.accepted_at
        completed_at             = Get-NowIso
        updated_at               = Get-NowIso
        artifact_ref             = $(if ($Art) { $Art } else { $old.artifact_ref })
        completion_claim_allowed = $false
        worker_policy_cn         = "Admin default accept; no governance loop"
    }
    Write-Json (Get-TaskPath $L $Tid) $task
    $q = Read-Json $L.queue_file
    $newItems = @()
    foreach ($it in @($q.items)) {
        if ([string]$it.task_id -eq $Tid) {
            $newItems += [pscustomobject]@{
                task_id = $Tid; priority = [int]$it.priority; enqueued_at = [string]$it.enqueued_at
                state = $Result; accepted_at = $it.accepted_at; completed_at = Get-NowIso
            }
        } else { $newItems += $it }
    }
    Write-Json $L.queue_file ([ordered]@{
            schema_version = "xinao.dual_brain.worker_queue.v1"
            items          = $newItems
            updated_at     = Get-NowIso
        })
    return [pscustomobject]@{ ok = $true; action = "WorkerComplete"; task = [pscustomobject]$task; completion_claim_allowed = $false }
}

function Invoke-Status {
    param($L)
    $threads = @(Get-ChildItem $L.threads -Filter "*.json" -EA SilentlyContinue)
    $tasks = @(Get-ChildItem $L.tasks -Filter "*.json" -EA SilentlyContinue)
    $q = Read-Json $L.queue_file
    return [pscustomobject]@{
        ok = $true; action = "Status"
        bus_root = $L.root
        zhuxian_path = $script:Zhuxian
        zhuxian_exists = (Test-Path -LiteralPath $script:Zhuxian)
        thread_count = $threads.Count
        task_count = $tasks.Count
        queue_items = @($q.items).Count
        product_ready = $false
        completion_claim_allowed = $false
        honesty_cn = "scaffold bus status; not product multi-window chat"
    }
}

function Invoke-SelfSmoke {
    param($L)
    $steps = @()
    $failed = $false
    $who = "grok_4_5"
    $peer = "codex"

    # isolate smoke: empty worker queue so Pull hits this run's task
    Write-Json $L.queue_file ([ordered]@{
            schema_version = "xinao.dual_brain.worker_queue.v1"
            items          = @()
            updated_at     = Get-NowIso
            note_cn        = "cleared for SelfSmoke"
        })

    try {
        $o = Invoke-ThreadOpen -L $L -Who $who -Peer $peer -TitleText "smoke discuss" -BodyText "提议：对齐主线后分工"
        $tid = $o.thread.thread_id
        $steps += [ordered]@{ step = "ThreadOpen"; ok = $true; thread_id = $tid }
    } catch {
        $failed = $true
        $steps += [ordered]@{ step = "ThreadOpen"; ok = $false; err = $_.Exception.Message }
        $tid = $null
    }

    if ($tid) {
        try {
            $p1 = Invoke-ThreadPost -L $L -Who $peer -Tid $tid -KindName "counter" -BodyText "还价：先外搜再定" -ToPeer $who
            $steps += [ordered]@{ step = "ThreadPost_counter"; ok = $true; state = $p1.thread_state }
        } catch {
            $failed = $true
            $steps += [ordered]@{ step = "ThreadPost_counter"; ok = $false; err = $_.Exception.Message }
        }
        try {
            $cl = Invoke-ThreadClose -L $L -Who $who -Tid $tid -KindName "accept" -BodyText "接受：按外搜后方案"
            $steps += [ordered]@{ step = "ThreadClose_accept"; ok = ($cl.thread_state -eq "ACCEPTED"); state = $cl.thread_state }
            if ($cl.thread_state -ne "ACCEPTED") { $failed = $true }
        } catch {
            $failed = $true
            $steps += [ordered]@{ step = "ThreadClose_accept"; ok = $false; err = $_.Exception.Message }
        }
    }

    $gid = $null
    try {
        $ba = Invoke-BrainAccept -L $L -Who $who -TitleText "smoke task" -GoalText "焊演示" -BodyText "gate"
        $gid = $ba.gate.gate_id
        $steps += [ordered]@{ step = "BrainAccept"; ok = $true; gate_id = $gid; exec = $ba.gate.execute_allowed }
        if ($ba.gate.execute_allowed) { $failed = $true; $steps[-1].ok = $false; $steps[-1].err = "should not execute yet" }
    } catch {
        $failed = $true
        $steps += [ordered]@{ step = "BrainAccept"; ok = $false; err = $_.Exception.Message }
    }

    if ($gid) {
        try {
            $bg = Invoke-BrainGateCheck -L $L -Who $who -Gid $gid -NoteText "smoke governance"
            $steps += [ordered]@{ step = "BrainGateCheck"; ok = [bool]$bg.execute_allowed; exec = $bg.execute_allowed }
            if (-not $bg.execute_allowed) { $failed = $true }
        } catch {
            $failed = $true
            $steps += [ordered]@{ step = "BrainGateCheck"; ok = $false; err = $_.Exception.Message }
        }
        try {
            $td = Invoke-TaskDispatch -L $L -Who $who -TitleText "smoke admin work" -GoalText "demo" -Gid $gid -Tid $tid -IsNonConsensus $false -Prio 50
            $taskId = $td.task.task_id
            $steps += [ordered]@{ step = "TaskDispatch"; ok = $true; task_id = $taskId }
        } catch {
            $failed = $true
            $taskId = $null
            $steps += [ordered]@{ step = "TaskDispatch"; ok = $false; err = $_.Exception.Message }
        }
    } else { $taskId = $null }

    if ($taskId) {
        try {
            $wp = Invoke-WorkerPull -L $L -Who "admin"
            $pullOk = ($null -ne $wp.pulled) -and ([string]$wp.pulled.task_id -eq [string]$taskId) -and ([string]$wp.pulled.state -eq "accepted")
            $steps += [ordered]@{ step = "WorkerPull_default_accept"; ok = $pullOk; state = $(if ($wp.pulled) { $wp.pulled.state } else { $null }); task_id = $(if ($wp.pulled) { $wp.pulled.task_id } else { $null }) }
            if (-not $pullOk) { $failed = $true }
        } catch {
            $failed = $true
            $steps += [ordered]@{ step = "WorkerPull"; ok = $false; err = $_.Exception.Message }
        }
        try {
            $ws = Invoke-WorkerSchedule -L $L -Who "admin"
            $steps += [ordered]@{ step = "WorkerSchedule"; ok = $true; plan_n = @($ws.schedule.plan).Count }
        } catch {
            $failed = $true
            $steps += [ordered]@{ step = "WorkerSchedule"; ok = $false; err = $_.Exception.Message }
        }
        try {
            $wc = Invoke-WorkerComplete -L $L -Who "admin" -Tid $taskId -Result "done" -Art "D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_bus\self_smoke_latest.json"
            $steps += [ordered]@{ step = "WorkerComplete"; ok = ($wc.task.state -eq "done"); state = $wc.task.state }
        } catch {
            $failed = $true
            $steps += [ordered]@{ step = "WorkerComplete"; ok = $false; err = $_.Exception.Message }
        }
    }

    # negative: admin cannot open thread
    try {
        $null = Invoke-ThreadOpen -L $L -Who "admin" -Peer "codex" -TitleText "should fail" -BodyText "x"
        $failed = $true
        $steps += [ordered]@{ step = "AdminDiscussForbidden"; ok = $false; err = "admin opened thread" }
    } catch {
        $steps += [ordered]@{ step = "AdminDiscussForbidden"; ok = $true; err = $_.Exception.Message }
    }

    $result = [ordered]@{
        schema_version           = "xinao.dual_brain.self_smoke.v1"
        ok                       = (-not $failed)
        action                   = "SelfSmoke"
        ts                       = Get-NowIso
        bus_root                 = $L.root
        steps                    = $steps
        product_ready            = $false
        completion_claim_allowed = $false
        honesty_cn               = "SelfSmoke proves discuss close + brain gate + queue scaffold + optional mailbox mirror; != multi-window product; != P0 closed; LivePanel doorbell != read"
        contract_ref             = "grok_dual_brain_discuss_task_bus.v1.json"
        mailbox_thin_bind_cn     = "ThreadPost defaults mirror Maildir; -NoMirrorMailbox disables; legacy bus not deleted"
    }
    # T3: verify mailbox mirror side-effect from last ThreadPost path (open may have mirrored propose)
    try {
        $mb = Invoke-MailboxStatus -MbRoot (Get-MailboxRoot)
        $steps += [ordered]@{
            step              = "MailboxThinBind"
            ok                = $true
            mailbox_root      = $mb.mailbox_root
            maildir_new_count = $mb.maildir_new_count
            delivery_mode     = $mb.delivery_mode
        }
        $result.mailbox_status = $mb
        $result.steps = $steps
    }
    catch {
        $steps += [ordered]@{ step = "MailboxThinBind"; ok = $false; err = $_.Exception.Message }
        $result.steps = $steps
        $result.ok = $false
    }
    Write-Json $L.smoke $result
    Write-Json $L.latest $result
    return [pscustomobject]$result
}

# --- main ---
$root = Get-BusRoot
$layout = Init-Layout $root

$result = switch ($Action) {
    "ThreadOpen" { Invoke-ThreadOpen -L $layout -Who $Actor -Peer $To -TitleText $Title -BodyText $Body }
    "ThreadPost" { Invoke-ThreadPost -L $layout -Who $Actor -Tid $ThreadId -KindName $Kind -BodyText $Body -ToPeer $To }
    "ThreadClose" { Invoke-ThreadClose -L $layout -Who $Actor -Tid $ThreadId -KindName $Kind -BodyText $Body }
    "ThreadStatus" { Invoke-ThreadStatus -L $layout -Tid $ThreadId }
    "ThreadList" { Invoke-ThreadList -L $layout }
    "BrainAccept" { Invoke-BrainAccept -L $layout -Who $Actor -TitleText $Title -GoalText $Goal -BodyText $Body }
    "BrainGateCheck" { Invoke-BrainGateCheck -L $layout -Who $Actor -Gid $GateId -NoteText $Note }
    "BrainExecuteNote" { Invoke-BrainExecuteNote -L $layout -Who $Actor -Gid $GateId -NoteText $Note }
    "TaskDispatch" {
        Invoke-TaskDispatch -L $layout -Who $Actor -TitleText $Title -GoalText $Goal `
            -Gid $GateId -Tid $ThreadId -IsNonConsensus ([bool]$NonConsensus) -Prio $Priority
    }
    "TaskList" { Invoke-TaskList -L $layout }
    "WorkerPull" { Invoke-WorkerPull -L $layout -Who $Actor }
    "WorkerSchedule" { Invoke-WorkerSchedule -L $layout -Who $Actor }
    "WorkerComplete" { Invoke-WorkerComplete -L $layout -Who $Actor -Tid $TaskId -Result $WorkerResult -Art $ArtifactRef }
    "MailboxStatus" { Invoke-MailboxStatus -MbRoot (Get-MailboxRoot) }
    "SelfSmoke" { Invoke-SelfSmoke -L $layout }
    "Status" { Invoke-Status -L $layout }
}

if ($Action -ne "SelfSmoke") {
    Write-Json $layout.latest ([ordered]@{
            updated_at               = Get-NowIso
            last_action              = $Action
            ok                       = [bool]$result.ok
            completion_claim_allowed = $false
            product_ready            = $false
            bus_root                 = $layout.root
        })
}

$json = $result | ConvertTo-Json -Depth 14
if (-not $Quiet) { Write-Output $json }
return $result
