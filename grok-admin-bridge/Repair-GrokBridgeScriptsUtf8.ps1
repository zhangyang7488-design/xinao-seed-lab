# Ensures grok-admin-bridge *.ps1 are UTF-8 with BOM for Windows PowerShell 5.1 (Chinese Windows).
param(
    [string]$BridgeRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $BridgeRoot) {
    $BridgeRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
}
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$utf8Bom = [System.Text.UTF8Encoding]::new($true)

$fixed = [System.Collections.Generic.List[string]]::new()
$skipped = [System.Collections.Generic.List[string]]::new()

Get-ChildItem -LiteralPath $BridgeRoot -Filter "*.ps1" -File | ForEach-Object {
    $path = $_.FullName
    $bytes = [System.IO.File]::ReadAllBytes($path)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    if ($hasBom) {
        $skipped.Add($_.Name)
        return
    }
    $text = $utf8NoBom.GetString($bytes)
    if ($text.StartsWith([char]0xFEFF)) {
        $text = $text.Substring(1)
    }
    [System.IO.File]::WriteAllText($path, $text, $utf8Bom)
    $fixed.Add($_.Name)
}

[ordered]@{
    schema_version = "xinao.grok_bridge_utf8_repair.v1"
    status         = "ok"
    bridge_root    = $BridgeRoot
    fixed_files    = @($fixed)
    skipped_bom_ok = @($skipped)
    note_cn        = "Windows PowerShell 5.1 requires UTF-8 BOM to parse Chinese string literals in .ps1"
} | ConvertTo-Json -Depth 6