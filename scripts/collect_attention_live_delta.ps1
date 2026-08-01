#Requires -Version 5.1
<#
.SYNOPSIS
  Thin, read-only attention live-delta facts for Codex Owner reconsideration.

.DESCRIPTION
  Emits a compact text packet of cheap, deterministic local facts only:
  current generation / release_id / source_commit (if present), installed skill
  entry existence, and config/auth/hooks handle existence.

  Does NOT: run git, start Python/Docker/xinao inspect/network, hash facets,
  persist baseline, invent owner_source_tip / PR refs, bind any human TXT
  reports, or classify DUPLICATE/UNIQUE_DELTA. Exists != consumer READY.
  Fail-open: exceptions print LIVE_DELTA_UNAVAILABLE and exit 0.

  Why not Get-CodexLocalStateSense.ps1: that script probes codex CLI features /
  plugins / workspace git and does not surface xinao current generation/release;
  calling it would be thicker and still miss the required fields.
#>
[CmdletBinding()]
param(
    [string]$CodexHome = "",
    [string]$XinaoStateRoot = "",
    [string]$InstalledSkillRoot = ""
)

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

function Resolve-Paths {
    param(
        [string]$CodexHomeIn,
        [string]$XinaoStateRootIn,
        [string]$InstalledSkillRootIn
    )
    $codex = if (-not [string]::IsNullOrWhiteSpace($CodexHomeIn)) {
        $CodexHomeIn
    } elseif ($env:CODEX_HOME) {
        $env:CODEX_HOME
    } else {
        Join-Path $env:USERPROFILE ".codex"
    }

    $xinaoState = if (-not [string]::IsNullOrWhiteSpace($XinaoStateRootIn)) {
        $XinaoStateRootIn
    } elseif ($env:XINAO_SKILL_STATE_ROOT) {
        $env:XINAO_SKILL_STATE_ROOT
    } else {
        "D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill"
    }

    $skillRoot = if (-not [string]::IsNullOrWhiteSpace($InstalledSkillRootIn)) {
        $InstalledSkillRootIn
    } elseif ($env:XINAO_INSTALLED_SKILL_ROOT) {
        $env:XINAO_INSTALLED_SKILL_ROOT
    } else {
        Join-Path $codex "skills\xinao"
    }

    return [ordered]@{
        CodexHome          = $codex
        XinaoStateRoot     = $xinaoState
        InstalledSkillRoot = $skillRoot
    }
}

function Test-LeafExistsLabel {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path -PathType Leaf) { "exists" } else { "missing" }
}

try {
    $paths = Resolve-Paths -CodexHomeIn $CodexHome -XinaoStateRootIn $XinaoStateRoot `
        -InstalledSkillRootIn $InstalledSkillRoot

    $currentPath = Join-Path $paths.XinaoStateRoot "researcher_container\current.json"
    $generation = ""
    $releaseId = ""
    $sourceCommit = ""
    $currentStatus = "missing"

    if (Test-Path -LiteralPath $currentPath -PathType Leaf) {
        try {
            $current = Get-Content -LiteralPath $currentPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($null -ne $current.generation) { $generation = [string]$current.generation }
            if ($current.active -and $current.active.release_id) {
                $releaseId = [string]$current.active.release_id
            }
            $manifestPath = $null
            if ($current.active -and $current.active.release_manifest_path) {
                $manifestPath = [string]$current.active.release_manifest_path
            }
            if ($manifestPath -and (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
                try {
                    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($manifest.source_identity -and $manifest.source_identity.source_commit) {
                        $sourceCommit = [string]$manifest.source_identity.source_commit
                    }
                } catch {
                    # Manifest unreadable: leave source_commit empty; pointer still counts.
                }
            }
            if ($generation -or $releaseId) {
                $currentStatus = "ok"
            } else {
                $currentStatus = "empty"
            }
        } catch {
            $currentStatus = "parse_fail"
        }
    }

    $skillMd = Join-Path $paths.InstalledSkillRoot "SKILL.md"
    $skillEntry = Join-Path $paths.InstalledSkillRoot "scripts\xinao.py"
    $skillLabel = if (
        (Test-Path -LiteralPath $skillMd -PathType Leaf) -or
        (Test-Path -LiteralPath $skillEntry -PathType Leaf)
    ) { "exists" } else { "missing" }

    $configLabel = Test-LeafExistsLabel (Join-Path $paths.CodexHome "config.toml")
    $authLabel = Test-LeafExistsLabel (Join-Path $paths.CodexHome "auth.json")
    $hooksLabel = Test-LeafExistsLabel (Join-Path $paths.CodexHome "hooks.json")

    $probeStatus = if ($currentStatus -eq "ok" -or $configLabel -eq "exists") { "OK" } else { "PARTIAL" }
    $ts = (Get-Date).ToUniversalTime().ToString("o")

    $lines = New-Object System.Collections.Generic.List[string]
    [void]$lines.Add("SENTINEL:XINAO_ATTENTION_LIVE_DELTA_V1")
    [void]$lines.Add("schema=xinao.attention_live_delta.v1_thin|probe=$probeStatus|ts=$ts")
    [void]$lines.Add("current_pointer=$currentStatus")
    if ($generation) { [void]$lines.Add("generation=$generation") }
    if ($releaseId) { [void]$lines.Add("release_id=$releaseId") }
    if ($sourceCommit) { [void]$lines.Add("source_commit=$sourceCommit") }
    [void]$lines.Add("installed_skill_entry=$skillLabel")
    [void]$lines.Add("config.toml=$configLabel")
    [void]$lines.Add("auth.json=$authLabel")
    [void]$lines.Add("hooks.json=$hooksLabel")
    [void]$lines.Add("note:exists_only_not_ready;facts_only;codex_disposition_only")
    [void]$lines.Add("scope:read_only_no_git_no_inspect_no_network_no_persist_no_secret_bytes")

    [Console]::WriteLine(($lines -join [Environment]::NewLine))
    exit 0
} catch {
    [Console]::WriteLine("SENTINEL:XINAO_ATTENTION_LIVE_DELTA_V1")
    [Console]::WriteLine("LIVE_DELTA_UNAVAILABLE:collector_exception")
    exit 0
}
