#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "GrokWorkerPoolAccounting.ps1")

function New-Usage([int64]$InputTokens, [int64]$CacheTokens, [int64]$OutputTokens, [int64]$ReasoningTokens) {
    return [pscustomobject]@{
        input_tokens = $InputTokens
        cache_read_input_tokens = $CacheTokens
        output_tokens = $OutputTokens
        reasoning_tokens = $ReasoningTokens
        total_tokens = $InputTokens + $CacheTokens + $OutputTokens + $ReasoningTokens
    }
}
function Assert-Accounting([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "GROK_ACCOUNTING_TEST_FAILED: $Name" }
    Write-Output "PASS: $Name"
}

$results = @(
    [pscustomobject]@{ status="accepted"; effective_output_accepted=$true; usage=(New-Usage 10 20 3 2); usage_accounting_complete=$true },
    [pscustomobject]@{ status="rejected"; effective_output_accepted=$false; usage=(New-Usage 11 21 4 3); usage_accounting_complete=$true },
    [pscustomobject]@{ status="timeout"; timed_out=$true; effective_output_accepted=$false; usage=(New-Usage 12 22 5 4); usage_accounting_complete=$true },
    [pscustomobject]@{ status="invoke_error"; effective_output_accepted=$false; usage=(New-Usage 13 23 6 5); usage_accounting_complete=$false }
)
$selection = [pscustomobject]@{
    provider_id = "grok_acpx_headless"
    profile_ref = "grok.com.cached_profile"
    transport_id = "direct-grok-worker-pool"
}
$actual = Get-GrokWorkerPoolUsageAccounting -Results $results -Selection $selection -Model "grok-4.5"

Assert-Accounting ($actual.usage.attempt_count -eq 4) "attempt_count_preserved"
Assert-Accounting ($actual.outcome_counts.accepted -eq 1) "accepted_partition"
Assert-Accounting ($actual.outcome_counts.rejected -eq 1) "rejected_partition"
Assert-Accounting ($actual.outcome_counts.timeout -eq 1) "timeout_partition"
Assert-Accounting ($actual.outcome_counts.incomplete -eq 1) "incomplete_partition"
Assert-Accounting ($actual.fail_count -eq 3) "fail_count_is_nonaccepted_sum"
Assert-Accounting ($actual.usage.cache_read_input_tokens -eq 86) "cache_tokens_preserved"
Assert-Accounting ($actual.usage.reasoning_tokens -eq 14) "reasoning_tokens_preserved"
Assert-Accounting (
    $actual.usage.total_tokens -eq (
        $actual.usage.by_outcome.accepted.total_tokens +
        $actual.usage.by_outcome.rejected.total_tokens +
        $actual.usage.by_outcome.timeout.total_tokens +
        $actual.usage.by_outcome.incomplete.total_tokens
    )
) "no_double_count"
Assert-Accounting (-not $actual.usage_accounting_complete) "incomplete_lane_marks_pool_incomplete"
