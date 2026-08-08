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
        Packages = @('npm:pi-subagents@0.43.0','npm:pi-autoresearch@1.6.2')
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
