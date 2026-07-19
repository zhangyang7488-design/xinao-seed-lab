#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "GrokWindowsPathIdentity.ps1")

function Assert-PathIdentity([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "PATH_IDENTITY_TEST_FAILED: $Name" }
    Write-Output "PASS: $Name"
}

$junction = "E:\XINAO_RESEARCH_WORKSPACES\S"
$physical = "E:\XINAO_RESEARCH_WORKSPACES\nianhua-new-route-active"
$alien = "D:\XINAO_RESEARCH_RUNTIME"

$junctionLease = Open-GrokDirectoryIdentityLease -Path $junction
$physicalLease = Open-GrokDirectoryIdentityLease -Path $physical
$alienLease = Open-GrokDirectoryIdentityLease -Path $alien
try {
    Assert-PathIdentity (
        Test-GrokDirectoryObjectIdentityEqual -Left $junctionLease -Right $physicalLease
    ) "junction_and_physical_are_same_directory_object"
    Assert-PathIdentity (-not (
        Test-GrokDirectoryObjectIdentityEqual -Left $junctionLease -Right $alienLease
    )) "alien_directory_object_is_rejected"
    Assert-PathIdentity (
        Assert-GrokDirectoryIdentityLeaseStable -Lease $junctionLease
    ) "junction_identity_lease_is_stable"
    Assert-PathIdentity (
        Assert-GrokDirectoryIdentityLeaseStable -Lease $physicalLease
    ) "physical_identity_lease_is_stable"
    Assert-PathIdentity (
        $junctionLease.object_id -eq $physicalLease.object_id
    ) "object_id_is_volume_and_file_identity"
}
finally {
    Close-GrokDirectoryIdentityLease -Lease $junctionLease
    Close-GrokDirectoryIdentityLease -Lease $physicalLease
    Close-GrokDirectoryIdentityLease -Lease $alienLease
}
