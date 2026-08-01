#Requires -Version 7.0
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$timeRuntime = Join-Path $PSScriptRoot "GrokAuthenticatedCatalogTime.ps1"
$refreshRuntime = Join-Path $PSScriptRoot "GrokAuthenticatedCatalogRefresh.ps1"
. $timeRuntime
. $refreshRuntime

function Assert-Contract([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "GROK_CATALOG_REFRESH_TEST_FAILED: $Name" }
}

$testRoot = Join-Path "D:\XINAO_RESEARCH_RUNTIME\tmp" (
    "grok-catalog-singleflight-" + (Get-Date -Format "yyyyMMddTHHmmss") + "-" +
    [guid]::NewGuid().ToString("N").Substring(0, 8)
)
$profile = Join-Path $testRoot "profile"
New-Item -ItemType Directory -Force -Path $profile | Out-Null
$utf8 = [Text.UTF8Encoding]::new($false)
$catalogPath = Join-Path $profile "models_cache.json"
$counterPath = Join-Path $testRoot "refresh-count.txt"
[IO.File]::WriteAllText((Join-Path $profile "auth.json"), '{"test":true}', $utf8)

function Write-TestCatalog(
    [DateTimeOffset]$FetchedAt,
    [string]$TargetCatalogPath = $catalogPath
) {
    $catalog = [ordered]@{
        origin = "https://cli-chat-proxy.grok.com/v1/models"
        fetched_at = $FetchedAt.ToString("o")
        grok_version = "0.2.112"
        auth_method = "session"
        models = [ordered]@{ "grok-4.5" = [ordered]@{} }
    }
    $temporary = $TargetCatalogPath + "." + [guid]::NewGuid().ToString("N") + ".tmp"
    [IO.File]::WriteAllText(
        $temporary,
        ($catalog | ConvertTo-Json -Depth 6 -Compress),
        $utf8
    )
    [IO.File]::Move($temporary, $TargetCatalogPath, $true)
}

Write-TestCatalog ([DateTimeOffset]::UtcNow.AddMinutes(-10))
$refreshAction = {
    [IO.File]::AppendAllText($counterPath, "refresh`n", $utf8)
    Write-TestCatalog ([DateTimeOffset]::UtcNow)
    [pscustomobject]@{ exit_code = 0; stdout = "grok-4.5"; stderr = "" }
}
$first = Invoke-GrokAuthenticatedCatalogSingleFlight `
    -GrokHome $profile -Model "grok-4.5" -TtlSeconds 300 -RefreshAction $refreshAction
$second = Invoke-GrokAuthenticatedCatalogSingleFlight `
    -GrokHome $profile -Model "grok-4.5" -TtlSeconds 300 -RefreshAction $refreshAction
Assert-Contract ($first.refresh_performed -eq $true) "stale_catalog_refreshed"
Assert-Contract ($second.refresh_performed -eq $false) "fresh_catalog_reused"
Assert-Contract (@(Get-Content -LiteralPath $counterPath).Count -eq 1) "sequential_single_refresh"

Write-TestCatalog ([DateTimeOffset]::UtcNow.AddMinutes(-10))
[IO.File]::WriteAllText($counterPath, "", $utf8)
$runnerPath = Join-Path $testRoot "concurrent-refresh-runner.ps1"
$runnerSource = @'
param(
    [string]$TimeRuntime,
    [string]$RefreshRuntime,
    [string]$Profile,
    [string]$CounterPath
)
$ErrorActionPreference = "Stop"
. $TimeRuntime
. $RefreshRuntime
$action = {
    [IO.File]::AppendAllText($CounterPath, "refresh`n", [Text.UTF8Encoding]::new($false))
    Start-Sleep -Milliseconds 250
    $catalogPath = Join-Path $Profile "models_cache.json"
    $catalog = [ordered]@{
        origin = "https://cli-chat-proxy.grok.com/v1/models"
        fetched_at = [DateTimeOffset]::UtcNow.ToString("o")
        grok_version = "0.2.112"
        auth_method = "session"
        models = [ordered]@{ "grok-4.5" = [ordered]@{} }
    }
    $temporary = $catalogPath + "." + [guid]::NewGuid().ToString("N") + ".tmp"
    [IO.File]::WriteAllText(
        $temporary,
        ($catalog | ConvertTo-Json -Depth 6 -Compress),
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::Move($temporary, $catalogPath, $true)
    [pscustomobject]@{ exit_code = 0; stdout = "grok-4.5"; stderr = "" }
}
$null = Invoke-GrokAuthenticatedCatalogSingleFlight `
    -GrokHome $Profile -Model "grok-4.5" -TtlSeconds 300 -RefreshAction $action
'@
[IO.File]::WriteAllText($runnerPath, $runnerSource, $utf8)
$pwsh = Get-Command pwsh.exe -ErrorAction Stop | Select-Object -ExpandProperty Source -First 1
$processes = @()
foreach ($index in 1..4) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $pwsh
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $runnerPath,
        $timeRuntime, $refreshRuntime, $profile, $counterPath
    )) {
        [void]$info.ArgumentList.Add($argument)
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    [void]$process.Start()
    $processes += $process
}
foreach ($process in $processes) {
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    Assert-Contract ($process.WaitForExit(30000)) "concurrent_refresh_timeout"
    $outText = $stdout.GetAwaiter().GetResult()
    $errText = $stderr.GetAwaiter().GetResult()
    Assert-Contract ($process.ExitCode -eq 0) "concurrent_refresh_exit:$outText|$errText"
}
Assert-Contract (@(Get-Content -LiteralPath $counterPath).Count -eq 1) "concurrent_single_refresh"

$missingProfile = Join-Path $testRoot "missing-auth-profile"
New-Item -ItemType Directory -Force -Path $missingProfile | Out-Null
$missingCatalog = Join-Path $missingProfile "models_cache.json"
Copy-Item -LiteralPath $catalogPath -Destination $missingCatalog
Write-TestCatalog -FetchedAt ([DateTimeOffset]::UtcNow) -TargetCatalogPath $missingCatalog
$missingRejected = $false
try {
    $null = Invoke-GrokAuthenticatedCatalogSingleFlight `
        -GrokHome $missingProfile -Model "grok-4.5" -TtlSeconds 300 `
        -RefreshAction { [pscustomobject]@{ exit_code = 0 } }
}
catch {
    $missingRejected = $_.Exception.Message -eq "GROK_AUTHENTICATED_PROFILE_AUTH_REQUIRED"
}
Assert-Contract $missingRejected "missing_auth_fails_closed"

$zeroAuthProfile = Join-Path $testRoot "zero-auth-profile"
New-Item -ItemType Directory -Force -Path $zeroAuthProfile | Out-Null
[IO.File]::WriteAllText((Join-Path $zeroAuthProfile "auth.json"), "", $utf8)
Write-TestCatalog `
    -FetchedAt ([DateTimeOffset]::UtcNow) `
    -TargetCatalogPath (Join-Path $zeroAuthProfile "models_cache.json")
$zeroAuthRejected = $false
try {
    $null = Invoke-GrokAuthenticatedCatalogSingleFlight `
        -GrokHome $zeroAuthProfile -Model "grok-4.5" -TtlSeconds 300 `
        -RefreshAction { [pscustomobject]@{ exit_code = 0 } }
}
catch {
    $zeroAuthRejected = $_.Exception.Message -eq "GROK_AUTHENTICATED_PROFILE_AUTH_REQUIRED"
}
Assert-Contract $zeroAuthRejected "zero_auth_fails_closed"

$removedAuthProfile = Join-Path $testRoot "removed-auth-during-refresh-profile"
New-Item -ItemType Directory -Force -Path $removedAuthProfile | Out-Null
$removedAuthPath = Join-Path $removedAuthProfile "auth.json"
[IO.File]::WriteAllText($removedAuthPath, '{"test":true}', $utf8)
Write-TestCatalog `
    -FetchedAt ([DateTimeOffset]::UtcNow.AddMinutes(-10)) `
    -TargetCatalogPath (Join-Path $removedAuthProfile "models_cache.json")
$removedAuthRejected = $false
try {
    $null = Invoke-GrokAuthenticatedCatalogSingleFlight `
        -GrokHome $removedAuthProfile -Model "grok-4.5" -TtlSeconds 300 `
        -RefreshAction {
            Remove-Item -LiteralPath $removedAuthPath -Force
            [pscustomobject]@{ exit_code = 0; stdout = "- grok-4.5"; stderr = "" }
        }
}
catch {
    $removedAuthRejected = $_.Exception.Message -eq "GROK_AUTHENTICATED_PROFILE_AUTH_REQUIRED"
}
Assert-Contract $removedAuthRejected "auth_removed_during_refresh_requires_reauth"

$revokedAuthProfile = Join-Path $testRoot "revoked-auth-profile"
New-Item -ItemType Directory -Force -Path $revokedAuthProfile | Out-Null
[IO.File]::WriteAllText((Join-Path $revokedAuthProfile "auth.json"), '{"test":true}', $utf8)
Write-TestCatalog `
    -FetchedAt ([DateTimeOffset]::UtcNow.AddMinutes(-10)) `
    -TargetCatalogPath (Join-Path $revokedAuthProfile "models_cache.json")
$revokedAuthRejected = $false
try {
    $null = Invoke-GrokAuthenticatedCatalogSingleFlight `
        -GrokHome $revokedAuthProfile -Model "grok-4.5" -TtlSeconds 300 `
        -RefreshAction {
            [pscustomobject]@{
                exit_code = 1
                stdout = ""
                stderr = "invalid_grant: RefreshTokenRejected"
            }
        }
}
catch {
    $revokedAuthRejected = $_.Exception.Message -eq "GROK_AUTHENTICATED_PROFILE_AUTH_REQUIRED"
}
Assert-Contract $revokedAuthRejected "revoked_auth_requires_reauth"

$commandFailureProfile = Join-Path $testRoot "command-failure-profile"
New-Item -ItemType Directory -Force -Path $commandFailureProfile | Out-Null
[IO.File]::WriteAllText((Join-Path $commandFailureProfile "auth.json"), '{"test":true}', $utf8)
Write-TestCatalog `
    -FetchedAt ([DateTimeOffset]::UtcNow.AddMinutes(-10)) `
    -TargetCatalogPath (Join-Path $commandFailureProfile "models_cache.json")
$commandFailureDistinguished = $false
try {
    $null = Invoke-GrokAuthenticatedCatalogSingleFlight `
        -GrokHome $commandFailureProfile -Model "grok-4.5" -TtlSeconds 300 `
        -RefreshAction {
            [pscustomobject]@{ exit_code = 17; stdout = ""; stderr = "network unavailable" }
        }
}
catch {
    $commandFailureDistinguished = (
        $_.Exception.Message -eq "GROK_AUTHENTICATED_MODEL_CATALOG_REFRESH_COMMAND_FAILED"
    )
}
Assert-Contract $commandFailureDistinguished "nonzero_refresh_with_auth_is_command_failure"

$staleAfterSuccessProfile = Join-Path $testRoot "stale-after-success-profile"
New-Item -ItemType Directory -Force -Path $staleAfterSuccessProfile | Out-Null
[IO.File]::WriteAllText((Join-Path $staleAfterSuccessProfile "auth.json"), '{"test":true}', $utf8)
Write-TestCatalog `
    -FetchedAt ([DateTimeOffset]::UtcNow.AddMinutes(-10)) `
    -TargetCatalogPath (Join-Path $staleAfterSuccessProfile "models_cache.json")
$staleAfterSuccessDistinguished = $false
try {
    $null = Invoke-GrokAuthenticatedCatalogSingleFlight `
        -GrokHome $staleAfterSuccessProfile -Model "grok-4.5" -TtlSeconds 300 `
        -RefreshAction { [pscustomobject]@{ exit_code = 0; stdout = "- grok-4.5"; stderr = "" } }
}
catch {
    $staleAfterSuccessDistinguished = (
        $_.Exception.Message -eq "GROK_AUTHENTICATED_MODEL_CATALOG_STALE"
    )
}
Assert-Contract $staleAfterSuccessDistinguished "successful_refresh_leaving_stale_catalog_is_stale"

$missingAfterSuccessProfile = Join-Path $testRoot "missing-after-success-profile"
New-Item -ItemType Directory -Force -Path $missingAfterSuccessProfile | Out-Null
[IO.File]::WriteAllText((Join-Path $missingAfterSuccessProfile "auth.json"), '{"test":true}', $utf8)
$missingAfterSuccessDistinguished = $false
try {
    $null = Invoke-GrokAuthenticatedCatalogSingleFlight `
        -GrokHome $missingAfterSuccessProfile -Model "grok-4.5" -TtlSeconds 300 `
        -RefreshAction { [pscustomobject]@{ exit_code = 0; stdout = "- grok-4.5"; stderr = "" } }
}
catch {
    $missingAfterSuccessDistinguished = (
        $_.Exception.Message -eq "GROK_AUTHENTICATED_MODEL_CATALOG_REFRESH_FAILED: catalog_missing"
    )
}
Assert-Contract $missingAfterSuccessDistinguished "successful_refresh_leaving_missing_catalog_is_refresh_failure"

[ordered]@{
    status = "verified"
    sequential_refresh_count = 1
    concurrent_workers = 4
    concurrent_refresh_count = 1
    missing_auth_rejected = $missingRejected
    zero_auth_rejected = $zeroAuthRejected
    removed_auth_rejected = $removedAuthRejected
    revoked_auth_rejected = $revokedAuthRejected
    command_failure_distinguished = $commandFailureDistinguished
    stale_after_success_distinguished = $staleAfterSuccessDistinguished
    missing_after_success_distinguished = $missingAfterSuccessDistinguished
} | ConvertTo-Json -Depth 4
