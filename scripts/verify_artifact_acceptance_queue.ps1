param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

$aaqPath = Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json"
$ledgerPath = Join-Path $RuntimeRoot "state\source_ledger\latest.json"

Assert-True (Test-Path -LiteralPath $aaqPath -PathType Leaf) "Missing artifact_acceptance_queue latest."
$aaq = Get-Content -LiteralPath $aaqPath -Raw -Encoding UTF8 | ConvertFrom-Json

Assert-True ([string]$aaq.schema_version -eq "xinao.seedcortex.artifact_acceptance_queue.v1") "AAQ schema mismatch."
Assert-True ($aaq.claim_card_hard_gate_enforced -eq $true) "AAQ ClaimCard hard gate is not enforced."
Assert-True ($aaq.claim_card_requires_source_ledger -eq $true) "AAQ does not require SourceLedger for ClaimCard."
Assert-True ($aaq.direct_fact_promotion_allowed -eq $false) "AAQ allowed direct fact promotion."
Assert-True ($aaq.completion_claim_allowed -eq $false) "AAQ allowed completion claim."
Assert-True ([int]$aaq.accepted_artifact_count -ge 1) "AAQ has no accepted artifact."

if ([int]$aaq.claim_card_source_ledger_entry_count -gt 0) {
    Assert-True (Test-Path -LiteralPath $ledgerPath -PathType Leaf) "Missing global SourceLedger latest."
    $ledger = Get-Content -LiteralPath $ledgerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$ledger.schema_version -eq "xinao.seedcortex.source_ledger.v1") "SourceLedger schema mismatch."
    Assert-True ($ledger.global_ledger -eq $true) "SourceLedger is not global."
    Assert-True ($ledger.private_ledger -eq $false) "SourceLedger is private."
    Assert-True ($ledger.claim_card_hard_gate_enforced -eq $true) "SourceLedger missing ClaimCard hard gate flag."
    Assert-True ([int]$ledger.entry_count -ge [int]$aaq.claim_card_source_ledger_entry_count) "SourceLedger count is below AAQ ClaimCard count."
}

Write-Output "artifact_acceptance_queue_latest=$aaqPath"
Write-Output "source_ledger_latest=$ledgerPath"
Write-Output "SENTINEL:XINAO_ARTIFACT_ACCEPTANCE_QUEUE_CLAIMCARD_GATE_READY"
