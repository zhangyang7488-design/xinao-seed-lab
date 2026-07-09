#Requires -Version 5.1
<#
.SYNOPSIS
  极致本机状态感知（非安全面）— 共享工具池，Grok/后台都可 invoke。
  禁止清单制；明确排除密钥/CVE/Trivy 等安全目标。
  非 333 新控制面。
.EXAMPLE
  .\Invoke-GrokStateSenseMax.ps1
  .\Invoke-GrokStateSenseMax.ps1 -Roots @('E:\XINAO_RESEARCH_WORKSPACES\S\services\agent_runtime')
#>
param(
    [string[]]$Roots = @(),
    [switch]$SkipDockerDeep,
    [switch]$SkipCodeStats,
    [switch]$SkipGit,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$senseRoot = "E:\XINAO_EXTERNAL_MATURE\state-sense-stack"
$scanRoot = "E:\XINAO_EXTERNAL_MATURE\scan-stack"
$outDir = Join-Path $runtime "state\state_sense_max"
$latestPath = Join-Path $outDir "latest.json"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 18), $utf8)
}

# PATH: sense + scan-stack
$env:Path = (@(
    (Join-Path $senseRoot "bin"),
    (Join-Path $scanRoot "bin"),
    (Join-Path $scanRoot "py\.venv\Scripts"),
    (Join-Path $scanRoot "npm\node_modules\.bin")
) + @($env:Path)) -join ";"

$deny = [ordered]@{
    principle_cn = "deny_list_not_allow_list — 非白名单"
    never_as_goal = @("Trivy","Grype","OSV","Gitleaks","TruffleHog","secret_surface_scan","dependency_CVE_scan")
    never_emit_raw = @("reveal_raw_secret","*.pem","id_rsa",".env raw dump to chat")
    hard_stop = @("payment","2fa","real_name","irreversible_cloud_delete","self_lock","delete_desktop_without_explicit")
    noise_skip = @("node_modules",".venv","__pycache__",".git/objects")
}

# default roots (anchors + dynamic — not closed allow-list)
if ($Roots.Count -eq 0) {
    $Roots = @(
        "E:\XINAO_RESEARCH_WORKSPACES\S\services\agent_runtime",
        "E:\XINAO_RESEARCH_WORKSPACES\S\materials",
        "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace-grok-4.5-island\grok-admin-bridge",
        (Join-Path $runtime "state")
    ) | Where-Object { Test-Path $_ }
}

$modules = [ordered]@{}
$errors = [System.Collections.Generic.List[string]]::new()

# --- 0 base sense ---
try {
    $base = & (Join-Path $bridge "Get-GrokLocalStateSense.ps1") -Quiet
    $modules.base_sense = [ordered]@{
        ok = $true
        ref = (Join-Path $runtime "state\local_state_sense\latest.json")
        signals = $base.signals
        roots_n = @($base.roots).Count
        auth = $base.auth_shape_cn
    }
} catch {
    $modules.base_sense = [ordered]@{ ok = $false; error = "$_" }
    [void]$errors.Add("base_sense:$_")
}

# --- 1 system ---
try {
    $modules.system = [ordered]@{
        ok = $true
        os = [System.Environment]::OSVersion.VersionString
        machine = $env:COMPUTERNAME
        user = $env:USERNAME
        ps_version = $PSVersionTable.PSVersion.ToString()
        cpu_count = [Environment]::ProcessorCount
        python = (& python --version 2>&1 | Out-String).Trim()
        node = (& node --version 2>&1 | Out-String).Trim()
        git = (& git --version 2>&1 | Out-String).Trim()
        docker = (& docker version --format '{{.Server.Version}}' 2>&1 | Out-String).Trim()
        go = if (Get-Command go -EA SilentlyContinue) { (& go version 2>&1 | Out-String).Trim() } else { "n/a" }
    }
} catch {
    $modules.system = [ordered]@{ ok = $false; error = "$_" }
}

# --- 2 code stats (scc) ---
if (-not $SkipCodeStats) {
    $scc = Join-Path $senseRoot "bin\scc.exe"
    if (-not (Test-Path $scc)) { $scc = "scc" }
    $stats = @()
    foreach ($r in $Roots) {
        if (-not (Test-Path $r)) { continue }
        try {
            $json = & $scc --format json --exclude-dir node_modules,.venv,dist,build,__pycache__,.git $r 2>$null | Out-String
            $parsed = $null
            try { $parsed = $json | ConvertFrom-Json } catch { }
            $stats += [ordered]@{
                root = $r
                ok = $true
                summary = if ($parsed) {
                    @($parsed | Select-Object -First 12 | ForEach-Object {
                        [ordered]@{ Name = $_.Name; Lines = $_.Lines; Code = $_.Code; Files = $_.Count }
                    })
                } else { $null }
                raw_head = if ($json.Length -gt 500) { $json.Substring(0,500) } else { $json }
            }
        } catch {
            $stats += [ordered]@{ root = $r; ok = $false; error = "$_" }
        }
    }
    $modules.code_stats_scc = [ordered]@{ ok = $true; tool = "scc"; roots = $stats; note = "tokei-class LOC; no CVE" }
}

# --- 3 git (log/diff/status — no secret) ---
if (-not $SkipGit) {
    $gitMods = @()
    $gitRoots = @(
        "E:\XINAO_RESEARCH_WORKSPACES\S",
        "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace-grok-4.5-island"
    ) | Where-Object { Test-Path (Join-Path $_ ".git") }
    foreach ($gr in $gitRoots) {
        try {
            Push-Location $gr
            $gitMods += [ordered]@{
                root = $gr
                branch = (& git rev-parse --abbrev-ref HEAD 2>$null)
                status_short = @((& git status -sb 2>$null) | Select-Object -First 20)
                last_log = @((& git log -5 --oneline 2>$null))
                diff_stat = @((& git diff --stat HEAD 2>$null) | Select-Object -First 30)
                dirty = ((& git status --porcelain 2>$null | Measure-Object).Count -gt 0)
            }
        } catch {
            $gitMods += [ordered]@{ root = $gr; error = "$_" }
        } finally { Pop-Location }
    }
    $modules.git = [ordered]@{
        ok = $true
        repos = $gitMods
        gh_available = [bool](Get-Command gh -EA SilentlyContinue)
        note = "history/status/diff for gap analysis; not secret scan"
    }
}

# --- 4 docker deep ---
if (-not $SkipDockerDeep) {
    try {
        $ps = @((docker ps -a --format "{{json .}}" 2>$null) | ForEach-Object { try { $_ | ConvertFrom-Json } catch { $null } } | Where-Object { $_ })
        $networks = @((docker network ls --format "{{.Name}}|{{.Driver}}" 2>$null))
        $inspectBrief = @()
        foreach ($c in ($ps | Select-Object -First 12)) {
            $name = $c.Names
            if (-not $name) { continue }
            try {
                $ins = docker inspect $name 2>$null | ConvertFrom-Json
                $i0 = $ins[0]
                $mounts = @($i0.Mounts | ForEach-Object { "$($_.Source) -> $($_.Destination)" } | Select-Object -First 8)
                $inspectBrief += [ordered]@{
                    name = $name
                    image = $i0.Config.Image
                    status = $i0.State.Status
                    mounts = $mounts
                    network_mode = $i0.HostConfig.NetworkMode
                }
            } catch { }
        }
        $modules.docker_deep = [ordered]@{
            ok = $true
            containers_n = $ps.Count
            networks = $networks
            inspect_brief = $inspectBrief
            dive_available = (Test-Path (Join-Path $senseRoot "bin\dive.exe"))
            note = "topology/mounts; dive for image layers on demand"
        }
    } catch {
        $modules.docker_deep = [ordered]@{ ok = $false; error = "$_" }
    }
}

# --- 5 process + network (Windows) ---
try {
    $topCpu = Get-Process | Sort-Object CPU -Descending | Select-Object -First 12 Name, Id, CPU, WorkingSet64
    $listen = @()
    try {
        $listen = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 40 LocalAddress, LocalPort, OwningProcess |
            ForEach-Object {
                $p = Get-Process -Id $_.OwningProcess -EA SilentlyContinue
                [ordered]@{
                    addr = $_.LocalAddress
                    port = $_.LocalPort
                    pid = $_.OwningProcess
                    proc = if ($p) { $p.ProcessName } else { "?" }
                }
            }
    } catch { }
    $modules.runtime = [ordered]@{
        ok = $true
        top_cpu = @($topCpu | ForEach-Object {
            [ordered]@{ name = $_.Name; id = $_.Id; cpu = $_.CPU; ws_mb = [math]::Round($_.WorkingSet64/1MB,1) }
        })
        listen_ports = $listen
        note = "open files(lsof)/strace linux-centric; Windows NetTCP + process here"
    }
} catch {
    $modules.runtime = [ordered]@{ ok = $false; error = "$_" }
}

# --- 6 packages inventory (versions only, NOT CVE) ---
try {
    $pip = @()
    $py = Join-Path $scanRoot "py\.venv\Scripts\python.exe"
    if (Test-Path $py) {
        $pip = @(& $py -m pip list --format=json 2>$null | ConvertFrom-Json | Select-Object -First 80 name, version)
    }
    $modules.packages = [ordered]@{
        ok = $true
        scan_stack_pip_sample = $pip
        note_cn = "仅版本清单；禁止依赖漏洞/CVE 当目标"
    }
} catch {
    $modules.packages = [ordered]@{ ok = $false; error = "$_" }
}

# --- 7 AST sample (ast-grep / tree-sitter) ---
try {
    $sg = Join-Path $scanRoot "bin\ast-grep.exe"
    $pyRoot = $Roots | Where-Object { Test-Path $_ } | Select-Object -First 1
    $sgOut = $null
    if ((Test-Path $sg) -and $pyRoot) {
        $sgOut = @((& $sg run -p "def `$FUNC($$$):" -l python $pyRoot 2>$null) | Select-Object -First 25)
    }
    $tsOk = $false
    $pyExe = Join-Path $scanRoot "py\.venv\Scripts\python.exe"
    if (Test-Path $pyExe) {
        $tsOk = (& $pyExe -c "import tree_sitter_languages; print('1')" 2>$null) -match '1'
    }
    $modules.ast = [ordered]@{
        ok = $true
        ast_grep_sample = $sgOut
        tree_sitter_languages = $tsOk
        note = "structure not security"
    }
} catch {
    $modules.ast = [ordered]@{ ok = $false; error = "$_" }
}

# --- 8 dead code / dep graph pointers (invoke existing) ---
$modules.dep_and_dead = [ordered]@{
    ok = $true
    tools = @{
        pydeps = (Test-Path (Join-Path $scanRoot "py\.venv\Scripts\pydeps.exe"))
        vulture = (Test-Path (Join-Path $scanRoot "py\.venv\Scripts\vulture.exe"))
        knip = (Test-Path (Join-Path $scanRoot "npm\node_modules\.bin\knip.cmd"))
        depcruise = (Test-Path (Join-Path $scanRoot "npm\node_modules\.bin\depcruise.cmd"))
        import_linter = (Test-Path (Join-Path $scanRoot "py\.venv\Scripts\lint-imports.exe"))
        tach = (Test-Path (Join-Path $scanRoot "py\.venv\Scripts\tach.exe"))
    }
    invoke_hint = "scan-stack py/npm tools; not auto-full-repo here (cost)"
}

# --- 9 fulltext index tool presence ---
$modules.fulltext_index = [ordered]@{
    ok = $true
    ugrep_indexer = (Test-Path (Join-Path $scanRoot "bin\ugrep-indexer.exe"))
    rg = (Test-Path (Join-Path $scanRoot "bin\rg.exe"))
    watchexec = (Test-Path (Join-Path $senseRoot "bin\watchexec.exe"))
    embedding_index = "deferred_T2_not_security"
    note_cn = "ugrep-indexer=本机全文索引；embedding 语义库 T2；禁止密钥扫描"
}

# --- 10 evidence freshness map ---
$evKeys = @(
    "full_gap_scan","holographic_gap","weak_strategy_policy_scan","scan_stack",
    "gap_driven_progressor","local_state_sense","grok_session_context","grok_long_workflow"
)
$ev = @()
foreach ($k in $evKeys) {
    $p = Join-Path $runtime "state\$k\latest.json"
    if (-not (Test-Path $p)) { $p = Join-Path $runtime "state\$k\task_queue.json" }
    $age = $null
    if (Test-Path $p) {
        $age = [math]::Round(((Get-Date) - (Get-Item $p).LastWriteTime).TotalMinutes, 1)
    }
    $ev += [ordered]@{ key = $k; path = $p; exists = (Test-Path $p); age_min = $age }
}
$modules.evidence_freshness = [ordered]@{ ok = $true; items = $ev }

# --- 11 tool binary inventory ---
$toolBins = @()
foreach ($pair in @(
    @{ n='scc'; p=(Join-Path $senseRoot 'bin\scc.exe') },
    @{ n='dive'; p=(Join-Path $senseRoot 'bin\dive.exe') },
    @{ n='watchexec'; p=(Join-Path $senseRoot 'bin\watchexec.exe') },
    @{ n='rg'; p=(Join-Path $scanRoot 'bin\rg.exe') },
    @{ n='fd'; p=(Join-Path $scanRoot 'bin\fd.exe') },
    @{ n='ast-grep'; p=(Join-Path $scanRoot 'bin\ast-grep.exe') },
    @{ n='ugrep'; p=(Join-Path $scanRoot 'bin\ugrep.exe') },
    @{ n='opengrep'; p=(Join-Path $scanRoot 'bin\opengrep.exe') },
    @{ n='semgrep'; p=(Join-Path $scanRoot 'py\.venv\Scripts\semgrep.exe') },
    @{ n='conftest'; p=(Join-Path $scanRoot 'bin\conftest.exe') },
    @{ n='gh'; p=(Get-Command gh -EA SilentlyContinue).Source },
    @{ n='git'; p=(Get-Command git -EA SilentlyContinue).Source },
    @{ n='docker'; p=(Get-Command docker -EA SilentlyContinue).Source }
)) {
    $toolBins += [ordered]@{ id = $pair.n; path = $pair.p; on_disk = [bool]($pair.p -and (Test-Path $pair.p)) }
}
$modules.tool_inventory = [ordered]@{
    ok = $true
    usable = @($toolBins | Where-Object { $_.on_disk }).Count
    total = $toolBins.Count
    tools = $toolBins
}

$result = [ordered]@{
    schema_version = "xinao.state_sense_max.v1"
    sentinel       = "SENTINEL:STATE_SENSE_MAX"
    generated_at   = (Get-Date).ToString("o")
    purpose_cn     = "极致本机状态感知（非安全）— 共享 Grok+后台；禁止清单制"
    constitutional_cn = "非新控制面；非 Temporal owner；非密钥/CVE 安全目标"
    deny_list      = $deny
    roots          = $Roots
    modules        = $modules
    errors         = @($errors)
    now_can_do_cn  = @(
        "Invoke-GrokStateSenseMax.ps1",
        "Get-GrokLocalStateSense.ps1",
        "Invoke-GrokGapDrivenProgressor.ps1 -PushQueue",
        "Invoke-GrokScanStack.ps1 -PolicyScan",
        ". E:\XINAO_EXTERNAL_MATURE\state-sense-stack\env.ps1"
    )
    completion_claim_allowed = $false
    shared_capability = $true
}

Write-JsonFile $latestPath $result
$stamp = Join-Path $outDir ("max_{0:yyyyMMdd_HHmmss}.json" -f (Get-Date))
Write-JsonFile $stamp $result

if (-not $Quiet) {
    $u = $modules.tool_inventory.usable
    Write-Host "StateSenseMax tools=$u/$($modules.tool_inventory.total) modules=$($modules.Keys.Count) errors=$($errors.Count)"
    Write-Host "evidence: $latestPath"
}
$result
