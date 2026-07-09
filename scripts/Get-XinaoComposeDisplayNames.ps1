#Requires -Version 5.1
<#
.SYNOPSIS
  读取 compose 中文显示名 + 机器 slug；脚本统一从此取容器名，勿硬编码 xinao-worker。
#>
param(
    [string]$RepoRoot = "",
    [string]$Key = ""
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) {
    $RepoRoot = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
}
$path = Join-Path $RepoRoot "materials\xinao_compose_display_names.v1.json"
if (-not (Test-Path -LiteralPath $path)) {
    throw "compose display names missing: $path"
}
$doc = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json

function Get-SlugSet([object]$Svc) {
    $set = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    [void]$set.Add([string]$Svc.container_name)
    [void]$set.Add([string]$Svc.compose_service)
    foreach ($l in @($Svc.legacy_slugs)) { if ($l) { [void]$set.Add([string]$l) } }
    return $set
}

$map = [ordered]@{}
foreach ($prop in $doc.services.PSObject.Properties) {
    $id = $prop.Name
    $svc = $prop.Value
    $map[$id] = [ordered]@{
        id              = $id
        display_cn      = [string]$svc.display_cn
        role_cn         = [string]$svc.role_cn
        compose_service = [string]$svc.compose_service
        container_name  = [string]$svc.container_name
        legacy_slugs    = @($svc.legacy_slugs)
        slug_set        = @(Get-SlugSet $svc)
    }
}

$worker = $map["houtai-gongren"]
$out = [ordered]@{
    schema_version   = [string]$doc.schema_version
    path             = $path
    stack_display_cn = [string]$doc.stack_display_cn
    worker           = $worker
    worker_container = [string]$worker.container_name
    worker_display_cn = [string]$worker.display_cn
    services         = $map
}

function Test-NamesMatch([string]$DockerPsText, [object]$Svc) {
    foreach ($slug in $Svc.slug_set) {
        if ($DockerPsText -match [regex]::Escape($slug)) { return $true }
    }
    return $false
}

$out.test_match_fn = "Test-NamesMatch"
if ($Key) {
    if (-not $map.Contains($Key)) { throw "Unknown compose name key: $Key" }
    return $map[$Key]
}
return $out