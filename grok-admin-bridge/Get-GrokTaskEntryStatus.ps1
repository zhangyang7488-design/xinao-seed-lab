#Requires -Version 5.1
<#
.SYNOPSIS
  列出任务入口 intake 状态与最新三句 readback。
#>
param(
    [string]$ConfigPath = "",
    [int]$Limit = 10
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $ConfigPath
$stateRoot = Join-Path $runtime "state\task_entry"
$latest = Join-Path $stateRoot "latest.json"
$intakeDir = Join-Path $stateRoot "intake"

$out = [ordered]@{
    schema_version = "xinao.task_entry.status.v1"
    generated_at   = (Get-Date).ToString("o")
    latest_ref     = $latest
    latest         = $null
    recent_intakes = @()
}

if (Test-Path -LiteralPath $latest) {
    $out.latest = Get-Content -LiteralPath $latest -Raw -Encoding UTF8 | ConvertFrom-Json
}

if (Test-Path -LiteralPath $intakeDir) {
    $out.recent_intakes = Get-ChildItem -LiteralPath $intakeDir -Filter "*.json" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First $Limit |
        ForEach-Object {
            $j = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            [ordered]@{
                task_id     = $j.task_id
                claim_state = $j.claim_state
                intent      = $j.intent_one_liner
                at          = $j.generated_at
                blockers    = $j.named_blockers
            }
        }
}

$out | ConvertTo-Json -Depth 6