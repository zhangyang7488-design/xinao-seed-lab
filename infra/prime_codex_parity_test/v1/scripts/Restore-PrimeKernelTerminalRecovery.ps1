#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Target = 'D:\XINAO_RESEARCH_RUNTIME\tools\prime-agent\0.7.0\node_modules\prime-agent\dist\core\tools\ipython.js',
    [string]$Backup = 'D:\XINAO_RESEARCH_RUNTIME\state\prime-agent\islands\local-cognition-account-b\known-good\pre-codex-pis-closure-20260808T0906+0800\runtime\prime-agent\dist\core\tools\ipython.js'
)

$ErrorActionPreference = 'Stop'
$preHash = '2289467E28B6F817EDFC65B0E5AA77382B193920323B9AEF95FBDC82812975BD'
$postHash = 'C3937FE213A747591FBE10F380AD7D27B911F47209A2E0BCB71566A3402ECD3F'
if (-not (Test-Path -LiteralPath $Backup -PathType Leaf)) { throw "PRIME_KERNEL_PATCH_BACKUP_MISSING: $Backup" }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Backup).Hash -ne $preHash) { throw 'PRIME_KERNEL_PATCH_BACKUP_HASH_MISMATCH' }
if (Test-Path -LiteralPath $Target -PathType Leaf) {
    $observed = (Get-FileHash -Algorithm SHA256 -LiteralPath $Target).Hash
    if ($observed -eq $preHash) { [pscustomobject]@{status='already_restored';target=$Target;sha256=$observed}; exit 0 }
    if ($observed -ne $postHash) { throw "PRIME_KERNEL_PATCH_REFUSE_UNKNOWN_TARGET: $observed" }
}
Copy-Item -LiteralPath $Backup -Destination $Target -Force
$after = (Get-FileHash -Algorithm SHA256 -LiteralPath $Target).Hash
if ($after -ne $preHash) { throw 'PRIME_KERNEL_PATCH_RESTORE_READBACK_FAILED' }
[pscustomobject]@{status='restored';target=$Target;sha256=$after}
