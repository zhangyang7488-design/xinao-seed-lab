#Requires -Version 5.1
<#
.SYNOPSIS
  Thin light research loop for Grok 4.5 (NOT 333 RootIntentLoop).
  External mature shape: local rg/disk first, optional web notes, evidence to D.
#>
[CmdletBinding()]
param(
    [ValidateSet('local_only', 'local_then_web_notes')]
    [string]$Mode = 'local_only',
    [Parameter(Mandatory = $true)]
    [string]$Objective,
    [string]$LocalQuery = '',
    [string]$Root = 'C:\Users\xx363\Grok_Admin_Isolated\workspace-grok-4.5-island',
    [string]$EvidenceOut = ''
)

$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding $false
$stateDir = 'D:\XINAO_RESEARCH_RUNTIME\state\grok_light_research'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
if (-not $EvidenceOut) {
    $EvidenceOut = Join-Path $stateDir ("latest_{0}.json" -f (Get-Date -Format 'yyyyMMddTHHmmss'))
}
if (-not $LocalQuery) { $LocalQuery = $Objective }

$hits = @()
$roots = @(
    $Root,
    'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination',
    'D:\XINAO_RESEARCH_RUNTIME\state',
    'C:\Users\xx363\Desktop\新建文件夹'
) | Where-Object { Test-Path $_ }

foreach ($r in $roots) {
    try {
        $found = Get-ChildItem -LiteralPath $r -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match [regex]::Escape(($LocalQuery -split '\s+')[0]) -or $_.FullName -match 'work_pool|coordination|capability' } |
            Select-Object -First 15 FullName, Length, LastWriteTime
        foreach ($f in $found) {
            $hits += [ordered]@{ root = $r; path = $f.FullName; length = $f.Length; mtime = $f.LastWriteTime.ToString('o') }
        }
    } catch {
        # continue other roots
    }
}

$result = [ordered]@{
    schema_version           = 'xinao.grok_light_research_loop.v1'
    mode                     = $Mode
    objective                = $Objective
    local_query              = $LocalQuery
    generated_at             = (Get-Date).ToString('o')
    not_333_mainline         = $true
    completion_claim_allowed = $false
    hit_count                = $hits.Count
    hits                     = $hits
    next_cn                  = @(
        '本环只做轻检索+落证，不替代 WebSearch 原生工具',
        '深研请主会话用 web_search / 子代理 explore',
        '量产 Task 才走 promote + Temporal'
    )
}

[System.IO.File]::WriteAllText($EvidenceOut, ($result | ConvertTo-Json -Depth 8), $utf8)
$latest = Join-Path $stateDir 'latest.json'
[System.IO.File]::WriteAllText($latest, ($result | ConvertTo-Json -Depth 8), $utf8)
Write-Output $EvidenceOut
$result | ConvertTo-Json -Depth 6
exit 0
