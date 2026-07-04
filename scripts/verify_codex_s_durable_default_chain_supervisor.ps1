[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "",
    [string]$SourceRoot = "",
    [string]$PackagePath = "",
    [string]$SupervisorWaveId = "codex-s-durable-default-chain-supervisor-verify-20260704"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $anchorFolder = ([string][char]0x65B0) + ([string][char]0x7CFB) + ([string][char]0x7EDF)
    $SourceRoot = Join-Path ([Environment]::GetFolderPath("Desktop")) $anchorFolder
}
if ([string]::IsNullOrWhiteSpace($PackagePath)) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $candidates = @(Get-ChildItem -LiteralPath $desktop -File -Filter "*20260704.bak_before_closure_update.txt" | Sort-Object LastWriteTime -Descending)
    if ($candidates.Count -gt 0) {
        $PackagePath = [string]$candidates[0].FullName
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$module = Join-Path $RepoRoot "services\agent_runtime\codex_s_durable_default_chain_supervisor.py"
$test = Join-Path $RepoRoot "tests\seedcortex\test_codex_s_durable_default_chain_supervisor.py"

python -m py_compile $module
Assert-True ($LASTEXITCODE -eq 0) "durable supervisor py_compile failed."

python -m pytest -q $test
Assert-True ($LASTEXITCODE -eq 0) "durable supervisor pytest failed."

$output = python -m services.agent_runtime.codex_s_durable_default_chain_supervisor `
    --runtime-root $RuntimeRoot `
    --repo-root $RepoRoot `
    --source-root $SourceRoot `
    --package-path $PackagePath `
    --supervisor-wave-id $SupervisorWaveId `
    --parent-wave-id "source-frontier-workerpool-global-closure-20260704-verify-wave" `
    --poll-seconds 1 `
    --max-cycles 1 `
    --once `
    --no-dispatch
$text = $output -join [Environment]::NewLine
Assert-True ($LASTEXITCODE -eq 0) "durable supervisor once run failed."
Assert-True ($text.Contains("SENTINEL:XINAO_CODEX_S_DURABLE_DEFAULT_CHAIN_SUPERVISOR_V1")) "durable supervisor sentinel missing."

$waveStem = ($SupervisorWaveId -replace '[^A-Za-z0-9_.-]+','-').Trim('.-')
$latest = Join-Path $RuntimeRoot "state\codex_s_durable_default_chain_supervisor\latest.json"
$waveLatest = Join-Path $RuntimeRoot "state\codex_s_durable_default_chain_supervisor\waves\$waveStem\latest.json"
$heartbeat = Join-Path $RuntimeRoot "state\codex_s_durable_default_chain_supervisor\waves\$waveStem\heartbeat_latest.json"
$readback = Join-Path $RuntimeRoot "readback\zh\codex_s_durable_default_chain_supervisor_$waveStem.md"
foreach ($path in @($latest, $waveLatest, $heartbeat, $readback)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing supervisor evidence: $path"
}

$payload = Get-Content -LiteralPath $waveLatest -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($payload.schema_version -eq "xinao.codex_s.durable_default_chain_supervisor.v1") "Supervisor schema mismatch."
Assert-True ($payload.status -eq "durable_default_chain_supervisor_polling") "Supervisor status mismatch."
Assert-True ($payload.supervisor_wave_id -eq $SupervisorWaveId) "Supervisor wave mismatch."
Assert-True ($payload.default_transaction_chain -eq "RootIntentLoop / S Default Dynamic Loop") "Default chain mismatch."
Assert-True ($payload.source_package.stage_package_ref.exists -eq $true) "Stage package not bound."
Assert-True ($payload.source_package.authority_existing_count -ge 4) "Authority refs not bound."
Assert-True ($payload.heartbeat.background_keepalive -eq $true) "Heartbeat keepalive missing."
Assert-True ($payload.heartbeat.polling_continues -eq $true) "Heartbeat continuation missing."
Assert-True ($payload.stop.stop_allowed -eq $false) "Supervisor allowed stop."
Assert-True ($payload.dispatch_supervision.pass_report_substitute_allowed -eq $false) "PASS substitute was allowed."
Assert-True ($payload.repair_plan.continue_main_loop -eq $true) "Repair plan does not continue main loop."
Assert-True ($payload.validation.passed -eq $true) "Supervisor validation failed."
Assert-True ($payload.completion_claim_allowed -eq $false) "Supervisor allowed completion claim."
Assert-True ($payload.not_execution_controller -eq $true) "Supervisor became execution controller."

$ledger = [string]$payload.output_paths.worker_dispatch_ledger_wave
Assert-True (Test-Path -LiteralPath $ledger -PathType Leaf) "Supervisor immutable ledger missing."
$ledgerPayload = Get-Content -LiteralPath $ledger -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($ledgerPayload.immutable_wave_evidence -eq $true) "Supervisor ledger is not immutable."
Assert-True ($ledgerPayload.latest_alias_is_not_proof -eq $true) "Supervisor ledger latest boundary missing."

Write-Output "durable_supervisor_latest=$latest"
Write-Output "durable_supervisor_wave_latest=$waveLatest"
Write-Output "durable_supervisor_heartbeat=$heartbeat"
Write-Output "durable_supervisor_ledger=$ledger"
Write-Output "durable_supervisor_readback_zh=$readback"
Write-Output "validation_result=READY_CONTINUE"
Write-Output "SENTINEL:XINAO_CODEX_S_DURABLE_DEFAULT_CHAIN_SUPERVISOR_V1"
