[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TaskId,
    [string]$WaveId = "",
    [ValidateSet("repo_safe", "max_parallel", "research", "repair", "audit", "productivity_v2")]
    [string]$Mode = "productivity_v2",
    [string]$ModeReason = "",
    [string]$ZhReadback = "",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$LanesJson = "",
    [string]$ResultsJson = ""
)

$ErrorActionPreference = "Stop"

function Write-JsonAtomic {
    param([string]$Path, [object]$Value, [int]$Depth = 10)
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $tmp = "$Path.$PID.tmp"
    ($Value | ConvertTo-Json -Depth $Depth) + [Environment]::NewLine | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

if (-not $WaveId.Trim()) {
    $WaveId = "wave_{0}" -f (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
}

$lanes = @()
if ($LanesJson.Trim()) {
    $lanes = @($LanesJson | ConvertFrom-Json)
}

$results = @()
if ($ResultsJson.Trim()) {
    $results = @($ResultsJson | ConvertFrom-Json)
}

$payload = [ordered]@{
    schema_version = "xinao.meta_rsi_wave.v1"
    wave_id = $WaveId
    task_id = $TaskId
    mode = $Mode
    mode_reason = $ModeReason
    fallback = [ordered]@{
        repo_mode_used = $false
        reason = "none"
    }
    lanes = @($lanes)
    results = @($results)
    adoption_state = "candidate_registered"
    runtime_enforced = $false
    completion_claim_allowed = $false
    zh_readback = $ZhReadback
    written_at = (Get-Date).ToUniversalTime().ToString("o")
    not_user_completion = $true
}

$outDir = Join-Path $RuntimeRoot "state\meta_rsi_wave"
$outPath = Join-Path $outDir "latest.json"
Write-JsonAtomic -Path $outPath -Value $payload
$payload | ConvertTo-Json -Depth 8