#Requires -Version 7.0
<#
.SYNOPSIS
  Prepare an isolated, byte-evidenced pure-v1 XINAO legacy-migration proof cone on D:.

.DESCRIPTION
  Candidate-only helper. Copies live pure-v1 state, historical source-renderings, and
  installed Skill bytes into a new destination proof cone; relocates only the cloned
  pointer's two absolute release-manifest paths; emits a strict receipt/inventory; and
  re-verifies the sealed cone in a fresh PowerShell process.

  Never mutates live sources. Never claims migration success or completion authority.
  Codex remains sole Owner/adopter/final verifier.

.NOTES
  Authority=false. completion_claim_allowed=false. migration_executed=false.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DestinationProofRoot,

    [string]$SourceLiveStateRoot = '',
    [string]$SourceInstalledSkillRoot = '',
    [string]$ActiveSourceRenderingRoot = '',
    [string]$PreviousSourceRenderingRoot = '',
    [string]$CandidateSourceRoot = '',
    [string]$ActiveLegacyRepositoryRoot = '',
    [string]$PreviousLegacyRepositoryRoot = '',

    [string]$ApprovedProofBase = 'D:\XINAO_RESEARCH_RUNTIME\proofs\isolated-legacy-migration',

    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$script:OwnedConeCreated = $false
$script:CreatedEmptyDestPendingMarker = $false
$script:OwnedMarkerName = '.xinao-isolated-migration-proof.owned'
$script:ReceiptFileName = 'preparation-receipt.json'
$script:SchemaVersion = 'xinao.isolated_legacy_migration_proof_receipt.v1'
$script:OwnedMarkerSchema = 'xinao.isolated_legacy_migration_proof_owned_marker.v1'

$script:LegacyPointerSchema = 'xinao.researcher_current_pointer.v1'
$script:LegacyReleaseSchema = 'xinao.researcher_release.v1'
$script:ReleaseIdPattern = '^researcher-[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{16}$'
$script:HexSha256Pattern = '^[0-9a-f]{64}$'

$script:LegacyPointerKeys = @(
    'schema_version',
    'release_id',
    'release_manifest_path',
    'release_manifest_sha256',
    'promoted_at',
    'previous_pointer_sha256',
    'previous_release_id',
    'previous_release_manifest_path',
    'previous_release_manifest_sha256'
) | Sort-Object

$script:LegacyReleaseKeys = @(
    'created_at',
    'generic_worker_route_allowed',
    'image_entrypoint',
    'image_id',
    'image_labels',
    'image_tag_observational',
    'release_id',
    'run_namespace',
    'schema_version',
    'skill_hashes',
    'source_identity',
    'state_namespace'
) | Sort-Object

$script:LegacySkillHashKeys = @(
    'capability_registry_sha256',
    'charter_sha256',
    'dockerfile_sha256',
    'entrypoint_sha256',
    'meta_sha256',
    'output_schema_sha256',
    'runtime_lock_sha256',
    'skill_invoker_sha256',
    'skill_md_sha256'
) | Sort-Object

$script:LegacySkillRenderingHashKeys = @(
    'capability_registry_sha256',
    'charter_sha256',
    'meta_sha256',
    'output_schema_sha256',
    'runtime_lock_sha256',
    'skill_invoker_sha256',
    'skill_md_sha256'
) | Sort-Object

$script:LegacyDockerHashKeys = @(
    'dockerfile_sha256',
    'entrypoint_sha256'
) | Sort-Object

$script:ReceiptTopLevelKeys = @(
    'authority',
    'candidate_source_git_identity',
    'completion_claim_allowed',
    'destination',
    'destination_tree_sha256',
    'files',
    'files_count',
    'inventories',
    'live_source_mutated',
    'migration_executed',
    'pointer_relocation',
    'prepared_at',
    'proposed_environment',
    'receipt_content_sha256',
    'receipt_relative_path',
    'schema_version',
    'source',
    'verify_only'
) | Sort-Object

$script:CandidateGitIdentitySchema = 'xinao.isolated_legacy_migration_candidate_git_identity.v1'
$script:CandidateGitProofBranch = 'proof'
$script:CandidateGitCommitMessage = 'xinao isolated migration proof sealed candidate source'
$script:CandidateGitAuthorName = 'xinao-isolated-migration-proof'
$script:CandidateGitAuthorEmail = 'xinao-isolated-migration-proof@invalid'
$script:CandidateGitAuthorDate = '2026-01-01T00:00:00 +0000'
$script:CandidateGitCommitterName = 'xinao-isolated-migration-proof'
$script:CandidateGitCommitterEmail = 'xinao-isolated-migration-proof@invalid'
$script:CandidateGitCommitterDate = '2026-01-01T00:00:00 +0000'
$script:CandidateGitEmptyHooksRelative = '.git/xinao-empty-hooks'

$script:ReceiptCandidateGitIdentityKeys = @(
    'alternates_absent',
    'author_date',
    'author_email',
    'author_name',
    'branch',
    'commit_message',
    'committer_date',
    'committer_email',
    'committer_name',
    'config',
    'external_gitdir_absent',
    'git_dir_relative_path',
    'head_commit',
    'head_tree',
    'hooks_path_relative',
    'repository_kind',
    'schema_version',
    'status_porcelain',
    'tracked_files'
) | Sort-Object

$script:ReceiptCandidateGitConfigKeys = @(
    'commit.gpgsign',
    'core.autocrlf',
    'core.eol',
    'core.filemode',
    'core.hooksPath',
    'core.symlinks',
    'init.defaultBranch',
    'user.email',
    'user.name'
) | Sort-Object

$script:ReceiptCandidateGitTrackedFileKeys = @(
    'content_sha256',
    'git_blob_sha1',
    'relative_path',
    'size'
) | Sort-Object

$script:ReceiptSourceKeys = @(
    'active_legacy_provenance_tree_sha256',
    'active_legacy_repository_root',
    'active_manifest_path',
    'active_manifest_sha256',
    'active_release_id',
    'active_rendering_tree_sha256',
    'active_source_rendering_root',
    'candidate_source_root',
    'candidate_source_tree_sha256',
    'installed_skill_root',
    'installed_skill_tree_sha256',
    'live_state_root',
    'pointer_path',
    'pointer_sha256_original',
    'previous_legacy_provenance_tree_sha256',
    'previous_legacy_repository_root',
    'previous_manifest_path',
    'previous_manifest_sha256',
    'previous_release_id',
    'previous_rendering_tree_sha256',
    'previous_source_rendering_root'
) | Sort-Object

$script:ReceiptDestinationKeys = @(
    'active_legacy_provenance_root',
    'active_manifest_path',
    'active_rendering_root',
    'approved_proof_base',
    'candidate_source_root',
    'installed_skill_root',
    'original_pointer_path',
    'pointer_path',
    'previous_legacy_provenance_root',
    'previous_manifest_path',
    'previous_rendering_root',
    'proof_root',
    'researcher_run_root',
    'skill_state_root'
) | Sort-Object

$script:ReceiptPointerRelocationKeys = @(
    'keys_relocated',
    'original_pointer_sha256',
    'original_previous_release_manifest_path',
    'original_release_manifest_path',
    'relocated_pointer_sha256',
    'relocated_previous_release_manifest_path',
    'relocated_release_manifest_path'
) | Sort-Object

$script:ReceiptEnvironmentKeys = @(
    'XINAO_INSTALLED_SKILL_ROOT',
    'XINAO_MIGRATION_SOURCE_ROOT',
    'XINAO_RESEARCHER_RUN_ROOT',
    'XINAO_SKILL_STATE_ROOT'
) | Sort-Object

$script:ReceiptInventoryKeys = @(
    'active_legacy_provenance',
    'active_legacy_provenance_tree_sha256',
    'active_rendering',
    'active_rendering_tree_sha256',
    'candidate_source',
    'candidate_source_tree_sha256',
    'installed_skill',
    'installed_skill_tree_sha256',
    'previous_legacy_provenance',
    'previous_legacy_provenance_tree_sha256',
    'previous_rendering',
    'previous_rendering_tree_sha256'
) | Sort-Object

$script:InventoryRowKeys = @(
    'relative_path',
    'sha256',
    'size',
    'type'
) | Sort-Object

function Fail {
    param([Parameter(Mandatory)][string]$Code, [Parameter(Mandatory)][string]$Detail)
    throw "${Code}: $Detail"
}

function Get-FullLiteralPath {
    param([Parameter(Mandatory)][string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        Fail 'PATH_EMPTY' 'Path is empty.'
    }
    if ($PathValue -match '%[^%]+%' -or $PathValue -match '\$env:') {
        Fail 'PATH_UNRESOLVED_VARIABLE' $PathValue
    }
    try {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    catch {
        Fail 'PATH_INVALID' "$PathValue :: $($_.Exception.Message)"
    }
}

function Test-PathsEqual {
    param([Parameter(Mandatory)][string]$Left, [Parameter(Mandatory)][string]$Right)
    return ([string]::Equals(
            [System.IO.Path]::GetFullPath($Left).TrimEnd('\', '/'),
            [System.IO.Path]::GetFullPath($Right).TrimEnd('\', '/'),
            [System.StringComparison]::OrdinalIgnoreCase
        ))
}

function Test-IsStrictChildPath {
    param(
        [Parameter(Mandatory)][string]$Parent,
        [Parameter(Mandatory)][string]$Child
    )
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    $childFull = [System.IO.Path]::GetFullPath($Child).TrimEnd('\', '/')
    if (Test-PathsEqual $parentFull $childFull) { return $false }
    $prefix = $parentFull + [System.IO.Path]::DirectorySeparatorChar
    return $childFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-IsReparsePoint {
    param([Parameter(Mandatory)][string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue)) { return $false }
    $item = Get-Item -LiteralPath $PathValue -Force
    return [bool]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
}

function Assert-NoReparseInChain {
    param(
        [Parameter(Mandatory)][string]$PathValue,
        [Parameter(Mandatory)][string]$ReasonCode
    )
    $full = Get-FullLiteralPath $PathValue
    $current = $full
    while ($true) {
        if (Test-Path -LiteralPath $current) {
            if (Test-IsReparsePoint $current) {
                Fail $ReasonCode "reparse forbidden: $current"
            }
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or (Test-PathsEqual $parent $current)) {
            break
        }
        $current = $parent
    }
}

function Get-FileHardLinkCount {
    param([Parameter(Mandatory)][string]$PathValue)
    $full = [System.IO.Path]::GetFullPath($PathValue)
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        Fail 'HARDLINK_PROBE_FAILED' "missing: $full"
    }
    # Deterministic synthetic fail-closed branch for tests; never infer nlink=1.
    if ($env:XINAO_TEST_FORCE_HARDLINK_PROBE_FAILURE -eq '1') {
        Fail 'HARDLINK_PROBE_FAILED' "forced probe failure: $full"
    }

    if ($IsLinux) {
        # Keep link-count enforcement on Linux without invoking either Windows
        # probe. Use a fixed system binary, pass the path as one literal
        # argument after `--`, and accept only one positive integer.
        $statPath = @('/usr/bin/stat', '/bin/stat') |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1
        if ([string]::IsNullOrWhiteSpace([string]$statPath)) {
            Fail 'HARDLINK_PROBE_FAILED' "$full :: linux stat executable missing"
        }

        try {
            $statOutput = @(& $statPath '--format=%h' '--' $full 2>&1)
            $statExitCode = $LASTEXITCODE
            $statText = (($statOutput | ForEach-Object { [string]$_ }) -join "`n").Trim()
            if ($statExitCode -eq 0 -and $statText -match '^[1-9][0-9]*$') {
                return [uint64]::Parse(
                    $statText,
                    [System.Globalization.CultureInfo]::InvariantCulture
                )
            }
            $statError = "exit=$statExitCode output=$statText"
        }
        catch {
            $statError = $_.Exception.Message
        }
        Fail 'HARDLINK_PROBE_FAILED' "$full :: linux-stat=$statError"
    }

    if (-not $IsWindows) {
        Fail 'HARDLINK_PROBE_FAILED' "$full :: unsupported platform: $([System.Environment]::OSVersion.Platform)"
    }

    $winError = $null
    try {
        if (-not ('XinaoLinkCountUtil' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class XinaoLinkCountUtil {
    [StructLayout(LayoutKind.Sequential)]
    struct BY_HANDLE_FILE_INFORMATION {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr CreateFileW(
        string lpFileName, uint dwDesiredAccess, uint dwShareMode,
        IntPtr lpSecurityAttributes, uint dwCreationDisposition,
        uint dwFlagsAndAttributes, IntPtr hTemplateFile);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetFileInformationByHandle(IntPtr hFile, out BY_HANDLE_FILE_INFORMATION info);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool CloseHandle(IntPtr hObject);
    static string LongPath(string path) {
        if (path.StartsWith(@"\\?\", StringComparison.Ordinal)) return path;
        if (path.StartsWith(@"\\", StringComparison.Ordinal)) return @"\\?\UNC\" + path.Substring(2);
        return @"\\?\" + path;
    }
    public static uint GetNumberOfLinks(string path) {
        // FILE_READ_ATTRIBUTES=0x80 avoids content locks; OPEN_EXISTING=3; share R/W/D=7
        string winPath = LongPath(path);
        IntPtr handle = CreateFileW(winPath, 0x80, 0x7, IntPtr.Zero, 3, 0, IntPtr.Zero);
        if (handle == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            BY_HANDLE_FILE_INFORMATION info;
            if (!GetFileInformationByHandle(handle, out info))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            return info.NumberOfLinks;
        } finally {
            CloseHandle(handle);
        }
    }
}
'@
        }
        return [uint32][XinaoLinkCountUtil]::GetNumberOfLinks($full)
    }
    catch {
        $winError = $_.Exception.Message
    }

    $fsutilError = $null
    try {
        $output = & fsutil.exe hardlink list "$full" 2>&1
        if ($LASTEXITCODE -eq 0) {
            $lines = @($output | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
            if ($lines.Count -ge 1) {
                return [uint32]$lines.Count
            }
            $fsutilError = 'fsutil returned zero link paths'
        }
        else {
            $fsutilError = "fsutil exit=$LASTEXITCODE :: $output"
        }
    }
    catch {
        $fsutilError = $_.Exception.Message
    }

    Fail 'HARDLINK_PROBE_FAILED' "$full :: native=$winError :: fallback=$fsutilError"
}

function Get-Sha256Bytes {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash($Bytes)
        return ([System.BitConverter]::ToString($hash) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-Sha256File {
    param([Parameter(Mandatory)][string]$PathValue)
    Assert-RegularFileSafe $PathValue -ReasonCode 'FILE_IDENTITY_INVALID'
    $bytes = [System.IO.File]::ReadAllBytes($PathValue)
    return Get-Sha256Bytes $bytes
}

function Assert-RegularFileSafe {
    param(
        [Parameter(Mandatory)][string]$PathValue,
        [Parameter(Mandatory)][string]$ReasonCode,
        [switch]$AllowHardLink
    )
    if (-not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
        Fail $ReasonCode "missing regular file: $PathValue"
    }
    Assert-NoReparseInChain $PathValue $ReasonCode
    $item = Get-Item -LiteralPath $PathValue -Force
    if ($item.PSIsContainer) {
        Fail $ReasonCode "directory not file: $PathValue"
    }
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        Fail $ReasonCode "reparse forbidden: $PathValue"
    }
    if (-not $AllowHardLink) {
        $links = Get-FileHardLinkCount $PathValue
        if ($links -ne 1) {
            Fail $ReasonCode "hardlink ambiguity (nlink=$links): $PathValue"
        }
    }
}

function Assert-DirectorySafe {
    param(
        [Parameter(Mandatory)][string]$PathValue,
        [Parameter(Mandatory)][string]$ReasonCode
    )
    if (-not (Test-Path -LiteralPath $PathValue -PathType Container)) {
        Fail $ReasonCode "missing directory: $PathValue"
    }
    Assert-NoReparseInChain $PathValue $ReasonCode
}

function ConvertTo-CanonicalJsonText {
    param([Parameter(Mandatory)]$Value)

    function Escape-JsonString([string]$Text) {
        $sb = [System.Text.StringBuilder]::new()
        [void]$sb.Append('"')
        foreach ($ch in $Text.ToCharArray()) {
            switch ($ch) {
                '"' { [void]$sb.Append('\"') }
                '\' { [void]$sb.Append('\\') }
                "`b" { [void]$sb.Append('\b') }
                "`f" { [void]$sb.Append('\f') }
                "`n" { [void]$sb.Append('\n') }
                "`r" { [void]$sb.Append('\r') }
                "`t" { [void]$sb.Append('\t') }
                default {
                    $code = [int][char]$ch
                    if ($code -lt 0x20) {
                        [void]$sb.AppendFormat('\u{0:x4}', $code)
                    }
                    else {
                        [void]$sb.Append($ch)
                    }
                }
            }
        }
        [void]$sb.Append('"')
        return $sb.ToString()
    }

    function Emit($Node) {
        if ($null -eq $Node) { return 'null' }
        if ($Node -is [bool]) { if ($Node) { return 'true' } else { return 'false' } }
        if ($Node -is [byte] -or $Node -is [int16] -or $Node -is [uint16] -or
            $Node -is [int] -or $Node -is [uint32] -or $Node -is [long] -or
            $Node -is [uint64] -or $Node -is [decimal] -or $Node -is [double] -or
            $Node -is [float] -or $Node -is [bigint]) {
            if ($Node -is [double] -or $Node -is [float]) {
                if ([double]::IsNaN([double]$Node) -or [double]::IsInfinity([double]$Node)) {
                    Fail 'JSON_CANONICALIZATION_FAILED' 'non-finite number'
                }
            }
            return ([string]$Node)
        }
        if ($Node -is [string]) { return (Escape-JsonString $Node) }
        if ($Node -is [datetime]) {
            return (Escape-JsonString ($Node.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")))
        }
        if ($Node -is [System.Collections.IDictionary]) {
            $keys = @($Node.Keys | ForEach-Object { [string]$_ })
            [Array]::Sort($keys, [System.StringComparer]::Ordinal)
            $parts = foreach ($key in $keys) {
                $k = Escape-JsonString $key
                $v = Emit $Node[$key]
                "${k}:${v}"
            }
            return '{' + ($parts -join ',') + '}'
        }
        if ($Node -is [pscustomobject]) {
            $map = [ordered]@{}
            foreach ($prop in $Node.PSObject.Properties) {
                $map[$prop.Name] = $prop.Value
            }
            return (Emit $map)
        }
        if ($Node -is [System.Collections.IEnumerable]) {
            $parts = foreach ($item in $Node) { Emit $item }
            return '[' + ($parts -join ',') + ']'
        }
        Fail 'JSON_CANONICALIZATION_FAILED' "unsupported type: $($Node.GetType().FullName)"
    }

    return ((Emit $Value) + "`n")
}

function Write-Utf8NoBomFileAtomic {
    param(
        [Parameter(Mandatory)][string]$PathValue,
        [Parameter(Mandatory)][string]$Text,
        [switch]$CreateNew
    )
    $full = Get-FullLiteralPath $PathValue
    $parent = Split-Path -Parent $full
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if ($CreateNew -and (Test-Path -LiteralPath $full)) {
        Fail 'IMMUTABLE_PATH_EXISTS' $full
    }
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $bytes = $utf8.GetBytes($Text)
    $temp = Join-Path $parent ('.{0}.{1}.{2}.tmp' -f (Split-Path -Leaf $full), $PID, ([guid]::NewGuid().ToString('N')))
    try {
        [System.IO.File]::WriteAllBytes($temp, $bytes)
        if ($CreateNew) {
            [System.IO.File]::Move($temp, $full)
        }
        else {
            [System.IO.File]::Move($temp, $full, $true)
        }
    }
    catch {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

function Write-BytesAtomic {
    param(
        [Parameter(Mandatory)][string]$PathValue,
        [Parameter(Mandatory)][byte[]]$Bytes,
        [switch]$CreateNew
    )
    $full = Get-FullLiteralPath $PathValue
    $parent = Split-Path -Parent $full
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if ($CreateNew -and (Test-Path -LiteralPath $full)) {
        Fail 'IMMUTABLE_PATH_EXISTS' $full
    }
    $temp = Join-Path $parent ('.{0}.{1}.{2}.tmp' -f (Split-Path -Leaf $full), $PID, ([guid]::NewGuid().ToString('N')))
    try {
        [System.IO.File]::WriteAllBytes($temp, $Bytes)
        if ($CreateNew) {
            [System.IO.File]::Move($temp, $full)
        }
        else {
            [System.IO.File]::Move($temp, $full, $true)
        }
    }
    catch {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

function ConvertFrom-StrictJsonText {
    param([Parameter(Mandatory)][string]$Text)
    # System.Text.Json preserves ISO-8601 strings (unlike ConvertFrom-Json DateTime coercion).
    try {
        $document = [System.Text.Json.JsonDocument]::Parse($Text)
    }
    catch {
        Fail 'JSON_READ_FAILED' $_.Exception.Message
    }
    function Convert-JsonElement {
        param([System.Text.Json.JsonElement]$Element)
        switch ($Element.ValueKind) {
            'Object' {
                $map = [ordered]@{}
                foreach ($property in $Element.EnumerateObject()) {
                    $map[$property.Name] = Convert-JsonElement -Element $property.Value
                }
                return $map
            }
            'Array' {
                $items = [System.Collections.Generic.List[object]]::new()
                foreach ($item in $Element.EnumerateArray()) {
                    $items.Add((Convert-JsonElement -Element $item)) | Out-Null
                }
                return @($items.ToArray())
            }
            'String' { return $Element.GetString() }
            'Number' {
                $raw = $Element.GetRawText()
                if ($raw -match '^-?\d+$') {
                    return [int64]$raw
                }
                return [double]::Parse($raw, [System.Globalization.CultureInfo]::InvariantCulture)
            }
            'True' { return $true }
            'False' { return $false }
            'Null' { return $null }
            default { Fail 'JSON_READ_FAILED' "unsupported kind: $($Element.ValueKind)" }
        }
    }
    return (Convert-JsonElement -Element $document.RootElement)
}

function Read-JsonObjectFile {
    param(
        [Parameter(Mandatory)][string]$PathValue,
        [string]$ReasonCode = 'JSON_READ_FAILED'
    )
    Assert-RegularFileSafe $PathValue -ReasonCode $ReasonCode
    $bytes = [System.IO.File]::ReadAllBytes($PathValue)
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    $obj = ConvertFrom-StrictJsonText -Text $text
    if ($null -eq $obj -or -not ($obj -is [System.Collections.IDictionary])) {
        Fail 'JSON_OBJECT_REQUIRED' $PathValue
    }
    return $obj
}

function Get-SortedRelativeInventory {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$ReasonCode,
        [string[]]$IgnoreNames = @(),
        [string[]]$IgnoreDirectoryNames = @()
    )
    Assert-DirectorySafe $Root $ReasonCode
    $rootFull = Get-FullLiteralPath $Root
    $rows = [System.Collections.Generic.List[object]]::new()
    $stack = [System.Collections.Generic.Stack[string]]::new()
    $stack.Push($rootFull)
    while ($stack.Count -gt 0) {
        $current = $stack.Pop()
        if (Test-IsReparsePoint $current) {
            Fail $ReasonCode "reparse forbidden: $current"
        }
        $entries = @(Get-ChildItem -LiteralPath $current -Force | Sort-Object -Property Name)
        foreach ($entry in $entries) {
            $name = $entry.Name
            if ($name -in $IgnoreNames) { continue }
            $path = $entry.FullName
            if ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                Fail $ReasonCode "reparse forbidden: $path"
            }
            if ($entry.PSIsContainer) {
                if ($name -in $IgnoreDirectoryNames) { continue }
                $stack.Push($path)
                continue
            }
            Assert-RegularFileSafe $path -ReasonCode $ReasonCode
            $rel = [System.IO.Path]::GetRelativePath($rootFull, $path).Replace('\', '/')
            if ([string]::IsNullOrWhiteSpace($rel) -or $rel.StartsWith('..') -or $rel.Contains('/../')) {
                Fail $ReasonCode "path escape: $rel"
            }
            $bytes = [System.IO.File]::ReadAllBytes($path)
            $rows.Add([ordered]@{
                    relative_path = $rel
                    type          = 'file'
                    size          = [int64]$bytes.LongLength
                    sha256        = (Get-Sha256Bytes $bytes)
                }) | Out-Null
        }
    }
    # Stable ordinal sort (culture-independent; matches cross-tool inventory contracts).
    $array = @($rows)
    if ($array.Count -gt 1) {
        [Array]::Sort(
            $array,
            [System.Comparison[object]] {
                param($left, $right)
                return [string]::CompareOrdinal(
                    [string]$left.relative_path,
                    [string]$right.relative_path
                )
            }
        )
    }
    # Collision check (case-insensitive on Windows).
    $seen = @{}
    foreach ($row in $array) {
        $key = $row.relative_path.ToLowerInvariant()
        if ($seen.ContainsKey($key)) {
            Fail $ReasonCode "path collision: $($row.relative_path)"
        }
        $seen[$key] = $true
    }
    return $array
}

function Get-InventoryTreeSha256 {
    param([Parameter(Mandatory)]$InventoryRows)
    $payload = ConvertTo-CanonicalJsonText -Value @($InventoryRows)
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    return (Get-Sha256Bytes ($utf8.GetBytes($payload)))
}

function Assert-ExactKeySet {
    param(
        [Parameter(Mandatory)]$Object,
        [Parameter(Mandatory)][string[]]$ExpectedKeys,
        [Parameter(Mandatory)][string]$ReasonCode,
        [Parameter(Mandatory)][string]$Context
    )
    if ($null -eq $Object -or -not ($Object -is [System.Collections.IDictionary])) {
        Fail $ReasonCode "object required: $Context"
    }
    $actual = @($Object.Keys | ForEach-Object { [string]$_ } | Sort-Object)
    $expected = @($ExpectedKeys | Sort-Object)
    if (($actual -join '|') -ne ($expected -join '|')) {
        Fail $ReasonCode "key set mismatch: $Context actual=$($actual -join ',') expected=$($expected -join ',')"
    }
}

function Assert-InventoryEqual {
    param(
        [Parameter(Mandatory)]$Left,
        [Parameter(Mandatory)]$Right,
        [Parameter(Mandatory)][string]$ReasonCode,
        [Parameter(Mandatory)][string]$Context
    )
    $leftArr = @($Left)
    $rightArr = @($Right)
    if ($leftArr.Count -ne $rightArr.Count) {
        Fail $ReasonCode "count mismatch ($Context): left=$($leftArr.Count) right=$($rightArr.Count)"
    }
    for ($i = 0; $i -lt $leftArr.Count; $i++) {
        $l = $leftArr[$i]
        $r = $rightArr[$i]
        if ($l -is [System.Collections.IDictionary]) {
            $lRel = [string]$l['relative_path']; $lSha = [string]$l['sha256']; $lSize = [int64]$l['size']; $lType = [string]$l['type']
        }
        else {
            $lRel = [string]$l.relative_path; $lSha = [string]$l.sha256; $lSize = [int64]$l.size; $lType = [string]$l.type
        }
        if ($r -is [System.Collections.IDictionary]) {
            $rRel = [string]$r['relative_path']; $rSha = [string]$r['sha256']; $rSize = [int64]$r['size']; $rType = [string]$r['type']
        }
        else {
            $rRel = [string]$r.relative_path; $rSha = [string]$r.sha256; $rSize = [int64]$r.size; $rType = [string]$r.type
        }
        if ($lRel -ne $rRel -or $lSha -ne $rSha -or $lSize -ne $rSize -or $lType -ne $rType) {
            Fail $ReasonCode "row drift ($Context): $lRel"
        }
    }
}

function Assert-InventoryRowsSchema {
    param(
        [Parameter(Mandatory)]$Rows,
        [Parameter(Mandatory)][string]$ReasonCode,
        [Parameter(Mandatory)][string]$Context
    )
    $arr = @($Rows)
    foreach ($row in $arr) {
        if ($null -eq $row -or -not ($row -is [System.Collections.IDictionary])) {
            Fail $ReasonCode "inventory row object required: $Context"
        }
        Assert-ExactKeySet -Object $row -ExpectedKeys $script:InventoryRowKeys -ReasonCode $ReasonCode -Context "$Context.row"
        if ([string]$row['type'] -ne 'file') {
            Fail $ReasonCode "inventory type must be file: $Context"
        }
        if ([string]::IsNullOrWhiteSpace([string]$row['relative_path'])) {
            Fail $ReasonCode "inventory relative_path empty: $Context"
        }
        if ([string]$row['sha256'] -notmatch $script:HexSha256Pattern) {
            Fail $ReasonCode "inventory sha256 invalid: $Context/$($row['relative_path'])"
        }
        try {
            [void][int64]$row['size']
        }
        catch {
            Fail $ReasonCode "inventory size invalid: $Context/$($row['relative_path'])"
        }
    }
}

function Copy-ExactTree {
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$DestinationRoot,
        [Parameter(Mandatory)][string]$ReasonCode,
        $ExpectedInventory = $null,
        [string]$ExpectedTreeSha256 = ''
    )
    $rows = Get-SortedRelativeInventory -Root $SourceRoot -ReasonCode $ReasonCode
    if ($null -ne $ExpectedInventory) {
        Assert-InventoryEqual -Left $ExpectedInventory -Right $rows -ReasonCode $ReasonCode -Context "preflight-bind:$SourceRoot"
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedTreeSha256)) {
        $observedTree = Get-InventoryTreeSha256 $rows
        if ($observedTree -ne $ExpectedTreeSha256) {
            Fail $ReasonCode "preflight tree sha mismatch: $SourceRoot"
        }
    }
    if (Test-Path -LiteralPath $DestinationRoot) {
        Fail $ReasonCode "destination exists: $DestinationRoot"
    }
    New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
    foreach ($row in $rows) {
        $rel = if ($row -is [System.Collections.IDictionary]) { [string]$row['relative_path'] } else { [string]$row.relative_path }
        $sha = if ($row -is [System.Collections.IDictionary]) { [string]$row['sha256'] } else { [string]$row.sha256 }
        $src = Join-Path $SourceRoot (($rel -split '/') -join [System.IO.Path]::DirectorySeparatorChar)
        $dst = Join-Path $DestinationRoot (($rel -split '/') -join [System.IO.Path]::DirectorySeparatorChar)
        $bytes = [System.IO.File]::ReadAllBytes($src)
        if ((Get-Sha256Bytes $bytes) -ne $sha) {
            Fail $ReasonCode "source changed while copying: $src"
        }
        Write-BytesAtomic -PathValue $dst -Bytes $bytes -CreateNew
    }
    $destRows = Get-SortedRelativeInventory -Root $DestinationRoot -ReasonCode $ReasonCode
    Assert-InventoryEqual -Left $rows -Right $destRows -ReasonCode $ReasonCode -Context "post-copy:$DestinationRoot"
    return $destRows
}

function Get-CandidateSourceInventory {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$ReasonCode
    )
    Assert-DirectorySafe $Root $ReasonCode
    $skillRoot = Join-Path $Root 'skills\xinao'
    $dockerRoot = Join-Path $Root 'docker\xinao-researcher'
    Assert-DirectorySafe $skillRoot $ReasonCode
    Assert-DirectorySafe $dockerRoot $ReasonCode
    $dockerfile = Join-Path $dockerRoot 'Dockerfile'
    $entrypoint = Join-Path $dockerRoot 'entrypoint.py'
    Assert-RegularFileSafe $dockerfile -ReasonCode $ReasonCode
    Assert-RegularFileSafe $entrypoint -ReasonCode $ReasonCode

    $rows = [System.Collections.Generic.List[object]]::new()
    foreach ($pair in @(
            @{ Prefix = 'skills/xinao'; Path = $skillRoot },
            @{ Prefix = 'docker/xinao-researcher'; Path = $dockerRoot }
        )) {
        $sub = Get-SortedRelativeInventory -Root $pair.Path -ReasonCode $ReasonCode
        foreach ($row in $sub) {
            $rel = if ($row -is [System.Collections.IDictionary]) { [string]$row['relative_path'] } else { [string]$row.relative_path }
            $sha = if ($row -is [System.Collections.IDictionary]) { [string]$row['sha256'] } else { [string]$row.sha256 }
            $size = if ($row -is [System.Collections.IDictionary]) { [int64]$row['size'] } else { [int64]$row.size }
            $rows.Add([ordered]@{
                    relative_path = "$($pair.Prefix)/$rel"
                    type          = 'file'
                    size          = $size
                    sha256        = $sha
                }) | Out-Null
        }
    }
    $array = @($rows)
    if ($array.Count -gt 1) {
        [Array]::Sort(
            $array,
            [System.Comparison[object]] {
                param($left, $right)
                return [string]::CompareOrdinal(
                    [string]$left.relative_path,
                    [string]$right.relative_path
                )
            }
        )
    }
    return $array
}

function Copy-CandidateSourceTree {
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$DestinationRoot,
        [Parameter(Mandatory)]$ExpectedInventory,
        [Parameter(Mandatory)][string]$ExpectedTreeSha256,
        [Parameter(Mandatory)][string]$ReasonCode
    )
    $liveRows = Get-CandidateSourceInventory -Root $SourceRoot -ReasonCode $ReasonCode
    Assert-InventoryEqual -Left $ExpectedInventory -Right $liveRows -ReasonCode $ReasonCode -Context 'candidate-preflight-bind'
    $liveTree = Get-InventoryTreeSha256 $liveRows
    if ($liveTree -ne $ExpectedTreeSha256) {
        Fail $ReasonCode "candidate preflight tree sha mismatch: $SourceRoot"
    }
    if (Test-Path -LiteralPath $DestinationRoot) {
        Fail $ReasonCode "destination exists: $DestinationRoot"
    }
    New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
    foreach ($row in $liveRows) {
        $rel = [string]$row.relative_path
        $src = Join-Path $SourceRoot (($rel -split '/') -join [System.IO.Path]::DirectorySeparatorChar)
        $dst = Join-Path $DestinationRoot (($rel -split '/') -join [System.IO.Path]::DirectorySeparatorChar)
        Assert-RegularFileSafe $src -ReasonCode $ReasonCode
        $bytes = [System.IO.File]::ReadAllBytes($src)
        if ((Get-Sha256Bytes $bytes) -ne [string]$row.sha256) {
            Fail $ReasonCode "candidate source changed while copying: $src"
        }
        Write-BytesAtomic -PathValue $dst -Bytes $bytes -CreateNew
    }
    $destRows = Get-CandidateSourceInventory -Root $DestinationRoot -ReasonCode $ReasonCode
    Assert-InventoryEqual -Left $liveRows -Right $destRows -ReasonCode $ReasonCode -Context 'candidate-post-copy'
    $destTree = Get-InventoryTreeSha256 $destRows
    if ($destTree -ne $ExpectedTreeSha256) {
        Fail $ReasonCode "candidate post-copy tree sha mismatch: $DestinationRoot"
    }
    return $destRows
}

function Resolve-GitExecutable {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($null -eq $cmd -or [string]::IsNullOrWhiteSpace([string]$cmd.Source)) {
        Fail 'GIT_EXECUTABLE_MISSING' 'git is not available on PATH'
    }
    return [string]$cmd.Source
}

function Get-IsolatedGitBaseEnvironment {
    # Force local-only Git configuration; never inherit user/system identity or filters.
    $emptyConfig = Join-Path ([System.IO.Path]::GetTempPath()) ('xinao-empty-gitconfig-{0}.cfg' -f $PID)
    if (-not (Test-Path -LiteralPath $emptyConfig -PathType Leaf)) {
        [System.IO.File]::WriteAllBytes($emptyConfig, [byte[]]@())
    }
    return [ordered]@{
        GIT_CONFIG_NOSYSTEM   = '1'
        GIT_CONFIG_GLOBAL     = $emptyConfig
        GIT_TERMINAL_PROMPT   = '0'
        GIT_OPTIONAL_LOCKS    = '0'
        GIT_LFS_SKIP_SMUDGE    = '1'
        GIT_CONFIG_COUNT       = '0'
    }
}

function Invoke-SealedGit {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string[]]$GitArguments,
        [hashtable]$ExtraEnv = @{},
        [switch]$AllowNonZero
    )
    $git = Resolve-GitExecutable
    $repoFull = Get-FullLiteralPath $RepoRoot
    $baseEnv = Get-IsolatedGitBaseEnvironment
    $saved = @{}
    $allKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($key in @($baseEnv.Keys)) { [void]$allKeys.Add([string]$key) }
    foreach ($key in @($ExtraEnv.Keys)) { [void]$allKeys.Add([string]$key) }
    try {
        foreach ($key in $allKeys) {
            $saved[$key] = [System.Environment]::GetEnvironmentVariable($key, 'Process')
            if ($ExtraEnv.ContainsKey($key)) {
                [System.Environment]::SetEnvironmentVariable($key, [string]$ExtraEnv[$key], 'Process')
            }
            elseif ($baseEnv.Contains($key)) {
                [System.Environment]::SetEnvironmentVariable($key, [string]$baseEnv[$key], 'Process')
            }
        }
        $raw = & $git -C $repoFull @GitArguments 2>&1
        $code = $LASTEXITCODE
        $text = (($raw | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).TrimEnd()
        if (-not $AllowNonZero -and $code -ne 0) {
            Fail 'GIT_COMMAND_FAILED' ("git {0} exit={1} :: {2}" -f ($GitArguments -join ' '), $code, $text)
        }
        return [ordered]@{
            exit_code = [int]$code
            stdout    = $text
        }
    }
    finally {
        foreach ($key in $saved.Keys) {
            [System.Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process')
        }
    }
}

function Assert-GitDirIsLocalRegular {
    param(
        [Parameter(Mandatory)][string]$CandidateRoot,
        [Parameter(Mandatory)][string]$ReasonCode
    )
    $root = Get-FullLiteralPath $CandidateRoot
    $gitPath = Join-Path $root '.git'
    if (-not (Test-Path -LiteralPath $gitPath)) {
        Fail $ReasonCode 'missing .git'
    }
    Assert-NoReparseInChain $gitPath $ReasonCode
    $item = Get-Item -LiteralPath $gitPath -Force
    if (-not $item.PSIsContainer) {
        # A .git file is an external gitdir/worktree pointer — forbidden.
        $pointerText = ''
        try {
            $pointerText = [System.IO.File]::ReadAllText($gitPath)
        }
        catch {
            $pointerText = '<unreadable>'
        }
        Fail $ReasonCode "external .git pointer forbidden: $pointerText"
    }
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        Fail $ReasonCode "reparse forbidden on .git: $gitPath"
    }
    foreach ($forbidden in @(
            (Join-Path $gitPath 'commondir'),
            (Join-Path $gitPath 'objects\info\alternates'),
            (Join-Path $gitPath 'worktrees')
        )) {
        if (Test-Path -LiteralPath $forbidden) {
            if ((Test-Path -LiteralPath $forbidden -PathType Container)) {
                $children = @(Get-ChildItem -LiteralPath $forbidden -Force -ErrorAction SilentlyContinue)
                if ($children.Count -gt 0) {
                    Fail $ReasonCode "external git topology present: $forbidden"
                }
            }
            else {
                $bytes = [System.IO.File]::ReadAllBytes($forbidden)
                if ($bytes.LongLength -gt 0) {
                    Fail $ReasonCode "external git topology present: $forbidden"
                }
            }
        }
    }
    # Reject submodule / gitfile indirection under product paths is handled by inventory reparse checks.
    return $gitPath
}

function Get-SealedCandidateTrackedGitFiles {
    param(
        [Parameter(Mandatory)][string]$CandidateRoot,
        [Parameter(Mandatory)]$ExpectedInventory,
        [Parameter(Mandatory)][string]$ReasonCode
    )
    $ls = Invoke-SealedGit -RepoRoot $CandidateRoot -GitArguments @('ls-files')
    $tracked = @()
    if (-not [string]::IsNullOrWhiteSpace($ls.stdout)) {
        $tracked = @(
            $ls.stdout -split "`r?`n" |
                ForEach-Object { $_.Trim() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
    }
    $expectedPaths = @($ExpectedInventory | ForEach-Object {
            if ($_ -is [System.Collections.IDictionary]) { [string]$_['relative_path'] } else { [string]$_.relative_path }
        })
    $trackedSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($path in $tracked) {
        if (-not $trackedSet.Add([string]$path)) {
            Fail $ReasonCode "duplicate tracked path: $path"
        }
    }
    $expectedSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($path in $expectedPaths) {
        if (-not $expectedSet.Add([string]$path)) {
            Fail $ReasonCode "duplicate expected path: $path"
        }
    }
    if ($trackedSet.Count -ne $expectedSet.Count) {
        Fail $ReasonCode "tracked set count drift: actual=$($trackedSet.Count) expected=$($expectedSet.Count)"
    }
    foreach ($path in $expectedSet) {
        if (-not $trackedSet.Contains($path)) {
            Fail $ReasonCode "tracked set missing path: $path"
        }
    }
    foreach ($path in $trackedSet) {
        if (-not $expectedSet.Contains($path)) {
            Fail $ReasonCode "tracked set extra path: $path"
        }
    }

    $rows = [System.Collections.Generic.List[object]]::new()
    foreach ($row in @($ExpectedInventory)) {
        $rel = if ($row -is [System.Collections.IDictionary]) { [string]$row['relative_path'] } else { [string]$row.relative_path }
        $sha = if ($row -is [System.Collections.IDictionary]) { [string]$row['sha256'] } else { [string]$row.sha256 }
        $size = if ($row -is [System.Collections.IDictionary]) { [int64]$row['size'] } else { [int64]$row.size }
        $abs = Join-Path $CandidateRoot (($rel -split '/') -join [System.IO.Path]::DirectorySeparatorChar)
        Assert-RegularFileSafe $abs -ReasonCode $ReasonCode
        $bytes = [System.IO.File]::ReadAllBytes($abs)
        if ((Get-Sha256Bytes $bytes) -ne $sha) {
            Fail $ReasonCode "product bytes drifted before/after git seal: $rel"
        }
        if ([int64]$bytes.LongLength -ne $size) {
            Fail $ReasonCode "product size drift: $rel"
        }
        $blob = Invoke-SealedGit -RepoRoot $CandidateRoot -GitArguments @('rev-parse', "HEAD:$rel")
        $blobId = [string]$blob.stdout.Trim()
        if ($blobId -notmatch '^[0-9a-f]{40,64}$') {
            Fail $ReasonCode "invalid blob id for $rel : $blobId"
        }
        $cat = Invoke-SealedGit -RepoRoot $CandidateRoot -GitArguments @('cat-file', '-p', $blobId)
        # cat-file -p returns blob bytes as string; re-read via hash-object comparison instead.
        $hashObj = Invoke-SealedGit -RepoRoot $CandidateRoot -GitArguments @('hash-object', $abs)
        $hashObjId = [string]$hashObj.stdout.Trim()
        if ($hashObjId -ne $blobId) {
            Fail $ReasonCode "blob content mismatch for $rel : index=$blobId worktree=$hashObjId"
        }
        $rows.Add([ordered]@{
                relative_path  = $rel
                size           = $size
                content_sha256 = $sha
                git_blob_sha1  = $blobId
            }) | Out-Null
    }
    return @($rows)
}

function Initialize-SealedCandidateSourceGitIdentity {
    param(
        [Parameter(Mandatory)][string]$CandidateRoot,
        [Parameter(Mandatory)]$ExpectedInventory,
        [Parameter(Mandatory)][string]$ExpectedTreeSha256
    )
    $root = Get-FullLiteralPath $CandidateRoot
    $reason = 'CANDIDATE_SOURCE_GIT_SEAL_FAILED'
    $product = Get-CandidateSourceInventory -Root $root -ReasonCode 'CANDIDATE_SOURCE_DRIFT'
    Assert-InventoryEqual -Left $ExpectedInventory -Right $product -ReasonCode $reason -Context 'pre-git-seal-product'
    $productTree = Get-InventoryTreeSha256 $product
    if ($productTree -ne $ExpectedTreeSha256) {
        Fail $reason "product tree sha mismatch before git seal: $root"
    }

    $gitPath = Join-Path $root '.git'
    if (Test-Path -LiteralPath $gitPath) {
        Fail $reason "refusing to seal over existing .git: $gitPath"
    }

    $null = Invoke-SealedGit -RepoRoot $root -GitArguments @(
        '-c', 'init.defaultBranch=proof',
        'init',
        '--template='
    )

    $null = Assert-GitDirIsLocalRegular -CandidateRoot $root -ReasonCode $reason

    $emptyHooks = Join-Path $root (($script:CandidateGitEmptyHooksRelative -split '/') -join [System.IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path -LiteralPath $emptyHooks -PathType Container)) {
        New-Item -ItemType Directory -Path $emptyHooks -Force | Out-Null
    }

    # Local-only identity / line-ending / filter / hooks / signing policy.
    $localConfigs = [ordered]@{
        'core.autocrlf'       = 'false'
        'core.eol'            = 'lf'
        'core.filemode'       = 'false'
        'core.symlinks'       = 'false'
        'core.hooksPath'      = $script:CandidateGitEmptyHooksRelative
        'commit.gpgsign'      = 'false'
        'tag.gpgsign'         = 'false'
        'init.defaultBranch'  = $script:CandidateGitProofBranch
        'user.name'           = $script:CandidateGitAuthorName
        'user.email'          = $script:CandidateGitAuthorEmail
    }
    foreach ($key in $localConfigs.Keys) {
        $null = Invoke-SealedGit -RepoRoot $root -GitArguments @('config', '--local', $key, [string]$localConfigs[$key])
    }

    # Stage exactly the product inventory paths (no extras).
    foreach ($row in @($ExpectedInventory)) {
        $rel = if ($row -is [System.Collections.IDictionary]) { [string]$row['relative_path'] } else { [string]$row.relative_path }
        $null = Invoke-SealedGit -RepoRoot $root -GitArguments @(
            '-c', 'core.autocrlf=false',
            '-c', 'core.eol=lf',
            'add', '--', $rel
        )
    }

    $commitEnv = @{
        GIT_AUTHOR_NAME     = $script:CandidateGitAuthorName
        GIT_AUTHOR_EMAIL    = $script:CandidateGitAuthorEmail
        GIT_AUTHOR_DATE     = $script:CandidateGitAuthorDate
        GIT_COMMITTER_NAME  = $script:CandidateGitCommitterName
        GIT_COMMITTER_EMAIL = $script:CandidateGitCommitterEmail
        GIT_COMMITTER_DATE   = $script:CandidateGitCommitterDate
    }
    $null = Invoke-SealedGit -RepoRoot $root -ExtraEnv $commitEnv -GitArguments @(
        '-c', 'commit.gpgsign=false',
        '-c', "core.hooksPath=$($script:CandidateGitEmptyHooksRelative)",
        'commit',
        '--no-verify',
        '-m', $script:CandidateGitCommitMessage
    )

    # Ensure branch name is the sealed proof branch.
    $null = Invoke-SealedGit -RepoRoot $root -GitArguments @('branch', '-M', $script:CandidateGitProofBranch)

    # Product bytes must be unchanged by git add/commit (no CRLF rewrite).
    $productAfter = Get-CandidateSourceInventory -Root $root -ReasonCode 'CANDIDATE_SOURCE_DRIFT'
    Assert-InventoryEqual -Left $ExpectedInventory -Right $productAfter -ReasonCode $reason -Context 'post-git-seal-product'
    if ((Get-InventoryTreeSha256 $productAfter) -ne $ExpectedTreeSha256) {
        Fail $reason 'product tree sha mismatch after git seal'
    }

    return (Get-SealedCandidateSourceGitIdentity -CandidateRoot $root -ExpectedInventory $ExpectedInventory -ReasonCode $reason)
}

function Get-SealedCandidateSourceGitIdentity {
    param(
        [Parameter(Mandatory)][string]$CandidateRoot,
        [Parameter(Mandatory)]$ExpectedInventory,
        [Parameter(Mandatory)][string]$ReasonCode
    )
    $root = Get-FullLiteralPath $CandidateRoot
    $null = Assert-GitDirIsLocalRegular -CandidateRoot $root -ReasonCode $ReasonCode

    $gitDirProbe = Invoke-SealedGit -RepoRoot $root -GitArguments @('rev-parse', '--is-inside-work-tree')
    if ([string]$gitDirProbe.stdout.Trim() -ne 'true') {
        Fail $ReasonCode 'not inside work tree'
    }
    $gitDirRel = Invoke-SealedGit -RepoRoot $root -GitArguments @('rev-parse', '--git-dir')
    $gitDirValue = [string]$gitDirRel.stdout.Trim().Replace('\', '/')
    if ($gitDirValue -ne '.git' -and -not (Test-PathsEqual (Join-Path $root $gitDirValue) (Join-Path $root '.git'))) {
        # Absolute git-dir must still resolve to candidate/.git
        $absGit = Get-FullLiteralPath $gitDirValue
        if (-not (Test-PathsEqual $absGit (Join-Path $root '.git'))) {
            Fail $ReasonCode "git-dir not local .git: $gitDirValue"
        }
    }
    $commonDir = Invoke-SealedGit -RepoRoot $root -GitArguments @('rev-parse', '--git-common-dir')
    $commonValue = [string]$commonDir.stdout.Trim().Replace('\', '/')
    if ($commonValue -ne '.git') {
        $absCommon = if ([System.IO.Path]::IsPathRooted($commonValue)) {
            Get-FullLiteralPath $commonValue
        }
        else {
            Get-FullLiteralPath (Join-Path $root $commonValue)
        }
        if (-not (Test-PathsEqual $absCommon (Join-Path $root '.git'))) {
            Fail $ReasonCode "git-common-dir external: $commonValue"
        }
    }

    $head = Invoke-SealedGit -RepoRoot $root -GitArguments @('rev-parse', 'HEAD')
    $tree = Invoke-SealedGit -RepoRoot $root -GitArguments @('rev-parse', 'HEAD^{tree}')
    $headId = [string]$head.stdout.Trim()
    $treeId = [string]$tree.stdout.Trim()
    if ($headId -notmatch '^[0-9a-f]{40,64}$' -or $treeId -notmatch '^[0-9a-f]{40,64}$') {
        Fail $ReasonCode "invalid HEAD/tree: commit=$headId tree=$treeId"
    }

    $status = Invoke-SealedGit -RepoRoot $root -GitArguments @('--no-optional-locks', 'status', '--porcelain')
    $statusText = [string]$status.stdout
    if (-not [string]::IsNullOrWhiteSpace($statusText)) {
        Fail $ReasonCode "dirty or untracked files: $statusText"
    }

    $branch = Invoke-SealedGit -RepoRoot $root -GitArguments @('rev-parse', '--abbrev-ref', 'HEAD')
    $branchName = [string]$branch.stdout.Trim()
    if ($branchName -ne $script:CandidateGitProofBranch) {
        Fail $ReasonCode "branch mismatch: $branchName"
    }

    $trackedFiles = Get-SealedCandidateTrackedGitFiles -CandidateRoot $root -ExpectedInventory $ExpectedInventory -ReasonCode $ReasonCode

    $config = [ordered]@{}
    foreach ($key in $script:ReceiptCandidateGitConfigKeys) {
        $got = Invoke-SealedGit -RepoRoot $root -GitArguments @('config', '--local', '--get', $key) -AllowNonZero
        if ([int]$got.exit_code -ne 0 -or [string]::IsNullOrWhiteSpace([string]$got.stdout)) {
            Fail $ReasonCode "missing local config: $key"
        }
        $config[$key] = [string]$got.stdout.Trim()
    }
    if ([string]$config['core.autocrlf'] -ne 'false') { Fail $ReasonCode 'core.autocrlf' }
    if ([string]$config['core.eol'] -ne 'lf') { Fail $ReasonCode 'core.eol' }
    if ([string]$config['core.filemode'] -ne 'false') { Fail $ReasonCode 'core.filemode' }
    if ([string]$config['core.symlinks'] -ne 'false') { Fail $ReasonCode 'core.symlinks' }
    if ([string]$config['core.hooksPath'] -ne $script:CandidateGitEmptyHooksRelative) { Fail $ReasonCode 'core.hooksPath' }
    if ([string]$config['commit.gpgsign'] -ne 'false') { Fail $ReasonCode 'commit.gpgsign' }
    if ([string]$config['user.name'] -ne $script:CandidateGitAuthorName) { Fail $ReasonCode 'user.name' }
    if ([string]$config['user.email'] -ne $script:CandidateGitAuthorEmail) { Fail $ReasonCode 'user.email' }
    if ([string]$config['init.defaultBranch'] -ne $script:CandidateGitProofBranch) { Fail $ReasonCode 'init.defaultBranch' }

    # Commit metadata sealed to deterministic proof identity.
    $authorName = Invoke-SealedGit -RepoRoot $root -GitArguments @('show', '-s', '--format=%an', 'HEAD')
    $authorEmail = Invoke-SealedGit -RepoRoot $root -GitArguments @('show', '-s', '--format=%ae', 'HEAD')
    $authorDate = Invoke-SealedGit -RepoRoot $root -GitArguments @('show', '-s', '--format=%aI', 'HEAD')
    $committerName = Invoke-SealedGit -RepoRoot $root -GitArguments @('show', '-s', '--format=%cn', 'HEAD')
    $committerEmail = Invoke-SealedGit -RepoRoot $root -GitArguments @('show', '-s', '--format=%ce', 'HEAD')
    $committerDate = Invoke-SealedGit -RepoRoot $root -GitArguments @('show', '-s', '--format=%cI', 'HEAD')
    $subject = Invoke-SealedGit -RepoRoot $root -GitArguments @('show', '-s', '--format=%s', 'HEAD')
    if ([string]$authorName.stdout.Trim() -ne $script:CandidateGitAuthorName) { Fail $ReasonCode 'author name' }
    if ([string]$authorEmail.stdout.Trim() -ne $script:CandidateGitAuthorEmail) { Fail $ReasonCode 'author email' }
    if ([string]$committerName.stdout.Trim() -ne $script:CandidateGitCommitterName) { Fail $ReasonCode 'committer name' }
    if ([string]$committerEmail.stdout.Trim() -ne $script:CandidateGitCommitterEmail) { Fail $ReasonCode 'committer email' }
    if ([string]$subject.stdout.Trim() -ne $script:CandidateGitCommitMessage) { Fail $ReasonCode 'commit message' }
    # Accept both space-offset form used for env and ISO from %aI.
    $aI = [string]$authorDate.stdout.Trim()
    $cI = [string]$committerDate.stdout.Trim()
    if ($aI -notmatch '^2026-01-01T00:00:00') { Fail $ReasonCode "author date: $aI" }
    if ($cI -notmatch '^2026-01-01T00:00:00') { Fail $ReasonCode "committer date: $cI" }

    # No configured remote object store / insteadOf rewrites that could pull external content.
    $remoteCheck = Invoke-SealedGit -RepoRoot $root -GitArguments @('config', '--local', '--get-regexp', '^remote\.') -AllowNonZero
    if ([int]$remoteCheck.exit_code -eq 0 -and -not [string]::IsNullOrWhiteSpace([string]$remoteCheck.stdout)) {
        Fail $ReasonCode "remote config forbidden: $($remoteCheck.stdout)"
    }

    return [ordered]@{
        schema_version         = $script:CandidateGitIdentitySchema
        repository_kind        = 'local_regular_directory'
        git_dir_relative_path  = '.git'
        external_gitdir_absent = $true
        alternates_absent      = $true
        branch                 = $script:CandidateGitProofBranch
        head_commit            = $headId
        head_tree              = $treeId
        status_porcelain       = ''
        commit_message         = $script:CandidateGitCommitMessage
        author_name            = $script:CandidateGitAuthorName
        author_email           = $script:CandidateGitAuthorEmail
        author_date            = $script:CandidateGitAuthorDate
        committer_name         = $script:CandidateGitCommitterName
        committer_email        = $script:CandidateGitCommitterEmail
        committer_date         = $script:CandidateGitCommitterDate
        hooks_path_relative    = $script:CandidateGitEmptyHooksRelative
        config                 = $config
        tracked_files          = @($trackedFiles)
    }
}

function Assert-SealedCandidateSourceGitIdentity {
    param(
        [Parameter(Mandatory)][string]$CandidateRoot,
        [Parameter(Mandatory)]$ExpectedIdentity,
        [Parameter(Mandatory)]$ExpectedInventory,
        [Parameter(Mandatory)][string]$ReasonCode
    )
    Assert-ExactKeySet -Object $ExpectedIdentity -ExpectedKeys $script:ReceiptCandidateGitIdentityKeys -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'candidate_source_git_identity'
    if ([string]$ExpectedIdentity['schema_version'] -ne $script:CandidateGitIdentitySchema) {
        Fail 'RECEIPT_SCHEMA_INVALID' 'candidate_source_git_identity.schema_version'
    }
    Assert-ExactKeySet -Object $ExpectedIdentity['config'] -ExpectedKeys $script:ReceiptCandidateGitConfigKeys -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'candidate_source_git_identity.config'
    $tracked = @($ExpectedIdentity['tracked_files'])
    if ($tracked.Count -lt 1) {
        Fail 'RECEIPT_SCHEMA_INVALID' 'candidate_source_git_identity.tracked_files empty'
    }
    foreach ($row in $tracked) {
        Assert-ExactKeySet -Object $row -ExpectedKeys $script:ReceiptCandidateGitTrackedFileKeys -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'candidate_source_git_identity.tracked_files.row'
        if ([string]$row['git_blob_sha1'] -notmatch '^[0-9a-f]{40,64}$') {
            Fail 'RECEIPT_SCHEMA_INVALID' "blob:$($row['relative_path'])"
        }
        if ([string]$row['content_sha256'] -notmatch $script:HexSha256Pattern) {
            Fail 'RECEIPT_SCHEMA_INVALID' "content_sha256:$($row['relative_path'])"
        }
    }

    $observed = Get-SealedCandidateSourceGitIdentity -CandidateRoot $CandidateRoot -ExpectedInventory $ExpectedInventory -ReasonCode $ReasonCode
    foreach ($key in @(
            'schema_version',
            'repository_kind',
            'git_dir_relative_path',
            'branch',
            'head_commit',
            'head_tree',
            'status_porcelain',
            'commit_message',
            'author_name',
            'author_email',
            'author_date',
            'committer_name',
            'committer_email',
            'committer_date',
            'hooks_path_relative'
        )) {
        if ([string]$observed[$key] -ne [string]$ExpectedIdentity[$key]) {
            Fail $ReasonCode "git identity field drift: $key"
        }
    }
    if ($observed['external_gitdir_absent'] -ne $true -or $ExpectedIdentity['external_gitdir_absent'] -ne $true) {
        Fail $ReasonCode 'external_gitdir_absent'
    }
    if ($observed['alternates_absent'] -ne $true -or $ExpectedIdentity['alternates_absent'] -ne $true) {
        Fail $ReasonCode 'alternates_absent'
    }
    foreach ($key in $script:ReceiptCandidateGitConfigKeys) {
        if ([string]$observed['config'][$key] -ne [string]$ExpectedIdentity['config'][$key]) {
            Fail $ReasonCode "config drift: $key"
        }
    }
    $expTracked = @($ExpectedIdentity['tracked_files'])
    $obsTracked = @($observed['tracked_files'])
    if ($expTracked.Count -ne $obsTracked.Count) {
        Fail $ReasonCode 'tracked_files count drift'
    }
    for ($i = 0; $i -lt $expTracked.Count; $i++) {
        foreach ($field in @('relative_path', 'size', 'content_sha256', 'git_blob_sha1')) {
            if ([string]$expTracked[$i][$field] -ne [string]$obsTracked[$i][$field]) {
                Fail $ReasonCode "tracked_files drift: $($expTracked[$i]['relative_path']).$field"
            }
        }
        # Bind tracked content hash to product inventory row.
        $rel = [string]$expTracked[$i]['relative_path']
        $hit = $false
        foreach ($invRow in @($ExpectedInventory)) {
            $invRel = if ($invRow -is [System.Collections.IDictionary]) { [string]$invRow['relative_path'] } else { [string]$invRow.relative_path }
            $invSha = if ($invRow -is [System.Collections.IDictionary]) { [string]$invRow['sha256'] } else { [string]$invRow.sha256 }
            $invSize = if ($invRow -is [System.Collections.IDictionary]) { [int64]$invRow['size'] } else { [int64]$invRow.size }
            if ($invRel -eq $rel) {
                $hit = $true
                if ($invSha -ne [string]$expTracked[$i]['content_sha256'] -or $invSize -ne [int64]$expTracked[$i]['size']) {
                    Fail $ReasonCode "tracked file not bound to candidate inventory: $rel"
                }
                break
            }
        }
        if (-not $hit) {
            Fail $ReasonCode "tracked path outside candidate inventory: $rel"
        }
    }
}

function Get-LegacyDockerProvenanceInventory {
    param(
        [Parameter(Mandatory)][string]$RepositoryRoot,
        [Parameter(Mandatory)][string]$ReasonCode
    )
    Assert-DirectorySafe $RepositoryRoot $ReasonCode
    $dockerRoot = Join-Path $RepositoryRoot 'docker\xinao-researcher'
    Assert-DirectorySafe $dockerRoot $ReasonCode
    $dockerfile = Join-Path $dockerRoot 'Dockerfile'
    $entrypoint = Join-Path $dockerRoot 'entrypoint.py'
    Assert-RegularFileSafe $dockerfile -ReasonCode $ReasonCode
    Assert-RegularFileSafe $entrypoint -ReasonCode $ReasonCode
    $rows = @(
        [ordered]@{
            relative_path = 'docker/xinao-researcher/Dockerfile'
            type          = 'file'
            size          = [int64]([System.IO.File]::ReadAllBytes($dockerfile).LongLength)
            sha256        = (Get-Sha256File $dockerfile)
        },
        [ordered]@{
            relative_path = 'docker/xinao-researcher/entrypoint.py'
            type          = 'file'
            size          = [int64]([System.IO.File]::ReadAllBytes($entrypoint).LongLength)
            sha256        = (Get-Sha256File $entrypoint)
        }
    )
    return @($rows | Sort-Object { $_.relative_path })
}

function Copy-LegacyDockerProvenance {
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$DestinationRoot,
        [Parameter(Mandatory)]$ExpectedInventory,
        [Parameter(Mandatory)][string]$ExpectedTreeSha256,
        [Parameter(Mandatory)][string]$ReasonCode
    )
    $liveRows = Get-LegacyDockerProvenanceInventory -RepositoryRoot $SourceRoot -ReasonCode $ReasonCode
    Assert-InventoryEqual -Left $ExpectedInventory -Right $liveRows -ReasonCode $ReasonCode -Context "legacy-provenance:$SourceRoot"
    $liveTree = Get-InventoryTreeSha256 $liveRows
    if ($liveTree -ne $ExpectedTreeSha256) {
        Fail $ReasonCode "legacy provenance tree sha mismatch: $SourceRoot"
    }
    if (Test-Path -LiteralPath $DestinationRoot) {
        Fail $ReasonCode "destination exists: $DestinationRoot"
    }
    New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
    foreach ($row in $liveRows) {
        $rel = [string]$row.relative_path
        $src = Join-Path $SourceRoot (($rel -split '/') -join [System.IO.Path]::DirectorySeparatorChar)
        $dst = Join-Path $DestinationRoot (($rel -split '/') -join [System.IO.Path]::DirectorySeparatorChar)
        $bytes = [System.IO.File]::ReadAllBytes($src)
        if ((Get-Sha256Bytes $bytes) -ne [string]$row.sha256) {
            Fail $ReasonCode "legacy provenance changed while copying: $src"
        }
        Write-BytesAtomic -PathValue $dst -Bytes $bytes -CreateNew
    }
    $destRows = Get-LegacyDockerProvenanceInventory -RepositoryRoot $DestinationRoot -ReasonCode $ReasonCode
    Assert-InventoryEqual -Left $liveRows -Right $destRows -ReasonCode $ReasonCode -Context "legacy-provenance-post:$DestinationRoot"
    return $destRows
}

function Get-LegacySkillSideHashes {
    param([Parameter(Mandatory)][string]$Root)
    Assert-DirectorySafe $Root 'MIGRATION_SOURCE_RENDERING_HASH_MISMATCH'
    $required = [ordered]@{
        skill_md_sha256              = (Join-Path $Root 'SKILL.md')
        skill_invoker_sha256         = (Join-Path $Root 'scripts\xinao.py')
        capability_registry_sha256   = (Join-Path $Root 'references\capabilities.v1.json')
        charter_sha256               = (Join-Path $Root 'references\researcher-charter.v1.json')
        runtime_lock_sha256          = (Join-Path $Root 'references\researcher-runtime-lock.v1.json')
        meta_sha256                  = (Join-Path $Root 'references\meta.md')
    }
    $outputV1 = Join-Path $Root 'references\researcher-output.v1.schema.json'
    $outputV2 = Join-Path $Root 'references\researcher-output.v2.schema.json'
    if (Test-Path -LiteralPath $outputV1 -PathType Leaf) {
        $outputPath = $outputV1
    }
    elseif (Test-Path -LiteralPath $outputV2 -PathType Leaf) {
        $outputPath = $outputV2
    }
    else {
        Fail 'MIGRATION_SOURCE_RENDERING_HASH_MISMATCH' 'output_schema_missing'
    }
    $hashes = [ordered]@{}
    $hashes['output_schema_sha256'] = Get-Sha256File $outputPath
    foreach ($key in $required.Keys) {
        $path = $required[$key]
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            Fail 'MIGRATION_SOURCE_RENDERING_HASH_MISMATCH' "missing: $(Split-Path -Leaf $path)"
        }
        $hashes[$key] = Get-Sha256File $path
    }
    return $hashes
}

function Assert-PureReleaseDirectory {
    param(
        [Parameter(Mandatory)][string]$ReleaseDir,
        [Parameter(Mandatory)][string]$ReleaseId
    )
    Assert-DirectorySafe $ReleaseDir 'V1_RELEASE_DIRECTORY_NOT_PURE'
    $entries = @(Get-ChildItem -LiteralPath $ReleaseDir -Force)
    foreach ($entry in $entries) {
        if ($entry.Name -ne 'release.json') {
            Fail 'V1_RELEASE_DIRECTORY_NOT_PURE' "${ReleaseId}: unexpected entry $($entry.Name)"
        }
        if ($entry.PSIsContainer -or ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            Fail 'V1_RELEASE_DIRECTORY_NOT_PURE' "${ReleaseId}: release.json must be regular file"
        }
    }
    $manifestPath = Join-Path $ReleaseDir 'release.json'
    Assert-RegularFileSafe $manifestPath -ReasonCode 'V1_RELEASE_MANIFEST_INVALID'
    return $manifestPath
}

function Assert-LegacyReleaseManifest {
    param(
        [Parameter(Mandatory)]$Manifest,
        [Parameter(Mandatory)][string]$ExpectedReleaseId,
        [Parameter(Mandatory)][string]$ManifestPath
    )
    $keys = @($Manifest.Keys | ForEach-Object { [string]$_ } | Sort-Object)
    $expectedKeys = $script:LegacyReleaseKeys
    if (($keys -join '|') -ne ($expectedKeys -join '|')) {
        Fail 'V1_RELEASE_MANIFEST_INVALID' "key set mismatch: $ManifestPath"
    }
    if ([string]$Manifest['schema_version'] -ne $script:LegacyReleaseSchema) {
        Fail 'V1_RELEASE_MANIFEST_INVALID' "schema: $ManifestPath"
    }
    if ([string]$Manifest['release_id'] -ne $ExpectedReleaseId) {
        Fail 'RELEASE_IDENTITY_INVALID' $ExpectedReleaseId
    }
    if (-not ([string]$Manifest['release_id'] -match $script:ReleaseIdPattern)) {
        Fail 'RELEASE_IDENTITY_INVALID' $ExpectedReleaseId
    }
    if ($Manifest['generic_worker_route_allowed'] -ne $false) {
        Fail 'RELEASE_CHAIN_CLASS_INVALID' $ExpectedReleaseId
    }
    $skillHashes = $Manifest['skill_hashes']
    if ($null -eq $skillHashes -or -not ($skillHashes -is [System.Collections.IDictionary])) {
        Fail 'V1_RELEASE_SKILL_HASHES_INVALID' $ExpectedReleaseId
    }
    $skillKeys = @($skillHashes.Keys | ForEach-Object { [string]$_ } | Sort-Object)
    if (($skillKeys -join '|') -ne ($script:LegacySkillHashKeys -join '|')) {
        Fail 'V1_RELEASE_SKILL_HASHES_INVALID' $ExpectedReleaseId
    }
    foreach ($key in $skillKeys) {
        $value = [string]$skillHashes[$key]
        if ($value -notmatch $script:HexSha256Pattern) {
            Fail 'V1_RELEASE_SKILL_HASHES_INVALID' $key
        }
    }
    $sourceIdentity = $Manifest['source_identity']
    if ($null -eq $sourceIdentity -or -not ($sourceIdentity -is [System.Collections.IDictionary])) {
        Fail 'RELEASE_SOURCE_IDENTITY_INVALID' $ExpectedReleaseId
    }
    if ($sourceIdentity['source_dirty'] -ne $false) {
        Fail 'DIRTY_RELEASE_ACTIVATION_FORBIDDEN' $ExpectedReleaseId
    }
    $imageId = [string]$Manifest['image_id']
    if (-not $imageId.StartsWith('sha256:') -or $imageId.Length -ne (7 + 64)) {
        Fail 'RELEASE_IMAGE_IDENTITY_INVALID' $ExpectedReleaseId
    }
    $entrypoint = @($Manifest['image_entrypoint'] | ForEach-Object { [string]$_ })
    $expectedEntrypoint = @('python', '-I', '/opt/xinao-researcher/entrypoint.py')
    if (($entrypoint -join '|') -ne ($expectedEntrypoint -join '|')) {
        Fail 'RELEASE_IMAGE_IDENTITY_INVALID' $ExpectedReleaseId
    }
}

function Assert-LegacyPointer {
    param(
        [Parameter(Mandatory)]$Pointer,
        [Parameter(Mandatory)][string]$PointerPath
    )
    $keys = @($Pointer.Keys | ForEach-Object { [string]$_ } | Sort-Object)
    if (($keys -join '|') -ne ($script:LegacyPointerKeys -join '|')) {
        Fail 'CURRENT_POINTER_SCHEMA_INVALID' "key set: $PointerPath"
    }
    if ([string]$Pointer['schema_version'] -ne $script:LegacyPointerSchema) {
        Fail 'CURRENT_POINTER_SCHEMA_INVALID' $PointerPath
    }
    foreach ($key in @(
            'release_id',
            'release_manifest_path',
            'release_manifest_sha256',
            'previous_release_id',
            'previous_release_manifest_path',
            'previous_release_manifest_sha256',
            'promoted_at'
        )) {
        $value = $Pointer[$key]
        if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
            Fail 'CURRENT_POINTER_SCHEMA_INVALID' $key
        }
    }
    $prevSha = $Pointer['previous_pointer_sha256']
    if ($null -ne $prevSha) {
        if ([string]$prevSha -notmatch $script:HexSha256Pattern) {
            Fail 'CURRENT_POINTER_SCHEMA_INVALID' 'previous_pointer_sha256'
        }
    }
    foreach ($key in @('release_manifest_sha256', 'previous_release_manifest_sha256')) {
        if ([string]$Pointer[$key] -notmatch $script:HexSha256Pattern) {
            Fail 'CURRENT_POINTER_SCHEMA_INVALID' $key
        }
    }
    if (-not ([string]$Pointer['release_id'] -match $script:ReleaseIdPattern)) {
        Fail 'CURRENT_POINTER_SCHEMA_INVALID' 'release_id'
    }
    if (-not ([string]$Pointer['previous_release_id'] -match $script:ReleaseIdPattern)) {
        Fail 'CURRENT_POINTER_SCHEMA_INVALID' 'previous_release_id'
    }
}

function Assert-DestinationAllowed {
    param(
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$ApprovedBase,
        [string[]]$ForbiddenRoots = @()
    )
    $dest = Get-FullLiteralPath $Destination
    $base = Get-FullLiteralPath $ApprovedBase

    $broad = @(
        'C:\', 'C:', 'D:\', 'D:', '\', '/',
        'C:\Users', 'D:\XINAO_RESEARCH_RUNTIME',
        'D:\XINAO_RESEARCH_RUNTIME\state',
        'D:\XINAO_RESEARCH_RUNTIME\worktrees'
    )
    foreach ($root in $broad) {
        if (Test-PathsEqual $dest $root) {
            Fail 'DESTINATION_BROAD_ROOT_FORBIDDEN' $dest
        }
    }

    $destRoot = [System.IO.Path]::GetPathRoot($dest)
    if ($destRoot.StartsWith('C:', [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail 'DESTINATION_C_DRIVE_FORBIDDEN' $dest
    }

    if (-not (Test-IsStrictChildPath -Parent $base -Child $dest)) {
        Fail 'DESTINATION_NOT_UNDER_APPROVED_BASE' "dest=$dest base=$base"
    }

    foreach ($forbidden in $ForbiddenRoots) {
        if ([string]::IsNullOrWhiteSpace($forbidden)) { continue }
        $f = Get-FullLiteralPath $forbidden
        if ((Test-PathsEqual $dest $f) -or (Test-IsStrictChildPath -Parent $f -Child $dest) -or (Test-IsStrictChildPath -Parent $dest -Child $f)) {
            Fail 'DESTINATION_OVERLAPS_PROTECTED_ROOT' "dest=$dest protected=$f"
        }
    }
}

function Assert-CandidateSourceRoot {
    param([Parameter(Mandatory)][string]$Root)
    $null = Get-CandidateSourceInventory -Root $Root -ReasonCode 'MIGRATION_SOURCE_CONE_MISSING'
}

function Assert-OwnedMarkerValid {
    param(
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$ApprovedBase,
        [Parameter(Mandatory)][string]$MarkerPath
    )
    $dest = Get-FullLiteralPath $Destination
    $base = Get-FullLiteralPath $ApprovedBase
    if (-not (Test-IsStrictChildPath -Parent $base -Child $dest)) {
        Fail 'OWNED_CLEANUP_REFUSED' "dest not under approved base: $dest"
    }
    Assert-NoReparseInChain $dest 'OWNED_CLEANUP_REFUSED'
    Assert-RegularFileSafe $MarkerPath -ReasonCode 'OWNED_CLEANUP_REFUSED'
    $marker = Read-JsonObjectFile -PathValue $MarkerPath -ReasonCode 'OWNED_CLEANUP_REFUSED'
    if ([string]$marker['schema_version'] -ne $script:OwnedMarkerSchema) {
        Fail 'OWNED_CLEANUP_REFUSED' 'marker schema mismatch'
    }
    if (-not (Test-PathsEqual ([string]$marker['proof_root']) $dest)) {
        Fail 'OWNED_CLEANUP_REFUSED' 'marker proof_root mismatch'
    }
    if ([int64]$marker['pid'] -ne [int64]$PID) {
        Fail 'OWNED_CLEANUP_REFUSED' "marker pid mismatch: $($marker['pid']) != $PID"
    }
    $expectedHash = [string]$marker['marker_body_sha256']
    $body = [ordered]@{}
    foreach ($key in @($marker.Keys | ForEach-Object { [string]$_ } | Sort-Object)) {
        if ($key -eq 'marker_body_sha256') { continue }
        $body[$key] = $marker[$key]
    }
    $bodyText = ConvertTo-CanonicalJsonText -Value $body
    $observed = Get-Sha256Bytes ([System.Text.UTF8Encoding]::new($false).GetBytes($bodyText))
    if ($observed -ne $expectedHash) {
        Fail 'OWNED_CLEANUP_REFUSED' 'marker body hash mismatch'
    }
}

function Remove-OwnedFailedCone {
    param(
        [Parameter(Mandatory)][string]$Destination,
        [string]$ApprovedBase = ''
    )
    $dest = Get-FullLiteralPath $Destination

    if ($script:OwnedConeCreated) {
        if ([string]::IsNullOrWhiteSpace($ApprovedBase)) {
            Write-Warning "Refusing cleanup: approved base missing for owned cone $dest"
            return
        }
        $marker = Join-Path $dest $script:OwnedMarkerName
        if (-not (Test-Path -LiteralPath $dest -PathType Container)) {
            $script:OwnedConeCreated = $false
            return
        }
        try {
            Assert-OwnedMarkerValid -Destination $dest -ApprovedBase $ApprovedBase -MarkerPath $marker
        }
        catch {
            Write-Warning "Refusing cleanup: $($_.Exception.Message)"
            return
        }
        # Only remove the just-created owned cone; never a caller-supplied existing directory.
        Remove-Item -LiteralPath $dest -Recurse -Force
        $script:OwnedConeCreated = $false
        $script:CreatedEmptyDestPendingMarker = $false
        return
    }

    # Marker-write failure may remove only a newly created empty directory.
    if (-not $script:CreatedEmptyDestPendingMarker) { return }
    if (-not (Test-Path -LiteralPath $dest -PathType Container)) {
        $script:CreatedEmptyDestPendingMarker = $false
        return
    }
    if (-not [string]::IsNullOrWhiteSpace($ApprovedBase)) {
        if (-not (Test-IsStrictChildPath -Parent (Get-FullLiteralPath $ApprovedBase) -Child $dest)) {
            Write-Warning "Refusing empty-dest cleanup outside approved base: $dest"
            return
        }
    }
    if (Test-IsReparsePoint $dest) {
        Write-Warning "Refusing empty-dest cleanup on reparse: $dest"
        return
    }
    $children = @(Get-ChildItem -LiteralPath $dest -Force)
    if ($children.Count -ne 0) {
        Write-Warning "Refusing empty-dest cleanup: non-empty $dest"
        return
    }
    Remove-Item -LiteralPath $dest -Force
    $script:CreatedEmptyDestPendingMarker = $false
}

function Get-ExpectedStateLayout {
    param([Parameter(Mandatory)][string]$StateRoot)
    $capability = Join-Path $StateRoot 'researcher_container'
    return [ordered]@{
        state_root              = $StateRoot
        capability_root         = $capability
        pointer                 = (Join-Path $capability 'current.json')
        release_root            = (Join-Path $capability 'releases')
        source_renderings_root  = (Join-Path $capability 'migration\source_renderings')
    }
}

function Invoke-SourcePreflight {
    param(
        [Parameter(Mandatory)][string]$LiveStateRoot,
        [Parameter(Mandatory)][string]$InstalledSkillRoot,
        [Parameter(Mandatory)][string]$ActiveRenderingRoot,
        [Parameter(Mandatory)][string]$PreviousRenderingRoot,
        [Parameter(Mandatory)][string]$CandidateSourceRoot,
        [Parameter(Mandatory)][string]$ActiveLegacyRepositoryRoot,
        [Parameter(Mandatory)][string]$PreviousLegacyRepositoryRoot
    )

    $stateRoot = Get-FullLiteralPath $LiveStateRoot
    $installedRoot = Get-FullLiteralPath $InstalledSkillRoot
    $activeRendering = Get-FullLiteralPath $ActiveRenderingRoot
    $previousRendering = Get-FullLiteralPath $PreviousRenderingRoot
    $candidateRoot = Get-FullLiteralPath $CandidateSourceRoot
    $activeLegacyRepo = Get-FullLiteralPath $ActiveLegacyRepositoryRoot
    $previousLegacyRepo = Get-FullLiteralPath $PreviousLegacyRepositoryRoot

    Assert-DirectorySafe $stateRoot 'SOURCE_STATE_INVALID'
    Assert-DirectorySafe $installedRoot 'INSTALLED_SKILL_INVALID'
    Assert-DirectorySafe $activeRendering 'MIGRATION_SOURCE_RENDERING_ABSENT'
    Assert-DirectorySafe $previousRendering 'MIGRATION_SOURCE_RENDERING_ABSENT'
    Assert-CandidateSourceRoot $candidateRoot
    Assert-DirectorySafe $activeLegacyRepo 'LEGACY_REPOSITORY_ROOT_INVALID'
    Assert-DirectorySafe $previousLegacyRepo 'LEGACY_REPOSITORY_ROOT_INVALID'

    $layout = Get-ExpectedStateLayout $stateRoot
    $pointerPath = $layout.pointer
    Assert-RegularFileSafe $pointerPath -ReasonCode 'CURRENT_POINTER_ABSENT'
    $pointerBytes = [System.IO.File]::ReadAllBytes($pointerPath)
    $pointerSha = Get-Sha256Bytes $pointerBytes
    $pointer = Read-JsonObjectFile $pointerPath
    Assert-LegacyPointer -Pointer $pointer -PointerPath $pointerPath

    $activeId = [string]$pointer['release_id']
    $previousId = [string]$pointer['previous_release_id']
    if ($activeId -eq $previousId) {
        Fail 'ROLLBACK_MATERIAL_INVALID' $previousId
    }

    $expectedActiveManifest = Join-Path $layout.release_root "$activeId\release.json"
    $expectedPreviousManifest = Join-Path $layout.release_root "$previousId\release.json"
    $activeManifestPath = Get-FullLiteralPath ([string]$pointer['release_manifest_path'])
    $previousManifestPath = Get-FullLiteralPath ([string]$pointer['previous_release_manifest_path'])
    if (-not (Test-PathsEqual $activeManifestPath $expectedActiveManifest)) {
        Fail 'MIGRATION_RELEASE_INCOMPLETE' "active path mismatch: $activeManifestPath"
    }
    if (-not (Test-PathsEqual $previousManifestPath $expectedPreviousManifest)) {
        Fail 'ROLLBACK_MATERIAL_ABSENT' "previous path mismatch: $previousManifestPath"
    }

    $activeDir = Split-Path -Parent $activeManifestPath
    $previousDir = Split-Path -Parent $previousManifestPath
    Assert-PureReleaseDirectory -ReleaseDir $activeDir -ReleaseId $activeId | Out-Null
    Assert-PureReleaseDirectory -ReleaseDir $previousDir -ReleaseId $previousId | Out-Null

    $activeShaObserved = Get-Sha256File $activeManifestPath
    $previousShaObserved = Get-Sha256File $previousManifestPath
    if ($activeShaObserved -ne [string]$pointer['release_manifest_sha256']) {
        Fail 'RELEASE_MANIFEST_IDENTITY_MISMATCH' $activeManifestPath
    }
    if ($previousShaObserved -ne [string]$pointer['previous_release_manifest_sha256']) {
        Fail 'RELEASE_MANIFEST_IDENTITY_MISMATCH' $previousManifestPath
    }

    $activeManifest = Read-JsonObjectFile $activeManifestPath
    $previousManifest = Read-JsonObjectFile $previousManifestPath
    Assert-LegacyReleaseManifest -Manifest $activeManifest -ExpectedReleaseId $activeId -ManifestPath $activeManifestPath
    Assert-LegacyReleaseManifest -Manifest $previousManifest -ExpectedReleaseId $previousId -ManifestPath $previousManifestPath

    # Rendering trees: regular-file-only + skill-side hash match (byte-exact CRLF/LF).
    # dockerfile/entrypoint are NOT compared from renderings or v2 candidate (different generations).
    $activeRenderingInventory = Get-SortedRelativeInventory -Root $activeRendering -ReasonCode 'SKILL_BUNDLE_SOURCE_INVALID'
    $previousRenderingInventory = Get-SortedRelativeInventory -Root $previousRendering -ReasonCode 'SKILL_BUNDLE_SOURCE_INVALID'
    $activeRenderingTreeSha = Get-InventoryTreeSha256 $activeRenderingInventory
    $previousRenderingTreeSha = Get-InventoryTreeSha256 $previousRenderingInventory
    $activeSkillSide = Get-LegacySkillSideHashes $activeRendering
    $previousSkillSide = Get-LegacySkillSideHashes $previousRendering
    foreach ($key in $script:LegacySkillRenderingHashKeys) {
        if (-not $activeSkillSide.Contains($key)) {
            Fail 'MIGRATION_SOURCE_RENDERING_HASH_MISMATCH' "${activeId}:missing:$key"
        }
        if ([string]$activeManifest['skill_hashes'][$key] -ne [string]$activeSkillSide[$key]) {
            Fail 'MIGRATION_SOURCE_RENDERING_HASH_MISMATCH' "${activeId}:${key}"
        }
    }
    foreach ($key in $script:LegacySkillRenderingHashKeys) {
        if (-not $previousSkillSide.Contains($key)) {
            Fail 'MIGRATION_SOURCE_RENDERING_HASH_MISMATCH' "${previousId}:missing:$key"
        }
        if ([string]$previousManifest['skill_hashes'][$key] -ne [string]$previousSkillSide[$key]) {
            Fail 'MIGRATION_SOURCE_RENDERING_HASH_MISMATCH' "${previousId}:${key}"
        }
    }

    # Legacy v1 docker/entrypoint provenance from explicit repository roots (not v2 candidate).
    $activeLegacyInventory = Get-LegacyDockerProvenanceInventory -RepositoryRoot $activeLegacyRepo -ReasonCode 'LEGACY_DOCKER_PROVENANCE_INVALID'
    $previousLegacyInventory = Get-LegacyDockerProvenanceInventory -RepositoryRoot $previousLegacyRepo -ReasonCode 'LEGACY_DOCKER_PROVENANCE_INVALID'
    $activeLegacyTreeSha = Get-InventoryTreeSha256 $activeLegacyInventory
    $previousLegacyTreeSha = Get-InventoryTreeSha256 $previousLegacyInventory
    $activeDockerMap = @{}
    foreach ($row in $activeLegacyInventory) {
        $activeDockerMap[[string]$row.relative_path] = [string]$row.sha256
    }
    $previousDockerMap = @{}
    foreach ($row in $previousLegacyInventory) {
        $previousDockerMap[[string]$row.relative_path] = [string]$row.sha256
    }
    if ($activeDockerMap['docker/xinao-researcher/Dockerfile'] -ne [string]$activeManifest['skill_hashes']['dockerfile_sha256']) {
        Fail 'LEGACY_DOCKERFILE_HASH_MISMATCH' "${activeId}:dockerfile_sha256"
    }
    if ($activeDockerMap['docker/xinao-researcher/entrypoint.py'] -ne [string]$activeManifest['skill_hashes']['entrypoint_sha256']) {
        Fail 'LEGACY_ENTRYPOINT_HASH_MISMATCH' "${activeId}:entrypoint_sha256"
    }
    if ($previousDockerMap['docker/xinao-researcher/Dockerfile'] -ne [string]$previousManifest['skill_hashes']['dockerfile_sha256']) {
        Fail 'LEGACY_DOCKERFILE_HASH_MISMATCH' "${previousId}:dockerfile_sha256"
    }
    if ($previousDockerMap['docker/xinao-researcher/entrypoint.py'] -ne [string]$previousManifest['skill_hashes']['entrypoint_sha256']) {
        Fail 'LEGACY_ENTRYPOINT_HASH_MISMATCH' "${previousId}:entrypoint_sha256"
    }

    # Every declared skill_hashes key is bound either to rendering or legacy docker provenance.
    foreach ($key in $script:LegacySkillHashKeys) {
        if ($key -in $script:LegacySkillRenderingHashKeys) { continue }
        if ($key -in $script:LegacyDockerHashKeys) { continue }
        Fail 'V1_RELEASE_SKILL_HASHES_INVALID' "unbound skill_hashes key: $key"
    }

    $candidateInventory = Get-CandidateSourceInventory -Root $candidateRoot -ReasonCode 'MIGRATION_SOURCE_CONE_MISSING'
    $candidateTreeSha = Get-InventoryTreeSha256 $candidateInventory

    $installedInventory = Get-SortedRelativeInventory -Root $installedRoot -ReasonCode 'INSTALLED_SKILL_INVALID'
    $installedTreeSha = Get-InventoryTreeSha256 $installedInventory

    # Optional synthetic TOCTOU injection for negative tests only.
    if ($env:XINAO_TEST_MUTATE_RENDERING_AFTER_PREFLIGHT -eq '1') {
        $injectPath = Join-Path $activeRendering 'references\toctou-inject.txt'
        [System.IO.File]::WriteAllBytes($injectPath, [System.Text.Encoding]::UTF8.GetBytes("toctou-$PID`n"))
    }

    return [ordered]@{
        state_root                           = $stateRoot
        installed_skill_root                 = $installedRoot
        active_rendering_root                = $activeRendering
        previous_rendering_root              = $previousRendering
        candidate_source_root                = $candidateRoot
        active_legacy_repository_root        = $activeLegacyRepo
        previous_legacy_repository_root      = $previousLegacyRepo
        pointer_path                         = $pointerPath
        pointer                              = $pointer
        pointer_bytes                        = $pointerBytes
        pointer_sha256_original              = $pointerSha
        active_release_id                    = $activeId
        previous_release_id                  = $previousId
        active_manifest_path                 = $activeManifestPath
        previous_manifest_path               = $previousManifestPath
        active_manifest_sha256               = $activeShaObserved
        previous_manifest_sha256             = $previousShaObserved
        active_manifest                      = $activeManifest
        previous_manifest                    = $previousManifest
        active_rendering_inventory           = $activeRenderingInventory
        previous_rendering_inventory         = $previousRenderingInventory
        active_rendering_tree_sha256         = $activeRenderingTreeSha
        previous_rendering_tree_sha256       = $previousRenderingTreeSha
        candidate_source_inventory           = $candidateInventory
        candidate_source_tree_sha256         = $candidateTreeSha
        active_legacy_provenance_inventory   = $activeLegacyInventory
        previous_legacy_provenance_inventory = $previousLegacyInventory
        active_legacy_provenance_tree_sha256 = $activeLegacyTreeSha
        previous_legacy_provenance_tree_sha256 = $previousLegacyTreeSha
        installed_inventory                  = $installedInventory
        installed_skill_tree_sha256          = $installedTreeSha
        active_release_bytes                 = [System.IO.File]::ReadAllBytes($activeManifestPath)
        previous_release_bytes               = [System.IO.File]::ReadAllBytes($previousManifestPath)
    }
}

function New-ProofCone {
    param(
        [Parameter(Mandatory)]$Preflight,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$ApprovedBase
    )

    $dest = Get-FullLiteralPath $Destination
    $approvedFull = Get-FullLiteralPath $ApprovedBase
    Assert-DestinationAllowed -Destination $dest -ApprovedBase $approvedFull -ForbiddenRoots @(
        $Preflight.state_root,
        $Preflight.installed_skill_root,
        $Preflight.active_rendering_root,
        $Preflight.previous_rendering_root,
        $Preflight.candidate_source_root,
        $Preflight.active_legacy_repository_root,
        $Preflight.previous_legacy_repository_root
    )

    # Reject reparse/junction chains before the first destination write.
    Assert-NoReparseInChain $dest 'DESTINATION_REPARSE_FORBIDDEN'
    Assert-NoReparseInChain $approvedFull 'DESTINATION_REPARSE_FORBIDDEN'

    if (Test-Path -LiteralPath $dest) {
        Fail 'DESTINATION_EXISTS' $dest
    }

    $parent = Split-Path -Parent $dest
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        # Create only intermediate parents under approved base, never broad roots.
        if (-not (Test-IsStrictChildPath -Parent $approvedFull -Child $parent) -and
            -not (Test-PathsEqual $parent $approvedFull)) {
            Fail 'DESTINATION_PARENT_NOT_UNDER_APPROVED_BASE' $parent
        }
        Assert-NoReparseInChain $parent 'DESTINATION_REPARSE_FORBIDDEN'
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    else {
        Assert-NoReparseInChain $parent 'DESTINATION_REPARSE_FORBIDDEN'
    }

    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    $script:CreatedEmptyDestPendingMarker = $true
    $script:OwnedConeCreated = $false
    $markerPath = Join-Path $dest $script:OwnedMarkerName
    $markerCore = [ordered]@{
        schema_version = $script:OwnedMarkerSchema
        created_at     = (Get-Date).ToUniversalTime().ToString('o')
        proof_root     = $dest
        pid            = [int64]$PID
    }
    $markerCoreText = ConvertTo-CanonicalJsonText -Value $markerCore
    $markerHash = Get-Sha256Bytes ([System.Text.UTF8Encoding]::new($false).GetBytes($markerCoreText))
    $markerCore['marker_body_sha256'] = $markerHash
    $markerBody = ConvertTo-CanonicalJsonText -Value $markerCore
    Write-Utf8NoBomFileAtomic -PathValue $markerPath -Text $markerBody -CreateNew
    # Ownership only after durable marker write.
    $script:OwnedConeCreated = $true
    $script:CreatedEmptyDestPendingMarker = $false

    $stateRoot = Join-Path $dest 'isolated-state'
    $installedRoot = Join-Path $dest 'installed-skill'
    $runRoot = Join-Path $dest 'researcher-runs'
    $candidateCloneRoot = Join-Path $dest 'candidate-source'
    $layout = Get-ExpectedStateLayout $stateRoot

    New-Item -ItemType Directory -Path $layout.release_root -Force | Out-Null
    New-Item -ItemType Directory -Path $layout.source_renderings_root -Force | Out-Null
    New-Item -ItemType Directory -Path $runRoot -Force | Out-Null

    # Exact release bytes under isolated state.
    $activeReleaseDir = Join-Path $layout.release_root $Preflight.active_release_id
    $previousReleaseDir = Join-Path $layout.release_root $Preflight.previous_release_id
    New-Item -ItemType Directory -Path $activeReleaseDir -Force | Out-Null
    New-Item -ItemType Directory -Path $previousReleaseDir -Force | Out-Null
    $clonedActiveManifest = Join-Path $activeReleaseDir 'release.json'
    $clonedPreviousManifest = Join-Path $previousReleaseDir 'release.json'
    Write-BytesAtomic -PathValue $clonedActiveManifest -Bytes $Preflight.active_release_bytes -CreateNew
    Write-BytesAtomic -PathValue $clonedPreviousManifest -Bytes $Preflight.previous_release_bytes -CreateNew
    if ((Get-Sha256File $clonedActiveManifest) -ne $Preflight.active_manifest_sha256) {
        Fail 'RELEASE_COPY_DRIFT' $clonedActiveManifest
    }
    if ((Get-Sha256File $clonedPreviousManifest) -ne $Preflight.previous_manifest_sha256) {
        Fail 'RELEASE_COPY_DRIFT' $clonedPreviousManifest
    }

    # Exact renderings bound to preflight inventories/tree hashes.
    $clonedActiveRendering = Join-Path $layout.source_renderings_root $Preflight.active_release_id
    $clonedPreviousRendering = Join-Path $layout.source_renderings_root $Preflight.previous_release_id
    $null = Copy-ExactTree `
        -SourceRoot $Preflight.active_rendering_root `
        -DestinationRoot $clonedActiveRendering `
        -ReasonCode 'RENDERING_COPY_FAILED' `
        -ExpectedInventory $Preflight.active_rendering_inventory `
        -ExpectedTreeSha256 $Preflight.active_rendering_tree_sha256
    $null = Copy-ExactTree `
        -SourceRoot $Preflight.previous_rendering_root `
        -DestinationRoot $clonedPreviousRendering `
        -ReasonCode 'RENDERING_COPY_FAILED' `
        -ExpectedInventory $Preflight.previous_rendering_inventory `
        -ExpectedTreeSha256 $Preflight.previous_rendering_tree_sha256

    # Installed skill clone bound to preflight inventory.
    $null = Copy-ExactTree `
        -SourceRoot $Preflight.installed_skill_root `
        -DestinationRoot $installedRoot `
        -ReasonCode 'INSTALLED_SKILL_COPY_FAILED' `
        -ExpectedInventory $Preflight.installed_inventory `
        -ExpectedTreeSha256 $Preflight.installed_skill_tree_sha256

    # Seal v2 candidate migration source inside the proof cone (not live caller path).
    $null = Copy-CandidateSourceTree `
        -SourceRoot $Preflight.candidate_source_root `
        -DestinationRoot $candidateCloneRoot `
        -ExpectedInventory $Preflight.candidate_source_inventory `
        -ExpectedTreeSha256 $Preflight.candidate_source_tree_sha256 `
        -ReasonCode 'CANDIDATE_SOURCE_COPY_FAILED'

    # Self-contained Git source identity for build_release consumer preconditions.
    # Must remain entirely inside candidate-source; never point at caller worktree.
    $candidateGitIdentity = Initialize-SealedCandidateSourceGitIdentity `
        -CandidateRoot $candidateCloneRoot `
        -ExpectedInventory $Preflight.candidate_source_inventory `
        -ExpectedTreeSha256 $Preflight.candidate_source_tree_sha256

    # Seal legacy v1 docker/entrypoint provenance outside runtime skill rendering trees.
    $evidenceDir = Join-Path $dest 'evidence'
    New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
    $activeLegacyProvRoot = Join-Path $evidenceDir 'legacy-provenance\active'
    $previousLegacyProvRoot = Join-Path $evidenceDir 'legacy-provenance\previous'
    $null = Copy-LegacyDockerProvenance `
        -SourceRoot $Preflight.active_legacy_repository_root `
        -DestinationRoot $activeLegacyProvRoot `
        -ExpectedInventory $Preflight.active_legacy_provenance_inventory `
        -ExpectedTreeSha256 $Preflight.active_legacy_provenance_tree_sha256 `
        -ReasonCode 'LEGACY_PROVENANCE_COPY_FAILED'
    $null = Copy-LegacyDockerProvenance `
        -SourceRoot $Preflight.previous_legacy_repository_root `
        -DestinationRoot $previousLegacyProvRoot `
        -ExpectedInventory $Preflight.previous_legacy_provenance_inventory `
        -ExpectedTreeSha256 $Preflight.previous_legacy_provenance_tree_sha256 `
        -ReasonCode 'LEGACY_PROVENANCE_COPY_FAILED'

    # Preserve original pointer bytes for evidence.
    $originalPointerPath = Join-Path $evidenceDir 'source-pointer.original.json'
    Write-BytesAtomic -PathValue $originalPointerPath -Bytes $Preflight.pointer_bytes -CreateNew
    if ((Get-Sha256File $originalPointerPath) -ne $Preflight.pointer_sha256_original) {
        Fail 'POINTER_EVIDENCE_DRIFT' $originalPointerPath
    }

    # Relocate only the two absolute release-manifest paths.
    $relocatedPointer = [ordered]@{}
    foreach ($key in ($Preflight.pointer.Keys | ForEach-Object { [string]$_ } | Sort-Object)) {
        $relocatedPointer[$key] = $Preflight.pointer[$key]
    }
    $relocatedPointer['release_manifest_path'] = $clonedActiveManifest
    $relocatedPointer['previous_release_manifest_path'] = $clonedPreviousManifest
    $relocatedText = ConvertTo-CanonicalJsonText -Value $relocatedPointer
    Write-Utf8NoBomFileAtomic -PathValue $layout.pointer -Text $relocatedText -CreateNew
    $relocatedPointerSha = Get-Sha256File $layout.pointer

    # Inventory every sealed product file except the receipt (written next).
    # .git is excluded from byte inventory and explicitly revalidated via candidate_source_git_identity
    # (index/logs are not consumer identity; status revalidation uses --no-optional-locks).
    $filesWithoutReceipt = Get-SortedRelativeInventory `
        -Root $dest `
        -ReasonCode 'PROOF_INVENTORY_INVALID' `
        -IgnoreDirectoryNames @('.git')
    $receiptPath = Join-Path $dest $script:ReceiptFileName

    $receiptBody = [ordered]@{
        schema_version           = $script:SchemaVersion
        prepared_at              = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
        candidate_source_git_identity = $candidateGitIdentity
        source                   = [ordered]@{
            live_state_root                      = $Preflight.state_root
            installed_skill_root                 = $Preflight.installed_skill_root
            active_source_rendering_root         = $Preflight.active_rendering_root
            previous_source_rendering_root       = $Preflight.previous_rendering_root
            candidate_source_root                = $Preflight.candidate_source_root
            active_legacy_repository_root        = $Preflight.active_legacy_repository_root
            previous_legacy_repository_root      = $Preflight.previous_legacy_repository_root
            pointer_path                         = $Preflight.pointer_path
            pointer_sha256_original              = $Preflight.pointer_sha256_original
            active_release_id                    = $Preflight.active_release_id
            previous_release_id                  = $Preflight.previous_release_id
            active_manifest_path                 = $Preflight.active_manifest_path
            previous_manifest_path               = $Preflight.previous_manifest_path
            active_manifest_sha256               = $Preflight.active_manifest_sha256
            previous_manifest_sha256             = $Preflight.previous_manifest_sha256
            installed_skill_tree_sha256          = $Preflight.installed_skill_tree_sha256
            active_rendering_tree_sha256         = $Preflight.active_rendering_tree_sha256
            previous_rendering_tree_sha256       = $Preflight.previous_rendering_tree_sha256
            candidate_source_tree_sha256         = $Preflight.candidate_source_tree_sha256
            active_legacy_provenance_tree_sha256 = $Preflight.active_legacy_provenance_tree_sha256
            previous_legacy_provenance_tree_sha256 = $Preflight.previous_legacy_provenance_tree_sha256
        }
        destination              = [ordered]@{
            proof_root                     = $dest
            skill_state_root               = $stateRoot
            installed_skill_root           = $installedRoot
            researcher_run_root            = $runRoot
            candidate_source_root          = $candidateCloneRoot
            active_manifest_path           = $clonedActiveManifest
            previous_manifest_path         = $clonedPreviousManifest
            pointer_path                   = $layout.pointer
            active_rendering_root          = $clonedActiveRendering
            previous_rendering_root        = $clonedPreviousRendering
            active_legacy_provenance_root  = $activeLegacyProvRoot
            previous_legacy_provenance_root = $previousLegacyProvRoot
            original_pointer_path          = $originalPointerPath
            approved_proof_base            = $approvedFull
        }
        pointer_relocation       = [ordered]@{
            original_release_manifest_path           = [string]$Preflight.pointer['release_manifest_path']
            original_previous_release_manifest_path  = [string]$Preflight.pointer['previous_release_manifest_path']
            relocated_release_manifest_path          = $clonedActiveManifest
            relocated_previous_release_manifest_path = $clonedPreviousManifest
            original_pointer_sha256                  = $Preflight.pointer_sha256_original
            relocated_pointer_sha256                 = $relocatedPointerSha
            keys_relocated                           = @(
                'release_manifest_path',
                'previous_release_manifest_path'
            )
        }
        proposed_environment     = [ordered]@{
            XINAO_SKILL_STATE_ROOT      = $stateRoot
            XINAO_RESEARCHER_RUN_ROOT   = $runRoot
            XINAO_INSTALLED_SKILL_ROOT  = $installedRoot
            XINAO_MIGRATION_SOURCE_ROOT = $candidateCloneRoot
        }
        inventories              = [ordered]@{
            installed_skill                        = @($Preflight.installed_inventory)
            installed_skill_tree_sha256            = $Preflight.installed_skill_tree_sha256
            active_rendering                       = @($Preflight.active_rendering_inventory)
            active_rendering_tree_sha256           = $Preflight.active_rendering_tree_sha256
            previous_rendering                     = @($Preflight.previous_rendering_inventory)
            previous_rendering_tree_sha256         = $Preflight.previous_rendering_tree_sha256
            candidate_source                       = @($Preflight.candidate_source_inventory)
            candidate_source_tree_sha256           = $Preflight.candidate_source_tree_sha256
            active_legacy_provenance               = @($Preflight.active_legacy_provenance_inventory)
            active_legacy_provenance_tree_sha256   = $Preflight.active_legacy_provenance_tree_sha256
            previous_legacy_provenance             = @($Preflight.previous_legacy_provenance_inventory)
            previous_legacy_provenance_tree_sha256 = $Preflight.previous_legacy_provenance_tree_sha256
        }
        files                    = @($filesWithoutReceipt)
        files_count              = @($filesWithoutReceipt).Count
        destination_tree_sha256  = (Get-InventoryTreeSha256 $filesWithoutReceipt)
        receipt_relative_path    = $script:ReceiptFileName
        live_source_mutated      = $false
        migration_executed       = $false
        authority                = $false
        completion_claim_allowed = $false
        verify_only              = $false
    }

    $bodyText = ConvertTo-CanonicalJsonText -Value $receiptBody
    $contentSha = Get-Sha256Bytes ([System.Text.UTF8Encoding]::new($false).GetBytes($bodyText))
    $receiptBody['receipt_content_sha256'] = $contentSha
    $sealedText = ConvertTo-CanonicalJsonText -Value $receiptBody
    Write-Utf8NoBomFileAtomic -PathValue $receiptPath -Text $sealedText -CreateNew

    return [ordered]@{
        proof_root   = $dest
        receipt_path = $receiptPath
        receipt      = (Read-JsonObjectFile -PathValue $receiptPath -ReasonCode 'RECEIPT_ABSENT')
    }
}

function Invoke-VerifyOnly {
    param(
        [Parameter(Mandatory)][string]$Destination,
        [string]$ApprovedBase = ''
    )
    $dest = Get-FullLiteralPath $Destination
    if (-not (Test-Path -LiteralPath $dest -PathType Container)) {
        Fail 'DESTINATION_ABSENT' $dest
    }
    Assert-NoReparseInChain $dest 'DESTINATION_REPARSE_FORBIDDEN'
    $receiptPath = Join-Path $dest $script:ReceiptFileName
    Assert-RegularFileSafe $receiptPath -ReasonCode 'RECEIPT_ABSENT'
    $receipt = Read-JsonObjectFile -PathValue $receiptPath -ReasonCode 'RECEIPT_ABSENT'

    Assert-ExactKeySet -Object $receipt -ExpectedKeys $script:ReceiptTopLevelKeys -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'receipt.top'
    if ([string]$receipt['schema_version'] -ne $script:SchemaVersion) {
        Fail 'RECEIPT_SCHEMA_INVALID' "schema_version:$receiptPath"
    }
    if ([string]$receipt['receipt_relative_path'] -ne $script:ReceiptFileName) {
        Fail 'RECEIPT_SCHEMA_INVALID' 'receipt_relative_path'
    }
    if ($receipt['verify_only'] -ne $false) {
        Fail 'RECEIPT_SCHEMA_INVALID' 'verify_only must be false on sealed prepare receipt'
    }
    foreach ($flag in @('live_source_mutated', 'migration_executed', 'authority', 'completion_claim_allowed')) {
        if ($receipt[$flag] -ne $false) {
            Fail 'RECEIPT_CLAIM_FLAG_INVALID' "$flag=$($receipt[$flag])"
        }
    }
    if ($receipt['files_count'] -isnot [int64] -and $receipt['files_count'] -isnot [int] -and $receipt['files_count'] -isnot [long]) {
        Fail 'RECEIPT_SCHEMA_INVALID' 'files_count type'
    }
    if ([string]$receipt['destination_tree_sha256'] -notmatch $script:HexSha256Pattern) {
        Fail 'RECEIPT_SCHEMA_INVALID' 'destination_tree_sha256'
    }
    if ([string]$receipt['receipt_content_sha256'] -notmatch $script:HexSha256Pattern) {
        Fail 'RECEIPT_SCHEMA_INVALID' 'receipt_content_sha256'
    }
    if ([string]::IsNullOrWhiteSpace([string]$receipt['prepared_at'])) {
        Fail 'RECEIPT_SCHEMA_INVALID' 'prepared_at'
    }

    Assert-ExactKeySet -Object $receipt['source'] -ExpectedKeys $script:ReceiptSourceKeys -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'receipt.source'
    Assert-ExactKeySet -Object $receipt['destination'] -ExpectedKeys $script:ReceiptDestinationKeys -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'receipt.destination'
    Assert-ExactKeySet -Object $receipt['pointer_relocation'] -ExpectedKeys $script:ReceiptPointerRelocationKeys -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'receipt.pointer_relocation'
    Assert-ExactKeySet -Object $receipt['proposed_environment'] -ExpectedKeys $script:ReceiptEnvironmentKeys -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'receipt.proposed_environment'
    Assert-ExactKeySet -Object $receipt['inventories'] -ExpectedKeys $script:ReceiptInventoryKeys -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'receipt.inventories'
    Assert-ExactKeySet -Object $receipt['candidate_source_git_identity'] -ExpectedKeys $script:ReceiptCandidateGitIdentityKeys -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'receipt.candidate_source_git_identity'

    $inv = $receipt['inventories']
    foreach ($name in @(
            'installed_skill',
            'active_rendering',
            'previous_rendering',
            'candidate_source',
            'active_legacy_provenance',
            'previous_legacy_provenance'
        )) {
        Assert-InventoryRowsSchema -Rows $inv[$name] -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context "inventories.$name"
    }
    foreach ($name in @(
            'installed_skill_tree_sha256',
            'active_rendering_tree_sha256',
            'previous_rendering_tree_sha256',
            'candidate_source_tree_sha256',
            'active_legacy_provenance_tree_sha256',
            'previous_legacy_provenance_tree_sha256'
        )) {
        if ([string]$inv[$name] -notmatch $script:HexSha256Pattern) {
            Fail 'RECEIPT_SCHEMA_INVALID' "inventories.$name"
        }
    }
    Assert-InventoryRowsSchema -Rows $receipt['files'] -ReasonCode 'RECEIPT_SCHEMA_INVALID' -Context 'files'

    $approvedResolved = if (-not [string]::IsNullOrWhiteSpace($ApprovedBase)) {
        Get-FullLiteralPath $ApprovedBase
    }
    else {
        Get-FullLiteralPath ([string]$receipt['destination']['approved_proof_base'])
    }
    Assert-DestinationAllowed -Destination $dest -ApprovedBase $approvedResolved -ForbiddenRoots @()
    if (-not (Test-PathsEqual $dest ([string]$receipt['destination']['proof_root']))) {
        Fail 'PROOF_PATH_TOPOLOGY_INVALID' 'destination.proof_root'
    }
    if (-not (Test-PathsEqual $approvedResolved ([string]$receipt['destination']['approved_proof_base']))) {
        Fail 'PROOF_PATH_TOPOLOGY_INVALID' 'destination.approved_proof_base'
    }

    $dst = $receipt['destination']
    $envMap = $receipt['proposed_environment']
    # Exact derived path topology under DestinationProofRoot.
    $expectedPaths = [ordered]@{
        skill_state_root                = (Join-Path $dest 'isolated-state')
        installed_skill_root            = (Join-Path $dest 'installed-skill')
        researcher_run_root             = (Join-Path $dest 'researcher-runs')
        candidate_source_root           = (Join-Path $dest 'candidate-source')
        pointer_path                    = (Join-Path $dest 'isolated-state\researcher_container\current.json')
        original_pointer_path           = (Join-Path $dest 'evidence\source-pointer.original.json')
        active_legacy_provenance_root   = (Join-Path $dest 'evidence\legacy-provenance\active')
        previous_legacy_provenance_root = (Join-Path $dest 'evidence\legacy-provenance\previous')
    }
    foreach ($key in $expectedPaths.Keys) {
        if (-not (Test-PathsEqual ([string]$dst[$key]) ([string]$expectedPaths[$key]))) {
            Fail 'PROOF_PATH_TOPOLOGY_INVALID' $key
        }
    }
    $activeId = [string]$receipt['source']['active_release_id']
    $previousId = [string]$receipt['source']['previous_release_id']
    if (-not (Test-PathsEqual ([string]$dst['active_manifest_path']) (Join-Path $dest "isolated-state\researcher_container\releases\$activeId\release.json"))) {
        Fail 'PROOF_PATH_TOPOLOGY_INVALID' 'active_manifest_path'
    }
    if (-not (Test-PathsEqual ([string]$dst['previous_manifest_path']) (Join-Path $dest "isolated-state\researcher_container\releases\$previousId\release.json"))) {
        Fail 'PROOF_PATH_TOPOLOGY_INVALID' 'previous_manifest_path'
    }
    if (-not (Test-PathsEqual ([string]$dst['active_rendering_root']) (Join-Path $dest "isolated-state\researcher_container\migration\source_renderings\$activeId"))) {
        Fail 'PROOF_PATH_TOPOLOGY_INVALID' 'active_rendering_root'
    }
    if (-not (Test-PathsEqual ([string]$dst['previous_rendering_root']) (Join-Path $dest "isolated-state\researcher_container\migration\source_renderings\$previousId"))) {
        Fail 'PROOF_PATH_TOPOLOGY_INVALID' 'previous_rendering_root'
    }

    # Every proposed environment path exact and under proof root.
    if (-not (Test-PathsEqual ([string]$envMap['XINAO_SKILL_STATE_ROOT']) ([string]$dst['skill_state_root']))) {
        Fail 'PROOF_PATH_TOPOLOGY_INVALID' 'env.XINAO_SKILL_STATE_ROOT'
    }
    if (-not (Test-PathsEqual ([string]$envMap['XINAO_RESEARCHER_RUN_ROOT']) ([string]$dst['researcher_run_root']))) {
        Fail 'PROOF_PATH_TOPOLOGY_INVALID' 'env.XINAO_RESEARCHER_RUN_ROOT'
    }
    if (-not (Test-PathsEqual ([string]$envMap['XINAO_INSTALLED_SKILL_ROOT']) ([string]$dst['installed_skill_root']))) {
        Fail 'PROOF_PATH_TOPOLOGY_INVALID' 'env.XINAO_INSTALLED_SKILL_ROOT'
    }
    if (-not (Test-PathsEqual ([string]$envMap['XINAO_MIGRATION_SOURCE_ROOT']) ([string]$dst['candidate_source_root']))) {
        Fail 'PROOF_PATH_TOPOLOGY_INVALID' 'env.XINAO_MIGRATION_SOURCE_ROOT'
    }
    foreach ($key in $script:ReceiptEnvironmentKeys) {
        $pathValue = Get-FullLiteralPath ([string]$envMap[$key])
        if (-not (Test-IsStrictChildPath -Parent $dest -Child $pathValue) -and -not (Test-PathsEqual $dest $pathValue)) {
            # env roots are children of proof root
            if (-not (Test-IsStrictChildPath -Parent $dest -Child $pathValue)) {
                Fail 'PROOF_PATH_TOPOLOGY_INVALID' "env outside proof root: $key"
            }
        }
        if (-not (Test-IsStrictChildPath -Parent $dest -Child $pathValue)) {
            Fail 'PROOF_PATH_TOPOLOGY_INVALID' "env outside proof root: $key"
        }
    }

    $pointerPath = [string]$dst['pointer_path']
    Assert-RegularFileSafe $pointerPath -ReasonCode 'POINTER_ABSENT'
    $pointer = Read-JsonObjectFile $pointerPath
    Assert-LegacyPointer -Pointer $pointer -PointerPath $pointerPath
    $reloc = $receipt['pointer_relocation']
    $relocKeys = @($reloc['keys_relocated'] | ForEach-Object { [string]$_ } | Sort-Object)
    if (($relocKeys -join '|') -ne 'previous_release_manifest_path|release_manifest_path') {
        Fail 'RECEIPT_SCHEMA_INVALID' 'pointer_relocation.keys_relocated'
    }
    if (-not (Test-PathsEqual ([string]$pointer['release_manifest_path']) ([string]$reloc['relocated_release_manifest_path']))) {
        Fail 'POINTER_RELOCATION_MISMATCH' 'release_manifest_path'
    }
    if (-not (Test-PathsEqual ([string]$pointer['previous_release_manifest_path']) ([string]$reloc['relocated_previous_release_manifest_path']))) {
        Fail 'POINTER_RELOCATION_MISMATCH' 'previous_release_manifest_path'
    }
    if (-not (Test-PathsEqual ([string]$pointer['release_manifest_path']) ([string]$dst['active_manifest_path']))) {
        Fail 'POINTER_RELOCATION_MISMATCH' 'active_manifest_path'
    }
    if (-not (Test-PathsEqual ([string]$pointer['previous_release_manifest_path']) ([string]$dst['previous_manifest_path']))) {
        Fail 'POINTER_RELOCATION_MISMATCH' 'previous_manifest_path'
    }
    $observedPointerSha = Get-Sha256File $pointerPath
    if ($observedPointerSha -ne [string]$reloc['relocated_pointer_sha256']) {
        Fail 'POINTER_HASH_DRIFT' $pointerPath
    }
    if ((Get-Sha256File ([string]$dst['original_pointer_path'])) -ne [string]$reloc['original_pointer_sha256']) {
        Fail 'ORIGINAL_POINTER_HASH_DRIFT' ([string]$dst['original_pointer_path'])
    }

    # Releases pure + hashes.
    foreach ($pair in @(
            @{
                id   = $activeId
                path = [string]$dst['active_manifest_path']
                sha  = [string]$receipt['source']['active_manifest_sha256']
            },
            @{
                id   = $previousId
                path = [string]$dst['previous_manifest_path']
                sha  = [string]$receipt['source']['previous_manifest_sha256']
            }
        )) {
        $dir = Split-Path -Parent $pair.path
        Assert-PureReleaseDirectory -ReleaseDir $dir -ReleaseId $pair.id | Out-Null
        if ((Get-Sha256File $pair.path) -ne $pair.sha) {
            Fail 'RELEASE_HASH_DRIFT' $pair.path
        }
        $manifest = Read-JsonObjectFile $pair.path
        Assert-LegacyReleaseManifest -Manifest $manifest -ExpectedReleaseId $pair.id -ManifestPath $pair.path
    }

    $activeManifest = Read-JsonObjectFile ([string]$dst['active_manifest_path'])
    $previousManifest = Read-JsonObjectFile ([string]$dst['previous_manifest_path'])
    $activeRendering = [string]$dst['active_rendering_root']
    $previousRendering = [string]$dst['previous_rendering_root']

    # Renderings rebound to receipt inventories + skill-side hashes vs manifests.
    $activeRenderingInv = Get-SortedRelativeInventory -Root $activeRendering -ReasonCode 'RENDERING_HASH_DRIFT'
    $previousRenderingInv = Get-SortedRelativeInventory -Root $previousRendering -ReasonCode 'RENDERING_HASH_DRIFT'
    Assert-InventoryEqual -Left $inv['active_rendering'] -Right $activeRenderingInv -ReasonCode 'RENDERING_INVENTORY_DRIFT' -Context 'active'
    Assert-InventoryEqual -Left $inv['previous_rendering'] -Right $previousRenderingInv -ReasonCode 'RENDERING_INVENTORY_DRIFT' -Context 'previous'
    $activeRenderingTree = Get-InventoryTreeSha256 $activeRenderingInv
    $previousRenderingTree = Get-InventoryTreeSha256 $previousRenderingInv
    if ($activeRenderingTree -ne [string]$inv['active_rendering_tree_sha256'] -or
        $activeRenderingTree -ne [string]$receipt['source']['active_rendering_tree_sha256']) {
        Fail 'RENDERING_TREE_SHA_DRIFT' 'active'
    }
    if ($previousRenderingTree -ne [string]$inv['previous_rendering_tree_sha256'] -or
        $previousRenderingTree -ne [string]$receipt['source']['previous_rendering_tree_sha256']) {
        Fail 'RENDERING_TREE_SHA_DRIFT' 'previous'
    }
    $activeSide = Get-LegacySkillSideHashes $activeRendering
    $previousSide = Get-LegacySkillSideHashes $previousRendering
    foreach ($key in $script:LegacySkillRenderingHashKeys) {
        if ([string]$activeManifest['skill_hashes'][$key] -ne [string]$activeSide[$key]) {
            Fail 'RENDERING_HASH_DRIFT' "active:$key"
        }
        if ([string]$previousManifest['skill_hashes'][$key] -ne [string]$previousSide[$key]) {
            Fail 'RENDERING_HASH_DRIFT' "previous:$key"
        }
    }

    # Installed skill inventory + tree.
    $installedRoot = [string]$dst['installed_skill_root']
    $installedInventory = Get-SortedRelativeInventory -Root $installedRoot -ReasonCode 'INSTALLED_SKILL_INVALID'
    Assert-InventoryEqual -Left $inv['installed_skill'] -Right $installedInventory -ReasonCode 'INSTALLED_SKILL_TREE_DRIFT' -Context 'installed'
    $installedTreeSha = Get-InventoryTreeSha256 $installedInventory
    if ($installedTreeSha -ne [string]$inv['installed_skill_tree_sha256'] -or
        $installedTreeSha -ne [string]$receipt['source']['installed_skill_tree_sha256']) {
        Fail 'INSTALLED_SKILL_TREE_DRIFT' $installedRoot
    }

    # Sealed candidate source inventory (v2 generation; not bound to legacy dockerfile hashes).
    $candidateRoot = [string]$dst['candidate_source_root']
    $candidateInv = Get-CandidateSourceInventory -Root $candidateRoot -ReasonCode 'CANDIDATE_SOURCE_DRIFT'
    Assert-InventoryEqual -Left $inv['candidate_source'] -Right $candidateInv -ReasonCode 'CANDIDATE_SOURCE_DRIFT' -Context 'candidate'
    $candidateTree = Get-InventoryTreeSha256 $candidateInv
    if ($candidateTree -ne [string]$inv['candidate_source_tree_sha256'] -or
        $candidateTree -ne [string]$receipt['source']['candidate_source_tree_sha256']) {
        Fail 'CANDIDATE_SOURCE_TREE_DRIFT' $candidateRoot
    }

    # Revalidate self-contained Git identity required by build_release (HEAD/tree/clean status).
    Assert-SealedCandidateSourceGitIdentity `
        -CandidateRoot $candidateRoot `
        -ExpectedIdentity $receipt['candidate_source_git_identity'] `
        -ExpectedInventory $inv['candidate_source'] `
        -ReasonCode 'CANDIDATE_SOURCE_GIT_IDENTITY_DRIFT'

    # Legacy docker provenance inventories + bind to release skill_hashes.
    foreach ($side in @(
            @{
                Label    = 'active'
                Root     = [string]$dst['active_legacy_provenance_root']
                InvKey   = 'active_legacy_provenance'
                TreeKey  = 'active_legacy_provenance_tree_sha256'
                Manifest = $activeManifest
                Release  = $activeId
            },
            @{
                Label    = 'previous'
                Root     = [string]$dst['previous_legacy_provenance_root']
                InvKey   = 'previous_legacy_provenance'
                TreeKey  = 'previous_legacy_provenance_tree_sha256'
                Manifest = $previousManifest
                Release  = $previousId
            }
        )) {
        $provInv = Get-LegacyDockerProvenanceInventory -RepositoryRoot $side.Root -ReasonCode 'LEGACY_PROVENANCE_DRIFT'
        Assert-InventoryEqual -Left $inv[$side.InvKey] -Right $provInv -ReasonCode 'LEGACY_PROVENANCE_DRIFT' -Context $side.Label
        $provTree = Get-InventoryTreeSha256 $provInv
        if ($provTree -ne [string]$inv[$side.TreeKey] -or
            $provTree -ne [string]$receipt['source'][$side.TreeKey]) {
            Fail 'LEGACY_PROVENANCE_TREE_DRIFT' $side.Label
        }
        $map = @{}
        foreach ($row in $provInv) {
            $map[[string]$row.relative_path] = [string]$row.sha256
        }
        if ($map['docker/xinao-researcher/Dockerfile'] -ne [string]$side.Manifest['skill_hashes']['dockerfile_sha256']) {
            Fail 'LEGACY_DOCKERFILE_HASH_MISMATCH' "$($side.Release):dockerfile_sha256"
        }
        if ($map['docker/xinao-researcher/entrypoint.py'] -ne [string]$side.Manifest['skill_hashes']['entrypoint_sha256']) {
            Fail 'LEGACY_ENTRYPOINT_HASH_MISMATCH' "$($side.Release):entrypoint_sha256"
        }
    }

    # Full cone inventory vs receipt.files (excluding receipt and .git control dir).
    $observed = Get-SortedRelativeInventory `
        -Root $dest `
        -ReasonCode 'PROOF_INVENTORY_INVALID' `
        -IgnoreDirectoryNames @('.git')
    $observedWithoutReceipt = @($observed | Where-Object {
            $rel = if ($_ -is [System.Collections.IDictionary]) { [string]$_['relative_path'] } else { [string]$_.relative_path }
            $rel -ne $script:ReceiptFileName
        })
    $expectedFiles = @($receipt['files'])
    if ([int64]$receipt['files_count'] -ne [int64]@($expectedFiles).Count) {
        Fail 'RECEIPT_SCHEMA_INVALID' 'files_count does not match files[]'
    }
    if (@($observedWithoutReceipt).Count -ne @($expectedFiles).Count) {
        Fail 'PROOF_INVENTORY_COUNT_MISMATCH' "observed=$(@($observedWithoutReceipt).Count) expected=$(@($expectedFiles).Count)"
    }
    $expectedMap = @{}
    foreach ($row in $expectedFiles) {
        $expectedMap[[string]$row['relative_path']] = $row
    }
    foreach ($row in $observedWithoutReceipt) {
        $rel = if ($row -is [System.Collections.IDictionary]) { [string]$row['relative_path'] } else { [string]$row.relative_path }
        $sha = if ($row -is [System.Collections.IDictionary]) { [string]$row['sha256'] } else { [string]$row.sha256 }
        $size = if ($row -is [System.Collections.IDictionary]) { [int64]$row['size'] } else { [int64]$row.size }
        if (-not $expectedMap.ContainsKey($rel)) {
            Fail 'PROOF_EXTRA_FILE' $rel
        }
        $exp = $expectedMap[$rel]
        if ([string]$exp['sha256'] -ne $sha -or [int64]$exp['size'] -ne $size) {
            Fail 'PROOF_FILE_DRIFT' $rel
        }
    }
    foreach ($rel in $expectedMap.Keys) {
        $hit = $false
        foreach ($row in $observedWithoutReceipt) {
            $rrel = if ($row -is [System.Collections.IDictionary]) { [string]$row['relative_path'] } else { [string]$row.relative_path }
            if ($rrel -eq $rel) { $hit = $true; break }
        }
        if (-not $hit) {
            Fail 'PROOF_MISSING_FILE' $rel
        }
    }

    $treeSha = Get-InventoryTreeSha256 $observedWithoutReceipt
    if ($treeSha -ne [string]$receipt['destination_tree_sha256']) {
        Fail 'PROOF_TREE_SHA_MISMATCH' $treeSha
    }

    # Content hash over receipt body without receipt_content_sha256.
    $body = [ordered]@{}
    foreach ($key in ($receipt.Keys | ForEach-Object { [string]$_ } | Sort-Object)) {
        if ($key -eq 'receipt_content_sha256') { continue }
        $body[$key] = $receipt[$key]
    }
    $bodyText = ConvertTo-CanonicalJsonText -Value $body
    $contentSha = Get-Sha256Bytes ([System.Text.UTF8Encoding]::new($false).GetBytes($bodyText))
    if ($contentSha -ne [string]$receipt['receipt_content_sha256']) {
        Fail 'RECEIPT_CONTENT_SHA_MISMATCH' $receiptPath
    }

    return [ordered]@{
        status                   = 'VERIFIED'
        proof_root               = $dest
        receipt_path             = $receiptPath
        destination_tree_sha256  = $treeSha
        relocated_pointer_sha256 = [string]$reloc['relocated_pointer_sha256']
        original_pointer_sha256  = [string]$reloc['original_pointer_sha256']
        live_source_mutated      = $false
        migration_executed       = $false
        authority                = $false
        completion_claim_allowed = $false
    }
}

function Invoke-FreshProcessVerify {
    param(
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$ApprovedBase
    )
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $args = @(
        '-NoLogo',
        '-NoProfile',
        '-File', $PSCommandPath,
        '-VerifyOnly',
        '-DestinationProofRoot', $Destination,
        '-ApprovedProofBase', $ApprovedBase
    )
    $output = & $pwsh @args 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        $text = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
        Fail 'FRESH_PROCESS_VERIFY_FAILED' "exit=$code :: $text"
    }
    return ($output | Out-String)
}

# ----------------------- main -----------------------

try {
    if ($VerifyOnly) {
        $result = Invoke-VerifyOnly -Destination $DestinationProofRoot -ApprovedBase $ApprovedProofBase
        $text = ConvertTo-CanonicalJsonText -Value $result
        Write-Output $text.TrimEnd()
        exit 0
    }

    foreach ($name in @(
            'SourceLiveStateRoot',
            'SourceInstalledSkillRoot',
            'ActiveSourceRenderingRoot',
            'PreviousSourceRenderingRoot',
            'CandidateSourceRoot',
            'ActiveLegacyRepositoryRoot',
            'PreviousLegacyRepositoryRoot'
        )) {
        $value = Get-Variable -Name $name -ValueOnly
        if ([string]::IsNullOrWhiteSpace([string]$value)) {
            Fail 'PARAMETER_REQUIRED' $name
        }
    }

    $preflight = Invoke-SourcePreflight `
        -LiveStateRoot $SourceLiveStateRoot `
        -InstalledSkillRoot $SourceInstalledSkillRoot `
        -ActiveRenderingRoot $ActiveSourceRenderingRoot `
        -PreviousRenderingRoot $PreviousSourceRenderingRoot `
        -CandidateSourceRoot $CandidateSourceRoot `
        -ActiveLegacyRepositoryRoot $ActiveLegacyRepositoryRoot `
        -PreviousLegacyRepositoryRoot $PreviousLegacyRepositoryRoot

    # Capture live source fingerprints before any write for post-check.
    $liveFingerprints = [ordered]@{
        pointer              = $preflight.pointer_sha256_original
        active               = $preflight.active_manifest_sha256
        previous             = $preflight.previous_manifest_sha256
        installed            = $preflight.installed_skill_tree_sha256
        active_rendering     = $preflight.active_rendering_tree_sha256
        previous_rendering   = $preflight.previous_rendering_tree_sha256
        candidate            = $preflight.candidate_source_tree_sha256
        active_legacy        = $preflight.active_legacy_provenance_tree_sha256
        previous_legacy      = $preflight.previous_legacy_provenance_tree_sha256
    }

    $created = New-ProofCone -Preflight $preflight -Destination $DestinationProofRoot -ApprovedBase $ApprovedProofBase

    # Live sources must be unchanged (do not silently re-inventory a drifted source as accepted).
    if ((Get-Sha256File $preflight.pointer_path) -ne $liveFingerprints.pointer) {
        Fail 'LIVE_SOURCE_MUTATED' $preflight.pointer_path
    }
    if ((Get-Sha256File $preflight.active_manifest_path) -ne $liveFingerprints.active) {
        Fail 'LIVE_SOURCE_MUTATED' $preflight.active_manifest_path
    }
    if ((Get-Sha256File $preflight.previous_manifest_path) -ne $liveFingerprints.previous) {
        Fail 'LIVE_SOURCE_MUTATED' $preflight.previous_manifest_path
    }
    $installedNow = Get-SortedRelativeInventory -Root $preflight.installed_skill_root -ReasonCode 'INSTALLED_SKILL_INVALID'
    if ((Get-InventoryTreeSha256 $installedNow) -ne $liveFingerprints.installed) {
        Fail 'LIVE_SOURCE_MUTATED' $preflight.installed_skill_root
    }
    $activeRenderingNow = Get-SortedRelativeInventory -Root $preflight.active_rendering_root -ReasonCode 'SKILL_BUNDLE_SOURCE_INVALID'
    if ((Get-InventoryTreeSha256 $activeRenderingNow) -ne $liveFingerprints.active_rendering) {
        Fail 'LIVE_SOURCE_MUTATED' $preflight.active_rendering_root
    }
    $previousRenderingNow = Get-SortedRelativeInventory -Root $preflight.previous_rendering_root -ReasonCode 'SKILL_BUNDLE_SOURCE_INVALID'
    if ((Get-InventoryTreeSha256 $previousRenderingNow) -ne $liveFingerprints.previous_rendering) {
        Fail 'LIVE_SOURCE_MUTATED' $preflight.previous_rendering_root
    }
    $candidateNow = Get-CandidateSourceInventory -Root $preflight.candidate_source_root -ReasonCode 'MIGRATION_SOURCE_CONE_MISSING'
    if ((Get-InventoryTreeSha256 $candidateNow) -ne $liveFingerprints.candidate) {
        Fail 'LIVE_SOURCE_MUTATED' $preflight.candidate_source_root
    }
    $activeLegacyNow = Get-LegacyDockerProvenanceInventory -RepositoryRoot $preflight.active_legacy_repository_root -ReasonCode 'LEGACY_DOCKER_PROVENANCE_INVALID'
    if ((Get-InventoryTreeSha256 $activeLegacyNow) -ne $liveFingerprints.active_legacy) {
        Fail 'LIVE_SOURCE_MUTATED' $preflight.active_legacy_repository_root
    }
    $previousLegacyNow = Get-LegacyDockerProvenanceInventory -RepositoryRoot $preflight.previous_legacy_repository_root -ReasonCode 'LEGACY_DOCKER_PROVENANCE_INVALID'
    if ((Get-InventoryTreeSha256 $previousLegacyNow) -ne $liveFingerprints.previous_legacy) {
        Fail 'LIVE_SOURCE_MUTATED' $preflight.previous_legacy_repository_root
    }

    $null = Invoke-FreshProcessVerify -Destination $created.proof_root -ApprovedBase $ApprovedProofBase
    $script:OwnedConeCreated = $false  # success: do not clean up
    $script:CreatedEmptyDestPendingMarker = $false

    $summary = [ordered]@{
        status                       = 'PREPARED'
        proof_root                   = $created.proof_root
        receipt_path                 = $created.receipt_path
        original_pointer_sha256      = [string]$created.receipt['pointer_relocation']['original_pointer_sha256']
        relocated_pointer_sha256     = [string]$created.receipt['pointer_relocation']['relocated_pointer_sha256']
        destination_tree_sha256      = [string]$created.receipt['destination_tree_sha256']
        proposed_environment         = $created.receipt['proposed_environment']
        live_source_mutated          = $false
        migration_executed           = $false
        authority                    = $false
        completion_claim_allowed     = $false
        fresh_process_verify         = 'passed'
    }
    Write-Output ((ConvertTo-CanonicalJsonText -Value $summary).TrimEnd())
    exit 0
}
catch {
    try {
        Remove-OwnedFailedCone -Destination $DestinationProofRoot -ApprovedBase $ApprovedProofBase
    }
    catch {
        Write-Warning "Cleanup after failure also failed: $($_.Exception.Message)"
    }
    Write-Error $_
    exit 1
}
