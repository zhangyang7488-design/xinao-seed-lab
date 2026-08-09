#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AgentDir,
    [string]$ReceiptPath = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\acceptance\pi-subagents-filesystem-policy-v1.json',
    [string]$FixtureRoot,
    [ValidateRange(30000,600000)][int]$TimeoutMs = 120000
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSFilesystemAcceptancePath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\','/')
}

function Get-PiSubagentsSourceAggregateSha256 {
    param([Parameter(Mandatory)][string]$AgentDir)
    $sourceRoot = Join-Path $AgentDir 'npm\node_modules\pi-subagents\src'
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) { return 'absent' }
    $prefix = [IO.Path]::GetFullPath($sourceRoot).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    $lines = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
        $relative = [IO.Path]::GetFullPath($_.FullName).Substring($prefix.Length).Replace('\','/')
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        "$relative`t$($_.Length)`t$hash"
    })
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($lines -join "`n"))
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
    } finally {
        if ($null -ne $sha) { $sha.Dispose() }
    }
}

$target = Get-NormalizedPiSFilesystemAcceptancePath -Path $AgentDir
$labParent = Get-NormalizedPiSFilesystemAcceptancePath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
if ((Get-NormalizedPiSFilesystemAcceptancePath -Path (Split-Path -Parent $target)) -cne $labParent) {
    throw "PI_S_FILESYSTEM_POLICY_ACCEPTANCE_REQUIRES_MAIN_BODY_LAB: $target"
}

$spec = Get-PiDualEntrySpec -Profile 'prime-s'
$primeBSpec = Get-PiDualEntrySpec -Profile 'prime-b'
Assert-PiDualEntryBinary -Spec $spec
$activePackageBefore = Get-PiSubagentsSourceAggregateSha256 -AgentDir $spec.AgentDir
$primeBPackageBefore = Get-PiSubagentsSourceAggregateSha256 -AgentDir $primeBSpec.AgentDir
if ($activePackageBefore -ceq 'absent' -or $primeBPackageBefore -ceq 'absent') {
    throw 'PI_S_FILESYSTEM_POLICY_ACCEPTANCE_REFERENCE_PACKAGE_MISSING'
}
$packageRoot = Join-Path $target 'npm\node_modules\pi-subagents'
$cliPath = Join-Path $spec.PiToolRoot 'node_modules\@earendil-works\pi-coding-agent\dist\cli.js'
$rpcClientPath = Join-Path $spec.PiToolRoot 'node_modules\@earendil-works\pi-coding-agent\dist\modes\rpc\rpc-client.js'
$securityHarness = Join-Path $PSScriptRoot 'Test-PiSubagentFilesystemPolicy.mjs'
$bodyHarness = Join-Path $PSScriptRoot 'Test-PiSubagentFilesystemPolicyBodyLab.mjs'
$stopHarness = Join-Path $PSScriptRoot 'Test-PiSubagentSessionStopProcess.mjs'
$stopExtension = Join-Path $PSScriptRoot 'fixtures\pi-owner-stop-autolaunch.ts'
$stopFixture = Join-Path $PSScriptRoot 'fixtures\pi-owner-stop-child.mjs'
$applyScript = Join-Path $PSScriptRoot 'Apply-PiSSubagentsFilesystemPolicy.ps1'
$windowsScript = Join-Path $PSScriptRoot 'Apply-PiSSubagentsWindowsCompatibility.ps1'
$ownerStopScript = Join-Path $PSScriptRoot 'Apply-PiSSubagentsSessionStopCompatibility.ps1'
$startScript = Join-Path $PSScriptRoot 'Start-UpstreamPi.ps1'
$installScript = Join-Path $PSScriptRoot 'Install-UpstreamPiCapabilities.ps1'
$bodyLabFactory = Join-Path $PSScriptRoot 'New-PiSBodyLab.ps1'
$dualEntryAcceptance = Join-Path $PSScriptRoot 'Test-UpstreamPiDualEntry.ps1'
$readmePath = Join-Path (Split-Path -Parent $PSScriptRoot) 'README.md'
$patchPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'patches\pi-subagents-0.44.0-filesystem-policy.patch'
foreach ($required in @(
    (Join-Path $packageRoot 'package.json'),$cliPath,$rpcClientPath,$securityHarness,$bodyHarness,
    $stopHarness,$stopExtension,$stopFixture,$applyScript,$windowsScript,$ownerStopScript,
    $startScript,$installScript,$bodyLabFactory,$dualEntryAcceptance,$readmePath,$patchPath
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_FILESYSTEM_POLICY_ACCEPTANCE_INPUT_MISSING: $required"
    }
}

function Test-PiFilesystemPolicyPatchOrder {
    param([Parameter(Mandatory)][string]$Text)
    $windows = $Text.IndexOf('Apply-PiSSubagentsWindowsCompatibility.ps1',[StringComparison]::Ordinal)
    $owner = $Text.IndexOf('Apply-PiSSubagentsSessionStopCompatibility.ps1',[StringComparison]::Ordinal)
    $policy = $Text.IndexOf('Apply-PiSSubagentsFilesystemPolicy.ps1',[StringComparison]::Ordinal)
    $windows -ge 0 -and $owner -gt $windows -and $policy -gt $owner
}

$startText = Get-Content -Raw -LiteralPath $startScript -Encoding UTF8
$installText = Get-Content -Raw -LiteralPath $installScript -Encoding UTF8
$bodyLabFactoryText = Get-Content -Raw -LiteralPath $bodyLabFactory -Encoding UTF8
$dualEntryText = Get-Content -Raw -LiteralPath $dualEntryAcceptance -Encoding UTF8
$readmeText = Get-Content -Raw -LiteralPath $readmePath -Encoding UTF8
$startPrimeSOnly = $startText -match "(?s)if\s*\(\`$Profile\s+-eq\s+'prime-s'\)\s*\{.*?Apply-PiSSubagentsSessionStopCompatibility\.ps1.*?Apply-PiSSubagentsFilesystemPolicy\.ps1"
$startDisableMidTurnIndex = $startText.LastIndexOf('if ($DisableMidTurnCompactionCompatibility)',[StringComparison]::Ordinal)
$startDisableMidTurnKeepsPrerequisites =
    $startDisableMidTurnIndex -ge 0 -and
    $startText.LastIndexOf('Apply-PiSSubagentsWindowsCompatibility.ps1',[StringComparison]::Ordinal) -lt $startDisableMidTurnIndex -and
    $startText.LastIndexOf('Apply-PiSHermesSessionCompatibility.ps1',[StringComparison]::Ordinal) -lt $startDisableMidTurnIndex -and
    $startText.IndexOf('Apply-PiSSubagentsSessionStopCompatibility.ps1',[StringComparison]::Ordinal) -gt $startDisableMidTurnIndex
$installPrimeSOnly = $installText -match "(?s)if\s*\(\`$profileName\s+-eq\s+'prime-s'\)\s*\{.*?Apply-PiSSubagentsSessionStopCompatibility\.ps1.*?Apply-PiSSubagentsFilesystemPolicy\.ps1"
$bodyLabPrimeSOnly = $bodyLabFactoryText -match "Get-PiDualEntrySpec\s+-Profile\s+'prime-s'"
$dualEntryPrimeBNegative = $dualEntryText.IndexOf('primeBOverlayPolicyMatches',[StringComparison]::Ordinal) -ge 0 -and
    $dualEntryText.IndexOf('PI_SURFACE_TEST_COLD_BACKUP_INHERITED_FILESYSTEM_POLICY',[StringComparison]::Ordinal) -ge 0
$readmeOneHome = $readmeText.IndexOf('Start、Install',[StringComparison]::Ordinal) -ge 0 -and
    $readmeText.IndexOf('PiB 永不调用',[StringComparison]::Ordinal) -ge 0 -and
    $readmeText.IndexOf('路径能力边界',[StringComparison]::Ordinal) -ge 0 -and
    $readmeText.IndexOf('只含安全内容的 projection',[StringComparison]::Ordinal) -ge 0 -and
    $readmeText.IndexOf('Windows OS sandbox',[StringComparison]::Ordinal) -ge 0
if (
    -not (Test-PiFilesystemPolicyPatchOrder -Text $startText) -or
    -not (Test-PiFilesystemPolicyPatchOrder -Text $installText) -or
    -not (Test-PiFilesystemPolicyPatchOrder -Text $bodyLabFactoryText) -or
    -not $startPrimeSOnly -or
    -not $startDisableMidTurnKeepsPrerequisites -or
    -not $installPrimeSOnly -or
    -not $bodyLabPrimeSOnly -or
    -not $dualEntryPrimeBNegative -or
    -not $readmeOneHome
) { throw 'PI_S_FILESYSTEM_POLICY_WIRING_SOURCE_INVALID' }

$primeBPolicyModule = Join-Path $primeBSpec.AgentDir 'npm\node_modules\pi-subagents\src\runs\shared\filesystem-policy.ts'
$primeBManifestText = if (Test-Path -LiteralPath $primeBSpec.OverlayProjectionManifest -PathType Leaf) {
    Get-Content -Raw -LiteralPath $primeBSpec.OverlayProjectionManifest -Encoding UTF8
} else { '' }
$primeBOverlayPolicyMatches = @()
if (Test-Path -LiteralPath $primeBSpec.OverlayRoot -PathType Container) {
    $primeBOverlayPolicyMatches = @(Get-ChildItem -LiteralPath $primeBSpec.OverlayRoot -File -Recurse | Where-Object {
        $_.FullName -match 'filesystem[-_]?policy' -or
        (Select-String -LiteralPath $_.FullName -Pattern 'filesystemPolicy','filesystem-policy' -SimpleMatch -Quiet)
    })
}
if (
    (Test-Path -LiteralPath $primeBPolicyModule -PathType Leaf) -or
    $primeBManifestText -match 'filesystemPolicy|filesystem-policy' -or
    $primeBOverlayPolicyMatches.Count -ne 0
) { throw 'PI_S_FILESYSTEM_POLICY_PRIME_B_NEGATIVE_FAILED' }

if ([string]::IsNullOrWhiteSpace($FixtureRoot)) {
    $FixtureRoot = Join-Path 'D:\XINAO_RESEARCH_RUNTIME\temp' ("pi-filesystem-policy-acceptance-" + [Guid]::NewGuid().ToString('N'))
}
$FixtureRoot = Get-NormalizedPiSFilesystemAcceptancePath -Path $FixtureRoot
if (Test-Path -LiteralPath $FixtureRoot) {
    throw "PI_S_FILESYSTEM_POLICY_ACCEPTANCE_FIXTURE_ALREADY_EXISTS: $FixtureRoot"
}
New-Item -ItemType Directory -Force -Path $FixtureRoot | Out-Null
$bodyReceiptPath = Join-Path $FixtureRoot 'body-lab-receipt.json'
$sessionDir = Join-Path $FixtureRoot 'root-sessions'
$moduleRoot = Join-Path $FixtureRoot 'package-source'
New-Item -ItemType Directory -Force -Path $moduleRoot | Out-Null
Get-ChildItem -LiteralPath $packageRoot -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $moduleRoot -Recurse -Force
}
# Node's native type stripper intentionally rejects .ts below any node_modules segment.
# Exercise an exact byte projection outside that segment while resolving its dependencies
# through fixture-local junctions. The real Pi cases still load the installed body-lab
# package through Pi's own runtime.
$moduleNodeModules = Join-Path $moduleRoot 'node_modules'
$moduleScope = Join-Path $moduleNodeModules '@earendil-works'
$agentNpmRoot = Split-Path -Parent $packageRoot
$piCodingAgentRoot = Join-Path $spec.PiToolRoot 'node_modules\@earendil-works\pi-coding-agent'
$piPeerRoot = Join-Path $piCodingAgentRoot 'node_modules\@earendil-works'
New-Item -ItemType Directory -Force -Path $moduleScope | Out-Null
foreach ($dependency in @('jiti','typebox','yaml')) {
    $dependencySource = Join-Path $agentNpmRoot $dependency
    if (-not (Test-Path -LiteralPath $dependencySource -PathType Container)) {
        throw "PI_S_FILESYSTEM_POLICY_ACCEPTANCE_DEPENDENCY_MISSING: $dependencySource"
    }
    New-Item -ItemType Junction -Path (Join-Path $moduleNodeModules $dependency) -Target $dependencySource | Out-Null
}
$peerDependencies = [ordered]@{
    'pi-coding-agent' = $piCodingAgentRoot
    'pi-agent-core' = Join-Path $piPeerRoot 'pi-agent-core'
    'pi-ai' = Join-Path $piPeerRoot 'pi-ai'
    'pi-tui' = Join-Path $piPeerRoot 'pi-tui'
}
foreach ($peer in $peerDependencies.GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $peer.Value -PathType Container)) {
        throw "PI_S_FILESYSTEM_POLICY_ACCEPTANCE_PEER_DEPENDENCY_MISSING: $($peer.Value)"
    }
    New-Item -ItemType Junction -Path (Join-Path $moduleScope $peer.Key) -Target $peer.Value | Out-Null
}

$windowsRaw = @(& $windowsScript -AgentDir $target -VerifyOnly 2>&1)
if ($LASTEXITCODE -ne 0) { throw "PI_S_FILESYSTEM_POLICY_ACCEPTANCE_WINDOWS_VERIFY_FAILED: $($windowsRaw -join ' ')" }
$windowsReceipt = ($windowsRaw -join [Environment]::NewLine) | ConvertFrom-Json
$ownerRaw = @(& $ownerStopScript -AgentDir $target -VerifyOnly 2>&1)
if ($LASTEXITCODE -ne 0) { throw "PI_S_FILESYSTEM_POLICY_ACCEPTANCE_OWNER_STOP_VERIFY_FAILED: $($ownerRaw -join ' ')" }
$ownerReceipt = ($ownerRaw -join [Environment]::NewLine) | ConvertFrom-Json
$policyRaw = @(& $applyScript -AgentDir $target -VerifyOnly 2>&1)
if ($LASTEXITCODE -ne 0) { throw "PI_S_FILESYSTEM_POLICY_ACCEPTANCE_PATCH_VERIFY_FAILED: $($policyRaw -join ' ')" }
$policyReceipt = ($policyRaw -join [Environment]::NewLine) | ConvertFrom-Json

$securityRaw = @(& node --experimental-strip-types $securityHarness $moduleRoot 2>&1)
if ($LASTEXITCODE -ne 0) { throw "PI_S_FILESYSTEM_POLICY_SECURITY_ACCEPTANCE_FAILED: $($securityRaw -join ' ')" }
$securityReceipt = ($securityRaw -join [Environment]::NewLine) | ConvertFrom-Json
if (
    [string]$securityReceipt.schema -cne 'xinao.pi_subagents_filesystem_policy_security_acceptance.v1' -or
    @($securityReceipt.checks.PSObject.Properties | Where-Object { $_.Value -ne $true }).Count -ne 0
) { throw 'PI_S_FILESYSTEM_POLICY_SECURITY_ACCEPTANCE_INVALID' }

$bodyRaw = @(& node $bodyHarness `
    --cli $cliPath `
    --rpc-client $rpcClientPath `
    --agent-dir $target `
    --module-root $moduleRoot `
    --codex-home $spec.CodexHome `
    --stop-harness $stopHarness `
    --stop-extension $stopExtension `
    --stop-fixture $stopFixture `
    --fixture-root $FixtureRoot `
    --session-dir $sessionDir `
    --receipt $bodyReceiptPath `
    --timeout-ms ([string]$TimeoutMs) 2>&1)
if ($LASTEXITCODE -ne 0) { throw "PI_S_FILESYSTEM_POLICY_BODY_LAB_ACCEPTANCE_FAILED: $($bodyRaw -join ' ')" }
$bodyReceipt = Get-Content -Raw -LiteralPath $bodyReceiptPath -Encoding UTF8 | ConvertFrom-Json
if (
    [string]$bodyReceipt.schema -cne 'xinao.pi_subagents_filesystem_policy_body_lab.v1' -or
    [string]$bodyReceipt.status -cne 'verified' -or
    $bodyReceipt.foreground_safe_read -ne $true -or
    $bodyReceipt.denied_read_blocked -ne $true -or
    $bodyReceipt.junction_escape_blocked_without_sentinel -ne $true -or
    $bodyReceipt.broad_grep_blocked -ne $true -or
    $bodyReceipt.safe_sibling_grep -ne $true -or
    $bodyReceipt.bash_processes_created -ne $false -or
    $bodyReceipt.detached_async_complete -ne $true -or
    $bodyReceipt.resume_retained_policy -ne $true -or
    [int]$bodyReceipt.resume_max_subagent_depth -ne 0 -or
    $bodyReceipt.stale_repair_retained_markers -ne $true -or
    $bodyReceipt.stale_result_only_resume_rejected -ne $true -or
    $bodyReceipt.owner_stop_process_verified -ne $true -or
    $bodyReceipt.no_policy_bash_unchanged -ne $true -or
    $bodyReceipt.no_policy_detached_resume_unchanged -ne $true
) { throw 'PI_S_FILESYSTEM_POLICY_BODY_LAB_ACCEPTANCE_INVALID' }

$transcriptEvidence = @($bodyReceipt.child_tool_result_evidence.PSObject.Properties | ForEach-Object { $_.Value })
if ($transcriptEvidence.Count -ne 11) { throw "PI_S_FILESYSTEM_POLICY_TRANSCRIPT_EVIDENCE_COUNT_INVALID: $($transcriptEvidence.Count)" }
foreach ($evidence in $transcriptEvidence) {
    if (-not (Test-Path -LiteralPath ([string]$evidence.transcriptPath) -PathType Leaf)) {
        throw "PI_S_FILESYSTEM_POLICY_TRANSCRIPT_MISSING: $($evidence.transcriptPath)"
    }
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath ([string]$evidence.transcriptPath)).Hash.ToLowerInvariant()
    if ($actualHash -cne [string]$evidence.transcriptSha256) {
        throw "PI_S_FILESYSTEM_POLICY_TRANSCRIPT_HASH_MISMATCH: case=$($evidence.caseName)"
    }
    if ($null -eq $evidence.isError) { throw "PI_S_FILESYSTEM_POLICY_TRANSCRIPT_IS_ERROR_MISSING: case=$($evidence.caseName)" }
}
$activePackageAfter = Get-PiSubagentsSourceAggregateSha256 -AgentDir $spec.AgentDir
$primeBPackageAfter = Get-PiSubagentsSourceAggregateSha256 -AgentDir $primeBSpec.AgentDir
if ($activePackageAfter -cne $activePackageBefore) {
    throw 'PI_S_FILESYSTEM_POLICY_ACCEPTANCE_MODIFIED_ACTIVE_PACKAGE'
}
if ($primeBPackageAfter -cne $primeBPackageBefore) {
    throw 'PI_S_FILESYSTEM_POLICY_ACCEPTANCE_MODIFIED_PRIME_B_PACKAGE'
}

$sourceFiles = [ordered]@{
    acceptance_wrapper = $PSCommandPath
    apply = $applyScript
    windows = $windowsScript
    owner_stop = $ownerStopScript
    start = $startScript
    install = $installScript
    body_lab_factory = $bodyLabFactory
    dual_entry_acceptance = $dualEntryAcceptance
    readme = $readmePath
    patch = $patchPath
    security_harness = $securityHarness
    body_harness = $bodyHarness
    owner_stop_harness = $stopHarness
    owner_stop_extension = $stopExtension
    owner_stop_fixture = $stopFixture
}
$sourceHashes = [ordered]@{}
foreach ($entry in $sourceFiles.GetEnumerator()) {
    $sourceHashes[$entry.Key] = (Get-FileHash -Algorithm SHA256 -LiteralPath $entry.Value).Hash.ToLowerInvariant()
}
$receipt = [ordered]@{
    schema = 'xinao.pi_s_subagents_filesystem_policy_acceptance.v1'
    status = 'verified'
    generated_at = [DateTimeOffset]::Now.ToString('o')
    lab_agent_dir = $target
    fixture_root = $FixtureRoot
    package = 'pi-subagents@0.44.0'
    patch = $policyReceipt
    windows_compatibility = $windowsReceipt
    owner_session_stop_compatibility = $ownerReceipt
    security = $securityReceipt
    body_lab = $bodyReceipt
    wiring = [ordered]@{
        start_patch_order = $true
        start_prime_s_only = $startPrimeSOnly
        start_disable_midturn_keeps_subagent_prerequisites = $startDisableMidTurnKeepsPrerequisites
        install_patch_order = $true
        install_prime_s_only = $installPrimeSOnly
        body_lab_patch_order = $true
        body_lab_prime_s_only = $bodyLabPrimeSOnly
        dual_entry_prime_b_negative = $dualEntryPrimeBNegative
        readme_one_home_and_path_policy_limit = $readmeOneHome
        prime_b_active_module_absent = -not (Test-Path -LiteralPath $primeBPolicyModule -PathType Leaf)
        prime_b_manifest_absent = -not [bool]($primeBManifestText -match 'filesystemPolicy|filesystem-policy')
        prime_b_source_overlay_absent = ($primeBOverlayPolicyMatches.Count -eq 0)
    }
    source_sha256 = $sourceHashes
    transcript_count = $transcriptEvidence.Count
    transcript_hashes_read_back_equal = $true
    active_pi_subagents_source_before_sha256 = $activePackageBefore
    active_pi_subagents_source_after_sha256 = $activePackageAfter
    active_pi_subagents_source_unchanged = ($activePackageAfter -ceq $activePackageBefore)
    prime_b_pi_subagents_source_before_sha256 = $primeBPackageBefore
    prime_b_pi_subagents_source_after_sha256 = $primeBPackageAfter
    prime_b_pi_subagents_source_unchanged = ($primeBPackageAfter -ceq $primeBPackageBefore)
}
Write-PiDualEntryJsonAtomic -Path $ReceiptPath -Value $receipt
$receipt | ConvertTo-Json -Depth 15
