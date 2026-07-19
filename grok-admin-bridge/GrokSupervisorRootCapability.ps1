#Requires -Version 7.0

function Resolve-GrokSupervisorSelectorRoot {
    [CmdletBinding()]
    param(
        [string]$SupervisorRoot = "",
        [string]$Cwd = "",
        [Parameter(Mandatory = $true)]
        [string]$SelectionResolver
    )

    if (-not (Test-Path -LiteralPath $SelectionResolver -PathType Leaf)) {
        throw "CODEX_GROK_SELECTION_RESOLVER_MISSING: $SelectionResolver"
    }

    $candidates = [Collections.Generic.List[object]]::new()
    $seen = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($candidate in @(
        [pscustomobject]@{ kind = "supervisor_root_hint"; value = $SupervisorRoot },
        [pscustomobject]@{ kind = "task_cwd"; value = $Cwd }
    )) {
        if ([string]::IsNullOrWhiteSpace([string]$candidate.value)) { continue }
        try {
            $full = [IO.Path]::GetFullPath([string]$candidate.value)
        }
        catch {
            $candidates.Add([pscustomobject]@{
                hint_kind = [string]$candidate.kind
                requested_root = [string]$candidate.value
                invalid_path = $true
            })
            continue
        }
        if ($seen.Add($full)) {
            $candidates.Add([pscustomobject]@{
                hint_kind = [string]$candidate.kind
                requested_root = $full
                invalid_path = $false
            })
        }
    }
    if ($candidates.Count -eq 0) {
        throw "CODEX_GROK_SUPERVISOR_ROOT_HINTS_MISSING: provide SupervisorRoot or a selector-capable Cwd"
    }

    $reports = [Collections.Generic.List[object]]::new()
    foreach ($candidate in $candidates) {
        $report = [ordered]@{
            hint_kind = [string]$candidate.hint_kind
            requested_root = [string]$candidate.requested_root
            capable = $false
            failure_code = ""
            failure_detail = ""
        }
        if ($candidate.invalid_path -eq $true) {
            $report.failure_code = "SUPERVISOR_ROOT_PATH_INVALID"
            $report.failure_detail = [string]$candidate.requested_root
            $reports.Add([pscustomobject]$report)
            continue
        }
        $root = [string]$candidate.requested_root
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            $report.failure_code = "SUPERVISOR_ROOT_MISSING"
            $report.failure_detail = $root
            $reports.Add([pscustomobject]$report)
            continue
        }
        $entry = Join-Path $root "services\agent_runtime\routing_policy_reader.py"
        if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
            $report.failure_code = "SUPERVISOR_SELECTOR_ENTRY_MISSING"
            $report.failure_detail = $entry
            $reports.Add([pscustomobject]$report)
            continue
        }
        $python = Join-Path $root ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
            $report.failure_code = "SUPERVISOR_PYTHON_MISSING"
            $report.failure_detail = $python
            $reports.Add([pscustomobject]$report)
            continue
        }
        $probeOutput = @(
            & $python -I -B $SelectionResolver `
                --probe-only `
                --supervisor-root $root 2>&1 |
                ForEach-Object { [string]$_ }
        )
        $probeExit = $LASTEXITCODE
        $probeLine = @($probeOutput | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) |
            Select-Object -Last 1
        $probe = $null
        if ($probeLine) {
            try { $probe = $probeLine | ConvertFrom-Json -ErrorAction Stop }
            catch { $probe = $null }
        }
        if ($null -eq $probe) {
            $report.failure_code = "SUPERVISOR_SELECTOR_PROBE_OUTPUT_INVALID"
            $report.failure_detail = ($probeOutput -join "`n")
            $reports.Add([pscustomobject]$report)
            continue
        }
        $report.resolved_root = [string]$probe.resolved_root
        $report.python_executable = [string]$probe.python_executable
        $report.python_isolated = $probe.python_isolated -eq $true
        $report.dont_write_bytecode = $probe.dont_write_bytecode -eq $true
        $report.selector_source = [string]$probe.selector_source
        $report.selector_source_sha256 = [string]$probe.selector_source_sha256
        $report.imported_module_source = [string]$probe.imported_module_source
        $report.failure_code = [string]$probe.failure_code
        $report.failure_detail = [string]$probe.failure_detail
        $report.capable = (
            $probeExit -eq 0 -and
            $probe.capable -eq $true -and
            $probe.python_isolated -eq $true -and
            $probe.dont_write_bytecode -eq $true -and
            [string]$probe.selector_source_sha256 -match '^[0-9a-f]{64}$' -and
            [string]::Equals(
                [string]$probe.selector_source,
                [string]$probe.imported_module_source,
                [StringComparison]::OrdinalIgnoreCase
            )
        )
        if (-not $report.capable -and [string]::IsNullOrWhiteSpace($report.failure_code)) {
            $report.failure_code = "SUPERVISOR_SELECTOR_PROBE_CONTRACT_MISMATCH"
        }
        $reports.Add([pscustomobject]$report)
        if ($report.capable) {
            $explicitHintWasGiven = -not [string]::IsNullOrWhiteSpace($SupervisorRoot)
            return [pscustomobject]@{
                schema_version = "xinao.grok_supervisor_root_resolution.v1"
                resolved_root = [string]$report.resolved_root
                python_executable = [string]$report.python_executable
                selector_source = [string]$report.selector_source
                selector_source_sha256 = [string]$report.selector_source_sha256
                imported_module_source = [string]$report.imported_module_source
                selected_from = [string]$report.hint_kind
                fallback_used = (
                    $explicitHintWasGiven -and
                    [string]$report.hint_kind -ne "supervisor_root_hint"
                )
                candidate_reports = @($reports)
            }
        }
    }
    $diagnostic = [ordered]@{
        schema_version = "xinao.grok_supervisor_root_resolution_failure.v1"
        supervisor_root_hint = $SupervisorRoot
        cwd = $Cwd
        candidate_reports = @($reports)
    } | ConvertTo-Json -Depth 8 -Compress
    throw "CODEX_GROK_SUPERVISOR_CAPABILITY_MISSING: $diagnostic"
}
