[CmdletBinding()]
param(
    [string]$OutputRoot = "C:\Users\xx363\Desktop\GROK_GLOBAL_RULES_HARVEST_20260626",
    [ValidateSet("B", "C", "DP", "BC", "BCDP", "BDP")]
    [string]$Summon = "BCDP",
    [switch]$SkipGather,
    [switch]$WaitForAll,
    [int]$WaitSec = 600,
    [string]$ConfigPath = (Join-Path $PSScriptRoot "bridge.config.json")
)

$ErrorActionPreference = "Stop"
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$python = [string]$config.ucp_python

function Expand-Summon($t) {
    switch ($t) {
        "B" { @("B") }; "C" { @("C") }; "DP" { @("DP") }
        "BC" { @("B", "C") }; "BDP" { @("B", "DP") }; "BCDP" { @("B", "C", "DP") }
        default { throw "bad summon" }
    }
}

if (-not $SkipGather) {
    & (Join-Path $PSScriptRoot "Invoke-GrokGlobalRulesHarvestGather.ps1") -OutputRoot $OutputRoot | Out-Null
}

$list = Expand-Summon $Summon
$jobs = @()
$dispatches = [System.Collections.Generic.List[object]]::new()

foreach ($code in $list) {
    $rec = [ordered]@{ auditor = $code; status = "pending" }
    if ($code -in @("B", "C")) {
        $script = Join-Path $PSScriptRoot "run_grok_rules_harvest_worker.py"
        $args = @($script, "--auditor", $code, "--output-root", $OutputRoot, "--timeout-seconds", ([string]$WaitSec))
    }
    else {
        $script = Join-Path $PSScriptRoot "run_grok_rules_harvest_dp_worker.py"
        $args = @($script, "--output-root", $OutputRoot, "--timeout-seconds", ([string][Math]::Min(300, $WaitSec)))
    }
    if ($WaitForAll) {
        & $python @args
        $rec.status = if ($LASTEXITCODE -eq 0) { "completed" } else { "completed_partial" }
        $rec.exit_code = $LASTEXITCODE
    }
    else {
        $job = Start-Job -ScriptBlock { param($Py, $A) & $Py @A; return $LASTEXITCODE } -ArgumentList $python, $args
        $rec.status = "summoned_async"
        $rec.job_id = $job.Id
        $jobs += $job
    }
    $dispatches.Add([pscustomobject]$rec)
}

if ($WaitForAll -and $jobs.Count -gt 0) {
    Receive-Job -Job $jobs -Wait | Out-Null
    Remove-Job -Job $jobs -Force
}

$manifest = [ordered]@{
    schema_version = "xinao.grok_global_rules_harvest_summon.v1"
    generated_at = (Get-Date).ToString("o")
    output_root = $OutputRoot
    summon = $list
    does_not_block_codex_a = $true
    visible_window = $false
    dispatches = @($dispatches)
    desktop_files = @(
        "00_README_规则地图.txt",
        "01_B_工程规则_L0仓库运行时.txt",
        "02_C_工程规则_备用仓.txt",
        "03_DP_语义规则_人类可读索引.txt",
        "04_Grok桥接与分工规则.txt",
        "raw/"
    )
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "D:\XINAO_CLEAN_RUNTIME\state\grok_global_rules_harvest\summon_latest.json" -Encoding UTF8
$manifest | ConvertTo-Json -Depth 8