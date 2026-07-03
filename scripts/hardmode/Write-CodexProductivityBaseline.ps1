[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ProbeId,
    [string]$TaskId = "productivity_baseline_probe",
    [string]$WaveId = "",
    [bool]$HadCodeDiff = $false,
    [bool]$HadInvoke = $false,
    [string]$InvokePath = "",
    [string[]]$GatekeeperSignals = @("none_observed"),
    [Parameter(Mandatory = $true)][string]$ZhReadback,
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"

function Write-JsonAtomic {
    param([string]$Path, [object]$Value, [int]$Depth = 8)
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $tmp = "$Path.$PID.tmp"
    ($Value | ConvertTo-Json -Depth $Depth) + [Environment]::NewLine | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

$payload = [ordered]@{
    schema_version = "xinao.codex_productivity_baseline.v1"
    probe_id = $ProbeId
    task_id = $TaskId
    wave_id = $WaveId
    had_code_diff = $HadCodeDiff
    had_invoke = $HadInvoke
    invoke_path = $InvokePath
    gatekeeper_signals = @($GatekeeperSignals)
    zh_readback = $ZhReadback
    written_at = (Get-Date).ToUniversalTime().ToString("o")
    not_user_completion = $true
}

$outDir = Join-Path $RuntimeRoot "state\codex_productivity_baseline"
$outPath = Join-Path $outDir "latest.json"
Write-JsonAtomic -Path $outPath -Value $payload
$payload | ConvertTo-Json -Depth 6