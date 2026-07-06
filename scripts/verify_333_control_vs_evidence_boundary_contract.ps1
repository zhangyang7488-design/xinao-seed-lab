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

$latestPath = Join-Path $RuntimeRoot "state\codex_333_control_vs_evidence_boundary_contract\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\codex_333_control_vs_evidence_boundary_contract.md"
$payload = Read-JsonFile $latestPath

Assert-True ([string]$payload.schema_version -eq "xinao.codex_s.333_control_vs_evidence_boundary_contract.v1") "schema mismatch."
Assert-True ([string]$payload.sentinel -eq "SENTINEL:XINAO_CODEX_S_333_CONTROL_VS_EVIDENCE_BOUNDARY_READY") "sentinel mismatch."
Assert-True ([string]$payload.status -eq "control_vs_evidence_boundary_contract_ready") "contract is not ready."
Assert-True ($payload.validation.passed -eq $true) "validation did not pass."
Assert-True ($payload.validation.checks.source_mentions_contract -eq $true) "source package did not mention the contract."
Assert-True ($payload.validation.checks.external_mature_claimcards_present -eq $true) "external mature claimcards missing."
Assert-True ($payload.validation.checks.latest_json_read_model_only -eq $true) "latest.json boundary missing."
Assert-True ($payload.validation.checks.default_trigger_refs_evidence_only -eq $true) "default trigger no-stop refs are not evidence-only."
Assert-True ($payload.validation.checks.aaq_direct_fact_promotion_denied -eq $true) "AAQ direct fact promotion not denied."
Assert-True ($payload.validation.checks.tool_registry_provider_visible -eq $true) "ToolRegistry provider missing."
Assert-True ($payload.validation.checks.continuity_points_here -eq $true) "continuity router does not point here."
Assert-True ($payload.boundary_contract.latest_json_role -eq "disposable_read_model_projection_not_control_authority") "latest role mismatch."
Assert-True (@($payload.boundary_contract.forbidden_promotions) -contains "latest_json_triggers_dispatch") "latest dispatch promotion not forbidden."
Assert-True (@($payload.boundary_contract.required_promotion_chain) -contains "ArtifactAcceptanceQueue accepted/rejected decision") "AAQ missing from promotion chain."
Assert-True ($payload.completion_claim_allowed -eq $false) "completion claim is allowed."
Assert-True ($payload.not_execution_controller -eq $true) "not_execution_controller missing."
Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "readback missing."

Write-Output "control_vs_evidence_boundary_latest=$latestPath"
Write-Output "control_vs_evidence_boundary_readback=$readbackPath"
Write-Output "validation_result=ok"
