#Requires -Version 5.1
<#
.SYNOPSIS
  解析 compose 拼音机器名 + 中文显示名。
  优先 S 仓权威；S 脚本/JSON 缺失时回退 Grok 岛本地 loader（防 Pulse/GapScan 自锁）。
#>
param(
    [string]$ConfigPath = "",
    [string]$Key = ""
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }

$sRepo = ""
$materialsFromConfig = ""
if (Test-Path -LiteralPath $ConfigPath) {
    $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $sRepo = [string]$config.repo_root
    if ($config.grok_codex_s_native_temporal_route) {
        $materialsFromConfig = [string]$config.grok_codex_s_native_temporal_route.compose_display_names
    }
}

# 1) S 仓官方 loader（若仍在）
$sLoader = $null
if ($sRepo) {
    $candidate = Join-Path $sRepo "scripts\Get-XinaoComposeDisplayNames.ps1"
    if (Test-Path -LiteralPath $candidate) { $sLoader = $candidate }
}

# 2) 岛内 loader（永远应在）
$islandLoader = Join-Path $bridge "Get-XinaoComposeDisplayNames.ps1"

if ($sLoader) {
    if ($Key) {
        return & $sLoader -RepoRoot $sRepo -Key $Key
    }
    return & $sLoader -RepoRoot $sRepo
}

if (-not (Test-Path -LiteralPath $islandLoader)) {
    throw "Compose display loader missing on island: $islandLoader (and S loader absent)"
}

$matArg = ""
if ($materialsFromConfig -and (Test-Path -LiteralPath $materialsFromConfig)) {
    $matArg = $materialsFromConfig
}

if ($Key) {
    if ($matArg) {
        return & $islandLoader -RepoRoot $sRepo -MaterialsPath $matArg -Key $Key
    }
    return & $islandLoader -RepoRoot $sRepo -Key $Key
}

if ($matArg) {
    return & $islandLoader -RepoRoot $sRepo -MaterialsPath $matArg
}
return & $islandLoader -RepoRoot $sRepo
