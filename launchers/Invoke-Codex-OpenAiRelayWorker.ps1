#Requires -Version 7.0

$ErrorActionPreference = "Stop"
$pointerPath = "D:\XINAO_RESEARCH_RUNTIME\state\codex_openai_relay_releases\current.json"
if (-not (Test-Path -LiteralPath $pointerPath -PathType Leaf)) {
    throw "CODEX_OPENAI_RELAY_RELEASE_POINTER_MISSING: $pointerPath"
}
$pointer = Get-Content -LiteralPath $pointerPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$pointer.schema_version -ne "xinao.codex_openai_relay_release_pointer.v1") {
    throw "CODEX_OPENAI_RELAY_RELEASE_POINTER_SCHEMA_INVALID"
}
$dispatch = [string]$pointer.dispatch_ref
if (-not (Test-Path -LiteralPath $dispatch -PathType Leaf)) {
    throw "CODEX_OPENAI_RELAY_RELEASE_DISPATCH_MISSING: $dispatch"
}
$observed = (Get-FileHash -LiteralPath $dispatch -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not [string]::Equals($observed, [string]$pointer.dispatch_sha256, [StringComparison]::Ordinal)) {
    throw "CODEX_OPENAI_RELAY_RELEASE_DISPATCH_HASH_MISMATCH"
}
& $dispatch @args
exit $LASTEXITCODE
