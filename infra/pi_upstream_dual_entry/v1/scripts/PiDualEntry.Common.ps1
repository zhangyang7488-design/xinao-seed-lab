#Requires -Version 5.1

$script:PiDualEntryVersion = '0.84.1'
$script:PiDualEntryToolRoot = 'D:\XINAO_RESEARCH_RUNTIME\tools\pi\0.84.1'
$script:PiDualEntryCommand = Join-Path $script:PiDualEntryToolRoot 'node_modules\.bin\pi.cmd'
$script:PiDualEntryStateRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1'
$script:PiDualEntryMinimumNodeVersion = [version]'22.19.0'
$script:PiDualEntryBehaviorCodexHome = 'C:\Users\xx363\.codex'
$script:PiDualEntryFamilyContract = 'E:\XINAO_RESEARCH_WORKSPACES\pi-local-cognition-contract-island\AGENTS.md'
$script:PiDualEntrySourceRoot = Split-Path -Parent $PSScriptRoot

function Resolve-PiDualEntryAccountBinding {
    param([Parameter(Mandatory)][ValidateSet('main','account-b')][string]$Slot)

    if ($Slot -eq 'main') {
        return [pscustomobject]@{
            Slot = 'main'
            DisplayName = 'Main Codex'
            CodexHome = 'C:\Users\xx363\.codex'
        }
    }
    [pscustomobject]@{
        Slot = 'account-b'
        DisplayName = 'Codex Account B'
        CodexHome = 'C:\Users\xx363\.codex-s-hardmode-account-b'
    }
}

function Get-PiDualEntryDefaultAccountSlot {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)
    if ($Profile -eq 'prime-b') { 'account-b' } else { 'main' }
}

function Get-PiDualEntryAccountBindingPath {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)
    Join-Path $script:PiDualEntryStateRoot "profiles\$Profile\account-binding.json"
}

function Get-PiDualEntryActiveAccountSlot {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)

    $path = Get-PiDualEntryAccountBindingPath -Profile $Profile
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return Get-PiDualEntryDefaultAccountSlot -Profile $Profile
    }
    try {
        $binding = Get-Content -Raw -LiteralPath $path -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "PI_ACCOUNT_BINDING_INVALID: $path"
    }
    $slot = [string]$binding.active_slot
    if ($slot -notin @('main','account-b')) {
        throw "PI_ACCOUNT_BINDING_SLOT_INVALID: profile=$Profile slot=$slot"
    }
    $slot
}

function Get-PiDualEntryAccountBinding {
    param(
        [Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile,
        [ValidateSet('main','account-b')][string]$Slot
    )
    if ([string]::IsNullOrWhiteSpace($Slot)) {
        $Slot = Get-PiDualEntryActiveAccountSlot -Profile $Profile
    }
    Resolve-PiDualEntryAccountBinding -Slot $Slot
}

function Initialize-PiDualEntryAccountBinding {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)

    $path = Get-PiDualEntryAccountBindingPath -Profile $Profile
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        [void](Get-PiDualEntryActiveAccountSlot -Profile $Profile)
        return $path
    }
    $slot = Get-PiDualEntryDefaultAccountSlot -Profile $Profile
    $account = Resolve-PiDualEntryAccountBinding -Slot $slot
    Write-PiDualEntryJsonAtomic -Path $path -Value ([ordered]@{
        schema = 'xinao.pi_surface_account_binding.v1'
        profile = $Profile
        active_slot = $slot
        selected_codex_home = $account.CodexHome
        updated_at = [DateTimeOffset]::Now.ToString('o')
    })
    $path
}

function Get-PiDualEntryNodeInfo {
    $nodeCommand = Get-Command node.exe -ErrorAction Stop
    $rawVersion = ([string](& $nodeCommand.Source --version | Select-Object -First 1)).Trim()
    $versionText = $rawVersion.TrimStart('v')
    try { $version = [version]$versionText } catch { throw "PI_NODE_VERSION_UNREADABLE: $rawVersion" }

    [pscustomobject]@{
        Path = $nodeCommand.Source
        RawVersion = $rawVersion
        Version = $version
        Minimum = $script:PiDualEntryMinimumNodeVersion
        MinimumSatisfied = ($version -ge $script:PiDualEntryMinimumNodeVersion)
    }
}

function Get-PiDualEntrySpec {
    param([Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile)

    $account = Get-PiDualEntryAccountBinding -Profile $Profile
    $agentDir = Join-Path $script:PiDualEntryStateRoot "profiles\$Profile"
    $overlayRoot = Join-Path $script:PiDualEntrySourceRoot "surface-overlays\$Profile"
    $common = [ordered]@{
        Profile = $Profile
        AccountSlot = $account.Slot
        AccountDisplayName = $account.DisplayName
        AccountBindingPath = Get-PiDualEntryAccountBindingPath -Profile $Profile
        AgentDir = $agentDir
        SessionDir = Join-Path $agentDir 'sessions'
        CodexHome = $script:PiDualEntryBehaviorCodexHome
        AgentsSource = Join-Path $script:PiDualEntryBehaviorCodexHome 'AGENTS.md'
        CodexAuthSource = Join-Path $account.CodexHome 'auth.json'
        FamilyContractSource = $script:PiDualEntryFamilyContract
        ContractProjection = Join-Path $agentDir 'PI_CONTRACT.md'
        OverlayRoot = $overlayRoot
        OverlayAgentDir = Join-Path $overlayRoot 'agents'
        OverlayContractDir = Join-Path $overlayRoot 'contract'
        OverlayExtensionDir = Join-Path $overlayRoot 'extensions'
        OverlaySkillDir = Join-Path $overlayRoot 'skills'
        OverlayProjectionManifest = Join-Path $agentDir 'xinao-surface-overlay-manifest.json'
        SupervisorPipe = $(if ($Profile -eq 'prime-s') { '\\.\pipe\xinao-pi-supervisor-prime-s-v1' } else { $null })
    }
    if ($Profile -eq 'prime-b') {
        return [pscustomobject]($common + [ordered]@{
            Role = 'minimum-usable'
            DisplayName = 'PrimeB'
            Workspace = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island'
            SurfaceIsland = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island'
            SurfaceContractSource = 'E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island\AGENTS.md'
            SurfaceSentinel = 'PI_SURFACE_PRIME_B_V3'
            Packages = @('npm:pi-subagents@0.43.0')
            ExcludedTools = @()
            MutexName = 'Local\XinaoUpstreamPi0841B'
        })
    }
    [pscustomobject]($common + [ordered]@{
        Role = 'primary'
        DisplayName = 'prime S'
        Workspace = 'E:\XINAO_RESEARCH_WORKSPACES\S'
        SurfaceIsland = 'E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island'
        SurfaceContractSource = 'E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island\AGENTS.md'
        SurfaceSentinel = 'PI_SURFACE_PRIME_S_V1'
        Packages = @('npm:pi-subagents@0.43.0','npm:pi-autoresearch@1.6.2','npm:pi-hermes-memory@0.9.4','npm:pi-mcp-adapter@2.21.1')
        ExcludedTools = @('skill_manage','mcp','mcpScript')
        MutexName = 'Local\XinaoUpstreamPi0841S'
    })
}

function Sync-PiDualEntryContractProjection {
    param([Parameter(Mandatory)]$Spec)

    $contractSources = @($Spec.FamilyContractSource,$Spec.SurfaceContractSource)
    if (Test-Path -LiteralPath $Spec.OverlayContractDir -PathType Container) {
        $contractSources += @(Get-ChildItem -LiteralPath $Spec.OverlayContractDir -File -Filter '*.md' | Sort-Object Name | Select-Object -ExpandProperty FullName)
    }
    foreach ($source in $contractSources) {
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "PI_CONTRACT_SOURCE_MISSING: $source"
        }
    }
    New-Item -ItemType Directory -Force -Path $Spec.AgentDir | Out-Null
    $contentParts = @(
        '# GENERATED ACTIVE PI CONTRACT - DO NOT EDIT THIS PROJECTION'
        "# family_source: $($Spec.FamilyContractSource)"
        "# surface_source: $($Spec.SurfaceContractSource)"
    )
    foreach ($source in $contractSources) {
        $contentParts += @('',"# source: $source",'',(Get-Content -Raw -LiteralPath $source -Encoding UTF8).TrimEnd(),'','---')
    }
    $content = (($contentParts -join [Environment]::NewLine).TrimEnd('-',[char]13,[char]10)) + [Environment]::NewLine
    [IO.File]::WriteAllText($Spec.ContractProjection,$content,[Text.UTF8Encoding]::new($false))
    [pscustomobject]@{
        Path = $Spec.ContractProjection
        Sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Spec.ContractProjection).Hash.ToLowerInvariant()
        FamilySha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Spec.FamilyContractSource).Hash.ToLowerInvariant()
        SurfaceSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Spec.SurfaceContractSource).Hash.ToLowerInvariant()
        Sources = @($contractSources)
    }
}

function Sync-PiDualEntrySurfaceOverlay {
    param([Parameter(Mandatory)]$Spec)

    New-Item -ItemType Directory -Force -Path $Spec.AgentDir | Out-Null
    $previousOwned = @()
    if (Test-Path -LiteralPath $Spec.OverlayProjectionManifest -PathType Leaf) {
        try {
            $previous = Get-Content -Raw -LiteralPath $Spec.OverlayProjectionManifest -Encoding UTF8 | ConvertFrom-Json
        } catch {
            throw "PI_PROFILE_OVERLAY_MANIFEST_INVALID: $($Spec.OverlayProjectionManifest)"
        }
        if ([string]$previous.schema -ne 'xinao.pi_surface_overlay_projection.v1' -or [string]$previous.profile -ne [string]$Spec.Profile) {
            throw "PI_PROFILE_OVERLAY_MANIFEST_IDENTITY_MISMATCH: $($Spec.OverlayProjectionManifest)"
        }
        $previousOwned = @($previous.owned_files | ForEach-Object { [string]$_ })
    }

    $sourceKinds = [ordered]@{
        extensions = $Spec.OverlayExtensionDir
        skills = $Spec.OverlaySkillDir
    }
    $owned = @()
    $hashes = [ordered]@{}
    foreach ($kind in $sourceKinds.Keys) {
        $sourceRoot = [string]$sourceKinds[$kind]
        if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) { continue }
        $sourcePrefix = [IO.Path]::GetFullPath($sourceRoot).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
        foreach ($source in @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | Sort-Object FullName)) {
            $sourceFull = [IO.Path]::GetFullPath($source.FullName)
            if (-not $sourceFull.StartsWith($sourcePrefix,[StringComparison]::OrdinalIgnoreCase)) {
                throw "PI_PROFILE_OVERLAY_SOURCE_ESCAPE: $sourceFull"
            }
            $relative = $sourceFull.Substring($sourcePrefix.Length).Replace('\','/')
            if ([string]::IsNullOrWhiteSpace($relative) -or $relative -match '(^|/)\.\.(/|$)') {
                throw "PI_PROFILE_OVERLAY_RELATIVE_PATH_INVALID: $relative"
            }
            $ownedRelative = "$kind/$relative"
            if ($ownedRelative -in $owned) { throw "PI_PROFILE_OVERLAY_SOURCE_COLLISION: $ownedRelative" }
            $destination = Join-Path $Spec.AgentDir $ownedRelative.Replace('/','\')
            $destinationParent = Split-Path -Parent $destination
            New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
            $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceFull).Hash.ToLowerInvariant()
            if ((Test-Path -LiteralPath $destination -PathType Leaf) -and $ownedRelative -notin $previousOwned) {
                $existingHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
                if ($existingHash -ne $sourceHash) {
                    throw "PI_PROFILE_OVERLAY_PROJECTION_CONFLICT: $destination"
                }
            }
            Copy-Item -LiteralPath $sourceFull -Destination $destination -Force
            $destinationHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
            if ($destinationHash -ne $sourceHash) { throw "PI_PROFILE_OVERLAY_PROJECTION_DRIFT: $destination" }
            $owned += $ownedRelative
            $hashes[$ownedRelative] = $sourceHash
        }
    }

    $agentPrefix = [IO.Path]::GetFullPath($Spec.AgentDir).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    foreach ($stale in @($previousOwned | Where-Object { $_ -notin $owned })) {
        if ($stale -notmatch '^(extensions|skills)/' -or $stale -match '(^|/)\.\.(/|$)') {
            throw "PI_PROFILE_OVERLAY_STALE_PATH_INVALID: $stale"
        }
        $stalePath = [IO.Path]::GetFullPath((Join-Path $Spec.AgentDir $stale.Replace('/','\')))
        if (-not $stalePath.StartsWith($agentPrefix,[StringComparison]::OrdinalIgnoreCase)) {
            throw "PI_PROFILE_OVERLAY_STALE_PATH_ESCAPE: $stalePath"
        }
        if (Test-Path -LiteralPath $stalePath -PathType Leaf) {
            Remove-Item -LiteralPath $stalePath -Force
        }
    }

    Write-PiDualEntryJsonAtomic -Path $Spec.OverlayProjectionManifest -Value ([ordered]@{
        schema = 'xinao.pi_surface_overlay_projection.v1'
        profile = $Spec.Profile
        source_root = $Spec.OverlayRoot
        owned_files = @($owned)
        sha256 = $hashes
    })
    [pscustomobject]@{
        Path = $Spec.OverlayProjectionManifest
        Sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Spec.OverlayProjectionManifest).Hash.ToLowerInvariant()
        OwnedFiles = @($owned)
        Hashes = $hashes
    }
}

function Assert-PiDualEntryBinary {
    $node = Get-PiDualEntryNodeInfo
    if (-not $node.MinimumSatisfied) {
        throw "PI_NODE_VERSION_TOO_OLD: required=$($node.Minimum) actual=$($node.Version) path=$($node.Path)"
    }
    if (-not (Test-Path -LiteralPath $script:PiDualEntryCommand -PathType Leaf)) {
        throw "PI_0841_BINARY_MISSING: $script:PiDualEntryCommand"
    }
    $versionOutput = @(& $script:PiDualEntryCommand --version 2>$null)
    $actual = ([string]($versionOutput | Select-Object -First 1)).Trim()
    if (-not [string]::Equals($actual, $script:PiDualEntryVersion, [StringComparison]::Ordinal)) {
        throw "PI_VERSION_MISMATCH: expected=$script:PiDualEntryVersion actual=$actual"
    }
}

function Test-PiDualEntryAuth {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        $auth = Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json
        $provider = $auth.'openai-codex'
        return (
            $null -ne $provider -and
            [string]$provider.type -eq 'oauth' -and
            -not [string]::IsNullOrWhiteSpace([string]$provider.access) -and
            -not [string]::IsNullOrWhiteSpace([string]$provider.refresh) -and
            -not [string]::IsNullOrWhiteSpace([string]$provider.accountId)
        )
    } catch { return $false }
}

function Get-PiDualEntryAuthAccountId {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-PiDualEntryAuth -Path $Path)) { return $null }
    $auth = Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json
    [string]$auth.'openai-codex'.accountId
}

function Write-PiDualEntryJsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value,
        [int]$Depth = 12
    )
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Path.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()).tmp"
    $json = $Value | ConvertTo-Json -Depth $Depth
    [IO.File]::WriteAllText($temporary,$json + [Environment]::NewLine,[Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}
