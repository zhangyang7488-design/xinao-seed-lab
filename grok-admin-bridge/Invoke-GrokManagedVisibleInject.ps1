[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Message,
    [string]$RuntimeRoot = "D:\XINAO_CLEAN_RUNTIME",
    [string]$BridgeRoot = "",
    [string]$Workspace = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace",
    [string]$WindowTitle = "管理员: Grok",
    [string]$InjectId = "",
    [string]$DeliveryId = "",
    [ValidateSet("auto", "enter_normal", "ctrl_i_interrupt", "ctrl_enter")]
    [string]$SubmitMode = "auto",
    [int]$WaitSec = 45,
    [switch]$NoWake,
    [switch]$Typeahead,
    [switch]$AllowShortcutFallback,
    [switch]$ClearInputBeforePaste,
    [switch]$SelectionProbeOnly,
    [switch]$SkipSubmit,
    [switch]$PollReadback
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

if (-not $BridgeRoot) {
    $BridgeRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
}

$stateDir = Join-Path $BridgeRoot "state\grok_managed_visible_inject"
$promptDir = Join-Path $stateDir "prompts"
New-Item -ItemType Directory -Force -Path $stateDir, $promptDir | Out-Null

$shortcutPath = "C:\Users\xx363\Desktop\Grok Admin Isolated.lnk"
$grokLeaderSocketMarker = "grok_admin_isolated_window"

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class XinaoGrokManagedVisibleInjectNative {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
}
"@

function Get-GrokAdminWindowState {
    $statePath = Join-Path $RuntimeRoot "state\grok_admin_isolated_window\latest.json"
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return [pscustomobject]@{
            state_path = $statePath
            grok_pid = 0
            workspace = $Workspace
            shortcut = $shortcutPath
            grok_pid_alive = $false
        }
    }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $grokPid = if ($state.grok_pid) { [int]$state.grok_pid } else { 0 }
        $terminalPid = if ($state.terminal_pid) { [int]$state.terminal_pid } else { 0 }
        $shellPid = if ($state.shell_pid) { [int]$state.shell_pid } else { 0 }
        return [pscustomobject]@{
            state_path = $statePath
            grok_pid = $grokPid
            terminal_pid = $terminalPid
            shell_pid = $shellPid
            workspace = if ($state.workspace) { [string]$state.workspace } else { $Workspace }
            shortcut = if ($state.shortcut) { [string]$state.shortcut } else { $shortcutPath }
            grok_pid_alive = [bool]($grokPid -ne 0 -and (Get-Process -Id $grokPid -ErrorAction SilentlyContinue))
            terminal_pid_alive = [bool]($terminalPid -ne 0 -and (Get-Process -Id $terminalPid -ErrorAction SilentlyContinue))
        }
    }
    catch {
        return [pscustomobject]@{
            state_path = $statePath
            grok_pid = 0
            workspace = $Workspace
            shortcut = $shortcutPath
            grok_pid_alive = $false
        }
    }
}

function Get-GrokIsolatedProcessRows {
    $rows = @()
    try {
        $rows = @(Get-CimInstance Win32_Process -Filter "Name='grok.exe'" -ErrorAction Stop |
            Where-Object {
                $cmd = [string]$_.CommandLine
                $cmd -match [regex]::Escape($Workspace) -and
                $cmd -match $grokLeaderSocketMarker
            } |
            ForEach-Object {
                [pscustomobject]@{
                    ProcessId = [int]$_.ProcessId
                    ParentProcessId = [int]$_.ParentProcessId
                    CommandLine = [string]$_.CommandLine
                }
            })
    }
    catch {}
    return @($rows)
}

function Get-TerminalPidForProcess {
    param([int]$ProcessId)
    $procId = $ProcessId
    for ($i = 0; $i -lt 10; $i++) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
        if (-not $p) { return 0 }
        if ([string]$p.Name -ieq "WindowsTerminal.exe") {
            return [int]$p.ProcessId
        }
        $procId = [int]$p.ParentProcessId
        if ($procId -le 0) { break }
    }
    return 0
}

function Get-GrokLauncherTerminalPids {
    $pids = New-Object System.Collections.Generic.HashSet[int]
    $grokState = Get-GrokAdminWindowState
    if ($grokState.terminal_pid -ne 0) { [void]$pids.Add([int]$grokState.terminal_pid) }
    foreach ($row in (Get-GrokIsolatedProcessRows)) {
        $terminalPid = Get-TerminalPidForProcess -ProcessId $row.ProcessId
        if ($terminalPid -ne 0) { [void]$pids.Add($terminalPid) }
        $parentTerminalPid = Get-TerminalPidForProcess -ProcessId $row.ParentProcessId
        if ($parentTerminalPid -ne 0) { [void]$pids.Add($parentTerminalPid) }
    }
    try {
        @(Get-CimInstance Win32_Process -Filter "Name='WindowsTerminal.exe'" |
            Where-Object {
                $_.CommandLine -match "Start-Grok-Admin-Isolated|Grok Admin Isolated|Grok_Admin_Isolated"
            } |
            ForEach-Object { [void]$pids.Add([int]$_.ProcessId) })
    }
    catch {}
    try {
        @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
            Where-Object { $_.CommandLine -match "Start-Grok-Admin-Isolated" } |
            ForEach-Object {
                $terminalPid = Get-TerminalPidForProcess -ProcessId $_.ProcessId
                if ($terminalPid -ne 0) { [void]$pids.Add($terminalPid) }
            })
    }
    catch {}
    return @($pids)
}

function Get-CodexAManagedTerminalPids {
    $pids = New-Object System.Collections.Generic.HashSet[int]
    $managedStatePath = Join-Path $RuntimeRoot "state\codexa_managed_window\latest.json"
    if (Test-Path -LiteralPath $managedStatePath -PathType Leaf) {
        try {
            $managedState = Get-Content -LiteralPath $managedStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($managedState.terminal_pid) { [void]$pids.Add([int]$managedState.terminal_pid) }
        }
        catch {}
    }
    try {
        @(Get-CimInstance Win32_Process -Filter "Name='WindowsTerminal.exe'" |
            Where-Object {
                $_.CommandLine -match "Launch-Codex-A-Managed-Visible|Open-Codex-A-Managed"
            } |
            ForEach-Object { [void]$pids.Add([int]$_.ProcessId) })
    }
    catch {}
    return @($pids)
}

function Normalize-TabName {
    param([string]$TabName)
    if ([string]::IsNullOrWhiteSpace($TabName)) { return "" }
    $text = $TabName.Trim()
    $text = ($text -replace '^[\u2800-\u28FF?\uFFFD]+\s*', "").Trim()
    return $text
}

function Test-IsCodexATabName {
    param([string]$TabName)
    if ([string]::IsNullOrWhiteSpace($TabName)) { return $false }
    $trimmed = Normalize-TabName $TabName
    if ($trimmed -match '(?i)\bgrok\b') { return $false }
    return (
        $trimmed -eq "A" -or
        $trimmed -match '(?i)^codexa\b' -or
        $trimmed -match '(?i)OPEN CODEX' -or
        $trimmed -match '(?i)codex\s*-\s*a\b' -or
        $trimmed -match '(?i)codexa\s+managed' -or
        $TabName -match '(?i)(^|\s)A(\s|$)' -and $TabName -notmatch '(?i)grok'
    )
}

function Test-IsGrokAuditNoiseTabName {
    param([string]$TabName)
    if ([string]::IsNullOrWhiteSpace($TabName)) { return $false }
    return (
        $TabName -match '(?i)segment.?audit' -or
        $TabName -match '(?i)codex\s*to\s*grok' -or
        $TabName -match '(?i)evidence\s*rev' -or
        $TabName -match '(?i)audit\s*summon'
    )
}

function Test-IsGrokLauncherShellTabName {
    param([string]$TabName)
    if ([string]::IsNullOrWhiteSpace($TabName)) { return $false }
    return (
        $TabName -match '(?i)Start-Grok-Admin-Isolated' -or
        $TabName -match '(?i)Grok Admin Isolated Window' -or
        (
            $TabName -match '(?i)Running:.*powershell' -and
            $TabName -match '(?i)\bgrok\b' -and
            $TabName -notmatch '(?i)segment.?audit|codex\s*to\s*grok|evidence\s*rev|audit\s*summon'
        )
    )
}

function Test-IsGrokAdminTabName {
    param([string]$TabName)
    if ([string]::IsNullOrWhiteSpace($TabName)) { return $false }
    if (Test-IsCodexATabName -TabName $TabName) { return $false }
    if (Test-IsGrokAuditNoiseTabName -TabName $TabName) { return $false }
    return (
        $TabName -eq $WindowTitle -or
        $TabName -match '(?i)管理员:\s*Grok' -or
        $TabName -match '(?i)XINAO Grok Admin Isolated' -or
        $TabName -match '(?i)Grok Admin Isolated' -or
        (Test-IsGrokLauncherShellTabName -TabName $TabName)
    )
}

function Get-LatestGrokIsolatedProcessRow {
    $rows = @(Get-GrokIsolatedProcessRows)
    if ($rows.Count -eq 0) { return $null }
    $best = $null
    foreach ($row in $rows) {
        try {
            $proc = Get-Process -Id $row.ProcessId -ErrorAction Stop
            $row | Add-Member -NotePropertyName StartTime -NotePropertyValue $proc.StartTime -Force
            if (-not $best -or $proc.StartTime -gt $best.StartTime) { $best = $row }
        }
        catch {}
    }
    if ($best) { return $best }
    return $rows[0]
}

function Get-GrokChildForShell {
    param([int]$ShellProcessId)
    try {
        return @(Get-CimInstance Win32_Process -Filter "Name='grok.exe'" -ErrorAction Stop |
            Where-Object {
                [int]$_.ParentProcessId -eq $ShellProcessId -and
                [string]$_.CommandLine -match [regex]::Escape($Workspace) -and
                [string]$_.CommandLine -match $grokLeaderSocketMarker
            })
    }
    catch { return @() }
}

function Discover-GrokAdminTabsWithShellBinding {
    param(
        [int[]]$TerminalPids,
        $LatestGrokProcess,
        $CodexATerminalPids
    )
    if ($TerminalPids.Count -eq 0 -or -not $LatestGrokProcess) { return @() }
    $shellPid = [int]$LatestGrokProcess.ParentProcessId
    $shellCmd = ""
    try {
        $shellProc = Get-CimInstance Win32_Process -Filter "ProcessId=$shellPid" -ErrorAction Stop
        $shellCmd = [string]$shellProc.CommandLine
    }
    catch { return @() }
    if ($shellCmd -notmatch 'Start-Grok-Admin-Isolated') { return @() }

    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $windowCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ClassNameProperty,
        "CASCADIA_HOSTING_WINDOW_CLASS"
    )
    $windows = @($root.FindAll([System.Windows.Automation.TreeScope]::Children, $windowCondition))
    $foregroundHandle = [XinaoGrokManagedVisibleInjectNative]::GetForegroundWindow()
    $foregroundPidRaw = [uint32]0
    [void][XinaoGrokManagedVisibleInjectNative]::GetWindowThreadProcessId($foregroundHandle, [ref]$foregroundPidRaw)
    $discovered = @()

    foreach ($window in $windows) {
        $windowProcessId = [int]$window.Current.ProcessId
        if ($TerminalPids -notcontains $windowProcessId) { continue }
        $tabCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::TabItem
        )
        $tabs = @($window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCondition))
        foreach ($tab in $tabs) {
            if (Test-IsCodexATabName -TabName ([string]$tab.Current.Name)) { continue }
            try {
                $selectionPattern = $tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
                $selectionPattern.Select()
            }
            catch {}
            Start-Sleep -Milliseconds 320
            $grokChildren = @(Get-GrokChildForShell -ShellProcessId $shellPid)
            if ($grokChildren.Count -eq 0) { continue }
            $tabName = [string]$tab.Current.Name
            $windowName = [string]$window.Current.Name
            if (Test-IsGrokAuditNoiseTabName -TabName $tabName) { continue }
            $discovered += [pscustomobject]@{
                Window = $window
                Tab = $tab
                ProcessId = $windowProcessId
                NativeWindowHandle = $window.Current.NativeWindowHandle
                WindowName = $windowName
                TabName = $tabName
                MatchReason = "shell_process_binding"
                IsExactTitle = [bool]($tabName -match '(?i)管理员:\s*Grok')
                IsGrokAdminTab = $true
                GrokLauncherTerminal = $true
                CodexATerminal = [bool]($CodexATerminalPids -contains $windowProcessId)
                GrokProcessBound = $true
                IsForeground = (($window.Current.NativeWindowHandle -eq $foregroundHandle.ToInt32()) -or ($windowProcessId -eq [int]$foregroundPidRaw))
                ProcessStartTime = ""
                DiscoveredBy = "shell_process_binding"
                BoundShellPid = $shellPid
                BoundGrokPid = [int]$grokChildren[0].ProcessId
            }
            break
        }
        if ($discovered.Count -gt 0) { break }
    }
    return @($discovered)
}

function Discover-GrokAdminTabsWithTerminalScan {
    param(
        [int[]]$TerminalPids,
        $CodexATerminalPids
    )
    if ($TerminalPids.Count -eq 0) { return @() }
    $discovered = @()
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $windowCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ClassNameProperty,
        "CASCADIA_HOSTING_WINDOW_CLASS"
    )
    $windows = @($root.FindAll([System.Windows.Automation.TreeScope]::Children, $windowCondition))
    $foregroundHandle = [XinaoGrokManagedVisibleInjectNative]::GetForegroundWindow()
    $foregroundPidRaw = [uint32]0
    [void][XinaoGrokManagedVisibleInjectNative]::GetWindowThreadProcessId($foregroundHandle, [ref]$foregroundPidRaw)

    foreach ($window in $windows) {
        $windowProcessId = [int]$window.Current.ProcessId
        if ($TerminalPids -notcontains $windowProcessId) { continue }
        $tabCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::TabItem
        )
        $tabs = @($window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCondition))
        foreach ($tab in $tabs) {
            try {
                $selectionPattern = $tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
                $selectionPattern.Select()
            }
            catch {}
            Start-Sleep -Milliseconds 280
            $tabName = [string]$tab.Current.Name
            $windowName = [string]$window.Current.Name
            $adminTitleSeen = (
                $tabName -match '(?i)管理员:\s*Grok' -or
                $windowName -match '(?i)管理员:\s*Grok' -or
                $tabName -eq $WindowTitle -or
                $windowName -eq $WindowTitle
            )
            if (-not $adminTitleSeen) {
                if (Test-IsCodexATabName -TabName $tabName) { continue }
                if (Test-IsGrokAuditNoiseTabName -TabName $tabName) { continue }
                if (-not (Test-IsGrokAdminTabName -TabName $tabName)) { continue }
            }

            $discovered += [pscustomobject]@{
                Window = $window
                Tab = $tab
                ProcessId = $windowProcessId
                NativeWindowHandle = $window.Current.NativeWindowHandle
                WindowName = $windowName
                TabName = $tabName
                MatchReason = "terminal_scan_grok_admin_tab"
                IsExactTitle = [bool]($tabName -match '(?i)管理员:\s*Grok' -or $tabName -eq $WindowTitle)
                IsGrokAdminTab = $true
                GrokLauncherTerminal = $true
                CodexATerminal = [bool]($CodexATerminalPids -contains $windowProcessId)
                GrokProcessBound = $true
                IsForeground = (($window.Current.NativeWindowHandle -eq $foregroundHandle.ToInt32()) -or ($windowProcessId -eq [int]$foregroundPidRaw))
                ProcessStartTime = ""
                DiscoveredBy = "terminal_tab_scan"
            }
        }
    }
    return @($discovered)
}

function Get-GrokWindowCandidates {
    $grokState = Get-GrokAdminWindowState
    $grokLauncherTerminalPids = @(Get-GrokLauncherTerminalPids)
    $codexATerminalPids = @(Get-CodexAManagedTerminalPids)
    $grokProcessRows = @(Get-GrokIsolatedProcessRows)
    $latestGrokProcess = Get-LatestGrokIsolatedProcessRow

    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $windowCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ClassNameProperty,
        "CASCADIA_HOSTING_WINDOW_CLASS"
    )
    $windows = @($root.FindAll([System.Windows.Automation.TreeScope]::Children, $windowCondition))
    $foregroundHandle = [XinaoGrokManagedVisibleInjectNative]::GetForegroundWindow()
    $foregroundPidRaw = [uint32]0
    [void][XinaoGrokManagedVisibleInjectNative]::GetWindowThreadProcessId($foregroundHandle, [ref]$foregroundPidRaw)

    $titleMatches = @()
    $processMatches = @()
    foreach ($window in $windows) {
        $windowProcessId = [int]$window.Current.ProcessId
        $windowName = [string]$window.Current.Name
        $grokLauncherTerminal = $grokLauncherTerminalPids -contains $windowProcessId
        $codexATerminal = $codexATerminalPids -contains $windowProcessId
        $processStart = ""
        try {
            $processStart = (Get-Process -Id $windowProcessId -ErrorAction Stop).StartTime.ToString("o")
        }
        catch {}

        $tabCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::TabItem
        )
        $tabs = @($window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCondition))
        foreach ($tab in $tabs) {
            $tabName = [string]$tab.Current.Name
            if (Test-IsCodexATabName -TabName $tabName) { continue }
            if (Test-IsGrokAuditNoiseTabName -TabName $tabName) { continue }

            $isExactTitle = ($tabName -eq $WindowTitle) -or ($tabName -match '(?i)管理员:\s*Grok')
            $isGrokAdminTab = Test-IsGrokAdminTabName -TabName $tabName
            if (-not $isGrokAdminTab) { continue }

            $matchReason = if ($isExactTitle) { "exact_grok_tab_title" }
            elseif ($isGrokAdminTab) { "grok_admin_tab_title" }
            else { "grok_launcher_terminal_process" }

            $candidate = [pscustomobject]@{
                Window = $window
                Tab = $tab
                ProcessId = $windowProcessId
                NativeWindowHandle = $window.Current.NativeWindowHandle
                WindowName = $windowName
                TabName = $tabName
                MatchReason = $matchReason
                IsExactTitle = [bool]$isExactTitle
                IsGrokAdminTab = [bool]$isGrokAdminTab
                GrokLauncherTerminal = [bool]$grokLauncherTerminal
                CodexATerminal = [bool]$codexATerminal
                GrokProcessBound = [bool]$grokLauncherTerminal
                IsForeground = (($window.Current.NativeWindowHandle -eq $foregroundHandle.ToInt32()) -or ($windowProcessId -eq [int]$foregroundPidRaw))
                ProcessStartTime = $processStart
            }
            if ($isExactTitle -or ($isGrokAdminTab -and $grokLauncherTerminal)) {
                $titleMatches += $candidate
            }
            elseif ($grokLauncherTerminal) {
                $processMatches += $candidate
            }
        }
    }

    $all = @($titleMatches + $processMatches)
    $seen = @{}
    $unique = @()
    foreach ($candidate in $all) {
        $key = "$($candidate.ProcessId):$($candidate.NativeWindowHandle):$($candidate.TabName)"
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = $true
            $unique += $candidate
        }
    }
    $scanned = @()
    if ($unique.Count -eq 0 -and $grokLauncherTerminalPids.Count -gt 0) {
        $scanned = @(Discover-GrokAdminTabsWithTerminalScan -TerminalPids $grokLauncherTerminalPids -CodexATerminalPids $codexATerminalPids)
        if ($scanned.Count -eq 0 -and $grokProcessRows.Count -gt 0) {
            $orderedRows = @($grokProcessRows | Sort-Object {
                try { (Get-Process -Id $_.ProcessId -ErrorAction Stop).StartTime } catch { Get-Date }
            })
            foreach ($row in $orderedRows) {
                $scanned = @(Discover-GrokAdminTabsWithShellBinding -TerminalPids $grokLauncherTerminalPids -LatestGrokProcess $row -CodexATerminalPids $codexATerminalPids)
                if ($scanned.Count -gt 0) { break }
            }
        }
        foreach ($candidate in $scanned) {
            $key = "$($candidate.ProcessId):$($candidate.NativeWindowHandle):$($candidate.TabName)"
            if (-not $seen.ContainsKey($key)) {
                $seen[$key] = $true
                $unique += $candidate
            }
        }
    }

    return [pscustomobject]@{
        Candidates = @($unique)
        GrokState = $grokState
        GrokLauncherTerminalPids = $grokLauncherTerminalPids
        CodexATerminalPids = $codexATerminalPids
        GrokProcessRows = $grokProcessRows
        LatestGrokProcess = $latestGrokProcess
        TerminalScanUsed = [bool]($scanned.Count -gt 0)
    }
}

function Select-GrokWindowCandidate {
    param(
        [Parameter(Mandatory = $true)][array]$Candidates,
        $Probe = $null
    )
    $grokLauncherTerminalPids = if ($Probe) { @($Probe.GrokLauncherTerminalPids) } else { @(Get-GrokLauncherTerminalPids) }
    $foreground = @($Candidates | Where-Object { $_.IsForeground })
    $exact = @($Candidates | Where-Object { $_.IsExactTitle })
    $grokAdminTab = @($Candidates | Where-Object { $_.IsGrokAdminTab })
    $grokLauncher = @($Candidates | Where-Object { $_.GrokLauncherTerminal })
    $grokLauncherAdmin = @($grokLauncher | Where-Object { $_.IsGrokAdminTab })
    $foregroundGrokAdmin = @($grokAdminTab | Where-Object { $_.IsForeground })
    $terminalGrokAdmin = @()
    if ($grokLauncherTerminalPids.Count -eq 1) {
        $terminalGrokAdmin = @($grokAdminTab | Where-Object { $_.ProcessId -eq $grokLauncherTerminalPids[0] })
    }

    $selected = $null
    $policy = ""
    $reason = ""

    if ($exact.Count -eq 1) {
        $selected = $exact[0]
        $policy = "exact_grok_tab_title"
        $reason = "exact tab title equals Grok admin window"
    }
    elseif ($grokLauncherAdmin.Count -eq 1) {
        $selected = $grokLauncherAdmin[0]
        $policy = "grok_launcher_terminal_grok_admin_tab"
        $reason = "single grok admin tab inside grok-isolated terminal process"
    }
    elseif ($terminalGrokAdmin.Count -eq 1) {
        $selected = $terminalGrokAdmin[0]
        $policy = "grok_process_bound_terminal_tab"
        $reason = "single grok admin tab in terminal bound to isolated grok.exe"
    }
    elseif ($grokAdminTab.Count -eq 1) {
        $selected = $grokAdminTab[0]
        $policy = "grok_admin_tab_title"
        $reason = "single grok admin tab candidate"
    }
    elseif ($foregroundGrokAdmin.Count -ge 1) {
        $selected = $foregroundGrokAdmin[0]
        $policy = "foreground_grok_admin_tab"
        $reason = "foreground candidate is a grok admin tab"
    }
    elseif ($foreground.Count -ge 1) {
        $selected = ($foreground | Where-Object { $_.IsGrokAdminTab } | Select-Object -First 1)
        if ($selected) {
            $policy = "recent_foreground_grok_tab"
            $reason = "foreground grok tab selected from candidates"
        }
    }
    elseif ($Candidates.Count -ge 1) {
        $policy = "multiple_grok_tabs_require_unique_grok_admin_tab"
        $reason = "multiple grok-related tabs found and no unique grok admin tab could be selected safely"
    }

    return [pscustomobject]@{
        Selected = $selected
        SelectionPolicy = $policy
        SelectionReason = $reason
        GrokLauncherTerminalPids = $grokLauncherTerminalPids
        LastActiveEvidence = [ordered]@{
            foreground_candidate_count = $foreground.Count
            selected_is_foreground = if ($null -ne $selected) { [bool]$selected.IsForeground } else { $false }
        }
    }
}

function Send-GrokSubmitKeys {
    param(
        [ValidateSet("enter_normal", "ctrl_i_interrupt", "ctrl_enter")]
        [string]$Mode
    )
    $VK_CONTROL = 0x11
    $VK_I = 0x49
    $VK_RETURN = 0x0D
    $KEYEVENTF_KEYUP = 0x0002
    switch ($Mode) {
        "ctrl_i_interrupt" {
            [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_CONTROL, 0, 0, [UIntPtr]::Zero)
            [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_I, 0, 0, [UIntPtr]::Zero)
            [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_I, 0, $KEYEVENTF_KEYUP, [UIntPtr]::Zero)
            [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_CONTROL, 0, $KEYEVENTF_KEYUP, [UIntPtr]::Zero)
        }
        "ctrl_enter" {
            [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_CONTROL, 0, 0, [UIntPtr]::Zero)
            [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_RETURN, 0, 0, [UIntPtr]::Zero)
            [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_RETURN, 0, $KEYEVENTF_KEYUP, [UIntPtr]::Zero)
            [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_CONTROL, 0, $KEYEVENTF_KEYUP, [UIntPtr]::Zero)
        }
        default {
            [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_RETURN, 0, 0, [UIntPtr]::Zero)
            [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_RETURN, 0, $KEYEVENTF_KEYUP, [UIntPtr]::Zero)
        }
    }
}

function Invoke-GrokDeliveryReadback {
    param(
        [string]$ReadbackScript,
        [string]$WorkspacePath,
        [string]$DeliveryIdValue,
        [string]$MessageSha256,
        [datetime]$StartedAt,
        [int]$WaitSec,
        [switch]$PollUntilConfirmed
    )
    if (-not (Test-Path -LiteralPath $ReadbackScript -PathType Leaf)) {
        return [pscustomobject]@{
            visible_submission_confirmed = $false
            session_modified_after_send = $false
            named_blocker = "GROK_SESSION_READBACK_SCRIPT_MISSING"
        }
    }
    $readbackParams = @{
        Workspace = $WorkspacePath
        DeliveryId = $DeliveryIdValue
        MessageSha256 = $MessageSha256
        StartedAt = $StartedAt
        WaitSec = $WaitSec
    }
    if ($PollUntilConfirmed) { $readbackParams.PollUntilConfirmed = $true }
    $raw = & $ReadbackScript @readbackParams | Out-String
    $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    try {
        return ($raw | ConvertFrom-Json) | Add-Member -NotePropertyName readback_exit_code -NotePropertyValue $exitCode -Force -PassThru
    }
    catch {
        return [pscustomobject]@{
            visible_submission_confirmed = $false
            session_modified_after_send = $false
            named_blocker = "GROK_SESSION_READBACK_INVALID_JSON"
            readback_exit_code = $exitCode
        }
    }
}

function Write-Result {
    param(
        [string]$Status,
        [string]$NamedBlocker = "",
        [array]$Candidates = @(),
        [object]$Selection = $null,
        [object]$Probe = $null,
        [string]$PromptPath = "",
        [string]$MessageSha256 = "",
        [string]$DeliveryIdValue = "",
        [string]$SubmitModeUsed = "",
        [object]$Evidence = $null,
        [bool]$ShortcutLaunched = $false,
        [bool]$PreExistingFound = $false
    )
    $selected = if ($null -ne $Selection) { $Selection.Selected } else { $null }
    $payload = [ordered]@{
        schema_version = if ($Typeahead) { "xinao.grok-managed-visible-typeahead.v1" } else { "xinao.grok-managed-visible-inject.v1" }
        status = $Status
        named_blocker = $NamedBlocker
        target_policy = "grok_admin_isolated_desktop_context_reuse_first"
        shortcut_fallback_requires_explicit_allow = $true
        allow_shortcut_fallback = [bool]$AllowShortcutFallback
        shortcut_ref = $shortcutPath
        pre_existing_grok_tui_found = [bool]$PreExistingFound
        used_existing_grok_tui = [bool]($null -ne $selected -and -not $ShortcutLaunched)
        shortcut_launched = [bool]$ShortcutLaunched
        desktop_context_continuity_policy = "reuse_existing_grok_tui_first_shortcut_only_when_explicit_allow"
        typeahead = [bool]$Typeahead
        target_window_title = $WindowTitle
        workspace = $Workspace
        grok_state = if ($Probe) { $Probe.GrokState } else { (Get-GrokAdminWindowState) }
        grok_launcher_terminal_pids = if ($Probe) { @($Probe.GrokLauncherTerminalPids) } else { @(Get-GrokLauncherTerminalPids) }
        grok_process_rows = if ($Probe) { @($Probe.GrokProcessRows) } else { @(Get-GrokIsolatedProcessRows) }
        candidates = @($Candidates | ForEach-Object {
            [ordered]@{
                process_id = $_.ProcessId
                native_window_handle = $_.NativeWindowHandle
                window_name = $_.WindowName
                tab_name = $_.TabName
                match_reason = $_.MatchReason
                is_exact_title = [bool]$_.IsExactTitle
                is_grok_admin_tab = [bool]$_.IsGrokAdminTab
                grok_launcher_terminal = [bool]$_.GrokLauncherTerminal
                codex_a_terminal = [bool]$_.CodexATerminal
                grok_process_bound = [bool]$_.GrokProcessBound
                is_foreground = [bool]$_.IsForeground
                process_start_time = $_.ProcessStartTime
            }
        })
        selected_candidate = if ($null -ne $selected) {
            [ordered]@{
                process_id = $selected.ProcessId
                native_window_handle = $selected.NativeWindowHandle
                window_name = $selected.WindowName
                tab_name = $selected.TabName
                match_reason = $selected.MatchReason
                is_exact_title = [bool]$selected.IsExactTitle
                is_grok_admin_tab = [bool]$selected.IsGrokAdminTab
                grok_launcher_terminal = [bool]$selected.GrokLauncherTerminal
                codex_a_terminal = [bool]$selected.CodexATerminal
                grok_process_bound = [bool]$selected.GrokProcessBound
                is_foreground = [bool]$selected.IsForeground
                process_start_time = $selected.ProcessStartTime
            }
        }
        else { $null }
        selection_policy = if ($null -ne $Selection) { $Selection.SelectionPolicy } else { "" }
        selection_reason = if ($null -ne $Selection) { $Selection.SelectionReason } else { "" }
        last_active_evidence = if ($null -ne $Selection) { $Selection.LastActiveEvidence } else { $null }
        target_window_handle = if ($null -ne $selected) { $selected.NativeWindowHandle } else { 0 }
        target_process_id = if ($null -ne $selected) { $selected.ProcessId } else { 0 }
        target_tab_name = if ($null -ne $selected) { $selected.TabName } else { "" }
        prompt_path = $PromptPath
        message_sha256 = $MessageSha256
        delivery_id = $DeliveryIdValue
        submit_mode_used = $SubmitModeUsed
        evidence = if ($Evidence) {
            [ordered]@{
                visible_submission_confirmed = [bool]$Evidence.visible_submission_confirmed
                visible_submitted = [bool]$Evidence.visible_submitted
                session_modified_after_send = [bool]$Evidence.session_modified_after_send
                prompt_history_seen = [bool]$Evidence.prompt_history_seen
                delivery_id_seen = [bool]$Evidence.delivery_id_seen
                user_message_seen = [bool]$Evidence.user_message_seen
                assistant_seen = [bool]$Evidence.assistant_seen
                turn_started_after_delivery = [bool]$Evidence.turn_started_after_delivery
                submit_keys_sent_only = [bool]$Evidence.submit_keys_sent_only
                grok_running_at_submit_probe = if ($Evidence.runtime_state) { [bool]$Evidence.runtime_state.grok_running } else { $false }
                submit_recommendation_at_probe = if ($Evidence.runtime_state) { [string]$Evidence.runtime_state.submit_recommendation } else { "" }
                named_blocker = if ($Evidence.named_blocker) { [string]$Evidence.named_blocker } else { "" }
                session_id = if ($Evidence.session_id) { [string]$Evidence.session_id } else { "" }
                readback_exit_code = if ($Evidence.readback_exit_code) { [int]$Evidence.readback_exit_code } else { 0 }
            }
        }
        else { $null }
        visible_submission_confirmed = if ($Evidence) { [bool]$Evidence.visible_submission_confirmed } else { $false }
        session_modified_after_send = if ($Evidence) { [bool]$Evidence.visible_submission_confirmed } else { $false }
        generated_at = (Get-Date).ToString("o")
        sentinel = if ($Typeahead) { "SENTINEL:XINAO_GROK_MANAGED_VISIBLE_TYPEAHEAD_RECORDED" } else { "SENTINEL:XINAO_GROK_MANAGED_VISIBLE_INJECT_RECORDED" }
    }
    $latest = Join-Path $stateDir "latest.json"
    $payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latest -Encoding UTF8
    $payload | ConvertTo-Json -Depth 12
}

function Start-GrokShortcutIfNeeded {
    param([int]$WaitSec)
    $grokState = Get-GrokAdminWindowState
    $launchShortcut = if ($grokState.shortcut) { [string]$grokState.shortcut } else { $shortcutPath }
    if (-not (Test-Path -LiteralPath $launchShortcut -PathType Leaf)) {
        throw "GROK_ADMIN_SHORTCUT_NOT_FOUND: $launchShortcut"
    }
    Start-Process -FilePath $launchShortcut -WindowStyle Normal | Out-Null
    $deadline = (Get-Date).AddSeconds([Math]::Max(8, $WaitSec))
    do {
        Start-Sleep -Milliseconds 800
        $probe = Get-GrokWindowCandidates
        $selection = Select-GrokWindowCandidate -Candidates $probe.Candidates -Probe $probe
        if ($null -ne $selection.Selected) {
            return [pscustomobject]@{
                Candidate = $selection.Selected
                Selection = $selection
                Probe = $probe
            }
        }
    } while ((Get-Date) -lt $deadline)
    throw "GROK_TUI_WINDOW_NOT_FOUND_AFTER_SHORTCUT"
}

$probeResult = Get-GrokWindowCandidates
$matches = @($probeResult.Candidates)
$selection = if ($matches.Count -gt 0) {
    Select-GrokWindowCandidate -Candidates $matches -Probe $probeResult
}
else {
    [pscustomobject]@{
        Selected = $null
        SelectionPolicy = "no_grok_admin_tab_candidates"
        SelectionReason = "isolated grok.exe is running but no grok admin tab title was verified in cascadia"
        GrokLauncherTerminalPids = @($probeResult.GrokLauncherTerminalPids)
        LastActiveEvidence = [ordered]@{
            foreground_candidate_count = 0
            selected_is_foreground = $false
        }
    }
}
$preExistingFound = [bool]($matches.Count -gt 0)
$shortcutLaunched = $false

if ($null -eq $selection.Selected) {
    if ($NoWake -or -not $AllowShortcutFallback) {
        Write-Result -Status "blocked" -NamedBlocker "V2_DESKTOP_GROK_CONTEXT_CONTINUITY_NOT_VERIFIED" -Candidates $matches -Selection $selection -Probe $probeResult -PreExistingFound $preExistingFound
        exit 2
    }
    try {
        $wake = Start-GrokShortcutIfNeeded -WaitSec $WaitSec
        $selection = $wake.Selection
        $matches = @($wake.Probe.Candidates)
        $probeResult = $wake.Probe
        $shortcutLaunched = $true
        $preExistingFound = $false
    }
    catch {
        Write-Result -Status "blocked" -NamedBlocker "V2_DESKTOP_GROK_CONTEXT_CONTINUITY_NOT_VERIFIED" -Candidates $matches -Selection $selection -Probe $probeResult -PreExistingFound $preExistingFound
        exit 2
    }
}

if ($SelectionProbeOnly) {
    Write-Result -Status "selection_probe" -Candidates $matches -Selection $selection -Probe $probeResult -PreExistingFound $preExistingFound -ShortcutLaunched $shortcutLaunched
    exit 0
}

$selected = $selection.Selected
$injectId = if ($InjectId) { $InjectId } else { "grok_managed_visible_typeahead_" + (Get-Date -Format "yyyyMMdd_HHmmss_fff") }
$deliveryIdValue = if ($DeliveryId) { $DeliveryId } else { $injectId }
$wrapped = if ($Message -match '(?i)delivery_id\s*=') { $Message } else { "$Message`ndelivery_id=$deliveryIdValue" }
$promptPath = Join-Path $promptDir "$injectId.prompt.md"
$wrapped | Set-Content -LiteralPath $promptPath -Encoding UTF8
$bytes = [System.Text.Encoding]::UTF8.GetBytes($wrapped)
$sha = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace("-", "").ToLowerInvariant()
$startedAt = Get-Date
$readbackScript = Join-Path $BridgeRoot "Get-GrokSessionDeliveryReadback.ps1"
$preSubmitProbe = Invoke-GrokDeliveryReadback -ReadbackScript $readbackScript -WorkspacePath $Workspace -DeliveryIdValue "" -MessageSha256 "" -StartedAt $startedAt -WaitSec 3
$resolvedSubmitMode = $SubmitMode
if ($resolvedSubmitMode -eq "auto") {
    $resolvedSubmitMode = if ($preSubmitProbe.runtime_state -and $preSubmitProbe.runtime_state.submit_recommendation) {
        [string]$preSubmitProbe.runtime_state.submit_recommendation
    } else { "enter_normal" }
}
if ($resolvedSubmitMode -notin @("enter_normal", "ctrl_i_interrupt", "ctrl_enter")) {
    $resolvedSubmitMode = "enter_normal"
}

try {
    $selectionPattern = $selected.Tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
    $selectionPattern.Select()
}
catch {}
try { $selected.Tab.SetFocus() } catch { try { $selected.Window.SetFocus() } catch {} }

$handle = [intptr][int]$selected.NativeWindowHandle
[void][XinaoGrokManagedVisibleInjectNative]::ShowWindowAsync($handle, 5)
Start-Sleep -Milliseconds 120
[void][XinaoGrokManagedVisibleInjectNative]::BringWindowToTop($handle)
[void][XinaoGrokManagedVisibleInjectNative]::SetForegroundWindow($handle)
Start-Sleep -Milliseconds 250
$rect = New-Object XinaoGrokManagedVisibleInjectNative+RECT
[void][XinaoGrokManagedVisibleInjectNative]::GetWindowRect($handle, [ref]$rect)
$x = [int](($rect.Left + $rect.Right) / 2)
$y = [int]($rect.Bottom - 90)
[void][XinaoGrokManagedVisibleInjectNative]::SetCursorPos($x, $y)
Start-Sleep -Milliseconds 80
[XinaoGrokManagedVisibleInjectNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
[XinaoGrokManagedVisibleInjectNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 180

[System.Windows.Forms.Clipboard]::SetText($wrapped)
$VK_CONTROL = 0x11
$VK_SHIFT = 0x10
$VK_U = 0x55
$VK_V = 0x56
$VK_RETURN = 0x0D
$KEYEVENTF_KEYUP = 0x0002
if ($ClearInputBeforePaste) {
    [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_CONTROL, 0, 0, [UIntPtr]::Zero)
    [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_U, 0, 0, [UIntPtr]::Zero)
    [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_U, 0, $KEYEVENTF_KEYUP, [UIntPtr]::Zero)
    [XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_CONTROL, 0, $KEYEVENTF_KEYUP, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 120
}
[XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_CONTROL, 0, 0, [UIntPtr]::Zero)
[XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_SHIFT, 0, 0, [UIntPtr]::Zero)
[XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_V, 0, 0, [UIntPtr]::Zero)
[XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_V, 0, $KEYEVENTF_KEYUP, [UIntPtr]::Zero)
[XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_SHIFT, 0, $KEYEVENTF_KEYUP, [UIntPtr]::Zero)
[XinaoGrokManagedVisibleInjectNative]::keybd_event([byte]$VK_CONTROL, 0, $KEYEVENTF_KEYUP, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 120
if (-not $SkipSubmit) {
    Send-GrokSubmitKeys -Mode $resolvedSubmitMode
    Start-Sleep -Milliseconds 200
}

$evidence = $null
if ($PollReadback -or $Typeahead) {
    $evidence = Invoke-GrokDeliveryReadback `
        -ReadbackScript $readbackScript `
        -WorkspacePath $Workspace `
        -DeliveryIdValue $deliveryIdValue `
        -MessageSha256 $sha `
        -StartedAt $startedAt `
        -WaitSec $WaitSec `
        -PollUntilConfirmed:($PollReadback -or $Typeahead)
}

$confirmed = [bool]($evidence -and $evidence.visible_submission_confirmed)
$status = if ($Typeahead) {
    if ($confirmed) { "grok_managed_visible_typeahead_readback_confirmed" }
    elseif ($SkipSubmit) { "grok_managed_visible_typeahead_paste_only" }
    else { "grok_managed_visible_typeahead_submit_keys_sent_unconfirmed" }
} else {
    if ($confirmed) { "grok_managed_visible_inject_readback_confirmed" }
    elseif ($SkipSubmit) { "grok_managed_visible_inject_paste_only" }
    else { "grok_managed_visible_inject_submit_keys_sent_unconfirmed" }
}
$namedBlocker = if ($confirmed) { "" } elseif ($evidence -and $evidence.named_blocker) { [string]$evidence.named_blocker } else { "GROK_VISIBLE_TYPEAHEAD_NOT_SUBMITTED" }
Write-Result -Status $status -NamedBlocker $namedBlocker -Candidates $matches -Selection $selection -Probe $probeResult -PromptPath $promptPath -MessageSha256 $sha -DeliveryIdValue $deliveryIdValue -SubmitModeUsed $resolvedSubmitMode -Evidence $evidence -ShortcutLaunched $shortcutLaunched -PreExistingFound $preExistingFound
if ($confirmed) { exit 0 }
if ($SkipSubmit) { exit 0 }
exit 3
