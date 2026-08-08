#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$AgentDir = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

$expectedAgentDir = [IO.Path]::GetFullPath((Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s')).TrimEnd('\')
$actualAgentDir = [IO.Path]::GetFullPath($AgentDir).TrimEnd('\')
if (-not [string]::Equals($actualAgentDir,$expectedAgentDir,[StringComparison]::OrdinalIgnoreCase)) {
    throw "PI_S_NUMPAD_TARGET_NOT_ACTIVE_PRIME_S: $actualAgentDir"
}

$sourceRoot = Split-Path -Parent $PSScriptRoot
$helperSource = Join-Path $sourceRoot 'helpers\PrimeS-NumPadEnter-Follow.ahk'
$toolRoot = 'D:\XINAO_RESEARCH_RUNTIME\tools\autohotkey\2.0.26'
$autoHotkey = Join-Path $toolRoot 'AutoHotkey64.exe'
$bootstrapAutoHotkey = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island\tools\autohotkey-2.0.26\AutoHotkey64.exe'
$expectedAutoHotkeySha256 = 'a2a54b8abc476d7671d4de0771bb54bf5f2373d79ff6871d0ba6a62c3b88ae00'
$keybindingsPath = Join-Path $actualAgentDir 'keybindings.json'
$inputRoot = Join-Path $actualAgentDir 'input'
$receiptPath = Join-Path $inputRoot 'numpad-enter-follow-install.json'
$terminalSettingsPath = Join-Path $env:LOCALAPPDATA 'Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json'

if (-not (Test-Path -LiteralPath $helperSource -PathType Leaf)) {
    throw "PI_S_NUMPAD_HELPER_SOURCE_MISSING: $helperSource"
}

function Get-KeyList {
    param($Value)
    if ($null -eq $Value) { return @() }
    if ($Value -is [string]) { return @([string]$Value) }
    @($Value | ForEach-Object { [string]$_ })
}

function Read-Keybindings {
    $result = [ordered]@{}
    if (-not (Test-Path -LiteralPath $keybindingsPath -PathType Leaf)) { return $result }
    try {
        $parsed = Get-Content -Raw -LiteralPath $keybindingsPath -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "PI_S_NUMPAD_KEYBINDINGS_INVALID_JSON: $keybindingsPath"
    }
    if ($null -eq $parsed -or $parsed -is [Array] -or $parsed -is [string]) {
        throw "PI_S_NUMPAD_KEYBINDINGS_INVALID_OBJECT: $keybindingsPath"
    }
    foreach ($property in $parsed.PSObject.Properties) {
        $result[$property.Name] = $property.Value
    }
    $result
}

function Assert-F12Available {
    param([System.Collections.IDictionary]$Bindings)
    $claimants = @()
    foreach ($action in $Bindings.Keys) {
        if ([string]$action -eq 'tui.altScreen.bottom') { continue }
        if (@(Get-KeyList -Value $Bindings[$action]) -contains 'f12') {
            $claimants += [string]$action
        }
    }
    if ($claimants.Count -gt 0) {
        throw "PI_S_NUMPAD_F12_ALREADY_CLAIMED: $($claimants -join ',')"
    }
}

function Get-PrimeSTerminalIdentity {
    if (-not (Test-Path -LiteralPath $terminalSettingsPath -PathType Leaf)) {
        throw "PI_S_NUMPAD_WINDOWS_TERMINAL_SETTINGS_MISSING: $terminalSettingsPath"
    }
    try {
        $terminalSettings = Get-Content -Raw -LiteralPath $terminalSettingsPath -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "PI_S_NUMPAD_WINDOWS_TERMINAL_SETTINGS_INVALID: $terminalSettingsPath"
    }
    $profiles = @($terminalSettings.profiles.list | Where-Object { [string]$_.name -eq 'XINAO prime S' })
    if ($profiles.Count -ne 1) { throw "PI_S_NUMPAD_WINDOWS_TERMINAL_PROFILE_NOT_UNIQUE: count=$($profiles.Count)" }
    $profile = $profiles[0]
    if ([string]$profile.tabTitle -ne 'prime S' -or $profile.suppressApplicationTitle -ne $true) {
        throw "PI_S_NUMPAD_WINDOWS_TERMINAL_TITLE_SCOPE_INVALID: tabTitle=$($profile.tabTitle) suppressApplicationTitle=$($profile.suppressApplicationTitle)"
    }
    [pscustomobject]@{
        Settings = $terminalSettings
        Profile = $profile
    }
}

$terminalIdentity = Get-PrimeSTerminalIdentity
$terminalSettingsChanged = $false
if ([string]$terminalIdentity.Profile.closeOnExit -ne 'always') {
    if ($ValidateOnly) {
        throw "PI_S_WINDOWS_TERMINAL_CLOSE_ON_EXIT_NOT_INSTALLED: expected=always actual=$($terminalIdentity.Profile.closeOnExit)"
    }
    $terminalIdentity.Profile | Add-Member -NotePropertyName closeOnExit -NotePropertyValue 'always' -Force
    Write-PiDualEntryJsonAtomic -Path $terminalSettingsPath -Value $terminalIdentity.Settings -Depth 30
    $terminalSettingsChanged = $true
}
$bindings = Read-Keybindings
Assert-F12Available -Bindings $bindings
$existingBottom = if ($bindings.Contains('tui.altScreen.bottom')) {
    @(Get-KeyList -Value $bindings['tui.altScreen.bottom'])
} else {
    @('end')
}
$bottomKeys = @($existingBottom)
if ($bottomKeys -notcontains 'f12') { $bottomKeys += 'f12' }
if ($bottomKeys.Count -eq 0) { $bottomKeys = @('f12') }

if ($ValidateOnly) {
    if (-not (Test-Path -LiteralPath $autoHotkey -PathType Leaf)) {
        throw "PI_S_NUMPAD_AUTOHOTKEY_NOT_INSTALLED: $autoHotkey"
    }
    $actualToolHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $autoHotkey).Hash.ToLowerInvariant()
    if ($actualToolHash -ne $expectedAutoHotkeySha256) {
        throw "PI_S_NUMPAD_AUTOHOTKEY_HASH_MISMATCH: expected=$expectedAutoHotkeySha256 actual=$actualToolHash"
    }
    if (-not $bindings.Contains('tui.altScreen.bottom') -or @($existingBottom) -notcontains 'f12') {
        throw "PI_S_NUMPAD_KEYBINDING_NOT_INSTALLED: $keybindingsPath"
    }
} else {
    if (-not (Test-Path -LiteralPath $autoHotkey -PathType Leaf)) {
        if (-not (Test-Path -LiteralPath $bootstrapAutoHotkey -PathType Leaf)) {
            throw "PI_S_NUMPAD_AUTOHOTKEY_BOOTSTRAP_MISSING: $bootstrapAutoHotkey"
        }
        $bootstrapHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $bootstrapAutoHotkey).Hash.ToLowerInvariant()
        if ($bootstrapHash -ne $expectedAutoHotkeySha256) {
            throw "PI_S_NUMPAD_AUTOHOTKEY_BOOTSTRAP_HASH_MISMATCH: expected=$expectedAutoHotkeySha256 actual=$bootstrapHash"
        }
        New-Item -ItemType Directory -Force -Path $toolRoot | Out-Null
        Copy-Item -LiteralPath $bootstrapAutoHotkey -Destination $autoHotkey
    }
    $actualToolHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $autoHotkey).Hash.ToLowerInvariant()
    if ($actualToolHash -ne $expectedAutoHotkeySha256) {
        throw "PI_S_NUMPAD_AUTOHOTKEY_HASH_MISMATCH: expected=$expectedAutoHotkeySha256 actual=$actualToolHash"
    }

    $bindings['tui.altScreen.bottom'] = @($bottomKeys)
    Write-PiDualEntryJsonAtomic -Path $keybindingsPath -Value $bindings

    $validationRoot = Join-Path $inputRoot 'validation'
    New-Item -ItemType Directory -Force -Path $validationRoot | Out-Null
    $validationId = [guid]::NewGuid().ToString('N')
    $isolatedHelper = Join-Path $validationRoot "PrimeS-NumPadEnter-Follow.selftest-$validationId.ahk"
    $stdoutPath = "$isolatedHelper.out"
    $stderrPath = "$isolatedHelper.err"
    try {
        Copy-Item -LiteralPath $helperSource -Destination $isolatedHelper
        $selfTest = Start-Process -FilePath $autoHotkey -ArgumentList @('/ErrorStdOut',$isolatedHelper,'--self-test') -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -Wait -PassThru
        if ($selfTest.ExitCode -ne 0) {
            $errorText = if (Test-Path -LiteralPath $stderrPath) { (Get-Content -Raw -LiteralPath $stderrPath -ErrorAction SilentlyContinue).Trim() } else { '' }
            throw "PI_S_NUMPAD_HELPER_SELF_TEST_FAILED: exit=$($selfTest.ExitCode) error=$errorText"
        }
    } finally {
        foreach ($temporary in @($isolatedHelper,$stdoutPath,$stderrPath)) {
            if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
        }
    }

    New-Item -ItemType Directory -Force -Path $inputRoot | Out-Null
    Write-PiDualEntryJsonAtomic -Path $receiptPath -Value ([ordered]@{
        schema = 'xinao.pis.numpad_enter_follow_install.v1'
        status = 'ready'
        profile = 'prime-s'
        window_scope = 'prime S ahk_exe WindowsTerminal.exe'
        physical_key = 'NumpadEnter'
        input_route = 'ordinary Enter'
        transcript_route = 'F12 -> tui.altScreen.bottom'
        auto_follow_restored = $true
        main_enter_unchanged = $true
        default_end_preserved = (@($bottomKeys) -contains 'end')
        helper_failure_blocks_pi = $false
        windows_terminal_profile_close_on_exit = 'always'
        windows_terminal_settings_modified = $terminalSettingsChanged
        helper_source = $helperSource
        helper_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $helperSource).Hash.ToLowerInvariant()
        autohotkey = $autoHotkey
        autohotkey_sha256 = $actualToolHash
        keybindings = $keybindingsPath
        keybindings_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $keybindingsPath).Hash.ToLowerInvariant()
        updated_at = [DateTimeOffset]::Now.ToString('o')
    })
}

[ordered]@{
    schema = 'xinao.pis.numpad_enter_follow_status.v1'
    status = 'ready'
    profile = 'prime-s'
    validate_only = [bool]$ValidateOnly
    helper_source = $helperSource
    autohotkey = $autoHotkey
    keybindings = $keybindingsPath
    bottom_keys = @($bottomKeys)
    windows_terminal_profile_close_on_exit = 'always'
    windows_terminal_settings_modified = $terminalSettingsChanged
    main_enter_unchanged = $true
    helper_failure_blocks_pi = $false
    receipt = $receiptPath
} | ConvertTo-Json -Depth 5
