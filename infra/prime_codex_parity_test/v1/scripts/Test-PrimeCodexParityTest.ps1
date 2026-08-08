#Requires -Version 5.1
[CmdletBinding()]
param([switch]$SourceOnly,[switch]$Json)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PrimeParity.Common.ps1')

$checks = [System.Collections.Generic.List[object]]::new()
function Add-Check {
    param([string]$Name,[bool]$Passed,[string]$Detail,[bool]$Blocking = $true)
    $checks.Add([ordered]@{name=$Name;passed=$Passed;blocking=$Blocking;detail=$Detail}) | Out-Null
}

$sourceFiles = @(
    'README.md','COMPATIBILITY_MATRIX.md','BASELINE_COMPATIBILITY_ADOPTION.md','profile\AGENTS.md','profile\settings.json','overlay\FRAME.md',
    'overlay\skills\prime-runtime-compat\SKILL.md','extension\index.ts','extension\frame-loader.cjs',
    'bindings\account-b.json','bindings\account-s.json','launchers\Open-Prime-Codex-Parity-Test.ps1',
    'scripts\PrimeParity.Common.ps1','scripts\Prepare-PrimeCodexParityTest.ps1',
    'scripts\Start-PrimeCodexParityTest.ps1','scripts\Restore-PrimeCurrentMode.ps1',
    'scripts\Set-PrimeCodexParityAccount.ps1','scripts\Initialize-PrimeCodexParityAccount.ps1',
    'scripts\New-PrimeCodexParityKnownGood.ps1','scripts\Run-PrimeCodexParityBehaviorRegression.ps1',
    'scripts\Test-PrimeCodexParityTest.ps1','scripts\prime-daemon-command.mjs',
    'scripts\Stop-PrimeParityDaemon.mjs',
    'evals\provider.py','evals\assert-trajectory.js','evals\promptfooconfig.yaml',
    'evals\fixtures\xinao-existing-repo.json','evals\fixtures\existing-launch-consumer.json',
    'evals\fixtures\greenfield-repo.json'
)
foreach ($relative in $sourceFiles) {
    $path = Join-Path $script:PrimeParitySourceRoot $relative
    Add-Check -Name "source:$relative" -Passed (Test-Path -LiteralPath $path -PathType Leaf) -Detail $path
}

$templateB = Read-PrimeParityJson -Path (Join-Path $script:PrimeParitySourceRoot 'bindings\account-b.json')
$templateS = Read-PrimeParityJson -Path (Join-Path $script:PrimeParitySourceRoot 'bindings\account-s.json')
Add-Check 'account-template-b-verified' ($templateB.initial_state -eq 'verified' -and $templateB.account_id -eq 'account-b') 'Account B is the initial verified binding.'
Add-Check 'account-template-s-fail-closed' ($templateS.initial_state -eq 'unconfigured' -and $null -eq $templateS.prime_auth_source) 'Account S has no invented or copied Prime authentication source.'
Add-Check 'binding-files-contain-no-secret' ($templateB.secret_material_in_binding -eq $false -and $templateS.secret_material_in_binding -eq $false) 'Bindings contain paths and state only.'

$extensionText = Get-Content -Raw -LiteralPath (Join-Path $script:PrimeParitySourceRoot 'extension\index.ts') -Encoding UTF8
$frameText = Get-Content -Raw -LiteralPath (Join-Path $script:PrimeParitySourceRoot 'overlay\FRAME.md') -Encoding UTF8
$commonText = Get-Content -Raw -LiteralPath (Join-Path $script:PrimeParitySourceRoot 'scripts\PrimeParity.Common.ps1') -Encoding UTF8
$prepareText = Get-Content -Raw -LiteralPath (Join-Path $script:PrimeParitySourceRoot 'scripts\Prepare-PrimeCodexParityTest.ps1') -Encoding UTF8
Add-Check 'extension-account-neutral-input' ($extensionText.Contains('PRIME_CODEX_PARITY_ACCOUNT_HOME') -and -not $extensionText.Contains('CODEX_B_ROOT')) 'The consumer resolves account home from the active binding.'
Add-Check 'extension-live-codex-consumer' ($extensionText.Contains('SENTINEL:HUMAN_INTENT_CONTINUITY_ROLE_SEPARATION_V1') -and $extensionText.Contains('UserPromptSubmit')) 'Live Codex L0 and zero-beat hook are consumed per turn.'
Add-Check 'extension-source-direction-guard' ($extensionText.Contains('protectedRoots') -and $extensionText.Contains('block: true')) 'Direct edit guard protects upstream behavior sources.'
Add-Check 'frame-user-side-grounding' ($frameText.Contains('technical agent inside the current machine') -and $frameText.Contains('smallest sufficient live surface')) 'Detached generic-adviser failure is represented as a generative rule.'
Add-Check 'frame-classification-reversal' ($frameText.Contains('genuine greenfield object may justify one')) 'Existing-repo and greenfield surfaces can reverse classification.'
Add-Check 'frame-owner-eligibility-not-appointment' ($frameText.Contains('role eligible') -and $frameText.Contains('explicitly appointed')) 'Behavior consumption is not collapsed into formal appointment.'
Add-Check 'frame-no-auto-approval-reviewer' ($frameText.Contains('must not add an automatic approval-review model')) 'The test adds no approval-review agent route.'
Add-Check 'session-switch-checks-entire-rlm-tree' ($commonText.Contains('Assert-PrimeParityConversationTreeIdle') -and $commonText.Contains('runtimeKind')) 'Idle parent cannot hide a still-running RLM child during a mode switch.'
Add-Check 'desktop-entry-source-name' ($prepareText.Contains('Desktop\prime S.lnk') -and $prepareText.Contains('--title "prime S"')) 'The projected desktop entry is named prime S.'
Add-Check 'desktop-entry-source-icon' ($prepareText.Contains('CodexLaunchers\assets\codex-s-hardmode.ico,0')) 'The projected shortcut uses the same icon as PrimeB.'
Add-Check 'protected-prime-b-source-entry' ($prepareText.Contains('Desktop\PrimeB.lnk')) 'The existing PrimeB shortcut is the protected baseline entry.'
$mainConfig = Get-Content -Raw -LiteralPath 'C:\Users\xx363\.codex\config.toml' -Encoding UTF8
$bConfig = Get-Content -Raw -LiteralPath 'C:\Users\xx363\.codex-s-hardmode-account-b\config.toml' -Encoding UTF8
$approvalDisabled = {
    param([string]$Text)
    $Text -match '(?m)^approval_policy\s*=\s*"never"' -and $Text -match '(?m)^approvals_reviewer\s*=\s*"user"'
}
Add-Check 'codex-auto-approval-reviewer-disabled' ((& $approvalDisabled $mainConfig) -and (& $approvalDisabled $bConfig)) 'Main and B Codex homes use approval_policy=never with user reviewer.'

if (-not $SourceOnly) {
    $conversation = Get-PrimeParityConversationBinding
    $active = Read-PrimeParityJson -Path (Join-Path $script:PrimeParityRuntimeRoot 'active-account.json')
    $bindingB = Read-PrimeParityJson -Path (Join-Path $script:PrimeParityRuntimeRoot 'bindings\account-b.json')
    $bindingS = Read-PrimeParityJson -Path (Join-Path $script:PrimeParityRuntimeRoot 'bindings\account-s.json')
    Add-Check 'active-account-b' ($active.account_id -eq 'account-b') 'Initial active binding remains Account B.'
    Add-Check 'runtime-account-b-verified' ($bindingB.state -eq 'verified' -and (Test-PrimeParityAuth -Path ([string]$bindingB.profile_auth_path))) 'Account B Prime-format auth is valid without printing it.'
    Add-Check 'runtime-account-s-inactive' ($bindingS.state -eq 'unconfigured' -and -not (Test-PrimeParityAuth -Path ([string]$bindingS.profile_auth_path))) 'Account S remains inactive until a verified Prime auth source exists.'
    Add-Check 'one-conversation-pointer' ($conversation.session_copy_created -eq $false -and $conversation.durable_session_id -eq '019fddc4-a1a2-702e-a03e-9dbd8f499651') "Exact durable session $($conversation.durable_session_id); no copy."
    $runtimeSessionCopies = @(Get-ChildItem -LiteralPath $script:PrimeParityRuntimeRoot -Recurse -Filter '*.jsonl' -File -ErrorAction SilentlyContinue)
    Add-Check 'no-runtime-session-copy' ($runtimeSessionCopies.Count -eq 0) "Parity runtime JSONL copies: $($runtimeSessionCopies.Count)"

    $baseline = Read-PrimeParityJson -Path (Join-Path $script:PrimeParityRuntimeRoot 'validation\protected-baseline.json')
    foreach ($name in @('prime_shortcut','c_launcher','d_launcher')) {
        $before = $baseline.$name
        $now = Get-PrimeParityFileRecord -Path ([string]$before.path)
        $same = ($now.sha256 -eq $before.sha256 -and $now.length -eq $before.length -and $now.last_write_time_utc -eq $before.last_write_time_utc)
        Add-Check "protected-$name" $same "sha256=$($now.sha256); mtime=$($now.last_write_time_utc)"
    }
    $islandFailures = @()
    $currentIslandFiles = @(Get-ChildItem -LiteralPath $script:PrimeParityOldIsland -Recurse -File -Force | Sort-Object FullName)
    if ($currentIslandFiles.Count -ne @($baseline.old_island_files).Count) {
        $islandFailures += "count:$($currentIslandFiles.Count)/$(@($baseline.old_island_files).Count)"
    }
    $beforeByPath = @{}
    foreach ($record in @($baseline.old_island_files)) { $beforeByPath[[string]$record.path] = $record }
    foreach ($file in $currentIslandFiles) {
        $before = $beforeByPath[$file.FullName]
        if ($null -eq $before -or (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash -ne $before.sha256) {
            $islandFailures += $file.FullName
        }
    }
    Add-Check 'protected-old-island-files' ($islandFailures.Count -eq 0) ($(if($islandFailures.Count -eq 0){'All old island files unchanged.'}else{$islandFailures -join ';'}))

    $gitDiff = (& git -C $script:PrimeParitySRoot diff --binary | Out-String)
    $gitDiffHash = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($gitDiff))).Replace('-','')
    $gitStatus = @(& git -C $script:PrimeParitySRoot status --short | Where-Object { $_ -notmatch 'infra/prime_codex_parity_test/v1' })
    Add-Check 'protected-unrelated-s-tracked-diff' ($gitDiffHash -eq $baseline.s_tracked_diff_sha256) "sha256=$gitDiffHash"
    Add-Check 'protected-unrelated-s-status' (($gitStatus -join "`n") -eq (@($baseline.s_status_excluding_new_feature) -join "`n")) "entries=$($gitStatus.Count)"

    Add-Check 'new-c-launcher-present' (Test-Path -LiteralPath 'C:\Users\xx363\CodexLaunchers\Open-Prime-Codex-Parity-Test.ps1' -PathType Leaf) 'New account-neutral launcher exists.'
    $shortcutPath = 'C:\Users\xx363\Desktop\prime S.lnk'
    Add-Check 'new-desktop-entry-present' (Test-Path -LiteralPath $shortcutPath -PathType Leaf) 'The prime S test shortcut exists alongside PrimeB.lnk.'
    if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
        Add-Check 'new-desktop-entry-icon' ($shortcut.IconLocation -eq 'C:\Users\xx363\CodexLaunchers\assets\codex-s-hardmode.ico,0') "icon=$($shortcut.IconLocation)"
    }
    Add-Check 'legacy-desktop-entry-retired' (-not (Test-Path -LiteralPath 'C:\Users\xx363\Desktop\Prime-Codex-Parity-Test.lnk')) 'The obsolete test shortcut name is absent.'
    Add-Check 'runtime-overlay-private' (Test-Path -LiteralPath (Join-Path $script:PrimeParityRuntimeRoot 'overlay\FRAME.md') -PathType Leaf) 'Mutable Prime compatibility overlay is on D.'
    Add-Check 'runtime-extension-projected' (Test-Path -LiteralPath (Join-Path $script:PrimeParityRuntimeRoot 'extension\index.ts') -PathType Leaf) 'Executable adapter projection exists on D.'

    $live = Get-PrimeParityExactLiveSession -Conversation $conversation
    if ($null -ne $live) {
        Add-Check 'live-session-identity' ($live.sessionId -eq $conversation.durable_session_id -and [System.IO.Path]::GetFullPath([string]$live.sessionFile) -eq [System.IO.Path]::GetFullPath([string]$conversation.session_file)) 'Live worker is attached to the exact durable JSONL.'
    }
}

$failures = @($checks | Where-Object { -not $_.passed -and $_.blocking })
$receipt = [ordered]@{
    schema = 'xinao.prime_codex_parity.static_acceptance.v1'
    status = if ($failures.Count -eq 0) { 'verified' } else { 'failed' }
    source_only = [bool]$SourceOnly
    passed = @($checks | Where-Object passed).Count
    failed = $failures.Count
    checks = $checks
    observed_at = (Get-Date).ToString('o')
}
if (-not $SourceOnly -and (Test-Path -LiteralPath $script:PrimeParityRuntimeRoot)) {
    Write-PrimeParityJsonAtomic -Path (Join-Path $script:PrimeParityRuntimeRoot 'validation\static-latest.json') -Value $receipt
}
if ($Json) { $receipt | ConvertTo-Json -Depth 12 } else {
    Write-Host "Prime parity static acceptance: $($receipt.status) ($($receipt.passed) passed, $($receipt.failed) failed)" -ForegroundColor $(if($failures.Count -eq 0){'Green'}else{'Red'})
    foreach ($failure in $failures) { Write-Host "- $($failure.name): $($failure.detail)" -ForegroundColor Yellow }
}
if ($failures.Count -gt 0) { exit 1 }
exit 0
