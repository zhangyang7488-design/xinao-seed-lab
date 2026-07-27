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

function Write-TestCatalog([DateTimeOffset]$FetchedAt) {
    $catalog = [ordered]@{
        origin = "https://cli-chat-proxy.grok.com/v1/models"
        fetched_at = $FetchedAt.ToString("o")
        grok_version = "0.2.112"
        auth_method = "session"
        models = [ordered]@{ "grok-4.5" = [ordered]@{} }
    }
    $temporary = $catalogPath + "." + [guid]::NewGuid().ToString("N") + ".tmp"
    [IO.File]::WriteAllText(
        $temporary,
        ($catalog | ConvertTo-Json -Depth 6 -Compress),
        $utf8
    )
    [IO.File]::Move($temporary, $catalogPath, $true)
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
$missingObject = Get-Content -LiteralPath $missingCatalog -Raw -Encoding UTF8 | ConvertFrom-Json
$missingObject.fetched_at = [DateTimeOffset]::UtcNow.AddMinutes(-10).ToString("o")
[IO.File]::WriteAllText(
    $missingCatalog,
    ($missingObject | ConvertTo-Json -Depth 6 -Compress),
    $utf8
)
$missingRejected = $false
try {
    $null = Invoke-GrokAuthenticatedCatalogSingleFlight `
        -GrokHome $missingProfile -Model "grok-4.5" -TtlSeconds 300 `
        -RefreshAction { [pscustomobject]@{ exit_code = 0 } }
}
catch {
    $missingRejected = $_.Exception.Message -eq "GROK_AUTHENTICATED_PROFILE_AUTH_MISSING"
}
Assert-Contract $missingRejected "missing_auth_fails_closed"

[ordered]@{
    status = "verified"
    sequential_refresh_count = 1
    concurrent_workers = 4
    concurrent_refresh_count = 1
    missing_auth_rejected = $missingRejected
} | ConvertTo-Json -Depth 4
