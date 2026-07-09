[CmdletBinding()]
param(
    [string]$Workspace = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace",
    [string]$GrokSessionsRoot = "",
    [string]$DeliveryId = "",
    [string]$MessageSha256 = "",
    [datetime]$StartedAt,
    [int]$WaitSec = 45,
    [switch]$PollUntilConfirmed
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

if (-not $GrokSessionsRoot) {
    $GrokSessionsRoot = Join-Path $env:USERPROFILE ".grok\sessions"
}

$RunningPhases = @(
    "waiting_for_model",
    "streaming_reasoning",
    "streaming_content",
    "streaming_assistant",
    "tool_execution",
    "permission_prompt"
)

function Get-GrokEncodedWorkspaceDirName {
    param([string]$Path)
    $normalized = $Path.Trim().TrimEnd('\')
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $normalized.ToCharArray()) {
        if ($ch -match '[A-Za-z0-9\-_.~]') {
            [void]$sb.Append($ch)
        }
        elseif ($ch -eq '\') {
            [void]$sb.Append('%5C')
        }
        elseif ($ch -eq ':') {
            [void]$sb.Append('%3A')
        }
        else {
            [void]$sb.Append([uri]::EscapeDataString([string]$ch))
        }
    }
    return $sb.ToString()
}

function Read-SharedTextLines {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return @() }
    $stream = $null
    $reader = $null
    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
        $lines = New-Object System.Collections.Generic.List[string]
        while (-not $reader.EndOfStream) {
            $lines.Add($reader.ReadLine())
        }
        return @($lines)
    }
    finally {
        if ($null -ne $reader) { $reader.Dispose() }
        elseif ($null -ne $stream) { $stream.Dispose() }
    }
}

function ConvertTo-EventTimestamp {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    try { return [datetimeoffset]::Parse($Text) } catch { return $null }
}

function Get-GrokWorkspaceSessionRoot {
    param([string]$WorkspacePath)
    $encoded = Get-GrokEncodedWorkspaceDirName -Path $WorkspacePath
    return Join-Path $GrokSessionsRoot $encoded
}

function Get-LatestGrokSessionArtifacts {
    param([string]$WorkspaceSessionRoot)
    if (-not (Test-Path -LiteralPath $WorkspaceSessionRoot -PathType Container)) {
        return [pscustomobject]@{
            session_id = ""
            session_dir = ""
            chat_history_path = ""
            events_path = ""
            prompt_history_path = ""
        }
    }
    $promptHistory = Join-Path $WorkspaceSessionRoot "prompt_history.jsonl"
    $sessionDirs = @(Get-ChildItem -LiteralPath $WorkspaceSessionRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "chat_history.jsonl") })
    if ($sessionDirs.Count -eq 0) {
        return [pscustomobject]@{
            session_id = ""
            session_dir = ""
            chat_history_path = ""
            events_path = ""
            prompt_history_path = $promptHistory
        }
    }
    $best = $sessionDirs | Sort-Object {
        $chat = Join-Path $_.FullName "chat_history.jsonl"
        if (Test-Path -LiteralPath $chat) { (Get-Item -LiteralPath $chat).LastWriteTimeUtc } else { [datetime]::MinValue }
    } -Descending | Select-Object -First 1
    return [pscustomobject]@{
        session_id = $best.Name
        session_dir = $best.FullName
        chat_history_path = Join-Path $best.FullName "chat_history.jsonl"
        events_path = Join-Path $best.FullName "events.jsonl"
        prompt_history_path = $promptHistory
    }
}

function Get-GrokRuntimeState {
    param([string]$EventsPath, [int]$RecentWindowSec = 20)
    if (-not (Test-Path -LiteralPath $EventsPath -PathType Leaf)) {
        return [pscustomobject]@{
            grok_running = $false
            latest_phase = ""
            latest_event_type = ""
            latest_event_ts = ""
            submit_recommendation = "enter_normal"
        }
    }
    $lines = @(Read-SharedTextLines -Path $EventsPath)
    $tail = if ($lines.Count -gt 120) { $lines[($lines.Count - 120)..($lines.Count - 1)] } else { $lines }
    $latestPhase = ""
    $latestType = ""
    $latestTs = $null
    foreach ($line in $tail) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $obj = $line | ConvertFrom-Json
            if ($obj.type -eq "phase_changed" -and $obj.phase) {
                $latestPhase = [string]$obj.phase
                $latestType = "phase_changed"
                $latestTs = ConvertTo-EventTimestamp ([string]$obj.ts)
            }
            elseif ($obj.type) {
                $latestType = [string]$obj.type
                $latestTs = ConvertTo-EventTimestamp ([string]$obj.ts)
            }
        }
        catch {}
    }
    $running = $false
    if ($latestTs) {
        $ageSec = ([datetimeoffset]::UtcNow - $latestTs).TotalSeconds
        if ($ageSec -le $RecentWindowSec) {
            if ($latestPhase -in $RunningPhases -or $latestType -in @("tool_started", "loop_started", "first_token", "turn_started")) {
                $running = $true
            }
        }
    }
    $submit = if ($running) { "ctrl_i_interrupt" } else { "enter_normal" }
    return [pscustomobject]@{
        grok_running = $running
        latest_phase = $latestPhase
        latest_event_type = $latestType
        latest_event_ts = if ($latestTs) { $latestTs.ToString("o") } else { "" }
        submit_recommendation = $submit
    }
}

function Test-PromptHistoryContainsDelivery {
    param(
        [string]$PromptHistoryPath,
        [string]$DeliveryId,
        [string]$MessageSha256,
        [datetime]$StartedAt
    )
    if (-not (Test-Path -LiteralPath $PromptHistoryPath -PathType Leaf)) { return $false }
    $lines = @(Read-SharedTextLines -Path $PromptHistoryPath)
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        $line = $lines[$i]
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $obj = $line | ConvertFrom-Json
            $ts = ConvertTo-EventTimestamp ([string]$obj.timestamp)
            if (-not $ts) { continue }
            if ($ts.LocalDateTime -lt $StartedAt) { continue }
            $prompt = [string]$obj.prompt
            if ($DeliveryId -and $prompt.Contains($DeliveryId)) { return $true }
            if ($MessageSha256 -and $prompt.Contains($MessageSha256.Substring(0, [Math]::Min(16, $MessageSha256.Length)))) { return $true }
        }
        catch {}
    }
    return $false
}

function Get-ChatHistoryDeliveryEvidence {
    param(
        [string]$ChatHistoryPath,
        [string]$DeliveryId,
        [datetime]$StartedAt
    )
    $result = [ordered]@{
        delivery_id_seen = $false
        user_message_seen = $false
        assistant_seen = $false
        turn_started_after_delivery = $false
        matched_session_path = $ChatHistoryPath
        last_agent_excerpt = ""
    }
    if (-not $DeliveryId -or -not (Test-Path -LiteralPath $ChatHistoryPath -PathType Leaf)) {
        return [pscustomobject]$result
    }
    $lines = @(Read-SharedTextLines -Path $ChatHistoryPath)
    $afterDelivery = $false
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.Contains($DeliveryId)) {
            $result.delivery_id_seen = $true
            $result.user_message_seen = $true
            $afterDelivery = $true
            continue
        }
        if (-not $afterDelivery) { continue }
        try {
            $obj = $line | ConvertFrom-Json
            if ($obj.type -eq "assistant") {
                $result.assistant_seen = $true
                if ($obj.content) {
                    if ($obj.content -is [string]) {
                        $result.last_agent_excerpt = [string]$obj.content
                    }
                    elseif ($obj.content -is [array]) {
                        $parts = @($obj.content | ForEach-Object {
                            if ($_.text) { [string]$_.text } else { "" }
                        })
                        $result.last_agent_excerpt = ($parts -join "`n")
                    }
                }
                break
            }
        }
        catch {}
    }
    return [pscustomobject]$result
}

function Get-EventsDeliveryEvidence {
    param(
        [string]$EventsPath,
        [datetime]$StartedAt
    )
    $result = [ordered]@{
        turn_started_after_delivery = $false
        latest_turn_started_at = ""
    }
    if (-not (Test-Path -LiteralPath $EventsPath -PathType Leaf)) {
        return [pscustomobject]$result
    }
    $lines = @(Read-SharedTextLines -Path $EventsPath)
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $obj = $line | ConvertFrom-Json
            if ($obj.type -ne "turn_started") { continue }
            $ts = ConvertTo-EventTimestamp ([string]$obj.ts)
            if (-not $ts) { continue }
            if ($ts.LocalDateTime -ge $StartedAt) {
                $result.turn_started_after_delivery = $true
                $result.latest_turn_started_at = $ts.ToString("o")
            }
        }
        catch {}
    }
    return [pscustomobject]$result
}

function Get-GrokDeliveryReadbackEvidence {
    param(
        [string]$WorkspacePath,
        [string]$DeliveryId,
        [string]$MessageSha256,
        [datetime]$StartedAt
    )
    $workspaceRoot = Get-GrokWorkspaceSessionRoot -WorkspacePath $WorkspacePath
    $artifacts = Get-LatestGrokSessionArtifacts -WorkspaceSessionRoot $workspaceRoot
    $runtime = Get-GrokRuntimeState -EventsPath $artifacts.events_path
    $promptSeen = Test-PromptHistoryContainsDelivery -PromptHistoryPath $artifacts.prompt_history_path -DeliveryId $DeliveryId -MessageSha256 $MessageSha256 -StartedAt $StartedAt
    $chat = Get-ChatHistoryDeliveryEvidence -ChatHistoryPath $artifacts.chat_history_path -DeliveryId $DeliveryId -StartedAt $StartedAt
    $events = Get-EventsDeliveryEvidence -EventsPath $artifacts.events_path -StartedAt $StartedAt

    $sessionModified = $false
    foreach ($path in @($artifacts.chat_history_path, $artifacts.events_path, $artifacts.prompt_history_path)) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            if ((Get-Item -LiteralPath $path).LastWriteTime -ge $StartedAt) {
                $sessionModified = $true
                break
            }
        }
    }

    $deliveryConfirmed = [bool](
        $promptSeen -or
        $chat.delivery_id_seen -or
        ($chat.user_message_seen -and ($events.turn_started_after_delivery -or $chat.assistant_seen))
    )
    $visibleSubmitted = [bool]($promptSeen -or $chat.delivery_id_seen -or $events.turn_started_after_delivery)

    return [pscustomobject]@{
        schema_version = "xinao.grok_session_delivery_readback.v1"
        workspace = $WorkspacePath
        workspace_session_root = $workspaceRoot
        session_id = $artifacts.session_id
        session_dir = $artifacts.session_dir
        chat_history_path = $artifacts.chat_history_path
        events_path = $artifacts.events_path
        prompt_history_path = $artifacts.prompt_history_path
        delivery_id = $DeliveryId
        message_sha256 = $MessageSha256
        started_at = $StartedAt.ToString("o")
        runtime_state = $runtime
        prompt_history_seen = $promptSeen
        delivery_id_seen = $chat.delivery_id_seen
        user_message_seen = $chat.user_message_seen
        assistant_seen = $chat.assistant_seen
        turn_started_after_delivery = $events.turn_started_after_delivery
        session_modified_after_send = $sessionModified
        visible_submission_confirmed = $deliveryConfirmed
        visible_submitted = $visibleSubmitted
        submit_keys_sent_only = (-not $deliveryConfirmed)
        named_blocker = if ($deliveryConfirmed) { "" } else { "GROK_VISIBLE_TYPEAHEAD_NOT_SUBMITTED" }
        last_agent_excerpt = $chat.last_agent_excerpt
        generated_at = (Get-Date).ToString("o")
    }
}

if (-not $StartedAt) {
    $StartedAt = Get-Date
}

$readOnce = {
    Get-GrokDeliveryReadbackEvidence -WorkspacePath $Workspace -DeliveryId $DeliveryId -MessageSha256 $MessageSha256 -StartedAt $StartedAt
}

if ($PollUntilConfirmed) {
    $deadline = (Get-Date).AddSeconds([Math]::Max(5, $WaitSec))
    $evidence = & $readOnce
    do {
        if ($evidence.visible_submission_confirmed) { break }
        Start-Sleep -Milliseconds 700
        $evidence = & $readOnce
    } while ((Get-Date) -lt $deadline)
    $evidence | ConvertTo-Json -Depth 10
    if ($evidence.visible_submission_confirmed) { exit 0 }
    exit 3
}

$single = & $readOnce
$single | ConvertTo-Json -Depth 10