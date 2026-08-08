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

$bindingPath = Get-PiDualEntryAccountBindingPath -Profile $Profile
$binding = [ordered]@{
    schema = 'xinao.pi_surface_account_binding.v1'
    profile = $Profile
    active_slot = $Slot
    selected_codex_home = $selected.CodexHome
    updated_at = [DateTimeOffset]::Now.ToString('o')
}
Write-PiDualEntryJsonAtomic -Path $bindingPath -Value $binding
& (Join-Path $PSScriptRoot 'Seed-PiCodexAuth.ps1') -Profile $Profile -Force | Out-Null

[ordered]@{
    status = 'bound'
    profile = $Profile
    active_slot = $Slot
    codex_home = $selected.CodexHome
    binding_path = $bindingPath
    selected_profile_auth_rebound = $true
    other_profile_changed = $false
    behavior_projection_changed = $false
    session_tree_changed = $false
    secrets_emitted = $false
} | ConvertTo-Json -Depth 4
