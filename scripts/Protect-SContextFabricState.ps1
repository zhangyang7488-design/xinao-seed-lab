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

if ($Apply) {
    $acl = Get-Acl -LiteralPath $resolved
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) {
        [void]$acl.RemoveAccessRuleSpecific($rule)
    }
    $inheritance = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $fullControl = [System.Security.AccessControl.FileSystemRights]::FullControl
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
$allowSids = @(
    $readback.Access |
        Where-Object AccessControlType -eq 'Allow' |
        ForEach-Object {
            $_.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value
        } |
        Sort-Object -Unique
)
$expectedValues = @($expectedSids | ForEach-Object Value | Sort-Object -Unique)
$unexpected = @($allowSids | Where-Object { $_ -notin $expectedValues })
$missing = @($expectedValues | Where-Object { $_ -notin $allowSids })
$compliant = $readback.AreAccessRulesProtected -and $unexpected.Count -eq 0 -and $missing.Count -eq 0

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
    compliant = $compliant
} | ConvertTo-Json -Depth 5

if (-not $compliant) {
    exit 1
}
