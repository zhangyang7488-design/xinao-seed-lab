#Requires -Version 5.1

$script:GrokWorkerSelectionReceiptSchema = "xinao.supervisor_worker_decision_receipt.v1"
$script:GrokWorkerSelectionProvider = "grok_acpx_headless"
$script:GrokWorkerSelectionProfile = "grok.com.cached_profile"
$script:GrokWorkerSelectionTransport = "direct-grok-worker-pool"

function ConvertTo-GrokJsonStringLiteral {
    param([AllowEmptyString()][string]$Value)

    $builder = New-Object Text.StringBuilder
    [void]$builder.Append('"')
    foreach ($char in $Value.ToCharArray()) {
        $code = [int]$char
        $escape = switch ($code) {
            8 { '\b' }
            9 { '\t' }
            10 { '\n' }
            12 { '\f' }
            13 { '\r' }
            34 { '\"' }
            92 { '\\' }
            default { $null }
        }
        if ($null -ne $escape) {
            [void]$builder.Append([string]$escape)
            continue
        }
        if ($code -lt 32) {
            [void]$builder.Append(('\u{0:x4}' -f $code))
        }
        else {
            [void]$builder.Append($char)
        }
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function ConvertTo-GrokCanonicalJson {
    param([AllowNull()][object]$Value)

    if ($null -eq $Value) { return "null" }
    if ($Value -is [string] -or $Value -is [char]) {
        return ConvertTo-GrokJsonStringLiteral ([string]$Value)
    }
    if ($Value -is [bool]) {
        if ([bool]$Value) { return "true" }
        return "false"
    }
    if ($Value -is [Collections.IDictionary]) {
        $parts = [Collections.Generic.List[string]]::new()
        $keys = @($Value.Keys | ForEach-Object { [string]$_ } | Sort-Object)
        foreach ($key in $keys) {
            $parts.Add(
                (ConvertTo-GrokJsonStringLiteral $key) + ":" +
                (ConvertTo-GrokCanonicalJson $Value[$key])
            )
        }
        return "{" + [string]::Join(",", $parts.ToArray()) + "}"
    }
    if ($Value -is [pscustomobject]) {
        $parts = [Collections.Generic.List[string]]::new()
        $properties = @($Value.PSObject.Properties | Sort-Object Name)
        foreach ($property in $properties) {
            $parts.Add(
                (ConvertTo-GrokJsonStringLiteral ([string]$property.Name)) + ":" +
                (ConvertTo-GrokCanonicalJson $property.Value)
            )
        }
        return "{" + [string]::Join(",", $parts.ToArray()) + "}"
    }
    if ($Value -is [Collections.IEnumerable]) {
        $parts = [Collections.Generic.List[string]]::new()
        foreach ($item in $Value) {
            $parts.Add((ConvertTo-GrokCanonicalJson $item))
        }
        return "[" + [string]::Join(",", $parts.ToArray()) + "]"
    }
    if ($Value -is [single] -or $Value -is [double]) {
        $number = ([IFormattable]$Value).ToString("R", [Globalization.CultureInfo]::InvariantCulture)
        if ($number -match '^(NaN|Infinity|-Infinity)$') {
            throw "GROK_SELECTION_NON_JSON_NUMBER"
        }
        if ($number -notmatch '[.eE]') {
            $number += ".0"
        }
        return $number.ToLowerInvariant()
    }
    if (
        $Value -is [byte] -or $Value -is [sbyte] -or
        $Value -is [int16] -or $Value -is [uint16] -or
        $Value -is [int32] -or $Value -is [uint32] -or
        $Value -is [int64] -or $Value -is [uint64] -or
        $Value -is [decimal]
    ) {
        $number = ([IFormattable]$Value).ToString($null, [Globalization.CultureInfo]::InvariantCulture)
        return $number
    }
    throw "GROK_SELECTION_UNSUPPORTED_JSON_VALUE: $($Value.GetType().FullName)"
}

function Get-GrokUtf8Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Text)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Read-GrokWorkerSelectionReceipt {
    [CmdletBinding()]
    param(
        [string]$SelectionPath = "",
        [string]$Model = "",
        [string]$Cwd = "",
        [string]$RequiredPrefix = "GROK_WORKER_POOL"
    )

    if ([string]::IsNullOrWhiteSpace($SelectionPath)) {
        throw ($RequiredPrefix + "_SELECTIONPATH_REQUIRED")
    }
    if ([string]::IsNullOrWhiteSpace($Model)) {
        throw ($RequiredPrefix + "_MODEL_REQUIRED")
    }
    if ([string]::IsNullOrWhiteSpace($Cwd)) {
        throw ($RequiredPrefix + "_CWD_REQUIRED")
    }

    try { $resolvedSelectionPath = [IO.Path]::GetFullPath($SelectionPath) }
    catch { throw "GROK_SELECTION_PATH_INVALID: $SelectionPath" }
    if (-not (Test-Path -LiteralPath $resolvedSelectionPath -PathType Leaf)) {
        throw "GROK_SELECTION_PATH_MISSING: $resolvedSelectionPath"
    }
    try { $resolvedCwd = [IO.Path]::GetFullPath($Cwd) }
    catch { throw "GROK_SELECTION_CWD_INVALID: $Cwd" }
    if (-not (Test-Path -LiteralPath $resolvedCwd -PathType Container)) {
        throw "GROK_SELECTION_CWD_MISSING: $resolvedCwd"
    }

    try {
        $strictUtf8 = New-Object Text.UTF8Encoding $false, $true
        $json = [IO.File]::ReadAllText($resolvedSelectionPath, $strictUtf8)
    }
    catch {
        throw "GROK_SELECTION_RECEIPT_INVALID_UTF8: $resolvedSelectionPath"
    }
    try {
        $convertFromJson = Get-Command ConvertFrom-Json -ErrorAction Stop
        if ($convertFromJson.Parameters.ContainsKey("DateKind")) {
            $receipt = $json | ConvertFrom-Json -DateKind String -ErrorAction Stop
        }
        else {
            $receipt = $json | ConvertFrom-Json -ErrorAction Stop
        }
    }
    catch { throw "GROK_SELECTION_RECEIPT_INVALID_JSON: $resolvedSelectionPath" }
    if ($null -eq $receipt -or $receipt -isnot [pscustomobject]) {
        throw "GROK_SELECTION_RECEIPT_TOP_LEVEL_NOT_OBJECT"
    }
    if (-not [string]::Equals(
        [string]$receipt.schema_version,
        $script:GrokWorkerSelectionReceiptSchema,
        [StringComparison]::Ordinal
    )) {
        throw "GROK_SELECTION_RECEIPT_SCHEMA_MISMATCH"
    }
    if (-not [string]::Equals([string]$receipt.decision, "selected", [StringComparison]::Ordinal)) {
        throw "GROK_SELECTION_DECISION_NOT_SELECTED"
    }

    $claimedHash = [string]$receipt.decision_sha256
    if ($claimedHash -notmatch '^[0-9a-f]{64}$') {
        throw "GROK_SELECTION_DECISION_HASH_INVALID"
    }
    $basis = [ordered]@{}
    foreach ($property in $receipt.PSObject.Properties) {
        if ($property.Name -ne "decision_sha256") {
            $basis[$property.Name] = $property.Value
        }
    }
    $canonical = ConvertTo-GrokCanonicalJson $basis
    $observedHash = Get-GrokUtf8Sha256Hex $canonical
    if (-not [string]::Equals($claimedHash, $observedHash, [StringComparison]::Ordinal)) {
        throw "GROK_SELECTION_DECISION_HASH_MISMATCH: claimed=$claimedHash observed=$observedHash"
    }

    $selected = $receipt.selected_candidate
    if ($null -eq $selected -or $selected -isnot [pscustomobject]) {
        throw "GROK_SELECTION_SELECTED_CANDIDATE_MISSING"
    }
    if (-not [string]::Equals(
        [string]$selected.provider_id,
        $script:GrokWorkerSelectionProvider,
        [StringComparison]::Ordinal
    )) {
        throw "GROK_SELECTION_PROVIDER_MISMATCH"
    }
    if (-not [string]::Equals(
        [string]$selected.profile_ref,
        $script:GrokWorkerSelectionProfile,
        [StringComparison]::Ordinal
    )) {
        throw "GROK_SELECTION_PROFILE_MISMATCH"
    }
    if (-not [string]::Equals(
        [string]$selected.transport_id,
        $script:GrokWorkerSelectionTransport,
        [StringComparison]::Ordinal
    )) {
        throw "GROK_SELECTION_TRANSPORT_MISMATCH"
    }
    $requestedModel = $Model.Trim()
    if (-not [string]::Equals(
        [string]$selected.model_id,
        $requestedModel,
        [StringComparison]::Ordinal
    )) {
        throw "GROK_SELECTION_MODEL_MISMATCH: selected=$($selected.model_id) requested=$requestedModel"
    }
    foreach ($fact in @("declared_active", "healthy", "positive_benefit")) {
        if ($selected.$fact -ne $true) {
            throw "GROK_SELECTION_SELECTED_CANDIDATE_NOT_ELIGIBLE: $fact"
        }
    }

    return [pscustomobject]@{
        selection_path = $resolvedSelectionPath
        decision_sha256 = $claimedHash
        provider_id = [string]$selected.provider_id
        profile_ref = [string]$selected.profile_ref
        model_id = $requestedModel
        transport_id = [string]$selected.transport_id
        cwd = $resolvedCwd
        receipt = $receipt
    }
}
