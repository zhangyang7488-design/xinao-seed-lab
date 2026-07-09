#Requires -Version 5.1
<#
.SYNOPSIS
  成熟优先治理环 · 策略门（OPA精神轻量落地）。记录步骤、保存规划、评估偏离；fail-open 不锁 Grok 工具。
#>
param(
    [switch]$Read,
    [switch]$RecordStep,
    [string]$StepId = "",
    [ValidateSet("platform_ops", "business_wave", "delivery_shell", "dialogue_only", "research_external", "")]
    [string]$TaskClass = "",
    [string]$SummaryCn = "",
    [string[]]$ExternalRefs = @(),
    [string[]]$LocalRefs = @(),
    [string]$CarrierChoice = "",
    [switch]$SavePlan,
    [string]$PlanMarkdown = "",
    [string]$PlanPath = "",
    [switch]$Evaluate,
    [string]$ProposedAction = "",
    [switch]$RecordDeviation,
    [string]$DeviationId = "",
    [string]$DeviationReason = "",
    [string]$SunsetCn = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$bridge = $PSScriptRoot
$loopPath = Join-Path $bridge "grok_mature_first_governance_loop.v1.json"
$policyPath = Join-Path $bridge "grok_mature_first_policy.v1.json"
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$stateRoot = Join-Path $runtime "state\grok_governance"
$latestPath = Join-Path $stateRoot "latest.json"
$deviationPath = Join-Path $stateRoot "deviations.ndjson"
$plansDir = Join-Path $stateRoot "plans"
New-Item -ItemType Directory -Force -Path $stateRoot, $plansDir | Out-Null

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-Latest([object]$Payload) {
    $json = $Payload | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($latestPath, $json, $utf8)
    if (-not $Quiet) { $json }
}

if ($Read) {
    if (-not (Test-Path -LiteralPath $latestPath)) {
        $out = [ordered]@{
            schema_version = "xinao.grok_governance.status.v1"
            status         = "no_governance_yet"
            hint_cn        = "平台/运维/焊路事务开头运行 -RecordStep 0_classify"
        }
        if (-not $Quiet) { $out | ConvertTo-Json -Depth 6 }
        exit 0
    }
    if (-not $Quiet) { Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 }
    exit 0
}

$loop = Read-Json $loopPath
$policy = Read-Json $policyPath
$now = (Get-Date).ToString("o")
$sessionId = "gov-{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")

$latest = Read-Json $latestPath
if ($null -eq $latest -or $latest.schema_version -ne "xinao.grok_governance.session.v1") {
    $latest = [ordered]@{
        schema_version = "xinao.grok_governance.session.v1"
        session_id     = $sessionId
        started_at     = $now
        task_class     = ""
        steps          = @()
        plan_ref       = ""
        deviations     = @()
        ready_to_execute = $false
        plan_only_mode   = $false
    }
}

if ($RecordStep) {
    if (-not $StepId) { throw "RecordStep requires -StepId" }
    if ($TaskClass) { $latest.task_class = $TaskClass }
    $step = [ordered]@{
        id            = $StepId
        at            = $now
        summary_cn    = $SummaryCn
        external_refs = @($ExternalRefs)
        local_refs    = @($LocalRefs)
        carrier_choice = $CarrierChoice
    }
    $steps = [System.Collections.Generic.List[object]]::new()
    if ($latest.steps) { foreach ($s in $latest.steps) { $steps.Add($s) } }
    $steps.Add([pscustomobject]$step)
    $latest.steps = @($steps)
    $required = @("0_classify", "1_external_first", "3_choose_carrier", "4_plan_artifact")
    $done = @($latest.steps | ForEach-Object { $_.id })
    $latest.ready_to_execute = (-not ($required | Where-Object { $_ -notin $done }))
    $latest.updated_at = $now
    Write-Latest $latest
    exit 0
}

if ($SavePlan) {
    if (-not $PlanMarkdown -and $PlanPath) {
        if (Test-Path -LiteralPath $PlanPath) {
            $PlanMarkdown = Get-Content -LiteralPath $PlanPath -Raw -Encoding UTF8
        }
    }
    if (-not $PlanMarkdown) { throw "SavePlan requires -PlanMarkdown or -PlanPath" }
    $planFile = Join-Path $plansDir ("plan_{0}.md" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    [System.IO.File]::WriteAllText($planFile, $PlanMarkdown, $utf8)
    $latest.plan_ref = $planFile
    $latest.plan_only_mode = $true
    $latest.updated_at = $now
    if (-not ($latest.steps | Where-Object { $_.id -eq "4_plan_artifact" })) {
        $steps = [System.Collections.Generic.List[object]]::new()
        if ($latest.steps) { foreach ($s in $latest.steps) { $steps.Add($s) } }
        $steps.Add([pscustomobject]@{
            id = "4_plan_artifact"; at = $now; summary_cn = "plan_saved"; external_refs = @(); local_refs = @(); carrier_choice = ""
        })
        $latest.steps = @($steps)
    }
    Write-Latest $latest
    exit 0
}

if ($RecordDeviation) {
    $dev = @{
        at = $now
        id = if ($DeviationId) { $DeviationId } else { "DEVIATION_{0}" -f (Get-Date -Format "HHmmss") }
        reason_cn = $DeviationReason
        sunset_cn = $SunsetCn
        proposed_action = $ProposedAction
    } | ConvertTo-Json -Compress
    Add-Content -LiteralPath $deviationPath -Value $dev -Encoding UTF8
    $devs = [System.Collections.Generic.List[object]]::new()
    if ($latest.deviations) { foreach ($d in $latest.deviations) { $devs.Add($d) } }
    $devs.Add(($dev | ConvertFrom-Json))
    $latest.deviations = @($devs)
    $latest.updated_at = $now
    Write-Latest $latest
    exit 0
}

if ($Evaluate) {
    $tc = if ($TaskClass) { $TaskClass } else { [string]$latest.task_class }
    $action = $ProposedAction
    $warnings = [System.Collections.Generic.List[string]]::new()
    $hardStop = $false
    if ($policy -and $policy.deny_without_deviation) {
        foreach ($rule in $policy.deny_without_deviation) {
            $classes = @($rule.task_classes)
            if ($classes -contains "*" -or $classes -contains $tc) {
                $pat = [string]$rule.pattern_cn
                if ($pat -and $action -match $pat) {
                    [void]$warnings.Add([string]$rule.message_cn)
                    if ($rule.effect -eq "hard_stop_writes") { $hardStop = $true }
                }
            }
        }
    }
    $report = [ordered]@{
        schema_version = "xinao.grok_governance.evaluate.v1"
        generated_at   = $now
        task_class     = $tc
        proposed_action = $action
        ready_to_execute = [bool]$latest.ready_to_execute
        warnings       = @($warnings)
        hard_stop_writes = $hardStop
        policy_ref     = $policyPath
        deviation_required = ($warnings.Count -gt 0)
        fail_open      = $true
        not_tool_deny  = $true
    }
    if (-not $Quiet) { $report | ConvertTo-Json -Depth 6 }
    exit 0
}

throw "Specify -Read, -RecordStep, -SavePlan, -Evaluate, or -RecordDeviation"