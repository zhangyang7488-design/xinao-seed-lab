Describe 'Xinao bounded agent operation reconciler' {
    BeforeAll {
        $root = Split-Path -Parent $PSScriptRoot
        $script:reconciler = Join-Path $root 'provisioning\Invoke-XinaoCoordReconcile.ps1'
    }

    It 'writes bounded verified evidence and returns without registering in tests' {
        $state = Join-Path $TestDrive 'state'
        $managed = Join-Path $TestDrive 'fake-managed.ps1'
        @'
param([string]$Target, [Parameter(ValueFromRemainingArguments=$true)][string[]]$TargetArgs)
[ordered]@{
    ok = $true
    action = 'agent_operation.reconcile'
    bounded = $true
    max_runtime_seconds = 10
    elapsed_ms = 1
    stop_reason = $null
    results = @()
    sweep = [ordered]@{ ok = $true; expired_agent_operation_leases = 0 }
} | ConvertTo-Json -Depth 8
exit 0
'@ | Set-Content -LiteralPath $managed -Encoding UTF8

        $result = & pwsh.exe `
            -NoLogo `
            -NoProfile `
            -NonInteractive `
            -ExecutionPolicy Bypass `
            -File $reconciler `
            -Mode Check `
            -ManagedPath $managed `
            -StateRoot $state `
            -DatabasePath (Join-Path $TestDrive 'coord.sqlite3') `
            -MaxRuntimeSeconds 10 | ConvertFrom-Json

        $result.status | Should -Be 'verified'
        $result.bounded | Should -BeTrue
        $evidence = Get-Content -LiteralPath (Join-Path $state 'evidence.jsonl') -Tail 1 | ConvertFrom-Json
        $evidence.action | Should -Be 'agent_operation.reconcile'
        $evidence.status | Should -Be 'verified'
    }

    It 'has no install mode or task-scheduler persistence surface' {
        $source = Get-Content -Raw -LiteralPath $reconciler
        $source | Should -Not -Match 'ScheduledTask'
        $source | Should -Not -Match "'Install'"
        $status = & pwsh.exe -NoProfile -File $reconciler -Mode Status -StateRoot (Join-Path $TestDrive 'status') |
            ConvertFrom-Json
        $status.persistence_mode | Should -Be 'explicit_only_no_background_scheduler'
        $status.background_reconciler_configured | Should -BeFalse
    }
}
