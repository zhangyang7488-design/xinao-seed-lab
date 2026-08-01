#Requires -Version 5.1

function Test-GrokAuthenticatedProfileAuthPresent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$GrokHome
    )

    try {
        $authPath = Join-Path $GrokHome "auth.json"
        if (-not (Test-Path -LiteralPath $authPath -PathType Leaf)) {
            return $false
        }
        return (Get-Item -LiteralPath $authPath -Force -ErrorAction Stop).Length -gt 0
    }
    catch {
        return $false
    }
}

function Test-GrokAuthenticatedCatalogRefreshResultAuthRequired {
    [CmdletBinding()]
    param(
        [AllowNull()]
        [object]$RefreshResult
    )

    if ($null -eq $RefreshResult) {
        return $false
    }

    $parts = [Collections.Generic.List[string]]::new()
    foreach ($name in @("auth_required", "failure_code", "error", "stdout", "stderr")) {
        $value = $null
        if ($RefreshResult -is [Collections.IDictionary] -and $RefreshResult.Contains($name)) {
            $value = $RefreshResult[$name]
        }
        elseif ($null -ne $RefreshResult.PSObject.Properties[$name]) {
            $value = $RefreshResult.$name
        }
        if ($name -eq "auth_required" -and $value -eq $true) {
            return $true
        }
        if ($null -ne $value) {
            $parts.Add([string]$value)
        }
    }

    $diagnostic = $parts -join "`n"
    return $diagnostic -match '(?i)(?:invalid_grant|RefreshTokenRejected|refresh[ _-]?token.{0,40}(?:expired|invalid|rejected|revoked)|(?:authentication|authorization|sign[ -]?in|login).{0,40}(?:required|expired|invalid|revoked)|(?:not|no longer)[ -]?authenticated|\bunauthorized\b|\b401\b)'
}

function Get-GrokAuthenticatedCatalogRefreshState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$GrokHome,
        [Parameter(Mandatory = $true)]
        [string]$Model,
        [Parameter(Mandatory = $true)]
        [double]$TtlSeconds
    )

    $catalogPath = Join-Path $GrokHome "models_cache.json"
    $state = [ordered]@{
        valid = $false
        reason = "catalog_missing"
        path = $catalogPath
        fetched_at = ""
        age_seconds = [double]::PositiveInfinity
        sha256 = ""
    }
    if (-not (Test-Path -LiteralPath $catalogPath -PathType Leaf)) {
        return [pscustomobject]$state
    }
    try {
        $catalog = Get-Content -LiteralPath $catalogPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
        $origin = [uri]$catalog.origin
        if ($origin.Scheme -ne "https" -or $origin.Host -ne "cli-chat-proxy.grok.com") {
            $state.reason = "catalog_origin_invalid"
            return [pscustomobject]$state
        }
        if ([string]$catalog.auth_method -ne "session") {
            $state.reason = "catalog_auth_method_invalid"
            return [pscustomobject]$state
        }
        if (@($catalog.models.PSObject.Properties.Name) -notcontains $Model) {
            $state.reason = "requested_model_absent"
            return [pscustomobject]$state
        }
        $fetchedAt = ConvertTo-GrokCatalogFetchedAtUtc $catalog.fetched_at
        $ageSeconds = ([DateTimeOffset]::UtcNow - $fetchedAt).TotalSeconds
        $state.fetched_at = $fetchedAt.ToString("o")
        $state.age_seconds = [math]::Round($ageSeconds, 3)
        $state.sha256 = (
            Get-FileHash -LiteralPath $catalogPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        if (-not (Test-GrokCatalogAgeWithinWindow `
            -AgeSeconds $ageSeconds `
            -TtlSeconds $TtlSeconds `
            -MaxFutureSkewSeconds 30)) {
            $state.reason = "catalog_stale"
            return [pscustomobject]$state
        }
        $state.valid = $true
        $state.reason = "fresh_authenticated_catalog"
        return [pscustomobject]$state
    }
    catch {
        $state.reason = "catalog_invalid"
        return [pscustomobject]$state
    }
}

function Invoke-GrokAuthenticatedCatalogSingleFlight {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$GrokHome,
        [Parameter(Mandatory = $true)]
        [string]$Model,
        [Parameter(Mandatory = $true)]
        [double]$TtlSeconds,
        [Parameter(Mandatory = $true)]
        [scriptblock]$RefreshAction,
        [ValidateRange(1, 300)]
        [int]$LockTimeoutSeconds = 60
    )

    $resolvedHome = [IO.Path]::GetFullPath($GrokHome)
    if (-not (Test-Path -LiteralPath $resolvedHome -PathType Container) -or
        -not (Test-GrokAuthenticatedProfileAuthPresent -GrokHome $resolvedHome)) {
        throw "GROK_AUTHENTICATED_PROFILE_AUTH_REQUIRED"
    }
    $lockPath = Join-Path $resolvedHome ".xinao-authenticated-catalog-refresh.lock"
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($LockTimeoutSeconds)
    $started = [DateTimeOffset]::UtcNow
    $lease = $null
    while ($null -eq $lease -and [DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            $lease = [IO.File]::Open(
                $lockPath,
                [IO.FileMode]::OpenOrCreate,
                [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None
            )
        }
        catch [IO.IOException] {
            Start-Sleep -Milliseconds 50
        }
    }
    if ($null -eq $lease) {
        throw "GROK_AUTHENTICATED_MODEL_CATALOG_REFRESH_LOCK_TIMEOUT"
    }

    try {
        if (-not (Test-GrokAuthenticatedProfileAuthPresent -GrokHome $resolvedHome)) {
            throw "GROK_AUTHENTICATED_PROFILE_AUTH_REQUIRED"
        }
        $before = Get-GrokAuthenticatedCatalogRefreshState `
            -GrokHome $resolvedHome -Model $Model -TtlSeconds $TtlSeconds
        $refreshPerformed = $false
        if (-not $before.valid) {
            $refreshResult = $null
            try {
                $refreshResult = & $RefreshAction
            }
            catch {
                if (-not (Test-GrokAuthenticatedProfileAuthPresent -GrokHome $resolvedHome) -or
                    (Test-GrokAuthenticatedCatalogRefreshResultAuthRequired -RefreshResult $_)) {
                    throw "GROK_AUTHENTICATED_PROFILE_AUTH_REQUIRED"
                }
                throw "GROK_AUTHENTICATED_MODEL_CATALOG_REFRESH_COMMAND_FAILED"
            }
            if (-not (Test-GrokAuthenticatedProfileAuthPresent -GrokHome $resolvedHome) -or
                (Test-GrokAuthenticatedCatalogRefreshResultAuthRequired -RefreshResult $refreshResult)) {
                throw "GROK_AUTHENTICATED_PROFILE_AUTH_REQUIRED"
            }
            if ($null -eq $refreshResult -or [int]$refreshResult.exit_code -ne 0) {
                throw "GROK_AUTHENTICATED_MODEL_CATALOG_REFRESH_COMMAND_FAILED"
            }
            $refreshPerformed = $true
        }

        $after = Get-GrokAuthenticatedCatalogRefreshState `
            -GrokHome $resolvedHome -Model $Model -TtlSeconds $TtlSeconds
        if (-not (Test-GrokAuthenticatedProfileAuthPresent -GrokHome $resolvedHome)) {
            throw "GROK_AUTHENTICATED_PROFILE_AUTH_REQUIRED"
        }
        if (-not $after.valid) {
            if ([string]$after.reason -eq "catalog_stale") {
                throw "GROK_AUTHENTICATED_MODEL_CATALOG_STALE"
            }
            throw "GROK_AUTHENTICATED_MODEL_CATALOG_REFRESH_FAILED: $($after.reason)"
        }
        return [pscustomobject][ordered]@{
            schema_version = "xinao.grok.authenticated_catalog_singleflight.v1"
            refresh_performed = $refreshPerformed
            initial_reason = [string]$before.reason
            final_reason = [string]$after.reason
            fetched_at = [string]$after.fetched_at
            age_seconds = [double]$after.age_seconds
            catalog_sha256 = [string]$after.sha256
            lock_wait_ms = [math]::Round(
                ([DateTimeOffset]::UtcNow - $started).TotalMilliseconds,
                3
            )
        }
    }
    finally {
        $lease.Dispose()
    }
}
