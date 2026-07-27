#Requires -Version 5.1

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
        $before = Get-GrokAuthenticatedCatalogRefreshState `
            -GrokHome $resolvedHome -Model $Model -TtlSeconds $TtlSeconds
        $refreshPerformed = $false
        if (-not $before.valid) {
            $authPath = Join-Path $resolvedHome "auth.json"
            if (-not (Test-Path -LiteralPath $authPath -PathType Leaf) -or
                (Get-Item -LiteralPath $authPath -Force).Length -le 0) {
                throw "GROK_AUTHENTICATED_PROFILE_AUTH_MISSING"
            }
            $refreshResult = & $RefreshAction
            if ($null -eq $refreshResult -or [int]$refreshResult.exit_code -ne 0) {
                throw "GROK_AUTHENTICATED_MODEL_CATALOG_REFRESH_COMMAND_FAILED"
            }
            $refreshPerformed = $true
        }

        $after = Get-GrokAuthenticatedCatalogRefreshState `
            -GrokHome $resolvedHome -Model $Model -TtlSeconds $TtlSeconds
        if (-not $after.valid) {
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
