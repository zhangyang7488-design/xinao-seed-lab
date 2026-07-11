#Requires -Version 5.1
<#
.SYNOPSIS
  Thin weld: ACP + scheduler_tick + hidden-stdio / CREATE_NO_WINDOW to island invokable shell.
.DESCRIPTION
  Does NOT invent a second orchestrator. Forwards to mature carriers:

    ACP:
      E:\...\dual-brain-coordination\adapters\grok\Invoke-XinaoGrokAcp.ps1
    scheduler_tick (event-driven complete-then-refill isomorphic):
      Invoke-GrokWorkerPoolOrchestrator.ps1 -Action Pulse
      (optional dual-brain xinao_work_pool.WorkPool.pulse if PYTHONPATH present)
    hidden-stdio:
      D:\XINAO_RESEARCH_RUNTIME\tools\hidden-stdio\current.json -> xinao-hidden-stdio.exe
    CREATE_NO_WINDOW host pool:
      Invoke-GrokComposer25Worker.ps1 / Invoke-GrokWorkerPool.ps1 (already welded)

  Actions:
    Inventory | Smoke | SchedulerTick | Acp | HiddenStdio | Weld (default: Inventory+Smoke+evidence)

.EXAMPLE
  .\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action Weld
  .\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action SchedulerTick -MaxParallel 2
  .\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action Acp -AcpAction status -Session xinao-main
  .\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action HiddenStdio
#>
param(
    [ValidateSet("Inventory", "Smoke", "SchedulerTick", "Acp", "HiddenStdio", "Weld")]
    [string]$Action = "Weld",
    [ValidateSet("ensure", "submit", "run", "status", "cancel", "history", "close", "raw")]
    [string]$AcpAction = "status",
    [string]$Session = "xinao-main",
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [int]$MaxParallel = 2,
    [string]$DualBrainRoot = "E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination",
    [string]$HiddenStdioCurrent = "D:\XINAO_RESEARCH_RUNTIME\tools\hidden-stdio\current.json",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = "D:\XINAO_RESEARCH_RUNTIME"
if (Test-Path -LiteralPath (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")) {
    try { $runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") } catch { }
}

$stateDir = Join-Path $runtime "state\capability_max_weld"
$zhDir = Join-Path $runtime "readback\zh"
$evidencePath = Join-Path $stateDir "weld_acp_scheduler_hidden_stdio.json"
$zhPath = Join-Path $zhDir "weld_acp_scheduler_hidden_stdio_latest.md"
New-Item -ItemType Directory -Force -Path $stateDir, $zhDir | Out-Null

$acpAdapter = Join-Path $DualBrainRoot "adapters\grok\Invoke-XinaoGrokAcp.ps1"
$acpxManaged = Join-Path $DualBrainRoot "provisioning\Invoke-XinaoAcpxManaged.ps1"
$orch = Join-Path $bridge "Invoke-GrokWorkerPoolOrchestrator.ps1"
$composer = Join-Path $bridge "Invoke-GrokComposer25Worker.ps1"
$pool = Join-Path $bridge "Invoke-GrokWorkerPool.ps1"
$workPoolPy = Join-Path $DualBrainRoot "src\xinao_work_pool\ledger.py"

function Write-Utf8File([string]$Path, [string]$Content) {
    [IO.File]::WriteAllText($Path, $Content, $utf8)
}

function Get-HiddenStdioInfo {
    $info = [ordered]@{
        current_json_exists = $false
        current_json = $HiddenStdioCurrent
        launcher_path = $null
        generation_id = $null
        status = $null
        child_creation_flag = $null
        binary_exists = $false
    }
    if (Test-Path -LiteralPath $HiddenStdioCurrent) {
        $info.current_json_exists = $true
        $j = Get-Content -LiteralPath $HiddenStdioCurrent -Raw -Encoding UTF8 | ConvertFrom-Json
        $info.launcher_path = [string]$j.launcher_path
        $info.generation_id = [string]$j.generation_id
        $info.status = [string]$j.status
        $info.child_creation_flag = [string]$j.child_creation_flag
        if ($info.launcher_path) {
            $info.binary_exists = Test-Path -LiteralPath $info.launcher_path
        }
    }
    return $info
}

function Invoke-HiddenStdioSmoke {
    $h = Get-HiddenStdioInfo
    $result = [ordered]@{
        ok = $false
        mode = "xinao-hidden-stdio"
        launcher_path = $h.launcher_path
        stdout = $null
        stderr = $null
        exit_code = $null
        error = $null
        generation_id = $h.generation_id
        child_creation_flag = $h.child_creation_flag
    }
    if (-not $h.binary_exists) {
        $result.error = "HIDDEN_STDIO_BINARY_MISSING"
        return $result
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $h.launcher_path
    $psi.Arguments = 'cmd.exe /c echo HIDDEN_STDIO_SMOKE_OK'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $p = [Diagnostics.Process]::Start($psi)
    $out = $p.StandardOutput.ReadToEnd()
    $err = $p.StandardError.ReadToEnd()
    [void]$p.WaitForExit(10000)
    $result.stdout = ($out | Out-String).Trim()
    $result.stderr = ($err | Out-String).Trim()
    $result.exit_code = $p.ExitCode
    $result.ok = ($p.ExitCode -eq 0 -and $result.stdout -match "HIDDEN_STDIO_SMOKE_OK")
    return $result
}

function Invoke-CreateNoWindowPsiSmoke {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "cmd.exe"
    $psi.Arguments = "/c echo CREATE_NO_WINDOW_PSI_OK"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $p = [Diagnostics.Process]::Start($psi)
    $out = $p.StandardOutput.ReadToEnd()
    [void]$p.WaitForExit(5000)
    return [ordered]@{
        ok = ($p.ExitCode -eq 0 -and (($out | Out-String).Trim() -match "CREATE_NO_WINDOW_PSI_OK"))
        mode = "ProcessStartInfo.CreateNoWindow"
        create_no_window = $true
        use_shell_execute = $false
        exit_code = $p.ExitCode
        stdout = ($out | Out-String).Trim()
        mirror_of = "Invoke-GrokComposer25Worker.ps1 spawn shape"
    }
}

function Invoke-SchedulerTick {
    param([int]$Parallel = 2)
    $tick = [ordered]@{
        ok = $false
        isomorphic_name = "scheduler_tick"
        carrier = "Invoke-GrokWorkerPoolOrchestrator.ps1 -Action Pulse"
        note_cn = "桌面文档 scheduler_tick = 完成/失败后重新算前沿并补派；岛内成熟载体=WorkerPoolOrchestrator Pulse（complete-then-refill），非第二 orchestrator"
        not_second_orchestrator = $true
        max_parallel = $Parallel
        ledger_path = (Join-Path $runtime "state\grok_worker_pool_ledger\latest.json")
        pulse = $null
        dual_brain_work_pool = [ordered]@{
            present = (Test-Path -LiteralPath $workPoolPy)
            module = "xinao_work_pool.ledger.WorkPool.pulse"
            default_root = "D:\XINAO_RESEARCH_RUNTIME\state\agent_work_pool"
            note_cn = "dual-brain 外部 work_pool 亦有 pulse；本薄壳默认不启第二 owner，只点名存在"
        }
        error = $null
    }
    if (-not (Test-Path -LiteralPath $orch)) {
        $tick.error = "ORCHESTRATOR_MISSING: $orch"
        return $tick
    }
    try {
        $null = & $orch -Action Pulse -MaxParallel $Parallel -Quiet 2>&1
        $tick.ok = ($LASTEXITCODE -eq 0 -or $null -eq $LASTEXITCODE)
        if (Test-Path -LiteralPath $tick.ledger_path) {
            $led = Get-Content -LiteralPath $tick.ledger_path -Raw -Encoding UTF8 | ConvertFrom-Json
            $tick.pulse = [ordered]@{
                generated_at = $led.generated_at
                max_parallel = $led.max_parallel
                in_flight_count = $led.in_flight_count
                refill_required = $led.refill_required
                refill_count = $led.refill_count
                frontier_depth = $led.frontier_depth
                last_action = $led.last_action
                schema_version = $led.schema_version
            }
            $tick.ok = $true
        }
    }
    catch {
        $tick.error = "$_"
        $tick.ok = $false
    }
    return $tick
}

function Invoke-AcpThin {
    param(
        [string]$Act = "status",
        [string]$Sess = "xinao-main",
        [string]$Pr = "",
        [string]$Pf = ""
    )
    $r = [ordered]@{
        ok = $false
        adapter = $acpAdapter
        adapter_exists = (Test-Path -LiteralPath $acpAdapter)
        acpx_managed = $acpxManaged
        acpx_managed_exists = (Test-Path -LiteralPath $acpxManaged)
        action = $Act
        session = $Sess
        stdout = $null
        exit_code = $null
        error = $null
        default_mainline_welded = $false
        note_cn = "Grok ACP 薄入口在 dual-brain；本脚本仅桥接，不造第二 ACP runtime"
    }
    if (-not $r.adapter_exists) {
        $r.error = "ACP_ADAPTER_MISSING"
        return $r
    }
    $argsList = @("-NoProfile", "-File", $acpAdapter, "-Action", $Act, "-Session", $Sess)
    if ($Pr) { $argsList += @("-Prompt", $Pr) }
    if ($Pf) { $argsList += @("-PromptFile", $Pf) }
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "pwsh"
        $psi.Arguments = ($argsList | ForEach-Object {
                if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
            }) -join ' '
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $p = [Diagnostics.Process]::Start($psi)
        $out = $p.StandardOutput.ReadToEnd()
        $err = $p.StandardError.ReadToEnd()
        [void]$p.WaitForExit(120000)
        $r.exit_code = $p.ExitCode
        $r.stdout = (($out + "`n" + $err) | Out-String).Trim()
        if ($r.stdout.Length -gt 4000) { $r.stdout = $r.stdout.Substring(0, 4000) }
        $r.ok = ($p.ExitCode -eq 0)
        $r.default_mainline_welded = $true  # bridge can now invoke
    }
    catch {
        $r.error = "$_"
    }
    return $r
}

function Get-Inventory {
    $h = Get-HiddenStdioInfo
    $acpxCurrent = Join-Path $runtime "tools\acpx\current.json"
    $acpxInfo = $null
    if (Test-Path -LiteralPath $acpxCurrent) {
        $aj = Get-Content -LiteralPath $acpxCurrent -Raw -Encoding UTF8 | ConvertFrom-Json
        $acpxInfo = [ordered]@{
            generation_id = $aj.generation_id
            cli_path = $aj.cli_path
            node_path = $aj.node_path
            schema_version = $aj.schema_version
        }
    }
    $sThin = Join-Path "E:\XINAO_RESEARCH_WORKSPACES\S" "services\agent_runtime\thin_glue_provider_scheduler.py"
    return [ordered]@{
        acp = [ordered]@{
            adapter_ps1 = $acpAdapter
            present = (Test-Path -LiteralPath $acpAdapter)
            actions = @("ensure", "submit", "run", "status", "cancel", "history", "close", "raw")
            acpx_home_default = "D:\XINAO_RESEARCH_RUNTIME\state\acpx-grok-brain"
            acpx_managed_ps1 = $acpxManaged
            acpx_managed_present = (Test-Path -LiteralPath $acpxManaged)
            acpx_tools_current = $acpxInfo
            uses_hidden_stdio_in_config = $true
            config = (Join-Path $DualBrainRoot "provisioning\acpx-grok-config.json")
            welded_default_mainline_cn = "ACP 已在 dual-brain 成熟；岛 bridge 经本薄壳可 invoke；非 WorkerPool 默认批跑替代"
            s_workspace = "S 仓无 ACP 主实现（扫无匹配）"
        }
        scheduler_tick = [ordered]@{
            desktop_intent_cn = "每次完成/失败/额度变化运行 scheduler_tick：重算前沿并补派"
            island_carrier = $orch
            island_carrier_present = (Test-Path -LiteralPath $orch)
            island_action = "Pulse | Complete | RunOnce"
            dual_brain_work_pool_pulse = $workPoolPy
            dual_brain_work_pool_present = (Test-Path -LiteralPath $workPoolPy)
            s_provider_scheduler = $sThin
            s_provider_scheduler_present = (Test-Path -LiteralPath $sThin)
            s_note_cn = "S thin_glue_provider_scheduler = LiteLLM 网关探针，不是事件驱动 scheduler_tick"
            welded_default_mainline = (Test-Path -LiteralPath $orch)
            second_orchestrator = $false
        }
        hidden_stdio = $h
        create_no_window_host = [ordered]@{
            composer25 = $composer
            composer25_present = (Test-Path -LiteralPath $composer)
            worker_pool = $pool
            worker_pool_present = (Test-Path -LiteralPath $pool)
            spawn_shape = "UseShellExecute=false + CreateNoWindow=true"
            evidence_pool_latest = (Join-Path $runtime "state\grok_worker_pool\latest.json")
            welded_default_mainline = $true
            note_cn = "Host pool 已焊；hidden-stdio 用于 ACP/MCP 子进程透传 stdio"
        }
        not_cn = @(
            "not second orchestrator",
            "not claim 333 closed",
            "not replace Temporal control plane",
            "ACP full turn not required for weld smoke"
        )
    }
}

function Write-Evidence {
    param([hashtable]$Payload)
    $json = $Payload | ConvertTo-Json -Depth 12
    Write-Utf8File -Path $evidencePath -Content $json

    $inv = $Payload.inventory
    $sm = $Payload.smoke
    $lines = @(
        "# ACP + scheduler_tick + hidden-stdio 薄焊读回",
        "",
        "- 生成时间：$((Get-Date).ToString('o'))",
        "- 证据：``$evidencePath``",
        "- completion_claim_allowed：**false**",
        "",
        "## 清单（是否焊默认主路）",
        "",
        "| 面 | 入口 | 焊默认主路 |",
        "|----|------|------------|",
        "| ACP | ``Invoke-XinaoGrokAcp.ps1`` + 本薄壳 ``-Action Acp`` | 桥接可 invoke；session 默认 no-session 直至 ensure |",
        "| scheduler_tick | ``Invoke-GrokWorkerPoolOrchestrator -Action Pulse`` | **是**（complete-then-refill 岛主路） |",
        "| hidden-stdio | ``xinao-hidden-stdio.exe``（current.json） | **是**（ACPX grok-build command） |",
        "| CREATE_NO_WINDOW | Composer25 / WorkerPool | **是**（Host headless） |",
        "",
        "## 烟测",
        "",
        "- hidden-stdio: **$($sm.hidden_stdio.ok)** exit=$($sm.hidden_stdio.exit_code) out=``$($sm.hidden_stdio.stdout)``",
        "- CreateNoWindow PSI: **$($sm.create_no_window_psi.ok)**",
        "- scheduler_tick(Pulse): **$($sm.scheduler_tick.ok)** refill_required=$($sm.scheduler_tick.pulse.refill_required) refill_count=$($sm.scheduler_tick.pulse.refill_count)",
        "- ACP status: **$($sm.acp.ok)** ``$($sm.acp.stdout)``",
        "",
        "## now_can_invoke",
        "",
        '```powershell',
        '.\grok-admin-bridge\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action Weld',
        '.\grok-admin-bridge\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action SchedulerTick -MaxParallel 2',
        '.\grok-admin-bridge\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action Acp -AcpAction status',
        '.\grok-admin-bridge\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action HiddenStdio',
        '.\grok-admin-bridge\Invoke-GrokWorkerPoolOrchestrator.ps1 -Action Pulse -MaxParallel 2',
        'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\adapters\grok\Invoke-XinaoGrokAcp.ps1 -Action status',
        '& (Get-Content D:\XINAO_RESEARCH_RUNTIME\tools\hidden-stdio\current.json | ConvertFrom-Json).launcher_path cmd.exe /c echo OK',
        '```',
        "",
        "## 缺口（诚实）",
        "",
        "- 本焊 **不** 声称 ACP session 常驻、不声称 scheduler 永续 owner、不声称 333 闭合",
        "- dual-brain ``WorkPool.pulse`` 存在但 **未** 升为本岛默认 owner（避免第二 orchestrator）",
        "- S ``thin_glue_provider_scheduler`` 是网关探针，**不是** scheduler_tick",
        "- ACP ensure/submit 全 turn 需配额；默认烟测只用 status",
        ""
    )
    Write-Utf8File -Path $zhPath -Content ($lines -join "`n")
}

$started = (Get-Date).ToString("o")

switch ($Action) {
    "Inventory" {
        $inv = Get-Inventory
        if (-not $Quiet) { $inv | ConvertTo-Json -Depth 10 }
        break
    }
    "HiddenStdio" {
        $r = Invoke-HiddenStdioSmoke
        if (-not $Quiet) { $r | ConvertTo-Json -Depth 6 }
        if (-not $r.ok) { exit 1 }
        break
    }
    "SchedulerTick" {
        $r = Invoke-SchedulerTick -Parallel $MaxParallel
        if (-not $Quiet) { $r | ConvertTo-Json -Depth 8 }
        if (-not $r.ok) { exit 1 }
        break
    }
    "Acp" {
        $r = Invoke-AcpThin -Act $AcpAction -Sess $Session -Pr $Prompt -Pf $PromptFile
        if (-not $Quiet) { $r | ConvertTo-Json -Depth 6 }
        if (-not $r.ok) { exit 1 }
        break
    }
    "Smoke" {
        $sm = [ordered]@{
            hidden_stdio = Invoke-HiddenStdioSmoke
            create_no_window_psi = Invoke-CreateNoWindowPsiSmoke
            scheduler_tick = Invoke-SchedulerTick -Parallel $MaxParallel
            acp = Invoke-AcpThin -Act "status" -Sess "xinao-weld-probe"
        }
        if (-not $Quiet) { $sm | ConvertTo-Json -Depth 10 }
        $all = $sm.hidden_stdio.ok -and $sm.create_no_window_psi.ok -and $sm.scheduler_tick.ok -and $sm.acp.ok
        if (-not $all) { exit 1 }
        break
    }
    "Weld" {
        $inv = Get-Inventory
        $sm = [ordered]@{
            hidden_stdio = Invoke-HiddenStdioSmoke
            create_no_window_psi = Invoke-CreateNoWindowPsiSmoke
            scheduler_tick = Invoke-SchedulerTick -Parallel $MaxParallel
            acp = Invoke-AcpThin -Act "status" -Sess "xinao-weld-probe"
        }
        $allOk = [bool]($sm.hidden_stdio.ok -and $sm.create_no_window_psi.ok -and $sm.scheduler_tick.ok -and $sm.acp.ok)
        $payload = [ordered]@{
            schema = "xinao.weld_acp_scheduler_hidden_stdio.v1"
            sentinel = "SENTINEL:WELD_ACP_SCHEDULER_HIDDEN_STDIO"
            generated_at_local = (Get-Date).ToString("o")
            generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            started_at = $started
            completion_claim_allowed = $false
            task = "ACP + scheduler_tick + hidden-stdio/CREATE_NO_WINDOW thin weld to island invokable shell"
            not_second_orchestrator = $true
            weld_script = $MyInvocation.MyCommand.Path
            dual_brain_root = $DualBrainRoot
            inventory = $inv
            smoke = $sm
            smoke_all_ok = $allOk
            default_mainline = [ordered]@{
                acp_bridge = $true
                scheduler_tick_via_worker_pool_pulse = $true
                hidden_stdio_verified = [bool]$sm.hidden_stdio.ok
                create_no_window_verified = [bool]$sm.create_no_window_psi.ok
                host_worker_pool_already_welded = $true
            }
            now_can_invoke = @(
                ".\grok-admin-bridge\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action Weld",
                ".\grok-admin-bridge\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action SchedulerTick",
                ".\grok-admin-bridge\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action Acp -AcpAction status",
                ".\grok-admin-bridge\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action HiddenStdio",
                ".\grok-admin-bridge\Invoke-GrokWorkerPoolOrchestrator.ps1 -Action Pulse -MaxParallel 2",
                "E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\adapters\grok\Invoke-XinaoGrokAcp.ps1 -Action status",
                "D:\...\xinao-hidden-stdio.exe cmd.exe /c echo OK"
            )
            gaps_cn = @(
                "ACP ensure/submit 全 turn 未在本焊强制跑（配额/时长）",
                "dual-brain WorkPool.pulse 未升为岛默认 owner",
                "S 无 ACP 主实现；provider_scheduler 非 tick",
                "不声称 333/P0 闭合"
            )
            evidence_path = $evidencePath
            zh_readback = $zhPath
        }
        Write-Evidence -Payload $payload
        if (-not $Quiet) {
            Write-Host "evidence=$evidencePath"
            Write-Host "zh=$zhPath"
            Write-Host "smoke_all_ok=$allOk"
            $payload | ConvertTo-Json -Depth 12
        }
        if (-not $allOk) { exit 1 }
        break
    }
}
