#Requires -Version 5.1
<#
.SYNOPSIS
  P0 步 4–7 薄绑：认领后等待波内产物落盘，再调 WaveStatus（不新造 orchestrator）。
#>
param(
    [int]$WaitSeconds = 60,
    [int]$PollIntervalSeconds = 10,
    [string]$ConfigPath = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$waveScript = Join-Path $PSScriptRoot "Invoke-GrokTaskEntryWaveStatus.ps1"
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$last = $null

while ((Get-Date) -lt $deadline) {
    $last = & $waveScript -ConfigPath $ConfigPath -Quiet | ConvertFrom-Json
    if ($last.steps.step6_fanin_ok -eq $true) { break }
    if ($last.steps.step4_langgraph_ok -eq $true -and $last.steps.step5_execution_ok -eq $true) {
        Start-Sleep -Seconds $PollIntervalSeconds
        continue
    }
    Start-Sleep -Seconds $PollIntervalSeconds
}

if (-not $last) {
    $last = & $waveScript -ConfigPath $ConfigPath -Quiet | ConvertFrom-Json
}

$out = [ordered]@{
    schema_version = "xinao.task_entry.continue_wave.v1"
    generated_at   = (Get-Date).ToString("o")
    wait_seconds   = $WaitSeconds
    wave_status    = $last
    completion_claim_allowed = $false
}

if (-not $Quiet) { $out | ConvertTo-Json -Depth 10 }
exit 0