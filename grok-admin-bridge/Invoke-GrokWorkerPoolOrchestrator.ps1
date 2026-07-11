#Requires -Version 5.1
<#
.SYNOPSIS
  Grok headless worker pool orchestrator — max_parallel + complete-then-refill ledger.
.DESCRIPTION
  Separate from batch Invoke-GrokWorkerPool.ps1 (still default one-shot N).
  Ledger-driven resident machine for Codex -> many Grok Composer25 workers.

  Actions:
    Pulse    — refresh frontier, reconcile in_flight, write refill + spawn_directives
    Register — mark a worker slot running
    Complete — end one slot; immediately recompute refill_count
    Read     — print ledger JSON (Pulse if missing)
    RunOnce  — if refill_required, spawn slots (CREATE_NO_WINDOW) then re-Pulse

  Pause gate (RunOnce only unless -SkipPauseGate):
    status=PAUSED_ALL AND subagent_spawn=false -> refuse
    status=RESUMED_WORKER_POOL (or spawn allowed) -> allow

.EXAMPLE
  .\Invoke-GrokWorkerPoolOrchestrator.ps1 -Action Pulse -MaxParallel 4
  .\Invoke-GrokWorkerPoolOrchestrator.ps1 -Action Register -WorkerId w1 -Title "lane task"
  .\Invoke-GrokWorkerPoolOrchestrator.ps1 -Action Complete -WorkerId w1 -Status success
  .\Invoke-GrokWorkerPoolOrchestrator.ps1 -Action RunOnce -Prompt "Do X; write evidence" -MaxParallel 4
#>
param(
    [ValidateSet("Pulse", "Register", "Complete", "Read", "RunOnce")]
    [string]$Action = "Pulse",
    [string]$WorkerId = "",
    [string]$Title = "",
    [ValidateSet("running", "success", "failed", "cancelled", "timeout")]
    [string]$Status = "running",
    [ValidateRange(0, 32)]
    [int]$MaxParallel = 0,
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "grok-composer-2.5-fast",
    [int]$MaxTurns = 8,
    [string]$GrokHome = "C:\Users\xx363\.grok-4.5-lane",
    [ValidateSet("worker_pool", "composer25_background")]
    [string]$SpawnMode = "composer25_background",
    [switch]$SkipPauseGate,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = "D:\XINAO_RESEARCH_RUNTIME"
if (Test-Path -LiteralPath (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")) {
    try { $runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") } catch { }
}
$contractPath = Join-Path $bridge "grok_worker_pool_refill.v1.json"
$poolScript = Join-Path $bridge "Invoke-GrokWorkerPool.ps1"
$workerScript = Join-Path $bridge "Invoke-GrokComposer25Worker.ps1"
$ledgerDir = Join-Path $runtime "state\grok_worker_pool_ledger"
$latestPath = Join-Path $ledgerDir "latest.json"
$pinnedFrontierPath = Join-Path $ledgerDir "pinned_frontier.json"
$pausePath = Join-Path $runtime "state\kaigong_wave\user_pause_all_latest.json"
$resumePath = Join-Path $runtime "state\kaigong_wave\user_resume_worker_pool_latest.json"
$zhPath = Join-Path $runtime "readback\zh\grok_worker_pool_refill_latest.md"
New-Item -ItemType Directory -Force -Path $ledgerDir, (Split-Path $zhPath) | Out-Null

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function To-SafeInt([object]$Value, [int]$Default = 0) {
    if ($null -eq $Value) { return $Default }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double]) { return [int]$Value }
    $s = [string]$Value
    if ([string]::IsNullOrWhiteSpace($s)) { return $Default }
    $n = 0
    if ([int]::TryParse($s, [ref]$n)) { return $n }
    return $Default
}

function Resolve-MaxParallel {
    if ($MaxParallel -gt 0) { return [math]::Min(32, [math]::Max(1, $MaxParallel)) }
    $c = Read-Json $contractPath
    if ($c -and $c.max_parallel_default) {
        return [math]::Min(32, [math]::Max(1, [int]$c.max_parallel_default))
    }
    return 4
}

function Test-WorkerPoolPauseBlocked {
    if ($SkipPauseGate) {
        return [pscustomobject]@{ blocked = $false; reason = "SkipPauseGate"; pause_status = $null }
    }
    $status = $null
    $spawn = $true
    if (Test-Path -LiteralPath $pausePath) {
        try {
            $pause = Read-Json $pausePath
            if ($pause) {
                $status = [string]$pause.status
                if ($null -ne $pause.subagent_spawn) { $spawn = [bool]$pause.subagent_spawn }
            }
        } catch { }
    }
    # RESUMED_WORKER_POOL explicitly allows headless pool path
    if ($status -eq "RESUMED_WORKER_POOL") {
        return [pscustomobject]@{ blocked = $false; reason = "RESUMED_WORKER_POOL"; pause_status = $status }
    }
    if ($status -eq "PAUSED_ALL" -and $spawn -eq $false) {
        return [pscustomobject]@{
            blocked = $true
            reason  = "PAUSED_ALL + subagent_spawn=false"
            pause_status = $status
        }
    }
    # resume file may open pool even if pause status stale
    if (Test-Path -LiteralPath $resumePath) {
        try {
            $r = Read-Json $resumePath
            if ($r -and [string]$r.status -eq "RESUMED_WORKER_POOL") {
                return [pscustomobject]@{ blocked = $false; reason = "resume_file RESUMED_WORKER_POOL"; pause_status = $status }
            }
            if ($r -and $r.allows -and $r.allows.grok_worker_pool -eq $true) {
                return [pscustomobject]@{ blocked = $false; reason = "resume allows.grok_worker_pool"; pause_status = $status }
            }
        } catch { }
    }
    return [pscustomobject]@{ blocked = $false; reason = "open"; pause_status = $status }
}

function Resolve-DefaultPrompt {
    if ($PromptFile) {
        if (-not (Test-Path -LiteralPath $PromptFile)) { throw "PromptFile missing: $PromptFile" }
        return (Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8)
    }
    if (-not [string]::IsNullOrWhiteSpace($Prompt)) { return $Prompt }
    $prior = Read-Json $latestPath
    if ($prior -and $prior.default_prompt -and -not [string]::IsNullOrWhiteSpace([string]$prior.default_prompt)) {
        return [string]$prior.default_prompt
    }
    return ""
}

function Build-Frontier([string]$DefaultPromptText) {
    $queue = [System.Collections.Generic.List[object]]::new()
    $seen = @{}

    function Add-Item([string]$Id, [string]$Src, [string]$TitleCn, [int]$Pri, [string]$Hint = "") {
        if ($seen[$Id]) { return }
        $seen[$Id] = $true
        if (-not $Hint) { $Hint = $TitleCn }
        [void]$queue.Add([pscustomobject]@{
            id             = $Id
            source         = $Src
            title_cn       = $TitleCn
            priority       = $Pri
            prompt_hint_cn = $Hint
            lane           = "composer25"
        })
    }

    $pinned = Read-Json $pinnedFrontierPath
    if ($pinned -and $pinned.items) {
        foreach ($p in @($pinned.items)) {
            $id = if ($p.id) { [string]$p.id } else { "pin_$([guid]::NewGuid().ToString('N').Substring(0, 8))" }
            $t = if ($p.title_cn) { [string]$p.title_cn } else { $id }
            $hint = if ($p.prompt_hint_cn) { [string]$p.prompt_hint_cn } elseif ($p.prompt) { [string]$p.prompt } else { $t }
            Add-Item $id "pinned_frontier" $t (To-SafeInt $p.priority 90) $hint
        }
    }

    $prior = Read-Json $latestPath
    if ($prior -and $prior.frontier) {
        foreach ($f in @($prior.frontier | Select-Object -First 24)) {
            $id = if ($f.id) { [string]$f.id } else { continue }
            $t = if ($f.title_cn) { [string]$f.title_cn } else { $id }
            $hint = if ($f.prompt_hint_cn) { [string]$f.prompt_hint_cn } else { $t }
            Add-Item $id "prior_frontier" $t (To-SafeInt $f.priority 60) $hint
        }
    }

    $codex = Read-Json (Join-Path $runtime "state\codex_dispatch_grok_worker_pool\latest.json")
    if ($codex -and $codex.dispatch_id) {
        $hint = if ($DefaultPromptText) { $DefaultPromptText } else { "Codex dispatch $($codex.dispatch_id) headless worker slot" }
        Add-Item "codex_$($codex.dispatch_id)" "codex_dispatch" "Codex dispatch refill slot" 85 $hint
    }

    # Keep refill slots available when frontier thin (resident machine)
    if ($queue.Count -lt 4) {
        $base = if ($DefaultPromptText) { $DefaultPromptText } else { "[grok_worker_pool_refill] idle slot — wait for Codex prompt or pinned_frontier" }
        for ($k = 1; $k -le 4; $k++) {
            Add-Item "slot_generic_$k" "generic_slot" "Generic worker slot $k" (50 - $k) $base
        }
    }

    return @($queue | Sort-Object { - $_.priority })
}

function Build-SpawnDirectives([object[]]$Frontier, [int]$Count, [string]$DefaultPromptText) {
    $out = [System.Collections.Generic.List[object]]::new()
    $i = 0
    foreach ($f in $Frontier) {
        if ($i -ge $Count) { break }
        $hint = if ($f.prompt_hint_cn) { [string]$f.prompt_hint_cn } elseif ($DefaultPromptText) { $DefaultPromptText } else { [string]$f.title_cn }
        [void]$out.Add([ordered]@{
            directive_id   = "spawn_$([guid]::NewGuid().ToString('N').Substring(0, 8))"
            source_id      = [string]$f.id
            title_cn       = [string]$f.title_cn
            priority       = (To-SafeInt $f.priority 50)
            lane           = "composer25"
            prompt_hint_cn = $hint
            action_cn      = "IMMEDIATE spawn headless Composer25 (CREATE_NO_WINDOW); not Task45; not visible TUI"
            invoke_cn      = "Invoke-GrokWorkerPool.ps1 or Invoke-GrokComposer25Worker.ps1 -Background"
        })
        $i++
    }
    return @($out)
}

function Get-InFlightRunning([object]$Prior) {
    $list = [System.Collections.Generic.List[object]]::new()
    if ($Prior -and $Prior.in_flight) {
        foreach ($row in @($Prior.in_flight)) {
            if ([string]$row.status -eq "running") { [void]$list.Add($row) }
        }
    }
    return $list
}

function Write-WorkerPoolLedger([hashtable]$Payload) {
    $Payload.generated_at = (Get-Date).ToString("o")
    $Payload.schema_version = "xinao.grok_worker_pool_ledger.v1"
    $Payload.sentinel = "SENTINEL:GROK_WORKER_POOL_ORCHESTRATOR"
    $Payload.completion_claim_allowed = $false
    $Payload.contract_ref = "grok_worker_pool_refill.v1.json"
    $Payload.hot_path_batch_cn = "Invoke-GrokWorkerPool.ps1 still valid for one-shot -N (unchanged default)"
    $Payload.ledger_path = $latestPath
    $Payload.not_cn = @(
        "does not claim 333 closed",
        "not Task45 subagent_pool lane owner",
        "not visible TUI inject default"
    )
    $json = ($Payload | ConvertTo-Json -Depth 12)
    [System.IO.File]::WriteAllText($latestPath, $json, $utf8)

    $md = @"
# Grok worker pool refill ledger

- time: $($Payload.generated_at)
- max_parallel: **$($Payload.max_parallel)** · in_flight: **$($Payload.in_flight_count)** · refill_required: **$($Payload.refill_required)** · refill_count: **$($Payload.refill_count)**
- last_action: $($Payload.last_action)
- ledger: ``$latestPath``
- complete-then-refill: Complete 后立刻重算 refill_count；RunOnce 在 refill_required 时 spawn CREATE_NO_WINDOW 工人
- pause: PAUSED_ALL + subagent_spawn=false 拒 RunOnce；RESUMED_WORKER_POOL 允许
- completion_claim_allowed: false（不宣称 333 闭合）

## spawn_directives ($($Payload.refill_count))
$($Payload.spawn_directives | ForEach-Object { "- $($_.directive_id) | $($_.title_cn)" } | Out-String)
"@
    [System.IO.File]::WriteAllText($zhPath, $md, $utf8)
}

function Invoke-PulseCore([System.Collections.Generic.List[object]]$InFlight, [int]$MaxP, [string]$DefaultPromptText, [string]$LastAction, [hashtable]$Extra = @{}) {
    $frontier = Build-Frontier $DefaultPromptText
    $refill = [math]::Max(0, $MaxP - $InFlight.Count)
    $directives = Build-SpawnDirectives $frontier $refill $DefaultPromptText
    $payload = @{
        max_parallel       = $MaxP
        in_flight          = @($InFlight)
        in_flight_count    = $InFlight.Count
        frontier           = @($frontier | Select-Object -First 24)
        frontier_depth     = $frontier.Count
        refill_required    = ($refill -gt 0)
        refill_count       = $refill
        spawn_directives   = $directives
        last_action        = $LastAction
        default_prompt     = $DefaultPromptText
        model              = $Model
        cwd                = if ($Cwd) { $Cwd } else { (Get-Location).Path }
        per_turn_rule_cn   = "Read ledger: if refill_required then RunOnce or Register+spawn to max_parallel; on Complete recompute refill immediately"
        shape_cn           = "max_parallel + complete-then-refill resident machine for Codex->Grok headless workers"
    }
    foreach ($k in $Extra.Keys) { $payload[$k] = $Extra[$k] }
    Write-WorkerPoolLedger $payload
    return $payload
}

function Start-Composer25Background([string]$LanePrompt, [string]$EvidenceDir, [string]$WorkCwd) {
    if (-not (Test-Path -LiteralPath $workerScript)) {
        throw "WORKER_SCRIPT_MISSING: $workerScript"
    }
    New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
    $pf = Join-Path $EvidenceDir "prompt.md"
    [System.IO.File]::WriteAllText($pf, $LanePrompt, $utf8)
    $args = @{
        PromptFile  = $pf
        Cwd         = $WorkCwd
        Model       = $Model
        MaxTurns    = $MaxTurns
        GrokHome    = $GrokHome
        EvidenceDir = $EvidenceDir
        Background  = $true
        Quiet       = $true
    }
    & $workerScript @args
    $code = $LASTEXITCODE
    $meta = $null
    $laneLatest = Join-Path $EvidenceDir "latest.json"
    if (Test-Path -LiteralPath $laneLatest) {
        try { $meta = Read-Json $laneLatest } catch { }
    }
    return [pscustomobject]@{
        exit_code    = $code
        evidence_dir = $EvidenceDir
        pid          = if ($meta) { $meta.pid } else { $null }
        run_id       = if ($meta) { $meta.run_id } else { $null }
        status       = if ($meta) { [string]$meta.status } else { "spawned" }
    }
}

# --- main ---
$maxP = Resolve-MaxParallel
$prior = Read-Json $latestPath
$inFlight = Get-InFlightRunning $prior
$defaultPromptText = Resolve-DefaultPrompt
$workCwd = if ($Cwd) { $Cwd } else { (Get-Location).Path }

switch ($Action) {
    "Register" {
        if (-not $WorkerId) { $WorkerId = "gww_$([guid]::NewGuid().ToString('N').Substring(0, 10))" }
        $deduped = [System.Collections.Generic.List[object]]::new()
        foreach ($row in @($inFlight)) {
            if ([string]$row.id -ne $WorkerId) { [void]$deduped.Add($row) }
        }
        $inFlight = $deduped
        [void]$inFlight.Add([ordered]@{
            id         = $WorkerId
            title      = $Title
            status     = "running"
            lane       = "composer25"
            started_at = (Get-Date).ToString("o")
        })
        $payload = Invoke-PulseCore $inFlight $maxP $defaultPromptText "register" @{
            registered_id = $WorkerId
        }
        if (-not $Quiet) {
            @{ ok = $true; id = $WorkerId; in_flight_count = $inFlight.Count; refill_count = $payload.refill_count; refill_required = $payload.refill_required } | ConvertTo-Json -Depth 6
        }
        exit 0
    }

    "Complete" {
        if (-not $WorkerId) { throw "Complete requires -WorkerId" }
        $newList = [System.Collections.Generic.List[object]]::new()
        foreach ($row in @($inFlight)) {
            if ([string]$row.id -eq $WorkerId) { continue }
            if ([string]$row.status -eq "running") { [void]$newList.Add($row) }
        }
        $inFlight = $newList
        # Complete -> immediately recompute refill_count
        $payload = Invoke-PulseCore $inFlight $maxP $defaultPromptText "complete" @{
            completed_id         = $WorkerId
            completed_status     = $Status
            immediate_refill_cn  = "complete -> immediate refill; refill_count recomputed"
        }
        if (-not $Quiet) {
            @{
                ok              = $true
                completed_id    = $WorkerId
                completed_status = $Status
                in_flight_count = $inFlight.Count
                refill_count    = $payload.refill_count
                refill_required = $payload.refill_required
                spawn_directives = $payload.spawn_directives
            } | ConvertTo-Json -Depth 8
        }
        exit 0
    }

    "Read" {
        if (-not (Test-Path -LiteralPath $latestPath)) {
            & $PSCommandPath -Action Pulse -MaxParallel $maxP -Quiet | Out-Null
        }
        Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8
        exit 0
    }

    "RunOnce" {
        $gate = Test-WorkerPoolPauseBlocked
        if ($gate.blocked) {
            $err = [ordered]@{
                ok = $false
                error = "PAUSED_ALL"
                detail_cn = "status=PAUSED_ALL 且 subagent_spawn=false：拒 RunOnce。清 pause 或 -SkipPauseGate。RESUMED_WORKER_POOL 允许。"
                pause_status = $gate.pause_status
                reason = $gate.reason
                pause_path = $pausePath
                completion_claim_allowed = $false
            }
            # Prefer JSON + exit 3 (do not Write-Error: Stop mode aborts before exit code).
            $err | ConvertTo-Json -Depth 6 | Write-Output
            exit 3
        }

        # Refresh ledger first
        $payload = Invoke-PulseCore $inFlight $maxP $defaultPromptText "runonce_pre" @{
            pause_gate = $gate
        }
        if (-not $payload.refill_required -or $payload.refill_count -le 0) {
            if (-not $Quiet) {
                @{
                    ok = $true
                    spawned = 0
                    refill_required = $false
                    in_flight_count = $inFlight.Count
                    max_parallel = $maxP
                    note_cn = "slots full or no refill; no spawn"
                    ledger = $latestPath
                } | ConvertTo-Json -Depth 6
            }
            exit 0
        }

        $spawnN = [int]$payload.refill_count
        $directives = @($payload.spawn_directives)
        $spawnResults = [System.Collections.Generic.List[object]]::new()
        $runRoot = Join-Path $ledgerDir ("run_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 6)))
        New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

        if ($SpawnMode -eq "worker_pool") {
            if (-not (Test-Path -LiteralPath $poolScript)) { throw "POOL_SCRIPT_MISSING: $poolScript" }
            $promptBody = $defaultPromptText
            if (-not $promptBody -and $directives.Count -gt 0) {
                $promptBody = [string]$directives[0].prompt_hint_cn
            }
            if ([string]::IsNullOrWhiteSpace($promptBody)) {
                $promptBody = "[grok_worker_pool_refill] RunOnce batch spawn $spawnN"
            }
            $poolArgs = @{
                N           = $spawnN
                Prompt      = $promptBody
                Cwd         = $workCwd
                Model       = $Model
                MaxTurns    = $MaxTurns
                GrokHome    = $GrokHome
                TimeoutSec  = 120
                Quiet       = $true
            }
            if ($SkipPauseGate) { $poolArgs.SkipPauseGate = $true }
            # Batch path waits; still honor CREATE_NO_WINDOW inside WorkerPool
            & $poolScript @poolArgs
            $poolCode = $LASTEXITCODE
            for ($i = 0; $i -lt $spawnN; $i++) {
                $wid = "gwp_batch_$i" + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 6))
                [void]$inFlight.Add([ordered]@{
                    id         = $wid
                    title      = "worker_pool lane $i"
                    status     = "running"
                    lane       = "composer25"
                    started_at = (Get-Date).ToString("o")
                    spawn_mode = "worker_pool"
                })
                [void]$spawnResults.Add([ordered]@{
                    worker_id = $wid
                    lane = $i
                    pool_exit = $poolCode
                    spawn_mode = "worker_pool"
                })
            }
        } else {
            # Default: per-directive Composer25 Background (CREATE_NO_WINDOW), non-blocking slots
            $i = 0
            foreach ($d in $directives) {
                if ($i -ge $spawnN) { break }
                $wid = if ($d.directive_id) { [string]$d.directive_id } else { "gww_$([guid]::NewGuid().ToString('N').Substring(0, 10))" }
                $laneDir = Join-Path $runRoot ("lane_{0:D2}" -f $i)
                $body = if ($d.prompt_hint_cn) { [string]$d.prompt_hint_cn } else { $defaultPromptText }
                if ([string]::IsNullOrWhiteSpace($body)) {
                    $body = "[grok_worker_pool_refill] $($d.title_cn)"
                }
                $lanePrompt = @"
[grok_worker_pool_refill]
worker_id=$wid
source_id=$($d.source_id)
lane=$i
max_parallel=$maxP
model=$Model

$body
"@
                try {
                    $sr = Start-Composer25Background -LanePrompt $lanePrompt -EvidenceDir $laneDir -WorkCwd $workCwd
                    [void]$inFlight.Add([ordered]@{
                        id           = $wid
                        title        = [string]$d.title_cn
                        status       = "running"
                        lane         = "composer25"
                        started_at   = (Get-Date).ToString("o")
                        pid          = $sr.pid
                        run_id       = $sr.run_id
                        evidence_dir = $sr.evidence_dir
                        spawn_mode   = "composer25_background"
                    })
                    [void]$spawnResults.Add([ordered]@{
                        worker_id    = $wid
                        lane         = $i
                        pid          = $sr.pid
                        run_id       = $sr.run_id
                        evidence_dir = $sr.evidence_dir
                        status       = $sr.status
                        spawn_mode   = "composer25_background"
                    })
                } catch {
                    [void]$spawnResults.Add([ordered]@{
                        worker_id = $wid
                        lane = $i
                        status = "spawn_error"
                        error = "$_"
                    })
                }
                $i++
            }
        }

        $payload = Invoke-PulseCore $inFlight $maxP $defaultPromptText "runonce" @{
            pause_gate     = $gate
            spawned_count  = $spawnResults.Count
            spawn_results  = @($spawnResults)
            run_root       = $runRoot
            spawn_mode     = $SpawnMode
        }

        if (-not $Quiet) {
            @{
                ok              = $true
                spawned         = $spawnResults.Count
                spawn_mode      = $SpawnMode
                in_flight_count = $inFlight.Count
                max_parallel    = $maxP
                refill_required = $payload.refill_required
                refill_count    = $payload.refill_count
                spawn_results   = @($spawnResults)
                ledger          = $latestPath
                pause_gate      = $gate
                completion_claim_allowed = $false
            } | ConvertTo-Json -Depth 10
        }
        exit 0
    }

    default {
        # Pulse
        $payload = Invoke-PulseCore $inFlight $maxP $defaultPromptText "pulse"
        if (-not $Quiet) {
            Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8
        }
        exit 0
    }
}
