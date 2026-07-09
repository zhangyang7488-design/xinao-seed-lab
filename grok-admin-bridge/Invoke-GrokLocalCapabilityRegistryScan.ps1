#Requires -Version 5.1
<#
.SYNOPSIS
  Global local capability registry scan — all drives + frozen anchors.
  NOT_333_MAINLINE · evidence only · no user menu.
#>
param(
    [string]$ContractPath = (Join-Path $PSScriptRoot "grok_local_capability_registry.v1.json"),
    [string]$GlueRegistryPath = "E:\XINAO_RESEARCH_WORKSPACES\S\materials\authority_glue\glue_mature_repo_registry.v1.json",
    [string]$OfficialRoot = "E:\XINAO_EXTERNAL_MATURE\codex_20260627\official",
    [string]$WorkspaceConfig = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\.grok\config.toml",
    [string]$GlobalConfig = "C:\Users\xx363\.grok\config.toml",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-McpServerEnabled([string]$ConfigPath, [string]$ServerKey) {
    if (-not (Test-Path -LiteralPath $ConfigPath)) { return $false }
    $text = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
    if ($text -notmatch "\[mcp_servers\.$([regex]::Escape($ServerKey))\]") { return $false }
    return ($text -match "enabled\s*=\s*true")
}

function Test-HttpProbe([string]$Url, [int]$TimeoutSec = 3, [string]$BearerToken = $null) {
    try {
        $params = @{ Uri = $Url; Method = "Get"; TimeoutSec = $TimeoutSec; UseBasicParsing = $true }
        if ($BearerToken) { $params.Headers = @{ Authorization = "Bearer $BearerToken" } }
        $r = Invoke-WebRequest @params
        return [ordered]@{ ok = $true; status = [int]$r.StatusCode }
    }
    catch {
        return [ordered]@{ ok = $false; error = $_.Exception.Message }
    }
}

function Get-GlueRegistryRepos([object]$Glue) {
    $repos = @{}
    if (-not $Glue -or -not $Glue.layers) { return $repos }
    foreach ($layerProp in $Glue.layers.PSObject.Properties) {
        foreach ($item in $Glue.layers.($layerProp.Name)) {
            if ($item.repo) { $repos[$item.repo] = [ordered]@{ layer = $layerProp.Name; item = $item } }
        }
    }
    return $repos
}

function Get-DirName([string]$Repo) { $Repo -replace "/", "__" }

$contract = Read-Json $ContractPath
$glue = Read-Json $GlueRegistryPath
$glueRepos = Get-GlueRegistryRepos $glue

$drives = @(Get-PSDrive -PSProvider FileSystem | ForEach-Object { $_.Root })
$anchors = @($contract.scan_roots_all_drives.frozen_anchors)
$scanPaths = @($anchors | Select-Object -Unique)

$categories = @()
foreach ($cat in $contract.category_catalog) {
    $entry = [ordered]@{
        id           = $cat.id
        registry_key = $cat.registry_key
        on_disk      = $false
        paths_found  = @()
        claim_state  = "unknown"
        mcp_hooked   = $false
        probe        = $null
        notes        = @()
    }

    if ($cat.expected_path) {
        if (Test-Path -LiteralPath $cat.expected_path) {
            $entry.on_disk = $true
            $entry.paths_found += $cat.expected_path
        }
    }
    if ($cat.expected_mirror) {
        if (Test-Path -LiteralPath $cat.expected_mirror) {
            $entry.on_disk = $true
            $entry.paths_found += $cat.expected_mirror
        }
    }
    if ($cat.mcp_server_key) {
        $ws = Test-McpServerEnabled $WorkspaceConfig $cat.mcp_server_key
        $gl = Test-McpServerEnabled $GlobalConfig $cat.mcp_server_key
        $entry.mcp_hooked = ($ws -or $gl)
        $entry.notes += "workspace_mcp=$ws; global_mcp=$gl"
    }
    if ($cat.expected_url) {
        $bearer = $null
        if ($cat.probe_bearer_default) {
            $bearer = if ($env:LITELLM_MASTER_KEY) { $env:LITELLM_MASTER_KEY } else { [string]$cat.probe_bearer_default }
        }
        $entry.probe = Test-HttpProbe $cat.expected_url 5 $bearer
        if ($entry.probe.ok) { $entry.notes += "http_probe_ok" }
    }

    $inGlue = $false
    if ($cat.registry_key -eq "openhands") { $inGlue = $glueRepos.ContainsKey("OpenHands/OpenHands") }
    if ($cat.registry_key -eq "litellm") {
        $inGlue = ($glueRepos.Keys | Where-Object { $_ -like "BerriAI/litellm" }).Count -gt 0
    }

    if ($cat.registry_key -eq "litellm" -and $entry.probe -and $entry.probe.ok) {
        $entry.claim_state = "registered_and_hooked"
        $entry.notes += "thin_glue_invoke_ok"
    }
    elseif ($entry.on_disk -and $entry.mcp_hooked) { $entry.claim_state = "registered_and_hooked" }
    elseif ($entry.on_disk -and -not $entry.mcp_hooked) { $entry.claim_state = "registered_dormant" }
    elseif (-not $entry.on_disk -and $inGlue) { $entry.claim_state = "registry_ghost" }
    else { $entry.claim_state = "on_disk_unclaimed" }

    if ($cat.voided_safety_label -and $entry.on_disk -and -not $entry.mcp_hooked) {
        $entry.claim_state = "safety_template_sealed"
        $entry.notes += "voided_label=$($cat.voided_safety_label)"
    }

    $categories += [pscustomobject]$entry
}

$officialMirrors = @()
if (Test-Path -LiteralPath $OfficialRoot) {
    $officialMirrors = @(Get-ChildItem -LiteralPath $OfficialRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
}

$glueMissingOnDisk = @()
foreach ($repo in $glueRepos.Keys) {
    $dir = Get-DirName $repo
    $p = Join-Path $OfficialRoot $dir
    if (-not (Test-Path -LiteralPath $p)) {
        $glueMissingOnDisk += [ordered]@{ repo = $repo; layer = $glueRepos[$repo].layer; expected = $p }
    }
}

$toolExes = @()
foreach ($root in $scanPaths) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    $toolsDir = Join-Path $root "tools"
    if (Test-Path -LiteralPath $toolsDir) {
        Get-ChildItem -LiteralPath $toolsDir -Recurse -Filter "*.exe" -ErrorAction SilentlyContinue | ForEach-Object {
            $toolExes += $_.FullName
        }
    }
}
$toolExes = @($toolExes | Select-Object -Unique)

$docker = [ordered]@{ daemon_ok = $false; images = @(); error = $null }
try {
    $null = & docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        $docker.daemon_ok = $true
        $imgs = & docker images --format "{{.Repository}}:{{.Tag}}" 2>&1
        if ($LASTEXITCODE -eq 0) {
            $docker.images = @($imgs | Where-Object { $_ -match "openhands|all-hands|litellm|xinao" })
        }
    }
    else { $docker.error = "docker info exit $LASTEXITCODE" }
}
catch { $docker.error = $_.Exception.Message }

$registryHooks = @()
foreach ($repo in $glueRepos.Keys) {
    $item = $glueRepos[$repo].item
    $layer = $glueRepos[$repo].layer
    $dir = Get-DirName $repo
    $mirrorPath = Join-Path $OfficialRoot $dir
    $onDisk = Test-Path -LiteralPath $mirrorPath
    $isDocsOnly = ($repo -eq "docker") -or (-not $item.url -or $item.url -notlike "https://github.com/*")
    if ($isDocsOnly) { continue }
    $hookState = if ($onDisk) { "registered_dormant" } else { "registry_ghost" }
    $registryHooks += [ordered]@{
        repo         = $repo
        layer        = $layer
        mirror_path  = $mirrorPath
        on_disk      = $onDisk
        claim_state  = $hookState
        optional     = [bool]$item.optional
        接线暂缓     = [bool]$item.'接线暂缓'
        invoke_hint  = "integrated_bus glue_seam_invoke params_only"
        hook_target  = "local_capability_registry.glue_mirror_hook"
    }
}
$registryHooksPresent = @($registryHooks | Where-Object { $_.on_disk }).Count
$registryHooksGhost = @($registryHooks | Where-Object { -not $_.on_disk }).Count

$counts = [ordered]@{
    registered_and_hooked    = @($categories | Where-Object { $_.claim_state -eq "registered_and_hooked" }).Count
    registered_dormant       = @($categories | Where-Object { $_.claim_state -eq "registered_dormant" }).Count
    on_disk_unclaimed        = @($categories | Where-Object { $_.claim_state -eq "on_disk_unclaimed" }).Count
    registry_ghost           = @($categories | Where-Object { $_.claim_state -eq "registry_ghost" }).Count
    safety_template_sealed   = @($categories | Where-Object { $_.claim_state -eq "safety_template_sealed" }).Count
    official_mirror_count    = $officialMirrors.Count
    glue_registry_missing    = $glueMissingOnDisk.Count
    glue_registry_hooks      = $registryHooks.Count
    glue_registry_hooks_present = $registryHooksPresent
    glue_registry_hooks_ghost = $registryHooksGhost
    tool_exe_count           = $toolExes.Count
}

$report = [ordered]@{
    schema_version = "xinao.local_capability_registry_scan.v1"
    sentinel       = "SENTINEL:LOCAL_CAPABILITY_REGISTRY_SCAN"
    generated_at   = (Get-Date).ToString("o")
    not_333_mainline = $true
    drives_scanned = $drives
    anchors_scanned = $scanPaths
    counts         = $counts
    categories     = $categories
    tool_exes      = $toolExes
    official_mirrors = $officialMirrors
    glue_missing_on_disk = $glueMissingOnDisk
    registry_hooks = $registryHooks
    docker         = $docker
    safety_template_void_list = $contract.safety_template_void_list
}

$outDir = "D:\XINAO_RESEARCH_RUNTIME\state\local_capability_registry"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$hist = Join-Path $outDir "scan_$stamp.json"
$latest = Join-Path $outDir "latest.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $hist -Encoding UTF8
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $latest -Encoding UTF8

if (-not $Quiet) {
    Write-Host "LOCAL_CAPABILITY_REGISTRY_SCAN"
    Write-Host "hooked=$($counts.registered_and_hooked) dormant=$($counts.registered_dormant) unclaimed=$($counts.on_disk_unclaimed) sealed=$($counts.safety_template_sealed)"
    Write-Host "mirrors=$($counts.official_mirror_count) glue_missing=$($counts.glue_registry_missing) glue_hooks=$($counts.glue_registry_hooks_present)/$($counts.glue_registry_hooks) tool_exe=$($counts.tool_exe_count) docker=$($docker.daemon_ok)"
    Write-Host "latest=$latest"
    $report | ConvertTo-Json -Depth 6
}
else {
    $report | ConvertTo-Json -Depth 6 -Compress
}