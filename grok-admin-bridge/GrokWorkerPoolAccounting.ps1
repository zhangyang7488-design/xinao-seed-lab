#Requires -Version 5.1

function Get-GrokWorkerPoolUsageAccounting {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object[]]$Results,
        [Parameter(Mandatory = $true)]$Selection,
        [Parameter(Mandatory = $true)][string]$Model
    )

    $tokenKeys = @(
        "input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens"
    )
    $byOutcome = [ordered]@{}
    foreach ($name in @("accepted", "rejected", "timeout", "incomplete")) {
        $bucket = [ordered]@{ attempt_count = 0 }
        foreach ($key in $tokenKeys) { $bucket[$key] = [int64]0 }
        $byOutcome[$name] = $bucket
    }

    $usageAccountingComplete = $true
    foreach ($result in @($Results)) {
        $outcome = [string]$result.status
        if ($outcome -notin @("accepted", "rejected", "timeout", "incomplete")) {
            $outcome = if ($result.timed_out -eq $true -or $result.worker_timed_out -eq $true) {
                "timeout"
            }
            elseif ($null -eq $result.meta_path -or [string]::IsNullOrWhiteSpace([string]$result.worker_status)) {
                "incomplete"
            }
            else {
                "rejected"
            }
        }
        if ($outcome -eq "accepted" -and $result.effective_output_accepted -ne $true) {
            $outcome = "rejected"
        }
        $result.status = $outcome
        if ($null -eq $result.PSObject.Properties["outcome"]) {
            $result | Add-Member -NotePropertyName outcome -NotePropertyValue $outcome
        }
        else {
            $result.outcome = $outcome
        }
        $bucket = $byOutcome[$outcome]
        $bucket.attempt_count = [int]$bucket.attempt_count + 1
        foreach ($key in $tokenKeys) {
            $value = [int64]0
            if ($null -ne $result.usage -and $null -ne $result.usage.$key) {
                $value = [int64]$result.usage.$key
            }
            $bucket[$key] = [int64]$bucket[$key] + $value
        }
        if ($result.usage_accounting_complete -ne $true) {
            $usageAccountingComplete = $false
        }
    }

    $usage = [ordered]@{
        provider_id = [string]$Selection.provider_id
        profile_ref = [string]$Selection.profile_ref
        transport_id = [string]$Selection.transport_id
        model = $Model
        attempt_count = @($Results).Count
    }
    foreach ($key in $tokenKeys) {
        $usage[$key] = [int64](
            ($byOutcome.Values | ForEach-Object { [int64]$_[$key] } | Measure-Object -Sum).Sum
        )
    }
    $usage.by_outcome = $byOutcome

    $outcomeCounts = [ordered]@{}
    foreach ($name in $byOutcome.Keys) {
        $outcomeCounts[$name] = [int]$byOutcome[$name].attempt_count
    }
    $attemptCountFromBuckets = [int](
        ($outcomeCounts.Values | Measure-Object -Sum).Sum
    )
    if ($attemptCountFromBuckets -ne @($Results).Count) {
        throw "GROK_USAGE_ATTEMPT_PARTITION_MISMATCH"
    }
    $totalFromBuckets = [int64](
        ($byOutcome.Values | ForEach-Object { [int64]$_.total_tokens } | Measure-Object -Sum).Sum
    )
    if ($totalFromBuckets -ne [int64]$usage.total_tokens) {
        throw "GROK_USAGE_TOKEN_PARTITION_MISMATCH"
    }

    return [pscustomobject]@{
        usage = $usage
        usage_accounting_complete = $usageAccountingComplete
        outcome_counts = $outcomeCounts
        fail_count = (
            [int]$outcomeCounts.rejected +
            [int]$outcomeCounts.timeout +
            [int]$outcomeCounts.incomplete
        )
    }
}
