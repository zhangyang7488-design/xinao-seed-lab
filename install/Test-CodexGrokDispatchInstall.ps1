#Requires -Version 7.0

$ErrorActionPreference = "Stop"

function Assert-Contract([bool]$Condition, [string]$Name) {
    if (-not $Condition) {
        throw "CODEX_GROK_INSTALL_TEST_FAILED: $Name"
    }
}

function Get-Sha256Lower([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$installer = Join-Path $PSScriptRoot "Install-CodexGrokDispatch.ps1"
$testRoot = Join-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_install_tests" (
    "install-" + [guid]::NewGuid().ToString("N")
)
$runtimeRoot = Join-Path $testRoot "runtime"
$targetBridge = Join-Path $testRoot "target-bridge"
$targetLauncher = Join-Path $testRoot "launchers\Invoke-Codex-GrokWorkerPool.ps1"
$authProfile = Join-Path $testRoot "profile"
$runtimeFiles = @(
    "GrokAuthenticatedCatalogTime.ps1",
    "GrokAuthenticatedCatalogRefresh.ps1",
    "Invoke-CodexDispatchGrokWorkerPool.ps1",
    "Invoke-GrokComposer25Worker.ps1"
)
$dependencies = @(
    "GrokWindowsPathIdentity.ps1",
    "GrokWorkerProcessRuntime.ps1",
    "Invoke-GrokWorkerPool.ps1",
    "GrokWorkerSelectionReceipt.ps1",
    "resolve_grok_worker_selection_receipt.py",
    "GrokSupervisorRootCapability.ps1",
    "Test-GrokCliEffectiveOutput.ps1"
)
$utf8 = [Text.UTF8Encoding]::new($false)

try {
    New-Item -ItemType Directory -Path $runtimeRoot, $targetBridge, (Split-Path -Parent $targetLauncher), $authProfile -Force | Out-Null
    foreach ($dependency in $dependencies) {
        [IO.File]::WriteAllBytes(
            (Join-Path $targetBridge $dependency),
            [IO.File]::ReadAllBytes((Join-Path $repoRoot ("grok-admin-bridge\" + $dependency)))
        )
    }

    $previousHashes = [ordered]@{}
    foreach ($relative in $runtimeFiles) {
        $target = Join-Path $targetBridge $relative
        [IO.File]::WriteAllText($target, ("previous::" + $relative), $utf8)
        $previousHashes[$relative] = Get-Sha256Lower $target
    }
    [IO.File]::WriteAllText($targetLauncher, "previous::launcher", $utf8)
    $previousLauncherSha256 = Get-Sha256Lower $targetLauncher
    [IO.File]::WriteAllText((Join-Path $authProfile "auth.json"), "{}", $utf8)

    $installOutput = @(
        & $installer `
            -SourceRoot $repoRoot `
            -RuntimeRoot $runtimeRoot `
            -TargetLauncher $targetLauncher `
            -TargetBridgeRoot $targetBridge `
            -AuthProfileRoot $authProfile
    )
    $receipt = ($installOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop
    Assert-Contract ([string]$receipt.schema_version -eq "xinao.codex_grok_dispatch_install_receipt.v2") "receipt_schema"
    Assert-Contract ([bool]$receipt.auth_present) "auth_readiness_present"
    Assert-Contract ([string]$receipt.auth_state -eq "present_nonempty") "auth_readiness_state"
    Assert-Contract (-not [bool]$receipt.auth_bytes_read) "auth_bytes_not_read"
    Assert-Contract (-not [bool]$receipt.auth_copied_or_backed_up) "auth_not_copied"
    Assert-Contract ([string]$receipt.exact_prior_reuse_policy -match "zero_refresh_zero_worker_zero_tokens") "prior_reuse_policy_preserved"
    Assert-Contract (@($receipt.install_items).Count -eq 5) "install_item_count"
    foreach ($relative in $runtimeFiles) {
        $source = Join-Path $repoRoot ("grok-admin-bridge\" + $relative)
        $target = Join-Path $targetBridge $relative
        Assert-Contract ((Get-Sha256Lower $target) -eq (Get-Sha256Lower $source)) ("runtime_readback:" + $relative)
        $item = @($receipt.install_items | Where-Object { [string]$_.relative_ref -eq $relative })
        Assert-Contract ($item.Count -eq 1) ("runtime_receipt_item:" + $relative)
        Assert-Contract ([string]$item[0].previous_sha256 -eq [string]$previousHashes[$relative]) ("runtime_previous_hash:" + $relative)
    }
    Assert-Contract ((Get-Sha256Lower $targetLauncher) -eq (Get-Sha256Lower (Join-Path $repoRoot "launchers\Invoke-Codex-GrokWorkerPool.ps1"))) "launcher_readback"
    Assert-Contract (Test-Path -LiteralPath ([string]$receipt.rollback_script_ref) -PathType Leaf) "rollback_script_present"

    $rollbackOutput = @(
        & ([string]$receipt.rollback_script_ref) -InstallReceiptPath ([string]$receipt.receipt_ref)
    )
    $rollback = ($rollbackOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop
    Assert-Contract ([string]$rollback.schema_version -eq "xinao.codex_grok_dispatch_rollback_result.v1") "rollback_schema"
    Assert-Contract (-not [bool]$rollback.auth_profile_touched) "rollback_auth_untouched"
    foreach ($relative in $runtimeFiles) {
        Assert-Contract ((Get-Sha256Lower (Join-Path $targetBridge $relative)) -eq [string]$previousHashes[$relative]) ("runtime_rollback:" + $relative)
    }
    Assert-Contract ((Get-Sha256Lower $targetLauncher) -eq $previousLauncherSha256) "launcher_rollback"
    Assert-Contract (-not (Test-Path -LiteralPath ([string]$receipt.release_pointer_ref) -PathType Leaf)) "pointer_rollback"

    Remove-Item -LiteralPath (Join-Path $authProfile "auth.json") -Force
    $missingAuthOutput = @(
        & $installer `
            -SourceRoot $repoRoot `
            -RuntimeRoot $runtimeRoot `
            -TargetLauncher $targetLauncher `
            -TargetBridgeRoot $targetBridge `
            -AuthProfileRoot $authProfile
    )
    $missingAuthReceipt = ($missingAuthOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop
    Assert-Contract (-not [bool]$missingAuthReceipt.auth_present) "missing_auth_not_ready"
    Assert-Contract ([string]$missingAuthReceipt.auth_state -eq "login_required") "missing_auth_state"
    Assert-Contract ((Get-Sha256Lower $targetLauncher) -eq (Get-Sha256Lower (Join-Path $repoRoot "launchers\Invoke-Codex-GrokWorkerPool.ps1"))) "missing_auth_does_not_block_program_install"
    $null = @(
        & ([string]$missingAuthReceipt.rollback_script_ref) -InstallReceiptPath ([string]$missingAuthReceipt.receipt_ref)
    )

    [ordered]@{
        status = "verified"
        install_readback = $true
        bridge_runtime_file_count = $runtimeFiles.Count
        public_launcher_installed = $true
        previous_bytes_backed_up = $true
        rollback_executed = $true
        auth_present_readiness = "present_nonempty"
        auth_missing_readiness = "login_required"
        auth_secret_read_or_copied = $false
        exact_prior_reuse_policy_preserved = $true
    } | ConvertTo-Json -Depth 6
}
finally {
    if (Test-Path -LiteralPath $testRoot -PathType Container) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
