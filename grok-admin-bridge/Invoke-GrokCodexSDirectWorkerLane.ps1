[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "bridge.config.json"),
    [string]$RuntimeRoot = "",
    [string]$RepoRoot = "",
    [string]$Mode = "draft",
    [string]$Provider = "auto",
    [string]$Objective = "",
    [string]$InputText = "",
    [string]$InputFile = "",
    [string]$WaveId = "",
    [string]$LaneId = "",
    [switch]$NoWrite
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$tool = $config.grok_codex_s_direct_worker_lane_tool

if (-not $RuntimeRoot) { $RuntimeRoot = [string]$config.runtime_root }
if (-not $RepoRoot) { $RepoRoot = [string]$config.repo_root }

$sScript = [string]$tool.codex_s_invoke_script
if (-not (Test-Path -LiteralPath $sScript -PathType Leaf)) {
    throw "Codex S worker lane script missing: $sScript"
}

$invokeArgs = @{
    RuntimeRoot = $RuntimeRoot
    RepoRoot    = $RepoRoot
    Mode        = $Mode
    Provider    = $Provider
    Objective   = $Objective
    InputText   = $InputText
    InputFile   = $InputFile
    WaveId      = $WaveId
    LaneId      = $LaneId
}
if ($NoWrite) { $invokeArgs.NoWrite = $true }

$startedAt = Get-Date
$exitCode = 0
$stdout = ""
$stderr = ""
try {
    $proc = & $sScript @invokeArgs 2>&1
    $stdout = ($proc | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { $exitCode = $LASTEXITCODE }
}
catch {
    $exitCode = 1
    $stderr = $_.Exception.Message
}

$latestPath = Join-Path $RuntimeRoot "state\codex_s_direct_worker_lane\latest.json"
$lanePayload = $null
if (Test-Path -LiteralPath $latestPath -PathType Leaf) {
    try {
        $lanePayload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {}
}

$grokStateDir = Join-Path $PSScriptRoot "state\grok_codex_s_direct_worker_lane"
New-Item -ItemType Directory -Force -Path $grokStateDir | Out-Null
$grokLatest = Join-Path $grokStateDir "latest.json"

$result = [ordered]@{
    schema_version       = "xinao.grok_codex_s_direct_worker_lane_invoke.v1"
    sentinel             = "SENTINEL:GROK_CODEX_S_DIRECT_WORKER_LANE_INVOKE"
    generated_at         = (Get-Date).ToString("o")
    grok_role            = "brain_executor_worker_lane_invoke"
    not_333_mainline     = $true
    completion_claim_allowed = $false
    not_user_completion  = $true
    not_execution_controller = $true
    request              = [ordered]@{
        mode      = $Mode
        provider  = $Provider
        objective = $Objective
        input_file = $InputFile
        input_text_chars = if ($InputText) { $InputText.Length } else { 0 }
        wave_id   = $WaveId
        lane_id   = $LaneId
        no_write  = [bool]$NoWrite
    }
    codex_s_invoke_script = $sScript
    exit_code            = $exitCode
    stderr               = $stderr
    stdout_excerpt       = if ($stdout.Length -gt 4000) { $stdout.Substring(0, 4000) } else { $stdout }
    codex_s_latest_ref   = $latestPath
    codex_s_latest_exists = Test-Path -LiteralPath $latestPath -PathType Leaf
    lane_status          = if ($lanePayload) { $lanePayload.status } else { $null }
    lane_named_blocker   = if ($lanePayload -and $lanePayload.PSObject.Properties.Name -contains "named_blocker") { $lanePayload.named_blocker } elseif ($lanePayload -and $lanePayload.lane_result) { $lanePayload.lane_result.named_blocker } else { "" }
    provider_invocation_performed = if ($lanePayload -and $lanePayload.lane_result) { $lanePayload.lane_result.provider_invocation_performed } else { $null }
    model_invocation_performed = if ($lanePayload -and $lanePayload.lane_result) { $lanePayload.lane_result.model_invocation_performed } else { $null }
    artifact_ref         = if ($lanePayload -and $lanePayload.lane_result) { $lanePayload.lane_result.artifact_ref } else { "" }
    duration_ms          = [int]((Get-Date) - $startedAt).TotalMilliseconds
    boundary_cn          = "直调 Qwen/DP worker lane；不是 RootIntentLoop/Temporal 333 主链；须 fan-in/AAQ 才能晋升事实。"
}

$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $grokLatest -Encoding UTF8
Write-Output ($result | ConvertTo-Json -Depth 12 -Compress)
exit $exitCode