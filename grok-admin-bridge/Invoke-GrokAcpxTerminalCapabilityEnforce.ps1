#Requires -Version 5.1
<#
.SYNOPSIS
  Enforce Grok shell_terminal capability deny (alias-normalized) on all live surfaces.
.DESCRIPTION
  Mature end-of-path fix for visible-console class bugs:
    - capability CSV = run_terminal_cmd,run_terminal_command (not lone Bash / not single legacy id)
    - sync dual-brain source config into known ACPX homes
    - verify live managed generation operation-runner embeds the same CSV
    - hidden-stdio is inventory-only (not the isolation gate)

  Does not freeze Grok, does not strip file/web tools, does not re-provision unless -EnsureGeneration.
.EXAMPLE
  .\Invoke-GrokAcpxTerminalCapabilityEnforce.ps1 -Action Enforce
  .\Invoke-GrokAcpxTerminalCapabilityEnforce.ps1 -Action Audit
#>
param(
    [ValidateSet("Audit", "Enforce", "SyncHomes")]
    [string]$Action = "Enforce",
    [string]$DualBrainRoot = "E:\XINAO_RESEARCH_WORKSPACES\S\projects\dual-brain-coordination",
    [string]$AcpxCurrent = "D:\XINAO_RESEARCH_RUNTIME\tools\acpx\current.json",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = "D:\XINAO_RESEARCH_RUNTIME"
if (Test-Path -LiteralPath (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")) {
    try { $runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") } catch { }
}

$contractPath = Join-Path $bridge "grok_shell_capability_aliases.v1.json"
$stateDir = Join-Path $runtime "state\capability_max_weld"
$zhDir = Join-Path $runtime "readback\zh"
$evidencePath = Join-Path $stateDir "acpx_terminal_capability_enforce.json"
$zhPath = Join-Path $zhDir "acpx_terminal_capability_enforce_latest.md"
New-Item -ItemType Directory -Force -Path $stateDir, $zhDir | Out-Null

function Write-Utf8File([string]$Path, [string]$Content) {
    [IO.File]::WriteAllText($Path, $Content, $utf8)
}

function Get-Contract {
    if (-not (Test-Path -LiteralPath $contractPath)) {
        throw "CONTRACT_MISSING: $contractPath"
    }
    return (Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Get-DisallowedTokenFromConfig([string]$ConfigPath) {
    if (-not (Test-Path -LiteralPath $ConfigPath)) { return $null }
    $j = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $args = @($j.agents.'grok-build'.args)
    $idx = [Array]::IndexOf($args, "--disallowed-tools")
    if ($idx -lt 0 -or ($idx + 1) -ge $args.Count) { return "" }
    return [string]$args[$idx + 1]
}

function Test-RunnerHasCsv([string]$RunnerPath, [string]$Csv) {
    if (-not (Test-Path -LiteralPath $RunnerPath)) { return $false }
    $raw = Get-Content -LiteralPath $RunnerPath -Raw -Encoding UTF8
    return ($raw -match [regex]::Escape("--disallowed-tools $Csv"))
}

function Get-KnownHomes {
    $base = Join-Path $runtime "state"
    $names = @(
        "acpx-grok-admin",
        "acpx-grok-brain",
        "acpx-grok-canary",
        "acpx-runtime-grok",
        "acpx-runtime-canary"
    )
    $list = foreach ($n in $names) {
        $cfg = Join-Path $base "$n\.acpx\config.json"
        if (Test-Path -LiteralPath (Join-Path $base $n)) {
            [pscustomobject]@{ home = $n; config = $cfg; exists = (Test-Path -LiteralPath $cfg) }
        }
    }
    return @($list)
}

$contract = Get-Contract
$csv = [string]$contract.disallowed_tools_csv
$sourceConfig = Join-Path $DualBrainRoot "provisioning\acpx-grok-config.json"
$sourceRunner = Join-Path $DualBrainRoot "provisioning\acpx-runtime\operation-runner.mjs"

$report = [ordered]@{
    schema = "xinao.acpx_terminal_capability_enforce.v1"
    sentinel = "SENTINEL:ACPX_TERMINAL_CAPABILITY_ENFORCE"
    generated_at = (Get-Date).ToString("o")
    action = $Action
    capability_id = [string]$contract.capability_id
    required_csv = $csv
    surfaces = [ordered]@{}
    homes = @()
    ok = $false
    completion_claim_allowed = $false
}

# Source
$srcToken = Get-DisallowedTokenFromConfig $sourceConfig
$srcRunnerOk = Test-RunnerHasCsv $sourceRunner $csv
$report.surfaces.source_config = [ordered]@{
    path = $sourceConfig
    exists = (Test-Path -LiteralPath $sourceConfig)
    disallowed = $srcToken
    ok = ($srcToken -eq $csv)
    sha256 = if (Test-Path -LiteralPath $sourceConfig) { (Get-FileHash -LiteralPath $sourceConfig -Algorithm SHA256).Hash } else { $null }
}
$report.surfaces.source_runner = [ordered]@{
    path = $sourceRunner
    exists = (Test-Path -LiteralPath $sourceRunner)
    ok = $srcRunnerOk
    sha256 = if (Test-Path -LiteralPath $sourceRunner) { (Get-FileHash -LiteralPath $sourceRunner -Algorithm SHA256).Hash } else { $null }
}

# Live generation
$liveGen = $null
$liveRunner = $null
if (Test-Path -LiteralPath $AcpxCurrent) {
    $liveGen = Get-Content -LiteralPath $AcpxCurrent -Raw -Encoding UTF8 | ConvertFrom-Json
    $liveRunner = [string]$liveGen.runner_path
}
$liveOk = Test-RunnerHasCsv $liveRunner $csv
$report.surfaces.live_generation = [ordered]@{
    current_json = $AcpxCurrent
    generation_id = if ($liveGen) { [string]$liveGen.generation_id } else { $null }
    runner_path = $liveRunner
    ok = $liveOk
    sha256 = if ($liveRunner -and (Test-Path -LiteralPath $liveRunner)) { (Get-FileHash -LiteralPath $liveRunner -Algorithm SHA256).Hash } else { $null }
}

# Homes
$homes = @(Get-KnownHomes)
$homeResults = @()
foreach ($h in $homes) {
    $tokenBefore = Get-DisallowedTokenFromConfig $h.config
    $synced = $false
    if ($Action -in @("Enforce", "SyncHomes") -and (Test-Path -LiteralPath $sourceConfig)) {
        $dir = Split-Path -Parent $h.config
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $tmp = Join-Path $dir (".config.capenforce.{0}.tmp" -f [guid]::NewGuid().ToString("N"))
        Copy-Item -LiteralPath $sourceConfig -Destination $tmp -Force
        Move-Item -LiteralPath $tmp -Destination $h.config -Force
        $synced = $true
    }
    $tokenAfter = Get-DisallowedTokenFromConfig $h.config
    $homeResults += ,([ordered]@{
        home = $h.home
        config = $h.config
        existed_before = $h.exists
        disallowed_before = $tokenBefore
        disallowed_after = $tokenAfter
        synced = $synced
        ok = ($tokenAfter -eq $csv)
    })
}
$report.homes = $homeResults

$allHomesOk = (@($homeResults | Where-Object { -not $_.ok }).Count -eq 0)
$report.ok = [bool](
    $report.surfaces.source_config.ok -and
    $report.surfaces.source_runner.ok -and
    $report.surfaces.live_generation.ok -and
    $allHomesOk
)

# Evidence
$json = $report | ConvertTo-Json -Depth 8
Write-Utf8File $evidencePath $json

$lines = @(
    "# ACPX shell_terminal capability 强制读回",
    "",
    "- generated: $($report.generated_at)",
    "- action: **$Action**",
    "- required_csv: ``$csv``",
    "- overall_ok: **$($report.ok)**",
    "- completion_claim_allowed: **false**",
    "",
    "## Surfaces",
    "",
    "| Surface | OK | Detail |",
    "|---------|----|--------|",
    "| source config | $($report.surfaces.source_config.ok) | ``$srcToken`` |",
    "| source runner | $($report.surfaces.source_runner.ok) | dual-brain operation-runner |",
    "| live generation | $($report.surfaces.live_generation.ok) | ``$($report.surfaces.live_generation.generation_id)`` |",
    "",
    "## Homes",
    ""
)
foreach ($hr in $homeResults) {
    $lines += "- **$($hr.home)**: ok=$($hr.ok) synced=$($hr.synced) before=``$($hr.disallowed_before)`` after=``$($hr.disallowed_after)``"
}
$lines += @(
    "",
    "## Note",
    "",
    "- hidden-stdio / CREATE_NO_WINDOW 不是本闸门；工具子进程靠 capability deny。",
    "- 证据: ``$evidencePath``"
)
Write-Utf8File $zhPath (($lines -join "`n") + "`n")

if (-not $Quiet) {
    Write-Output $json
}

if (-not $report.ok -and $Action -ne "Audit") {
    throw "ACPX_TERMINAL_CAPABILITY_ENFORCE_FAILED: see $evidencePath"
}

exit 0
