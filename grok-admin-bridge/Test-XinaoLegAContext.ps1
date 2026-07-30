#Requires -Version 7.0
<#
.SYNOPSIS
  Focused positive/negative tests for Build-XinaoLegAContext.ps1.

.DESCRIPTION
  Builds a synthetic mainline tree with the owned relative paths and enough
  lines for the package selectors. Covers happy path, idempotent rebuild,
  source-hash pin drift, missing source, non-UTF8 source, oversize content,
  and fresh-process invocation. Never touches live C/D projections.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$PythonExe = "",
    [string]$TestRoot = ""
)

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false)

function Assert-True([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "XINAO_LEG_A_CONTEXT_TEST_FAILED: $Name" }
}

function Get-Sha256LowerFile([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function New-LineFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$LineCount,
        [string]$Prefix = "L",
        [int]$PadWidth = 40
    )
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $sb = [Text.StringBuilder]::new()
    for ($i = 1; $i -le $LineCount; $i++) {
        $payload = ("{0}{1:D5} {2}" -f $Prefix, $i, ("x" * $PadWidth))
        [void]$sb.Append($payload)
        [void]$sb.Append("`n")
    }
    [IO.File]::WriteAllText($Path, $sb.ToString(), $utf8)
}

function New-SyntheticMainline([string]$Root) {
    # Owned paths + enough lines for the highest owned end line (1695 / 327 / 40 / 296).
    $science = Join-Path $Root "01_主线入口/《新澳严格数学科学研究模式——独立融合稿》.txt"
    $dual = Join-Path $Root "工具胶水宪法/新澳双腿执行结构树_腿A直调_腿B后台_当前有效.txt"
    $cross = Join-Path $Root "工具胶水宪法/跨接缝执行封套与一致性协议_当前有效.txt"
    $glue = Join-Path $Root "工具胶水宪法/软件工具胶水宪法_当前有效.txt"
    New-LineFile -Path $science -LineCount 1800 -Prefix "SCI" -PadWidth 24
    New-LineFile -Path $dual -LineCount 350 -Prefix "DUAL" -PadWidth 24
    New-LineFile -Path $cross -LineCount 80 -Prefix "CROSS" -PadWidth 24
    New-LineFile -Path $glue -LineCount 320 -Prefix "GLUE" -PadWidth 24
    return [ordered]@{
        science = $science
        dual    = $dual
        cross   = $cross
        glue    = $glue
    }
}

function Invoke-Build {
    param(
        [Parameter(Mandatory = $true)][string]$OutputDir,
        [Parameter(Mandatory = $true)][string]$MainlineRoot,
        [string]$ExpectedSourcePinsPath = "",
        [int]$MaxContentBytes = 65536,
        [switch]$FreshProcess
    )
    $buildScript = Join-Path $PSScriptRoot "Build-XinaoLegAContext.ps1"
    $argList = @(
        "-NoLogo", "-NoProfile", "-NonInteractive",
        "-File", $buildScript,
        "-OutputDir", $OutputDir,
        "-MainlineRoot", $MainlineRoot,
        "-RepoRoot", $script:RepoRootResolved,
        "-MaxContentBytes", "$MaxContentBytes",
        "-Quiet"
    )
    if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
        $argList += @("-PythonExe", $PythonExe)
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSourcePinsPath)) {
        $argList += @("-ExpectedSourcePinsPath", $ExpectedSourcePinsPath)
    }

    if ($FreshProcess) {
        $pwshCmd = Get-Command pwsh -ErrorAction SilentlyContinue
        if (-not $pwshCmd) { $pwshCmd = Get-Command pwsh.exe -ErrorAction SilentlyContinue }
        Assert-True ($null -ne $pwshCmd) "fresh_process_pwsh_available"
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $pwshCmd.Source
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        foreach ($a in $argList) { [void]$info.ArgumentList.Add($a) }
        $proc = [Diagnostics.Process]::new()
        $proc.StartInfo = $info
        [void]$proc.Start()
        $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
        $stderrTask = $proc.StandardError.ReadToEndAsync()
        Assert-True ($proc.WaitForExit(120000)) "fresh_process_timeout"
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        return [pscustomobject]@{
            exit_code = $proc.ExitCode
            stdout    = $stdout
            stderr    = $stderr
        }
    }

    $invokeParams = @{
        OutputDir        = $OutputDir
        MainlineRoot     = $MainlineRoot
        RepoRoot         = $script:RepoRootResolved
        MaxContentBytes  = $MaxContentBytes
        Quiet            = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
        $invokeParams.PythonExe = $PythonExe
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSourcePinsPath)) {
        $invokeParams.ExpectedSourcePinsPath = $ExpectedSourcePinsPath
    }

    $errorText = ""
    $exitCode = 0
    $stdout = ""
    try {
        $stdout = & $buildScript @invokeParams 2>&1 | ForEach-Object { [string]$_ } | Out-String
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) { $exitCode = 0 }
    }
    catch {
        $exitCode = 1
        $errorText = [string]$_.Exception.Message
        $stdout = $errorText
    }
    return [pscustomobject]@{
        exit_code = $exitCode
        stdout    = $stdout
        stderr    = $errorText
    }
}

function Resolve-TestRepoRoot([string]$Requested) {
    $candidates = @()
    if ($Requested) { $candidates += $Requested }
    if ($env:XINAO_S_REPO_ROOT) { $candidates += $env:XINAO_S_REPO_ROOT }
    $bridgeConfig = Join-Path $PSScriptRoot "bridge.config.json"
    if (Test-Path -LiteralPath $bridgeConfig -PathType Leaf) {
        try {
            $cfg = Get-Content -LiteralPath $bridgeConfig -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($cfg.repo_root) { $candidates += [string]$cfg.repo_root }
        }
        catch { }
    }
    $candidates += @("E:\XINAO_RESEARCH_WORKSPACES\S", "/app")
    foreach ($c in $candidates) {
        if ([string]::IsNullOrWhiteSpace($c)) { continue }
        try { $full = [IO.Path]::GetFullPath($c) } catch { continue }
        $mod = Join-Path $full "services/agent_runtime/context_slice_manifest.py"
        $modWin = Join-Path $full "services\agent_runtime\context_slice_manifest.py"
        if ((Test-Path -LiteralPath $mod -PathType Leaf) -or
            (Test-Path -LiteralPath $modWin -PathType Leaf)) {
            return $full
        }
    }
    throw "XINAO_LEG_A_CONTEXT_TEST_REPO_ROOT_MISSING"
}

# --- arrange ---
$script:RepoRootResolved = Resolve-TestRepoRoot $RepoRoot
if ([string]::IsNullOrWhiteSpace($TestRoot)) {
    $baseTmp = $env:TEMP
    if ([string]::IsNullOrWhiteSpace($baseTmp)) { $baseTmp = [IO.Path]::GetTempPath() }
    # Prefer isolated D runtime tmp when present (Windows host); else process temp.
    $dTmp = "D:\XINAO_RESEARCH_RUNTIME\tmp"
    if (Test-Path -LiteralPath "D:\XINAO_RESEARCH_RUNTIME" -PathType Container) {
        $baseTmp = $dTmp
        New-Item -ItemType Directory -Force -Path $baseTmp | Out-Null
    }
    $TestRoot = Join-Path $baseTmp (
        "xinao-leg-a-context-" + (Get-Date -Format "yyyyMMddTHHmmss") + "-" +
        [guid]::NewGuid().ToString("N").Substring(0, 8)
    )
}
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null

$mainline = Join-Path $TestRoot "mainline"
$files = New-SyntheticMainline $mainline
$results = [System.Collections.Generic.List[string]]::new()

# ---------------------------------------------------------------------------
# Positive: build seal
# ---------------------------------------------------------------------------
$out1 = Join-Path $TestRoot "out-positive"
$result1 = Invoke-Build -OutputDir $out1 -MainlineRoot $mainline
Assert-True ($result1.exit_code -eq 0) "positive_exit_zero:$($result1.stdout)$($result1.stderr)"
$public1 = $result1.stdout | ConvertFrom-Json
Assert-True ([string]$public1.sentinel -eq "XINAO_LEG_A_CONTEXT_SEAL_CANDIDATE_V1") "positive_sentinel"
Assert-True ($public1.ok -eq $true) "positive_ok"
Assert-True ($public1.authority -eq $false) "positive_authority_false"
Assert-True ($public1.completion_claim_allowed -eq $false) "positive_no_completion"
Assert-True ($public1.candidate_only -eq $true) "positive_candidate_only"
Assert-True ([string]$public1.context_sha256 -match '^[0-9a-f]{64}$') "positive_context_sha"
Assert-True ([string]$public1.source_manifest_sha256 -match '^[0-9a-f]{64}$') "positive_source_manifest_sha"
Assert-True (Test-Path -LiteralPath ([string]$public1.manifest_path) -PathType Leaf) "positive_manifest_path"
Assert-True (Test-Path -LiteralPath ([string]$public1.spec_path) -PathType Leaf) "positive_spec_path"
Assert-True (@($public1.source_file_identities).Count -eq 4) "positive_four_sources"
$manifest1 = Get-Content -LiteralPath ([string]$public1.manifest_path) -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ([string]$manifest1.schema_version -eq "xinao.context_slice_manifest.v1") "positive_manifest_schema"
Assert-True ($manifest1.authority -eq $false) "positive_manifest_authority"
Assert-True ([int]$manifest1.total_content_bytes -le 65536) "positive_under_budget"
Assert-True ([int]$manifest1.total_content_bytes -gt 0) "positive_nonzero_content"
# Deny outcomes / authority-shaped fields on public envelope
Assert-True (-not ($public1.PSObject.Properties.Name -contains "outcome")) "positive_no_outcome_field"
Assert-True (-not ($public1.PSObject.Properties.Name -contains "completion_status")) "positive_no_completion_status"
[void]$results.Add("positive_build")

# ---------------------------------------------------------------------------
# Positive: idempotent rebuild
# ---------------------------------------------------------------------------
$out2 = Join-Path $TestRoot "out-idempotent"
$result2a = Invoke-Build -OutputDir $out2 -MainlineRoot $mainline
$result2b = Invoke-Build -OutputDir $out2 -MainlineRoot $mainline
Assert-True ($result2a.exit_code -eq 0 -and $result2b.exit_code -eq 0) "idempotent_exit"
$pub2a = $result2a.stdout | ConvertFrom-Json
$pub2b = $result2b.stdout | ConvertFrom-Json
Assert-True ([string]$pub2a.context_sha256 -ceq [string]$pub2b.context_sha256) "idempotent_context_sha"
Assert-True ([string]$pub2a.source_manifest_sha256 -ceq [string]$pub2b.source_manifest_sha256) "idempotent_source_manifest_sha"
Assert-True ((Get-Sha256LowerFile ([string]$pub2a.spec_path)) -ceq (Get-Sha256LowerFile ([string]$pub2b.spec_path))) "idempotent_spec_bytes"
[void]$results.Add("idempotent_rebuild")

# ---------------------------------------------------------------------------
# Positive: expected source pins match
# ---------------------------------------------------------------------------
$pinsPath = Join-Path $TestRoot "pins-ok.json"
$pinMap = [ordered]@{}
foreach ($row in @($public1.source_file_identities)) {
    $pinMap[[string]$row.path] = [string]$row.source_sha256
}
[IO.File]::WriteAllText($pinsPath, ($pinMap | ConvertTo-Json -Compress), $utf8)
$outPins = Join-Path $TestRoot "out-pins-ok"
$resultPins = Invoke-Build -OutputDir $outPins -MainlineRoot $mainline -ExpectedSourcePinsPath $pinsPath
Assert-True ($resultPins.exit_code -eq 0) "pins_match_exit:$($resultPins.stdout)$($resultPins.stderr)"
[void]$results.Add("pins_match")

# ---------------------------------------------------------------------------
# Negative: source drift against pins
# ---------------------------------------------------------------------------
$files = New-SyntheticMainline $mainline
$cleanBuild = Invoke-Build -OutputDir (Join-Path $TestRoot "out-clean-for-pins") -MainlineRoot $mainline
Assert-True ($cleanBuild.exit_code -eq 0) "drift_setup_clean_build"
$cleanPub = $cleanBuild.stdout | ConvertFrom-Json
$pinMap2 = [ordered]@{}
foreach ($row in @($cleanPub.source_file_identities)) {
    $pinMap2[[string]$row.path] = [string]$row.source_sha256
}
$pins2 = Join-Path $TestRoot "pins-drift2.json"
[IO.File]::WriteAllText($pins2, ($pinMap2 | ConvertTo-Json -Compress), $utf8)
[IO.File]::AppendAllText($files.science, "DRIFT2`n", $utf8)
$outDrift2 = Join-Path $TestRoot "out-drift2"
$dr = Invoke-Build -OutputDir $outDrift2 -MainlineRoot $mainline -ExpectedSourcePinsPath $pins2
$driftText = "$($dr.stdout)$($dr.stderr)"
Assert-True ($dr.exit_code -ne 0) "source_drift_rejected:$driftText"
Assert-True ($driftText -match "SOURCE_DRIFT") "source_drift_message:$driftText"
[void]$results.Add("negative_source_drift")

# Restore clean tree
$files = New-SyntheticMainline $mainline

# ---------------------------------------------------------------------------
# Negative: missing source
# ---------------------------------------------------------------------------
$brokenMainline = Join-Path $TestRoot "mainline-missing"
$brokenFiles = New-SyntheticMainline $brokenMainline
Remove-Item -LiteralPath $brokenFiles.cross -Force
$outMissing = Join-Path $TestRoot "out-missing"
$missingRejected = $false
$missingText = ""
try {
    $mr = Invoke-Build -OutputDir $outMissing -MainlineRoot $brokenMainline
    $missingText = "$($mr.stdout)$($mr.stderr)"
    if ($mr.exit_code -ne 0) { $missingRejected = $true }
}
catch {
    $missingRejected = $true
    $missingText = [string]$_.Exception.Message
}
Assert-True $missingRejected "missing_source_rejected:$missingText"
Assert-True ($missingText -match "SOURCE_MISSING|not a file|XINAO_LEG_A_CONTEXT") "missing_source_message:$missingText"
[void]$results.Add("negative_missing_source")

# ---------------------------------------------------------------------------
# Negative: non-UTF8 encoding
# ---------------------------------------------------------------------------
$encMainline = Join-Path $TestRoot "mainline-encoding"
$encFiles = New-SyntheticMainline $encMainline
[IO.File]::WriteAllBytes($encFiles.glue, [byte[]](0xFF, 0xFE, 0x00, 0x41, 0x00, 0x0A))
$outEnc = Join-Path $TestRoot "out-encoding"
$encRejected = $false
$encText = ""
try {
    $er = Invoke-Build -OutputDir $outEnc -MainlineRoot $encMainline
    $encText = "$($er.stdout)$($er.stderr)"
    if ($er.exit_code -ne 0) { $encRejected = $true }
}
catch {
    $encRejected = $true
    $encText = [string]$_.Exception.Message
}
Assert-True $encRejected "encoding_rejected:$encText"
Assert-True ($encText -match "ENCODING|UTF-8|utf-8|XINAO_LEG_A_CONTEXT") "encoding_message:$encText"
[void]$results.Add("negative_encoding")

# ---------------------------------------------------------------------------
# Negative: oversize selected content
# ---------------------------------------------------------------------------
$bigMainline = Join-Path $TestRoot "mainline-oversize"
$bigFiles = New-SyntheticMainline $bigMainline
# Blow up lines inside an owned selector window (science 1-80) with huge padding.
New-LineFile -Path $bigFiles.science -LineCount 1800 -Prefix "BIG" -PadWidth 2000
$outBig = Join-Path $TestRoot "out-oversize"
$bigRejected = $false
$bigText = ""
try {
    $br = Invoke-Build -OutputDir $outBig -MainlineRoot $bigMainline -MaxContentBytes 65536
    $bigText = "$($br.stdout)$($br.stderr)"
    if ($br.exit_code -ne 0) { $bigRejected = $true }
}
catch {
    $bigRejected = $true
    $bigText = [string]$_.Exception.Message
}
Assert-True $bigRejected "oversize_rejected:$bigText"
Assert-True ($bigText -match "OVERSIZE|max_content_bytes|exceeds") "oversize_message:$bigText"
[void]$results.Add("negative_oversize")

# ---------------------------------------------------------------------------
# Positive: fresh-process invocation (no prior session state)
# ---------------------------------------------------------------------------
$freshMainline = Join-Path $TestRoot "mainline-fresh"
$null = New-SyntheticMainline $freshMainline
$outFresh = Join-Path $TestRoot "out-fresh"
$fresh = Invoke-Build -OutputDir $outFresh -MainlineRoot $freshMainline -FreshProcess
Assert-True ($fresh.exit_code -eq 0) "fresh_process_exit:$($fresh.stdout)$($fresh.stderr)"
$freshPub = $fresh.stdout | ConvertFrom-Json
Assert-True ([string]$freshPub.sentinel -eq "XINAO_LEG_A_CONTEXT_SEAL_CANDIDATE_V1") "fresh_process_sentinel"
Assert-True ([string]$freshPub.context_sha256 -match '^[0-9a-f]{64}$') "fresh_process_context_sha"
# Same synthetic generator + same owned spec ⇒ same identity as positive (line content identical format)
# Note: fresh tree is re-seeded independently; content is deterministic from New-LineFile, so hashes match out1.
Assert-True ([string]$freshPub.context_sha256 -ceq [string]$public1.context_sha256) "fresh_process_deterministic_vs_inprocess"
[void]$results.Add("fresh_process")

# ---------------------------------------------------------------------------
# Negative: invalid MaxContentBytes above consumer default
# ---------------------------------------------------------------------------
$outMax = Join-Path $TestRoot "out-max"
$maxRejected = $false
$maxText = ""
try {
    $xr = Invoke-Build -OutputDir $outMax -MainlineRoot $freshMainline -MaxContentBytes 70000
    $maxText = "$($xr.stdout)$($xr.stderr)"
    if ($xr.exit_code -ne 0) { $maxRejected = $true }
}
catch {
    $maxRejected = $true
    $maxText = [string]$_.Exception.Message
}
Assert-True $maxRejected "max_bytes_cap_rejected:$maxText"
[void]$results.Add("negative_max_bytes_cap")

$summary = [ordered]@{
    ok            = $true
    sentinel      = "XINAO_LEG_A_CONTEXT_SEAL_CANDIDATE_V1"
    test_root     = $TestRoot
    repo_root     = $script:RepoRootResolved
    passed        = @($results)
    passed_count  = $results.Count
    context_sha256 = [string]$public1.context_sha256
    authority     = $false
    completion_claim_allowed = $false
}
Write-Output ($summary | ConvertTo-Json -Depth 6)
exit 0
