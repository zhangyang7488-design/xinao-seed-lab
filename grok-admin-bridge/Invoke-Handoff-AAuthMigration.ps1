$ErrorActionPreference = "Stop"
$h = Get-Content -LiteralPath (Join-Path $PSScriptRoot "handoffs\2026-06-28_a_brain_authorization_migration_segment_audit_unchanged.v1.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$sem = ($h.semantic_object | ConvertTo-Json -Depth 12 -Compress)
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $sem `
    -IntentOneLiner $h.intent_one_liner_cn `
    -MustDoOneLiner "auth_lane_to_A; split continuation vs segment_audit; run workflow tests" `
    -ForbiddenOneLiner "grok_mainline_auth; remove segment_audit; bidirectional_http_poll" `
    -AcceptanceOneLiner "DAG_auto_continue; phase_exit_segment_audit_unchanged; tests_PASS" `
    -WaitSec 75