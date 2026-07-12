param(
    [int]$DurationSeconds = 60,
    [int]$IntervalMilliseconds = 100,
    [Parameter(Mandatory = $true)][string]$EvidencePath
)

$ErrorActionPreference = 'Stop'

Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class XinaoWindowProbe {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr extraData);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", SetLastError = true)] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@

function Get-VisibleWindows {
    $rows = [System.Collections.Generic.List[object]]::new()
    $callback = [XinaoWindowProbe+EnumWindowsProc]{
        param([IntPtr]$handle, [IntPtr]$unused)
        if (-not [XinaoWindowProbe]::IsWindowVisible($handle)) { return $true }
        $pidValue = [uint32]0
        [void][XinaoWindowProbe]::GetWindowThreadProcessId($handle, [ref]$pidValue)
        if ($pidValue -eq 0) { return $true }
        $titleBuffer = [Text.StringBuilder]::new(1024)
        [void][XinaoWindowProbe]::GetWindowText($handle, $titleBuffer, $titleBuffer.Capacity)
        try { $process = Get-Process -Id ([int]$pidValue) -ErrorAction Stop } catch { return $true }
        $name = [string]$process.ProcessName
        if ($name -notmatch '^(conhost|OpenConsole|WindowsTerminal|cmd|powershell|pwsh|python|pythonw|uv|docker|wt)$') {
            return $true
        }
        $started = try { $process.StartTime.ToUniversalTime().ToString('o') } catch { '' }
        $rows.Add([ordered]@{
            handle = $handle.ToInt64()
            pid = [int]$pidValue
            process = $name
            started_at = $started
            title = $titleBuffer.ToString()
        })
        return $true
    }
    [void][XinaoWindowProbe]::EnumWindows($callback, [IntPtr]::Zero)
    return @($rows)
}

$baseline = @(Get-VisibleWindows)
$baselineKeys = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($row in $baseline) { [void]$baselineKeys.Add("$($row.handle)|$($row.pid)|$($row.started_at)") }
$observed = [System.Collections.Generic.List[object]]::new()
$observedKeys = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
$deadline = [DateTime]::UtcNow.AddSeconds($DurationSeconds)

while ([DateTime]::UtcNow -lt $deadline) {
    $foreground = [XinaoWindowProbe]::GetForegroundWindow().ToInt64()
    foreach ($row in @(Get-VisibleWindows)) {
        $key = "$($row.handle)|$($row.pid)|$($row.started_at)"
        if (-not $baselineKeys.Contains($key) -and $observedKeys.Add($key)) {
            $row.foreground_when_seen = ($row.handle -eq $foreground)
            $row.observed_at = [DateTime]::UtcNow.ToString('o')
            $observed.Add($row)
        }
    }
    Start-Sleep -Milliseconds $IntervalMilliseconds
}

$payload = [ordered]@{
    schema_version = 'xinao.visible_console_window_probe.v1'
    started_at = [DateTime]::UtcNow.AddSeconds(-$DurationSeconds).ToString('o')
    duration_seconds = $DurationSeconds
    interval_milliseconds = $IntervalMilliseconds
    baseline_count = $baseline.Count
    new_console_window_count = $observed.Count
    foreground_regression_count = @($observed | Where-Object { $_.foreground_when_seen }).Count
    observed = @($observed)
}
$parent = Split-Path -Parent $EvidencePath
if ($parent) { [IO.Directory]::CreateDirectory($parent) | Out-Null }
$json = $payload | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($EvidencePath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
$json
if ($observed.Count -gt 0) { exit 1 }
