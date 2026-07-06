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

$latestPath = Join-Path $RuntimeRoot "state\codex_333_legacy_freeze_manifest\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\codex_333_legacy_freeze_manifest.md"
$payload = Read-JsonFile $latestPath

Assert-True ([string]$payload.schema_version -eq "xinao.codex_s.333_legacy_freeze_manifest.v1") "schema mismatch."
Assert-True ([string]$payload.sentinel -eq "SENTINEL:XINAO_CODEX_S_333_LEGACY_FREEZE_MANIFEST_READY") "sentinel mismatch."
Assert-True ([string]$payload.status -eq "legacy_freeze_manifest_ready") "legacy freeze manifest is not ready."
Assert-True ($payload.validation.passed -eq $true) "validation did not pass."
Assert-True ($payload.validation.checks.source_mentions_legacy_freeze -eq $true) "source package did not mention legacy freeze."
Assert-True ($payload.validation.checks.l0_declares_legacy_boundary -eq $true) "L0 legacy boundary missing."
Assert-True ($payload.validation.checks.workspace_contract_declares_legacy_boundary -eq $true) "workspace boundary missing."
Assert-True ($payload.validation.checks.guard_ready -eq $true) "reference-only runtime guard not ready."
Assert-True ($payload.validation.checks.cli_entrypoint_registered -eq $true) "CLI entrypoint missing."
Assert-True ($payload.validation.checks.tool_registry_provider_visible -eq $true) "ToolRegistry provider missing."
Assert-True ($payload.reference_only_runtime_guard.old_completion_gate_allowed -eq $false) "old completion gate allowed."
Assert-True ($payload.completion_claim_allowed -eq $false) "completion claim is allowed."
Assert-True ($payload.not_execution_controller -eq $true) "not_execution_controller missing."
Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "readback missing."

Write-Output "legacy_freeze_manifest_latest=$latestPath"
Write-Output "legacy_freeze_manifest_readback=$readbackPath"
Write-Output "validation_result=ok"
