#Requires -Version 7.0
<#
.SYNOPSIS
  Build one deterministic, bounded, read-only XINAO leg-A context seal.

.DESCRIPTION
  Discovers the stable current science active-parent and tool-glue sources from
  established mainline paths, owns a versioned line-range slice sufficient for
  worker role / parent intent / leg-A·B separation / maturation / real-consumer
  completion, and seals them through the existing repository context-slice
  builder (scripts/build_context_slice_manifest.py +
  services.agent_runtime.context_slice_manifest).

  Writes only under the caller-supplied OutputDir. Never grants authority,
  never claims completion, never packs outcomes/secrets/directory snapshots/
  cached semantic answers/task authority.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputDir,

    [string]$MainlineRoot = "",
    [string]$RepoRoot = "",
    [string]$PythonExe = "",
    [string]$ExpectedSourcePinsPath = "",
    [int]$MaxContentBytes = 65536,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false)

# ---------------------------------------------------------------------------
# Package-owned versioned slice (bounded; must stay within DEFAULT_MAX 65536).
# Covers: scientific parent intent, worker role, leg-A/B, maturation, consumer DoD.
# ---------------------------------------------------------------------------
$script:PackageId = "xinao_leg_a_context_seal"
$script:PackageSpecVersion = "xinao.leg_a_context_slice_owned_spec.v1"
$script:SealSchemaVersion = "xinao.leg_a_context_seal_receipt.v1"
$script:ContextSliceSpecVersion = "xinao.context_slice_spec.v1"
$script:DefaultWindowsMainline = "C:\Users\xx363\Desktop\主线"
$script:DefaultLinuxMainline = "/mainline"
$script:DefaultWindowsRepo = "E:\XINAO_RESEARCH_WORKSPACES\S"

# Stable relative paths under mainline root (discovered, not caller-invented each time).
$script:OwnedEntries = @(
    [ordered]@{
        path = "01_主线入口/《新澳严格数学科学研究模式——独立融合稿》.txt"
        role = "current_scientific_parent_intent"
        selectors = @(
            [ordered]@{ kind = "line_range"; start = 1; end = 80 }
            [ordered]@{ kind = "line_range"; start = 1535; end = 1575 }
            [ordered]@{ kind = "line_range"; start = 1649; end = 1695 }
        )
    }
    [ordered]@{
        path = "工具胶水宪法/新澳双腿执行结构树_腿A直调_腿B后台_当前有效.txt"
        role = "leg_a_leg_b_separation_and_worker_role"
        selectors = @(
            [ordered]@{ kind = "line_range"; start = 1; end = 45 }
            [ordered]@{ kind = "line_range"; start = 150; end = 190 }
            [ordered]@{ kind = "line_range"; start = 310; end = 327 }
        )
    }
    [ordered]@{
        path = "工具胶水宪法/跨接缝执行封套与一致性协议_当前有效.txt"
        role = "cross_seam_execution_envelope"
        selectors = @(
            [ordered]@{ kind = "line_range"; start = 14; end = 40 }
        )
    }
    [ordered]@{
        path = "工具胶水宪法/软件工具胶水宪法_当前有效.txt"
        role = "software_mainline_maturation_and_real_consumer_completion"
        selectors = @(
            [ordered]@{ kind = "line_range"; start = 52; end = 95 }
            [ordered]@{ kind = "line_range"; start = 125; end = 165 }
            [ordered]@{ kind = "line_range"; start = 288; end = 296 }
        )
    }
)

function Write-BytesAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][byte[]]$Bytes
    )
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    $leaf = Split-Path -Leaf $Path
    $temporary = Join-Path $directory ("." + $leaf + "." + [guid]::NewGuid().ToString("N") + ".tmp")
    $backup = Join-Path $directory ("." + $leaf + "." + [guid]::NewGuid().ToString("N") + ".bak")
    try {
        $stream = [IO.File]::Open(
            $temporary,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        try {
            $stream.Write($Bytes, 0, $Bytes.Length)
            $stream.Flush($true)
        }
        finally {
            $stream.Dispose()
        }
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            [IO.File]::Replace($temporary, $Path, $backup, $true)
        }
        else {
            [IO.File]::Move($temporary, $Path)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $backup -PathType Leaf) {
            Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
        }
    }
}

function Write-TextAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text
    )
    Write-BytesAtomic -Path $Path -Bytes $utf8.GetBytes($Text)
}

function Get-Sha256LowerBytes([byte[]]$Bytes) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($hash.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $hash.Dispose()
    }
}

function Get-Sha256LowerFile([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Resolve-MainlineRoot([string]$Requested) {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { [void]$candidates.Add($Requested) }
    if (-not [string]::IsNullOrWhiteSpace($env:XINAO_MAINLINE_ROOT)) {
        [void]$candidates.Add($env:XINAO_MAINLINE_ROOT)
    }
    [void]$candidates.Add($script:DefaultWindowsMainline)
    [void]$candidates.Add($script:DefaultLinuxMainline)

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        try { $full = [IO.Path]::GetFullPath($candidate) }
        catch { continue }
        if (Test-Path -LiteralPath $full -PathType Container) {
            $probe = Join-Path $full "01_主线入口"
            $probe2 = Join-Path $full "工具胶水宪法"
            if ((Test-Path -LiteralPath $probe -PathType Container) -or
                (Test-Path -LiteralPath $probe2 -PathType Container)) {
                return $full
            }
            # Still accept an explicit requested root (tests may use a synthetic tree).
            if (-not [string]::IsNullOrWhiteSpace($Requested) -and
                [string]::Equals(
                    $full,
                    [IO.Path]::GetFullPath($Requested),
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                return $full
            }
        }
    }
    throw "XINAO_LEG_A_CONTEXT_MAINLINE_ROOT_MISSING"
}

function Resolve-RepoRoot([string]$Requested) {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { [void]$candidates.Add($Requested) }
    if (-not [string]::IsNullOrWhiteSpace($env:XINAO_S_REPO_ROOT)) {
        [void]$candidates.Add($env:XINAO_S_REPO_ROOT)
    }
    $bridgeConfig = Join-Path $PSScriptRoot "bridge.config.json"
    if (Test-Path -LiteralPath $bridgeConfig -PathType Leaf) {
        try {
            $cfg = Get-Content -LiteralPath $bridgeConfig -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($cfg.repo_root) { [void]$candidates.Add([string]$cfg.repo_root) }
        }
        catch {
            # ignore malformed bridge config; other candidates may still work
        }
    }
    [void]$candidates.Add($script:DefaultWindowsRepo)
    [void]$candidates.Add("/app")

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        try { $full = [IO.Path]::GetFullPath($candidate) }
        catch { continue }
        $builder = Join-Path $full "scripts\build_context_slice_manifest.py"
        $module = Join-Path $full "services\agent_runtime\context_slice_manifest.py"
        if ((Test-Path -LiteralPath $builder -PathType Leaf) -and
            (Test-Path -LiteralPath $module -PathType Leaf)) {
            return $full
        }
        # Also accept forward-slash form on non-Windows.
        $builderUnix = Join-Path $full "scripts/build_context_slice_manifest.py"
        $moduleUnix = Join-Path $full "services/agent_runtime/context_slice_manifest.py"
        if ((Test-Path -LiteralPath $builderUnix -PathType Leaf) -and
            (Test-Path -LiteralPath $moduleUnix -PathType Leaf)) {
            return $full
        }
    }
    throw "XINAO_LEG_A_CONTEXT_REPO_ROOT_MISSING: need scripts/build_context_slice_manifest.py"
}

function Resolve-Python([string]$Requested, [string]$ResolvedRepoRoot) {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { [void]$candidates.Add($Requested) }
    if (-not [string]::IsNullOrWhiteSpace($env:XINAO_PYTHON_EXE)) {
        [void]$candidates.Add($env:XINAO_PYTHON_EXE)
    }
    [void]$candidates.Add((Join-Path $ResolvedRepoRoot ".venv\Scripts\python.exe"))
    [void]$candidates.Add((Join-Path $ResolvedRepoRoot ".venv/bin/python"))
    [void]$candidates.Add("python3")
    [void]$candidates.Add("python")

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        if ($candidate -in @("python", "python3")) {
            $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
            continue
        }
        try { $full = [IO.Path]::GetFullPath($candidate) }
        catch { continue }
        if (Test-Path -LiteralPath $full -PathType Leaf) { return $full }
    }
    throw "XINAO_LEG_A_CONTEXT_PYTHON_MISSING"
}

function Assert-RelativePathSafe([string]$RelativePath) {
    $normalized = $RelativePath.Replace("\", "/")
    if ([string]::IsNullOrWhiteSpace($normalized) -or
        [IO.Path]::IsPathRooted($normalized) -or
        $normalized.Contains("..") -or
        $normalized.StartsWith("/")) {
        throw "XINAO_LEG_A_CONTEXT_PATH_ESCAPE: $RelativePath"
    }
}

function Get-SourceFileOrThrow([string]$Root, [string]$RelativePath) {
    Assert-RelativePathSafe $RelativePath
    $full = [IO.Path]::GetFullPath((Join-Path $Root ($RelativePath.Replace("/", [IO.Path]::DirectorySeparatorChar))))
    $rootFull = [IO.Path]::GetFullPath($Root)
    if (-not $full.StartsWith(
            $rootFull.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        ) -and $full -ne $rootFull) {
        throw "XINAO_LEG_A_CONTEXT_PATH_ESCAPE: $RelativePath"
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        throw "XINAO_LEG_A_CONTEXT_SOURCE_MISSING: $RelativePath"
    }
    return $full
}

function Assert-Utf8File([string]$Path, [string]$RelativePath) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    try {
        $null = $utf8.GetString($bytes)
        # Reject UTF-16 BOM and other non-UTF8 by strict decoder
        $decoder = $utf8.GetDecoder()
        $decoder.Fallback = [Text.DecoderExceptionFallback]::new()
        $charBuf = New-Object char[] ($bytes.Length + 1)
        $null = $decoder.GetChars($bytes, 0, $bytes.Length, $charBuf, 0, $true)
    }
    catch {
        throw "XINAO_LEG_A_CONTEXT_SOURCE_ENCODING: $RelativePath"
    }
}

function Get-OwnedSpecObject {
    $entries = @(
        foreach ($entry in $script:OwnedEntries) {
            [ordered]@{
                path = [string]$entry.path
                selectors = @(
                    foreach ($sel in @($entry.selectors)) {
                        [ordered]@{
                            kind = [string]$sel.kind
                            start = [int]$sel.start
                            end = [int]$sel.end
                        }
                    }
                )
            }
        }
    )
    return [ordered]@{
        schema_version = $script:ContextSliceSpecVersion
        entries = $entries
    }
}

try {
    $outputDirFull = [IO.Path]::GetFullPath($OutputDir)
}
catch {
    throw "XINAO_LEG_A_CONTEXT_OUTPUT_DIR_INVALID: $OutputDir"
}
if ([string]::IsNullOrWhiteSpace($outputDirFull)) {
    throw "XINAO_LEG_A_CONTEXT_OUTPUT_DIR_INVALID: $OutputDir"
}
New-Item -ItemType Directory -Force -Path $outputDirFull | Out-Null

$mainlineRootFull = Resolve-MainlineRoot $MainlineRoot
$repoRootFull = Resolve-RepoRoot $RepoRoot
$pythonFull = Resolve-Python -Requested $PythonExe -ResolvedRepoRoot $repoRootFull
$builderScript = Join-Path $repoRootFull "scripts/build_context_slice_manifest.py"
if (-not (Test-Path -LiteralPath $builderScript -PathType Leaf)) {
    $builderScript = Join-Path $repoRootFull "scripts\build_context_slice_manifest.py"
}
if (-not (Test-Path -LiteralPath $builderScript -PathType Leaf)) {
    throw "XINAO_LEG_A_CONTEXT_BUILDER_SCRIPT_MISSING: $builderScript"
}

if ($MaxContentBytes -lt 1 -or $MaxContentBytes -gt 65536) {
    # Consumers validate with DEFAULT_MAX_CONTENT_BYTES=65536; never emit a larger seal.
    throw "XINAO_LEG_A_CONTEXT_MAX_CONTENT_BYTES_INVALID: must be 1..65536"
}

# Optional expected full-file pins (path -> sha256). Drift fails closed before model use.
$expectedPins = $null
if (-not [string]::IsNullOrWhiteSpace($ExpectedSourcePinsPath)) {
    $pinsPath = [IO.Path]::GetFullPath($ExpectedSourcePinsPath)
    if (-not (Test-Path -LiteralPath $pinsPath -PathType Leaf)) {
        throw "XINAO_LEG_A_CONTEXT_SOURCE_PINS_MISSING: $pinsPath"
    }
    try {
        $expectedPins = Get-Content -LiteralPath $pinsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "XINAO_LEG_A_CONTEXT_SOURCE_PINS_INVALID_JSON: $pinsPath"
    }
}

$sourceIdentities = [System.Collections.Generic.List[object]]::new()
foreach ($entry in $script:OwnedEntries) {
    $rel = [string]$entry.path
    $full = Get-SourceFileOrThrow -Root $mainlineRootFull -RelativePath $rel
    Assert-Utf8File -Path $full -RelativePath $rel
    $bytes = [IO.File]::ReadAllBytes($full)
    $sha = Get-Sha256LowerBytes $bytes
    $lineCount = [Text.Encoding]::UTF8.GetString($bytes).Split([char]10).Length
    foreach ($sel in @($entry.selectors)) {
        if ([int]$sel.end -gt $lineCount) {
            throw "XINAO_LEG_A_CONTEXT_LINE_RANGE_EXCEEDS_SOURCE: path=$rel end=$($sel.end) lines=$lineCount"
        }
    }
    if ($null -ne $expectedPins) {
        $pin = $null
        if ($expectedPins -is [hashtable] -or $expectedPins -is [System.Collections.IDictionary]) {
            if ($expectedPins.Contains($rel)) { $pin = [string]$expectedPins[$rel] }
        }
        elseif ($expectedPins.PSObject.Properties.Name -contains $rel) {
            $pin = [string]$expectedPins.$rel
        }
        elseif ($expectedPins.sources) {
            foreach ($row in @($expectedPins.sources)) {
                if ([string]$row.path -eq $rel) { $pin = [string]$row.sha256; break }
            }
        }
        if ([string]::IsNullOrWhiteSpace([string]$pin)) {
            throw "XINAO_LEG_A_CONTEXT_SOURCE_PIN_MISSING: $rel"
        }
        if ([string]$pin.ToLowerInvariant() -cne $sha) {
            throw "XINAO_LEG_A_CONTEXT_SOURCE_DRIFT: path=$rel expected=$pin observed=$sha"
        }
    }
    $sourceIdentities.Add([ordered]@{
            path          = $rel
            role          = [string]$entry.role
            absolute_path = $full
            source_sha256 = $sha
            source_bytes  = $bytes.Length
        }) | Out-Null
}

# Materialize owned slice spec with deterministic JSON via Python (same stack as builder).
$specPath = Join-Path $outputDirFull "xinao_leg_a_context_slice_spec.v1.json"
$manifestPath = Join-Path $outputDirFull "xinao_leg_a_context_slice_manifest.v1.json"
$receiptPath = Join-Path $outputDirFull "xinao_leg_a_context_seal_receipt.v1.json"
$specWorkPath = Join-Path $outputDirFull (".spec_work." + [guid]::NewGuid().ToString("N") + ".json")

$specObject = Get-OwnedSpecObject
# Intermediate PS JSON is only a carrier into Python canonicalization.
Write-TextAtomic -Path $specWorkPath -Text (($specObject | ConvertTo-Json -Depth 8 -Compress))

$canonicalizer = @'
import json
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_bytes()
payload = json.loads(raw.decode("utf-8"))
if payload.get("schema_version") != "xinao.context_slice_spec.v1":
    raise SystemExit("spec schema_version mismatch")
entries = payload.get("entries")
if not isinstance(entries, list) or not entries:
    raise SystemExit("spec entries missing")
# Normalize key order for stable bytes.
normalized = {
    "schema_version": "xinao.context_slice_spec.v1",
    "entries": [
        {
            "path": str(entry["path"]),
            "selectors": [
                {
                    "kind": str(sel["kind"]),
                    "start": int(sel["start"]),
                    "end": int(sel["end"]),
                }
                for sel in entry["selectors"]
            ],
        }
        for entry in entries
    ],
}
text = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
Path(sys.argv[2]).write_bytes(text.encode("utf-8"))
print(text.encode("utf-8").hex()[:16])
'@

$canonTmp = Join-Path $outputDirFull (".canon." + [guid]::NewGuid().ToString("N") + ".py")
Write-TextAtomic -Path $canonTmp -Text $canonicalizer
try {
    $canonOut = & $pythonFull -I -B $canonTmp $specWorkPath $specPath 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "XINAO_LEG_A_CONTEXT_SPEC_CANON_FAILED: $canonOut"
    }
}
finally {
    Remove-Item -LiteralPath $canonTmp -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $specWorkPath -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $specPath -PathType Leaf)) {
    throw "XINAO_LEG_A_CONTEXT_SPEC_WRITE_FAILED"
}
$specSha256 = Get-Sha256LowerFile $specPath

# Invoke the existing repository builder (not a second context platform).
$builderArgs = @(
    "-I", "-B", $builderScript,
    "--root", $mainlineRootFull,
    "--spec", $specPath,
    "--output", $manifestPath,
    "--max-content-bytes", "$MaxContentBytes"
)
$builderOutput = & $pythonFull @builderArgs 2>&1
$builderExit = $LASTEXITCODE
if ($builderExit -ne 0) {
    $joined = ($builderOutput | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    if ($joined -match "max_content_bytes|exceeds max_content") {
        throw "XINAO_LEG_A_CONTEXT_OVERSIZE: $joined"
    }
    if ($joined -match "bounded relative path|escapes root") {
        throw "XINAO_LEG_A_CONTEXT_PATH_ESCAPE: $joined"
    }
    if ($joined -match "not UTF-8|Unicode") {
        throw "XINAO_LEG_A_CONTEXT_SOURCE_ENCODING: $joined"
    }
    if ($joined -match "is not a file|source is not a file") {
        throw "XINAO_LEG_A_CONTEXT_SOURCE_MISSING: $joined"
    }
    throw "XINAO_LEG_A_CONTEXT_BUILDER_FAILED: exit=$builderExit $joined"
}

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "XINAO_LEG_A_CONTEXT_MANIFEST_MISSING_AFTER_BUILD"
}

# Parse builder stdout summary when present; always re-read manifest for hard fields.
$manifestRaw = [IO.File]::ReadAllText($manifestPath, $utf8)
try {
    $manifest = $manifestRaw | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "XINAO_LEG_A_CONTEXT_MANIFEST_INVALID_JSON"
}

if ([string]$manifest.schema_version -cne "xinao.context_slice_manifest.v1") {
    throw "XINAO_LEG_A_CONTEXT_MANIFEST_SCHEMA_MISMATCH"
}
if ($manifest.authority -ne $false -or $manifest.completion_claim_allowed -ne $false) {
    throw "XINAO_LEG_A_CONTEXT_MANIFEST_AUTHORITY_LEAK"
}
if ([string]$manifest.context_sha256 -notmatch '^[0-9a-f]{64}$' -or
    [string]$manifest.source_manifest_sha256 -notmatch '^[0-9a-f]{64}$') {
    throw "XINAO_LEG_A_CONTEXT_MANIFEST_HASH_MISSING"
}
if ([string]$manifest.spec_sha256 -cne $specSha256) {
    throw "XINAO_LEG_A_CONTEXT_SPEC_HASH_MISMATCH"
}

# Re-validate live source hashes against sealed manifest identities (exact drift check).
foreach ($src in @($manifest.sources)) {
    $rel = [string]$src.path
    $full = Get-SourceFileOrThrow -Root $mainlineRootFull -RelativePath $rel
    $liveSha = Get-Sha256LowerFile $full
    if ($liveSha -cne [string]$src.source_sha256) {
        throw "XINAO_LEG_A_CONTEXT_SOURCE_DRIFT: path=$rel expected=$($src.source_sha256) observed=$liveSha"
    }
}

$manifestFileSha256 = Get-Sha256LowerFile $manifestPath

$receipt = [ordered]@{
    schema_version              = $script:SealSchemaVersion
    package_id                  = $script:PackageId
    owned_spec_version          = $script:PackageSpecVersion
    sentinel                    = "XINAO_LEG_A_CONTEXT_SEAL_CANDIDATE_V1"
    authority                   = $false
    completion_claim_allowed    = $false
    candidate_only              = $true
    repair_authorized           = $false
    task_authority              = $false
    includes_outcomes           = $false
    includes_secrets            = $false
    includes_directory_snapshot = $false
    includes_cached_semantic_answers = $false
    mainline_root               = $mainlineRootFull
    repo_root                   = $repoRootFull
    builder_script              = $builderScript
    python_exe                  = $pythonFull
    max_content_bytes           = $MaxContentBytes
    total_content_bytes         = [int]$manifest.total_content_bytes
    spec_path                   = $specPath
    spec_sha256                 = $specSha256
    manifest_path               = $manifestPath
    manifest_file_sha256        = $manifestFileSha256
    context_sha256              = [string]$manifest.context_sha256
    source_manifest_sha256      = [string]$manifest.source_manifest_sha256
    source_file_identities      = @($sourceIdentities)
    false_green_deny            = [string]$manifest.false_green_deny
    not_included                = @(
        "outcomes",
        "secrets",
        "broad_directory_snapshots",
        "cached_semantic_answers",
        "task_authority",
        "completion_claims"
    )
}

$receiptJson = ($receipt | ConvertTo-Json -Depth 8)
Write-TextAtomic -Path $receiptPath -Text $receiptJson

# Public stdout envelope for Invoke-XinaoLegAWorker.ps1 and other callers.
$public = [ordered]@{
    ok                       = $true
    sentinel                 = "XINAO_LEG_A_CONTEXT_SEAL_CANDIDATE_V1"
    schema_version           = $script:SealSchemaVersion
    package_id               = $script:PackageId
    authority                = $false
    completion_claim_allowed = $false
    candidate_only           = $true
    manifest_path            = $manifestPath
    context_sha256           = [string]$manifest.context_sha256
    source_manifest_sha256   = [string]$manifest.source_manifest_sha256
    spec_path                = $specPath
    spec_sha256              = $specSha256
    receipt_path             = $receiptPath
    total_content_bytes      = [int]$manifest.total_content_bytes
    source_file_identities   = @(
        foreach ($row in $sourceIdentities) {
            [ordered]@{
                path          = [string]$row.path
                role          = [string]$row.role
                source_sha256 = [string]$row.source_sha256
                source_bytes  = [int]$row.source_bytes
            }
        }
    )
}

$publicJson = $public | ConvertTo-Json -Depth 8
if (-not $Quiet) {
    Write-Output $publicJson
}
else {
    Write-Output ($public | ConvertTo-Json -Depth 8 -Compress)
}

exit 0
