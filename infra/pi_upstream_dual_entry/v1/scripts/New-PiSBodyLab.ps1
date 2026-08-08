#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$')][string]$LabId,
    [string[]]$CandidatePackage = @(),
    [switch]$SeedSerperCredential
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

Assert-PiDualEntryBinary
$source = Get-PiDualEntrySpec -Profile 'prime-s'
$labRoot = Join-Path $script:PiDualEntryStateRoot "body-labs\prime-s\$LabId"
if (Test-Path -LiteralPath $labRoot) { throw "PI_S_BODY_LAB_ALREADY_EXISTS: $labRoot" }

$allPackages = @(@($source.Packages) + @($CandidatePackage) | Select-Object -Unique)
foreach ($package in $allPackages) {
    if ([string]$package -notmatch '^npm:(?:@[^/]+/)?[^@]+@\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$') {
        throw "PI_S_BODY_LAB_PACKAGE_NOT_PINNED: $package"
    }
}

$labValues = [ordered]@{}
foreach ($property in $source.PSObject.Properties) { $labValues[$property.Name] = $property.Value }
$labValues.AgentDir = $labRoot
$labValues.SessionDir = Join-Path $labRoot 'sessions'
$labValues.ContractProjection = Join-Path $labRoot 'PI_CONTRACT.md'
$labValues.OverlayProjectionManifest = Join-Path $labRoot 'xinao-surface-overlay-manifest.json'
$labValues.SupervisorPipe = "\\.\pipe\xinao-pi-supervisor-prime-s-lab-$LabId"
$labSpec = [pscustomobject]$labValues

New-Item -ItemType Directory -Force -Path $labSpec.AgentDir | Out-Null
New-Item -ItemType Directory -Force -Path $labSpec.SessionDir | Out-Null
$contract = Sync-PiDualEntryContractProjection -Spec $labSpec
$overlay = Sync-PiDualEntrySurfaceOverlay -Spec $labSpec

$authPath = Join-Path $labSpec.AgentDir 'auth.json'
$activeAuthSource = Join-Path $source.AgentDir 'auth.json'
Copy-Item -LiteralPath $activeAuthSource -Destination $authPath -Force
if (-not (Test-PiDualEntryAuth -Path $authPath)) { throw "PI_S_BODY_LAB_AUTH_INVALID: $authPath" }
Copy-Item -LiteralPath $source.AccountBindingPath -Destination (Join-Path $labSpec.AgentDir 'account-binding.json') -Force

$agentsPath = Join-Path $labSpec.AgentDir 'AGENTS.md'
New-Item -ItemType SymbolicLink -Path $agentsPath -Target $source.AgentsSource | Out-Null
$agentProjection = Join-Path $labSpec.AgentDir 'agents'
New-Item -ItemType Directory -Force -Path $agentProjection | Out-Null
foreach ($agentFile in @(Get-ChildItem -LiteralPath (Join-Path $source.AgentDir 'agents') -File -Filter '*.md')) {
    Copy-Item -LiteralPath $agentFile.FullName -Destination (Join-Path $agentProjection $agentFile.Name) -Force
}

$sourceSettingsPath = Join-Path $source.AgentDir 'settings.json'
$settings = Get-Content -Raw -LiteralPath $sourceSettingsPath -Encoding UTF8 | ConvertFrom-Json
$settings.sessionDir = $labSpec.SessionDir.Replace('\','/')
$settings.packages = @($allPackages)
Write-PiDualEntryJsonAtomic -Path (Join-Path $labSpec.AgentDir 'settings.json') -Value $settings

$sourceSubagentConfig = Join-Path $source.AgentDir 'extensions\subagent\config.json'
$subagentConfig = Get-Content -Raw -LiteralPath $sourceSubagentConfig -Encoding UTF8 | ConvertFrom-Json
$subagentConfig.defaultSessionDir = (Join-Path $labSpec.SessionDir 'children').Replace('\','/')
Write-PiDualEntryJsonAtomic -Path (Join-Path $labSpec.AgentDir 'extensions\subagent\config.json') -Value $subagentConfig

& (Join-Path $PSScriptRoot 'Set-PiSBodyConfiguration.ps1') -AgentDir $labSpec.AgentDir | Out-Null

$env:PI_CODING_AGENT_DIR = $labSpec.AgentDir
$env:PI_CODING_AGENT_SESSION_DIR = $labSpec.SessionDir
$env:PI_SKIP_VERSION_CHECK = '1'
$env:PI_TELEMETRY = '0'
$env:CODEX_HOME = $source.CodexHome
foreach ($package in $allPackages) {
    $installOutput = @(& $script:PiDualEntryCommand install $package --no-approve 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "PI_S_BODY_LAB_INSTALL_FAILED: package=$package output=$($installOutput -join ' ')"
    }
}
$subagentsCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSSubagentsWindowsCompatibility.ps1') -AgentDir $labSpec.AgentDir) | ConvertFrom-Json
$hermesSessionCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSHermesSessionCompatibility.ps1') -AgentDir $labSpec.AgentDir) | ConvertFrom-Json

$serperReceipt = $null
if ($SeedSerperCredential) {
    $serperReceipt = & (Join-Path $PSScriptRoot 'Set-PiSSerperCredential.ps1') -AgentDir $labSpec.AgentDir
}

$installedSettings = Get-Content -Raw -LiteralPath (Join-Path $labSpec.AgentDir 'settings.json') -Encoding UTF8 | ConvertFrom-Json
$installedPackages = @($installedSettings.packages)
foreach ($package in $allPackages) {
    if ($package -notin $installedPackages) { throw "PI_S_BODY_LAB_PACKAGE_MISSING: $package" }
}
$sessionFiles = @(Get-ChildItem -LiteralPath $labSpec.SessionDir -Recurse -File -ErrorAction SilentlyContinue)
if ($sessionFiles.Count -ne 0) { throw "PI_S_BODY_LAB_SESSION_NOT_EMPTY: $($sessionFiles.Count)" }

$manifestPath = Join-Path $labSpec.AgentDir 'pi-s-body-lab.json'
Write-PiDualEntryJsonAtomic -Path $manifestPath -Value ([ordered]@{
    schema = 'xinao.pi_s_body_lab.v1'
    lab_id = $LabId
    source_profile = 'prime-s'
    pi_version = $script:PiDualEntryVersion
    node_version = (Get-PiDualEntryNodeInfo).RawVersion
    agent_dir = $labSpec.AgentDir
    session_dir = $labSpec.SessionDir
    supervisor_pipe = $labSpec.SupervisorPipe
    baseline_packages = @($source.Packages)
    candidate_packages = @($CandidatePackage)
    installed_packages = @($installedPackages)
    serper_credential_stored = [bool]($null -ne $serperReceipt -and $serperReceipt.credential_stored)
    serper_provider_status = $(if ($null -ne $serperReceipt) { $serperReceipt.provider_status } else { 'not_configured' })
    serper_status_code = $(if ($null -ne $serperReceipt) { $serperReceipt.status_code } else { $null })
    source_settings_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceSettingsPath).Hash.ToLowerInvariant()
    auth_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $authPath).Hash.ToLowerInvariant()
    contract_projection_sha256 = $contract.Sha256
    surface_overlay_manifest_sha256 = $overlay.Sha256
    subagents_windows_compatibility = $subagentsCompatibility
    hermes_session_compatibility = $hermesSessionCompatibility
    session_file_count = 0
    created_at = [DateTimeOffset]::Now.ToString('o')
})

Get-Content -Raw -LiteralPath $manifestPath -Encoding UTF8
