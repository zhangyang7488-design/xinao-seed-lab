[CmdletBinding()]
param(
    [string]$Root = 'D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric',
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$expectedRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric'
$resolved = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
if (-not [string]::Equals($resolved, $expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing ACL operation outside the exact S Context Fabric root: $resolved"
}
$item = Get-Item -LiteralPath $resolved -Force
if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Context Fabric root must be a real non-link directory.'
}

$currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$expectedSids = @(
    $currentSid,
    [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
    [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
)
$inheritance = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
$propagation = [System.Security.AccessControl.PropagationFlags]::None
$allow = [System.Security.AccessControl.AccessControlType]::Allow
$fullControl = [System.Security.AccessControl.FileSystemRights]::FullControl

if ($Apply) {
    $acl = Get-Acl -LiteralPath $resolved
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) {
        [void]$acl.RemoveAccessRuleSpecific($rule)
    }
    foreach ($sid in $expectedSids) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            $fullControl,
            $inheritance,
            $propagation,
            $allow
        )
        $acl.SetAccessRule($rule)
    }
    Set-Acl -LiteralPath $resolved -AclObject $acl
}

$readback = Get-Acl -LiteralPath $resolved
$allowRules = @(
    $readback.Access | Where-Object AccessControlType -eq 'Allow'
)
$normalizedAllowRules = @(
    $allowRules | ForEach-Object {
        [pscustomobject]@{
            Sid = $_.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value
            Rights = $_.FileSystemRights
            Inheritance = $_.InheritanceFlags
            Propagation = $_.PropagationFlags
        }
    }
)
$allowSids = @($normalizedAllowRules | ForEach-Object Sid | Sort-Object -Unique)
$expectedValues = @($expectedSids | ForEach-Object Value | Sort-Object -Unique)
$unexpected = @($allowSids | Where-Object { $_ -notin $expectedValues })
$missing = @($expectedValues | Where-Object { $_ -notin $allowSids })
$missingFullControl = @()
foreach ($expectedSid in $expectedValues) {
    $matching = @(
        $normalizedAllowRules | Where-Object {
            $_.Sid -eq $expectedSid -and
            ($_.Rights -band $fullControl) -eq $fullControl -and
            ($_.Inheritance -band $inheritance) -eq $inheritance -and
            $_.Propagation -eq $propagation
        }
    )
    if ($matching.Count -eq 0) {
        $missingFullControl += $expectedSid
    }
}
$compliant = (
    $readback.AreAccessRulesProtected -and
    $unexpected.Count -eq 0 -and
    $missing.Count -eq 0 -and
    $missingFullControl.Count -eq 0
)

[ordered]@{
    schema_version = 's.context_fabric_acl.v1'
    root = $resolved
    apply_requested = [bool]$Apply
    inheritance_protected = $readback.AreAccessRulesProtected
    allowed_identities = @(
        $readback.Access |
            Where-Object AccessControlType -eq 'Allow' |
            ForEach-Object IdentityReference |
            ForEach-Object Value |
            Sort-Object -Unique
    )
    unexpected_allow_count = $unexpected.Count
    missing_expected_count = $missing.Count
    missing_full_control_count = $missingFullControl.Count
    compliant = $compliant
} | ConvertTo-Json -Depth 5

if (-not $compliant) {
    exit 1
}
