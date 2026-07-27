#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "GrokWindowsPathIdentity.ps1")

function Assert-PathIdentity([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "PATH_IDENTITY_TEST_FAILED: $Name" }
    Write-Output "PASS: $Name"
}

$testRoot = Join-Path "D:\XINAO_RESEARCH_RUNTIME\tmp" (
    "grok-path-identity-" + [guid]::NewGuid().ToString("N")
)
$physical = Join-Path $testRoot "physical"
$junction = Join-Path $testRoot "junction"
$alien = Join-Path $testRoot "alien"
New-Item -ItemType Directory -Force -Path $physical, $alien | Out-Null
[void](New-Item -ItemType Junction -Path $junction -Target $physical)
$longPhysical = $physical
while ($longPhysical.Length -le 270) {
    $longPhysical = Join-Path $longPhysical "long-path-segment-0123456789"
}
New-Item -ItemType Directory -Force -Path $longPhysical | Out-Null

$junctionLease = Open-GrokDirectoryIdentityLease -Path $junction
$physicalLease = Open-GrokDirectoryIdentityLease -Path $physical
$alienLease = Open-GrokDirectoryIdentityLease -Path $alien
$longLease = $null
try {
    $longLease = Open-GrokDirectoryIdentityLease -Path $longPhysical
    Assert-PathIdentity ($longPhysical.Length -gt 260) "long_path_exceeds_legacy_max_path"
    Assert-PathIdentity (
        Assert-GrokDirectoryIdentityLeaseStable -Lease $longLease
    ) "long_path_identity_lease_is_stable"
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
    if ($null -ne $longLease) { Close-GrokDirectoryIdentityLease -Lease $longLease }
    Close-GrokDirectoryIdentityLease -Lease $junctionLease
    Close-GrokDirectoryIdentityLease -Lease $physicalLease
    Close-GrokDirectoryIdentityLease -Lease $alienLease
    if (Test-Path -LiteralPath $testRoot -PathType Container) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
