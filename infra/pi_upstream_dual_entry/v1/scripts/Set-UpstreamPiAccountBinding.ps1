#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile,
    [Parameter(Mandatory)][ValidateSet('main','account-b')][string]$Slot
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

$selected = Resolve-PiDualEntryAccountBinding -Slot $Slot
foreach ($required in @($selected.CodexHome,(Join-Path $selected.CodexHome 'auth.json'))) {
    if (-not (Test-Path -LiteralPath $required)) { throw "PI_ACCOUNT_BINDING_SOURCE_MISSING: $required" }
}

$currentSpec = Get-PiDualEntrySpec -Profile $Profile
$mutex = [Threading.Mutex]::new($false,$currentSpec.MutexName)
$held = $false
$bindingPath = Get-PiDualEntryAccountBindingPath -Profile $Profile
$authPath = Join-Path $currentSpec.AgentDir 'auth.json'
$bindingPreimage = $(if (Test-Path -LiteralPath $bindingPath -PathType Leaf) { [IO.File]::ReadAllBytes($bindingPath) } else { $null })
$authPreimage = $(if (Test-Path -LiteralPath $authPath -PathType Leaf) { [IO.File]::ReadAllBytes($authPath) } else { $null })
try {
    try { $held = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) {
        throw "PI_ACCOUNT_BINDING_REQUIRES_PROFILE_STOP: profile=$Profile"
    }

    $binding = [ordered]@{
        schema = 'xinao.pi_surface_account_binding.v1'
        profile = $Profile
        active_slot = $Slot
        selected_codex_home = $selected.CodexHome
        updated_at = [DateTimeOffset]::Now.ToString('o')
    }
    try {
        Write-PiDualEntryJsonAtomic -Path $bindingPath -Value $binding
        & (Join-Path $PSScriptRoot 'Seed-PiCodexAuth.ps1') -Profile $Profile -Force | Out-Null
    } catch {
        if ($null -ne $bindingPreimage) { [IO.File]::WriteAllBytes($bindingPath,$bindingPreimage) }
        elseif (Test-Path -LiteralPath $bindingPath -PathType Leaf) { Remove-Item -LiteralPath $bindingPath -Force }
        if ($null -ne $authPreimage) { [IO.File]::WriteAllBytes($authPath,$authPreimage) }
        elseif (Test-Path -LiteralPath $authPath -PathType Leaf) { Remove-Item -LiteralPath $authPath -Force }
        throw
    }
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}

[ordered]@{
    status = 'bound'
    profile = $Profile
    active_slot = $Slot
    codex_home = $selected.CodexHome
    binding_path = $bindingPath
    selected_profile_auth_rebound = $true
    clean_process_boundary_enforced = $true
    new_children_inherit_selected_profile_auth_by_construction = $true
    fresh_root_child_account_probe_required = $true
    independent_provider_credentials_preserved = $true
    other_profile_changed = $false
    behavior_projection_changed = $false
    session_tree_changed = $false
    secrets_emitted = $false
} | ConvertTo-Json -Depth 4
