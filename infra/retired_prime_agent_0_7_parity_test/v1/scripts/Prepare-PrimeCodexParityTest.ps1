#Requires -Version 5.1
[CmdletBinding()]
param([switch]$RefreshOverlaySeed)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PrimeParity.Common.ps1')

function Copy-PrimeParityDirectory {
    param([Parameter(Mandatory)][string]$Source,[Parameter(Mandatory)][string]$Destination)
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Destination -Recurse -Force
}

function Initialize-PrimeParityProfile {
    param([Parameter(Mandatory)][string]$AccountId)
    $profile = Join-Path $script:PrimeParityRuntimeRoot "profiles\$AccountId"
    New-Item -ItemType Directory -Force -Path $profile | Out-Null
    Copy-Item -LiteralPath (Join-Path $script:PrimeParitySourceRoot 'profile\AGENTS.md') -Destination (Join-Path $profile 'AGENTS.md') -Force
    Copy-Item -LiteralPath (Join-Path $script:PrimeParitySourceRoot 'profile\settings.json') -Destination (Join-Path $profile 'settings.json') -Force
    Copy-Item -LiteralPath (Join-Path $script:PrimeParityOldProfile 'keybindings.json') -Destination (Join-Path $profile 'keybindings.json') -Force
    $profile
}

function ConvertTo-PrimeParityRuntimeBinding {
    param([Parameter(Mandatory)]$Template,[Parameter(Mandatory)][string]$Profile,[string]$AuthSource)
    $authPath = Join-Path $Profile 'auth.json'
    [ordered]@{
        schema = 'xinao.prime_codex_parity.account_binding.runtime.v1'
        account_id = [string]$Template.account_id
        display_name = [string]$Template.display_name
        provider = [string]$Template.provider
        codex_home = [string]$Template.codex_home
        canonical_codex_root = [string]$Template.canonical_codex_root
        profile_path = $Profile
        profile_auth_path = $authPath
        auth_source_path = $AuthSource
        auth_transport = if ($AuthSource) { 'same-volume-hardlink' } else { 'unconfigured' }
        state = if ($AuthSource -and (Test-PrimeParityAuth -Path $authPath)) { 'verified' } else { 'unconfigured' }
        secret_material_in_binding = $false
        updated_at = (Get-Date).ToString('o')
    }
}

foreach ($required in @(
    $script:PrimeParityPrimeCommand,
    $script:PrimeParityOldIsland,
    $script:PrimeParityOldProfile,
    (Join-Path $script:PrimeParityOldProfile 'auth.json'),
    (Join-Path $script:PrimeParityOldProfile 'kernel-venv\Scripts\python.exe')
)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "PRIME_PARITY_PREPARE_REQUIRED_PATH_MISSING: $required" }
}

$sourceRoots = @(Get-PrimeParityTopLevelSessions)
if ($sourceRoots.Count -ne 1) { throw "PRIME_PARITY_PREPARE_REQUIRES_ONE_TOP_LEVEL_SOURCE_SESSION: observed=$($sourceRoots.Count)" }
Assert-PrimeParityIdle -Session $sourceRoots[0]
$sourceConversation = [pscustomobject]@{durable_session_id=$sourceRoots[0].sessionId;session_file=$sourceRoots[0].sessionFile}
Assert-PrimeParityConversationTreeIdle -Conversation $sourceConversation

$directories = @(
    $script:PrimeParityRuntimeRoot,
    (Join-Path $script:PrimeParityRuntimeRoot 'bindings'),
    (Join-Path $script:PrimeParityRuntimeRoot 'profiles'),
    (Join-Path $script:PrimeParityRuntimeRoot 'shared'),
    (Join-Path $script:PrimeParityRuntimeRoot 'candidate-output'),
    (Join-Path $script:PrimeParityRuntimeRoot 'continuation'),
    (Join-Path $script:PrimeParityRuntimeRoot 'launch'),
    (Join-Path $script:PrimeParityRuntimeRoot 'validation')
)
foreach ($directory in $directories) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }

Copy-PrimeParityDirectory -Source (Join-Path $script:PrimeParitySourceRoot 'extension') -Destination (Join-Path $script:PrimeParityRuntimeRoot 'extension')
$overlayDestination = Join-Path $script:PrimeParityRuntimeRoot 'overlay'
if ($RefreshOverlaySeed -or -not (Test-Path -LiteralPath (Join-Path $overlayDestination 'FRAME.md') -PathType Leaf)) {
    Copy-PrimeParityDirectory -Source (Join-Path $script:PrimeParitySourceRoot 'overlay') -Destination $overlayDestination
}

$shared = Join-Path $script:PrimeParityRuntimeRoot 'shared'
foreach ($name in @('windows-compat.cjs','rlm-model-catalog-compat.cjs')) {
    Copy-Item -LiteralPath (Join-Path $script:PrimeParityOldProfile $name) -Destination (Join-Path $shared $name) -Force
}
$sharedVenv = Join-Path $shared 'kernel-venv'
if (-not (Test-Path -LiteralPath (Join-Path $sharedVenv 'Scripts\python.exe') -PathType Leaf)) {
    New-Item -ItemType Directory -Force -Path $sharedVenv | Out-Null
    $null = & robocopy.exe (Join-Path $script:PrimeParityOldProfile 'kernel-venv') $sharedVenv /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { throw "PRIME_PARITY_KERNEL_COPY_FAILED: robocopy=$LASTEXITCODE" }
}

$profileB = Initialize-PrimeParityProfile -AccountId 'account-b'
$profileS = Initialize-PrimeParityProfile -AccountId 'account-s'
$authSourceB = Join-Path $script:PrimeParityOldProfile 'auth.json'
$authDestinationB = Join-Path $profileB 'auth.json'
if (-not (Test-Path -LiteralPath $authDestinationB -PathType Leaf)) {
    New-Item -ItemType HardLink -Path $authDestinationB -Target $authSourceB | Out-Null
}
if (-not (Test-PrimeParityAuth -Path $authDestinationB)) { throw 'PRIME_PARITY_ACCOUNT_B_AUTH_PROJECTION_INVALID' }

$templateB = Read-PrimeParityJson -Path (Join-Path $script:PrimeParitySourceRoot 'bindings\account-b.json')
$templateS = Read-PrimeParityJson -Path (Join-Path $script:PrimeParitySourceRoot 'bindings\account-s.json')
$runtimeBindingB = ConvertTo-PrimeParityRuntimeBinding -Template $templateB -Profile $profileB -AuthSource $authSourceB
$runtimeBindingS = ConvertTo-PrimeParityRuntimeBinding -Template $templateS -Profile $profileS -AuthSource $null
if (Test-PrimeParityAuth -Path (Join-Path $profileS 'auth.json')) {
    $runtimeBindingS.state = 'verified'
    $runtimeBindingS.auth_source_path = (Join-Path $profileS 'auth.json')
    $runtimeBindingS.auth_transport = 'profile-native'
}
Write-PrimeParityJsonAtomic -Path (Join-Path $script:PrimeParityRuntimeRoot 'bindings\account-b.json') -Value $runtimeBindingB
Write-PrimeParityJsonAtomic -Path (Join-Path $script:PrimeParityRuntimeRoot 'bindings\account-s.json') -Value $runtimeBindingS

$activeAccountPath = Join-Path $script:PrimeParityRuntimeRoot 'active-account.json'
if (-not (Test-Path -LiteralPath $activeAccountPath -PathType Leaf)) {
    Write-PrimeParityJsonAtomic -Path $activeAccountPath -Value ([ordered]@{
        schema = 'xinao.prime_codex_parity.active_account.v1'
        account_id = 'account-b'
        updated_at = (Get-Date).ToString('o')
        effect = 'account_binding_only_no_session_or_behavior_copy'
    })
}

$conversationPath = Join-Path $script:PrimeParityRuntimeRoot 'conversation-binding.json'
if (-not (Test-Path -LiteralPath $conversationPath -PathType Leaf)) {
    $live = @(Get-PrimeParityTopLevelSessions)
    if ($live.Count -ne 1) { throw "PRIME_PARITY_EXACTLY_ONE_LIVE_SOURCE_SESSION_REQUIRED: observed=$($live.Count)" }
    $sourceSession = $live[0]
    $sessionFile = [System.IO.Path]::GetFullPath([string]$sourceSession.sessionFile)
    $header = (Get-Content -LiteralPath $sessionFile -TotalCount 1 -Encoding UTF8) | ConvertFrom-Json
    if ($header.type -ne 'session' -or [string]$header.id -ne [string]$sourceSession.sessionId) {
        throw 'PRIME_PARITY_LIVE_SESSION_HEADER_MISMATCH'
    }
    Write-PrimeParityJsonAtomic -Path $conversationPath -Value ([ordered]@{
        schema = 'xinao.prime_codex_parity.conversation_binding.v1'
        durable_session_id = [string]$sourceSession.sessionId
        session_file = $sessionFile
        session_dir = Split-Path -Parent $sessionFile
        original_cwd = [string]$sourceSession.cwd
        original_profile = $script:PrimeParityOldProfile
        daemon_socket = $script:PrimeParitySocket
        captured_from_active_id = [string]$sourceSession.activeSessionId
        captured_at = (Get-Date).ToString('o')
        session_copy_created = $false
    })
}
$null = Get-PrimeParityConversationBinding

$baselinePath = Join-Path $script:PrimeParityRuntimeRoot 'validation\protected-baseline.json'
if (-not (Test-Path -LiteralPath $baselinePath -PathType Leaf)) {
    $islandFiles = @(Get-ChildItem -LiteralPath $script:PrimeParityOldIsland -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
        Get-PrimeParityFileRecord -Path $_.FullName
    })
    $gitDiffHash = (& git -C $script:PrimeParitySRoot diff --binary | Out-String)
    $gitStatus = @(& git -C $script:PrimeParitySRoot status --short | Where-Object { $_ -notmatch 'infra/prime_codex_parity_test/v1' })
    Write-PrimeParityJsonAtomic -Path $baselinePath -Value ([ordered]@{
        schema = 'xinao.prime_codex_parity.protected_baseline.v1'
        captured_at = (Get-Date).ToString('o')
        prime_shortcut = Get-PrimeParityFileRecord -Path 'C:\Users\xx363\Desktop\PrimeB.lnk'
        c_launcher = Get-PrimeParityFileRecord -Path 'C:\Users\xx363\CodexLaunchers\Open-Prime-Agent-Account-B.ps1'
        d_launcher = Get-PrimeParityFileRecord -Path 'D:\XINAO_RESEARCH_RUNTIME\state\prime-agent\profiles\account-b\Run-PrimeB-Test.ps1'
        old_island_files = $islandFiles
        s_tracked_diff_sha256 = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($gitDiffHash))).Replace('-','')
        s_status_excluding_new_feature = $gitStatus
        excluded_mutable_identity = @('provider auth token refresh','durable session append','runtime logs')
    })
}

$cLauncherSource = Join-Path $script:PrimeParitySourceRoot 'launchers\Open-Prime-Codex-Parity-Test.ps1'
$cLauncher = 'C:\Users\xx363\CodexLaunchers\Open-Prime-Codex-Parity-Test.ps1'
Copy-Item -LiteralPath $cLauncherSource -Destination $cLauncher -Force
$shortcutPath = 'C:\Users\xx363\Desktop\prime S.lnk'
$legacyShortcutPath = 'C:\Users\xx363\Desktop\Prime-Codex-Parity-Test.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'C:\Users\xx363\AppData\Local\Microsoft\WindowsApps\wt.exe'
$shortcut.Arguments = '-w new new-tab --title "prime S" -p "XINAO Prime Agent Account B" "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\xx363\CodexLaunchers\Open-Prime-Codex-Parity-Test.ps1"'
$shortcut.WorkingDirectory = $script:PrimeParitySRoot
$shortcut.IconLocation = 'C:\Users\xx363\CodexLaunchers\assets\codex-s-hardmode.ico,0'
$shortcut.Description = 'prime S; one durable Prime conversation with the Codex-compatible behavior surface'
$shortcut.Save()
if (Test-Path -LiteralPath $legacyShortcutPath -PathType Leaf) {
    Remove-Item -LiteralPath $legacyShortcutPath -Force
}

$receipt = [ordered]@{
    schema = 'xinao.prime_codex_parity.prepare_receipt.v1'
    status = 'prepared'
    runtime_root = $script:PrimeParityRuntimeRoot
    active_account = (Read-PrimeParityJson -Path $activeAccountPath).account_id
    account_b = (Read-PrimeParityJson -Path (Join-Path $script:PrimeParityRuntimeRoot 'bindings\account-b.json')).state
    account_s = (Read-PrimeParityJson -Path (Join-Path $script:PrimeParityRuntimeRoot 'bindings\account-s.json')).state
    durable_session_id = (Get-PrimeParityConversationBinding).durable_session_id
    session_copy_created = $false
    original_shortcut_changed = $false
    prepared_at = (Get-Date).ToString('o')
}
Write-PrimeParityJsonAtomic -Path (Join-Path $script:PrimeParityRuntimeRoot 'validation\prepare-latest.json') -Value $receipt
$receipt | ConvertTo-Json -Depth 8
