#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$helper = Join-Path $PSScriptRoot "GrokAuthenticatedCatalogTime.ps1"
. $helper

function Assert-Contract([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "CONTRACT_FAILED: $Name" }
}

$originalCulture = [Threading.Thread]::CurrentThread.CurrentCulture
try {
    [Threading.Thread]::CurrentThread.CurrentCulture =
        [Globalization.CultureInfo]::GetCultureInfo("de-DE")

    $zoneLess = ConvertTo-GrokCatalogFetchedAtUtc "07/17/2026 19:39:45"
    $zulu = ConvertTo-GrokCatalogFetchedAtUtc "2026-07-17T19:39:45Z"
    $offset = ConvertTo-GrokCatalogFetchedAtUtc "2026-07-17T21:39:45+02:00"
}
finally {
    [Threading.Thread]::CurrentThread.CurrentCulture = $originalCulture
}

$expected = [DateTimeOffset]::Parse(
    "2026-07-17T19:39:45Z",
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::RoundtripKind
)
Assert-Contract ($zoneLess -eq $expected) "zone_less_cli_timestamp_is_utc"
Assert-Contract ($zoneLess.Offset -eq [TimeSpan]::Zero) "zone_less_result_offset_is_zero"
Assert-Contract ($zulu -eq $expected) "zulu_timestamp_preserved"
Assert-Contract ($offset -eq $expected) "explicit_offset_preserved"

$now = [DateTimeOffset]::Parse("2026-07-17T19:46:33Z")
$ageSeconds = ($now - $zoneLess).TotalSeconds
Assert-Contract ($ageSeconds -eq 408) "fresh_cli_catalog_age"
Assert-Contract (Test-GrokCatalogAgeWithinWindow -AgeSeconds -17 -TtlSeconds 300) "future_within_skew_admitted"
Assert-Contract (Test-GrokCatalogAgeWithinWindow -AgeSeconds -30 -TtlSeconds 300) "future_skew_boundary_admitted"
Assert-Contract (-not (Test-GrokCatalogAgeWithinWindow -AgeSeconds -30.001 -TtlSeconds 300)) "future_beyond_skew_rejected"
Assert-Contract (Test-GrokCatalogAgeWithinWindow -AgeSeconds 300 -TtlSeconds 300) "ttl_boundary_admitted"
Assert-Contract (-not (Test-GrokCatalogAgeWithinWindow -AgeSeconds 300.001 -TtlSeconds 300)) "age_beyond_ttl_rejected"
Assert-Contract (-not (Test-GrokCatalogAgeWithinWindow -AgeSeconds ([double]::PositiveInfinity) -TtlSeconds 300)) "infinite_age_rejected"
Assert-Contract (-not (Test-GrokCatalogAgeWithinWindow -AgeSeconds ([double]::NaN) -TtlSeconds 300)) "nan_age_rejected"

$invalidRejected = $false
try { $null = ConvertTo-GrokCatalogFetchedAtUtc "not-a-time" }
catch {
    $invalidRejected = $_.Exception.Message -match
        "GROK_AUTHENTICATED_MODEL_CATALOG_FETCHED_AT_INVALID"
}
Assert-Contract $invalidRejected "invalid_timestamp_fails_closed"

[ordered]@{
    status = "verified"
    zone_less_utc = $zoneLess.ToString("o")
    explicit_z_utc = $zulu.ToString("o")
    explicit_offset_utc = $offset.ToString("o")
    fixed_age_seconds = $ageSeconds
    freshness_boundaries = "-30<=age<=300"
    invalid_rejected = $invalidRejected
} | ConvertTo-Json -Depth 3
