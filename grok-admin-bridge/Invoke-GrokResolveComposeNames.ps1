#Requires -Version 5.1
<#
.SYNOPSIS
  解析 compose 拼音机器名 + 中文显示名（读 S 仓 materials/xinao_compose_display_names.v1.json）
#>
param(
    [string]$ConfigPath = "",
    [string]$Key = ""
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sRepo = [string]$config.repo_root
$loader = Join-Path $sRepo "scripts\Get-XinaoComposeDisplayNames.ps1"
if (-not (Test-Path -LiteralPath $loader)) { throw "Get-XinaoComposeDisplayNames.ps1 missing: $loader" }
if ($Key) {
    return & $loader -RepoRoot $sRepo -Key $Key
}
return & $loader -RepoRoot $sRepo