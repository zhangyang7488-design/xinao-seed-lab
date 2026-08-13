[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Upgrade,
    [switch]$Remove,
    [switch]$Audit,
    [ValidateSet(1, 2, 5, 15)]
    [int]$Minutes = 15
)

$ErrorActionPreference = 'Stop'

$taskName = 'XINAO-S-Context-Rollout-Consumer-v1'
$taskPath = '\'
$sourcePythonRoot = 'D:\XINAO_RESEARCH_RUNTIME\tools\cpython-3.13.14-official'
$sourcePythonPath = 'D:\XINAO_RESEARCH_RUNTIME\tools\cpython-3.13.14-official\python.exe'
$sourceRepositoryRoot = 'E:\XINAO_RESEARCH_WORKSPACES\S'
$sourceConsumerScript = 'E:\XINAO_RESEARCH_WORKSPACES\S\scripts\context_rollout_consumer.py'
$bundleLockPath = 'E:\XINAO_RESEARCH_WORKSPACES\S\scripts\context_rollout_consumer.bundle.lock.json'
$consumerReceiptPath = 'D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric\_consumer\last_receipt.json'
$presentationReceiptPath = 'D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric\_consumer\presentation_last_receipt.json'
$expectedPresentationRuntimeRootHashes = @(
    '4dd6d4179cda425a90a3b46c52baa7e705ac26d95df3ed2b763f85478926d9c0',
    'afc8ff4d120f1968ad1fbaf4bb096435eba32561859786ee859a5d284c3782aa',
    '247ddd4bc4925aa2786b84b1495d657f23194b59e013058d8c0e84d200815691',
    'f1e7525ba72d661a66ef07895cfd662f9473a7c8f1f8bfb8b53b38ec99fed0b1',
    '5edffee57ec0692972583b8116c4dc7fc19a56d05af04175f1fc410c3f9352f6',
    '5ed766c971420da10a2b8b4a30d4b13c1954a2fc4930fc2a53ca05677a59c281',
    'b469bf51ee586a5c3ab9aa595288f3d505f39a4870d7a0f4e3a899ad504006a3',
    '91f853881f3bfcfbf1b165f0e679b14a7a49d6b6fc9200c5c93e283db533b39f',
    '1cf11489bc55199360b58b8c88e8a8f9544c6a27250de6b4e0cd847a7499ec60'
)
$officialPythonSha256 = 'ef8f51028ac5329641985112f8efb1c2d4c47c86b8011ddf7e6fae21e2b4e5a1'
$officialPythonwSha256 = '95225ed035643523e8c586c11981e276541dce4949eb35cf8cf5741c824249d4'
$expectedBundleLockSha256 = '37c5a974127fc0d5ac1a3043311633f050ca24877a6dea412f7460bb84eda1b5'
$expectedBundleContentId = 'f117fe78c0772a6a1a6c451451f23c154340004b9df74775ac414fbc1729a664'
$expectedBundleFileCount = 1337
$managedUpgradeSourceContentId = 'ab30ddf91121299f0ed0a0595b4af13dc215a88512ed7c670090d1d2453b4c80'
$managedUpgradeSourceManifestSha256 = '0bd81900d25ff27c1978b130ee39a0586ad926d8b3574bdee33370d333da1d81'
$managedUpgradeSourceFileCount = 1337
$managedUpgradeSourceNormalizedXmlSha256 = 'c1f5bcebc3d35abdf93d612cdcc0dfb273a19b7bf3033970d891720d93c669dd'
$mutationMutexName = 'Global\XINAO.S.ContextRolloutConsumer.Mutation.v1'
$bundleLockSchema = 's.context_rollout_consumer.bundle_lock.v1'
$requiredLockedFilePaths = @(
    'python/python.exe',
    'python/pythonw.exe',
    'app/scripts/context_rollout_consumer.py',
    'app/scripts/Invoke-SPresentationDelivery.ps1',
    'app/services/__init__.py',
    'app/services/agent_runtime/__init__.py',
    'app/services/agent_runtime/context_fabric.py',
    'app/services/agent_runtime/context_runtime_completion.py'
    'app/services/agent_runtime/presentation_reducer.py'
    'app/services/agent_runtime/presentation_observer.py'
    'app/services/agent_runtime/presentation_delivery.py'
    'app/services/agent_runtime/presentation_lock.py'
)
$managedUpgradeSourceRequiredPaths = @($requiredLockedFilePaths)
$directLockedFileHashes = [ordered]@{
    'python/python.exe' = $officialPythonSha256
    'python/pythonw.exe' = $officialPythonwSha256
    'app/scripts/context_rollout_consumer.py' = '861e870ede5f6743a6c13b2c682edb346e3d9a0ff2089f56b4513dbeec8e8eb4'
    'app/scripts/Invoke-SPresentationDelivery.ps1' = '11137a2faacd8af55320aebdd7f2d08d01e5a20cd213a6a3615b6302f9016e21'
}
$bundleBoundary = [Environment]::ExpandEnvironmentVariables('%LOCALAPPDATA%')
if ([string]::IsNullOrWhiteSpace($bundleBoundary) -or -not [System.IO.Path]::IsPathRooted($bundleBoundary)) {
    throw 'LOCALAPPDATA does not resolve to an absolute current-user boundary.'
}
$bundleBase = Join-Path $bundleBoundary 'XINAO\SContextRolloutConsumer'
$descriptionPrefix = 'XINAO S context rollout consumer v1; registration='
$bundleManifestName = 'manifest.json'
$bundleManifestSchema = 's.context_rollout_consumer.bundle.v1'
$expectedRepetitionDuration = [System.Xml.XmlConvert]::ToString((New-TimeSpan -Days 3650))
$requestedActions = @($Apply, $Upgrade, $Remove, $Audit).Where({ $_ }).Count
if ($requestedActions -gt 1) {
    throw 'Choose only one of -Apply, -Upgrade, -Remove, or -Audit.'
}
if ($requestedActions -eq 0) {
    $Audit = $true
}

function Get-CurrentIdentityName {
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
}

function Get-CurrentIdentitySid {
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
}

function Resolve-IdentitySid {
    param([string]$Identity)
    if ([string]::IsNullOrWhiteSpace($Identity)) {
        return ''
    }
    if ($Identity -match '^S-1-') {
        return $Identity
    }
    try {
        return [System.Security.Principal.NTAccount]::new($Identity).Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
    }
    catch {
        return ''
    }
}

function Test-OrdinalPathEqual {
    param([string]$Actual, [string]$Expected)
    return [string]::Equals($Actual, $Expected, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-ExactPropertySet {
    param(
        [object]$Value,
        [string[]]$Expected
    )
    if ($null -eq $Value) {
        return $false
    }
    $actual = @($Value.PSObject.Properties.Name)
    if ($actual.Count -ne $Expected.Count) {
        return $false
    }
    foreach ($actualName in $actual) {
        $matched = $false
        foreach ($expectedName in $Expected) {
            if ([string]::Equals(
                    [string]$actualName,
                    [string]$expectedName,
                    [System.StringComparison]::Ordinal
                )) {
                $matched = $true
                break
            }
        }
        if (-not $matched) {
            return $false
        }
    }
    return $true
}

function Test-JsonInteger {
    param([object]$Value)
    return ($Value -is [byte] -or
        $Value -is [sbyte] -or
        $Value -is [int16] -or
        $Value -is [uint16] -or
        $Value -is [int32] -or
        $Value -is [uint32] -or
        $Value -is [int64] -or
        $Value -is [uint64]) -and [decimal]$Value -ge 0
}

function ConvertTo-StrictReceiptTimestamp {
    param([object]$Value)
    if ($Value -is [DateTimeOffset]) {
        return ([DateTimeOffset]$Value).ToUniversalTime()
    }
    if ($Value -is [DateTime]) {
        if (([DateTime]$Value).Kind -eq [DateTimeKind]::Unspecified) {
            return $null
        }
        return ([DateTimeOffset]([DateTime]$Value)).ToUniversalTime()
    }
    if ($Value -isnot [string] -or
        [string]::IsNullOrWhiteSpace([string]$Value) -or
        [string]$Value -notmatch '(Z|[+-][0-9]{2}:[0-9]{2})$') {
        return $null
    }
    $parsed = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse(
            [string]$Value,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::None,
            [ref]$parsed
        )) {
        return $null
    }
    return $parsed.ToUniversalTime()
}

function Test-CanonicalUtcTimestamp {
    param(
        [string]$Text,
        [object]$Value
    )
    if ($null -eq $Value) {
        return $false
    }
    return [string]::Equals(
        $Text,
        ([DateTimeOffset]$Value).ToUniversalTime().ToString('o'),
        [System.StringComparison]::Ordinal
    )
}

function Get-LowerSha256 {
    param([string]$LiteralPath)
    try {
        return (Get-FileHash -LiteralPath $LiteralPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    }
    catch {
        return ''
    }
}

function Get-TrustedBundleSids {
    return @(
        (Get-CurrentIdentitySid),
        'S-1-5-18',
        'S-1-5-32-544'
    )
}

function Get-WriteLikeRightsMask {
    # Do not include composite Read/Write/Modify/FullControl values here.  Those
    # values contain read bits and made the former audit classify read-only ACLs
    # as writable.  This is the exact set of mutation/delete/ACL-owner bits.
    return [System.Security.AccessControl.FileSystemRights]::WriteData -bor
        [System.Security.AccessControl.FileSystemRights]::AppendData -bor
        [System.Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
        [System.Security.AccessControl.FileSystemRights]::WriteAttributes -bor
        [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [System.Security.AccessControl.FileSystemRights]::Delete -bor
        [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [System.Security.AccessControl.FileSystemRights]::TakeOwnership
}

function Test-PathInsideBoundary {
    param(
        [string]$LiteralPath,
        [string]$BoundaryPath
    )
    try {
        $candidate = [System.IO.Path]::GetFullPath($LiteralPath).TrimEnd('\')
        $boundary = [System.IO.Path]::GetFullPath($BoundaryPath).TrimEnd('\')
        return [string]::Equals(
                $candidate,
                $boundary,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or $candidate.StartsWith(
                $boundary + [System.IO.Path]::DirectorySeparatorChar,
                [System.StringComparison]::OrdinalIgnoreCase
            )
    }
    catch {
        return $false
    }
}

function Test-TrustedAclAtPath {
    param(
        [string]$LiteralPath,
        [switch]$RequireProtectedExact
    )
    $trustedSids = @(Get-TrustedBundleSids)
    $writeLikeRights = Get-WriteLikeRightsMask
    try {
        $item = Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            return $false
        }
        $acl = Get-Acl -LiteralPath $LiteralPath -ErrorAction Stop
        $ownerSid = Resolve-IdentitySid ([string]$acl.Owner)
        if ([string]::IsNullOrWhiteSpace($ownerSid) -or $trustedSids -notcontains $ownerSid) {
            return $false
        }
        if ($RequireProtectedExact -and -not [bool]$acl.AreAccessRulesProtected) {
            return $false
        }
        $exactAllowSids = [System.Collections.Generic.HashSet[string]]::new(
            [System.StringComparer]::OrdinalIgnoreCase
        )
        foreach ($rule in @($acl.Access)) {
            $ruleSid = Resolve-IdentitySid ([string]$rule.IdentityReference)
            $isAllow = [string]::Equals(
                [string]$rule.AccessControlType,
                'Allow',
                [System.StringComparison]::OrdinalIgnoreCase
            )
            $rights = [System.Security.AccessControl.FileSystemRights]$rule.FileSystemRights
            if ($RequireProtectedExact) {
                if ([string]::IsNullOrWhiteSpace($ruleSid) -or
                    $trustedSids -notcontains $ruleSid -or
                    [bool]$rule.IsInherited) {
                    return $false
                }
                if ($isAllow -and
                    (($rights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -ne
                        [System.Security.AccessControl.FileSystemRights]::FullControl)) {
                    return $false
                }
                if ($isAllow) {
                    [void]$exactAllowSids.Add($ruleSid)
                }
                continue
            }
            if ($isAllow -and ($rights -band $writeLikeRights) -ne 0 -and
                ([string]::IsNullOrWhiteSpace($ruleSid) -or $trustedSids -notcontains $ruleSid)) {
                return $false
            }
        }
        if ($RequireProtectedExact) {
            foreach ($trustedSid in $trustedSids) {
                if (-not $exactAllowSids.Contains($trustedSid)) {
                    return $false
                }
            }
        }
        return $true
    }
    catch {
        return $false
    }
}

function Test-TrustedPathAcl {
    param(
        [string]$LiteralPath,
        [string]$BoundaryPath = $bundleBoundary
    )
    $script:LastTrustedPathValidation = 'path_acl_not_checked'
    try {
        $currentPath = [System.IO.Path]::GetFullPath($LiteralPath).TrimEnd('\')
        $boundary = [System.IO.Path]::GetFullPath($BoundaryPath).TrimEnd('\')
        $script:LastTrustedPathValidation = 'path_acl_paths_resolved'
        if (-not (Test-PathInsideBoundary $currentPath $boundary)) {
            $script:LastTrustedPathValidation = 'path_acl_outside_boundary'
            return $false
        }
        $pathDepth = 0
        while ($true) {
            $script:LastTrustedPathValidation = "path_acl_checking_$pathDepth"
            if (-not (Test-TrustedAclAtPath $currentPath)) {
                $script:LastTrustedPathValidation = "path_acl_invalid_$pathDepth"
                return $false
            }
            if (Test-OrdinalPathEqual $currentPath $boundary) {
                $script:LastTrustedPathValidation = 'path_acl_valid'
                return $true
            }
            $script:LastTrustedPathValidation = "path_acl_parent_$pathDepth"
            $parentInfo = [System.IO.Directory]::GetParent($currentPath)
            $parentPath = if ($null -ne $parentInfo) { [string]$parentInfo.FullName } else { '' }
            if ([string]::IsNullOrWhiteSpace($parentPath) -or
                -not (Test-PathInsideBoundary $parentPath $boundary) -or
                (Test-OrdinalPathEqual $parentPath $currentPath)) {
                $script:LastTrustedPathValidation = 'path_acl_parent_invalid'
                return $false
            }
            $currentPath = $parentPath.TrimEnd('\')
            $pathDepth += 1
        }
    }
    catch {
        $script:LastTrustedPathValidation += '_failed_' + $_.Exception.GetType().Name
        return $false
    }
}

function Set-ProtectedBundlePathAcl {
    param([string]$LiteralPath)
    $item = Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
    $currentSid = [System.Security.Principal.SecurityIdentifier]::new((Get-CurrentIdentitySid))
    $trustedIdentities = @(
        $currentSid,
        [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
        [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
    )
    if ($item.PSIsContainer) {
        $security = [System.Security.AccessControl.DirectorySecurity]::new()
        $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else {
        $security = [System.Security.AccessControl.FileSecurity]::new()
        $inheritance = [System.Security.AccessControl.InheritanceFlags]::None
    }
    $security.SetOwner($currentSid)
    $security.SetAccessRuleProtection($true, $false)
    foreach ($trustedIdentity in $trustedIdentities) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $trustedIdentity,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        [void]$security.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $LiteralPath -AclObject $security -ErrorAction Stop
}

function Set-ProtectedBundleTreeAcl {
    param([string]$BundleRoot)
    Set-ProtectedBundlePathAcl $BundleRoot
    foreach ($item in @(Get-ChildItem -LiteralPath $BundleRoot -Force -Recurse -ErrorAction Stop)) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Bundle staging contains a reparse point.'
        }
        Set-ProtectedBundlePathAcl ([string]$item.FullName)
    }
}

function Test-ProtectedBundleTreeAcl {
    param([string]$BundleRoot)
    $script:LastBundleAclValidation = 'bundle_acl_not_checked'
    try {
        if (-not (Test-TrustedPathAcl $BundleRoot $bundleBoundary)) {
            $script:LastBundleAclValidation = $script:LastTrustedPathValidation
            return $false
        }
        $bundleItems = @(
            Get-Item -LiteralPath $BundleRoot -Force -ErrorAction Stop
            Get-ChildItem -LiteralPath $BundleRoot -Force -Recurse -ErrorAction Stop
        )
        foreach ($item in $bundleItems) {
            if (-not (Test-TrustedAclAtPath ([string]$item.FullName) -RequireProtectedExact)) {
                $script:LastBundleAclValidation = 'bundle_acl_tree_invalid'
                return $false
            }
        }
        $script:LastBundleAclValidation = 'bundle_acl_valid'
        return $true
    }
    catch {
        $script:LastBundleAclValidation = 'bundle_acl_check_failed'
        return $false
    }
}

function Test-SafeBundleRelativePath {
    param([object]$Value)
    if ($Value -isnot [string] -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return $false
    }
    $path = [string]$Value
    if ($path.Contains('\') -or $path.Contains(':') -or $path.StartsWith('/') -or
        $path.IndexOf([char]0) -ge 0) {
        return $false
    }
    $parts = @($path.Split('/'))
    if (($parts.Count -lt 2 -and $path -ne 'app') -or
        $parts[0] -notin @('python', 'app')) {
        return $false
    }
    return @($parts | Where-Object {
            [string]::IsNullOrWhiteSpace($_) -or $_ -in @('.', '..')
        }).Count -eq 0
}

function Resolve-BundleChildPath {
    param(
        [string]$BundleRoot,
        [string]$RelativePath
    )
    if (-not (Test-SafeBundleRelativePath $RelativePath)) {
        throw 'Bundle manifest contains an unsafe relative path.'
    }
    $child = [System.IO.Path]::GetFullPath((Join-Path $BundleRoot $RelativePath.Replace('/', '\')))
    if (-not (Test-PathInsideBoundary $child $BundleRoot) -or
        (Test-OrdinalPathEqual $child $BundleRoot)) {
        throw 'Bundle manifest path escapes the content root.'
    }
    return $child
}

function Get-BundleContentId {
    param([object[]]$Records)
    [string[]]$canonicalLines = @($Records | ForEach-Object {
            [string]$_.relative_path + [char]0 +
                ([long]$_.size).ToString([System.Globalization.CultureInfo]::InvariantCulture) +
                [char]0 + [string]$_.sha256
        })
    [System.Array]::Sort($canonicalLines, [System.StringComparer]::Ordinal)
    $canonical = [string]::Join("`n", $canonicalLines) + "`n"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($canonical)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-OrderedBundleRecords {
    param([object[]]$Records)
    $byPath = @{}
    [string[]]$paths = @()
    foreach ($record in $Records) {
        $path = [string]$record.relative_path
        if ($byPath.ContainsKey($path)) {
            throw 'Bundle source plan contains duplicate relative paths.'
        }
        $byPath[$path] = $record
        $paths += $path
    }
    [System.Array]::Sort($paths, [System.StringComparer]::Ordinal)
    foreach ($path in $paths) {
        $record = $byPath[$path]
        [pscustomobject][ordered]@{
            relative_path = [string]$record.relative_path
            size = [long]$record.size
            sha256 = [string]$record.sha256
        }
    }
}

function Get-SourceBundlePlan {
    if (-not (Test-Path -LiteralPath $bundleLockPath -PathType Leaf)) {
        throw 'The adopted consumer bundle lock is missing.'
    }
    $lockItem = Get-Item -LiteralPath $bundleLockPath -Force -ErrorAction Stop
    if (($lockItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $lockItem.Length -lt 1 -or $lockItem.Length -gt 16MB) {
        throw 'The adopted consumer bundle lock carrier is unsafe.'
    }
    if (-not [string]::Equals(
            (Get-LowerSha256 $bundleLockPath),
            $expectedBundleLockSha256,
            [System.StringComparison]::Ordinal
        )) {
        throw 'The adopted consumer bundle lock hash is invalid.'
    }
    $lockJson = Get-Content -LiteralPath $bundleLockPath -Raw -Encoding UTF8
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) {
        $bundleLock = $lockJson | ConvertFrom-Json -DateKind String -ErrorAction Stop
    } else {
        $bundleLock = $lockJson | ConvertFrom-Json -ErrorAction Stop
    }
    if (-not (Test-ExactPropertySet $bundleLock @(
                'schema_version', 'authority', 'source_identity', 'content_id', 'files'
            )) -or
        -not [string]::Equals(
            [string]$bundleLock.schema_version,
            $bundleLockSchema,
            [System.StringComparison]::Ordinal
        ) -or $bundleLock.authority -isnot [bool] -or $bundleLock.authority -ne $false -or
        $bundleLock.source_identity -isnot [System.Management.Automation.PSCustomObject] -or
        -not (Test-ExactPropertySet $bundleLock.source_identity @(
                'application', 'release', 'python_distribution'
            )) -or
        -not [string]::Equals(
            [string]$bundleLock.source_identity.application,
            'xinao-s-context-rollout-consumer',
            [System.StringComparison]::Ordinal
        ) -or
        -not [string]::Equals(
            [string]$bundleLock.source_identity.release,
            '2026-08-14',
            [System.StringComparison]::Ordinal
        ) -or
        -not [string]::Equals(
            [string]$bundleLock.source_identity.python_distribution,
            'cpython-3.13.14-official',
            [System.StringComparison]::Ordinal
        ) -or $bundleLock.content_id -isnot [string] -or
        -not [string]::Equals(
            [string]$bundleLock.content_id,
            $expectedBundleContentId,
            [System.StringComparison]::Ordinal
        ) -or $bundleLock.files -isnot [System.Array] -or
        @($bundleLock.files).Count -ne $expectedBundleFileCount) {
        throw 'The adopted consumer bundle lock schema is invalid.'
    }

    $lockedByPath = @{}
    $lockedRecords = [System.Collections.Generic.List[object]]::new()
    $lockedPaths = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $previousPath = ''
    foreach ($record in @($bundleLock.files)) {
        if ($record -isnot [System.Management.Automation.PSCustomObject] -or
            -not (Test-ExactPropertySet $record @('relative_path', 'size', 'sha256')) -or
            -not (Test-SafeBundleRelativePath $record.relative_path) -or
            -not (Test-JsonInteger $record.size) -or
            $record.sha256 -isnot [string] -or [string]$record.sha256 -notmatch '^[0-9a-f]{64}$') {
            throw 'The adopted consumer bundle lock contains an invalid file record.'
        }
        $relativePath = [string]$record.relative_path
        if (-not [string]::IsNullOrEmpty($previousPath) -and
            [string]::CompareOrdinal($previousPath, $relativePath) -ge 0) {
            throw 'The adopted consumer bundle lock file records are not strictly sorted.'
        }
        if (-not $lockedPaths.Add($relativePath)) {
            throw 'The adopted consumer bundle lock contains a duplicate file path.'
        }
        $lockedRecord = [pscustomobject][ordered]@{
            relative_path = $relativePath
            size = [long]$record.size
            sha256 = [string]$record.sha256
        }
        $lockedByPath[$relativePath] = $lockedRecord
        $lockedRecords.Add($lockedRecord)
        $previousPath = $relativePath
    }
    foreach ($requiredPath in $requiredLockedFilePaths) {
        if (-not $lockedByPath.ContainsKey($requiredPath)) {
            throw 'The adopted consumer bundle lock is missing a required executable or module.'
        }
        if ([long]$lockedByPath[$requiredPath].size -lt 1) {
            throw 'The adopted consumer bundle lock required executable or module is invalid.'
        }
    }
    foreach ($directHashEntry in $directLockedFileHashes.GetEnumerator()) {
        if (-not $lockedByPath.ContainsKey([string]$directHashEntry.Key) -or
            -not [string]::Equals(
                [string]$lockedByPath[[string]$directHashEntry.Key].sha256,
                [string]$directHashEntry.Value,
                [System.StringComparison]::Ordinal
            )) {
            throw 'The adopted consumer bundle lock direct release pin is invalid.'
        }
    }
    if (-not [string]::Equals(
            (Get-BundleContentId @($lockedRecords)),
            [string]$bundleLock.content_id,
            [System.StringComparison]::Ordinal
        )) {
        throw 'The adopted consumer bundle lock content identity is invalid.'
    }

    if (-not (Test-Path -LiteralPath $sourcePythonRoot -PathType Container)) {
        throw 'Official Python distribution is missing.'
    }
    $pythonRootFull = [System.IO.Path]::GetFullPath($sourcePythonRoot).TrimEnd('\')
    $pythonRootItem = Get-Item -LiteralPath $pythonRootFull -Force -ErrorAction Stop
    if (($pythonRootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Official Python distribution root is a reparse point.'
    }
    $sourceByPath = @{}
    foreach ($item in @(Get-ChildItem -LiteralPath $pythonRootFull -Force -Recurse -ErrorAction Stop)) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Official Python distribution contains a reparse point.'
        }
        if ($item.PSIsContainer) {
            continue
        }
        $relative = ([string]$item.FullName).Substring($pythonRootFull.Length).TrimStart('\')
        $segments = @($relative.Split('\'))
        if ($segments -contains '__pycache__' -or
            [string]::Equals($item.Extension, '.pyc', [System.StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $relativePath = 'python/' + $relative.Replace('\', '/')
        if ($sourceByPath.ContainsKey($relativePath)) {
            throw 'Official Python distribution contains a duplicate source path.'
        }
        $sourceByPath[$relativePath] = [string]$item.FullName
    }
    $appSourceMap = [ordered]@{
        'app/scripts/context_rollout_consumer.py' = $sourceConsumerScript
        'app/scripts/Invoke-SPresentationDelivery.ps1' = Join-Path $sourceRepositoryRoot 'scripts\Invoke-SPresentationDelivery.ps1'
        'app/services/__init__.py' = Join-Path $sourceRepositoryRoot 'services\__init__.py'
        'app/services/agent_runtime/__init__.py' = Join-Path $sourceRepositoryRoot 'services\agent_runtime\__init__.py'
        'app/services/agent_runtime/context_fabric.py' = Join-Path $sourceRepositoryRoot 'services\agent_runtime\context_fabric.py'
        'app/services/agent_runtime/context_runtime_completion.py' = Join-Path $sourceRepositoryRoot 'services\agent_runtime\context_runtime_completion.py'
        'app/services/agent_runtime/presentation_reducer.py' = Join-Path $sourceRepositoryRoot 'services\agent_runtime\presentation_reducer.py'
        'app/services/agent_runtime/presentation_observer.py' = Join-Path $sourceRepositoryRoot 'services\agent_runtime\presentation_observer.py'
        'app/services/agent_runtime/presentation_delivery.py' = Join-Path $sourceRepositoryRoot 'services\agent_runtime\presentation_delivery.py'
        'app/services/agent_runtime/presentation_lock.py' = Join-Path $sourceRepositoryRoot 'services\agent_runtime\presentation_lock.py'
    }
    foreach ($entry in $appSourceMap.GetEnumerator()) {
        if (-not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) {
            throw 'A required consumer application source file is missing.'
        }
        $item = Get-Item -LiteralPath $entry.Value -Force -ErrorAction Stop
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'A required consumer application source file is a reparse point.'
        }
        $sourceByPath[[string]$entry.Key] = [string]$item.FullName
    }
    if ($sourceByPath.Count -ne $lockedRecords.Count) {
        throw 'The source bundle file set does not match the adopted release lock.'
    }

    $sourcePlan = [System.Collections.Generic.List[object]]::new()
    foreach ($lockedRecord in $lockedRecords) {
        $relativePath = [string]$lockedRecord.relative_path
        if (-not $sourceByPath.ContainsKey($relativePath)) {
            throw 'The source bundle is missing a file from the adopted release lock.'
        }
        $sourcePath = [string]$sourceByPath[$relativePath]
        $item = Get-Item -LiteralPath $sourcePath -Force -ErrorAction Stop
        if ([long]$item.Length -ne [long]$lockedRecord.size -or
            -not [string]::Equals(
                (Get-LowerSha256 $sourcePath),
                [string]$lockedRecord.sha256,
                [System.StringComparison]::Ordinal
            )) {
            throw 'A source bundle file does not match the adopted release lock.'
        }
        $sourcePlan.Add([pscustomobject][ordered]@{
                relative_path = $relativePath
                source_path = $sourcePath
                size = [long]$lockedRecord.size
                sha256 = [string]$lockedRecord.sha256
            })
    }
    return @($sourcePlan)
}

function New-BundleManifestBytes {
    param(
        [string]$ContentId,
        [object[]]$Records
    )
    $manifest = [ordered]@{
        schema_version = $bundleManifestSchema
        content_id = $ContentId
        files = @(Get-OrderedBundleRecords $Records)
        authority = $false
    }
    $json = $manifest | ConvertTo-Json -Depth 6 -Compress
    return [System.Text.UTF8Encoding]::new($false).GetBytes($json + "`n")
}

function Get-BytesSha256 {
    param([byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Test-BundlePayload {
    param(
        [string]$BundleRoot,
        [string]$ExpectedContentId,
        [string]$ExpectedManifestSha256,
        [string[]]$RequiredPaths = $requiredLockedFilePaths,
        [Nullable[int]]$ExpectedFileCount = $null
    )
    $result = [ordered]@{
        valid = $false
        validation = 'not_validated'
        files_valid = $false
        payload_hash_valid = $false
        payload_acl_valid = $false
        content_id = $ExpectedContentId
        manifest_sha256 = ''
        python_path = ''
        action_python_path = ''
        consumer_script = ''
        working_directory = ''
        arguments = ''
    }
    try {
        if ($ExpectedContentId -notmatch '^[0-9a-f]{64}$' -or
            $ExpectedManifestSha256 -notmatch '^[0-9a-f]{64}$' -or
            -not (Test-PathInsideBoundary $BundleRoot $bundleBase) -or
            -not (Test-Path -LiteralPath $BundleRoot -PathType Container)) {
            return $result
        }
        $result.validation = 'carrier_valid'
        $manifestPath = Join-Path $BundleRoot $bundleManifestName
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            return $result
        }
        $manifestItem = Get-Item -LiteralPath $manifestPath -Force -ErrorAction Stop
        if (($manifestItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
            $manifestItem.Length -lt 1 -or $manifestItem.Length -gt 16MB) {
            return $result
        }
        $manifestSha256 = Get-LowerSha256 $manifestPath
        $result.manifest_sha256 = $manifestSha256
        if (-not [string]::Equals(
                $manifestSha256,
                $ExpectedManifestSha256,
                [System.StringComparison]::Ordinal
            )) {
            return $result
        }
        $result.validation = 'manifest_hash_valid'
        $manifestJson = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
        if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) {
            $manifest = $manifestJson | ConvertFrom-Json -DateKind String -ErrorAction Stop
        } else {
            $manifest = $manifestJson | ConvertFrom-Json -ErrorAction Stop
        }
        if (-not (Test-ExactPropertySet $manifest @('schema_version', 'content_id', 'files', 'authority')) -or
            -not [string]::Equals([string]$manifest.schema_version, $bundleManifestSchema, [System.StringComparison]::Ordinal) -or
            $manifest.content_id -isnot [string] -or
            -not [string]::Equals([string]$manifest.content_id, $ExpectedContentId, [System.StringComparison]::Ordinal) -or
            $manifest.files -isnot [System.Array] -or @($manifest.files).Count -lt 6 -or
            @($manifest.files).Count -gt 20000 -or $manifest.authority -isnot [bool] -or
            $manifest.authority -ne $false -or
            ($null -ne $ExpectedFileCount -and
                @($manifest.files).Count -ne [int]$ExpectedFileCount)) {
            return $result
        }
        $result.validation = 'manifest_schema_valid'
        $manifestRecords = [System.Collections.Generic.List[object]]::new()
        $manifestPaths = [System.Collections.Generic.HashSet[string]]::new(
            [System.StringComparer]::OrdinalIgnoreCase
        )
        foreach ($record in @($manifest.files)) {
            if ($record -isnot [System.Management.Automation.PSCustomObject] -or
                -not (Test-ExactPropertySet $record @('relative_path', 'size', 'sha256')) -or
                -not (Test-SafeBundleRelativePath $record.relative_path) -or
                -not (Test-JsonInteger $record.size) -or
                $record.sha256 -isnot [string] -or [string]$record.sha256 -notmatch '^[0-9a-f]{64}$' -or
                -not $manifestPaths.Add([string]$record.relative_path)) {
                return $result
            }
            $manifestRecords.Add([pscustomobject]@{
                    relative_path = [string]$record.relative_path
                    size = [long]$record.size
                    sha256 = [string]$record.sha256
                })
        }
        $result.validation = 'manifest_records_valid'
        if ($null -eq $RequiredPaths -or @($RequiredPaths).Count -lt 1 -or
            @($RequiredPaths | Where-Object { -not $manifestPaths.Contains($_) }).Count -ne 0 -or
            -not [string]::Equals(
                (Get-BundleContentId @($manifestRecords)),
                $ExpectedContentId,
                [System.StringComparison]::Ordinal
            )) {
            return $result
        }
        $result.validation = 'content_id_valid'
        $enumerationRoot = ([string](Get-Item -LiteralPath $BundleRoot -Force -ErrorAction Stop).FullName).TrimEnd('\')
        $actualPayloadPaths = [System.Collections.Generic.HashSet[string]]::new(
            [System.StringComparer]::OrdinalIgnoreCase
        )
        foreach ($actualFile in @(Get-ChildItem -LiteralPath $BundleRoot -Force -Recurse -File -ErrorAction Stop)) {
            $actualFullName = [string]$actualFile.FullName
            if (-not $actualFullName.StartsWith(
                    $enumerationRoot + '\',
                    [System.StringComparison]::OrdinalIgnoreCase
                )) {
                return $result
            }
            $actualRelativePath = $actualFullName.Substring($enumerationRoot.Length).TrimStart('\').Replace('\', '/')
            if ([string]::Equals(
                    $actualRelativePath,
                    $bundleManifestName,
                    [System.StringComparison]::OrdinalIgnoreCase
                )) {
                continue
            }
            if (-not $manifestPaths.Contains($actualRelativePath) -or
                -not $actualPayloadPaths.Add($actualRelativePath)) {
                return $result
            }
        }
        if ($actualPayloadPaths.Count -ne $manifestRecords.Count) {
            return $result
        }
        $result.validation = 'file_set_valid'
        foreach ($record in $manifestRecords) {
            $filePath = Resolve-BundleChildPath $BundleRoot $record.relative_path
            if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
                return $result
            }
            $item = Get-Item -LiteralPath $filePath -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
                [long]$item.Length -ne [long]$record.size -or
                -not [string]::Equals(
                    (Get-LowerSha256 $filePath),
                    [string]$record.sha256,
                    [System.StringComparison]::Ordinal
                )) {
                return $result
            }
        }
        $result.validation = 'file_hashes_valid'
        $bundlePythonPath = Resolve-BundleChildPath $BundleRoot 'python/python.exe'
        $bundleActionPythonPath = Resolve-BundleChildPath $BundleRoot 'python/pythonw.exe'
        if (-not [string]::Equals(
                (Get-LowerSha256 $bundlePythonPath),
                $officialPythonSha256,
                [System.StringComparison]::Ordinal
            )) {
            return $result
        }
        if (-not [string]::Equals(
                (Get-LowerSha256 $bundleActionPythonPath),
                $officialPythonwSha256,
                [System.StringComparison]::Ordinal
            )) {
            return $result
        }
        $result.validation = 'official_python_valid'
        $result.files_valid = $true
        $result.payload_hash_valid = $true
        $result.payload_acl_valid = Test-ProtectedBundleTreeAcl $BundleRoot
        $result.python_path = $bundlePythonPath
        $result.action_python_path = $bundleActionPythonPath
        $result.consumer_script = Resolve-BundleChildPath $BundleRoot 'app/scripts/context_rollout_consumer.py'
        $result.working_directory = Resolve-BundleChildPath $BundleRoot 'app'
        $result.arguments = '-I -B "' + $result.consumer_script + '"'
        $result.valid = $result.files_valid -and $result.payload_hash_valid -and $result.payload_acl_valid
        $result.validation = if ($result.valid) { 'bundle_valid' } else { $script:LastBundleAclValidation }
        return $result
    }
    catch {
        return $result
    }
}

function Ensure-ProtectedBundleBase {
    if (-not (Test-Path -LiteralPath $bundleBoundary -PathType Container) -or
        -not (Test-TrustedPathAcl $bundleBoundary $bundleBoundary)) {
        throw 'The current-user LOCALAPPDATA boundary is not trustworthy.'
    }
    $xinaoRoot = Join-Path $bundleBoundary 'XINAO'
    if (-not (Test-Path -LiteralPath $xinaoRoot -PathType Container)) {
        [void][System.IO.Directory]::CreateDirectory($xinaoRoot)
        Set-ProtectedBundlePathAcl $xinaoRoot
    } elseif (-not (Test-TrustedPathAcl $xinaoRoot $bundleBoundary)) {
        throw 'The XINAO application-data ancestor is not trustworthy.'
    }
    if (-not (Test-Path -LiteralPath $bundleBase -PathType Container)) {
        [void][System.IO.Directory]::CreateDirectory($bundleBase)
        Set-ProtectedBundlePathAcl $bundleBase
    }
    if (-not (Test-TrustedAclAtPath $bundleBase -RequireProtectedExact) -or
        -not (Test-TrustedPathAcl $bundleBase $bundleBoundary)) {
        throw 'The consumer bundle base is not protected.'
    }
}

function Remove-OwnedBundleStaging {
    param(
        [string]$StagingPath,
        [string]$ContentId,
        [string]$RegistrationToken
    )
    $expectedName = ".$ContentId.staging.$RegistrationToken"
    $stagingParent = [System.IO.Path]::GetDirectoryName(
        [System.IO.Path]::GetFullPath($StagingPath)
    )
    if (-not (Test-OrdinalPathEqual $stagingParent $bundleBase) -or
        -not [string]::Equals(
            [System.IO.Path]::GetFileName($StagingPath),
            $expectedName,
            [System.StringComparison]::Ordinal
        )) {
        throw 'Refusing cleanup outside this invocation staging path.'
    }
    if (Test-Path -LiteralPath $StagingPath) {
        $stagingItems = @(
            Get-Item -LiteralPath $StagingPath -Force -ErrorAction Stop
            Get-ChildItem -LiteralPath $StagingPath -Force -Recurse -ErrorAction Stop
        )
        foreach ($item in $stagingItems) {
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Refusing cleanup of a staging tree containing a reparse point.'
            }
        }
        Remove-Item -LiteralPath $StagingPath -Recurse -Force -ErrorAction Stop
    }
}

function New-ProtectedConsumerBundle {
    param(
        [object[]]$SourcePlan,
        [string]$RegistrationToken
    )
    Ensure-ProtectedBundleBase
    $publicRecords = @(Get-OrderedBundleRecords $SourcePlan)
    $contentId = Get-BundleContentId $publicRecords
    $manifestBytes = New-BundleManifestBytes $contentId $publicRecords
    $manifestSha256 = Get-BytesSha256 $manifestBytes
    $finalRoot = Join-Path $bundleBase $contentId
    $stagingRoot = Join-Path $bundleBase ".$contentId.staging.$RegistrationToken"
    if (Test-Path -LiteralPath $finalRoot) {
        $existingValidation = Test-BundlePayload $finalRoot $contentId $manifestSha256
        if (-not $existingValidation.valid) {
            throw 'An existing content-addressed consumer bundle is invalid.'
        }
        return [pscustomobject]@{
            content_id = $contentId
            manifest_sha256 = $manifestSha256
            bundle_root = $finalRoot
            validation = $existingValidation
            staging_path = ''
        }
    }
    if (Test-Path -LiteralPath $stagingRoot) {
        throw 'This invocation staging path unexpectedly already exists.'
    }
    [void][System.IO.Directory]::CreateDirectory($stagingRoot)
    try {
        Set-ProtectedBundlePathAcl $stagingRoot
        foreach ($record in $SourcePlan) {
            $destination = Resolve-BundleChildPath $stagingRoot ([string]$record.relative_path)
            $destinationParent = [System.IO.Path]::GetDirectoryName(
                [System.IO.Path]::GetFullPath($destination)
            )
            [void][System.IO.Directory]::CreateDirectory($destinationParent)
            Copy-Item -LiteralPath ([string]$record.source_path) -Destination $destination -Force -ErrorAction Stop
        }
        [System.IO.File]::WriteAllBytes((Join-Path $stagingRoot $bundleManifestName), $manifestBytes)
        Set-ProtectedBundleTreeAcl $stagingRoot
        $stagingValidation = Test-BundlePayload $stagingRoot $contentId $manifestSha256
        if (-not $stagingValidation.valid) {
            throw 'Protected consumer bundle staging verification failed.'
        }
        try {
            [System.IO.Directory]::Move($stagingRoot, $finalRoot)
        }
        catch [System.IO.IOException] {
            if (-not (Test-Path -LiteralPath $finalRoot -PathType Container)) {
                throw
            }
            Remove-OwnedBundleStaging $stagingRoot $contentId $RegistrationToken
        }
        $finalValidation = Test-BundlePayload $finalRoot $contentId $manifestSha256
        if (-not $finalValidation.valid) {
            throw 'Protected consumer bundle final verification failed.'
        }
        return [pscustomobject]@{
            content_id = $contentId
            manifest_sha256 = $manifestSha256
            bundle_root = $finalRoot
            validation = $finalValidation
            staging_path = ''
        }
    }
    catch {
        $bundleFailure = $_
        if (Test-Path -LiteralPath $stagingRoot) {
            Remove-OwnedBundleStaging $stagingRoot $contentId $RegistrationToken
        }
        throw $bundleFailure
    }
}

function New-ConsumerTaskCandidate {
    param(
        [object]$Bundle,
        [string]$RegistrationToken,
        [int]$IntervalMinutes,
        [ValidateRange(1, 10)]
        [int]$StartDelayMinutes = 1
    )
    if ($RegistrationToken -notmatch '^[0-9a-f]{32}$') {
        throw 'Consumer task registration token is invalid.'
    }
    $identity = Get-CurrentIdentityName
    $registeredAt = [DateTimeOffset]::UtcNow
    $receiptNotBefore = [DateTimeOffset]::new(
        $registeredAt.AddMinutes($StartDelayMinutes).Ticks -
            ($registeredAt.AddMinutes($StartDelayMinutes).Ticks % [TimeSpan]::TicksPerSecond),
        [TimeSpan]::Zero
    )
    $description = "$descriptionPrefix$RegistrationToken;registered_at=$($registeredAt.ToString('o'));receipt_not_before=$($receiptNotBefore.ToString('o'));content_id=$($Bundle.content_id);manifest_sha256=$($Bundle.manifest_sha256)"
    $action = New-ScheduledTaskAction `
        -Execute $Bundle.validation.action_python_path `
        -Argument $Bundle.validation.arguments `
        -WorkingDirectory $Bundle.validation.working_directory
    $trigger = New-ScheduledTaskTrigger `
        -Once `
        -At $receiptNotBefore.LocalDateTime `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $trigger.Repetition.StopAtDurationEnd = $false
    $settings = New-ScheduledTaskSettingsSet `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    $principal = New-ScheduledTaskPrincipal `
        -UserId $identity `
        -LogonType Interactive `
        -RunLevel Limited
    $definition = New-ScheduledTask `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $description
    return [pscustomobject][ordered]@{
        description = $description
        registered_at = $registeredAt.ToString('o')
        receipt_not_before = $receiptNotBefore.ToString('o')
        definition = $definition
    }
}

function Get-NormalizedManagedPredecessorXmlSha256 {
    param(
        [string]$TaskXml,
        [object]$BundleValidation
    )
    if ([string]::IsNullOrWhiteSpace($TaskXml)) {
        return ''
    }
    $consolePath = [string]$BundleValidation.python_path
    $windowlessPath = [string]$BundleValidation.action_python_path
    $consoleCount = [regex]::Matches(
        $TaskXml,
        [regex]::Escape($consolePath),
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    ).Count
    $windowlessCount = [regex]::Matches(
        $TaskXml,
        [regex]::Escape($windowlessPath),
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    ).Count
    if ($consoleCount + $windowlessCount -ne 1) {
        return ''
    }
    $actionToken = '{XINAO_MANAGED_PYTHON_ACTION}'
    $normalized = $TaskXml.Replace($consolePath, $actionToken).Replace(
        $windowlessPath,
        $actionToken
    )
    return Get-BytesSha256 ([System.Text.UTF8Encoding]::new($false).GetBytes($normalized))
}

function Get-ManagedUpgradeSource {

    $result = [ordered]@{
        valid = $false
        validation = 'not_validated'
        task_xml = ''
        task_description = ''
        action_variant = ''
        content_id = ''
        manifest_sha256 = ''
    }
    $task = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        $result.validation = 'task_absent'
        return [pscustomobject]$result
    }

    $description = [string]$task.Description
    $descriptionPattern = '^' + [regex]::Escape($descriptionPrefix) +
        '(?<token>[0-9a-f]{32});registered_at=(?<registered>[^;]+);receipt_not_before=' +
        '(?<receipt_not_before>[^;]+);content_id=' +
        '(?<content>[0-9a-f]{64});manifest_sha256=(?<manifest>[0-9a-f]{64})$'
    $descriptionMatch = [regex]::Match($description, $descriptionPattern)
    if (-not $descriptionMatch.Success -or
        -not [string]::Equals(
            $descriptionMatch.Groups['content'].Value,
            $managedUpgradeSourceContentId,
            [System.StringComparison]::Ordinal
        ) -or
        -not [string]::Equals(
            $descriptionMatch.Groups['manifest'].Value,
            $managedUpgradeSourceManifestSha256,
            [System.StringComparison]::Ordinal
        )) {
        $result.validation = 'predecessor_description_invalid'
        return [pscustomobject]$result
    }
    $bundleRoot = Join-Path $bundleBase $managedUpgradeSourceContentId
    $bundleValidation = Test-BundlePayload `
        $bundleRoot `
        $managedUpgradeSourceContentId `
        $managedUpgradeSourceManifestSha256 `
        -RequiredPaths $managedUpgradeSourceRequiredPaths `
        -ExpectedFileCount $managedUpgradeSourceFileCount
    if (-not $bundleValidation.valid) {
        $result.validation = 'predecessor_bundle_invalid'
        return [pscustomobject]$result
    }

    $action = @($task.Actions)
    $actionVariant = if ($action.Count -eq 1 -and
        (Test-OrdinalPathEqual $action[0].Execute ([string]$bundleValidation.action_python_path))) {
        'windowless_python'
    } elseif ($action.Count -eq 1 -and
        (Test-OrdinalPathEqual $action[0].Execute ([string]$bundleValidation.python_path))) {
        'console_python'
    } else {
        ''
    }
    $contractValid = -not [string]::IsNullOrEmpty($actionVariant) -and
        [string]::Equals(
            [string]$task.State,
            'Ready',
            [System.StringComparison]::OrdinalIgnoreCase
        )
    if (-not $contractValid) {
        $result.validation = 'predecessor_task_contract_invalid'
        return [pscustomobject]$result
    }
    $taskXml = [string](Export-ScheduledTask `
            -TaskName $taskName `
            -TaskPath $taskPath `
            -ErrorAction Stop)
    if ([string]::IsNullOrWhiteSpace($taskXml)) {
        $result.validation = 'predecessor_export_invalid'
        return [pscustomobject]$result
    }
    $normalizedXmlSha256 = Get-NormalizedManagedPredecessorXmlSha256 `
        $taskXml `
        $bundleValidation
    if (-not [string]::Equals(
            $normalizedXmlSha256,
            $managedUpgradeSourceNormalizedXmlSha256,
            [System.StringComparison]::Ordinal
        )) {
        $result.validation = 'predecessor_xml_identity_invalid'
        return [pscustomobject]$result
    }
    $result.valid = $true
    $result.validation = 'managed_predecessor_valid'
    $result.task_xml = $taskXml
    $result.task_description = $description
    $result.action_variant = $actionVariant
    $result.content_id = $managedUpgradeSourceContentId
    $result.manifest_sha256 = $managedUpgradeSourceManifestSha256
    return [pscustomobject]$result
}

function Get-ConsumerTaskAudit {
    param(
        [Nullable[int]]$ExpectedMinutes,
        [string]$ExpectedRegistrationToken = ''
    )

    $task = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        return [ordered]@{
            schema_version = 's.context_rollout_consumer.install_audit.v1'
            status = 'absent'
            task_name = $taskName
            task_path = $taskPath
            valid = $false
            authority = $false
        }
    }

    $currentSid = Get-CurrentIdentitySid
    $taskSid = Resolve-IdentitySid ([string]$task.Principal.UserId)
    $action = @($task.Actions)
    $trigger = @($task.Triggers)
    $description = [string]$task.Description
    $descriptionPattern = '^' + [regex]::Escape($descriptionPrefix) +
        '(?<token>[0-9a-f]{32});registered_at=(?<registered>[^;]+);receipt_not_before=' +
        '(?<receipt_not_before>[^;]+);content_id=' +
        '(?<content>[0-9a-f]{64});manifest_sha256=(?<manifest>[0-9a-f]{64})$'
    $descriptionMatch = [regex]::Match($description, $descriptionPattern)
    $descriptionToken = if ($descriptionMatch.Success) {
        $descriptionMatch.Groups['token'].Value
    } else {
        ''
    }
    $descriptionContentId = if ($descriptionMatch.Success) {
        $descriptionMatch.Groups['content'].Value
    } else {
        ''
    }
    $descriptionManifestSha256 = if ($descriptionMatch.Success) {
        $descriptionMatch.Groups['manifest'].Value
    } else {
        ''
    }
    $descriptionRegisteredAtText = if ($descriptionMatch.Success) {
        $descriptionMatch.Groups['registered'].Value
    } else {
        ''
    }
    $descriptionRegisteredAt = ConvertTo-StrictReceiptTimestamp $descriptionRegisteredAtText
    $descriptionRegistrationValid = $null -ne $descriptionRegisteredAt -and
        (Test-CanonicalUtcTimestamp $descriptionRegisteredAtText $descriptionRegisteredAt) -and
        $descriptionRegisteredAt.Year -ge 2025 -and
        $descriptionRegisteredAt -le [DateTimeOffset]::Now.AddMinutes(2)
    $descriptionReceiptNotBeforeText = if ($descriptionMatch.Success) {
        $descriptionMatch.Groups['receipt_not_before'].Value
    } else {
        ''
    }
    $descriptionReceiptNotBefore = ConvertTo-StrictReceiptTimestamp $descriptionReceiptNotBeforeText
    $descriptionReceiptBoundaryValid = $null -ne $descriptionReceiptNotBefore -and
        (Test-CanonicalUtcTimestamp $descriptionReceiptNotBeforeText $descriptionReceiptNotBefore) -and
        $descriptionRegistrationValid -and
        $descriptionReceiptNotBefore -gt $descriptionRegisteredAt -and
        $descriptionReceiptNotBefore -le $descriptionRegisteredAt.AddMinutes(10)
    $expectedBundleRoot = if ($descriptionMatch.Success) {
        Join-Path $bundleBase $descriptionContentId
    } else {
        ''
    }
    $bundleValidation = if ($descriptionMatch.Success) {
        Test-BundlePayload $expectedBundleRoot $descriptionContentId $descriptionManifestSha256
    } else {
        [ordered]@{
            valid = $false
            validation = 'description_invalid'
            files_valid = $false
            payload_hash_valid = $false
            payload_acl_valid = $false
            python_path = ''
            action_python_path = ''
            consumer_script = ''
            working_directory = ''
            arguments = ''
        }
    }
    $filesValid = [bool]$bundleValidation.files_valid
    $payloadHashValid = [bool]$bundleValidation.payload_hash_valid
    $payloadAclValid = [bool]$bundleValidation.payload_acl_valid
    $taskInfo = $null
    try {
        $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath $taskPath -ErrorAction Stop
    }
    catch {
        $taskInfo = $null
    }
    $taskInfoValid = $null -ne $taskInfo
    $lastTaskResult = if ($taskInfoValid) { [long]$taskInfo.LastTaskResult } else { $null }
    $taskState = [string]$task.State
    $taskRunning = [string]::Equals(
        $taskState,
        'Running',
        [System.StringComparison]::OrdinalIgnoreCase
    )
    $lastRunAt = [DateTimeOffset]::MinValue
    if ($taskInfoValid -and $taskInfo.LastRunTime -is [DateTimeOffset] -and
        ([DateTimeOffset]$taskInfo.LastRunTime).Year -ge 2025) {
        $lastRunAt = [DateTimeOffset]$taskInfo.LastRunTime
    } elseif ($taskInfoValid -and $taskInfo.LastRunTime -is [DateTime] -and
        ([DateTime]$taskInfo.LastRunTime).Year -ge 2025) {
        $lastRunAt = [DateTimeOffset]([DateTime]$taskInfo.LastRunTime)
    }
    $taskHasRun = $taskInfoValid -and
        $lastRunAt.Year -ge 2025 -and
        $lastRunAt -le [DateTimeOffset]::Now.AddMinutes(2)
    $taskResultHealth = if (-not $taskInfoValid) {
        'task_info_unavailable'
    } elseif (-not $taskHasRun) {
        'task_not_yet_run'
    } elseif ($lastTaskResult -eq 0) {
        'task_last_result_ok'
    } elseif ($taskRunning) {
        'task_running'
    } else {
        'task_last_result_nonzero'
    }
    $intervalText = if ($trigger.Count -eq 1) {
        [string]$trigger[0].Repetition.Interval
    } else {
        ''
    }
    $allowedIntervals = @('PT1M', 'PT2M', 'PT5M', 'PT15M')
    $healthIntervalMinutes = switch ($intervalText) {
        'PT1M' { 1 }
        'PT2M' { 2 }
        'PT5M' { 5 }
        'PT15M' { 15 }
        default { 0 }
    }
    $consumerReceiptStatus = 'absent'
    $consumerReceiptErrorType = ''
    $consumerReceiptFinishedAt = ''
    $consumerReceiptSchemaValid = $false
    $consumerReceiptFresh = $false
    $consumerReceiptValidation = 'receipt_absent'
    if (Test-Path -LiteralPath $consumerReceiptPath -PathType Leaf) {
        try {
            $receiptItem = Get-Item -LiteralPath $consumerReceiptPath -ErrorAction Stop
            if (($receiptItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
                $receiptItem.Length -gt 1MB) {
                throw 'Consumer receipt carrier is unsafe.'
            }
            $receiptJson = Get-Content -LiteralPath $consumerReceiptPath -Raw -Encoding UTF8
            if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) {
                $consumerReceipt = $receiptJson | ConvertFrom-Json -DateKind String -ErrorAction Stop
            } else {
                $consumerReceipt = $receiptJson | ConvertFrom-Json -ErrorAction Stop
            }
            $candidateReceiptStatus = [string]$consumerReceipt.status
            $completedReceiptFields = @(
                'schema_version',
                'status',
                'started_at',
                'finished_at',
                'bootstrap',
                'state_recovered',
                'scan_start',
                'scan_end',
                'counts',
                'files',
                'file_receipts_total',
                'file_receipts_omitted',
                'authority'
            )
            $failedReceiptRequiredFields = @(
                'schema_version',
                'status',
                'error_type',
                'started_at',
                'finished_at',
                'authority'
            )
            $failedReceiptAllowedFields = @(
                'schema_version',
                'status',
                'error_type',
                'recovery_status',
                'corrupt_state_sha256',
                'started_at',
                'finished_at',
                'authority'
            )
            if (-not [string]::Equals(
                    [string]$consumerReceipt.schema_version,
                    's.context_rollout_consumer.receipt.v1',
                    [System.StringComparison]::Ordinal
                ) -or $consumerReceipt.authority -isnot [bool] -or
                $consumerReceipt.authority -ne $false) {
                throw 'Consumer receipt schema or authority marker is invalid.'
            }
            if ($candidateReceiptStatus -in @('completed', 'completed_with_errors')) {
                if (-not (Test-ExactPropertySet $consumerReceipt $completedReceiptFields) -or
                    $consumerReceipt.bootstrap -isnot [bool] -or
                    $consumerReceipt.state_recovered -isnot [bool] -or
                    $consumerReceipt.counts -isnot [System.Management.Automation.PSCustomObject] -or
                    $consumerReceipt.files -isnot [System.Array] -or
                    -not (Test-JsonInteger $consumerReceipt.file_receipts_total) -or
                    -not (Test-JsonInteger $consumerReceipt.file_receipts_omitted)) {
                    throw 'Consumer completed receipt shape is invalid.'
                }
                $allowedCountFields = @(
                    'appended',
                    'awaiting_stable',
                    'changed_candidates',
                    'classification_error',
                    'deferred',
                    'duplicate',
                    'file_error',
                    'ignored',
                    'imported',
                    'integrity_recheck_deferred',
                    'integrity_verified',
                    'inventoried',
                    'new_pre_cutoff_ignored',
                    'persistent_integrity_quarantine',
                    'quarantined_locator',
                    'retry_backoff',
                    'stable_roots_pruned',
                    'state_recovered',
                    'unadopted_non_growth_ignored',
                    'unchanged_cursor',
                    'unchanged_incomplete_tail',
                    'classified_excluded_non_cli',
                    'classified_excluded_non_root',
                    'classified_excluded_subagent',
                    'classified_invalid',
                    'classified_quarantined',
                    'classified_read_error',
                    'classified_root_cli'
                )
                foreach ($countProperty in $consumerReceipt.counts.PSObject.Properties) {
                    if ($allowedCountFields -notcontains [string]$countProperty.Name -or
                        -not (Test-JsonInteger $countProperty.Value)) {
                        throw 'Consumer receipt count is invalid.'
                    }
                }
                if (@($consumerReceipt.files).Count -gt 64) {
                    throw 'Consumer receipt file list exceeds its bound.'
                }
                $importedFileFields = @(
                    'carrier_id',
                    'locator_sha256',
                    'status',
                    'appended',
                    'duplicate',
                    'ignored',
                    'incomplete_tail'
                )
                $errorFileFields = @('carrier_id', 'locator_sha256', 'status', 'error_type')
                $allowedFileErrorTypes = @(
                    'context_fabric_unavailable',
                    'context_fabric_rejected',
                    'sqlite_error',
                    'filesystem_error',
                    'consumer_contract_error',
                    'invalid_value',
                    'unexpected_error',
                    'locator_timestamp_invalid',
                    'locator_timestamp_future',
                    'incomplete_session_meta',
                    'session_meta_too_large',
                    'invalid_session_meta_json',
                    'missing_session_meta',
                    'session_meta_ordinal',
                    'session_meta_payload',
                    'session_meta_timestamp',
                    'session_meta_timestamp_future',
                    'session_meta_locator_timestamp_mismatch',
                    'session_id_locator_mismatch'
                )
                foreach ($fileReceipt in @($consumerReceipt.files)) {
                    if ($fileReceipt -isnot [System.Management.Automation.PSCustomObject] -or
                        $fileReceipt.carrier_id -isnot [string] -or
                        [string]$fileReceipt.carrier_id -notin @('s-primary', 's-account-b') -or
                        $fileReceipt.locator_sha256 -isnot [string] -or
                        [string]$fileReceipt.locator_sha256 -notmatch '^[0-9a-f]{64}$' -or
                        $fileReceipt.status -isnot [string]) {
                        throw 'Consumer receipt file identity is invalid.'
                    }
                    $fileStatus = [string]$fileReceipt.status
                    if ($fileStatus -in @('imported', 'integrity_verified')) {
                        if (-not (Test-ExactPropertySet $fileReceipt $importedFileFields) -or
                            -not (Test-JsonInteger $fileReceipt.appended) -or
                            -not (Test-JsonInteger $fileReceipt.duplicate) -or
                            -not (Test-JsonInteger $fileReceipt.ignored) -or
                            $fileReceipt.incomplete_tail -isnot [bool]) {
                            throw 'Consumer imported file receipt is invalid.'
                        }
                    } elseif ($fileStatus -in @('quarantined', 'classification_error', 'error')) {
                        if (-not (Test-ExactPropertySet $fileReceipt $errorFileFields) -or
                            $fileReceipt.error_type -isnot [string] -or
                            $allowedFileErrorTypes -notcontains [string]$fileReceipt.error_type) {
                            throw 'Consumer error file receipt is invalid.'
                        }
                    } else {
                        throw 'Consumer file receipt status is invalid.'
                    }
                }
                if ([long]$consumerReceipt.file_receipts_total -ne
                    @($consumerReceipt.files).Count + [long]$consumerReceipt.file_receipts_omitted) {
                    throw 'Consumer receipt file bounds are inconsistent.'
                }
                $startedAt = ConvertTo-StrictReceiptTimestamp $consumerReceipt.started_at
                $finishedAt = ConvertTo-StrictReceiptTimestamp $consumerReceipt.finished_at
                $scanStart = ConvertTo-StrictReceiptTimestamp $consumerReceipt.scan_start
                $scanEnd = ConvertTo-StrictReceiptTimestamp $consumerReceipt.scan_end
                if ($null -eq $startedAt -or $null -eq $finishedAt -or
                    $null -eq $scanStart -or $null -eq $scanEnd) {
                    throw 'Consumer receipt timestamp parsing failed.'
                }
                if ($startedAt -gt $finishedAt -or $scanStart -gt $scanEnd -or
                    $scanEnd -gt $finishedAt) {
                    throw 'Consumer receipt timestamp ordering is invalid.'
                }
            } elseif ($candidateReceiptStatus -eq 'failed') {
                $actualFailedFields = @($consumerReceipt.PSObject.Properties.Name)
                if (@($failedReceiptRequiredFields | Where-Object { $actualFailedFields -notcontains $_ }).Count -ne 0 -or
                    @($actualFailedFields | Where-Object { $failedReceiptAllowedFields -notcontains $_ }).Count -ne 0) {
                    throw 'Consumer failed receipt shape is invalid.'
                }
                $allowedReceiptErrorTypes = @(
                    'consumer_state_invalid',
                    'state_quarantine_invalid',
                    'state_recovery_failed',
                    'context_fabric_unavailable',
                    'context_fabric_rejected',
                    'sqlite_error',
                    'filesystem_error',
                    'consumer_contract_error',
                    'invalid_value',
                    'unexpected_error'
                )
                if ($allowedReceiptErrorTypes -notcontains [string]$consumerReceipt.error_type) {
                    throw 'Consumer failed receipt error type is invalid.'
                }
                if ($actualFailedFields -contains 'corrupt_state_sha256' -and
                    [string]$consumerReceipt.corrupt_state_sha256 -notmatch '^[0-9a-f]{64}$') {
                    throw 'Consumer failed receipt state hash is invalid.'
                }
                $allowedRecoveryStatuses = @(
                    'staging_hash_only_quarantine',
                    'pending_next_run',
                    'pending_next_run_state_retained',
                    'unavailable_quarantine_marker',
                    'unavailable_unsafe_state_source',
                    'unavailable_missing_state_and_marker',
                    'manual_intervention_required'
                )
                if ($actualFailedFields -contains 'recovery_status' -and
                    $allowedRecoveryStatuses -notcontains [string]$consumerReceipt.recovery_status) {
                    throw 'Consumer failed receipt recovery status is invalid.'
                }
                $startedAt = ConvertTo-StrictReceiptTimestamp $consumerReceipt.started_at
                $finishedAt = ConvertTo-StrictReceiptTimestamp $consumerReceipt.finished_at
                if ($null -eq $startedAt -or $null -eq $finishedAt -or $startedAt -gt $finishedAt) {
                    throw 'Consumer failed receipt timestamps are invalid.'
                }
                $consumerReceiptErrorType = [string]$consumerReceipt.error_type
            } else {
                throw 'Consumer receipt status is invalid.'
            }
            $consumerReceiptStatus = $candidateReceiptStatus
            $consumerReceiptSchemaValid = $true
            $consumerReceiptValidation = 'receipt_schema_valid'
            $consumerReceiptFinishedAt = $finishedAt.ToString('o')
            if ($healthIntervalMinutes -gt 0) {
                $auditNow = [DateTimeOffset]::Now
                $freshnessBudget = New-TimeSpan -Minutes (5 + (2 * $healthIntervalMinutes))
                $consumerReceiptFresh = $finishedAt -ge $auditNow.Subtract($freshnessBudget) -and
                    $finishedAt -le $auditNow.AddMinutes(2) -and
                    $descriptionReceiptBoundaryValid -and
                    $lastRunAt -ge $descriptionReceiptNotBefore -and
                    $finishedAt -ge $descriptionReceiptNotBefore -and
                    $taskHasRun -and
                    $finishedAt -ge $lastRunAt.Subtract((New-TimeSpan -Minutes 1)) -and
                    $finishedAt -le $lastRunAt.AddMinutes(7)
            }
        }
        catch {
            $consumerReceiptValidation = switch ([string]$_.Exception.Message) {
                'Consumer receipt carrier is unsafe.' { 'receipt_carrier_unsafe' }
                'Consumer receipt schema or authority marker is invalid.' { 'receipt_header_invalid' }
                'Consumer completed receipt shape is invalid.' { 'receipt_completed_shape_invalid' }
                'Consumer receipt count is invalid.' { 'receipt_count_invalid' }
                'Consumer receipt file list exceeds its bound.' { 'receipt_file_list_unbounded' }
                'Consumer receipt file identity is invalid.' { 'receipt_file_identity_invalid' }
                'Consumer imported file receipt is invalid.' { 'receipt_import_file_invalid' }
                'Consumer error file receipt is invalid.' { 'receipt_error_file_invalid' }
                'Consumer file receipt status is invalid.' { 'receipt_file_status_invalid' }
                'Consumer receipt file bounds are inconsistent.' { 'receipt_file_bounds_invalid' }
                'Consumer receipt timestamp parsing failed.' { 'receipt_timestamp_parse_invalid' }
                'Consumer receipt timestamp ordering is invalid.' { 'receipt_timestamp_order_invalid' }
                'Consumer failed receipt shape is invalid.' { 'receipt_failed_shape_invalid' }
                'Consumer failed receipt error type is invalid.' { 'receipt_failed_error_invalid' }
                'Consumer failed receipt state hash is invalid.' { 'receipt_failed_hash_invalid' }
                'Consumer failed receipt recovery status is invalid.' { 'receipt_failed_recovery_invalid' }
                'Consumer failed receipt timestamps are invalid.' { 'receipt_failed_timestamps_invalid' }
                'Consumer receipt status is invalid.' { 'receipt_status_invalid' }
                default { 'receipt_parse_invalid' }
            }
            $consumerReceiptStatus = 'invalid'
            $consumerReceiptErrorType = ''
            $consumerReceiptFinishedAt = ''
            $consumerReceiptSchemaValid = $false
            $consumerReceiptFresh = $false
        }
    }
    $presentationReceiptStatus = 'absent'
    $presentationReceiptSchemaValid = $false
    $presentationReceiptFresh = $false
    $presentationReceiptValidation = 'presentation_receipt_absent'
    if (Test-Path -LiteralPath $presentationReceiptPath -PathType Leaf) {
        try {
            $presentationItem = Get-Item -LiteralPath $presentationReceiptPath -Force -ErrorAction Stop
            if (($presentationItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
                $presentationItem.Length -lt 1 -or $presentationItem.Length -gt 1MB) {
                throw 'Presentation receipt carrier is unsafe.'
            }
            $presentationJson = Get-Content -LiteralPath $presentationReceiptPath -Raw -Encoding UTF8
            if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) {
                $presentationReceipt = $presentationJson | ConvertFrom-Json -DateKind String -ErrorAction Stop
            } else {
                $presentationReceipt = $presentationJson | ConvertFrom-Json -ErrorAction Stop
            }
            $presentationFields = @(
                'schema_version', 'status', 'started_at', 'finished_at', 'runtime_roots',
                'counts', 'visible_emitter', 'ui_interception_claimed', 'authority'
            )
            if (-not (Test-ExactPropertySet $presentationReceipt $presentationFields) -or
                -not [string]::Equals(
                    [string]$presentationReceipt.schema_version,
                    's.context_rollout_presentation.receipt.v1',
                    [System.StringComparison]::Ordinal
                ) -or
                [string]$presentationReceipt.status -notin @('completed', 'completed_with_errors') -or
                $presentationReceipt.runtime_roots -isnot [System.Array] -or
                @($presentationReceipt.runtime_roots).Count -ne 9 -or
                $presentationReceipt.counts -isnot [System.Management.Automation.PSCustomObject] -or
                -not [string]::Equals(
                    [string]$presentationReceipt.visible_emitter,
                    'windows_notify_icon.v1',
                    [System.StringComparison]::Ordinal
                ) -or $presentationReceipt.ui_interception_claimed -isnot [bool] -or
                $presentationReceipt.ui_interception_claimed -ne $false -or
                $presentationReceipt.authority -isnot [bool] -or
                $presentationReceipt.authority -ne $false) {
                throw 'Presentation receipt shape is invalid.'
            }
            $allowedPresentationCountFields = @(
                'absent', 'error', 'observed', 'pending_delivery', 'transitions',
                'notification_attempted', 'notification_acknowledged', 'notification_failed'
            )
            foreach ($property in @($presentationReceipt.counts.PSObject.Properties)) {
                if ([string]$property.Name -notin $allowedPresentationCountFields -or
                    -not (Test-JsonInteger $property.Value)) {
                    throw 'Presentation receipt count is invalid.'
                }
            }
            $presentationRootFields = @(
                'runtime_root_sha256', 'observer_status', 'transition_count',
                'pending_delivery_count', 'routine_pending_count', 'visible_pending_count',
                'authority'
            )
            $presentationObservedExtraFields = @(
                'activity_id', 'account_slot', 'run_id', 'pointer_sha256',
                'run_config_sha256', 'binding_readback', 'projection_count',
                'controller_record_sha256', 'presentation_event_id'
            )
            $observedRuntimeRootHashes = [System.Collections.Generic.HashSet[string]]::new(
                [System.StringComparer]::Ordinal
            )
            [long]$rootStatusCount = 0
            [long]$rootTransitionCount = 0
            [long]$rootPendingDeliveryCount = 0
            foreach ($runtimeReceipt in @($presentationReceipt.runtime_roots)) {
                if ($runtimeReceipt -isnot [System.Management.Automation.PSCustomObject]) {
                    throw 'Presentation runtime receipt is invalid.'
                }
                $status = [string]$runtimeReceipt.observer_status
                $allowedFields = @($presentationRootFields)
                if ($status -in @('observed', 'unchanged')) {
                    $allowedFields += $presentationObservedExtraFields
                } elseif ($status -eq 'error') {
                    $allowedFields += 'error_type'
                } elseif ($status -ne 'absent') {
                    throw 'Presentation runtime status is invalid.'
                }
                if (-not (Test-ExactPropertySet $runtimeReceipt $allowedFields) -or
                    [string]$runtimeReceipt.runtime_root_sha256 -notmatch '^[0-9a-f]{64}$' -or
                    -not $observedRuntimeRootHashes.Add([string]$runtimeReceipt.runtime_root_sha256) -or
                    $runtimeReceipt.authority -isnot [bool] -or $runtimeReceipt.authority -ne $false) {
                    throw 'Presentation runtime receipt shape is invalid.'
                }
                foreach ($integerField in @(
                        'transition_count', 'pending_delivery_count',
                        'routine_pending_count', 'visible_pending_count'
                    )) {
                    if (-not (Test-JsonInteger $runtimeReceipt.$integerField)) {
                        throw 'Presentation runtime receipt count is invalid.'
                    }
                }
                $rootStatusCount += 1
                $rootTransitionCount += [long]$runtimeReceipt.transition_count
                $rootPendingDeliveryCount += [long]$runtimeReceipt.pending_delivery_count
                if ($status -in @('observed', 'unchanged')) {
                    foreach ($digestField in @(
                            'pointer_sha256', 'run_config_sha256',
                            'controller_record_sha256'
                        )) {
                        if ([string]$runtimeReceipt.$digestField -notmatch '^[0-9a-f]{64}$') {
                            throw 'Presentation runtime receipt digest is invalid.'
                        }
                    }
                    if ([string]$runtimeReceipt.account_slot -notin @('A', 'C') -or
                        [string]$runtimeReceipt.binding_readback -notin @(
                            'stable', 'changed_after_observe'
                        ) -or -not (Test-JsonInteger $runtimeReceipt.projection_count)) {
                        throw 'Presentation runtime observed identity is invalid.'
                    }
                }
            }
            foreach ($expectedRuntimeRootHash in $expectedPresentationRuntimeRootHashes) {
                if (-not $observedRuntimeRootHashes.Contains($expectedRuntimeRootHash)) {
                    throw 'Presentation runtime receipt root set is invalid.'
                }
            }
            [long]$countedRootStatuses = 0
            foreach ($countName in @('absent', 'error', 'observed')) {
                if ($presentationReceipt.counts.PSObject.Properties.Name -contains $countName) {
                    $countedRootStatuses += [long]$presentationReceipt.counts.$countName
                }
            }
            [long]$countedTransitions = if (
                $presentationReceipt.counts.PSObject.Properties.Name -contains 'transitions'
            ) { [long]$presentationReceipt.counts.transitions } else { 0 }
            [long]$countedPendingDelivery = if (
                $presentationReceipt.counts.PSObject.Properties.Name -contains 'pending_delivery'
            ) { [long]$presentationReceipt.counts.pending_delivery } else { 0 }
            if ($countedRootStatuses -ne $rootStatusCount -or
                $countedTransitions -ne $rootTransitionCount -or
                $countedPendingDelivery -ne $rootPendingDeliveryCount) {
                throw 'Presentation receipt aggregate counts are inconsistent.'
            }
            $presentationStartedAt = ConvertTo-StrictReceiptTimestamp $presentationReceipt.started_at
            $presentationFinishedAt = ConvertTo-StrictReceiptTimestamp $presentationReceipt.finished_at
            if ($null -eq $presentationStartedAt -or $null -eq $presentationFinishedAt -or
                $presentationStartedAt -gt $presentationFinishedAt) {
                throw 'Presentation receipt timestamps are invalid.'
            }
            $presentationReceiptStatus = [string]$presentationReceipt.status
            $presentationReceiptSchemaValid = $true
            $presentationReceiptValidation = 'presentation_receipt_schema_valid'
            if ($healthIntervalMinutes -gt 0) {
                $presentationBudget = New-TimeSpan -Minutes (5 + (2 * $healthIntervalMinutes))
                $presentationReceiptFresh = $presentationFinishedAt -ge [DateTimeOffset]::Now.Subtract($presentationBudget) -and
                    $presentationFinishedAt -le [DateTimeOffset]::Now.AddMinutes(2) -and
                    $descriptionReceiptBoundaryValid -and
                    $lastRunAt -ge $descriptionReceiptNotBefore -and
                    $presentationFinishedAt -ge $descriptionReceiptNotBefore -and
                    $taskHasRun -and
                    $presentationFinishedAt -ge $lastRunAt.Subtract((New-TimeSpan -Minutes 1)) -and
                    $presentationFinishedAt -le $lastRunAt.AddMinutes(7)
            }
        }
        catch {
            $presentationReceiptStatus = 'invalid'
            $presentationReceiptSchemaValid = $false
            $presentationReceiptFresh = $false
            $presentationReceiptValidation = 'presentation_receipt_invalid'
        }
    }
    $descriptionValid = $descriptionMatch.Success -and $descriptionRegistrationValid -and
        $descriptionReceiptBoundaryValid -and
        $payloadHashValid -and
        ([string]::IsNullOrWhiteSpace($ExpectedRegistrationToken) -or
            [string]::Equals(
                $descriptionToken,
                $ExpectedRegistrationToken,
                [System.StringComparison]::Ordinal
            ))
    $actionValid = $action.Count -eq 1 -and
        (Test-OrdinalPathEqual $action[0].Execute ([string]$bundleValidation.action_python_path)) -and
        [string]::Equals(
            [string]$action[0].Arguments,
            [string]$bundleValidation.arguments,
            [System.StringComparison]::Ordinal
        ) -and
        (Test-OrdinalPathEqual $action[0].WorkingDirectory ([string]$bundleValidation.working_directory))
    $principalValid = [string]::Equals(
            $taskSid,
            $currentSid,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        [string]::Equals([string]$task.Principal.RunLevel, 'Limited', [System.StringComparison]::OrdinalIgnoreCase) -and
        [string]::Equals([string]$task.Principal.LogonType, 'Interactive', [System.StringComparison]::OrdinalIgnoreCase)
    $settingsValid = [string]::Equals(
            [string]$task.Settings.MultipleInstances,
            'IgnoreNew',
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        [bool]$task.Settings.StartWhenAvailable -and
        -not [bool]$task.Settings.DisallowStartIfOnBatteries -and
        -not [bool]$task.Settings.StopIfGoingOnBatteries -and
        [string]::Equals(
            [string]$task.Settings.ExecutionTimeLimit,
            'PT5M',
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        [bool]$task.Settings.Enabled -and
        -not [bool]$task.Settings.Hidden -and
        -not [bool]$task.Settings.RunOnlyIfIdle -and
        -not [bool]$task.Settings.WakeToRun
    $triggerEnabled = $trigger.Count -eq 1 -and [bool]$trigger[0].Enabled
    $durationText = if ($trigger.Count -eq 1) {
        [string]$trigger[0].Repetition.Duration
    } else {
        ''
    }
    $durationValid = $trigger.Count -eq 1 -and
        [string]::Equals(
            $durationText,
            $expectedRepetitionDuration,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        -not [bool]$trigger[0].Repetition.StopAtDurationEnd
    $startBoundary = [DateTimeOffset]::MinValue
    $startBoundaryText = if ($trigger.Count -eq 1) { [string]$trigger[0].StartBoundary } else { '' }
    $startBoundaryValid = [DateTimeOffset]::TryParse(
            $startBoundaryText,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeLocal,
            [ref]$startBoundary
        ) -and
        $startBoundary.Year -ge 2025 -and
        $startBoundary -le [DateTimeOffset]::Now.AddMinutes(10)
    $triggerValid = $trigger.Count -eq 1 -and
        $allowedIntervals -contains $intervalText -and
        $triggerEnabled -and
        $durationValid -and
        $startBoundaryValid -and
        $descriptionReceiptBoundaryValid -and
        $startBoundary.ToUniversalTime() -eq $descriptionReceiptNotBefore
    if ($null -ne $ExpectedMinutes) {
        $triggerValid = $triggerValid -and $intervalText -eq "PT$([int]$ExpectedMinutes)M"
    }
    $enabledValid = -not [string]::Equals(
        [string]$task.State,
        'Disabled',
        [System.StringComparison]::OrdinalIgnoreCase
    )
    $contractValid = $descriptionValid -and $actionValid -and $principalValid -and
        $settingsValid -and $triggerValid -and $taskInfoValid
    $installationValid = $contractValid -and $filesValid -and $enabledValid -and $payloadAclValid
    $consumerHealth = if (-not $installationValid) {
        'installation_drifted'
    } elseif (-not $taskHasRun) {
        'pending_first_run'
    } elseif ($lastTaskResult -ne 0 -and -not $taskRunning) {
        'task_last_result_nonzero'
    } elseif (-not $consumerReceiptSchemaValid) {
        if ($consumerReceiptStatus -eq 'absent') { 'receipt_absent' } else { 'receipt_invalid' }
    } elseif (-not $consumerReceiptFresh) {
        'receipt_stale'
    } elseif (-not $presentationReceiptSchemaValid) {
        if ($presentationReceiptStatus -eq 'absent') {
            'presentation_receipt_absent'
        } else {
            'presentation_receipt_invalid'
        }
    } elseif (-not $presentationReceiptFresh) {
        'presentation_receipt_stale'
    } elseif ($presentationReceiptStatus -eq 'completed_with_errors') {
        'presentation_degraded'
    } elseif ($consumerReceiptStatus -eq 'completed_with_errors') {
        'degraded'
    } elseif ($consumerReceiptStatus -eq 'failed') {
        'failed'
    } elseif ($consumerReceiptStatus -eq 'completed') {
        'healthy'
    } else {
        'receipt_invalid'
    }
    $healthValid = $consumerHealth -eq 'healthy'
    $valid = $installationValid -and $healthValid
    $auditStatus = if ($valid) {
        'installed_valid'
    } elseif (-not $installationValid) {
        'installed_drifted'
    } elseif ($consumerHealth -eq 'pending_first_run') {
        'installed_pending'
    } else {
        'installed_degraded'
    }

    return [ordered]@{
        schema_version = 's.context_rollout_consumer.install_audit.v1'
        status = $auditStatus
        task_name = $taskName
        task_path = $taskPath
        valid = $valid
        installation_valid = $installationValid
        health_valid = $healthValid
        contract_valid = $contractValid
        description_valid = $descriptionValid
        payload_hash_valid = $payloadHashValid
        payload_acl_valid = $payloadAclValid
        action_valid = $actionValid
        principal_valid = $principalValid
        settings_valid = $settingsValid
        trigger_valid = $triggerValid
        task_info_valid = $taskInfoValid
        task_state = $taskState
        task_running = $taskRunning
        last_task_result = $lastTaskResult
        task_result_health = $taskResultHealth
        last_run_time = if ($taskInfoValid) { $taskInfo.LastRunTime } else { $null }
        next_run_time = if ($taskInfoValid) { $taskInfo.NextRunTime } else { $null }
        consumer_receipt_status = $consumerReceiptStatus
        consumer_receipt_error_type = $consumerReceiptErrorType
        consumer_receipt_finished_at = $consumerReceiptFinishedAt
        consumer_receipt_schema_valid = $consumerReceiptSchemaValid
        consumer_receipt_fresh = $consumerReceiptFresh
        consumer_receipt_validation = $consumerReceiptValidation
        presentation_receipt_status = $presentationReceiptStatus
        presentation_receipt_schema_valid = $presentationReceiptSchemaValid
        presentation_receipt_fresh = $presentationReceiptFresh
        presentation_receipt_validation = $presentationReceiptValidation
        consumer_health = $consumerHealth
        trigger_enabled = $triggerEnabled
        start_boundary = $startBoundaryText
        start_boundary_valid = $startBoundaryValid
        repetition_duration = $durationText
        repetition_duration_valid = $durationValid
        bundle_valid = [bool]$bundleValidation.valid
        bundle_validation = [string]$bundleValidation.validation
        content_id = $descriptionContentId
        manifest_sha256 = $descriptionManifestSha256
        registered_at = $descriptionRegisteredAtText
        receipt_not_before = $descriptionReceiptNotBeforeText
        files_valid = $filesValid
        enabled_valid = $enabledValid
        execute = if ($action.Count -eq 1) { [string]$action[0].Execute } else { '' }
        arguments = if ($action.Count -eq 1) { [string]$action[0].Arguments } else { '' }
        working_directory = if ($action.Count -eq 1) { [string]$action[0].WorkingDirectory } else { '' }
        pinned_execute = [string]$bundleValidation.action_python_path
        pinned_arguments = [string]$bundleValidation.arguments
        pinned_working_directory = [string]$bundleValidation.working_directory
        interval = $intervalText
        user_id = [string]$task.Principal.UserId
        user_sid = $taskSid
        multiple_instances = [string]$task.Settings.MultipleInstances
        start_when_available = [bool]$task.Settings.StartWhenAvailable
        disallow_start_on_batteries = [bool]$task.Settings.DisallowStartIfOnBatteries
        stop_if_going_on_batteries = [bool]$task.Settings.StopIfGoingOnBatteries
        execution_time_limit = [string]$task.Settings.ExecutionTimeLimit
        settings_enabled = [bool]$task.Settings.Enabled
        hidden = [bool]$task.Settings.Hidden
        run_only_if_idle = [bool]$task.Settings.RunOnlyIfIdle
        wake_to_run = [bool]$task.Settings.WakeToRun
        authority = $false
    }
}

function Test-OwnedUpgradeReplacement {
    param(
        [object]$Task,
        [object]$Candidate,
        [object]$Bundle,
        [int]$ExpectedMinutes
    )
    if ($null -eq $Task) {
        return $false
    }
    $action = @($Task.Actions)
    $trigger = @($Task.Triggers)
    $currentSid = Get-CurrentIdentitySid
    $taskSid = Resolve-IdentitySid ([string]$Task.Principal.UserId)
    $startBoundary = [DateTimeOffset]::MinValue
    $startBoundaryText = if ($trigger.Count -eq 1) { [string]$trigger[0].StartBoundary } else { '' }
    $candidateReceiptNotBefore = ConvertTo-StrictReceiptTimestamp `
        ([string]$Candidate.receipt_not_before)
    $startBoundaryValid = [DateTimeOffset]::TryParse(
            $startBoundaryText,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeLocal,
            [ref]$startBoundary
        ) -and $startBoundary.Year -ge 2025 -and
        $startBoundary -le [DateTimeOffset]::Now.AddMinutes(10) -and
        $null -ne $candidateReceiptNotBefore -and
        $startBoundary.ToUniversalTime() -eq $candidateReceiptNotBefore
    return $action.Count -eq 1 -and
        [string]::Equals(
            [string]$Task.Description,
            [string]$Candidate.description,
            [System.StringComparison]::Ordinal
        ) -and
        (Test-OrdinalPathEqual $action[0].Execute ([string]$Bundle.validation.action_python_path)) -and
        [string]::Equals(
            [string]$action[0].Arguments,
            [string]$Bundle.validation.arguments,
            [System.StringComparison]::Ordinal
        ) -and
        (Test-OrdinalPathEqual $action[0].WorkingDirectory ([string]$Bundle.validation.working_directory)) -and
        [string]::Equals($taskSid, $currentSid, [System.StringComparison]::OrdinalIgnoreCase) -and
        [string]::Equals(
            [string]$Task.Principal.RunLevel,
            'Limited',
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        [string]::Equals(
            [string]$Task.Principal.LogonType,
            'Interactive',
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        [string]::Equals(
            [string]$Task.Settings.MultipleInstances,
            'IgnoreNew',
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        [bool]$Task.Settings.StartWhenAvailable -and
        -not [bool]$Task.Settings.DisallowStartIfOnBatteries -and
        -not [bool]$Task.Settings.StopIfGoingOnBatteries -and
        [string]::Equals(
            [string]$Task.Settings.ExecutionTimeLimit,
            'PT5M',
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        [bool]$Task.Settings.Enabled -and
        -not [bool]$Task.Settings.Hidden -and
        -not [bool]$Task.Settings.RunOnlyIfIdle -and
        -not [bool]$Task.Settings.WakeToRun -and
        $trigger.Count -eq 1 -and [bool]$trigger[0].Enabled -and
        [string]::Equals(
            [string]$trigger[0].Repetition.Interval,
            "PT$([int]$ExpectedMinutes)M",
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        [string]::Equals(
            [string]$trigger[0].Repetition.Duration,
            $expectedRepetitionDuration,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        -not [bool]$trigger[0].Repetition.StopAtDurationEnd -and
        $startBoundaryValid -and
        [string]::Equals(
            [string]$Task.State,
            'Ready',
            [System.StringComparison]::OrdinalIgnoreCase
        )
}

function Invoke-ConsumerTaskUpgradeCore {
    param([int]$IntervalMinutes)

    $original = Get-ManagedUpgradeSource
    if (-not $original.valid) {
        throw "Refusing upgrade because the existing task is not the exact managed predecessor ($($original.validation))."
    }
    $registrationToken = [Guid]::NewGuid().ToString('N')
    $sourcePlan = @(Get-SourceBundlePlan)
    $bundle = New-ProtectedConsumerBundle $sourcePlan $registrationToken
    $candidate = New-ConsumerTaskCandidate `
        -Bundle $bundle `
        -RegistrationToken $registrationToken `
        -IntervalMinutes $IntervalMinutes `
        -StartDelayMinutes 10

    $preReplace = Get-ManagedUpgradeSource
    if (-not $preReplace.valid -or
        -not [string]::Equals(
            [string]$preReplace.task_xml,
            [string]$original.task_xml,
            [System.StringComparison]::Ordinal
        )) {
        throw 'Managed predecessor changed while preparing its replacement; refusing upgrade.'
    }

    $replaceAttempted = $false
    $ownedReplacementXml = ''
    try {
        $replaceAttempted = $true
        Register-ScheduledTask `
            -TaskName $taskName `
            -TaskPath $taskPath `
            -InputObject $candidate.definition `
            -Force | Out-Null
        if ([DateTimeOffset]::Now -ge [DateTimeOffset]::Parse(
                [string]$candidate.receipt_not_before,
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::RoundtripKind
            )) {
            throw 'Scheduled Task replacement did not finish before its first eligible run boundary.'
        }
        $registered = Get-ScheduledTask `
            -TaskName $taskName `
            -TaskPath $taskPath `
            -ErrorAction Stop
        if (-not (Test-OwnedUpgradeReplacement `
                $registered `
                $candidate `
                $bundle `
                $IntervalMinutes)) {
            throw 'Registered Scheduled Task did not read back as this invocation replacement.'
        }
        $ownedReplacementXml = [string](Export-ScheduledTask `
                -TaskName $taskName `
                -TaskPath $taskPath `
                -ErrorAction Stop)
        $readback = Get-ConsumerTaskAudit `
            -ExpectedMinutes $IntervalMinutes `
            -ExpectedRegistrationToken $registrationToken
        if (-not $readback.installation_valid) {
            throw 'Upgraded Scheduled Task readback did not match the exact new consumer contract.'
        }
        $readback.status = 'upgraded_pending_first_run'
        $readback.valid = $false
        if ($readback.PSObject.Properties.Name -contains 'health_valid') {
            $readback.health_valid = $false
        }
        if ($readback.PSObject.Properties.Name -contains 'consumer_health') {
            $readback.consumer_health = 'pending_first_new_release_run'
        }
        return $readback
    }
    catch {
        $upgradeFailure = $_
        if (-not $replaceAttempted) {
            throw $upgradeFailure
        }
        $current = Get-ScheduledTask `
            -TaskName $taskName `
            -TaskPath $taskPath `
            -ErrorAction SilentlyContinue
        $restoreRequired = $null -eq $current
        if ($null -ne $current) {
            $currentXml = [string](Export-ScheduledTask `
                    -TaskName $taskName `
                    -TaskPath $taskPath `
                    -ErrorAction Stop)
            if ([string]::Equals(
                    $currentXml,
                    [string]$original.task_xml,
                    [System.StringComparison]::Ordinal
                )) {
                throw $upgradeFailure
            }
            $currentIsOwnedReplacement = Test-OwnedUpgradeReplacement `
                $current `
                $candidate `
                $bundle `
                $IntervalMinutes
            if (-not $currentIsOwnedReplacement -or
                (-not [string]::IsNullOrEmpty($ownedReplacementXml) -and
                    -not [string]::Equals(
                    $currentXml,
                    $ownedReplacementXml,
                    [System.StringComparison]::Ordinal
                ))) {
                throw 'Scheduled Task changed to an unowned identity during upgrade; refusing rollback overwrite.'
            }
            if ([string]::IsNullOrEmpty($ownedReplacementXml)) {
                $ownedReplacementXml = $currentXml
            }
            $restoreRequired = $true
        }
        if ($restoreRequired) {
            try {
                if ($null -eq $current) {
                    Register-ScheduledTask `
                        -TaskName $taskName `
                        -TaskPath $taskPath `
                        -Xml ([string]$original.task_xml) | Out-Null
                } else {
                    Register-ScheduledTask `
                        -TaskName $taskName `
                        -TaskPath $taskPath `
                        -Xml ([string]$original.task_xml) `
                        -Force | Out-Null
                }
            }
            catch {
                throw "Scheduled Task upgrade rollback registration failed: $($_.Exception.Message)"
            }
            $restored = Get-ManagedUpgradeSource
            if (-not $restored.valid -or
                -not [string]::Equals(
                    [string]$restored.task_xml,
                    [string]$original.task_xml,
                    [System.StringComparison]::Ordinal
                )) {
                throw 'Scheduled Task upgrade rollback did not restore the exact predecessor definition.'
            }
        }
        throw $upgradeFailure
    }
}

function Enter-ConsumerTaskMutationMutex {
    $mutex = [System.Threading.Mutex]::new($false, $mutationMutexName)
    try {
        try {
            $acquired = $mutex.WaitOne(0)
        }
        catch [System.Threading.AbandonedMutexException] {
            $acquired = $true
        }
        if (-not $acquired) {
            throw 'Another managed consumer task mutation is already active.'
        }
        return $mutex
    }
    catch {
        $mutex.Dispose()
        throw
    }
}

$mutationMutex = $null
if ($Apply -or $Upgrade -or $Remove) {
    $mutationMutex = Enter-ConsumerTaskMutationMutex
}

try {

if ($Upgrade) {
    $upgradeResult = Invoke-ConsumerTaskUpgradeCore -IntervalMinutes $Minutes
    $upgradeResult | ConvertTo-Json -Depth 5
    exit 0
}

if ($Apply) {
    $existing = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        $existingAudit = Get-ConsumerTaskAudit -ExpectedMinutes $Minutes -ExpectedRegistrationToken ''
        if (-not $existingAudit.installation_valid) {
            throw 'Refusing to overwrite an existing same-named Scheduled Task whose exact contract has drifted.'
        }
        $existingAudit.status = if ($existingAudit.valid) {
            'already_installed_valid'
        } else {
            'already_installed_degraded'
        }
        $existingAudit | ConvertTo-Json -Depth 5
        if ($existingAudit.valid) {
            exit 0
        }
        exit 2
    }
    $registrationToken = [Guid]::NewGuid().ToString('N')
    $sourcePlan = @(Get-SourceBundlePlan)
    $bundle = New-ProtectedConsumerBundle $sourcePlan $registrationToken
    $candidate = New-ConsumerTaskCandidate `
        -Bundle $bundle `
        -RegistrationToken $registrationToken `
        -IntervalMinutes $Minutes
    $createdDescription = [string]$candidate.description
    $definition = $candidate.definition
    $createdThisInvocation = $false
    try {
        Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -InputObject $definition | Out-Null
        $createdThisInvocation = $true
        $result = Get-ConsumerTaskAudit `
            -ExpectedMinutes $Minutes `
            -ExpectedRegistrationToken $registrationToken
        if (-not $result.installation_valid) {
            throw 'Scheduled Task readback did not match the exact consumer contract.'
        }
        if (-not $result.valid) {
            $result.status = 'installed_pending_first_run'
        }
        $result | ConvertTo-Json -Depth 5
        exit 0
    }
    catch {
        $applyFailure = $_
        if ($createdThisInvocation) {
            $rollbackCandidate = Get-ScheduledTask `
                -TaskName $taskName `
                -TaskPath $taskPath `
                -ErrorAction SilentlyContinue
            if ($null -ne $rollbackCandidate) {
                if (-not [string]::Equals(
                        [string]$rollbackCandidate.Description,
                        $createdDescription,
                        [System.StringComparison]::Ordinal
                    )) {
                    throw 'Scheduled Task changed identity after registration; refusing rollback deletion.'
                }
                Unregister-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Confirm:$false
            }
            if ($null -ne (Get-ScheduledTask `
                        -TaskName $taskName `
                        -TaskPath $taskPath `
                        -ErrorAction SilentlyContinue)) {
                throw 'Scheduled Task apply rollback did not read back absent.'
            }
        }
        throw $applyFailure
    }
}

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        [ordered]@{
            schema_version = 's.context_rollout_consumer.install_audit.v1'
            status = 'already_absent'
            task_name = $taskName
            task_path = $taskPath
            authority = $false
        } | ConvertTo-Json -Depth 5
        exit 0
    }
    $auditResult = Get-ConsumerTaskAudit -ExpectedMinutes $null -ExpectedRegistrationToken ''
    if (-not $auditResult.contract_valid) {
        throw 'Refusing to remove a same-named Scheduled Task whose exact contract has drifted.'
    }
    Unregister-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Confirm:$false
    if ($null -ne (Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue)) {
        throw 'Scheduled Task removal readback failed.'
    }
    [ordered]@{
        schema_version = 's.context_rollout_consumer.install_audit.v1'
        status = 'removed'
        task_name = $taskName
        task_path = $taskPath
        authority = $false
    } | ConvertTo-Json -Depth 5
    exit 0
}

$auditResult = Get-ConsumerTaskAudit -ExpectedMinutes $null -ExpectedRegistrationToken ''
$auditResult | ConvertTo-Json -Depth 5
if (-not $auditResult.valid) {
    exit 2
}
exit 0
}
finally {
    if ($null -ne $mutationMutex) {
        $mutationMutex.ReleaseMutex()
        $mutationMutex.Dispose()
    }
}
