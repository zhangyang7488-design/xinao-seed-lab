#Requires -Version 5.1

function ConvertTo-GrokCatalogFetchedAtUtc {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    $raw = $Value.Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "GROK_AUTHENTICATED_MODEL_CATALOG_FETCHED_AT_INVALID"
    }

    $parsed = [DateTimeOffset]::MinValue
    $styles = [Globalization.DateTimeStyles]::AllowWhiteSpaces
    $hasExplicitOffset = $raw -match '(?i)(?:Z|[+-]\d{2}:?\d{2})$'
    if (-not $hasExplicitOffset) {
        # Grok CLI 0.2.103 writes authenticated catalog timestamps as UTC
        # clock values without a zone suffix. Never reinterpret those values
        # through the host's local timezone.
        $styles = $styles -bor [Globalization.DateTimeStyles]::AssumeUniversal
        $styles = $styles -bor [Globalization.DateTimeStyles]::AdjustToUniversal
    }

    $parsedOk = [DateTimeOffset]::TryParse(
        $raw,
        [Globalization.CultureInfo]::InvariantCulture,
        $styles,
        [ref]$parsed
    )
    if (-not $parsedOk) {
        throw "GROK_AUTHENTICATED_MODEL_CATALOG_FETCHED_AT_INVALID: $Value"
    }
    return $parsed.ToUniversalTime()
}

function Test-GrokCatalogAgeWithinWindow {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [double]$AgeSeconds,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, [double]::MaxValue)]
        [double]$TtlSeconds,
        [ValidateRange(0, [double]::MaxValue)]
        [double]$MaxFutureSkewSeconds = 30
    )

    if ([double]::IsNaN($AgeSeconds) -or [double]::IsInfinity($AgeSeconds)) {
        return $false
    }
    return (
        $AgeSeconds -ge (-1 * $MaxFutureSkewSeconds) -and
        $AgeSeconds -le $TtlSeconds
    )
}
