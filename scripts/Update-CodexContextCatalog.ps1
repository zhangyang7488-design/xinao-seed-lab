#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$IslandRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island',
    [string]$CatalogPath = '',
    [string]$CoreIndexPath = '',
    [string]$MaintenanceMapPath = ''
)

$ErrorActionPreference = 'Stop'
$utf8 = [Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

if ([string]::IsNullOrWhiteSpace($CatalogPath)) {
    $CatalogPath = Join-Path $IslandRoot 'context_catalog.json'
}
if ([string]::IsNullOrWhiteSpace($CoreIndexPath)) {
    $CoreIndexPath = Join-Path $IslandRoot 'core_index.json'
}
if ([string]::IsNullOrWhiteSpace($MaintenanceMapPath)) {
    $MaintenanceMapPath = Join-Path $IslandRoot 'contracts\mainline_maintenance_map.v1.json'
}

function Get-Sha256Lower {
    param([Parameter(Mandatory)][string]$LiteralPath)
    return (Get-FileHash -LiteralPath $LiteralPath -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory)][string]$LiteralPath,
        [Parameter(Mandatory)]$Value
    )
    $parent = Split-Path -Parent $LiteralPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temporary = Join-Path $parent ('.' + [IO.Path]::GetFileName($LiteralPath) + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $json = $Value | ConvertTo-Json -Depth 12
        [IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, $utf8)
        Move-Item -LiteralPath $temporary -Destination $LiteralPath -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $MaintenanceMapPath -PathType Leaf)) {
    throw "CONTEXT_SOURCE_MAP_MISSING:$MaintenanceMapPath"
}
$map = Get-Content -LiteralPath $MaintenanceMapPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    [string]$map.schema_version -ne 'xinao.machine_context_source_map.v2' -or
    [string]$map.sentinel -ne 'SENTINEL:XINAO_MACHINE_CONTEXT_SOURCE_MAP_V2' -or
    $map.authority -ne $false
) {
    throw 'CONTEXT_SOURCE_MAP_IDENTITY_INVALID'
}
$sources = @($map.sources)
if ($sources.Count -eq 0) {
    throw 'CONTEXT_SOURCE_MAP_EMPTY'
}

$seen = @{}
$observed = [Collections.Generic.List[object]]::new()
foreach ($source in $sources) {
    $id = [string]$source.id
    $path = [string]$source.path
    if ([string]::IsNullOrWhiteSpace($id) -or [string]::IsNullOrWhiteSpace($path)) {
        throw 'CONTEXT_SOURCE_ID_OR_PATH_EMPTY'
    }
    if ($seen.ContainsKey($id)) {
        throw "CONTEXT_SOURCE_ID_DUPLICATE:$id"
    }
    $seen[$id] = $true
    $required = [bool]$source.required
    $available = Test-Path -LiteralPath $path -PathType Leaf
    if ($required -and -not $available) {
        throw "REQUIRED_SOURCE_MISSING:${id}:$path"
    }
    $entry = [ordered]@{
        id = $id
        path = $path
        role = [string]$source.role
        required = $required
        available = $available
        load_policy = if ($source.load_policy) { [string]$source.load_policy } else { 'on_demand' }
    }
    if ($available) {
        $item = Get-Item -LiteralPath $path
        $entry.bytes = [int64]$item.Length
        $entry.sha256 = Get-Sha256Lower -LiteralPath $path
        $entry.observed_write_time_utc = $item.LastWriteTimeUtc.ToString('o')
    }
    $observed.Add([pscustomobject]$entry)
}

$generatedAt = [DateTime]::UtcNow.ToString('o')
$architecture = [ordered]@{
    default_parent = 'E:\XINAO_RESEARCH_WORKSPACES\xinao-native-research'
    engineering = 'E:\XINAO_RESEARCH_WORKSPACES\S'
    runtime = 'D:\XINAO_RESEARCH_RUNTIME'
    cold_archive = 'E:\XINAO_COLD_STORAGE\archives\LEGACY_XINAO_PLATFORM'
    desktop_hot_entry = 'C:\Users\xx363\Desktop\主线'
}
$catalog = [ordered]@{
    schema_version = 'xinao.codex_context_catalog.v4'
    sentinel = 'SENTINEL:XINAO_CODEX_CONTEXT_CATALOG_V4'
    authority = $false
    completion_claim_allowed = $false
    generated_at = $generatedAt
    architecture = $architecture
    default_route = 'native_xinao_research_unless_current_request_explicitly_names_another_object'
    legacy_platform_in_active_choice_set = $false
    sources = @($observed)
}
$core = [ordered]@{
    schema_version = 'xinao.codex_core_index.v4'
    sentinel = 'SENTINEL:XINAO_CODEX_CORE_INDEX_V4'
    authority = $false
    generated_at = $generatedAt
    architecture = $architecture
    catalog_path = $CatalogPath
    source_map_path = $MaintenanceMapPath
    startup_source_ids = @(
        'global_agents',
        'stable_mainline_entry',
        'native_agents',
        'native_start',
        'session_start_context',
        'predecision_intent_guard'
    )
    on_demand_source_ids = @($observed | Where-Object { $_.load_policy -ne 'startup' } | ForEach-Object { $_.id })
}
$generatedState = [pscustomobject]@{
    generated_at = $generatedAt
    source_count = $observed.Count
    required_count = @($observed | Where-Object { $_.required }).Count
    available_count = @($observed | Where-Object { $_.available }).Count
}
$map | Add-Member -NotePropertyName generated_state -NotePropertyValue $generatedState -Force
$map.sources = @($observed)

Write-JsonAtomic -LiteralPath $CatalogPath -Value $catalog
Write-JsonAtomic -LiteralPath $CoreIndexPath -Value $core
Write-JsonAtomic -LiteralPath $MaintenanceMapPath -Value $map

$receipt = [ordered]@{
    schema_version = 'xinao.context_catalog_refresh_receipt.v2'
    status = 'REFRESHED'
    authority_text_mutated = $false
    legacy_projection_generated = $false
    catalog_path = $CatalogPath
    core_index_path = $CoreIndexPath
    source_map_path = $MaintenanceMapPath
    source_count = $observed.Count
    required_count = @($observed | Where-Object { $_.required }).Count
    available_count = @($observed | Where-Object { $_.available }).Count
}
[Console]::WriteLine(($receipt | ConvertTo-Json -Depth 5 -Compress))
