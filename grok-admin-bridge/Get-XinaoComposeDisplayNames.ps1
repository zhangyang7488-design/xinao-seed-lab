#Requires -Version 5.1
<#
.SYNOPSIS
  读 compose 拼音机器名 + 中文 display_cn。
  Grok 岛自带副本：S 仓 scripts/materials 缺失时仍可解析，避免 Pulse 自锁。
#>
param(
    [string]$RepoRoot = "",
    [string]$MaterialsPath = "",
    [string]$Key = ""
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot

function ConvertTo-ServiceMap([object]$RawServices) {
    $map = [ordered]@{}
    if ($null -eq $RawServices) { return $map }
    if ($RawServices -is [System.Collections.IDictionary]) {
        foreach ($k in $RawServices.Keys) {
            $map[[string]$k] = $RawServices[$k]
        }
        return $map
    }
    foreach ($p in $RawServices.PSObject.Properties) {
        $map[[string]$p.Name] = $p.Value
    }
    return $map
}

function Resolve-MaterialsPath {
    if ($MaterialsPath -and (Test-Path -LiteralPath $MaterialsPath)) {
        return $MaterialsPath
    }
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($RepoRoot) {
        [void]$candidates.Add((Join-Path $RepoRoot "materials\xinao_compose_display_names.v1.json"))
    }
    [void]$candidates.Add((Join-Path $bridge "materials\xinao_compose_display_names.v1.json"))
    # bridge.config optional path
    $cfgPath = Join-Path $bridge "bridge.config.json"
    if (Test-Path -LiteralPath $cfgPath) {
        try {
            $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $fromCfg = [string]$cfg.grok_codex_s_native_temporal_route.compose_display_names
            if ($fromCfg) { [void]$candidates.Add($fromCfg) }
            $sRepo = [string]$cfg.repo_root
            if ($sRepo) {
                [void]$candidates.Add((Join-Path $sRepo "materials\xinao_compose_display_names.v1.json"))
            }
        } catch { }
    }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    return $null
}

$mat = Resolve-MaterialsPath
if (-not $mat) {
    # last-resort embedded defaults (must match HolographicGapScan keys)
    $services = [ordered]@{
        "shiwu-ku" = [ordered]@{
            container_name = "shiwu-ku"; display_cn = "事务库"
            slug_set = @("shiwu-ku"); legacy_slugs = @("postgres", "xinao-postgres")
        }
        "houtai-gongren" = [ordered]@{
            container_name = "houtai-gongren"; display_cn = "后台工人"
            slug_set = @("houtai-gongren"); legacy_slugs = @("xinao-worker")
        }
        "naijiu-shiwu" = [ordered]@{
            container_name = "naijiu-shiwu"; display_cn = "耐久事务"
            slug_set = @("naijiu-shiwu"); legacy_slugs = @("temporal", "xinao-temporal")
        }
        "moxing-wangguan" = [ordered]@{
            container_name = "moxing-wangguan"; display_cn = "模型网关"
            slug_set = @("moxing-wangguan"); legacy_slugs = @("litellm", "xinao-litellm")
        }
    }
    $result = [ordered]@{
        schema_version = "xinao.compose_display_names.v1"
        materials_path = $null
        materials_source = "embedded_fallback"
        services = $services
    }
} else {
    $raw = Get-Content -LiteralPath $mat -Raw -Encoding UTF8 | ConvertFrom-Json
    $services = ConvertTo-ServiceMap $raw.services
    $result = [ordered]@{
        schema_version = if ($raw.schema_version) { [string]$raw.schema_version } else { "xinao.compose_display_names.v1" }
        materials_path = $mat
        materials_source = "json_file"
        services = $services
    }
}

if ($Key) {
    $svcMap = $result.services
    if ($svcMap -is [System.Collections.IDictionary] -and $svcMap.Contains($Key)) {
        return $svcMap[$Key]
    }
    $prop = $svcMap.PSObject.Properties | Where-Object { $_.Name -eq $Key } | Select-Object -First 1
    if ($prop) { return $prop.Value }
    return $null
}

# ClaimDurable / 薄壳约定：扁平机器名（services map 之外的捷径）
function Get-ContainerNameFromMap([object]$Map, [string]$ServiceKey, [string]$Fallback) {
    if ($null -eq $Map) { return $Fallback }
    $entry = $null
    if ($Map -is [System.Collections.IDictionary] -and $Map.Contains($ServiceKey)) {
        $entry = $Map[$ServiceKey]
    } else {
        $prop = $Map.PSObject.Properties | Where-Object { $_.Name -eq $ServiceKey } | Select-Object -First 1
        if ($prop) { $entry = $prop.Value }
    }
    if ($null -eq $entry) { return $Fallback }
    if ($entry.container_name) { return [string]$entry.container_name }
    if ($entry.compose_service) { return [string]$entry.compose_service }
    return $Fallback
}

$result["worker_container"] = Get-ContainerNameFromMap $result.services "houtai-gongren" "houtai-gongren"
$result["temporal_container"] = Get-ContainerNameFromMap $result.services "naijiu-shiwu" "naijiu-shiwu"
$result["postgres_container"] = Get-ContainerNameFromMap $result.services "shiwu-ku" "shiwu-ku"
$result["temporal_ui_container"] = Get-ContainerNameFromMap $result.services "shiwu-mianban" "shiwu-mianban"

return $result
