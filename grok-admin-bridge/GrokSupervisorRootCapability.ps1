#Requires -Version 7.0

function Resolve-GrokSupervisorSelectorRoot {
    [CmdletBinding()]
    param(
        [string]$SupervisorRoot = "",
        [string]$Cwd = "",
        [Parameter(Mandatory = $true)]
        [string]$SelectionResolver,
        [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
        [string]$ReleasePointer = ""
    )

    if (-not (Test-Path -LiteralPath $SelectionResolver -PathType Leaf)) {
        throw "CODEX_GROK_SELECTION_RESOLVER_MISSING: $SelectionResolver"
    }

    $candidateKind = ""
    $root = ""
    $python = ""
    $releaseBinding = $null
    if (-not [string]::IsNullOrWhiteSpace($SupervisorRoot)) {
        try { $root = [IO.Path]::GetFullPath($SupervisorRoot) }
        catch { throw "CODEX_GROK_SUPERVISOR_ROOT_INVALID: $SupervisorRoot" }
        $python = Join-Path $root ".venv\Scripts\python.exe"
        $candidateKind = "explicit_supervisor_root"
    }
    else {
        if ([string]::IsNullOrWhiteSpace($ReleasePointer)) {
            $ReleasePointer = Join-Path $RuntimeRoot "state\grok_supervisor_selector\current.json"
        }
        try { $ReleasePointer = [IO.Path]::GetFullPath($ReleasePointer) }
        catch { throw "CODEX_GROK_SELECTOR_RELEASE_POINTER_INVALID: $ReleasePointer" }
        if (-not (Test-Path -LiteralPath $ReleasePointer -PathType Leaf)) {
            throw "CODEX_GROK_SELECTOR_RELEASE_POINTER_MISSING: $ReleasePointer"
        }
        try {
            $pointer = Get-Content -LiteralPath $ReleasePointer -Raw -Encoding UTF8 |
                ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "CODEX_GROK_SELECTOR_RELEASE_POINTER_INVALID_JSON: $ReleasePointer"
        }
        if ([string]$pointer.schema_version -ne "xinao.selector_release_pointer.v1") {
            throw "CODEX_GROK_SELECTOR_RELEASE_POINTER_SCHEMA_MISMATCH"
        }
        $root = [IO.Path]::GetFullPath([string]$pointer.release_root)
        $manifestPath = [IO.Path]::GetFullPath([string]$pointer.release_manifest_ref)
        $expectedManifestSha = ([string]$pointer.release_manifest_sha256).ToLowerInvariant()
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            throw "CODEX_GROK_SELECTOR_RELEASE_MANIFEST_MISSING: $manifestPath"
        }
        $observedManifestSha = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($expectedManifestSha -notmatch '^[0-9a-f]{64}$' -or $observedManifestSha -ne $expectedManifestSha) {
            throw "CODEX_GROK_SELECTOR_RELEASE_MANIFEST_HASH_MISMATCH"
        }
        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
                ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "CODEX_GROK_SELECTOR_RELEASE_MANIFEST_INVALID_JSON: $manifestPath"
        }
        if (
            [string]$manifest.schema_version -ne "xinao.selector_release.v1" -or
            [string]$manifest.release_id -ne [string]$pointer.release_id -or
            -not [string]::Equals(
                [IO.Path]::GetFullPath([string]$manifest.release_root),
                $root,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            -not [string]::Equals(
                [IO.Path]::GetFullPath((Split-Path -Parent $manifestPath)),
                $root,
                [StringComparison]::OrdinalIgnoreCase
            )
        ) {
            throw "CODEX_GROK_SELECTOR_RELEASE_IDENTITY_MISMATCH"
        }
        foreach ($file in @($manifest.files)) {
            $relative = [string]$file.path
            if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[\\/])[.][.]([\\/]|$)') {
                throw "CODEX_GROK_SELECTOR_RELEASE_FILE_PATH_INVALID: $relative"
            }
            $target = [IO.Path]::GetFullPath((Join-Path $root $relative))
            if (-not $target.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                throw "CODEX_GROK_SELECTOR_RELEASE_FILE_OUTSIDE_ROOT: $relative"
            }
            if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
                throw "CODEX_GROK_SELECTOR_RELEASE_FILE_MISSING: $relative"
            }
            $expected = ([string]$file.sha256).ToLowerInvariant()
            $observed = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($expected -notmatch '^[0-9a-f]{64}$' -or $expected -ne $observed) {
                throw "CODEX_GROK_SELECTOR_RELEASE_FILE_HASH_MISMATCH: $relative"
            }
        }
        $python = [IO.Path]::GetFullPath([string]$manifest.python_executable)
        $candidateKind = "stable_release_pointer"
        $releaseBinding = [ordered]@{
            pointer_path = $ReleasePointer
            pointer_sha256 = (Get-FileHash -LiteralPath $ReleasePointer -Algorithm SHA256).Hash.ToLowerInvariant()
            release_id = [string]$pointer.release_id
            release_manifest_ref = $manifestPath
            release_manifest_sha256 = $observedManifestSha
        }
    }

    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "CODEX_GROK_SUPERVISOR_ROOT_MISSING: $root"
    }
    $entry = Join-Path $root "services\agent_runtime\routing_policy_reader.py"
    if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
        throw "CODEX_GROK_SUPERVISOR_SELECTOR_ENTRY_MISSING: $entry"
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "CODEX_GROK_SUPERVISOR_PYTHON_MISSING: $python"
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
    try { $probe = $probeLine | ConvertFrom-Json -ErrorAction Stop }
    catch {
        throw "CODEX_GROK_SUPERVISOR_SELECTOR_PROBE_OUTPUT_INVALID: $($probeOutput -join [Environment]::NewLine)"
    }
    $capable = (
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
    if (-not $capable) {
        $diagnostic = [ordered]@{
            schema_version = "xinao.grok_supervisor_root_resolution_failure.v2"
            selected_from = $candidateKind
            requested_root = $root
            task_cwd_ignored = $Cwd
            release_binding = $releaseBinding
            probe = $probe
        } | ConvertTo-Json -Depth 12 -Compress
        throw "CODEX_GROK_SUPERVISOR_CAPABILITY_MISSING: $diagnostic"
    }
    return [pscustomobject]@{
        schema_version = "xinao.grok_supervisor_root_resolution.v2"
        resolved_root = [string]$probe.resolved_root
        python_executable = [string]$probe.python_executable
        selector_source = [string]$probe.selector_source
        selector_source_sha256 = [string]$probe.selector_source_sha256
        imported_module_source = [string]$probe.imported_module_source
        selected_from = $candidateKind
        fallback_used = $false
        task_cwd_used_for_selector = $false
        release_binding = $releaseBinding
        candidate_reports = @($probe)
    }
}
