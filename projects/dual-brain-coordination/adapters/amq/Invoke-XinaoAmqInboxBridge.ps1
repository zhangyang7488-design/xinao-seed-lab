#Requires -Version 5.1
# Dual-brain AMQ thin bridge: pure doorbell (no inject) + turn drain.
# Fail-open always (exit 0).
[CmdletBinding()]
param(
    [ValidateSet('Drain', 'DoorbellOnce', 'HookSessionStart', 'HookPrompt', 'Status')]
    [string]$Action = 'Status',

    [ValidateSet('grok', 'codex', 'grok_4_5', 'admin')]
    [string]$Role = 'grok_4_5',

    [string]$AmRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq',
    [string]$AmqBin = 'D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe',
    [string]$KernelDb = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3',
    [string]$CoordCurrent = 'D:\XINAO_RESEARCH_RUNTIME\tools\xinao-coordination\current.json',
    [string]$HiddenStdioCurrent = 'D:\XINAO_RESEARCH_RUNTIME\tools\hidden-stdio\current.json',
    [string]$StateRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\inbox_bridge',
    [ValidateRange(1, 100)]
    [int]$Limit = 20,
    [switch]$EmitHookContext,
    [switch]$Quiet
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

function Write-Info([string]$Msg) {
    if (-not $Quiet) { Write-Host $Msg }
}

function Resolve-Me([string]$RoleName) {
    switch ($RoleName) {
        'grok_4_5' { return 'grok' }
        'grok' { return 'grok' }
        'codex' { return 'codex' }
        'admin' { return 'admin' }
        default { return 'grok' }
    }
}

function Resolve-KernelRole([string]$RoleName) {
    switch ($RoleName) {
        'grok' { return 'grok_4_5' }
        default { return $RoleName }
    }
}

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Get-NewList {
    param([string]$Me)
    if (-not (Test-Path -LiteralPath $AmqBin)) { return @() }
    $raw = & $AmqBin list --root $AmRoot --me $Me --new --limit $Limit --json 2>$null
    if (-not $raw) { return @() }
    try {
        $j = $raw | Out-String | ConvertFrom-Json
        if ($null -eq $j) { return @() }
        if ($j -is [System.Array]) { return @($j) }
        return @($j)
    }
    catch {
        return @()
    }
}

function Get-AmqBody($Item) {
    $path = [string]$Item.path
    if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { return '' }
    try {
        $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
        if ($text -match '(?s)^---json\r?\n.*?\r?\n---\r?\n(.*)$') {
            return [string]$Matches[1]
        }
    }
    catch { }
    return ''
}

function Resolve-CurrentTool([string]$CurrentPath, [string]$RelativePath, [string]$ExplicitProperty) {
    if (-not (Test-Path -LiteralPath $CurrentPath -PathType Leaf)) {
        throw "current pointer missing: $CurrentPath"
    }
    $current = Get-Content -LiteralPath $CurrentPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $explicit = [string]$current.$ExplicitProperty
    $path = if ($explicit) { $explicit } else { Join-Path ([string]$current.generation_path) $RelativePath }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "current tool missing: $path"
    }
    return $path
}

function Invoke-KernelIngest([string]$KernelRole) {
    $coordCli = Resolve-CurrentTool -CurrentPath $CoordCurrent -RelativePath 'venv\Scripts\xinao-coord.exe' -ExplicitProperty 'cli_path'
    $hidden = Resolve-CurrentTool -CurrentPath $HiddenStdioCurrent -RelativePath 'xinao-hidden-stdio.exe' -ExplicitProperty 'launcher_path'
    $arguments = @(
        $coordCli,
        '--db', $KernelDb,
        'amq-ingest',
        '--recipient-role', $KernelRole,
        '--limit', [string]$Limit,
        '--amq-root', $AmRoot,
        '--amq-bin', $AmqBin
    )
    $raw = & $hidden @arguments 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "coordination amq-ingest failed exit=$LASTEXITCODE output=$($raw.Trim())"
    }
    if (-not $raw.Trim()) { throw 'coordination amq-ingest returned empty output' }
    return $raw | ConvertFrom-Json
}

function Invoke-Drain {
    param([string]$Me)
    $out = [ordered]@{
        ok                         = $false
        me                         = $Me
        role                       = $Role
        am_root                    = $AmRoot
        generated_at               = (Get-Date).ToString('o')
        drained_count              = 0
        ingested_count             = 0
        kernel_persisted_count     = 0
        errors_count               = 0
        quarantined_count          = 0
        receipt_stage              = ''
        items                      = @()
        summary_cn                 = ''
        honesty_cn                 = 'ingest=AMQ consume + kernel persisted; not model-read or model-finished-reply'
        completion_claim_allowed   = $false
    }
    if (-not (Test-Path -LiteralPath $AmqBin)) {
        $out.summary_cn = 'amq.exe missing'
        return [pscustomobject]$out
    }
    if (-not (Test-Path -LiteralPath $AmRoot)) {
        $out.summary_cn = 'AM_ROOT missing'
        return [pscustomobject]$out
    }

    $pending = @(Get-NewList -Me $Me)
    $pendingById = @{}
    $pendingBodyById = @{}
    foreach ($candidate in $pending) {
        $id = [string]$candidate.id
        if ($id) {
            $pendingById[$id] = $candidate
            # Capture before canonical ingest atomically moves new -> cur.
            $pendingBodyById[$id] = Get-AmqBody $candidate
        }
    }
    try {
        $j = Invoke-KernelIngest -KernelRole (Resolve-KernelRole $Role)
        $ingested = @($j.ingested)
        $errors = @($j.errors)
        $quarantined = @($j.quarantined)
        $out.drained_count = [int]$j.drained_count
        $out.ingested_count = $ingested.Count
        $out.kernel_persisted_count = @(
            $ingested | Where-Object { $_.kernel_written -eq $true -or $_.replayed -eq $true }
        ).Count
        $out.errors_count = $errors.Count
        $out.quarantined_count = $quarantined.Count
        $out.receipt_stage = [string]$j.receipt_stage
        $summaries = New-Object System.Collections.Generic.List[string]
        $itemObjs = @()
        foreach ($it in $ingested) {
            $id = [string]$it.amq_message_id
            $rawItem = if ($pendingById.ContainsKey($id)) { $pendingById[$id] } else { $null }
            $from = if ($null -ne $rawItem) { [string]$rawItem.from } else { '' }
            $subj = if ($null -ne $rawItem) { [string]$rawItem.subject } else { '' }
            $kind = if ($null -ne $rawItem) { [string]$rawItem.kind } else { '' }
            $body = if ($pendingBodyById.ContainsKey($id)) { [string]$pendingBodyById[$id] } else { '' }
            if ($body.Length -gt 240) { $body = $body.Substring(0, 240) + '...' }
            $body = [regex]::Replace($body, '\s+', ' ').Trim()
            $line = "from=$from subject=$subj body=$body"
            [void]$summaries.Add($line)
            $itemObjs += [ordered]@{
                id      = $id
                from    = $from
                subject = $subj
                kind    = $kind
                body    = $body
                thread_id = [string]$it.thread_id
                kernel_written = [bool]$it.kernel_written
                replayed = [bool]$it.replayed
            }
        }
        $out.items = $itemObjs
        if ($out.drained_count -le 0) {
            $out.summary_cn = 'no new mail'
            $out.ok = [bool]$j.ok
        }
        else {
            $joined = ($summaries -join ' | ')
            $out.summary_cn = "new_mail=$($out.drained_count) persisted=$($out.kernel_persisted_count) $joined"
            if ($out.summary_cn.Length -gt 1200) {
                $out.summary_cn = $out.summary_cn.Substring(0, 1200) + '...'
            }
            $out.ok = [bool]$j.ok
        }
    }
    catch {
        $out.summary_cn = "kernel ingest failed: $($_.Exception.Message)"
    }
    return [pscustomobject]$out
}

function Save-DrainResult {
    param($Result, [string]$Me)
    Ensure-Dir $StateRoot
    $path = Join-Path $StateRoot ("{0}_latest.json" -f $Me)
    $json = $Result | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($path, $json, [System.Text.UTF8Encoding]::new($false))
    $md = Join-Path $StateRoot ("{0}_latest.md" -f $Me)
    $mdBody = @(
        "# AMQ turn inbox $Me",
        "",
        $Result.summary_cn,
        "",
        "- at: $($Result.generated_at)",
        "- drained_count: $($Result.drained_count)"
    ) -join [Environment]::NewLine
    [System.IO.File]::WriteAllText($md, $mdBody, [System.Text.UTF8Encoding]::new($false))
    return $path
}

function Show-DoorbellToast {
    param([string]$Title, [string]$Body)
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        Add-Type -AssemblyName System.Drawing -ErrorAction Stop
        $ni = New-Object System.Windows.Forms.NotifyIcon
        $ni.Icon = [System.Drawing.SystemIcons]::Information
        $ni.Visible = $true
        $ni.BalloonTipTitle = $Title
        $ni.BalloonTipText = $Body
        $ni.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
        $ni.ShowBalloonTip(6000)
        Start-Sleep -Milliseconds 800
        $ni.Visible = $false
        $ni.Dispose()
        return $true
    }
    catch {
        return $false
    }
}

function Invoke-DoorbellOnce {
    param([string]$Me)
    Ensure-Dir $StateRoot
    $wmPath = Join-Path $StateRoot ("{0}_doorbell_watermark.json" -f $Me)
    $newItems = @(Get-NewList -Me $Me)
    $ids = @($newItems | ForEach-Object { [string]$_.id } | Where-Object { $_ })
    $prev = @()
    if (Test-Path -LiteralPath $wmPath) {
        try {
            $wj = Get-Content -LiteralPath $wmPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $prev = @($wj.seen_ids)
        }
        catch { $prev = @() }
    }
    $fresh = @($ids | Where-Object { $prev -notcontains $_ })
    $result = [ordered]@{
        ok          = $true
        me          = $Me
        new_count   = $ids.Count
        fresh_count = $fresh.Count
        toasted     = $false
        honesty_cn  = 'doorbell=notify only; not model read; no inject'
    }
    if ($fresh.Count -gt 0) {
        $sample = $newItems | Where-Object { $fresh -contains [string]$_.id } | Select-Object -First 3
        $bits = @($sample | ForEach-Object { "from=$($_.from) $($_.subject)" })
        $title = "dual-brain mail $Me"
        $body = "$($fresh.Count) new: " + ($bits -join '; ')
        if ($body.Length -gt 180) { $body = $body.Substring(0, 180) + '...' }
        $result.toasted = [bool](Show-DoorbellToast -Title $title -Body $body)
        $result.title = $title
        $result.body = $body
    }
    $wm = [ordered]@{
        me         = $Me
        updated_at = (Get-Date).ToString('o')
        seen_ids   = $ids
    }
    [System.IO.File]::WriteAllText(
        $wmPath,
        ($wm | ConvertTo-Json -Depth 4),
        [System.Text.UTF8Encoding]::new($false)
    )
    return [pscustomobject]$result
}

function Emit-HookContext {
    param([string]$EventName, [string]$ContextText)
    $payload = [ordered]@{
        continue = $true
        hookSpecificOutput = [ordered]@{
            hookEventName     = $EventName
            additionalContext = $ContextText
        }
    }
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 6 -Compress))
}

$me = Resolve-Me $Role
Ensure-Dir $StateRoot

try {
    switch ($Action) {
        'Status' {
            $list = @(Get-NewList -Me $me)
            [pscustomobject]@{
                ok        = $true
                me        = $me
                role      = $Role
                new_count = $list.Count
                latest    = (Join-Path $StateRoot ("{0}_latest.json" -f $me))
                am_root   = $AmRoot
            } | ConvertTo-Json -Depth 4
        }
        'Drain' {
            $r = Invoke-Drain -Me $me
            $path = Save-DrainResult -Result $r -Me $me
            Write-Info ("DRAIN me={0} count={1} path={2}" -f $me, $r.drained_count, $path)
            $r | ConvertTo-Json -Depth 8
        }
        'DoorbellOnce' {
            $r = Invoke-DoorbellOnce -Me $me
            Write-Info ("DOORBELL me={0} fresh={1} toasted={2}" -f $me, $r.fresh_count, $r.toasted)
            $r | ConvertTo-Json -Depth 6
        }
        'HookSessionStart' {
            $bell = Invoke-DoorbellOnce -Me $me
            $r = Invoke-Drain -Me $me
            $null = Save-DrainResult -Result $r -Me $me
            $ctx = "dual-brain inbox me=$me drained=$($r.drained_count) doorbell_fresh=$($bell.fresh_count) | $($r.summary_cn)"
            if ($EmitHookContext) {
                Emit-HookContext -EventName 'SessionStart' -ContextText $ctx
            }
            elseif (-not $Quiet) {
                Write-Output $ctx
            }
        }
        'HookPrompt' {
            $null = Invoke-DoorbellOnce -Me $me
            $r = Invoke-Drain -Me $me
            $null = Save-DrainResult -Result $r -Me $me
            $ctx = ''
            if ($r.drained_count -gt 0) {
                $ctx = "dual-brain turn mail: $($r.summary_cn)"
            }
            if ($EmitHookContext) {
                Emit-HookContext -EventName 'UserPromptSubmit' -ContextText $ctx
            }
            elseif ($ctx -and -not $Quiet) {
                Write-Output $ctx
            }
        }
    }
    exit 0
}
catch {
    Write-Info ("FAIL-OPEN: $($_.Exception.Message)")
    if ($EmitHookContext) {
        Emit-HookContext -EventName 'SessionStart' -ContextText ''
    }
    exit 0
}
