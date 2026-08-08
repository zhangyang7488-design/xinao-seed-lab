#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Session,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'

$terminalProfileName = 'prime'
$workspace = 'E:\XINAO_RESEARCH_WORKSPACES\S'
$sessionDir = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s\sessions'
$desktopWrapper = 'C:\Users\xx363\CodexLaunchers\Open-Prime.ps1'
$terminalSettingsPath = 'C:\Users\xx363\AppData\Local\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json'
$windowsTerminal = 'C:\Users\xx363\AppData\Local\Microsoft\WindowsApps\wt.exe'

foreach ($requiredFile in @($desktopWrapper,$terminalSettingsPath,$windowsTerminal)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "PIS_VISIBLE_RESTART_REQUIRED_FILE_MISSING: $requiredFile"
    }
}
if (-not (Test-Path -LiteralPath $sessionDir -PathType Container)) {
    throw "PIS_VISIBLE_RESTART_SESSION_DIR_MISSING: $sessionDir"
}

$candidate = $null
if (Test-Path -LiteralPath $Session -PathType Leaf) {
    $candidate = [IO.Path]::GetFullPath($Session)
} else {
    $matches = @(Get-ChildItem -LiteralPath $sessionDir -File -Filter '*.jsonl' | Where-Object {
        $_.Name.IndexOf($Session,[StringComparison]::OrdinalIgnoreCase) -ge 0
    })
    if ($matches.Count -ne 1) {
        throw "PIS_VISIBLE_RESTART_SESSION_NOT_UNIQUE: selection=$Session count=$($matches.Count)"
    }
    $candidate = [IO.Path]::GetFullPath($matches[0].FullName)
}
$sessionPrefix = [IO.Path]::GetFullPath($sessionDir).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
if (-not $candidate.StartsWith($sessionPrefix,[StringComparison]::OrdinalIgnoreCase)) {
    throw "PIS_VISIBLE_RESTART_SESSION_OUTSIDE_PROFILE: $candidate"
}
try { $sessionHeader = Get-Content -LiteralPath $candidate -TotalCount 1 -Encoding UTF8 | ConvertFrom-Json }
catch { throw "PIS_VISIBLE_RESTART_SESSION_HEADER_INVALID: $candidate" }
if ([string]$sessionHeader.type -cne 'session' -or [string]::IsNullOrWhiteSpace([string]$sessionHeader.id)) {
    throw "PIS_VISIBLE_RESTART_SESSION_IDENTITY_INVALID: $candidate"
}
$latestSession = Get-ChildItem -LiteralPath $sessionDir -File -Filter '*.jsonl' |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
if ($null -eq $latestSession -or -not [IO.Path]::GetFullPath($latestSession.FullName).Equals($candidate,[StringComparison]::OrdinalIgnoreCase)) {
    throw "PIS_VISIBLE_RESTART_SESSION_NOT_LATEST_FOR_PROFILE: requested=$candidate latest=$($latestSession.FullName)"
}

$terminalSettings = Get-Content -Raw -LiteralPath $terminalSettingsPath -Encoding UTF8 | ConvertFrom-Json
$terminalProfiles = @($terminalSettings.profiles.list | Where-Object { [string]$_.name -eq $terminalProfileName })
if (
    $terminalProfiles.Count -ne 1 -or
    [string]$terminalProfiles[0].commandline -notmatch 'Open-Prime\.ps1' -or
    [string]$terminalProfiles[0].tabTitle -ne 'prime' -or
    $terminalProfiles[0].suppressApplicationTitle -ne $true -or
    [string]$terminalProfiles[0].closeOnExit -ne 'always'
) {
    throw 'PIS_VISIBLE_RESTART_TERMINAL_PROFILE_INVALID'
}

$receipt = [ordered]@{
    schema = 'xinao.pis_visible_restart.v1'
    status = 'ready'
    terminal_profile = $terminalProfileName
    terminal_host = $windowsTerminal
    desktop_wrapper = $desktopWrapper
    session_id = [string]$sessionHeader.id
    session_file = $candidate
    same_profile_session_required = $true
    ingress_readback_required = $true
    selection_mode = 'profile-native-continue-after-latest-session-proof'
}
if ($ValidateOnly) {
    $receipt | ConvertTo-Json -Depth 4
    exit 0
}

# The profile is the user-visible consumer. Its native commandline already owns the desktop wrapper,
# title, appearance and close-on-exit lifecycle. Supplying a replacement commandline through wt.exe
# was observed to return exit 0 while creating no Pi process. Launch the proven profile commandline
# unchanged. Start-UpstreamPi's default --continue can select only the newest profile session, so the
# exact requested session is proved newest above and must still be read back through ingress below.
$terminalArguments = @('-w','new','-p','"prime"')
$terminalProcess = Start-Process -FilePath $windowsTerminal -ArgumentList $terminalArguments -WorkingDirectory $workspace -PassThru
$receipt.status = 'launch_requested'
$receipt['launcher_process_id'] = $terminalProcess.Id
$receipt | ConvertTo-Json -Depth 4
