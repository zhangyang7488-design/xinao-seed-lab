#Requires -Version 7.0

[CmdletBinding()]
param(
    # Repo-hosted one-home still binds live Situation Island projections by default.
    [string]$IslandRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island',
    [string]$CatalogPath = '',
    [string]$MaintenanceMapPath = '',
    [string]$FoundationImplementationProjectionJson = '',
    # Optional CAS pins from tool-glue publication postflight (empty = derive-only refresh).
    [string]$ExpectedSoftwareFoundationSha256 = '',
    [string]$ExpectedSoftwareFoundationVersion = ''
)

if ([string]::IsNullOrWhiteSpace($CatalogPath)) {
    $CatalogPath = Join-Path $IslandRoot 'context_catalog.json'
}
if ([string]::IsNullOrWhiteSpace($MaintenanceMapPath)) {
    $MaintenanceMapPath = Join-Path $IslandRoot 'contracts\mainline_maintenance_map.v1.json'
}

$ErrorActionPreference = 'Stop'
$script:Utf8 = [Text.UTF8Encoding]::new($false)
# Fullwidth colon after 版本 — same declaration line as the authority text / Python consumer.
$script:ToolGlueVersionPrefix = ([string][char]0x7248) + ([string][char]0x672C) + ([string][char]0xFF1A)

function Assert-SafeLeaf([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "MISSING_${Label}: $Path" }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "UNSAFE_${Label}: $Path"
    }
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Get-StringSha256([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([Convert]::ToHexString($sha.ComputeHash($script:Utf8.GetBytes($Value)))).ToUpperInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-ToolGlueConstitutionVersion([string]$Path) {
    Assert-SafeLeaf $Path 'TOOL_GLUE_CONSTITUTION'
    # BOM-tolerant UTF-8 read; same single "版本：" declaration the Python consumer parses.
    $text = Get-Content -LiteralPath $Path -Raw -Encoding utf8
    $versionLines = @(
        $text -split "`r?`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_.StartsWith($script:ToolGlueVersionPrefix) }
    )
    if ($versionLines.Count -ne 1) {
        throw "TOOL_GLUE_CONSTITUTION_VERSION_LINE_COUNT_INVALID: count=$($versionLines.Count)"
    }
    $version = $versionLines[0].Substring($script:ToolGlueVersionPrefix.Length).Trim()
    if ([string]::IsNullOrWhiteSpace($version)) {
        throw 'TOOL_GLUE_CONSTITUTION_VERSION_EMPTY'
    }
    return $version
}

function ConvertTo-NormalizedJson([object]$Value) {
    return ($Value | ConvertTo-Json -Depth 40)
}

function Write-AtomicJsonIfChanged([string]$Path, [object]$Value, [string]$TimestampPropertyPath) {
    $oldObject = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($TimestampPropertyPath -eq 'updated_at') {
        $Value.updated_at = $oldObject.updated_at
    }
    elseif ($TimestampPropertyPath -eq 'generated_state.updated_at') {
        $Value.generated_state.updated_at = $oldObject.generated_state.updated_at
    }
    elseif ($TimestampPropertyPath -eq 'generated_at') {
        $Value.generated_at = $oldObject.generated_at
    }
    $oldNormalized = ConvertTo-NormalizedJson $oldObject
    $candidateNormalized = ConvertTo-NormalizedJson $Value
    # Mtime fields are observability metadata, not semantic identity. Content hashes,
    # byte counts, availability, file sets, and tree hashes decide whether a rewrite
    # is needed; ignoring mtime-only churn also breaks the map<->catalog refresh cycle.
    $mtimePattern = '(?m)"updated_at"\s*:\s*(?:"[^"]*"|null)'
    $oldComparable = [regex]::Replace($oldNormalized, $mtimePattern, '"updated_at":"<mtime-ignored>"')
    $candidateComparable = [regex]::Replace($candidateNormalized, $mtimePattern, '"updated_at":"<mtime-ignored>"')
    if ($oldComparable -eq $candidateComparable) {
        return $false
    }
    $now = [DateTimeOffset]::UtcNow.ToString('o')
    if ($TimestampPropertyPath -eq 'updated_at') {
        $Value.updated_at = $now
    }
    elseif ($TimestampPropertyPath -eq 'generated_state.updated_at') {
        $Value.generated_state.updated_at = $now
    }
    elseif ($TimestampPropertyPath -eq 'generated_at') {
        $Value.generated_at = $now
    }
    $temporary = "$Path.$PID.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText($temporary, ((ConvertTo-NormalizedJson $Value) + [Environment]::NewLine), $script:Utf8)
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
    return $true
}

function Get-TreeSnapshot([object]$Collection) {
    $rootPath = [string]$Collection.path
    if (-not (Test-Path -LiteralPath $rootPath -PathType Container)) {
        return [ordered]@{
            available = $false
            file_count = 0
            tree_sha256 = $null
            files = @()
        }
    }
    $extensions = @($Collection.include_extensions | ForEach-Object { ([string]$_).ToLowerInvariant() })
    $excluded = @($Collection.exclude_relative_paths | ForEach-Object { ([string]$_).Replace('/', '\').ToLowerInvariant() })
    $items = if ([bool]$Collection.recursive) {
        @(Get-ChildItem -LiteralPath $rootPath -File -Recurse -Force)
    }
    else {
        @(Get-ChildItem -LiteralPath $rootPath -File -Force)
    }
    $files = [System.Collections.Generic.List[object]]::new()
    foreach ($item in $items) {
        $relative = [IO.Path]::GetRelativePath($rootPath, $item.FullName).Replace('/', '\')
        if ($extensions.Count -gt 0 -and $extensions -notcontains $item.Extension.ToLowerInvariant()) { continue }
        if ($excluded -contains $relative.ToLowerInvariant()) { continue }
        $files.Add([ordered]@{
            relative_path = $relative
            bytes = [int64]$item.Length
            updated_at = $item.LastWriteTimeUtc.ToString('o')
            sha256 = Get-Sha256 $item.FullName
        })
    }
    $orderedFiles = @($files | Sort-Object relative_path)
    $payload = (($orderedFiles | ForEach-Object { "$($_.relative_path)|$($_.bytes)|$($_.sha256)" }) -join "`n")
    return [ordered]@{
        available = $true
        file_count = $orderedFiles.Count
        tree_sha256 = Get-StringSha256 $payload
        files = $orderedFiles
    }
}

Assert-SafeLeaf $MaintenanceMapPath 'MAINTENANCE_MAP'
Assert-SafeLeaf $CatalogPath 'CONTEXT_CATALOG'

$map = Get-Content -LiteralPath $MaintenanceMapPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$map.schema_version -ne 'xinao.mainline_maintenance_map.v1' -or [string]$map.sentinel -ne 'SENTINEL:XINAO_MAINLINE_MAINTENANCE_MAP_V1') {
    throw 'INVALID_MAINTENANCE_MAP_SCHEMA_OR_SENTINEL'
}
if ([bool]$map.authority) { throw 'MAINTENANCE_MAP_MUST_BE_NON_AUTHORITY' }

function Get-RequiredMapSourcePath([string]$Id) {
    $matches = @($map.sources | Where-Object { [string]$_.id -eq $Id })
    if ($matches.Count -ne 1) { throw "MAP_SOURCE_ID_COUNT_INVALID: id=$Id count=$($matches.Count)" }
    $path = [string]$matches[0].path
    Assert-SafeLeaf $path ("MAP_SOURCE_" + $Id.ToUpperInvariant())
    return $path
}

# Refresh only mechanically derived bindings on rebuildable machine projections.
# Human authorities are read-only inputs and are never written by this script.
$scienceSpecPath = Get-RequiredMapSourcePath 'current_science_spec'
$legacyDomainSpecPath = Get-RequiredMapSourcePath 'legacy_domain_spec'
$admissionContractPath = Get-RequiredMapSourcePath 'legacy_foundation_admission_contract'
$backgroundContractPath = Get-RequiredMapSourcePath 'background_model_contract'
$scienceProjectionPath = Get-RequiredMapSourcePath 'current_science_projection'
$blueprintPath = Get-RequiredMapSourcePath 'legacy_machine_projection'
$archiveManifestPath = Get-RequiredMapSourcePath 'archive_relocation_manifest'
$scienceSpecHash = Get-Sha256 $scienceSpecPath
$legacyDomainSpecHash = Get-Sha256 $legacyDomainSpecPath
$admissionContractHash = Get-Sha256 $admissionContractPath
$backgroundContractHash = Get-Sha256 $backgroundContractPath
$toolGluePath = Get-RequiredMapSourcePath 'tool_glue_constitution'
$toolGlueHash = Get-Sha256 $toolGluePath
# Version and sha256 are derived from the same authority leaf — no second write surface.
$toolGlueVersion = Get-ToolGlueConstitutionVersion $toolGluePath
$toolGlueHashLower = $toolGlueHash.ToLowerInvariant()
if (-not [string]::IsNullOrWhiteSpace($ExpectedSoftwareFoundationSha256)) {
    $expectedSha = $ExpectedSoftwareFoundationSha256.Trim().ToLowerInvariant()
    if ($expectedSha -cne $toolGlueHashLower) {
        throw "TOOL_GLUE_CONSTITUTION_SHA256_PIN_MISMATCH: expected=$expectedSha observed=$toolGlueHashLower"
    }
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedSoftwareFoundationVersion)) {
    $expectedVersion = $ExpectedSoftwareFoundationVersion.Trim()
    if ($expectedVersion -cne $toolGlueVersion) {
        throw "TOOL_GLUE_CONSTITUTION_VERSION_PIN_MISMATCH: expected=$expectedVersion observed=$toolGlueVersion"
    }
}

$scienceProjection = Get-Content -LiteralPath $scienceProjectionPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    [string]$scienceProjection.schema_version -ne 'xinao.science_active_parent_projection.v1' -or
    [string]$scienceProjection.sentinel -ne 'SENTINEL:XINAO_SCIENCE_ACTIVE_PARENT_PROJECTION_V1' -or
    [bool]$scienceProjection.authority -or
    [bool]$scienceProjection.completion_claim_allowed
) { throw 'SCIENCE_ACTIVE_PARENT_PROJECTION_INVALID' }
$scienceProjection.active_parent.path = $scienceSpecPath
$scienceProjection.active_parent.sha256 = $scienceSpecHash.ToLowerInvariant()
$scienceProjection.stable_entry.sha256 = (Get-Sha256 (Get-RequiredMapSourcePath 'stable_mainline_entry')).ToLowerInvariant()
$scienceProjection.software_foundation.path = $toolGluePath
$scienceProjection.software_foundation.sha256 = $toolGlueHashLower
# PSCustomObject from ConvertFrom-Json does not auto-create missing note properties.
$scienceProjection.software_foundation |
    Add-Member -NotePropertyName version -NotePropertyValue $toolGlueVersion -Force
$scienceProjection.background_contract.path = $backgroundContractPath
$scienceProjection.background_contract.sha256 = $backgroundContractHash.ToLowerInvariant()
$scienceProjection.legacy_parent.path = $legacyDomainSpecPath
$scienceProjection.legacy_parent.sha256 = $legacyDomainSpecHash.ToLowerInvariant()
$scienceProjection.legacy_admission_contract.path = $admissionContractPath
$scienceProjection.legacy_admission_contract.sha256 = $admissionContractHash.ToLowerInvariant()
$scienceProjectionChanged = Write-AtomicJsonIfChanged $scienceProjectionPath $scienceProjection 'generated_at'

$blueprint = Get-Content -LiteralPath $blueprintPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$blueprint.authority.projection_is_not_authority) { throw 'BLUEPRINT_MUST_BE_NON_AUTHORITY' }
$blueprint.authority.human_spec = $legacyDomainSpecPath
$blueprint.authority.human_spec_sha256 = $legacyDomainSpecHash.ToLowerInvariant()
$blueprint.authority.formal_admission_contract = $admissionContractPath
$blueprint.authority.formal_admission_contract_sha256 = $admissionContractHash.ToLowerInvariant()
$blueprint.gates.normative_contract_sha256 = $admissionContractHash.ToLowerInvariant()
if (-not [string]::IsNullOrWhiteSpace($FoundationImplementationProjectionJson)) {
    throw 'FOUNDATION_IMPLEMENTATION_PROJECTION_OVERRIDE_RETIRED_USE_HASH_BOUND_PROMOTER'
}
$foundationGenerationPresent = $null -ne $blueprint.authority.foundation_generation
$sourcePromotionPending = -not $foundationGenerationPresent
if ($foundationGenerationPresent) {
    $generationRef = $blueprint.authority.foundation_generation
    $generationManifestPath = [string]$generationRef.manifest_path
    Assert-SafeLeaf $generationManifestPath 'FOUNDATION_GENERATION_MANIFEST'
    $manifestHash = Get-Sha256 $generationManifestPath
    if ($manifestHash -ne ([string]$generationRef.manifest_sha256).ToUpperInvariant()) {
        throw 'FOUNDATION_GENERATION_MANIFEST_HASH_MISMATCH'
    }
    $generationManifest = Get-Content -LiteralPath $generationManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        [string]$generationManifest.schema_version -ne 'xinao.foundation_authority_generation.v1' -or
        [string]$generationManifest.content_sha256 -ne [string]$generationRef.generation_content_sha256 -or
        (Split-Path -Leaf (Split-Path -Parent $generationManifestPath)) -ne [string]$generationManifest.content_sha256
    ) {
        throw 'FOUNDATION_GENERATION_IDENTITY_INVALID'
    }
    $sourcePromotionPending = (
        [string]$generationManifest.materials.human_spec_snapshot.sha256 -ne $legacyDomainSpecHash.ToLowerInvariant() -or
        [string]$generationManifest.materials.formal_contract_snapshot.sha256 -ne $admissionContractHash.ToLowerInvariant()
    )
}
$blueprintChanged = Write-AtomicJsonIfChanged $blueprintPath $blueprint ''

$sourceManifestPath = Join-Path (Split-Path -Parent $blueprintPath) 'source_manifest.json'
Assert-SafeLeaf $sourceManifestPath 'SOURCE_MANIFEST'
$sourceManifest = Get-Content -LiteralPath $sourceManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -eq $sourceManifest.superseded_auxiliary_contract) { throw 'SOURCE_MANIFEST_REPLACEMENT_BINDING_MISSING' }
$sourceManifest.superseded_auxiliary_contract.replacement_path = $admissionContractPath
$sourceManifest.superseded_auxiliary_contract.replacement_sha256 = $admissionContractHash.ToLowerInvariant()
$sourceManifestChanged = Write-AtomicJsonIfChanged $sourceManifestPath $sourceManifest ''

$archiveManifest = Get-Content -LiteralPath $archiveManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -eq $archiveManifest.current_publication) { throw 'ARCHIVE_MANIFEST_CURRENT_PUBLICATION_MISSING' }
$snapshotPath = [string]$archiveManifest.current_publication.versioned_snapshot_path
Assert-SafeLeaf $snapshotPath 'CURRENT_SPEC_SNAPSHOT'
$snapshotHash = Get-Sha256 $snapshotPath
if (
    $snapshotHash -ne ([string]$archiveManifest.current_publication.versioned_snapshot_sha256).ToUpperInvariant() -or
    $snapshotHash -ne ([string]$archiveManifest.current_publication.stable_spec_sha256).ToUpperInvariant() -or
    $snapshotHash -ne $scienceSpecHash -or
    [string]$archiveManifest.current_publication.stable_spec_path -ne $scienceSpecPath -or
    [string]$archiveManifest.current_publication.background_contract_sha256 -ne $backgroundContractHash.ToLowerInvariant()
) { throw 'CURRENT_PUBLICATION_SNAPSHOT_IDENTITY_INVALID' }
$archiveManifestChanged = $false

# Module operational notes are a non-authoritative, file-backed discovery layer. Cards remain
# separate from rules, runtime state, and evidence; this index only makes them discoverable.
$moduleNotesRoot = Join-Path $IslandRoot 'state\module_operational_notes'
$moduleCardsRoot = Join-Path $moduleNotesRoot 'cards'
$moduleIndexPath = Join-Path $moduleNotesRoot 'index.v1.json'
$moduleSchemaPath = Join-Path $IslandRoot 'contracts\module_operational_note.v1.schema.json'
Assert-SafeLeaf $moduleSchemaPath 'MODULE_OPERATIONAL_NOTE_SCHEMA'
Assert-SafeLeaf $moduleIndexPath 'MODULE_OPERATIONAL_NOTES_INDEX'
if (-not (Test-Path -LiteralPath $moduleCardsRoot -PathType Container)) {
    throw "MODULE_OPERATIONAL_NOTES_CARDS_ROOT_MISSING: $moduleCardsRoot"
}
$moduleCardRecords = [System.Collections.Generic.List[object]]::new()
$moduleIds = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($cardFile in @(Get-ChildItem -LiteralPath $moduleCardsRoot -File -Filter '*.json' -Force | Sort-Object Name)) {
    if ($cardFile.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "UNSAFE_MODULE_OPERATIONAL_NOTE_REPARSE_POINT: $($cardFile.FullName)"
    }
    $card = Get-Content -LiteralPath $cardFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        [string]$card.schema_version -ne 'xinao.module_operational_note.v1' -or
        [string]$card.sentinel -ne 'SENTINEL:XINAO_MODULE_OPERATIONAL_NOTE_V1' -or
        [string]::IsNullOrWhiteSpace([string]$card.module_id) -or
        [string]::IsNullOrWhiteSpace([string]$card.title) -or
        [string]::IsNullOrWhiteSpace([string]$card.summary) -or
        @($card.capabilities).Count -lt 1 -or
        @($card.binding_refs).Count -lt 1 -or
        $null -eq $card.recovery -or
        $null -eq $card.maintenance -or
        [string]$card.maintenance.secret_policy -ne 'credential_handle_paths_only_never_secret_values' -or
        [bool]$card.authority -or
        [bool]$card.completion_claim_allowed
    ) {
        throw "MODULE_OPERATIONAL_NOTE_CORE_CONTRACT_INVALID: $($cardFile.FullName)"
    }
    foreach ($verb in @('discover', 'diagnose', 'reproduce', 'degrade', 'restore', 'replace', 'retire')) {
        if (@($card.recovery.$verb).Count -lt 1) {
            throw "MODULE_OPERATIONAL_NOTE_RECOVERY_VERB_MISSING: module=$($card.module_id) verb=$verb"
        }
    }
    $forbiddenPropertyNames = @(
        $card.PSObject.Properties.Name
        $card.binding_refs | ForEach-Object { $_.PSObject.Properties.Name }
        $card.recovery.PSObject.Properties.Name
        $card.maintenance.PSObject.Properties.Name
        @($card.mature_baselines) | ForEach-Object { $_.PSObject.Properties.Name }
    ) | Where-Object { $_ -match '^(?i:api_?key|secret|token|password|credential_value|key_value)$' }
    if (@($forbiddenPropertyNames).Count -gt 0) {
        throw "MODULE_OPERATIONAL_NOTE_SECRET_VALUE_FIELD_FORBIDDEN: module=$($card.module_id) fields=$($forbiddenPropertyNames -join ',')"
    }
    if (-not $moduleIds.Add([string]$card.module_id)) {
        throw "MODULE_OPERATIONAL_NOTE_DUPLICATE_MODULE_ID: $($card.module_id)"
    }
    $moduleCardRecords.Add([ordered]@{
        module_id = [string]$card.module_id
        title = [string]$card.title
        summary = [string]$card.summary
        capabilities = @($card.capabilities)
        aliases = @($card.aliases)
        card_path = $cardFile.FullName
        bytes = [int64]$cardFile.Length
        sha256 = (Get-Sha256 $cardFile.FullName).ToLowerInvariant()
    })
}
$modulePayload = (($moduleCardRecords | ForEach-Object { "$($_.module_id)|$($_.bytes)|$($_.sha256)" }) -join "`n")
$moduleIndex = [ordered]@{
    schema_version = 'xinao.module_operational_notes_index.v1'
    sentinel = 'SENTINEL:XINAO_MODULE_OPERATIONAL_NOTES_INDEX_V1'
    generated_at = $null
    cards_root = $moduleCardsRoot
    card_count = $moduleCardRecords.Count
    cards_tree_sha256 = (Get-StringSha256 $modulePayload).ToLowerInvariant()
    cards = @($moduleCardRecords)
    authority = $false
    completion_claim_allowed = $false
}
$moduleIndexChanged = Write-AtomicJsonIfChanged $moduleIndexPath $moduleIndex 'generated_at'

foreach ($source in @($map.sources)) {
    $path = [string]$source.path
    $exists = Test-Path -LiteralPath $path -PathType Leaf
    $source | Add-Member -NotePropertyName available -NotePropertyValue $exists -Force
    if ($exists) {
        $item = Get-Item -LiteralPath $path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "UNSAFE_SOURCE_REPARSE_POINT: $path" }
        if ([string]$source.hash_policy -eq 'sha256') {
            $source | Add-Member -NotePropertyName bytes -NotePropertyValue ([int64]$item.Length) -Force
            $source | Add-Member -NotePropertyName updated_at -NotePropertyValue $item.LastWriteTimeUtc.ToString('o') -Force
            $source | Add-Member -NotePropertyName sha256 -NotePropertyValue (Get-Sha256 $path) -Force
        }
        else {
            $source.PSObject.Properties.Remove('bytes')
            $source.PSObject.Properties.Remove('updated_at')
            $source.PSObject.Properties.Remove('sha256')
        }
    }
    else {
        $source | Add-Member -NotePropertyName bytes -NotePropertyValue $null -Force
        $source | Add-Member -NotePropertyName updated_at -NotePropertyValue $null -Force
        $source.PSObject.Properties.Remove('sha256')
        if ([bool]$source.required) { throw "REQUIRED_SOURCE_MISSING: id=$($source.id) path=$path" }
    }
}

foreach ($collection in @($map.collections)) {
    $snapshot = Get-TreeSnapshot $collection
    $collection | Add-Member -NotePropertyName available -NotePropertyValue $snapshot.available -Force
    $collection | Add-Member -NotePropertyName file_count -NotePropertyValue $snapshot.file_count -Force
    $collection | Add-Member -NotePropertyName tree_sha256 -NotePropertyValue $snapshot.tree_sha256 -Force
    $collection | Add-Member -NotePropertyName files -NotePropertyValue $snapshot.files -Force
    if ([bool]$collection.required -and -not [bool]$snapshot.available) {
        throw "REQUIRED_COLLECTION_MISSING: id=$($collection.id) path=$($collection.path)"
    }
}
$map.generated_state.source_count = @($map.sources).Count
$map.generated_state.collection_count = @($map.collections).Count
$mapChanged = Write-AtomicJsonIfChanged $MaintenanceMapPath $map 'generated_state.updated_at'

$catalog = Get-Content -LiteralPath $CatalogPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    [string]$catalog.schema_version -ne 'xinao.codex_context_catalog.v3' -or
    [string]$catalog.sentinel -ne 'SENTINEL:XINAO_CODEX_CONTEXT_CATALOG_V3' -or
    [bool]$catalog.authority -or
    [bool]$catalog.completion_claim_allowed
) { throw 'CONTEXT_CATALOG_V3_CONTRACT_INVALID' }
$stableRouterPath = Get-RequiredMapSourcePath 'stable_mainline_entry'
$stableRouterText = Get-Content -LiteralPath $stableRouterPath -Raw -Encoding UTF8
$catalog.router_source.path = $stableRouterPath
$catalog.router_source.sha256 = (Get-Sha256 $stableRouterPath).ToLowerInvariant()
$seenModuleIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($entry in @($catalog.entries)) {
    $moduleId = [string]$entry.module_id
    $sourceId = [string]$entry.source_id
    if ([string]::IsNullOrWhiteSpace($moduleId) -or -not $seenModuleIds.Add($moduleId)) {
        throw "CONTEXT_CATALOG_MODULE_ID_INVALID_OR_DUPLICATE: $moduleId"
    }
    $moduleToken = ([string][char]96) + $moduleId + ([string][char]96)
    if (
        $moduleId -notin @('stable-router', 'maintenance-map') -and
        $stableRouterText -notmatch [regex]::Escape($moduleToken)
    ) {
        throw "CONTEXT_CATALOG_MODULE_NOT_DECLARED_BY_STABLE_ROUTER: $moduleId"
    }
    if (@($entry.keywords).Count -lt 1 -or [string]::IsNullOrWhiteSpace([string]$entry.read_policy)) {
        throw "CONTEXT_CATALOG_DISCOVERY_OR_READ_POLICY_MISSING: $moduleId"
    }
    if ($sourceId -eq 'maintenance_map_self') {
        $sourcePath = $MaintenanceMapPath
    }
    else {
        $sourceMatches = @($map.sources | Where-Object { [string]$_.id -eq $sourceId })
        if ($sourceMatches.Count -ne 1) {
            throw "CONTEXT_CATALOG_SOURCE_ID_COUNT_INVALID: module=$moduleId source_id=$sourceId count=$($sourceMatches.Count)"
        }
        $sourcePath = [string]$sourceMatches[0].path
    }
    $entry.source_path = $sourcePath
    $exists = Test-Path -LiteralPath $sourcePath -PathType Leaf
    $entry | Add-Member -NotePropertyName available -NotePropertyValue $exists -Force
    if ($exists) {
        $item = Get-Item -LiteralPath $sourcePath -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "UNSAFE_CATALOG_SOURCE: $sourcePath" }
        $entry | Add-Member -NotePropertyName bytes -NotePropertyValue ([int64]$item.Length) -Force
        $entry | Add-Member -NotePropertyName updated_at -NotePropertyValue $item.LastWriteTimeUtc.ToString('o') -Force
        $entry | Add-Member -NotePropertyName sha256 -NotePropertyValue (Get-Sha256 $sourcePath) -Force
    }
    else {
        $entry | Add-Member -NotePropertyName bytes -NotePropertyValue $null -Force
        $entry | Add-Member -NotePropertyName updated_at -NotePropertyValue $null -Force
        $entry | Add-Member -NotePropertyName sha256 -NotePropertyValue $null -Force
    }
}
$catalogChanged = Write-AtomicJsonIfChanged $CatalogPath $catalog 'updated_at'

[ordered]@{
    schema_version = 'xinao.mainline_projection_refresh.v1'
    refreshed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    maintenance_map = [ordered]@{
        path = $MaintenanceMapPath
        changed = $mapChanged
        sources = @($map.sources).Count
        collections = @($map.collections).Count
    }
    context_catalog = [ordered]@{
        path = $CatalogPath
        changed = $catalogChanged
        entries = @($catalog.entries).Count
        available = @($catalog.entries | Where-Object available).Count
    }
    projection_bindings = [ordered]@{
        blueprint_changed = $blueprintChanged
        foundation_projection_override_retired = $true
        foundation_generation_present = $foundationGenerationPresent
        source_promotion_pending = $sourcePromotionPending
        source_manifest_changed = $sourceManifestChanged
        archive_manifest_changed = $archiveManifestChanged
        current_science_projection_changed = $scienceProjectionChanged
        science_spec_sha256 = $scienceSpecHash
        legacy_domain_spec_sha256 = $legacyDomainSpecHash
        legacy_admission_contract_sha256 = $admissionContractHash
        module_operational_notes_index_changed = $moduleIndexChanged
        module_operational_notes_card_count = $moduleCardRecords.Count
        software_foundation_path = $toolGluePath
        software_foundation_sha256 = $toolGlueHashLower
        software_foundation_version = $toolGlueVersion
    }
    authority_text_mutated = $false
} | ConvertTo-Json -Depth 8 -Compress
exit 0
