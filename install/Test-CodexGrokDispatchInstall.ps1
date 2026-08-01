#Requires -Version 7.0

$ErrorActionPreference = "Stop"
function Assert-Contract([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "CODEX_GROK_INSTALL_TEST_FAILED: $Name" }
}
function Get-Sha256Lower([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$installer = Join-Path $PSScriptRoot "Install-CodexGrokDispatch.ps1"
$testRoot = Join-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_install_tests" ("install-" + [guid]::NewGuid().ToString("N"))
$runtimeRoot = Join-Path $testRoot "runtime"
$targetBridge = Join-Path $testRoot "bridge"
$targetLauncher = Join-Path $testRoot "launcher\Invoke-Codex-GrokWorkerPool.ps1"
$authProfile = Join-Path $testRoot "profile"
$runtimeFiles = @(
    "GrokAuthenticatedCatalogTime.ps1",
    "GrokAuthenticatedCatalogRefresh.ps1",
    "Invoke-CodexDispatchGrokWorkerPool.ps1",
    "Invoke-GrokComposer25Worker.ps1"
)
$utf8 = [Text.UTF8Encoding]::new($false)
try {
    New-Item -ItemType Directory -Path $runtimeRoot, $targetBridge, (Split-Path -Parent $targetLauncher), $authProfile -Force | Out-Null
    $previousHashes = [ordered]@{}
    foreach ($relative in $runtimeFiles) {
        $target = Join-Path $targetBridge $relative
        [IO.File]::WriteAllText($target, ("previous::" + $relative), $utf8)
        $previousHashes[$relative] = Get-Sha256Lower $target
    }
    [IO.File]::WriteAllText($targetLauncher, "previous::launcher", $utf8)
    [IO.File]::WriteAllText((Join-Path $authProfile "auth.json"), "{}", $utf8)

    $output = @(& $installer -SourceRoot $repoRoot -RuntimeRoot $runtimeRoot -TargetLauncher $targetLauncher -TargetBridgeRoot $targetBridge -AuthProfileRoot $authProfile)
    $receipt = ($output -join "`n") | ConvertFrom-Json -ErrorAction Stop
    Assert-Contract ([string]$receipt.schema_version -eq "xinao.codex_grok_dispatch_install_receipt.v2") "receipt_schema"
    Assert-Contract ([bool]$receipt.auth_present -and [string]$receipt.auth_state -eq "present_nonempty") "auth_readiness"
    Assert-Contract (-not [bool]$receipt.auth_bytes_read -and -not [bool]$receipt.auth_copied_or_backed_up) "auth_secret_untouched"
    Assert-Contract ([string]$receipt.exact_prior_reuse_policy -match "zero_refresh_zero_worker_zero_tokens") "prior_reuse_policy"
    Assert-Contract (@($receipt.install_items).Count -eq 5) "install_item_count"
    foreach ($relative in $runtimeFiles) {
        $source = Join-Path $repoRoot ("grok-admin-bridge\" + $relative)
        $target = Join-Path $targetBridge $relative
        Assert-Contract ((Get-Sha256Lower $target) -eq (Get-Sha256Lower $source)) ("runtime_readback:" + $relative)
        $item = @($receipt.install_items | Where-Object relative_ref -eq $relative)
        Assert-Contract ($item.Count -eq 1 -and [string]$item[0].previous_sha256 -eq [string]$previousHashes[$relative]) ("recoverable_previous:" + $relative)
        Assert-Contract (Test-Path -LiteralPath ([string]$item[0].rollback_ref) -PathType Leaf) ("backup_present:" + $relative)
    }
    Assert-Contract (Test-Path -LiteralPath ([string]$receipt.release_pointer_ref) -PathType Leaf) "pointer_present"
    [ordered]@{
        status = "verified"
        runtime_readback = $true
        previous_bytes_recoverable = $true
        auth_secret_touched = $false
        exact_prior_reuse_policy_preserved = $true
    } | ConvertTo-Json -Depth 5
}
finally {
    if (Test-Path -LiteralPath $testRoot -PathType Container) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
