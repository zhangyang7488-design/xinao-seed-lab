#Requires -Version 5.1
<#
.SYNOPSIS
  Start one logical Codex S runtime through credential slot A or B.

.DESCRIPTION
  A and B are not separate Codex configurations.  The main Codex home owns the
  canonical runtime definition.  Account B keeps only credential and
  product-managed account/session state; all declared behavior/configuration
  files are direct NTFS links to the canonical main-home objects.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("A", "B")]
    [string]$AccountSlot,

    [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"

$mainCodexHome = "C:\Users\xx363\.codex"
$accountBCodexHome = "C:\Users\xx363\.codex-s-hardmode-account-b"
$slotCodexHome = if ($AccountSlot -eq "A") { $mainCodexHome } else { $accountBCodexHome }
$workdir = "E:\XINAO_RESEARCH_WORKSPACES\S"
$runtime = "D:\XINAO_RESEARCH_RUNTIME"
$powerShellHome = "D:\XINAO_RESEARCH_RUNTIME\tools\powershell\7.6.4"
$powerShellExe = Join-Path $powerShellHome "pwsh.exe"
$expectedPowerShellSha256 = "DB6DD81183FE57D22E03B911EC9A30A2FD7C40542E97743615355A6FB44F458F"

function Get-NormalizedPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Get-LinkTargetPath([IO.FileSystemInfo]$Item) {
    $target = [string](@($Item.Target)[0])
    if ([string]::IsNullOrWhiteSpace($target)) {
        throw "CODEX_SHARED_RUNTIME_LINK_TARGET_EMPTY: $($Item.FullName)"
    }
    if (-not [IO.Path]::IsPathRooted($target)) {
        $target = Join-Path $Item.DirectoryName $target
    }
    return Get-NormalizedPath $target
}

function Assert-CanonicalFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "CODEX_SHARED_RUNTIME_CANONICAL_FILE_MISSING: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "CODEX_SHARED_RUNTIME_CANONICAL_FILE_MUST_NOT_BE_A_PROJECTION: $Path"
    }
}

function Ensure-SharedFileLink([string]$Projection, [string]$Canonical) {
    Assert-CanonicalFile $Canonical
    $canonicalFull = Get-NormalizedPath $Canonical

    if (Test-Path -LiteralPath $Projection) {
        $item = Get-Item -LiteralPath $Projection -Force
        if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "CODEX_SHARED_RUNTIME_DUPLICATE_FILE_REQUIRES_MIGRATION: $Projection"
        }
        $targetFull = Get-LinkTargetPath $item
        if (-not $targetFull.Equals($canonicalFull, [StringComparison]::OrdinalIgnoreCase)) {
            throw "CODEX_SHARED_RUNTIME_FILE_LINK_TARGET_MISMATCH: $Projection -> $targetFull"
        }
    } else {
        New-Item -ItemType SymbolicLink -Path $Projection -Target $canonicalFull | Out-Null
    }

    if ((Get-FileHash -LiteralPath $Projection -Algorithm SHA256).Hash -cne
        (Get-FileHash -LiteralPath $Canonical -Algorithm SHA256).Hash) {
        throw "CODEX_SHARED_RUNTIME_FILE_BYTES_DIVERGED: $Projection"
    }
}

function Ensure-SharedDirectoryJunction([string]$Projection, [string]$Canonical) {
    if (-not (Test-Path -LiteralPath $Canonical -PathType Container)) {
        throw "CODEX_SHARED_RUNTIME_CANONICAL_DIRECTORY_MISSING: $Canonical"
    }
    $canonicalFull = Get-NormalizedPath $Canonical

    if (Test-Path -LiteralPath $Projection) {
        $item = Get-Item -LiteralPath $Projection -Force
        if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "CODEX_SHARED_RUNTIME_DUPLICATE_DIRECTORY_REQUIRES_MIGRATION: $Projection"
        }
        $targetFull = Get-LinkTargetPath $item
        if (-not $targetFull.Equals($canonicalFull, [StringComparison]::OrdinalIgnoreCase)) {
            throw "CODEX_SHARED_RUNTIME_DIRECTORY_LINK_TARGET_MISMATCH: $Projection -> $targetFull"
        }
    } else {
        New-Item -ItemType Junction -Path $Projection -Target $canonicalFull | Out-Null
    }
}

function Assert-PrivateCredentialCarrier([string]$CodexHome) {
    foreach ($relative in @("auth.json", "sessions", "state_5.sqlite")) {
        $path = Join-Path $CodexHome $relative
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }
        $item = Get-Item -LiteralPath $path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "CODEX_CREDENTIAL_PRIVATE_STATE_MUST_NOT_BE_SHARED: $path"
        }
    }
}

function Assert-DistinctInstalledAccounts {
    $mainAuth = Join-Path $mainCodexHome "auth.json"
    $accountBAuth = Join-Path $accountBCodexHome "auth.json"
    if (-not ((Test-Path -LiteralPath $mainAuth -PathType Leaf) -and
              (Test-Path -LiteralPath $accountBAuth -PathType Leaf))) {
        return
    }

    $mainIdentity = (Get-Content -LiteralPath $mainAuth -Raw -Encoding UTF8 | ConvertFrom-Json).tokens.account_id
    $accountBIdentity = (Get-Content -LiteralPath $accountBAuth -Raw -Encoding UTF8 | ConvertFrom-Json).tokens.account_id
    if ([string]::IsNullOrWhiteSpace([string]$mainIdentity) -or
        [string]::IsNullOrWhiteSpace([string]$accountBIdentity)) {
        throw "CODEX_CREDENTIAL_ACCOUNT_ID_MISSING"
    }
    if ([string]$mainIdentity -ceq [string]$accountBIdentity) {
        throw "CODEX_CREDENTIAL_SLOTS_RESOLVE_TO_SAME_ACCOUNT"
    }
}

function Assert-OrCreateSharedRuntimeBindings {
    Assert-CanonicalFile (Join-Path $mainCodexHome "config.toml")
    Assert-CanonicalFile (Join-Path $mainCodexHome "AGENTS.md")
    Assert-CanonicalFile (Join-Path $mainCodexHome "hooks.json")

    if ($AccountSlot -eq "B") {
        foreach ($directoryName in @("agents", "skills", "rules", "plugins")) {
            Ensure-SharedDirectoryJunction `
                (Join-Path $accountBCodexHome $directoryName) `
                (Join-Path $mainCodexHome $directoryName)
        }

        $sharedFileNames = @("AGENTS.md", "config.toml", "hooks.json")
        $sharedFileNames += @(
            Get-ChildItem -LiteralPath $mainCodexHome -Filter "*.config.toml" -File |
                Select-Object -ExpandProperty Name
        )
        foreach ($fileName in ($sharedFileNames | Sort-Object -Unique)) {
            Ensure-SharedFileLink `
                (Join-Path $accountBCodexHome $fileName) `
                (Join-Path $mainCodexHome $fileName)
        }
    }

    Assert-PrivateCredentialCarrier $mainCodexHome
    Assert-PrivateCredentialCarrier $accountBCodexHome
    Assert-DistinctInstalledAccounts
}

function Resolve-CodexCommand {
    $command = Get-Command codex.cmd -ErrorAction SilentlyContinue
    if ($command) { return $command }
    $command = Get-Command codex -ErrorAction SilentlyContinue
    if ($command) { return $command }
    $bundled = "C:\Users\xx363\AppData\Roaming\npm\node_modules\@openai\codex\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\bin\codex.exe"
    if (Test-Path -LiteralPath $bundled -PathType Leaf) {
        return [pscustomobject]@{ Source = $bundled }
    }
    throw "CODEX_COMMAND_NOT_FOUND"
}

$mandatoryLevel = & whoami.exe /groups | Select-String -Pattern "S-1-16-(12288|16384)"
if (-not $mandatoryLevel) {
    throw "WINDOWS_ELEVATION_REQUIRED: use the Codex A or Codex B desktop shortcut"
}

foreach ($path in @($mainCodexHome, $accountBCodexHome, $workdir, $runtime, $powerShellHome)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "CODEX_S_REQUIRED_PATH_MISSING: $path"
    }
}
if (-not (Test-Path -LiteralPath $powerShellExe -PathType Leaf)) {
    throw "CODEX_S_POWERSHELL_MISSING: $powerShellExe"
}
if ((Get-FileHash -LiteralPath $powerShellExe -Algorithm SHA256).Hash -cne $expectedPowerShellSha256) {
    throw "CODEX_S_POWERSHELL_HASH_MISMATCH"
}

Assert-OrCreateSharedRuntimeBindings

if ($PrepareOnly) {
    Write-Output "CODEX_SHARED_RUNTIME_PREPARE_OK"
    Write-Output "logical_runtime=$mainCodexHome"
    Write-Output "credential_slot=$AccountSlot"
    Write-Output "credential_home=$slotCodexHome"
    Write-Output "shared_files=AGENTS.md,config.toml,hooks.json,*.config.toml"
    Write-Output "shared_directories=agents,skills,rules,plugins"
    Write-Output "private_state=auth.json,sessions,state_5.sqlite"
    return
}

$pathTail = @($env:Path -split ';' | Where-Object { $_ -and $_ -ine $powerShellHome })
$env:Path = (@($powerShellHome) + $pathTail) -join ';'

foreach ($name in @(
    "XINAO_CANONICAL_REPO", "XINAO_BLUEPRINT_REPO", "XINAO_LEGACY_BLUEPRINT_REPO",
    "XINAO_COMPAT_RUNTIME", "XINAO_COMPAT_RUNTIME_ROOT",
    "XINAO_CODEX_SITUATION_ISLAND", "XINAO_CODEX_SITUATION_REF",
    "XINAO_CODEX_CAPABILITY_REF", "XINAO_CODEX_MATURE_CAPABILITY_CATALOG_REF",
    "XINAO_DUAL_BRAIN_TURN_DRAIN", "XINAO_COORD_ROLE", "AM_ME", "AM_ROOT",
    "XINAO_INGRESS_BASE_URL", "XINAO_ROUTE_PROFILE", "XINAO_HARDMODE",
    "OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_MODEL",
    "CODEX_MODEL", "CODEX_API_BASE_URL", "CODEX_MODEL_PROVIDER",
    "DEEPSEEK_API_KEY", "CODEX_BRIDGE_PROXY_KEY", "PROXY_AUTH_KEY"
)) {
    Remove-Item -LiteralPath "Env:\$name" -ErrorAction SilentlyContinue
}

$env:CODEX_HOME = $slotCodexHome
$env:XINAO_REPO = $workdir
$env:XINAO_RUNTIME = $runtime
$env:XINAO_ACCOUNT_SLOT = "codex-credential-$($AccountSlot.ToLowerInvariant())"

if ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected) {
    throw "CODEX_S_INTERACTIVE_TERMINAL_REQUIRED"
}

$configPath = Join-Path $slotCodexHome "config.toml"
$configuredModel = "default"
$modelLine = Select-String -LiteralPath $configPath -Pattern '^\s*model\s*=' | Select-Object -First 1
if ($modelLine) {
    $configuredModel = ($modelLine.Line -split '=', 2)[1].Trim().Trim('"')
}

$authPath = Join-Path $slotCodexHome "auth.json"
$hasAuth = Test-Path -LiteralPath $authPath -PathType Leaf
$Host.UI.RawUI.WindowTitle = "Codex S - credential $AccountSlot"
Write-Host "CODEX S | one shared runtime | credential $AccountSlot" -ForegroundColor Cyan
Write-Host "SHARED_RUNTIME=$mainCodexHome"
Write-Host "CODEX_HOME=$slotCodexHome"
Write-Host "WORKDIR=$workdir"
Write-Host "MODEL=$configuredModel"
Write-Host "AUTH=$(if ($hasAuth) { 'present (this credential slot only)' } else { 'missing - login this credential slot' })"
Write-Host ""

Set-Location -LiteralPath $workdir
$codexCommand = Resolve-CodexCommand
$codexArguments = @("--cd", $workdir, "--dangerously-bypass-approvals-and-sandbox")
if ($AccountSlot -eq "B") {
    # config.toml is the exact shared canonical file.  Only the child node_repl
    # process needs the active credential carrier path as a process-local
    # override; this does not create a second configuration source.
    $codexArguments += @(
        "-c",
        "mcp_servers.node_repl.env.CODEX_HOME='$accountBCodexHome'"
    )
}
& $codexCommand.Source @codexArguments

$exitCode = $LASTEXITCODE
if ($null -eq $exitCode) { $exitCode = 0 }
if ($exitCode -ne 0) {
    throw "CODEX_S_LAUNCH_FAILED: credential $AccountSlot exited with $exitCode"
}
