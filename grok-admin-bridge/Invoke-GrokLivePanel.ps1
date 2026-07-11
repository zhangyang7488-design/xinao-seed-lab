#Requires -Version 5.1
<#
.SYNOPSIS
  Live panel function-tier thin weld skeleton (NOT a product-ready multi-window panel).

.DESCRIPTION
  Local directory bus: append-only messages.jsonl + presence heartbeats + ack receipts.
  Forbidden: SDK exec / subagent pool as window body; remote A2A/Kafka as default transport.
  completion_claim_allowed is always false in outputs.

  === T3 / 门铃语义硬钉（≠ 已读 · ≠ 交流主路）===
  EnsureIdentity / InjectPending = DOORBELL ONLY:
    - 侦测活体 → 复用置前 → 可选冷启 → 写 inject 待读义务队列
    - 证明：门铃可响 / 入口可尝试拉起 / inject 行可落盘
    - 不证明：窗内智能已读板、已读 mailbox、已消费 discuss、已 ack
  讨论/投递主路 = dual_brain_bus (+ ThreadPost→mailbox Maildir 薄绑)；
  禁止把 LivePanel 或 SendKeys 当交流主路。

.PARAMETER Action
  Post | Read | Ack | PresenceUpsert | PresenceProbe | WindowDetect | EnsureIdentity | InjectPending | RouteMention | TaskCreate | TaskUpdate | SelfSmoke

.EXAMPLE
  .\Invoke-GrokLivePanel.ps1 -Action SelfSmoke
  .\Invoke-GrokLivePanel.ps1 -Action EnsureIdentity -Identity admin -NoColdStart
  .\Invoke-GrokLivePanel.ps1 -Action RouteMention -From grok_4_5 -Body '@admin 请读板' -Mentions admin
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "Post", "Read", "Ack", "PresenceUpsert", "PresenceProbe",
        "WindowDetect", "EnsureIdentity", "InjectPending", "RouteMention",
        "TaskCreate", "TaskUpdate", "SelfSmoke"
    )]
    [string]$Action,

    [ValidateSet("grok_4_5", "admin", "codex")]
    [string]$Identity = "admin",

    [ValidateSet("grok_4_5", "admin", "codex")]
    [string]$From = "admin",

    [string]$To = "*",

    [string]$Body = "",

    [string[]]$Mentions = @(),

    [ValidateSet(
        "note", "ask", "discuss", "reply", "counter", "challenge",
        "accept", "reject", "each_close", "withdraw",
        "task_ptr", "ack_request", "read_receipt", "system"
    )]
    [string]$Kind = "note",

    [string]$Channel = "main",

    [string]$MsgId = "",

    [ValidateSet("read", "accepted", "declined", "deferred")]
    [string]$AckStatus = "read",

    [string]$AckNote = "",

    [ValidateSet("open", "closed", "unknown")]
    [string]$PresenceState = "open",

    [int]$FreshSeconds = 120,

    [int]$Tail = 20,

    [string]$MentionFilter = "",

    [string]$Since = "",

    [string]$ReplyTo = "",

    [string]$TaskRef = "",

    [string]$ArtifactRef = "",

    [string]$PanelRoot = "",

    [switch]$NoColdStart,

    [switch]$SkipInject,

    [switch]$SkipActivate,

    [ValidateSet("submitted", "working", "completed", "failed", "canceled")]
    [string]$TaskStatus = "submitted",

    [string]$TaskId = "",

    [string]$TaskTitle = "",

    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
try { chcp 65001 | Out-Null } catch {}
$utf8 = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = $utf8
try { [Console]::OutputEncoding = $utf8 } catch {}

$script:Identities = @("grok_4_5", "admin", "codex")
$bridge = $PSScriptRoot

function Get-RuntimeRoot {
    $resolver = Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1"
    if (Test-Path -LiteralPath $resolver) {
        try { return [string](& $resolver) } catch {}
    }
    return "D:\XINAO_RESEARCH_RUNTIME"
}

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function New-MsgId {
    return [guid]::NewGuid().ToString("N")
}

function Get-NowIso {
    return (Get-Date).ToString("o")
}

function ConvertTo-JsonUtf8([object]$Obj, [int]$Depth = 12) {
    return ($Obj | ConvertTo-Json -Depth $Depth -Compress:$false)
}

function Write-JsonFile([string]$Path, [object]$Obj) {
    $dir = Split-Path -Parent $Path
    Ensure-Dir $dir
    [System.IO.File]::WriteAllText($Path, (ConvertTo-JsonUtf8 $Obj), $utf8)
}

function Parse-MentionsFromBody([string]$Text) {
    $found = @()
    if ([string]::IsNullOrWhiteSpace($Text)) { return $found }
    $rx = [regex]'@([A-Za-z0-9_]+)'
    foreach ($m in $rx.Matches($Text)) {
        $token = $m.Groups[1].Value
        $map = @{
            "grok_4_5" = "grok_4_5"; "4.5" = "grok_4_5"; "grok45" = "grok_4_5"
            "admin" = "admin"; "admin_isolated" = "admin"
            "codex" = "codex"; "s" = "codex"
            "all" = "@all"
        }
        if ($map.ContainsKey($token)) {
            $found += $map[$token]
        }
        elseif ($script:Identities -contains $token) {
            $found += $token
        }
    }
    return @($found | Select-Object -Unique)
}

function Initialize-PanelLayout([string]$Root) {
    Ensure-Dir $Root
    Ensure-Dir (Join-Path $Root "panel")
    Ensure-Dir (Join-Path $Root "presence")
    Ensure-Dir (Join-Path $Root "acks")
    Ensure-Dir (Join-Path $Root "tasks")
    Ensure-Dir (Join-Path $Root "artifacts")
    Ensure-Dir (Join-Path $Root "inject")
    Ensure-Dir (Join-Path $Root "ensure")
    return [ordered]@{
        root            = $Root
        messages_jsonl  = Join-Path $Root "panel\messages.jsonl"
        presence_dir    = Join-Path $Root "presence"
        acks_dir        = Join-Path $Root "acks"
        tasks_dir       = Join-Path $Root "tasks"
        artifacts_dir   = Join-Path $Root "artifacts"
        inject_dir      = Join-Path $Root "inject"
        ensure_dir      = Join-Path $Root "ensure"
        latest_status   = Join-Path $Root "latest.json"
        self_smoke      = Join-Path $Root "self_smoke_latest.json"
    }
}

function Get-IdentityLaunchMap {
    $desk = Join-Path $env:USERPROFILE "Desktop"
    return @{
        grok_4_5 = @{
            desktop_lnk    = (Join-Path $desk "Grok 4.5.lnk")
            wt_profile     = "XINAO Grok 4.5"
            process_names  = @("grok")
            title_hints    = @("XINAO Grok 4.5", "Grok 4.5")
        }
        admin = @{
            desktop_lnk    = (Join-Path $desk "Grok Admin Isolated.lnk")
            wt_profile     = "XINAO Grok Admin Isolated"
            process_names  = @("grok")
            title_hints    = @("XINAO Grok Admin Isolated", "Grok Admin Isolated", "Admin Isolated")
        }
        codex = @{
            desktop_lnk    = (Join-Path $desk "OPEN CODEX S HARDMODE.lnk")
            wt_profile     = "XINAO Codex S Hardmode"
            process_names  = @("codex", "codex-code-mode-host")
            title_hints    = @("XINAO Codex", "Codex", "Hardmode")
        }
    }
}

function Initialize-Win32Foreground {
    if ($script:Win32Ready) { return }
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class LivePanelWin32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
}
"@ -ErrorAction SilentlyContinue
    $script:Win32Ready = $true
}

function Test-TitleHintMatch([string]$Title, [string[]]$Hints) {
    if ([string]::IsNullOrWhiteSpace($Title)) { return $false }
    foreach ($h in $Hints) {
        if ($Title -like ("*{0}*" -f $h)) { return $true }
    }
    return $false
}

function Invoke-WindowDetect {
    param(
        [string]$Id = ""
    )
    $map = Get-IdentityLaunchMap
    $ids = if ($Id -and ($script:Identities -contains $Id)) { @($Id) } else { $script:Identities }
    $rows = @()
    foreach ($identity in $ids) {
        $cfg = $map[$identity]
        $procs = @()
        foreach ($pn in $cfg.process_names) {
            $procs += @(Get-Process -Name $pn -ErrorAction SilentlyContinue)
        }
        # also scan WindowsTerminal titles
        $wt = @(Get-Process -Name "WindowsTerminal" -ErrorAction SilentlyContinue)
        $matched = @()
        foreach ($p in ($procs + $wt | Select-Object -Unique)) {
            $title = ""
            try { $title = [string]$p.MainWindowTitle } catch {}
            $byName = $cfg.process_names -contains $p.ProcessName
            $byTitle = Test-TitleHintMatch $title $cfg.title_hints
            if ($byName -or $byTitle) {
                if ($p.MainWindowHandle -ne [IntPtr]::Zero -or $byName) {
                    $matched += [ordered]@{
                        process_name = $p.ProcessName
                        pid          = $p.Id
                        title        = $title
                        has_main_window = ($p.MainWindowHandle -ne [IntPtr]::Zero)
                        main_window_handle = [int64]$p.MainWindowHandle
                        match_by     = $(if ($byTitle) { "title" } elseif ($byName) { "process_name" } else { "unknown" })
                    }
                }
            }
        }
        # unique by pid
        $uniq = @{}
        $list = @()
        foreach ($m in $matched) {
            if (-not $uniq.ContainsKey([string]$m.pid)) {
                $uniq[[string]$m.pid] = $true
                $list += [pscustomobject]$m
            }
        }
        $best = $null
        $withWin = @($list | Where-Object { $_.has_main_window } | Select-Object -First 1)
        if ($withWin.Count -gt 0) { $best = $withWin[0] }
        elseif ($list.Count -gt 0) { $best = $list[0] }

        $rows += [pscustomobject][ordered]@{
            identity            = $identity
            process_alive       = ($list.Count -gt 0)
            window_visible_hint = [bool]($best -and $best.has_main_window)
            match_count         = $list.Count
            best                = $best
            matches             = $list
            desktop_lnk         = $cfg.desktop_lnk
            desktop_lnk_exists  = (Test-Path -LiteralPath $cfg.desktop_lnk)
            wt_profile          = $cfg.wt_profile
            honesty_cn          = "B层进程/窗口侦测；≠会话已登录可接；≠产品互通"
        }
    }
    return [pscustomobject]@{
        ok                       = $true
        action                   = "WindowDetect"
        probed_at                = Get-NowIso
        identities               = $rows
        completion_claim_allowed = $false
        product_ready            = $false
        honesty_cn               = "仅桌面活体侦测；复用优先于冷启动；不能声称已接活"
    }
}

function Invoke-ActivateWindowHandle([int64]$Handle) {
    if ($Handle -eq 0) {
        return [pscustomobject]@{ ok = $false; reason = "no_handle" }
    }
    try {
        Initialize-Win32Foreground
        $h = [IntPtr]$Handle
        if ([LivePanelWin32]::IsIconic($h)) {
            [void][LivePanelWin32]::ShowWindow($h, 9) # SW_RESTORE
        }
        else {
            [void][LivePanelWin32]::ShowWindow($h, 5) # SW_SHOW
        }
        $fg = [LivePanelWin32]::SetForegroundWindow($h)
        return [pscustomobject]@{ ok = [bool]$fg; handle = $Handle; method = "SetForegroundWindow" }
    }
    catch {
        return [pscustomobject]@{ ok = $false; error = $_.Exception.Message }
    }
}

function Invoke-InjectPending {
    # DOORBELL ONLY: write inject obligation. ≠ message read. ≠ mailbox consumed. ≠ discuss mainline.
    param(
        $Layout,
        [string]$Id,
        [string]$Reason = "read_panel",
        [string]$MessageId = "",
        [string]$BodyText = "",
        [string]$TaskRefVal = ""
    )
    if ($script:Identities -notcontains $Id) { throw "Invalid identity: $Id" }
    $path = Join-Path $Layout.inject_dir ("{0}_pending.jsonl" -f $Id)
    $env = [ordered]@{
        schema_version           = "xinao.live_panel.inject.v1"
        inject_id                = (New-MsgId)
        ts                       = Get-NowIso
        identity                 = $Id
        reason                   = $Reason
        msg_id                   = $(if ($MessageId) { $MessageId } else { $null })
        body_hint                = $BodyText
        task_ref                 = $(if ($TaskRefVal) { $TaskRefVal } else { $null })
        role                     = "doorbell_only"
        instruction_cn           = "门铃义务：窗本体应读公共板/mailbox 并回执；本队列写入≠已读；≠交流主路；禁止 SendKeys 当主通道"
        completion_claim_allowed = $false
    }
    $line = ($env | ConvertTo-Json -Depth 8 -Compress)
    Add-Content -LiteralPath $path -Value $line -Encoding UTF8
    return [pscustomobject]@{
        ok                       = $true
        action                   = "InjectPending"
        identity                 = $Id
        path                     = $path
        inject_id                = $env.inject_id
        role                     = "doorbell_only"
        is_not                   = @("already_read", "discuss_mainline", "mailbox_consumed", "sendkeys_channel")
        completion_claim_allowed = $false
        honesty_cn               = "门铃 inject 落地≠窗内已消费；交流主路=bus/mailbox 非 LivePanel"
    }
}

function Invoke-ColdStartIdentity {
    param([string]$Id)
    $map = Get-IdentityLaunchMap
    $cfg = $map[$Id]
    if (-not $cfg) { throw "unknown identity $Id" }
    $started = $false
    $method = $null
    $detail = $null
    if (Test-Path -LiteralPath $cfg.desktop_lnk) {
        Start-Process -FilePath $cfg.desktop_lnk
        $started = $true
        $method = "desktop_lnk"
        $detail = $cfg.desktop_lnk
    }
    else {
        $wt = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\wt.exe"
        if (Test-Path -LiteralPath $wt) {
            Start-Process -FilePath $wt -ArgumentList @("-p", $cfg.wt_profile)
            $started = $true
            $method = "wt_profile"
            $detail = $cfg.wt_profile
        }
    }
    return [pscustomobject]@{
        ok                       = $started
        action                   = "ColdStart"
        identity                 = $Id
        method                   = $method
        detail                   = $detail
        completion_claim_allowed = $false
        honesty_cn               = "仅尝试拉起入口；≠已登录可接；≠已读板"
    }
}

function Invoke-EnsureIdentity {
    # DOORBELL ONLY state machine: detect → reuse/foreground → cold_start → inject.
    # Success here ≠ peer read the message / mailbox / discuss body. Not the comms mainline.
    param(
        $Layout,
        [string]$Id,
        [string]$BodyText = "",
        [string]$MessageId = "",
        [string]$TaskRefVal = "",
        [bool]$AllowColdStart = $true,
        [bool]$DoInject = $true,
        [bool]$DoActivate = $true
    )
    if ($script:Identities -notcontains $Id) { throw "Invalid identity: $Id" }
    $trace = @()
    # 1 detect
    $det = Invoke-WindowDetect -Id $Id
    $row = @($det.identities | Where-Object { $_.identity -eq $Id } | Select-Object -First 1)[0]
    $trace += [ordered]@{ step = "detect"; process_alive = $row.process_alive; window_visible_hint = $row.window_visible_hint; match_count = $row.match_count }

    $branch = "none"
    $activate = $null
    $cold = $null
    $inject = $null

    if ($row.process_alive) {
        # 2 reuse
        $branch = "reuse"
        if ($DoActivate -and $row.best -and $row.best.has_main_window) {
            $activate = Invoke-ActivateWindowHandle -Handle ([int64]$row.best.main_window_handle)
            $trace += [ordered]@{ step = "activate_reuse"; ok = $activate.ok }
        }
        else {
            $trace += [ordered]@{ step = "activate_reuse"; ok = $false; reason = "skip_or_no_main_window" }
        }
    }
    elseif ($AllowColdStart) {
        # 3 cold start
        $branch = "cold_start"
        $cold = Invoke-ColdStartIdentity -Id $Id
        $trace += [ordered]@{ step = "cold_start"; ok = $cold.ok; method = $cold.method }
        Start-Sleep -Milliseconds 800
        $det2 = Invoke-WindowDetect -Id $Id
        $row = @($det2.identities | Where-Object { $_.identity -eq $Id } | Select-Object -First 1)[0]
        $trace += [ordered]@{ step = "detect_after_cold"; process_alive = $row.process_alive }
        if ($DoActivate -and $row.best -and $row.best.has_main_window) {
            $activate = Invoke-ActivateWindowHandle -Handle ([int64]$row.best.main_window_handle)
            $trace += [ordered]@{ step = "activate_after_cold"; ok = $activate.ok }
        }
    }
    else {
        $branch = "not_started_no_cold"
        $trace += [ordered]@{ step = "cold_start"; ok = $false; reason = "NoColdStart" }
    }

    # 4 inject
    if ($DoInject) {
        $inject = Invoke-InjectPending -Layout $Layout -Id $Id -Reason "ensure_read_panel" -MessageId $MessageId -BodyText $BodyText -TaskRefVal $TaskRefVal
        $trace += [ordered]@{ step = "inject"; ok = $inject.ok; path = $inject.path }
    }

    # auxiliary file heartbeat
    try {
        $null = Invoke-PresenceUpsert -Layout $Layout -Id $Id -StateName $(if ($row.process_alive) { "open" } else { "unknown" }) -FreshSec $FreshSeconds
        $trace += [ordered]@{ step = "file_heartbeat"; ok = $true }
    }
    catch {
        $trace += [ordered]@{ step = "file_heartbeat"; ok = $false }
    }

    $accepted = $false # never claim accepted without ack
    $result = [ordered]@{
        schema_version           = "xinao.live_panel.ensure_identity.v1"
        ok                       = $true
        action                   = "EnsureIdentity"
        identity                 = $Id
        branch                   = $branch
        process_alive            = [bool]$row.process_alive
        window_visible_hint      = [bool]$row.window_visible_hint
        state_machine            = @("detect", "reuse_or_cold_start", "inject")
        trace                    = $trace
        detect                   = $row
        activate                 = $activate
        cold_start               = $cold
        inject                   = $inject
        accepted_live            = $accepted
        role                     = "doorbell_only"
        is_not                   = @("already_read", "discuss_mainline", "mailbox_consumed", "sendkeys_channel")
        completion_claim_allowed = $false
        product_ready            = $false
        honesty_cn               = "门铃 only：复用优先；冷启动仅拉入口；inject≠已读；无 ack 不能声称已接活；交流主路=dual_brain_bus/mailbox"
        forbid_cn                = "禁止 SDK exec/子代理冒充窗；禁止无活体假送达；禁止 SendKeys 当交流主路；禁止把 EnsureIdentity 当已读"
    }
    $outPath = Join-Path $Layout.ensure_dir ("{0}_latest.json" -f $Id)
    Write-JsonFile $outPath $result
    return [pscustomobject]$result
}

function Invoke-RouteMention {
    param(
        $Layout,
        [string]$FromId,
        [string]$BodyText,
        [string[]]$MentionList,
        [bool]$AllowColdStart = $true
    )
    if ([string]::IsNullOrWhiteSpace($BodyText)) { throw "RouteMention requires -Body" }
    $post = Invoke-Post -Layout $Layout -FromId $FromId -ToId "*" -BodyText $BodyText `
        -MentionList $MentionList -KindName $Kind -ChannelName $Channel -ExplicitMsgId "" `
        -ReplyToId $ReplyTo -TaskRefVal $TaskRef -ArtifactRefVal $ArtifactRef
    $targets = @($post.mentions | Where-Object { $script:Identities -contains $_ })
    $ensures = @()
    foreach ($t in $targets) {
        $ensures += Invoke-EnsureIdentity -Layout $Layout -Id $t -BodyText $BodyText -MessageId $post.msg_id `
            -TaskRefVal $TaskRef -AllowColdStart $AllowColdStart -DoInject (-not $SkipInject) -DoActivate (-not $SkipActivate)
    }
    return [pscustomobject]@{
        ok                       = $true
        action                   = "RouteMention"
        msg_id                   = $post.msg_id
        mentions                 = $targets
        ensure_results           = $ensures
        completion_claim_allowed = $false
        product_ready            = $false
        honesty_cn               = "已 Post+Ensure；各窗须读 inject/板并 ack 才算接活"
    }
}

function Invoke-TaskCreate {
    param(
        $Layout,
        [string]$TitleText,
        [string]$OwnerId,
        [string]$BodyText,
        [string]$Artifact
    )
    $tid = if ($TaskId) { $TaskId } else { "task_" + (New-MsgId).Substring(0, 12) }
    $path = Join-Path $Layout.tasks_dir ("{0}.json" -f $tid)
    $doc = [ordered]@{
        schema_version           = "xinao.live_panel.task.v1"
        task_id                  = $tid
        title                    = $(if ($TitleText) { $TitleText } else { "untitled" })
        status                   = "submitted"
        owner                    = $OwnerId
        created_at               = Get-NowIso
        updated_at               = Get-NowIso
        body                     = $BodyText
        artifact_ref             = $(if ($Artifact) { $Artifact } else { $null })
        completion_claim_allowed = $false
        honesty_cn               = "任务文件薄绑；≠后台 333 闭合"
    }
    Write-JsonFile $path $doc
    $posted = $null
    if ($BodyText -or $TitleText) {
        $b = if ($BodyText) { $BodyText } else { "任务 $tid : $TitleText" }
        if ($OwnerId -and $script:Identities -contains $OwnerId) {
            $b = "@$OwnerId $b"
        }
        $posted = Invoke-Post -Layout $Layout -FromId $From -ToId $(if ($OwnerId) { $OwnerId } else { "*" }) `
            -BodyText $b -MentionList @($(if ($OwnerId) { $OwnerId } else { @() })) `
            -KindName "task_ptr" -ChannelName $Channel -ExplicitMsgId "" -ReplyToId "" `
            -TaskRefVal $tid -ArtifactRefVal $Artifact
    }
    return [pscustomobject]@{
        ok                       = $true
        action                   = "TaskCreate"
        task_id                  = $tid
        path                     = $path
        post                     = $posted
        completion_claim_allowed = $false
    }
}

function Invoke-TaskUpdate {
    param(
        $Layout,
        [string]$Id,
        [string]$StatusName,
        [string]$Artifact
    )
    if ([string]::IsNullOrWhiteSpace($Id)) { throw "TaskUpdate requires -TaskId" }
    $path = Join-Path $Layout.tasks_dir ("{0}.json" -f $Id)
    if (-not (Test-Path -LiteralPath $path)) { throw "task not found: $path" }
    $doc = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    $doc.status = $StatusName
    $doc.updated_at = Get-NowIso
    if ($Artifact) { $doc.artifact_ref = $Artifact }
    $doc.completion_claim_allowed = $false
    Write-JsonFile $path $doc
    return [pscustomobject]@{
        ok                       = $true
        action                   = "TaskUpdate"
        task_id                  = $Id
        status                   = $StatusName
        path                     = $path
        artifact_ref             = $doc.artifact_ref
        completion_claim_allowed = $false
    }
}

function Invoke-Post {
    param(
        $Layout,
        [string]$FromId,
        [string]$ToId,
        [string]$BodyText,
        [string[]]$MentionList,
        [string]$KindName,
        [string]$ChannelName,
        [string]$ExplicitMsgId,
        [string]$ReplyToId,
        [string]$TaskRefVal,
        [string]$ArtifactRefVal
    )
    if ([string]::IsNullOrWhiteSpace($BodyText)) {
        throw "Post requires -Body"
    }
    if ($script:Identities -notcontains $FromId) {
        throw "Invalid -From identity: $FromId"
    }
    $bodyMentions = Parse-MentionsFromBody $BodyText
    $allMentions = @($MentionList + $bodyMentions | Where-Object { $_ } | Select-Object -Unique)
    $id = if ($ExplicitMsgId) { $ExplicitMsgId } else { New-MsgId }
    $env = [ordered]@{
        schema_version = "xinao.live_panel.message.v1"
        msg_id         = $id
        ts             = Get-NowIso
        from           = $FromId
        to             = $ToId
        kind           = $KindName
        body           = $BodyText
        mentions       = @($allMentions)
        channel        = $ChannelName
        reply_to       = $(if ($ReplyToId) { $ReplyToId } else { $null })
        task_ref       = $(if ($TaskRefVal) { $TaskRefVal } else { $null })
        artifact_ref   = $(if ($ArtifactRefVal) { $ArtifactRefVal } else { $null })
        transport      = "local_append_jsonl_directory_bus"
        note_cn        = "skeleton post; not product live panel"
    }
    $line = ($env | ConvertTo-Json -Depth 8 -Compress)
    Add-Content -LiteralPath $Layout.messages_jsonl -Value $line -Encoding UTF8
    return [pscustomobject]@{
        ok                       = $true
        action                   = "Post"
        msg_id                   = $id
        path                     = $Layout.messages_jsonl
        mentions                 = @($allMentions)
        completion_claim_allowed = $false
    }
}

function Invoke-Read {
    param(
        $Layout,
        [int]$TailN,
        [string]$MentionFilt,
        [string]$SinceIso
    )
    $rows = @()
    if (Test-Path -LiteralPath $Layout.messages_jsonl) {
        $lines = Get-Content -LiteralPath $Layout.messages_jsonl -Encoding UTF8 -ErrorAction SilentlyContinue
        foreach ($ln in $lines) {
            if ([string]::IsNullOrWhiteSpace($ln)) { continue }
            try {
                $obj = $ln | ConvertFrom-Json
                $rows += $obj
            }
            catch {
                # skip corrupt line
            }
        }
    }
    if ($SinceIso) {
        $sinceDt = [datetime]::Parse($SinceIso)
        $rows = @($rows | Where-Object {
                try { [datetime]::Parse([string]$_.ts) -ge $sinceDt } catch { $true }
            })
    }
    if ($MentionFilt) {
        $mf = $MentionFilt
        $rows = @($rows | Where-Object {
                $ments = @($_.mentions)
                ($ments -contains $mf) -or ([string]$_.to -eq $mf) -or ([string]$_.body -match [regex]::Escape("@$mf"))
            })
    }
    if ($TailN -gt 0 -and $rows.Count -gt $TailN) {
        $rows = @($rows | Select-Object -Last $TailN)
    }
    return [pscustomobject]@{
        ok                       = $true
        action                   = "Read"
        count                    = $rows.Count
        messages                 = $rows
        path                     = $Layout.messages_jsonl
        completion_claim_allowed = $false
    }
}

function Invoke-Ack {
    param(
        $Layout,
        [string]$MessageId,
        [string]$ReaderId,
        [string]$StatusName,
        [string]$NoteText
    )
    if ([string]::IsNullOrWhiteSpace($MessageId)) {
        throw "Ack requires -MsgId"
    }
    if ($script:Identities -notcontains $ReaderId) {
        throw "Invalid -Identity for Ack: $ReaderId"
    }
    $ackPath = Join-Path $Layout.acks_dir ("{0}__{1}.json" -f $MessageId, $ReaderId)
    $ack = [ordered]@{
        schema_version           = "xinao.live_panel.ack.v1"
        msg_id                   = $MessageId
        reader                   = $ReaderId
        status                   = $StatusName
        ack_ts                   = Get-NowIso
        note                     = $NoteText
        completion_claim_allowed = $false
        honesty_cn               = "ack file only; does not prove human-visible TUI responded"
    }
    Write-JsonFile $ackPath $ack
    return [pscustomobject]@{
        ok                       = $true
        action                   = "Ack"
        msg_id                   = $MessageId
        reader                   = $ReaderId
        path                     = $ackPath
        completion_claim_allowed = $false
    }
}

function Invoke-PresenceUpsert {
    param(
        $Layout,
        [string]$Id,
        [string]$StateName,
        [int]$FreshSec
    )
    if ($script:Identities -notcontains $Id) {
        throw "Invalid -Identity: $Id"
    }
    $path = Join-Path $Layout.presence_dir ("{0}.json" -f $Id)
    $doc = [ordered]@{
        schema_version           = "xinao.live_panel.presence.v1"
        identity                 = $Id
        state                    = $StateName
        heartbeat_ts             = Get-NowIso
        fresh_seconds            = $FreshSec
        source                   = "local_heartbeat_file"
        honesty_cn               = "file heartbeat freshness only; not proof of visible TUI foreground"
        forbid_cn                = "must not set open via SDK exec or subagent pool"
        completion_claim_allowed = $false
    }
    Write-JsonFile $path $doc
    return [pscustomobject]@{
        ok                       = $true
        action                   = "PresenceUpsert"
        identity                 = $Id
        state                    = $StateName
        path                     = $path
        completion_claim_allowed = $false
    }
}

function Invoke-PresenceProbe {
    param(
        $Layout,
        [int]$FreshSec
    )
    $now = Get-Date
    $results = @()
    foreach ($id in $script:Identities) {
        $path = Join-Path $Layout.presence_dir ("{0}.json" -f $id)
        $row = [ordered]@{
            identity      = $id
            path          = $path
            file_exists   = $false
            state_written = $null
            heartbeat_ts  = $null
            age_seconds   = $null
            effective     = "unknown"
            fresh_seconds = $FreshSec
        }
        if (Test-Path -LiteralPath $path) {
            $row.file_exists = $true
            try {
                $doc = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
                $row.state_written = [string]$doc.state
                $row.heartbeat_ts = [string]$doc.heartbeat_ts
                $fs = $FreshSec
                if ($doc.fresh_seconds) { $fs = [int]$doc.fresh_seconds }
                $row.fresh_seconds = $fs
                $hb = [datetime]::Parse([string]$doc.heartbeat_ts)
                $age = ($now - $hb).TotalSeconds
                $row.age_seconds = [math]::Round($age, 1)
                if ($age -le $fs) {
                    if ([string]$doc.state -eq "closed") {
                        $row.effective = "closed"
                    }
                    else {
                        $row.effective = "open"
                    }
                }
                else {
                    $row.effective = "closed"
                }
            }
            catch {
                $row.effective = "unknown"
                $row.error = $_.Exception.Message
            }
        }
        else {
            $row.effective = "unknown"
        }
        $results += [pscustomobject]$row
    }
    return [pscustomobject]@{
        ok                       = $true
        action                   = "PresenceProbe"
        probed_at                = Get-NowIso
        identities               = $results
        completion_claim_allowed = $false
        honesty_cn               = "effective=open means fresh local heartbeat only; not product presence of live TUI"
    }
}

function Invoke-SelfSmoke {
    param($Layout)
    $steps = @()
    $failed = $false
    $probe = $null

    foreach ($id in $script:Identities) {
        try {
            $r = Invoke-PresenceUpsert -Layout $Layout -Id $id -StateName "open" -FreshSec $FreshSeconds
            $steps += [ordered]@{ step = "PresenceUpsert_$id"; ok = $true; path = $r.path }
        }
        catch {
            $failed = $true
            $steps += [ordered]@{ step = "PresenceUpsert_$id"; ok = $false; error = $_.Exception.Message }
        }
    }

    try {
        $probe = Invoke-PresenceProbe -Layout $Layout -FreshSec $FreshSeconds
        $openCount = @($probe.identities | Where-Object { $_.effective -eq "open" }).Count
        $steps += [ordered]@{ step = "PresenceProbe"; ok = ($openCount -ge 1); open_count = $openCount }
        if ($openCount -lt 1) { $failed = $true }
    }
    catch {
        $failed = $true
        $steps += [ordered]@{ step = "PresenceProbe"; ok = $false; error = $_.Exception.Message }
        $probe = $null
    }

    try {
        $wd = Invoke-WindowDetect
        $alive = @($wd.identities | Where-Object { $_.process_alive }).Count
        $steps += [ordered]@{ step = "WindowDetect"; ok = $true; process_alive_count = $alive }
    }
    catch {
        $steps += [ordered]@{ step = "WindowDetect"; ok = $false; error = $_.Exception.Message }
    }

    try {
        $ens = Invoke-EnsureIdentity -Layout $Layout -Id "admin" -BodyText "SelfSmoke ensure" -AllowColdStart $false -DoInject $true -DoActivate $false
        $steps += [ordered]@{ step = "EnsureIdentity_admin_NoColdStart"; ok = $true; branch = $ens.branch; process_alive = $ens.process_alive }
    }
    catch {
        $steps += [ordered]@{ step = "EnsureIdentity_admin_NoColdStart"; ok = $false; error = $_.Exception.Message }
    }

    $smokeBody = "@grok_4_5 N1 SelfSmoke scaffold ping $(Get-NowIso) - not product"
    $postedId = $null
    try {
        $post = Invoke-Post -Layout $Layout -FromId "admin" -ToId "grok_4_5" -BodyText $smokeBody `
            -MentionList @("grok_4_5") -KindName "system" -ChannelName "main" -ExplicitMsgId "" `
            -ReplyToId "" -TaskRefVal "" -ArtifactRefVal ""
        $steps += [ordered]@{ step = "Post"; ok = $true; msg_id = $post.msg_id; mentions = $post.mentions }
        $postedId = $post.msg_id
    }
    catch {
        $failed = $true
        $steps += [ordered]@{ step = "Post"; ok = $false; error = $_.Exception.Message }
    }

    try {
        $read = Invoke-Read -Layout $Layout -TailN 5 -MentionFilt "grok_4_5" -SinceIso ""
        $hit = $false
        if ($postedId) {
            $hit = @($read.messages | Where-Object { $_.msg_id -eq $postedId }).Count -gt 0
        }
        $steps += [ordered]@{ step = "Read"; ok = $hit; count = $read.count; hit_posted = $hit }
        if (-not $hit) { $failed = $true }
    }
    catch {
        $failed = $true
        $steps += [ordered]@{ step = "Read"; ok = $false; error = $_.Exception.Message }
    }

    if ($postedId) {
        try {
            $ack = Invoke-Ack -Layout $Layout -MessageId $postedId -ReaderId "grok_4_5" -StatusName "read" -NoteText "SelfSmoke ack scaffold"
            $steps += [ordered]@{ step = "Ack"; ok = (Test-Path -LiteralPath $ack.path); path = $ack.path }
            if (-not (Test-Path -LiteralPath $ack.path)) { $failed = $true }
        }
        catch {
            $failed = $true
            $steps += [ordered]@{ step = "Ack"; ok = $false; error = $_.Exception.Message }
        }
    }
    else {
        $failed = $true
        $steps += [ordered]@{ step = "Ack"; ok = $false; error = "no msg_id from Post" }
    }

    $selfPath = $PSCommandPath
    if (-not $selfPath) { $selfPath = Join-Path $bridge "Invoke-GrokLivePanel.ps1" }
    $raw = Get-Content -LiteralPath $selfPath -Raw -Encoding UTF8
    $bad = @()
    if ($raw -match '(?im)^\s*[^#]*\b(Invoke-Codex|codex\.exe|npx\s+@a2a)\b') {
        $bad += "sdk_like_invoke"
        $failed = $true
    }
    $steps += [ordered]@{
        step = "NoSdkExecStatic"
        ok   = ($bad.Count -eq 0)
        bad  = $bad
    }

    $result = [ordered]@{
        schema_version           = "xinao.live_panel.self_smoke.v1"
        ok                       = (-not $failed)
        action                   = "SelfSmoke"
        ts                       = Get-NowIso
        panel_root               = $Layout.root
        steps                    = $steps
        presence_probe           = $probe
        implementation_status    = "design_written_scripts_smoke_optional"
        status                   = "scaffold_written_not_product"
        completion_claim_allowed = $false
        product_ready            = $false
        honesty_cn               = "SelfSmoke ok 仅表示骨架 Post/Read/Ack/Presence 闭环可跑；≠活面板产品可用；≠三窗 TUI 真互通"
        contract_ref             = "grok_live_panel_function_tier_thin_weld.v1.json"
        parent_intent_ref        = "grok_multi_window_live_panel_intent.v1.json"
        forbid_claim_cn          = "禁止宣称 live panel ready / presence=真实窗前台"
    }
    Write-JsonFile $Layout.self_smoke $result
    Write-JsonFile $Layout.latest_status ([ordered]@{
            schema_version           = "xinao.live_panel.latest.v1"
            updated_at               = Get-NowIso
            last_action              = "SelfSmoke"
            ok                       = $result.ok
            completion_claim_allowed = $false
            status                   = "scaffold_written_not_product"
            self_smoke_ref           = $Layout.self_smoke
            product_ready            = $false
        })
    return [pscustomobject]$result
}

# --- main ---
$runtime = Get-RuntimeRoot
if (-not $PanelRoot) {
    $PanelRoot = Join-Path $runtime "state\live_panel"
}
$layout = Initialize-PanelLayout $PanelRoot
$allowCold = -not $NoColdStart.IsPresent
$doInject = -not $SkipInject.IsPresent
$doActivate = -not $SkipActivate.IsPresent

$result = switch ($Action) {
    "Post" {
        Invoke-Post -Layout $layout -FromId $From -ToId $To -BodyText $Body `
            -MentionList $Mentions -KindName $Kind -ChannelName $Channel `
            -ExplicitMsgId $MsgId -ReplyToId $ReplyTo -TaskRefVal $TaskRef -ArtifactRefVal $ArtifactRef
    }
    "Read" {
        Invoke-Read -Layout $layout -TailN $Tail -MentionFilt $MentionFilter -SinceIso $Since
    }
    "Ack" {
        Invoke-Ack -Layout $layout -MessageId $MsgId -ReaderId $Identity -StatusName $AckStatus -NoteText $AckNote
    }
    "PresenceUpsert" {
        Invoke-PresenceUpsert -Layout $layout -Id $Identity -StateName $PresenceState -FreshSec $FreshSeconds
    }
    "PresenceProbe" {
        Invoke-PresenceProbe -Layout $layout -FreshSec $FreshSeconds
    }
    "WindowDetect" {
        Invoke-WindowDetect -Id $Identity
    }
    "EnsureIdentity" {
        Invoke-EnsureIdentity -Layout $layout -Id $Identity -BodyText $Body -MessageId $MsgId -TaskRefVal $TaskRef `
            -AllowColdStart $allowCold -DoInject $doInject -DoActivate $doActivate
    }
    "InjectPending" {
        Invoke-InjectPending -Layout $layout -Id $Identity -Reason "manual" -MessageId $MsgId -BodyText $Body -TaskRefVal $TaskRef
    }
    "RouteMention" {
        Invoke-RouteMention -Layout $layout -FromId $From -BodyText $Body -MentionList $Mentions -AllowColdStart $allowCold
    }
    "TaskCreate" {
        Invoke-TaskCreate -Layout $layout -TitleText $TaskTitle -OwnerId $Identity -BodyText $Body -Artifact $ArtifactRef
    }
    "TaskUpdate" {
        Invoke-TaskUpdate -Layout $layout -Id $TaskId -StatusName $TaskStatus -Artifact $ArtifactRef
    }
    "SelfSmoke" {
        Invoke-SelfSmoke -Layout $layout
    }
}

# Always stamp honesty on latest for non-smoke actions
if ($Action -ne "SelfSmoke") {
    Write-JsonFile $layout.latest_status ([ordered]@{
            schema_version           = "xinao.live_panel.latest.v1"
            updated_at               = Get-NowIso
            last_action              = $Action
            ok                       = [bool]$result.ok
            completion_claim_allowed = $false
            status                   = "scaffold_plus_wake_reuse_not_product"
            product_ready            = $false
            panel_root               = $layout.root
        })
}

$json = ConvertTo-JsonUtf8 $result
if (-not $Quiet) {
    Write-Output $json
}
return $result
