#Requires -Version 5.1
<#
.SYNOPSIS
  XINAO glue gap fill: registry repos -> shallow clone into EXTERNAL_MATURE official mirror.
.NOT_333_MAINLINE
#>
param(
    [string]$RegistryPath = "E:\XINAO_RESEARCH_WORKSPACES\S\materials\authority_glue\glue_mature_repo_registry.v1.json",
    [string]$OfficialRoot = "E:\XINAO_EXTERNAL_MATURE\codex_20260627\official",
    [string]$CommunityRoot = "E:\XINAO_EXTERNAL_MATURE\codex_20260627\community",
    [string]$CloneLog = "E:\XINAO_EXTERNAL_MATURE\codex_20260627\manifests\clone_status.jsonl",
    [string]$EvidenceRoot = "D:\XINAO_RESEARCH_RUNTIME\glue_gap_fill",
    [switch]$SkipLarge,
    [switch]$IncludeWiringSuspended,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$largeRepos = @("duckdb/duckdb", "OpenHands/OpenHands", "searxng/searxng")

function Get-DirName([string]$Repo) { $Repo -replace "/", "__" }

function Test-RepoPresent([string]$Repo) {
    $d = Get-DirName $Repo
    @($OfficialRoot, $CommunityRoot) | ForEach-Object {
        $p = Join-Path $_ $d
        if (Test-Path $p) { return $p }
    }
    return $null
}

$json = Get-Content -LiteralPath $RegistryPath -Raw | ConvertFrom-Json
$seen = @{}
$queue = [System.Collections.Generic.List[object]]::new()

foreach ($layerProp in $json.layers.PSObject.Properties) {
    $layer = $layerProp.Name
    foreach ($item in $json.layers.$layer) {
        if (-not $item.url -or $item.url -notlike "https://github.com/*") { continue }
        if ($item.'接线暂缓' -and -not $IncludeWiringSuspended) { continue }
        if ($item.optional -and $item.repo -eq "tavily-ai/tavily-python") { continue }
        if ($seen.ContainsKey($item.repo)) { continue }
        $seen[$item.repo] = $true
        if (Test-RepoPresent $item.repo) { continue }
        if ($SkipLarge -and ($largeRepos -contains $item.repo)) { continue }
        $queue.Add([pscustomobject]@{ layer = $layer; repo = $item.repo; url = $item.url })
    }
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$evidenceDir = Join-Path $EvidenceRoot "registry-gap-fill-$ts"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

$results = @()
foreach ($job in $queue) {
    $destName = Get-DirName $job.repo
    $dest = Join-Path $OfficialRoot $destName
    $entry = [ordered]@{
        time      = (Get-Date).ToString("o")
        layer     = $job.layer
        fullName  = $job.repo
        url       = $job.url
        dest      = $dest
        phase     = "official_registry_gap"
        status    = "pending"
        exitCode  = $null
    }
    if ($DryRun) {
        $entry.status = "dry_run"
        $results += [pscustomobject]$entry
        continue
    }
    if (Test-Path $dest) {
        $entry.status = "exists"
        $results += [pscustomobject]$entry
        continue
    }
    New-Item -ItemType Directory -Force -Path $OfficialRoot | Out-Null
    Write-Host "Cloning $($job.repo) -> $dest"
    & git clone --depth 1 $job.url $dest 2>&1 | Out-Host
    $code = $LASTEXITCODE
    $entry.exitCode = $code
    $entry.status = if ($code -eq 0) { "cloned" } else { "failed" }
    $line = ($entry | ConvertTo-Json -Compress)
    Add-Content -LiteralPath $CloneLog -Value $line -Encoding UTF8
    $results += [pscustomobject]$entry
}

$report = [ordered]@{
    schema_version = "xinao.glue_registry_gap_fill.v1"
    sentinel       = "SENTINEL:XINAO_GLUE_REGISTRY_GAP_FILL"
    generated_at   = (Get-Date).ToString("o")
    registry       = $RegistryPath
    queued         = $queue.Count
    results        = $results
    skip_large     = [bool]$SkipLarge
    dry_run        = [bool]$DryRun
}
$reportPath = Join-Path $evidenceDir "gap_fill_report.json"
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Host "Report: $reportPath"
$report | ConvertTo-Json -Depth 6