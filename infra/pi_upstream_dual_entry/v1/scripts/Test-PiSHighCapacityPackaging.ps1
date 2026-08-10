#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AgentDir,
    [Parameter(Mandatory)][string]$PiToolRoot,
    [string]$ReceiptPath,
    [string]$TypeScriptCompilerPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\','/')
}

function Test-PathEqual {
    param([Parameter(Mandatory)][string]$Left,[Parameter(Mandatory)][string]$Right)
    [string]::Equals((Get-NormalizedPath $Left),(Get-NormalizedPath $Right),[StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoReparseAncestor {
    param([Parameter(Mandatory)][string]$Path)
    $cursor = Get-NormalizedPath $Path
    $root = [IO.Path]::GetPathRoot($cursor)
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "PI_HIGH_CAPACITY_PACKAGING_REPARSE_REJECTED: $cursor"
            }
        }
        if (Test-PathEqual $cursor $root) { break }
        $parent = Split-Path -Parent $cursor
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ceq $cursor) { break }
        $cursor = $parent
    }
}

function ConvertTo-CommandLineArgument {
    param([AllowEmptyString()][string]$Value)
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '(\\*)"','$1$1\"' -replace '(\\+)$','$1$1') + '"'
}

function Invoke-HiddenProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [int]$TimeoutMs = 600000
    )
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $FilePath
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.Arguments = (@($Arguments | ForEach-Object { ConvertTo-CommandLineArgument ([string]$_) }) -join ' ')
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { throw "PI_HIGH_CAPACITY_PACKAGING_PROCESS_START_FAILED: $FilePath" }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TimeoutMs)) {
        try { $process.Kill() } catch { $null = $_ }
        $process.WaitForExit()
        throw "PI_HIGH_CAPACITY_PACKAGING_PROCESS_TIMEOUT: $FilePath"
    }
    [pscustomobject]@{
        exit_code = [int]$process.ExitCode
        stdout = [string]$stdoutTask.GetAwaiter().GetResult()
        stderr = [string]$stderrTask.GetAwaiter().GetResult()
    }
}

function ConvertTo-PowerShellLiteral {
    param([Parameter(Mandatory)]$Value)
    if ($Value -is [bool]) { if ($Value) { return '$true' } else { return '$false' } }
    return "'" + ([string]$Value).Replace("'","''") + "'"
}

function Invoke-HiddenPowerShellScript {
    param(
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Parameters,
        [int]$TimeoutMs = 600000
    )
    $pairs = @($Parameters.GetEnumerator() | ForEach-Object {
        "'$(($_.Key -replace "'","''"))' = $(ConvertTo-PowerShellLiteral $_.Value)"
    }) -join '; '
    $quotedScript = ConvertTo-PowerShellLiteral (Get-NormalizedPath $ScriptPath)
    $source = @"
`$ErrorActionPreference = 'Stop'
try {
    `$invokeParameters = @{ $pairs }
    `$value = & $quotedScript @invokeParameters
    if (`$null -ne `$value) { [Console]::Out.Write([string](`$value -join [Environment]::NewLine)) }
    exit 0
} catch {
    [Console]::Error.WriteLine([string]`$_.Exception.Message)
    exit 1
}
"@
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($source))
    Invoke-HiddenProcess -FilePath $script:PowerShellPath -Arguments @('-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded) -TimeoutMs $TimeoutMs
}

function ConvertFrom-ChildJson {
    param([Parameter(Mandatory)]$Result,[Parameter(Mandatory)][string]$Case)
    if ($Result.exit_code -ne 0) {
        throw "PI_HIGH_CAPACITY_PACKAGING_CASE_FAILED: case=$Case exit=$($Result.exit_code) stderr=$($Result.stderr.Trim()) stdout=$($Result.stdout.Trim())"
    }
    try { return ($Result.stdout.Trim() | ConvertFrom-Json) }
    catch { throw "PI_HIGH_CAPACITY_PACKAGING_JSON_INVALID: case=$Case stdout=$($Result.stdout.Trim())" }
}

function Assert-HighCapacityCandidateManifestReceipt {
    param(
        [Parameter(Mandatory)]$Receipt,
        [Parameter(Mandatory)][string]$Case,
        [Parameter(Mandatory)][string]$ExpectedSha256,
        [Parameter(Mandatory)][long]$ExpectedBytes
    )
    if ([string]$Receipt.candidate_manifest_sha256 -cne $ExpectedSha256 -or
        [long]$Receipt.candidate_manifest_bytes -ne $ExpectedBytes -or
        (Split-Path -Leaf ([string]$Receipt.candidate_manifest_path)) -cne 'pi-s-high-capacity-v4.2-manifest.json' -or
        [string]$Receipt.patch_id -cne 'pi-high-capacity-compatibility-v4.2') {
        throw "PI_HIGH_CAPACITY_PACKAGING_CANDIDATE_MANIFEST_RECEIPT_DRIFT: $Case"
    }
}

function Assert-ExpectedFailure {
    param([Parameter(Mandatory)]$Result,[Parameter(Mandatory)][string]$Case,[Parameter(Mandatory)][string]$Pattern)
    if ($Result.exit_code -eq 0) { throw "PI_HIGH_CAPACITY_PACKAGING_EXPECTED_FAILURE_MISSING: $Case" }
    $combined = "$($Result.stderr)`n$($Result.stdout)"
    if ($combined -notmatch $Pattern) {
        throw "PI_HIGH_CAPACITY_PACKAGING_FAILURE_ID_MISMATCH: case=$Case expected=$Pattern actual=$($combined.Trim())"
    }
    [ordered]@{ status = 'pass'; exit_code = $Result.exit_code; matched = $Pattern; error = $combined.Trim() }
}

function Get-PathState {
    param([Parameter(Mandatory)][string]$Path,[switch]$IncludeContent)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]@{ path=$Path; kind='absent'; bytes=0; sha256='absent'; content=$null }
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (-not ($item -is [IO.FileInfo]) -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        return [pscustomobject]@{ path=$Path; kind='invalid-object'; bytes=0; sha256='invalid-object'; content=$null }
    }
    $content = if ($IncludeContent) { [IO.File]::ReadAllBytes($Path) } else { $null }
    [pscustomobject]@{
        path = $Path
        kind = 'file'
        bytes = [Int64]$item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        content = $content
    }
}

function Get-LifecycleSnapshot {
    param([Parameter(Mandatory)][string]$TargetAgentDir,[Parameter(Mandatory)][string]$TargetPiToolRoot,[switch]$IncludeContent)
    $packageRoot = Join-Path $TargetAgentDir 'npm\node_modules\pi-subagents'
    $coreRoot = Join-Path $TargetPiToolRoot 'node_modules\@earendil-works\pi-coding-agent'
    $result = [ordered]@{}
    foreach ($relative in $script:PackageAffectedFiles) {
        $result["package::$relative"] = Get-PathState -Path (Join-Path $packageRoot $relative) -IncludeContent:$IncludeContent
    }
    foreach ($relative in $script:CoreAffectedFiles) {
        $result["core::$relative"] = Get-PathState -Path (Join-Path $coreRoot $relative) -IncludeContent:$IncludeContent
    }
    return $result
}

function Get-SnapshotDigest {
    param([Parameter(Mandatory)][System.Collections.IDictionary]$Snapshot)
    $lines = @($Snapshot.Keys | ForEach-Object {
        $state = $Snapshot[$_]
        "$_`t$($state.kind)`t$($state.bytes)`t$($state.sha256)"
    }) -join "`n"
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($lines)) }
    finally { $sha.Dispose() }
    @($hash | ForEach-Object { $_.ToString('x2') }) -join ''
}

function Get-TreeFingerprint {
    param([Parameter(Mandatory)][string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return 'absent' }
    $canonicalRoot = Get-NormalizedPath $Root
    $builder = New-Object Text.StringBuilder
    foreach ($file in @(Get-ChildItem -LiteralPath $canonicalRoot -Recurse -File -Force | Sort-Object FullName)) {
        if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "PI_HIGH_CAPACITY_PACKAGING_TREE_REPARSE_REJECTED: $($file.FullName)"
        }
        $relative = $file.FullName.Substring($canonicalRoot.Length + 1).Replace('\','/')
        $sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        [void]$builder.Append($relative).Append("`t").Append($file.Length).Append("`t").Append($sha256).Append("`n")
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($builder.ToString())) }
    finally { $sha.Dispose() }
    ([BitConverter]::ToString($hash)).Replace('-','').ToLowerInvariant()
}

function Assert-SnapshotEqual {
    param(
        [Parameter(Mandatory)][System.Collections.IDictionary]$Expected,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Actual,
        [Parameter(Mandatory)][string]$Case
    )
    $differences = New-Object Collections.Generic.List[string]
    foreach ($key in $Expected.Keys) {
        if (-not $Actual.Contains($key)) { $differences.Add("$key=missing"); continue }
        $left = $Expected[$key]; $right = $Actual[$key]
        if ($left.kind -cne $right.kind -or $left.sha256 -cne $right.sha256 -or [Int64]$left.bytes -ne [Int64]$right.bytes) {
            $differences.Add("$key=$($left.kind)/$($left.sha256)/$($left.bytes)!=$($right.kind)/$($right.sha256)/$($right.bytes)")
        }
    }
    if ($differences.Count -gt 0 -or $Expected.Count -ne $Actual.Count) {
        throw "PI_HIGH_CAPACITY_PACKAGING_SNAPSHOT_DRIFT: case=$Case differences=$($differences -join ';')"
    }
}

function Write-BytesAtomic {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][byte[]]$Bytes)
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temporary = "$Path.xinao-packaging-$PID-$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllBytes($temporary,$Bytes)
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { [IO.File]::Delete($temporary) }
    }
}

function Restore-ExactFileState {
    param(
        [Parameter(Mandatory)]$State,
        [Parameter(Mandatory)][string]$ExactPath,
        [Parameter(Mandatory)][string]$Label
    )
    $target = Get-NormalizedPath $ExactPath
    if (-not (Test-PathEqual ([string]$State.path) $target)) {
        throw "PI_HIGH_CAPACITY_PACKAGING_EXACT_FILE_RESTORE_PATH_DRIFT: $Label"
    }
    if ([string]$State.kind -ceq 'absent') {
        if (Test-Path -LiteralPath $target) {
            $item = Get-Item -LiteralPath $target -Force
            if (-not ($item -is [IO.FileInfo]) -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "PI_HIGH_CAPACITY_PACKAGING_EXACT_FILE_RESTORE_TARGET_INVALID: $Label"
            }
            [IO.File]::Delete($target)
        }
    } elseif ([string]$State.kind -ceq 'file') {
        if ($null -eq $State.content) {
            throw "PI_HIGH_CAPACITY_PACKAGING_EXACT_FILE_RESTORE_CONTENT_MISSING: $Label"
        }
        Write-BytesAtomic -Path $target -Bytes $State.content
    } else {
        throw "PI_HIGH_CAPACITY_PACKAGING_EXACT_FILE_RESTORE_STATE_REJECTED: $Label=$($State.kind)"
    }
    $actual = Get-PathState -Path $target
    if ([string]$actual.kind -cne [string]$State.kind -or
        [long]$actual.bytes -ne [long]$State.bytes -or
        [string]$actual.sha256 -cne [string]$State.sha256) {
        throw "PI_HIGH_CAPACITY_PACKAGING_EXACT_FILE_RESTORE_MISMATCH: $Label"
    }
    [pscustomobject]@{
        path = $target
        restored = $true
        initial_kind = [string]$State.kind
        initial_bytes = [long]$State.bytes
        initial_sha256 = [string]$State.sha256
        final_kind = [string]$actual.kind
        final_bytes = [long]$actual.bytes
        final_sha256 = [string]$actual.sha256
    }
}

function Restore-LifecycleSnapshot {
    param([Parameter(Mandatory)][System.Collections.IDictionary]$Snapshot)
    foreach ($key in $Snapshot.Keys) {
        $state = $Snapshot[$key]
        $path = Get-NormalizedPath $state.path
        $allowed = $path.StartsWith($script:PackageRoot + '\',[StringComparison]::OrdinalIgnoreCase) -or
                   $path.StartsWith($script:CoreRoot + '\',[StringComparison]::OrdinalIgnoreCase)
        if (-not $allowed) { throw "PI_HIGH_CAPACITY_PACKAGING_RESTORE_PATH_REJECTED: $path" }
        if ($state.kind -ceq 'absent') {
            if (Test-Path -LiteralPath $path -PathType Leaf) { [IO.File]::Delete($path) }
        } elseif ($state.kind -ceq 'file') {
            if ($null -eq $state.content) { throw "PI_HIGH_CAPACITY_PACKAGING_RESTORE_CONTENT_MISSING: $key" }
            Write-BytesAtomic -Path $path -Bytes $state.content
        } else {
            throw "PI_HIGH_CAPACITY_PACKAGING_RESTORE_STATE_REJECTED: $key=$($state.kind)"
        }
    }
}

function Assert-Generation {
    param([Parameter(Mandatory)][ValidateSet('Pre','V41','Final')][string]$Generation,[Parameter(Mandatory)][string]$Case)
    foreach ($entry in $script:PackageGenerations.GetEnumerator()) {
        $actual = (Get-PathState -Path (Join-Path $script:PackageRoot $entry.Key)).sha256
        if ($actual -cne [string]$entry.Value[$Generation]) {
            throw "PI_HIGH_CAPACITY_PACKAGING_GENERATION_DRIFT: case=$Case generation=$Generation file=$($entry.Key) expected=$($entry.Value[$Generation]) actual=$actual"
        }
    }
    foreach ($entry in $script:CoreGenerations.GetEnumerator()) {
        $actual = (Get-PathState -Path (Join-Path $script:CoreRoot $entry.Key)).sha256
        if ($actual -cne [string]$entry.Value[$Generation]) {
            throw "PI_HIGH_CAPACITY_PACKAGING_GENERATION_DRIFT: case=$Case generation=$Generation file=$($entry.Key) expected=$($entry.Value[$Generation]) actual=$actual"
        }
    }
}

function Invoke-CompatibilityScript {
    param([Parameter(Mandatory)][string]$Path,[switch]$VerifyOnly,[int]$TimeoutMs=600000)
    $parameters = [ordered]@{ AgentDir=$script:CanonicalAgentDir; PiToolRoot=$script:CanonicalPiToolRoot }
    if ($VerifyOnly) { $parameters['VerifyOnly'] = $true }
    Invoke-HiddenPowerShellScript -ScriptPath $Path -Parameters $parameters -TimeoutMs $TimeoutMs
}

function Invoke-OldApplyScript {
    param([Parameter(Mandatory)][string]$Path,[switch]$VerifyOnly)
    $parameters = [ordered]@{ AgentDir=$script:CanonicalAgentDir }
    if ($VerifyOnly) { $parameters['VerifyOnly'] = $true }
    Invoke-HiddenPowerShellScript -ScriptPath $Path -Parameters $parameters
}

function Invoke-GitPatch {
    param([Parameter(Mandatory)][string]$Root,[Parameter(Mandatory)][string]$PatchPath,[switch]$Reverse)
    $arguments = @('-c','core.autocrlf=false','-C',$Root,'apply')
    if ($Reverse) { $arguments += '--reverse' }
    $check = Invoke-HiddenProcess -FilePath $script:GitPath -Arguments @($arguments + @('--check',$PatchPath))
    if ($check.exit_code -ne 0) { throw "PI_HIGH_CAPACITY_PACKAGING_PATCH_CHECK_FAILED: $PatchPath $($check.stderr)$($check.stdout)" }
    $apply = Invoke-HiddenProcess -FilePath $script:GitPath -Arguments @($arguments + @($PatchPath))
    if ($apply.exit_code -ne 0) { throw "PI_HIGH_CAPACITY_PACKAGING_PATCH_APPLY_FAILED: $PatchPath $($apply.stderr)$($apply.stdout)" }
}

function Get-PatchTargetPath {
    param([Parameter(Mandatory)][string]$PatchPath)
    @([IO.File]::ReadAllLines($PatchPath,[Text.Encoding]::UTF8) | Where-Object { $_.StartsWith('+++ b/') } | ForEach-Object {
        $_.Substring(6).Replace('/','\')
    })
}

function Assert-ExactPathSet {
    param(
        [Parameter(Mandatory)][string[]]$Expected,
        [Parameter(Mandatory)][string[]]$Actual,
        [Parameter(Mandatory)][string]$Label
    )
    $expectedSet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $actualSet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($path in $Expected) { if (-not $expectedSet.Add($path)) { throw "PI_HIGH_CAPACITY_PACKAGING_PATH_SET_DUPLICATE_EXPECTED: $Label/$path" } }
    foreach ($path in $Actual) { if (-not $actualSet.Add($path)) { throw "PI_HIGH_CAPACITY_PACKAGING_PATH_SET_DUPLICATE_ACTUAL: $Label/$path" } }
    $missing = @($expectedSet | Where-Object { -not $actualSet.Contains($_) })
    $extra = @($actualSet | Where-Object { -not $expectedSet.Contains($_) })
    if ($missing.Count -gt 0 -or $extra.Count -gt 0) {
        throw "PI_HIGH_CAPACITY_PACKAGING_PATCH_PATH_UNION_DRIFT: label=$Label missing=$($missing -join ',') extra=$($extra -join ',')"
    }
}

function Invoke-V41GenerationMaterialization {
    Assert-Generation -Generation Pre -Case 'materialize-v41-source'
    Invoke-GitPatch -Root $script:PackageRoot -PatchPath $script:BasePackagePatch
    Invoke-GitPatch -Root $script:CoreRoot -PatchPath $script:BaseCorePatch
    Assert-Generation -Generation V41 -Case 'materialize-v41-target'
}

function Write-JsonAtomic {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Json)
    $target = Get-NormalizedPath $Path
    $parent = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temporary = "$target.tmp-$PID-$([Guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllText($temporary,$Json,[Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $target -Force
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { [IO.File]::Delete($temporary) }
    }
}

$script:PackageGenerations = [ordered]@{
    'src\extension\fanout-child.ts' = @{ Pre='0209c6079fb86be1257e68a460eedbea8da577193a831fc0ecec3e3a6f7d8e51'; V41='b777190d50b43d4ca1366da8f64e53eb75846d660a149029cc2cc027607f632b'; Final='b777190d50b43d4ca1366da8f64e53eb75846d660a149029cc2cc027607f632b' }
    'src\extension\index.ts' = @{ Pre='5170c2f15a74bcfc4edbfc2b20eef8494c6fb3836553da43c698596e357b7009'; V41='2d3d3c61eb59186a2abdd59b235a834abe5ac7daca64c9a504bb902eb78ed5a9'; Final='2d3d3c61eb59186a2abdd59b235a834abe5ac7daca64c9a504bb902eb78ed5a9' }
    'src\extension\public-execution.ts' = @{ Pre='e89b13bb1257fd626dcb21f69b0ca2ceb5750047a40757304af9e0e5dd02cede'; V41='ec34983599cbc79143c103333ae86475beba9a33f36379d6ca6254c3589e4d1f'; Final='ec34983599cbc79143c103333ae86475beba9a33f36379d6ca6254c3589e4d1f' }
    'src\extension\rpc.ts' = @{ Pre='397d971cc7ec1ef1df846426c654d343a3fa91ab718eec24a8e78a12ad0fc0a7'; V41='637d4c70a99f229c11e743a6b2e41569b91217f36f002958bf3ad3ed2cae5599'; Final='637d4c70a99f229c11e743a6b2e41569b91217f36f002958bf3ad3ed2cae5599' }
    'src\extension\schemas.ts' = @{ Pre='ddd81da1c7d0063acadfe692378b640bf87418c699b3b471e5e74b7eac069bcc'; V41='d83e7ba5311dfc2d4b0316365ff934929abe6e1ce59ffeea5d4134c242b33302'; Final='d83e7ba5311dfc2d4b0316365ff934929abe6e1ce59ffeea5d4134c242b33302' }
    'src\extension\tool-description.ts' = @{ Pre='d2ceefa78c4f5a5cf57d91f8b368144ffe29ea14ef2cf650f866218040aabb89'; V41='3493ac9686b14f7322786467948c6efcc0c23340bfaee32f06c50db57e278d50'; Final='3493ac9686b14f7322786467948c6efcc0c23340bfaee32f06c50db57e278d50' }
    'src\runs\background\async-execution.ts' = @{ Pre='b8a272c050155439dc405da71d2cf5c21002744357b1c37e5f046c399cde10e7'; V41='ef0ba69b0c6d083b27e5f05336031556ad0a7a2646cfb018ec91a3100c8eadf4'; Final='64ecfc461aea05adf809dda9a296364e8e85098ffb7b9c0d71c9d4c5101fb921' }
    'src\runs\background\async-resume.ts' = @{ Pre='ae3a301b1dab8ec0b8348def3111eb5382a8006d042b0726c313e8d83ef806e3'; V41='a32eb20de710ec4b443b1027d8bff76afc8d6e853d4d4e72783501b839764661'; Final='6356456ead3ad359324a5664786da74dc0077de80448e35f209a797127482371' }
    'src\runs\background\retained-children.ts' = @{ Pre='39baebf55230c3812d04d6573296356e62f80cf9f8cb258f0f2b3b4c9c77580a'; V41='444fd33aaeb5117483330d9fc1535acecf4531927070cea3c5c550367b7023b1'; Final='444fd33aaeb5117483330d9fc1535acecf4531927070cea3c5c550367b7023b1' }
    'src\runs\background\subagent-runner.ts' = @{ Pre='599eb6faad6029272d26b41aa9ed8c6c0cd1b389230cd5fe46203a555312382d'; V41='ae581fd8367e8ae32c712afb3cc405b2fa9e6b686b6b14f81af54d870c550f86'; Final='ae581fd8367e8ae32c712afb3cc405b2fa9e6b686b6b14f81af54d870c550f86' }
    'src\runs\foreground\chain-execution.ts' = @{ Pre='c810388939735b169bba11c9cb8359803e063d408cd9d18feb1884ffebbdec41'; V41='aaf7271cd547c948ef1f4492f32ec85f7ab4a113fc19899c34396fe89ec7ef77'; Final='aaf7271cd547c948ef1f4492f32ec85f7ab4a113fc19899c34396fe89ec7ef77' }
    'src\runs\foreground\execution.ts' = @{ Pre='3d757df6cf57b0865668da1ba876c10d57903601c18d77a01a01d25c6054cdb4'; V41='3345076d827c8e63f973794a195fefab5e600e8c000583d4a98f72b52fb051ce'; Final='3345076d827c8e63f973794a195fefab5e600e8c000583d4a98f72b52fb051ce' }
    'src\runs\foreground\subagent-executor.ts' = @{ Pre='f6e1ed79bfc0373e77efb0754dcfcddf643942d406d1c8371d57a5c3203f4fed'; V41='411f4f275f164786f2388fb001d67954366d69fd5188a996b1a79d300dcd320e'; Final='411f4f275f164786f2388fb001d67954366d69fd5188a996b1a79d300dcd320e' }
    'src\runs\shared\parallel-utils.ts' = @{ Pre='55a328d8b8b6a2d5802bdee1d512e06678f33cdaf7e574ab0713ac0df20c8dbf'; V41='1d0b11ce0fab443cdbe9798007c5fc68f344757e617d8ced572f93fe4a047793'; Final='1d0b11ce0fab443cdbe9798007c5fc68f344757e617d8ced572f93fe4a047793' }
    'src\runs\shared\pi-args.ts' = @{ Pre='20714d7c3ac80716ddcdabff4d63cdd25144748b3c74602de93587fa5c8f6020'; V41='a177dfe33d9eab63960df1cc998ead47be5138342427845d1896f9066332847f'; Final='a177dfe33d9eab63960df1cc998ead47be5138342427845d1896f9066332847f' }
    'src\runs\shared\spawn-budget.ts' = @{ Pre='fbc12ffc3623444fd4f802a5dce3165924a2864c06a151c562d8de59e3a4a7f8'; V41='5f5d8a25f9c4df093065bc8a56d60e2a2d5719b4ff99ed6b498fde8e38422744'; Final='5f5d8a25f9c4df093065bc8a56d60e2a2d5719b4ff99ed6b498fde8e38422744' }
    'src\runs\shared\turn-budget.ts' = @{ Pre='a8500a05bc8836d61de03afb186b4d000920b4a79b620819aa6242daa6ba0a8d'; V41='1984da30964641c3dc3428848f087ac12a3bc7374513e23fbd872651e82de06a'; Final='1984da30964641c3dc3428848f087ac12a3bc7374513e23fbd872651e82de06a' }
    'src\runs\shared\xinao-pi-subagent-capacity-runtime.d.ts' = @{ Pre='absent'; V41='52a0df5fef19215f13fe7fb6828e4513a7e55c28f13baaa4c32d0f2d64180af3'; Final='52a0df5fef19215f13fe7fb6828e4513a7e55c28f13baaa4c32d0f2d64180af3' }
    'src\runs\shared\xinao-pi-subagent-capacity-runtime.js' = @{ Pre='absent'; V41='ba5614b01ee3b2c15194d1006596bef50134fdd4f86125713cf61987f7be76b2'; Final='ba5614b01ee3b2c15194d1006596bef50134fdd4f86125713cf61987f7be76b2' }
    'src\shared\types.ts' = @{ Pre='2e80765b425f6a8481cb559759b313ae679e2f67959a3c0f61214e1d529d6a33'; V41='acb00bd809ebaaf65bd67f300444ce314d6255739af5f140c8fed640ed8791ec'; Final='acb00bd809ebaaf65bd67f300444ce314d6255739af5f140c8fed640ed8791ec' }
    'src\workflows\scripted-workflow.ts' = @{ Pre='b67c105c52e33be616f316471601120751741f283a0ccea3f123fb9867ccf0e6'; V41='80d38d915e08f0173387c14249bed9688d1f9ec1d5c7f177e6d4cafba68b2eea'; Final='80d38d915e08f0173387c14249bed9688d1f9ec1d5c7f177e6d4cafba68b2eea' }
}
$script:CoreGenerations = [ordered]@{
    'dist\core\sdk.js' = @{ Pre='f6e72f33f44c708249c8d74931d816c36fe27175f7fa1639cba0a3d988592821'; V41='0248f6d4c080a92e8e076016b0e4d9b8533041c624445da6cd94bc8a3f83e7c5'; Final='0248f6d4c080a92e8e076016b0e4d9b8533041c624445da6cd94bc8a3f83e7c5' }
    'dist\core\xinao-pi-subagent-capacity-runtime.js' = @{ Pre='absent'; V41='ba5614b01ee3b2c15194d1006596bef50134fdd4f86125713cf61987f7be76b2'; Final='ba5614b01ee3b2c15194d1006596bef50134fdd4f86125713cf61987f7be76b2' }
}
$script:PackageAffectedFiles = @($script:PackageGenerations.Keys) + @(
    'package.json',
    'src\runs\shared\single-output.ts',
    'src\shared\post-exit-stdio-guard.ts',
    'src\runs\background\stale-run-reconciler.ts',
    'src\runs\shared\filesystem-policy.ts',
    'src\runs\shared\subagent-prompt-runtime.ts',
    'src\shared\launch-contract.ts'
)
$script:CoreAffectedFiles = @($script:CoreGenerations.Keys) + @('package.json')

$script:CanonicalAgentDir = Get-NormalizedPath $AgentDir
$script:CanonicalPiToolRoot = Get-NormalizedPath $PiToolRoot
$bodyLabParent = Get-NormalizedPath 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\body-labs\prime-s'
if (-not (Test-PathEqual (Split-Path -Parent $script:CanonicalAgentDir) $bodyLabParent)) {
    throw "PI_HIGH_CAPACITY_PACKAGING_BODY_LAB_REQUIRED: $($script:CanonicalAgentDir)"
}
if (-not (Test-PathEqual $script:CanonicalPiToolRoot (Join-Path $script:CanonicalAgentDir 'pi-tool-root'))) {
    throw "PI_HIGH_CAPACITY_PACKAGING_ROOT_PAIR_MISMATCH: $($script:CanonicalPiToolRoot)"
}
foreach ($root in @($script:CanonicalAgentDir,$script:CanonicalPiToolRoot)) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw "PI_HIGH_CAPACITY_PACKAGING_ROOT_MISSING: $root" }
    Assert-NoReparseAncestor $root
}
$script:PackageRoot = Join-Path $script:CanonicalAgentDir 'npm\node_modules\pi-subagents'
$script:CoreRoot = Join-Path $script:CanonicalPiToolRoot 'node_modules\@earendil-works\pi-coding-agent'
$scriptRootParent = Split-Path -Parent $PSScriptRoot
$patchRoot = Join-Path $scriptRootParent 'patches'
$script:BasePackagePatch = Join-Path $patchRoot 'pi-subagents-0.44.0-high-capacity-v1.patch'
$script:DeltaPackagePatch = Join-Path $patchRoot 'pi-subagents-0.44.0-high-capacity-v4.2-descriptor-resume.patch'
$script:BaseCorePatch = Join-Path $patchRoot 'pi-coding-agent-0.84.1-high-capacity-v1.patch'
$candidateManifestPath = Join-Path $patchRoot 'pi-s-high-capacity-v4.2-manifest.json'
$applyScript = Join-Path $PSScriptRoot 'Apply-PiSHighCapacityCompatibility.ps1'
$restoreScript = Join-Path $PSScriptRoot 'Restore-PiSHighCapacityCompatibility.ps1'
$replayScript = Join-Path $PSScriptRoot 'Test-PiSHighCapacityReplay.ps1'
$filesystemResumeScript = Join-Path $PSScriptRoot 'Test-PiSHighCapacityFilesystemResume.ps1'
$oldApplyScripts = [ordered]@{
    windows = Join-Path $PSScriptRoot 'Apply-PiSSubagentsWindowsCompatibility.ps1'
    owner_stop = Join-Path $PSScriptRoot 'Apply-PiSSubagentsSessionStopCompatibility.ps1'
    filesystem_policy = Join-Path $PSScriptRoot 'Apply-PiSSubagentsFilesystemPolicy.ps1'
}
$filesystemApplySha = (Get-FileHash -LiteralPath $oldApplyScripts.filesystem_policy -Algorithm SHA256).Hash.ToLowerInvariant()
if ($filesystemApplySha -cne '05d05cc6739bc891c9cb0bbfed52b9af508e2b980c36ab705115a4cd96957aae') {
    throw "PI_HIGH_CAPACITY_PACKAGING_FILESYSTEM_APPLY_DRIFT: $filesystemApplySha"
}
$script:PowerShellPath = (Get-Command pwsh.exe,powershell.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
$script:GitPath = (Get-Command git.exe,git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
if ([string]::IsNullOrWhiteSpace($script:PowerShellPath)) { throw 'PI_HIGH_CAPACITY_PACKAGING_POWERSHELL_MISSING' }
foreach ($required in @($applyScript,$restoreScript,$replayScript,$filesystemResumeScript,$candidateManifestPath,$script:BasePackagePatch,$script:DeltaPackagePatch,$script:BaseCorePatch) + @($oldApplyScripts.Values)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "PI_HIGH_CAPACITY_PACKAGING_SOURCE_MISSING: $required" }
}
$replayScriptSha = (Get-FileHash -LiteralPath $replayScript -Algorithm SHA256).Hash.ToLowerInvariant()
if ($replayScriptSha -cne '5ccc0ce63ab132c0a8f34e3f976d1d982d48e6f559d7023fe086376f92b2096f') {
    throw "PI_HIGH_CAPACITY_PACKAGING_REPLAY_SCRIPT_DRIFT: $replayScriptSha"
}
$filesystemResumeScriptSha = (Get-FileHash -LiteralPath $filesystemResumeScript -Algorithm SHA256).Hash.ToLowerInvariant()
if ($filesystemResumeScriptSha -cne 'cc95bdf0a8e59cb0af20211ac1b2cfdfa8e71b17d4c753c7315724c3a6dd320d') {
    throw "PI_HIGH_CAPACITY_PACKAGING_FILESYSTEM_RESUME_SCRIPT_DRIFT: $filesystemResumeScriptSha"
}
$candidateManifestSha = (Get-FileHash -LiteralPath $candidateManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($candidateManifestSha -cne '8f88fa47dffb4ff591a4b89a367fde0dce96b3d19d3c397200dbc79869b63468') {
    throw "PI_HIGH_CAPACITY_PACKAGING_CANDIDATE_MANIFEST_DRIFT: $candidateManifestSha"
}
$candidateManifest = Get-Content -Raw -LiteralPath $candidateManifestPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$candidateManifest.schema -cne 'xinao.pi.subagent.capacity.candidate-manifest.v4.2' -or
    [string]$candidateManifest.generation -cne 'V4.2' -or
    @($candidateManifest.files).Count -ne 23 -or
    @($candidateManifest.patches).Count -ne 3) {
    throw 'PI_HIGH_CAPACITY_PACKAGING_CANDIDATE_MANIFEST_CONTRACT_DRIFT'
}
$replaySource = Get-Content -Raw -LiteralPath $replayScript -Encoding UTF8
if (-not $replaySource.Contains('Test-PiSHighCapacityFilesystemResume.ps1') -or
    -not $replaySource.Contains('xinao.pi_s_high_capacity_filesystem_resume_acceptance.v1') -or
    -not $replaySource.Contains($candidateManifestSha)) {
    throw 'PI_HIGH_CAPACITY_PACKAGING_REPLAY_FILESYSTEM_OR_MANIFEST_BINDING_MISSING'
}
$patchIdentities = [ordered]@{
    base_package = @{ path=$script:BasePackagePatch; expected='a31617bd6df9004f0581935de5ef68897b2382f3c7656b1d6977c7a61cc645d4' }
    delta_package = @{ path=$script:DeltaPackagePatch; expected='8c872c65657476a2db3c0dbc9145e9630e4e7715f7a476431fef07f51f98f75b' }
    base_core = @{ path=$script:BaseCorePatch; expected='13a89eda2b22e9337c90aa817e75e766499ee62f1fa044142a9cceef91d9d3ad' }
}
foreach ($entry in $patchIdentities.GetEnumerator()) {
    $entry.Value['actual'] = (Get-FileHash -LiteralPath $entry.Value.path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($entry.Value['actual'] -cne $entry.Value['expected']) { throw "PI_HIGH_CAPACITY_PACKAGING_PATCH_IDENTITY_DRIFT: $($entry.Key)" }
}
$basePackageTargets = @(Get-PatchTargetPath $script:BasePackagePatch)
$deltaPackageTargets = @(Get-PatchTargetPath $script:DeltaPackagePatch)
$baseCoreTargets = @(Get-PatchTargetPath $script:BaseCorePatch)
Assert-ExactPathSet -Expected @($script:PackageGenerations.Keys) -Actual $basePackageTargets -Label 'base-package'
Assert-ExactPathSet -Expected @('src\runs\background\async-execution.ts','src\runs\background\async-resume.ts') -Actual $deltaPackageTargets -Label 'delta-package'
Assert-ExactPathSet -Expected @($script:CoreGenerations.Keys) -Actual $baseCoreTargets -Label 'base-core'
$orderedPackagePaths = @($script:PackageGenerations.Keys)
$asyncExecutionIndex = [Array]::IndexOf($orderedPackagePaths,'src\runs\background\async-execution.ts')
$asyncResumeIndex = [Array]::IndexOf($orderedPackagePaths,'src\runs\background\async-resume.ts')
if ($asyncExecutionIndex -lt 0 -or $asyncResumeIndex -ne ($asyncExecutionIndex + 1)) {
    throw "PI_HIGH_CAPACITY_PACKAGING_DELTA_COMMIT_ORDER_DRIFT: execution=$asyncExecutionIndex resume=$asyncResumeIndex"
}
$patchIdentities['base_package']['targets'] = $basePackageTargets
$patchIdentities['delta_package']['targets'] = $deltaPackageTargets
$patchIdentities['base_core']['targets'] = $baseCoreTargets
$patchIdentities['delta_package']['commit_order'] = @('async-execution','async-resume')

$tempBase = Get-NormalizedPath 'D:\XINAO_RESEARCH_RUNTIME\temp\pi-high-capacity-packaging'
$tempRoot = Join-Path $tempBase ([Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
Assert-NoReparseAncestor $tempRoot
$originalSnapshot = $null
$junctionPath = $null
$junctionBackup = $null
$junctionOriginalPath = $null
$exclusiveLock = $null
$cleanupExact = $false
$cleanupTemp = $false
$packageTreeInitial = $null
$coreTreeInitial = $null
$capacityConfigPath = Join-Path $script:CanonicalAgentDir 'extensions\subagent\config.json'
$capacityConfigInitial = $null
$capacityConfigRestored = $true
$receipt = [ordered]@{
    schema='xinao.pi_s_high_capacity_packaging_acceptance.v2'
    status='running'
    started_at=[DateTimeOffset]::Now.ToString('o')
    agent_dir=$script:CanonicalAgentDir
    pi_tool_root=$script:CanonicalPiToolRoot
    patches=$patchIdentities
    candidate_manifest=[ordered]@{ path=$candidateManifestPath; bytes=(Get-Item -LiteralPath $candidateManifestPath).Length; sha256=$candidateManifestSha; generation='V4.2'; files=23 }
    replay_source=[ordered]@{ path=$replayScript; bytes=(Get-Item -LiteralPath $replayScript).Length; sha256=$replayScriptSha; filesystem_resume_path=$filesystemResumeScript; filesystem_resume_bytes=(Get-Item -LiteralPath $filesystemResumeScript).Length; filesystem_resume_sha256=$filesystemResumeScriptSha }
    compatibility_inputs=[ordered]@{ filesystem_apply_path=$oldApplyScripts.filesystem_policy; filesystem_apply_bytes=(Get-Item -LiteralPath $oldApplyScripts.filesystem_policy).Length; filesystem_apply_sha256=$filesystemApplySha; accepted_capacity_generations=@('V4.1','V4.2') }
    cases=[ordered]@{}
    nested_replay=$null
    capacity_config_projection=$null
    cleanup=[ordered]@{ exact_underlay=$false; temp=$false }
    error=$null
}

try {
    Assert-Generation -Generation Pre -Case 'initial-underlay'
    $originalSnapshot = Get-LifecycleSnapshot -TargetAgentDir $script:CanonicalAgentDir -TargetPiToolRoot $script:CanonicalPiToolRoot -IncludeContent
    $receipt.initial_underlay_digest = Get-SnapshotDigest $originalSnapshot
    $packageTreeInitial = Get-TreeFingerprint (Join-Path $script:PackageRoot 'src')
    $coreTreeInitial = Get-TreeFingerprint (Join-Path $script:CoreRoot 'dist\core')
    $receipt.initial_tree = [ordered]@{ package_src=$packageTreeInitial; core_dist_core=$coreTreeInitial }
    $capacityConfigInitial = Get-PathState -Path $capacityConfigPath -IncludeContent
    if ([string]$capacityConfigInitial.kind -notin @('file','absent')) {
        throw "PI_HIGH_CAPACITY_PACKAGING_CAPACITY_CONFIG_PREIMAGE_INVALID: $($capacityConfigInitial.kind)"
    }
    $capacityConfigRestored = $false

    $first = ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $applyScript) 'underlay-to-v42-apply'
    Assert-HighCapacityCandidateManifestReceipt -Receipt $first -Case 'underlay-to-v42-apply' -ExpectedSha256 $candidateManifestSha -ExpectedBytes (Get-Item -LiteralPath $candidateManifestPath).Length
    if (-not [bool]$first.changed -or [string]$first.transition -cne 'Pre->Final' -or -not [bool]$first.sqlite_probe.ok) { throw 'PI_HIGH_CAPACITY_PACKAGING_FIRST_APPLY_RECEIPT_INVALID' }
    Assert-Generation Final 'underlay-to-v42-apply'
    $finalSnapshot = Get-LifecycleSnapshot -TargetAgentDir $script:CanonicalAgentDir -TargetPiToolRoot $script:CanonicalPiToolRoot -IncludeContent
    $receipt.cases['underlay_to_v42_apply'] = [ordered]@{ status='pass'; transition=$first.transition; changed=$first.changed; sqlite=$first.sqlite_probe.ok; digest=Get-SnapshotDigest $finalSnapshot }

    $verify = ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $applyScript -VerifyOnly) 'v42-verify'
    $second = ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $applyScript) 'v42-second-apply'
    Assert-HighCapacityCandidateManifestReceipt -Receipt $verify -Case 'v42-verify' -ExpectedSha256 $candidateManifestSha -ExpectedBytes (Get-Item -LiteralPath $candidateManifestPath).Length
    Assert-HighCapacityCandidateManifestReceipt -Receipt $second -Case 'v42-second-apply' -ExpectedSha256 $candidateManifestSha -ExpectedBytes (Get-Item -LiteralPath $candidateManifestPath).Length
    if ([bool]$verify.changed -or -not [bool]$verify.verify_only -or [bool]$second.changed -or [string]$second.transition -cne 'no-op') { throw 'PI_HIGH_CAPACITY_PACKAGING_V42_IDEMPOTENCE_INVALID' }
    Assert-SnapshotEqual $finalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'v42-idempotence'
    $receipt.cases['v42_verify_second'] = [ordered]@{ status='pass'; verify_changed=$verify.changed; second_changed=$second.changed }

    foreach ($entry in $oldApplyScripts.GetEnumerator()) {
        $plain = ConvertFrom-ChildJson (Invoke-OldApplyScript -Path $entry.Value) "old-$($entry.Key)-plain"
        $oldVerify = ConvertFrom-ChildJson (Invoke-OldApplyScript -Path $entry.Value -VerifyOnly) "old-$($entry.Key)-verify"
        if ([bool]$plain.changed -or [bool]$oldVerify.changed -or -not [bool]$plain.high_capacity_combination_accepted) {
            throw "PI_HIGH_CAPACITY_PACKAGING_OLD_APPLY_COMPOSED_INVALID: $($entry.Key)"
        }
        if ($entry.Key -ceq 'filesystem_policy' -and
            ([string]$plain.high_capacity_generation_accepted -cne 'V4.2' -or [string]$oldVerify.high_capacity_generation_accepted -cne 'V4.2')) {
            throw 'PI_HIGH_CAPACITY_PACKAGING_FILESYSTEM_APPLY_V42_GENERATION_INVALID'
        }
        Assert-SnapshotEqual $finalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) "old-$($entry.Key)-no-mutation"
        $receipt.cases["old_$($entry.Key)_composed"] = [ordered]@{ status='pass'; plain_changed=$plain.changed; verify_changed=$oldVerify.changed }
    }

    $nestedReplayReceiptPath = Join-Path $tempRoot 'nested-high-capacity-replay.json'
    $replay = $null
    $nestedReplay = $null
    $nestedReplayBytes = 0
    $nestedReplaySha = $null
    $receipt.capacity_config_projection = [ordered]@{
        path = $capacityConfigPath
        initial_kind = [string]$capacityConfigInitial.kind
        initial_bytes = [long]$capacityConfigInitial.bytes
        initial_sha256 = [string]$capacityConfigInitial.sha256
        temporary_sha256 = $null
        max_subagent_depth = $null
        max_subagent_spawns_per_session = $null
        global_concurrency_limit = $null
        parallel_max_tasks = $null
        parallel_concurrency = $null
        turn_max = $null
        turn_grace = $null
        default_session_dir = $null
        restored_exactly = $false
        final_sha256 = $null
    }
    try {
        $capacityDefaultSessionDir = Join-Path $script:CanonicalAgentDir 'sessions\children'
        $temporaryCapacityConfig = New-PiSubagentCapacityConfig -Profile 'prime-s' -DefaultSessionDir $capacityDefaultSessionDir
        Write-PiDualEntryJsonAtomic -Path $capacityConfigPath -Value $temporaryCapacityConfig
        $capacityProjection = Assert-PiSubagentCapacityProjection -Profile 'prime-s' -AgentDir $script:CanonicalAgentDir
        $temporaryCapacityConfigReadback = Get-Content -Raw -LiteralPath $capacityConfigPath -Encoding UTF8 | ConvertFrom-Json
        if (-not (Test-PathEqual ([string]$temporaryCapacityConfigReadback.defaultSessionDir) $capacityDefaultSessionDir)) {
            throw 'PI_HIGH_CAPACITY_PACKAGING_TEMPORARY_CAPACITY_DEFAULT_SESSION_DIR_DRIFT'
        }
        $receipt.capacity_config_projection.temporary_sha256 = [string]$capacityProjection.config_sha256
        $receipt.capacity_config_projection.max_subagent_depth = [int]$capacityProjection.max_subagent_depth
        $receipt.capacity_config_projection.max_subagent_spawns_per_session = [int]$capacityProjection.max_subagent_spawns_per_session
        $receipt.capacity_config_projection.global_concurrency_limit = [int]$capacityProjection.global_concurrency_limit
        $receipt.capacity_config_projection.parallel_max_tasks = [int]$capacityProjection.parallel_max_tasks
        $receipt.capacity_config_projection.parallel_concurrency = [int]$capacityProjection.parallel_concurrency
        $receipt.capacity_config_projection.turn_max = [int]$capacityProjection.turn_max
        $receipt.capacity_config_projection.turn_grace = [int]$capacityProjection.turn_grace
        $receipt.capacity_config_projection.default_session_dir = [string]$temporaryCapacityConfigReadback.defaultSessionDir

        $replayParameters = [ordered]@{ AgentDir=$script:CanonicalAgentDir; PiToolRoot=$script:CanonicalPiToolRoot; ReceiptPath=$nestedReplayReceiptPath }
        if (-not [string]::IsNullOrWhiteSpace($TypeScriptCompilerPath)) { $replayParameters['TypeScriptCompilerPath'] = $TypeScriptCompilerPath }
        $replay = ConvertFrom-ChildJson (Invoke-HiddenPowerShellScript -ScriptPath $replayScript -Parameters $replayParameters -TimeoutMs 900000) 'nested-replay'
        if (-not (Test-Path -LiteralPath $nestedReplayReceiptPath -PathType Leaf)) { throw 'PI_HIGH_CAPACITY_PACKAGING_NESTED_REPLAY_RECEIPT_MISSING' }
        $nestedReplayBytes = (Get-Item -LiteralPath $nestedReplayReceiptPath).Length
        $nestedReplaySha = (Get-FileHash -LiteralPath $nestedReplayReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $nestedReplay = Get-Content -Raw -LiteralPath $nestedReplayReceiptPath -Encoding UTF8 | ConvertFrom-Json
        if ((Get-FileHash -LiteralPath $replayScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne $replayScriptSha -or
            (Get-FileHash -LiteralPath $filesystemResumeScript -Algorithm SHA256).Hash.ToLowerInvariant() -cne $filesystemResumeScriptSha) {
            throw 'PI_HIGH_CAPACITY_PACKAGING_REPLAY_SOURCE_CHANGED_DURING_RUN'
        }
    } finally {
        $capacityConfigRestore = Restore-ExactFileState -State $capacityConfigInitial -ExactPath $capacityConfigPath -Label 'nested-replay-capacity-config'
        $capacityConfigRestored = [bool]$capacityConfigRestore.restored
        $receipt.capacity_config_projection.restored_exactly = [bool]$capacityConfigRestore.restored
        $receipt.capacity_config_projection.final_sha256 = [string]$capacityConfigRestore.final_sha256
    }
    $filesystemCrossProductProperty = $nestedReplay.PSObject.Properties['filesystem_resume_cross_product']
    $filesystemCrossProduct = if ($null -eq $filesystemCrossProductProperty) { $null } else { $filesystemCrossProductProperty.Value }
    $receipt['nested_replay_observed'] = [ordered]@{
        receipt_properties = @($nestedReplay.PSObject.Properties.Name)
        status = [string]$nestedReplay.status
        error = [string]$nestedReplay.error
        filesystem_cross_product_present = ($null -ne $filesystemCrossProduct)
        filesystem_cross_product_properties = $(if ($null -eq $filesystemCrossProduct) { @() } else { @($filesystemCrossProduct.PSObject.Properties.Name) })
    }
    $nestedReplayChecks = [ordered]@{
        child_output_status = ([string]$replay.status -ceq 'verified')
        receipt_status = ([string]$nestedReplay.status -ceq 'verified')
        strict_typescript = ([string]$nestedReplay.strict_typescript.status -ceq 'pass')
        tests_failed_zero = ([int]$nestedReplay.tests.failed -eq 0)
        tests_observed_48 = ([int]$nestedReplay.tests.observed -eq 48)
        manifest_sha256 = ([string]$nestedReplay.candidate_manifest.sha256 -ceq $candidateManifestSha)
        manifest_package_files = ([int]$nestedReplay.candidate_manifest.package_files -eq 21)
        manifest_core_files = ([int]$nestedReplay.candidate_manifest.core_files -eq 2)
        filesystem_present = ($null -ne $filesystemCrossProduct)
        filesystem_schema = ($null -ne $filesystemCrossProduct -and [string]$filesystemCrossProduct.schema -ceq 'xinao.pi_s_high_capacity_filesystem_resume_acceptance.v1')
        filesystem_status = ($null -ne $filesystemCrossProduct -and [string]$filesystemCrossProduct.status -ceq 'verified')
        filesystem_receipt_sha256 = ($null -ne $filesystemCrossProduct -and [string]$filesystemCrossProduct.receipt_sha256 -match '^[a-f0-9]{64}$')
        filesystem_resume_provider = ($null -ne $filesystemCrossProduct -and [bool]$filesystemCrossProduct.resume_reached_provider)
        filesystem_no_policy_resume_provider = ($null -ne $filesystemCrossProduct -and [bool]$filesystemCrossProduct.no_policy_resume_reached_provider)
        filesystem_mutable_files_restored = ($null -ne $filesystemCrossProduct -and [bool]$filesystemCrossProduct.candidate_mutable_files_restored)
        filesystem_child_sessions_restored = ($null -ne $filesystemCrossProduct -and [bool]$filesystemCrossProduct.candidate_child_sessions_restored)
        filesystem_work_root_removed = ($null -ne $filesystemCrossProduct -and [bool]$filesystemCrossProduct.work_root_cleanup.removed)
        filesystem_hostile_root_removed = ($null -ne $filesystemCrossProduct -and [bool]$filesystemCrossProduct.hostile_root_cleanup.removed)
        capacity_config_restored = [bool]$receipt.capacity_config_projection.restored_exactly
        replay_temp_cleanup = [bool]$nestedReplay.temp_cleanup
    }
    $failedNestedReplayChecks = @($nestedReplayChecks.Keys | Where-Object { -not [bool]$nestedReplayChecks[$_] })
    if ($failedNestedReplayChecks.Count -ne 0) {
        throw "PI_HIGH_CAPACITY_PACKAGING_NESTED_REPLAY_INVALID: $($failedNestedReplayChecks -join ','); nested_error=$([string]$nestedReplay.error)"
    }
    $receipt.nested_replay = [ordered]@{
        status=$nestedReplay.status
        receipt_path=$nestedReplayReceiptPath
        receipt_bytes=$nestedReplayBytes
        receipt_sha256=$nestedReplaySha
        observed=$nestedReplay.tests.observed
        passed=$nestedReplay.tests.passed
        failed=$nestedReplay.tests.failed
        strict=$nestedReplay.strict_typescript.status
        candidate_manifest_sha256=$nestedReplay.candidate_manifest.sha256
        filesystem_resume_receipt_sha256=$filesystemCrossProduct.receipt_sha256
        filesystem_resume_provider=$filesystemCrossProduct.resume_reached_provider
        filesystem_no_policy_resume_provider=$filesystemCrossProduct.no_policy_resume_reached_provider
        filesystem_work_root_removed=$filesystemCrossProduct.work_root_cleanup.removed
        filesystem_hostile_root_removed=$filesystemCrossProduct.hostile_root_cleanup.removed
    }

    $restore = ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $restoreScript) 'v42-to-underlay-restore'
    Assert-HighCapacityCandidateManifestReceipt -Receipt $restore -Case 'v42-to-underlay-restore' -ExpectedSha256 $candidateManifestSha -ExpectedBytes (Get-Item -LiteralPath $candidateManifestPath).Length
    if (-not [bool]$restore.changed -or [string]$restore.transition -cne 'Final->Pre') { throw 'PI_HIGH_CAPACITY_PACKAGING_V42_RESTORE_INVALID' }
    Assert-SnapshotEqual $originalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'v42-restore-underlay'
    $restoreVerify = ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $restoreScript -VerifyOnly) 'underlay-restore-verify'
    $restoreSecond = ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $restoreScript) 'underlay-restore-second'
    if ([bool]$restoreVerify.changed -or [bool]$restoreSecond.changed) { throw 'PI_HIGH_CAPACITY_PACKAGING_RESTORE_IDEMPOTENCE_INVALID' }
    $receipt.cases['v42_restore_verify_second'] = [ordered]@{ status='pass'; transition=$restore.transition; verify_changed=$restoreVerify.changed; second_changed=$restoreSecond.changed }

    Invoke-V41GenerationMaterialization
    $v41Snapshot = Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot -IncludeContent
    $v41FilesystemPlain = ConvertFrom-ChildJson (Invoke-OldApplyScript -Path $oldApplyScripts.filesystem_policy) 'v41-filesystem-plain'
    $v41FilesystemVerify = ConvertFrom-ChildJson (Invoke-OldApplyScript -Path $oldApplyScripts.filesystem_policy -VerifyOnly) 'v41-filesystem-verify'
    if ([bool]$v41FilesystemPlain.changed -or [bool]$v41FilesystemVerify.changed -or
        -not [bool]$v41FilesystemPlain.high_capacity_combination_accepted -or
        [string]$v41FilesystemPlain.high_capacity_generation_accepted -cne 'V4.1' -or
        [string]$v41FilesystemVerify.high_capacity_generation_accepted -cne 'V4.1') {
        throw 'PI_HIGH_CAPACITY_PACKAGING_FILESYSTEM_APPLY_V41_GENERATION_INVALID'
    }
    Assert-SnapshotEqual $v41Snapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'v41-filesystem-no-mutation'
    $receipt.cases['filesystem_apply_v41_composed'] = [ordered]@{ status='pass'; plain_changed=$v41FilesystemPlain.changed; verify_changed=$v41FilesystemVerify.changed; generation=$v41FilesystemPlain.high_capacity_generation_accepted }
    $fromV41 = ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $applyScript) 'v41-to-v42-apply'
    Assert-HighCapacityCandidateManifestReceipt -Receipt $fromV41 -Case 'v41-to-v42-apply' -ExpectedSha256 $candidateManifestSha -ExpectedBytes (Get-Item -LiteralPath $candidateManifestPath).Length
    if (-not [bool]$fromV41.changed -or [string]$fromV41.transition -cne 'V41->Final') { throw 'PI_HIGH_CAPACITY_PACKAGING_V41_APPLY_INVALID' }
    Assert-Generation Final 'v41-to-v42'
    $fromV41Verify = ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $applyScript -VerifyOnly) 'v41-v42-verify'
    $fromV41Second = ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $applyScript) 'v41-v42-second'
    if ([bool]$fromV41Verify.changed -or [bool]$fromV41Second.changed) { throw 'PI_HIGH_CAPACITY_PACKAGING_V41_V42_IDEMPOTENCE_INVALID' }
    $receipt.cases['v41_to_v42_apply_verify_second'] = [ordered]@{ status='pass'; transition=$fromV41.transition; verify_changed=$fromV41Verify.changed; second_changed=$fromV41Second.changed }
    [void](ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $restoreScript) 'v42-underlay-after-v41-route')
    Assert-SnapshotEqual $originalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'v42-underlay-after-v41-route'

    Invoke-V41GenerationMaterialization
    $v41Restore = ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $restoreScript) 'v41-to-underlay-restore'
    Assert-HighCapacityCandidateManifestReceipt -Receipt $v41Restore -Case 'v41-to-underlay-restore' -ExpectedSha256 $candidateManifestSha -ExpectedBytes (Get-Item -LiteralPath $candidateManifestPath).Length
    if (-not [bool]$v41Restore.changed -or [string]$v41Restore.transition -cne 'V41->Pre') { throw 'PI_HIGH_CAPACITY_PACKAGING_V41_RESTORE_INVALID' }
    Assert-SnapshotEqual $originalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'v41-to-underlay-restore'
    $receipt.cases['v41_to_underlay_restore'] = [ordered]@{ status='pass'; transition=$v41Restore.transition; changed=$v41Restore.changed }

    Invoke-V41GenerationMaterialization
    $v42Execution = $finalSnapshot['package::src\runs\background\async-execution.ts']
    Write-BytesAtomic -Path (Join-Path $script:PackageRoot 'src\runs\background\async-execution.ts') -Bytes $v42Execution.content
    $mixedSnapshot = Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot
    $mixedFailure = Invoke-CompatibilityScript -Path $applyScript
    $receipt.cases['v41_v42_two_file_mixed'] = Assert-ExpectedFailure $mixedFailure 'v41-v42-two-file-mixed' 'PI_S_HIGH_CAPACITY_SOURCE_CONFLICT'
    Assert-SnapshotEqual $mixedSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'mixed-zero-additional-mutation'
    Restore-LifecycleSnapshot $v41Snapshot
    Assert-Generation V41 'mixed-restored-v41'
    [void](ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $restoreScript) 'mixed-v41-to-underlay')
    Assert-SnapshotEqual $originalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'mixed-case-underlay'

    Invoke-V41GenerationMaterialization
    # Permit staging reads but deny write/delete sharing so failure occurs after
    # async-execution has committed and the transactional rollback is exercised.
    $exclusiveLock = [IO.File]::Open((Join-Path $script:PackageRoot 'src\runs\background\async-resume.ts'),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try { $deltaLockFailure = Invoke-CompatibilityScript -Path $applyScript }
    finally { $exclusiveLock.Dispose(); $exclusiveLock=$null }
    $receipt.cases['v41_delta_midcommit_rollback'] = Assert-ExpectedFailure $deltaLockFailure 'v41-delta-midcommit' 'PI_S_HIGH_CAPACITY_COMMIT_ROLLED_BACK'
    Assert-SnapshotEqual $v41Snapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'v41-delta-rollback-exact'
    [void](ConvertFrom-ChildJson (Invoke-CompatibilityScript -Path $restoreScript) 'v41-delta-rollback-restore')
    Assert-SnapshotEqual $originalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'v41-delta-rollback-underlay'

    # Same read-share-only fault at the package/core boundary: stage succeeds,
    # package commits, core replacement fails, and all package writes roll back.
    $exclusiveLock = [IO.File]::Open((Join-Path $script:CoreRoot 'dist\core\sdk.js'),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try { $coreLockFailure = Invoke-CompatibilityScript -Path $applyScript }
    finally { $exclusiveLock.Dispose(); $exclusiveLock=$null }
    $receipt.cases['underlay_core_midcommit_rollback'] = Assert-ExpectedFailure $coreLockFailure 'underlay-core-midcommit' 'PI_S_HIGH_CAPACITY_COMMIT_ROLLED_BACK'
    Assert-SnapshotEqual $originalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'underlay-core-rollback-exact'

    $junctionPath = Join-Path $script:PackageRoot 'src\extension'
    $junctionOriginalPath = $junctionPath
    $junctionBackup = Join-Path $script:PackageRoot ('src\extension.xinao-packaging-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::Move($junctionPath,$junctionBackup)
    New-Item -ItemType Junction -Path $junctionPath -Target $junctionBackup | Out-Null
    $junctionSnapshot = Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot
    $junctionReceipts = @()
    $junctionFailure = Invoke-CompatibilityScript -Path $applyScript
    $junctionReceipts += Assert-ExpectedFailure $junctionFailure 'inner-package-junction-high-capacity' 'PI_S_HIGH_CAPACITY_REPARSE_POINT_REJECTED'
    foreach ($entry in @($oldApplyScripts.GetEnumerator() | Where-Object { $_.Key -in @('owner_stop','filesystem_policy') })) {
        $oldJunctionFailure = Invoke-OldApplyScript -Path $entry.Value
        $junctionReceipts += Assert-ExpectedFailure $oldJunctionFailure "inner-package-junction-$($entry.Key)" 'REPARSE_POINT_REJECTED'
    }
    Assert-SnapshotEqual $junctionSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'junction-zero-mutation'
    [IO.Directory]::Delete($junctionPath,$false)
    $junctionPath=$null
    [IO.Directory]::Move($junctionBackup,(Join-Path $script:PackageRoot 'src\extension'))
    $junctionBackup=$null
    $junctionOriginalPath=$null

    $junctionPath = Join-Path $script:PackageRoot 'src\runs\foreground'
    $junctionOriginalPath = $junctionPath
    $junctionBackup = Join-Path $script:PackageRoot ('src\runs\foreground.xinao-packaging-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::Move($junctionPath,$junctionBackup)
    New-Item -ItemType Junction -Path $junctionPath -Target $junctionBackup | Out-Null
    $windowsJunctionSnapshot = Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot
    $windowsJunctionFailure = Invoke-OldApplyScript -Path $oldApplyScripts.windows
    $junctionReceipts += Assert-ExpectedFailure $windowsJunctionFailure 'inner-package-junction-windows' 'REPARSE_POINT_REJECTED'
    Assert-SnapshotEqual $windowsJunctionSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'windows-junction-zero-mutation'
    [IO.Directory]::Delete($junctionPath,$false)
    $junctionPath=$null
    [IO.Directory]::Move($junctionBackup,(Join-Path $script:PackageRoot 'src\runs\foreground'))
    $junctionBackup=$null
    $junctionOriginalPath=$null
    $receipt.cases['inner_package_junction_rejected'] = [ordered]@{
        status='pass'
        layers=4
        extension_target_layers=@('high_capacity','owner_stop','filesystem_policy')
        foreground_target_layers=@('windows')
        receipts=$junctionReceipts
    }
    Assert-SnapshotEqual $originalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'junctions-restored-underlay'

    $primeB = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-b'
    # Use a real core root so the test would expose a weakened PrimeB target
    # guard instead of being saved by a later missing-core failure.
    $primeBTool = $script:CanonicalPiToolRoot
    $primeBefore = Get-LifecycleSnapshot $primeB $primeBTool
    $mainBeforePrimeGuard = Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot
    $primeFailure = Invoke-HiddenPowerShellScript -ScriptPath $applyScript -Parameters ([ordered]@{AgentDir=$primeB;PiToolRoot=$primeBTool})
    $receipt.cases['prime_b_guard'] = Assert-ExpectedFailure $primeFailure 'prime-b-guard' 'PI_S_HIGH_CAPACITY_TARGET_OUTSIDE_MAIN_PROFILE'
    Assert-SnapshotEqual $primeBefore (Get-LifecycleSnapshot $primeB $primeBTool) 'prime-b-zero-mutation'
    Assert-SnapshotEqual $mainBeforePrimeGuard (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'prime-b-main-lab-zero-mutation'

    Assert-SnapshotEqual $originalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'final-underlay'
    $receipt.status='verified'
} catch {
    $receipt.status='blocked'
    $receipt.error=[string]$_.Exception.Message
} finally {
    $finallyErrors = New-Object Collections.Generic.List[string]
    if ($null -ne $exclusiveLock) {
        try { $exclusiveLock.Dispose() } catch { $finallyErrors.Add("lock-dispose:$($_.Exception.Message)") }
        $exclusiveLock=$null
    }
    if ($null -ne $junctionPath -and (Test-Path -LiteralPath $junctionPath)) {
        try { [IO.Directory]::Delete($junctionPath,$false) } catch { $finallyErrors.Add("junction-delete:$($_.Exception.Message)") }
    }
    if ($null -ne $junctionBackup -and (Test-Path -LiteralPath $junctionBackup -PathType Container)) {
        if ([string]::IsNullOrWhiteSpace([string]$junctionOriginalPath)) {
            $finallyErrors.Add('junction-restore:original-path-missing')
        } elseif (-not (Test-Path -LiteralPath $junctionOriginalPath)) {
            try { [IO.Directory]::Move($junctionBackup,$junctionOriginalPath) } catch { $finallyErrors.Add("junction-restore:$($_.Exception.Message)") }
        }
    }
    if ($null -ne $capacityConfigInitial -and -not $capacityConfigRestored) {
        try {
            $capacityConfigRestore = Restore-ExactFileState -State $capacityConfigInitial -ExactPath $capacityConfigPath -Label 'finally-capacity-config'
            $capacityConfigRestored = [bool]$capacityConfigRestore.restored
            if ($null -ne $receipt.capacity_config_projection) {
                $receipt.capacity_config_projection.restored_exactly = [bool]$capacityConfigRestore.restored
                $receipt.capacity_config_projection.final_sha256 = [string]$capacityConfigRestore.final_sha256
            }
        } catch {
            $finallyErrors.Add("capacity-config-restore:$($_.Exception.Message)")
        }
    }
    if ($null -ne $originalSnapshot) {
        try {
            Restore-LifecycleSnapshot $originalSnapshot
            Assert-SnapshotEqual $originalSnapshot (Get-LifecycleSnapshot $script:CanonicalAgentDir $script:CanonicalPiToolRoot) 'finally-exact-underlay'
            $extensionPath = Join-Path $script:PackageRoot 'src\extension'
            $extensionItem = Get-Item -LiteralPath $extensionPath -Force
            if (($extensionItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'PI_HIGH_CAPACITY_PACKAGING_FINALLY_JUNCTION_REMAINS' }
            if ($null -ne $junctionBackup -and (Test-Path -LiteralPath $junctionBackup)) { throw "PI_HIGH_CAPACITY_PACKAGING_FINALLY_JUNCTION_BACKUP_REMAINS: $junctionBackup" }
            if ($null -ne $packageTreeInitial -and (Get-TreeFingerprint (Join-Path $script:PackageRoot 'src')) -cne $packageTreeInitial) { throw 'PI_HIGH_CAPACITY_PACKAGING_FINALLY_PACKAGE_TREE_DRIFT' }
            if ($null -ne $coreTreeInitial -and (Get-TreeFingerprint (Join-Path $script:CoreRoot 'dist\core')) -cne $coreTreeInitial) { throw 'PI_HIGH_CAPACITY_PACKAGING_FINALLY_CORE_TREE_DRIFT' }
            $cleanupExact=$true
        } catch {
            $receipt.status='blocked'
            $receipt.error="PI_HIGH_CAPACITY_PACKAGING_FINALLY_RESTORE_FAILED: $($_.Exception.Message); prior=$($receipt.error)"
        }
    }
    $resolvedTemp = Get-NormalizedPath $tempRoot
    $tempPrefix = $tempBase + [IO.Path]::DirectorySeparatorChar
    if ($resolvedTemp.StartsWith($tempPrefix,[StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolvedTemp) -match '^[0-9a-f]{32}$') {
        try {
            if (Test-Path -LiteralPath $resolvedTemp) { [IO.Directory]::Delete($resolvedTemp,$true) }
            $cleanupTemp=-not (Test-Path -LiteralPath $resolvedTemp)
        } catch { $finallyErrors.Add("temp-delete:$($_.Exception.Message)") }
    }
    $receipt.cleanup.exact_underlay=$cleanupExact
    $receipt.cleanup.temp=$cleanupTemp
    $receipt.cleanup['capacity_config_exact'] = [bool]$capacityConfigRestored
    if (-not $cleanupExact -or -not $cleanupTemp -or -not $capacityConfigRestored -or $finallyErrors.Count -gt 0) {
        $receipt.status='blocked'
        if ($finallyErrors.Count -gt 0) {
            $receipt.error="PI_HIGH_CAPACITY_PACKAGING_FINALLY_ERRORS: $($finallyErrors -join '|'); prior=$($receipt.error)"
        }
    }
    $receipt.completed_at=[DateTimeOffset]::Now.ToString('o')
    $json=$receipt | ConvertTo-Json -Depth 12
    if (-not [string]::IsNullOrWhiteSpace($ReceiptPath)) { Write-JsonAtomic -Path $ReceiptPath -Json $json }
    [Console]::Out.WriteLine($json)
}

if ($receipt.status -cne 'verified') { exit 1 }
