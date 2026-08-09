#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AgentDir,
    [Parameter(Mandatory)][string]$PiToolRoot,
    [switch]$VerifyOnly,
    [Parameter(DontShow)][switch]$InternalRestore
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSHighCapacityPath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\','/')
}

function Test-PiSHighCapacityPathEqual {
    param([Parameter(Mandatory)][string]$Left,[Parameter(Mandatory)][string]$Right)
    [string]::Equals(
        (Get-NormalizedPiSHighCapacityPath -Path $Left),
        (Get-NormalizedPiSHighCapacityPath -Path $Right),
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Get-PiSHighCapacityFileState {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Files
    )
    $state = [ordered]@{}
    foreach ($relative in $Files.Keys) {
        $path = Join-Path $Root $relative
        if (-not (Test-Path -LiteralPath $path)) {
            $state[$relative] = 'absent'
            continue
        }
        $item = Get-Item -LiteralPath $path -Force
        if (-not ($item -is [IO.FileInfo]) -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            $state[$relative] = 'invalid-object'
            continue
        }
        $state[$relative] = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    }
    $state
}

function Test-PiSHighCapacityState {
    param(
        [Parameter(Mandatory)][System.Collections.IDictionary]$Actual,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Files,
        [Parameter(Mandatory)][ValidateSet('Pre','Final')][string]$Expected
    )
    @($Files.Keys | Where-Object { $Actual[$_] -ceq $Files[$_][$Expected] }).Count -eq $Files.Count
}

function Format-PiSHighCapacityState {
    param([Parameter(Mandatory)][System.Collections.IDictionary]$State)
    @($State.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ';'
}

function Assert-PiSHighCapacityNoReparsePath {
    param([Parameter(Mandatory)][string]$Path)
    $full = Get-NormalizedPiSHighCapacityPath -Path $Path
    $root = [IO.Path]::GetPathRoot($full)
    $cursor = $full
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "PI_S_HIGH_CAPACITY_REPARSE_POINT_REJECTED: $cursor"
            }
        }
        if (Test-PiSHighCapacityPathEqual -Left $cursor -Right $root) { break }
        $parent = Split-Path -Parent $cursor
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ceq $cursor) { break }
        $cursor = $parent
    }
}

function Assert-PiSHighCapacityLocalFixedNtfsPath {
    param([Parameter(Mandatory)][string]$Path)
    $full = Get-NormalizedPiSHighCapacityPath -Path $Path
    $root = [IO.Path]::GetPathRoot($full)
    if ([string]::IsNullOrWhiteSpace($root) -or $root -notmatch '^[A-Za-z]:\\$') {
        throw "PI_S_HIGH_CAPACITY_LOCAL_NTFS_REQUIRED: path=$full"
    }
    $driveLetter = $root.Substring(0,1)
    $volume = Get-Volume -DriveLetter $driveLetter -ErrorAction Stop
    if ([string]$volume.FileSystem -cne 'NTFS') {
        throw "PI_S_HIGH_CAPACITY_NTFS_REQUIRED: path=$full filesystem=$($volume.FileSystem)"
    }
    $deviceId = $driveLetter.ToUpperInvariant() + ':'
    $logicalDisk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$deviceId'" -ErrorAction Stop
    if ([int]$logicalDisk.DriveType -ne 3) {
        throw "PI_S_HIGH_CAPACITY_FIXED_DRIVE_REQUIRED: path=$full drive_type=$($logicalDisk.DriveType)"
    }
    Assert-PiSHighCapacityNoReparsePath -Path $full
}

function Invoke-PiSHighCapacityHiddenProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )
    $quote = {
        param([string]$Value)
        if ($Value -notmatch '[\s"]') { return $Value }
        '"' + ($Value -replace '(\\*)"','$1$1\"' -replace '(\\+)$','$1$1') + '"'
    }
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Arguments = (@($Arguments | ForEach-Object { & $quote ([string]$_) }) -join ' ')
    $process = [Diagnostics.Process]::Start($startInfo)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    [pscustomobject]@{ ExitCode = $process.ExitCode; Stdout = $stdout; Stderr = $stderr }
}

function Invoke-PiSHighCapacitySqliteProbe {
    param([Parameter(Mandatory)][string]$TransactionRoot)
    $probeRoot = Join-Path $TransactionRoot 'sqlite-probe'
    New-Item -ItemType Directory -Force -Path $probeRoot | Out-Null
    $scriptPath = Join-Path $probeRoot 'probe.mjs'
    $databasePath = Join-Path $probeRoot 'probe.sqlite'
    $source = @'
import { DatabaseSync } from "node:sqlite";
const file = process.argv[2];
const db = new DatabaseSync(file, { timeout: 0 });
try {
  db.exec("BEGIN IMMEDIATE");
  db.exec("CREATE TABLE capacity_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)");
  db.prepare("INSERT INTO capacity_probe (value) VALUES (?)").run("ok");
  db.exec("COMMIT");
  const row = db.prepare("SELECT value FROM capacity_probe WHERE id = 1").get();
  if (row?.value !== "ok") throw new Error("SQLITE_PROBE_READBACK_FAILED");
  process.stdout.write(JSON.stringify({ ok: true, sqlite: true, transaction: "immediate", value: row.value }));
} catch (error) {
  try { db.exec("ROLLBACK"); } catch {}
  throw error;
} finally {
  db.close();
}
'@
    [IO.File]::WriteAllText($scriptPath,$source,[Text.UTF8Encoding]::new($false))
    $nodeCommand = Get-Command node -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $result = Invoke-PiSHighCapacityHiddenProcess -FilePath $nodeCommand.Source -Arguments @($scriptPath,$databasePath) -WorkingDirectory $probeRoot
    if ($result.ExitCode -ne 0) {
        throw "PI_S_HIGH_CAPACITY_SQLITE_PROBE_FAILED: exit=$($result.ExitCode) stderr=$($result.Stderr.Trim())"
    }
    if (-not [string]::IsNullOrWhiteSpace($result.Stderr)) {
        throw "PI_S_HIGH_CAPACITY_SQLITE_PROBE_STDERR_REJECTED: $($result.Stderr.Trim())"
    }
    try {
        $receipt = $result.Stdout | ConvertFrom-Json
    } catch {
        throw "PI_S_HIGH_CAPACITY_SQLITE_PROBE_OUTPUT_INVALID: $($result.Stdout)"
    }
    if (-not [bool]$receipt.ok -or -not [bool]$receipt.sqlite -or [string]$receipt.transaction -cne 'immediate') {
        throw "PI_S_HIGH_CAPACITY_SQLITE_PROBE_READBACK_FAILED: $($result.Stdout)"
    }
    [ordered]@{ ok = $true; node = $nodeCommand.Source; transaction = 'BEGIN IMMEDIATE'; stderr_empty = $true }
}

function Initialize-PiSHighCapacityStage {
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$StageRoot,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Files
    )
    New-Item -ItemType Directory -Force -Path $StageRoot | Out-Null
    foreach ($relative in $Files.Keys) {
        $source = Join-Path $SourceRoot $relative
        $destination = Join-Path $StageRoot $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination $destination -Force
        }
    }
}

function Invoke-PiSHighCapacityGitPatch {
    param(
        [Parameter(Mandatory)][string]$StageRoot,
        [Parameter(Mandatory)][string]$PatchPath,
        [switch]$Reverse
    )
    $arguments = @('-c','core.autocrlf=false','-C',$StageRoot,'apply')
    if ($Reverse) { $arguments += '--reverse' }
    $checkArguments = @($arguments + @('--check',$PatchPath))
    $checkOutput = & git @checkArguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "PI_S_HIGH_CAPACITY_PATCH_CHECK_FAILED: patch=$PatchPath output=$($checkOutput -join ' ')"
    }
    $applyArguments = @($arguments + @($PatchPath))
    $applyOutput = & git @applyArguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "PI_S_HIGH_CAPACITY_PATCH_APPLY_FAILED: patch=$PatchPath output=$($applyOutput -join ' ')"
    }
}

function Assert-PiSHighCapacityTreeState {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Files,
        [Parameter(Mandatory)][ValidateSet('Pre','Final')][string]$Expected,
        [Parameter(Mandatory)][string]$ErrorId
    )
    $actual = Get-PiSHighCapacityFileState -Root $Root -Files $Files
    if (-not (Test-PiSHighCapacityState -Actual $actual -Files $Files -Expected $Expected)) {
        throw "$ErrorId`: $(Format-PiSHighCapacityState -State $actual)"
    }
    $actual
}

function Test-PiSHighCapacityFileBytesEqual {
    param([Parameter(Mandatory)][string]$Left,[Parameter(Mandatory)][string]$Right)
    $leftBytes = [IO.File]::ReadAllBytes($Left)
    $rightBytes = [IO.File]::ReadAllBytes($Right)
    if ($leftBytes.Length -ne $rightBytes.Length) { return $false }
    for ($index = 0; $index -lt $leftBytes.Length; $index += 1) {
        if ($leftBytes[$index] -ne $rightBytes[$index]) { return $false }
    }
    $true
}

function Copy-PiSHighCapacityFileAtomic {
    param([Parameter(Mandatory)][string]$Source,[Parameter(Mandatory)][string]$Destination)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    $temporary = "$Destination.xinao-high-capacity-$PID-$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllBytes($temporary,[IO.File]::ReadAllBytes($Source))
        Move-Item -LiteralPath $temporary -Destination $Destination -Force
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Invoke-PiSHighCapacityCommit {
    param(
        [Parameter(Mandatory)][object[]]$Trees,
        [Parameter(Mandatory)][ValidateSet('Pre','Final')][string]$SourceState,
        [Parameter(Mandatory)][ValidateSet('Pre','Final')][string]$TargetState,
        [Parameter(Mandatory)][string]$TransactionRoot
    )
    $backupRoot = Join-Path $TransactionRoot 'rollback'
    New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
    $entries = New-Object Collections.ArrayList
    foreach ($tree in $Trees) {
        Assert-PiSHighCapacityTreeState -Root $tree.LiveRoot -Files $tree.Files -Expected $SourceState -ErrorId 'PI_S_HIGH_CAPACITY_COMMIT_SOURCE_CHANGED' | Out-Null
        foreach ($relative in $tree.Files.Keys) {
            $destination = Join-Path $tree.LiveRoot $relative
            $staged = Join-Path $tree.StageRoot $relative
            $backup = Join-Path (Join-Path $backupRoot $tree.Name) $relative
            $existed = Test-Path -LiteralPath $destination -PathType Leaf
            if ($existed) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
                Copy-Item -LiteralPath $destination -Destination $backup -Force
            }
            [void]$entries.Add([pscustomobject]@{
                Destination = $destination
                Staged = $staged
                Backup = $backup
                Existed = $existed
            })
        }
    }

    $committedEntries = New-Object Collections.ArrayList
    try {
        foreach ($entry in $entries) {
            if (Test-Path -LiteralPath $entry.Staged -PathType Leaf) {
                Copy-PiSHighCapacityFileAtomic -Source $entry.Staged -Destination $entry.Destination
            } elseif (Test-Path -LiteralPath $entry.Destination -PathType Leaf) {
                Remove-Item -LiteralPath $entry.Destination -Force
            }
            [void]$committedEntries.Add($entry)
        }
        foreach ($tree in $Trees) {
            Assert-PiSHighCapacityTreeState -Root $tree.LiveRoot -Files $tree.Files -Expected $TargetState -ErrorId 'PI_S_HIGH_CAPACITY_COMMIT_VERIFY_FAILED' | Out-Null
        }
    } catch {
        $commitError = $_
        $rollbackErrors = New-Object Collections.Generic.List[string]
        for ($entryIndex = $committedEntries.Count - 1; $entryIndex -ge 0; $entryIndex -= 1) {
            $entry = $committedEntries[$entryIndex]
            try {
                if ($entry.Existed) {
                    Copy-PiSHighCapacityFileAtomic -Source $entry.Backup -Destination $entry.Destination
                } elseif (Test-Path -LiteralPath $entry.Destination -PathType Leaf) {
                    Remove-Item -LiteralPath $entry.Destination -Force
                }
            } catch {
                $rollbackErrors.Add("$($entry.Destination):$($_.Exception.Message)")
            }
        }
        if ($rollbackErrors.Count -gt 0) {
            throw "PI_S_HIGH_CAPACITY_COMMIT_AND_ROLLBACK_FAILED: commit=$($commitError.Exception.Message) rollback=$($rollbackErrors -join '|')"
        }
        throw "PI_S_HIGH_CAPACITY_COMMIT_ROLLED_BACK: $($commitError.Exception.Message)"
    }
}

function Remove-PiSHighCapacityTransactionRoot {
    param([Parameter(Mandatory)][string]$TransactionRoot,[Parameter(Mandatory)][string]$TransactionParent)
    $full = Get-NormalizedPiSHighCapacityPath -Path $TransactionRoot
    $parentPrefix = (Get-NormalizedPiSHighCapacityPath -Path $TransactionParent) + [IO.Path]::DirectorySeparatorChar
    $leaf = Split-Path -Leaf $full
    if (-not $full.StartsWith($parentPrefix,[StringComparison]::OrdinalIgnoreCase) -or $leaf -notmatch '^txn-[a-f0-9]{32}$') {
        throw "PI_S_HIGH_CAPACITY_TRANSACTION_CLEANUP_TARGET_REJECTED: $full"
    }
    if (Test-Path -LiteralPath $full -PathType Container) {
        Remove-Item -LiteralPath $full -Recurse -Force
    }
}

$targetAgentDir = Get-NormalizedPiSHighCapacityPath -Path $AgentDir
$targetPiToolRoot = Get-NormalizedPiSHighCapacityPath -Path $PiToolRoot
$activeAgentDir = Get-NormalizedPiSHighCapacityPath -Path (Join-Path $script:PiDualEntryStateRoot 'profiles\prime-s')
$mainToolRoot = Get-NormalizedPiSHighCapacityPath -Path $script:PiDualEntryMainToolRoot
$labParent = Get-NormalizedPiSHighCapacityPath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
$targetParent = Get-NormalizedPiSHighCapacityPath -Path (Split-Path -Parent $targetAgentDir)

if (Test-PiSHighCapacityPathEqual -Left $targetAgentDir -Right $activeAgentDir) {
    if (-not (Test-PiSHighCapacityPathEqual -Left $targetPiToolRoot -Right $mainToolRoot)) {
        throw "PI_S_HIGH_CAPACITY_ROOT_PAIR_MISMATCH: agent_dir=$targetAgentDir pi_tool_root=$targetPiToolRoot"
    }
} elseif (Test-PiSHighCapacityPathEqual -Left $targetParent -Right $labParent) {
    $expectedLabToolRoot = Get-NormalizedPiSHighCapacityPath -Path (Join-Path $targetAgentDir 'pi-tool-root')
    if (-not (Test-PiSHighCapacityPathEqual -Left $targetPiToolRoot -Right $expectedLabToolRoot)) {
        throw "PI_S_HIGH_CAPACITY_LAB_ROOT_PAIR_MISMATCH: expected=$expectedLabToolRoot actual=$targetPiToolRoot"
    }
} else {
    throw "PI_S_HIGH_CAPACITY_TARGET_OUTSIDE_MAIN_PROFILE: agent_dir=$targetAgentDir"
}
Assert-PiSHighCapacityLocalFixedNtfsPath -Path $targetAgentDir
Assert-PiSHighCapacityLocalFixedNtfsPath -Path $targetPiToolRoot

$packageRoot = Join-Path $targetAgentDir 'npm\node_modules\pi-subagents'
$coreRoot = Join-Path $targetPiToolRoot 'node_modules\@earendil-works\pi-coding-agent'
$packageJsonPath = Join-Path $packageRoot 'package.json'
$corePackageJsonPath = Join-Path $coreRoot 'package.json'
$patchRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'patches'
$packagePatchPath = Join-Path $patchRoot 'pi-subagents-0.44.0-high-capacity-v1.patch'
$corePatchPath = Join-Path $patchRoot 'pi-coding-agent-0.84.1-high-capacity-v1.patch'
$expectedPackagePatchHash = 'a31617bd6df9004f0581935de5ef68897b2382f3c7656b1d6977c7a61cc645d4'
$expectedCorePatchHash = '13a89eda2b22e9337c90aa817e75e766499ee62f1fa044142a9cceef91d9d3ad'
$candidateManifestHash = '019f6fec12a1261c29af1c3e38a52a6a9858e14d7d42cbe9d918a3306fdeb4bb'

$packageFiles = [ordered]@{
    'src\extension\fanout-child.ts' = @{ Pre = '0209c6079fb86be1257e68a460eedbea8da577193a831fc0ecec3e3a6f7d8e51'; Final = 'b777190d50b43d4ca1366da8f64e53eb75846d660a149029cc2cc027607f632b' }
    'src\extension\index.ts' = @{ Pre = '5170c2f15a74bcfc4edbfc2b20eef8494c6fb3836553da43c698596e357b7009'; Final = '2d3d3c61eb59186a2abdd59b235a834abe5ac7daca64c9a504bb902eb78ed5a9' }
    'src\extension\public-execution.ts' = @{ Pre = 'e89b13bb1257fd626dcb21f69b0ca2ceb5750047a40757304af9e0e5dd02cede'; Final = 'ec34983599cbc79143c103333ae86475beba9a33f36379d6ca6254c3589e4d1f' }
    'src\extension\rpc.ts' = @{ Pre = '397d971cc7ec1ef1df846426c654d343a3fa91ab718eec24a8e78a12ad0fc0a7'; Final = '637d4c70a99f229c11e743a6b2e41569b91217f36f002958bf3ad3ed2cae5599' }
    'src\extension\schemas.ts' = @{ Pre = 'ddd81da1c7d0063acadfe692378b640bf87418c699b3b471e5e74b7eac069bcc'; Final = 'd83e7ba5311dfc2d4b0316365ff934929abe6e1ce59ffeea5d4134c242b33302' }
    'src\extension\tool-description.ts' = @{ Pre = 'd2ceefa78c4f5a5cf57d91f8b368144ffe29ea14ef2cf650f866218040aabb89'; Final = '3493ac9686b14f7322786467948c6efcc0c23340bfaee32f06c50db57e278d50' }
    'src\runs\background\async-execution.ts' = @{ Pre = 'b8a272c050155439dc405da71d2cf5c21002744357b1c37e5f046c399cde10e7'; Final = 'ef0ba69b0c6d083b27e5f05336031556ad0a7a2646cfb018ec91a3100c8eadf4' }
    'src\runs\background\async-resume.ts' = @{ Pre = 'ae3a301b1dab8ec0b8348def3111eb5382a8006d042b0726c313e8d83ef806e3'; Final = 'a32eb20de710ec4b443b1027d8bff76afc8d6e853d4d4e72783501b839764661' }
    'src\runs\background\retained-children.ts' = @{ Pre = '39baebf55230c3812d04d6573296356e62f80cf9f8cb258f0f2b3b4c9c77580a'; Final = '444fd33aaeb5117483330d9fc1535acecf4531927070cea3c5c550367b7023b1' }
    'src\runs\background\subagent-runner.ts' = @{ Pre = '599eb6faad6029272d26b41aa9ed8c6c0cd1b389230cd5fe46203a555312382d'; Final = 'ae581fd8367e8ae32c712afb3cc405b2fa9e6b686b6b14f81af54d870c550f86' }
    'src\runs\foreground\chain-execution.ts' = @{ Pre = 'c810388939735b169bba11c9cb8359803e063d408cd9d18feb1884ffebbdec41'; Final = 'aaf7271cd547c948ef1f4492f32ec85f7ab4a113fc19899c34396fe89ec7ef77' }
    'src\runs\foreground\execution.ts' = @{ Pre = '3d757df6cf57b0865668da1ba876c10d57903601c18d77a01a01d25c6054cdb4'; Final = '3345076d827c8e63f973794a195fefab5e600e8c000583d4a98f72b52fb051ce' }
    'src\runs\foreground\subagent-executor.ts' = @{ Pre = 'f6e1ed79bfc0373e77efb0754dcfcddf643942d406d1c8371d57a5c3203f4fed'; Final = '411f4f275f164786f2388fb001d67954366d69fd5188a996b1a79d300dcd320e' }
    'src\runs\shared\parallel-utils.ts' = @{ Pre = '55a328d8b8b6a2d5802bdee1d512e06678f33cdaf7e574ab0713ac0df20c8dbf'; Final = '1d0b11ce0fab443cdbe9798007c5fc68f344757e617d8ced572f93fe4a047793' }
    'src\runs\shared\pi-args.ts' = @{ Pre = '20714d7c3ac80716ddcdabff4d63cdd25144748b3c74602de93587fa5c8f6020'; Final = 'a177dfe33d9eab63960df1cc998ead47be5138342427845d1896f9066332847f' }
    'src\runs\shared\spawn-budget.ts' = @{ Pre = 'fbc12ffc3623444fd4f802a5dce3165924a2864c06a151c562d8de59e3a4a7f8'; Final = '5f5d8a25f9c4df093065bc8a56d60e2a2d5719b4ff99ed6b498fde8e38422744' }
    'src\runs\shared\turn-budget.ts' = @{ Pre = 'a8500a05bc8836d61de03afb186b4d000920b4a79b620819aa6242daa6ba0a8d'; Final = '1984da30964641c3dc3428848f087ac12a3bc7374513e23fbd872651e82de06a' }
    'src\runs\shared\xinao-pi-subagent-capacity-runtime.d.ts' = @{ Pre = 'absent'; Final = '52a0df5fef19215f13fe7fb6828e4513a7e55c28f13baaa4c32d0f2d64180af3' }
    'src\runs\shared\xinao-pi-subagent-capacity-runtime.js' = @{ Pre = 'absent'; Final = 'ba5614b01ee3b2c15194d1006596bef50134fdd4f86125713cf61987f7be76b2' }
    'src\shared\types.ts' = @{ Pre = '2e80765b425f6a8481cb559759b313ae679e2f67959a3c0f61214e1d529d6a33'; Final = 'acb00bd809ebaaf65bd67f300444ce314d6255739af5f140c8fed640ed8791ec' }
    'src\workflows\scripted-workflow.ts' = @{ Pre = 'b67c105c52e33be616f316471601120751741f283a0ccea3f123fb9867ccf0e6'; Final = '80d38d915e08f0173387c14249bed9688d1f9ec1d5c7f177e6d4cafba68b2eea' }
}
$coreFiles = [ordered]@{
    'dist\core\sdk.js' = @{ Pre = 'f6e72f33f44c708249c8d74931d816c36fe27175f7fa1639cba0a3d988592821'; Final = '0248f6d4c080a92e8e076016b0e4d9b8533041c624445da6cd94bc8a3f83e7c5' }
    'dist\core\xinao-pi-subagent-capacity-runtime.js' = @{ Pre = 'absent'; Final = 'ba5614b01ee3b2c15194d1006596bef50134fdd4f86125713cf61987f7be76b2' }
}

Assert-PiSHighCapacityNoReparsePath -Path $packageRoot
Assert-PiSHighCapacityNoReparsePath -Path $coreRoot
foreach ($relative in $packageFiles.Keys) {
    Assert-PiSHighCapacityNoReparsePath -Path (Join-Path $packageRoot $relative)
}
foreach ($relative in $coreFiles.Keys) {
    Assert-PiSHighCapacityNoReparsePath -Path (Join-Path $coreRoot $relative)
}

foreach ($required in @($packageJsonPath,$corePackageJsonPath,$packagePatchPath,$corePatchPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_HIGH_CAPACITY_SOURCE_MISSING: $required"
    }
}
$packagePatchHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $packagePatchPath).Hash.ToLowerInvariant()
$corePatchHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $corePatchPath).Hash.ToLowerInvariant()
if ($packagePatchHash -cne $expectedPackagePatchHash) {
    throw "PI_S_HIGH_CAPACITY_PACKAGE_PATCH_IDENTITY_MISMATCH: expected=$expectedPackagePatchHash actual=$packagePatchHash"
}
if ($corePatchHash -cne $expectedCorePatchHash) {
    throw "PI_S_HIGH_CAPACITY_CORE_PATCH_IDENTITY_MISMATCH: expected=$expectedCorePatchHash actual=$corePatchHash"
}
$package = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
$corePackage = Get-Content -Raw -LiteralPath $corePackageJsonPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$package.name -cne 'pi-subagents' -or [string]$package.version -cne '0.44.0') {
    throw "PI_S_HIGH_CAPACITY_PACKAGE_VERSION_UNSUPPORTED: $($package.name)@$($package.version)"
}
if ([string]$corePackage.name -cne '@earendil-works/pi-coding-agent' -or [string]$corePackage.version -cne '0.84.1') {
    throw "PI_S_HIGH_CAPACITY_CORE_VERSION_UNSUPPORTED: $($corePackage.name)@$($corePackage.version)"
}

$registryRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\capacity\prime-s'
$transactionParent = 'D:\XINAO_RESEARCH_RUNTIME\temp\pi-high-capacity-compatibility'
Assert-PiSHighCapacityLocalFixedNtfsPath -Path $registryRoot
Assert-PiSHighCapacityLocalFixedNtfsPath -Path $transactionParent

$transactionMutex = New-Object Threading.Mutex($false,'Global\XinaoPiSHighCapacityCompatibilityV1')
$transactionMutexAcquired = $false
try {
    try {
        $transactionMutexAcquired = $transactionMutex.WaitOne(0)
    } catch [Threading.AbandonedMutexException] {
        $transactionMutexAcquired = $true
    }
    if (-not $transactionMutexAcquired) {
        throw 'PI_S_HIGH_CAPACITY_TRANSACTION_ALREADY_RUNNING'
    }

$packageBefore = Get-PiSHighCapacityFileState -Root $packageRoot -Files $packageFiles
$coreBefore = Get-PiSHighCapacityFileState -Root $coreRoot -Files $coreFiles
$allPre = (
    (Test-PiSHighCapacityState -Actual $packageBefore -Files $packageFiles -Expected Pre) -and
    (Test-PiSHighCapacityState -Actual $coreBefore -Files $coreFiles -Expected Pre)
)
$allFinal = (
    (Test-PiSHighCapacityState -Actual $packageBefore -Files $packageFiles -Expected Final) -and
    (Test-PiSHighCapacityState -Actual $coreBefore -Files $coreFiles -Expected Final)
)
if (-not $allPre -and -not $allFinal) {
    throw "PI_S_HIGH_CAPACITY_SOURCE_CONFLICT: package=$(Format-PiSHighCapacityState -State $packageBefore) core=$(Format-PiSHighCapacityState -State $coreBefore)"
}

$operation = if ($InternalRestore) { 'restore' } else { 'apply' }
$alreadyDesired = if ($InternalRestore) { $allPre } else { $allFinal }
$sourceReady = if ($InternalRestore) { $allFinal } else { $allPre }
if ($VerifyOnly -and -not $alreadyDesired) {
    $errorId = if ($InternalRestore) { 'PI_S_HIGH_CAPACITY_RESTORE_NOT_APPLIED' } else { 'PI_S_HIGH_CAPACITY_PATCH_NOT_APPLIED' }
    throw "$errorId`: agent_dir=$targetAgentDir pi_tool_root=$targetPiToolRoot"
}

$transactionRoot = Join-Path $transactionParent ('txn-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $transactionRoot | Out-Null
$changed = $false
$sqliteProbe = $null
try {
    $sqliteProbe = Invoke-PiSHighCapacitySqliteProbe -TransactionRoot $transactionRoot
    if (-not $alreadyDesired) {
        if (-not $sourceReady) { throw 'PI_S_HIGH_CAPACITY_INTERNAL_STATE_CLASSIFICATION_FAILED' }
        $packageStage = Join-Path $transactionRoot 'stage-package'
        $coreStage = Join-Path $transactionRoot 'stage-core'
        Initialize-PiSHighCapacityStage -SourceRoot $packageRoot -StageRoot $packageStage -Files $packageFiles
        Initialize-PiSHighCapacityStage -SourceRoot $coreRoot -StageRoot $coreStage -Files $coreFiles

        if ($InternalRestore) {
            Invoke-PiSHighCapacityGitPatch -StageRoot $coreStage -PatchPath $corePatchPath -Reverse
            Invoke-PiSHighCapacityGitPatch -StageRoot $packageStage -PatchPath $packagePatchPath -Reverse
            Assert-PiSHighCapacityTreeState -Root $coreStage -Files $coreFiles -Expected Pre -ErrorId 'PI_S_HIGH_CAPACITY_RESTORE_CORE_STAGE_VERIFY_FAILED' | Out-Null
            Assert-PiSHighCapacityTreeState -Root $packageStage -Files $packageFiles -Expected Pre -ErrorId 'PI_S_HIGH_CAPACITY_RESTORE_PACKAGE_STAGE_VERIFY_FAILED' | Out-Null
            $trees = @(
                [pscustomobject]@{ Name = 'core'; LiveRoot = $coreRoot; StageRoot = $coreStage; Files = $coreFiles },
                [pscustomobject]@{ Name = 'package'; LiveRoot = $packageRoot; StageRoot = $packageStage; Files = $packageFiles }
            )
            Invoke-PiSHighCapacityCommit -Trees $trees -SourceState Final -TargetState Pre -TransactionRoot $transactionRoot
        } else {
            Invoke-PiSHighCapacityGitPatch -StageRoot $packageStage -PatchPath $packagePatchPath
            Invoke-PiSHighCapacityGitPatch -StageRoot $coreStage -PatchPath $corePatchPath
            Assert-PiSHighCapacityTreeState -Root $packageStage -Files $packageFiles -Expected Final -ErrorId 'PI_S_HIGH_CAPACITY_PACKAGE_STAGE_VERIFY_FAILED' | Out-Null
            Assert-PiSHighCapacityTreeState -Root $coreStage -Files $coreFiles -Expected Final -ErrorId 'PI_S_HIGH_CAPACITY_CORE_STAGE_VERIFY_FAILED' | Out-Null
            $packageRuntime = Join-Path $packageStage 'src\runs\shared\xinao-pi-subagent-capacity-runtime.js'
            $coreRuntime = Join-Path $coreStage 'dist\core\xinao-pi-subagent-capacity-runtime.js'
            if (-not (Test-PiSHighCapacityFileBytesEqual -Left $packageRuntime -Right $coreRuntime)) {
                throw 'PI_S_HIGH_CAPACITY_RUNTIME_PROJECTION_MISMATCH'
            }
            $trees = @(
                [pscustomobject]@{ Name = 'package'; LiveRoot = $packageRoot; StageRoot = $packageStage; Files = $packageFiles },
                [pscustomobject]@{ Name = 'core'; LiveRoot = $coreRoot; StageRoot = $coreStage; Files = $coreFiles }
            )
            Invoke-PiSHighCapacityCommit -Trees $trees -SourceState Pre -TargetState Final -TransactionRoot $transactionRoot
        }
        $changed = $true
    }

    $expectedAfter = if ($InternalRestore) { 'Pre' } else { 'Final' }
    $packageAfter = Assert-PiSHighCapacityTreeState -Root $packageRoot -Files $packageFiles -Expected $expectedAfter -ErrorId 'PI_S_HIGH_CAPACITY_PACKAGE_FINAL_VERIFY_FAILED'
    $coreAfter = Assert-PiSHighCapacityTreeState -Root $coreRoot -Files $coreFiles -Expected $expectedAfter -ErrorId 'PI_S_HIGH_CAPACITY_CORE_FINAL_VERIFY_FAILED'
    $runtimeProjectionEqual = $false
    if (-not $InternalRestore) {
        $packageRuntime = Join-Path $packageRoot 'src\runs\shared\xinao-pi-subagent-capacity-runtime.js'
        $coreRuntime = Join-Path $coreRoot 'dist\core\xinao-pi-subagent-capacity-runtime.js'
        $runtimeProjectionEqual = Test-PiSHighCapacityFileBytesEqual -Left $packageRuntime -Right $coreRuntime
        if (-not $runtimeProjectionEqual) { throw 'PI_S_HIGH_CAPACITY_RUNTIME_FINAL_PROJECTION_MISMATCH' }
    }

    [pscustomobject]@{
        schema = if ($InternalRestore) { 'xinao.pi_s_high_capacity_compatibility_restore.v1' } else { 'xinao.pi_s_high_capacity_compatibility.v1' }
        operation = $operation
        patch_id = 'pi-high-capacity-compatibility-v1'
        agent_dir = $targetAgentDir
        pi_tool_root = $targetPiToolRoot
        package = 'pi-subagents@0.44.0'
        core_package = '@earendil-works/pi-coding-agent@0.84.1'
        package_patch_path = $packagePatchPath
        package_patch_sha256 = $packagePatchHash
        core_patch_path = $corePatchPath
        core_patch_sha256 = $corePatchHash
        candidate_manifest_sha256 = $candidateManifestHash
        before_package_sha256 = $packageBefore
        before_core_sha256 = $coreBefore
        after_package_sha256 = $packageAfter
        after_core_sha256 = $coreAfter
        changed = $changed
        verify_only = [bool]$VerifyOnly
        sqlite_probe = $sqliteProbe
        registry_root = $registryRoot
        registry_root_created = $false
        runtime_projection_byte_equal = $runtimeProjectionEqual
        package_underlay = 'windows+owner-session-stop+filesystem-policy'
        core_underlay = 'midturn+native-continuation'
        handshake_written = $false
        mixed_state_accepted = $false
        verified = $true
        handshake_eligible = [bool](-not $InternalRestore)
        prime_b_modified = $false
        active_process_restart_required = $true
    } | ConvertTo-Json -Depth 8
} finally {
    Remove-PiSHighCapacityTransactionRoot -TransactionRoot $transactionRoot -TransactionParent $transactionParent
}
} finally {
    if ($transactionMutexAcquired) { $transactionMutex.ReleaseMutex() }
    $transactionMutex.Dispose()
}
