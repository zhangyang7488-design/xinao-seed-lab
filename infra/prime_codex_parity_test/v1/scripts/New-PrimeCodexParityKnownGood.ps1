#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PrimeParity.Common.ps1')

$static = Read-PrimeParityJson -Path (Join-Path $script:PrimeParityRuntimeRoot 'validation\static-latest.json')
if ($static.status -ne 'verified') { throw 'PRIME_PARITY_KNOWN_GOOD_REQUIRES_VERIFIED_STATIC_ACCEPTANCE' }
$behaviorPath = Join-Path $script:PrimeParityRuntimeRoot 'validation\behavior-latest.json'
if (Test-Path -LiteralPath $behaviorPath -PathType Leaf) {
    $behavior = Read-PrimeParityJson -Path $behaviorPath
    if ($behavior.status -ne 'verified') { throw 'PRIME_PARITY_KNOWN_GOOD_BEHAVIOR_ACCEPTANCE_NOT_VERIFIED' }
}

$stamp = Get-Date -Format 'yyyyMMddTHHmmssK'
$stamp = $stamp.Replace(':','')
$root = 'D:\XINAO_RESEARCH_RUNTIME\state\prime-agent\known-good'
$destination = Join-Path $root "prime-codex-parity-test-v1-$stamp"
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item -LiteralPath $script:PrimeParitySourceRoot -Destination (Join-Path $destination 'source') -Recurse -Force
$runtimeProjection = Join-Path $destination 'runtime-nonsecret'
New-Item -ItemType Directory -Force -Path $runtimeProjection | Out-Null
foreach ($name in @('extension','overlay','bindings','validation')) {
    Copy-Item -LiteralPath (Join-Path $script:PrimeParityRuntimeRoot $name) -Destination (Join-Path $runtimeProjection $name) -Recurse -Force
}
foreach ($name in @('active-account.json','conversation-binding.json')) {
    Copy-Item -LiteralPath (Join-Path $script:PrimeParityRuntimeRoot $name) -Destination (Join-Path $runtimeProjection $name) -Force
}
$secretFiles = @(Get-ChildItem -LiteralPath $destination -Recurse -File -Filter 'auth.json' -ErrorAction SilentlyContinue)
if ($secretFiles.Count -gt 0) { throw 'PRIME_PARITY_KNOWN_GOOD_SECRET_EXCLUSION_FAILED' }

$records = @(Get-ChildItem -LiteralPath $destination -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
    [ordered]@{
        relative_path = $_.FullName.Substring($destination.Length + 1)
        length = $_.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
    }
})
$manifest = [ordered]@{
    schema = 'xinao.prime_codex_parity.known_good.v1'
    created_at = (Get-Date).ToString('o')
    source = $script:PrimeParitySourceRoot
    runtime = $script:PrimeParityRuntimeRoot
    durable_session_id = (Get-PrimeParityConversationBinding).durable_session_id
    includes_session_history = $false
    includes_authentication = $false
    recovery_entry = 'source\scripts\Restore-PrimeCurrentMode.ps1'
    files = $records
}
Write-PrimeParityJsonAtomic -Path (Join-Path $destination 'manifest.json') -Value $manifest -Depth 16
Write-PrimeParityJsonAtomic -Path (Join-Path $root 'prime-codex-parity-test-v1-latest.json') -Value ([ordered]@{
    schema = 'xinao.prime_codex_parity.known_good_pointer.v1'
    path = $destination
    manifest = (Join-Path $destination 'manifest.json')
    updated_at = (Get-Date).ToString('o')
})
$manifest | ConvertTo-Json -Depth 8
