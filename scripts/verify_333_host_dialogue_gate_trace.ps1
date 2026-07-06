[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$latestPath = Join-Path $RuntimeRoot "state\codex_333_host_dialogue_gate_trace\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\codex_333_host_dialogue_gate_trace.md"
$payload = Read-JsonFile $latestPath

Assert-True ([string]$payload.schema_version -eq "xinao.codex_s.333_host_dialogue_gate_trace.v1") "schema mismatch."
Assert-True ([string]$payload.sentinel -eq "SENTINEL:XINAO_CODEX_S_333_HOST_DIALOGUE_GATE_TRACE_READY") "sentinel mismatch."
Assert-True ([string]$payload.status -eq "host_dialogue_gate_trace_ready") "host dialogue trace is not ready."
Assert-True ($payload.validation.passed -eq $true) "validation did not pass."
Assert-True ($payload.validation.checks.user_prompt_submit_hook_configured -eq $true) "UserPromptSubmit hook missing."
Assert-True ($payload.validation.checks.hook_script_names_message_classes -eq $true) "message classes missing from hook script."
Assert-True ($payload.validation.checks.sample_classes_match -eq $true) "sample classes do not match."
Assert-True ($payload.validation.checks.human_dialogue_no_hot_path_policy -eq $true) "human_dialogue no-hot-path policy missing."
Assert-True ($payload.validation.checks.cli_entrypoint_registered -eq $true) "CLI entrypoint missing."
Assert-True ($payload.completion_claim_allowed -eq $false) "completion claim is allowed."
Assert-True ($payload.not_execution_controller -eq $true) "not_execution_controller missing."
Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "readback missing."

Write-Output "host_dialogue_gate_trace_latest=$latestPath"
Write-Output "host_dialogue_gate_trace_readback=$readbackPath"
Write-Output "validation_result=ok"
