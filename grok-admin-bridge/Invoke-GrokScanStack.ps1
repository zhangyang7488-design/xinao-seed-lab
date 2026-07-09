#Requires -Version 5.1
<#
.SYNOPSIS
  XINAO E: scan-stack 能力面：Status / List / Smoke / Run / PolicyScan。
  策略·结构·合同·发现 — 非安全 CVE/密钥扫描。
  规则已挂：E:\XINAO_EXTERNAL_MATURE\scan-stack\rules\
.EXAMPLE
  .\Invoke-GrokScanStack.ps1 -Status
  .\Invoke-GrokScanStack.ps1 -List
  .\Invoke-GrokScanStack.ps1 -PolicyScan
  .\Invoke-GrokScanStack.ps1 -Run -Tool opengrep -ToolArgs @('--version')
#>
param(
    [switch]$Status,
    [switch]$List,
    [switch]$Smoke,
    [switch]$Run,
    [switch]$PolicyScan,
    [string]$Tool = "",
    [string[]]$ToolArgs = @(),
    [string[]]$Roots = @(),
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$bridge = $PSScriptRoot
$scanRoot = "E:\XINAO_EXTERNAL_MATURE\scan-stack"
$bin = Join-Path $scanRoot "bin"
$py = Join-Path $scanRoot "py\.venv\Scripts"
$npm = Join-Path $scanRoot "npm\node_modules\.bin"
$rulesRoot = Join-Path $scanRoot "rules"
$manifestPath = Join-Path $scanRoot "MANIFEST.json"
$envPs1 = Join-Path $scanRoot "env.ps1"

$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$stateRoot = Join-Path $runtime "state\scan_stack"
$policyStateRoot = Join-Path $runtime "state\weak_strategy_policy_scan"
$latestPath = Join-Path $stateRoot "latest.json"
$policyLatestPath = Join-Path $policyStateRoot "latest.json"
New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
New-Item -ItemType Directory -Force -Path $policyStateRoot | Out-Null

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 20), $utf8)
}

function Enable-ScanStackPath {
    $env:XINAO_SCAN_STACK = $scanRoot
    $env:Path = (@($bin, $py, $npm) + @($env:Path)) -join ";"
}

$engines = @(
    @{ id = "opengrep";          layer = "T0_rule";      role = "strategy_rules_main";     path = (Join-Path $bin "opengrep.exe"); kind = "exe" }
    @{ id = "opengrep-core";     layer = "T0_rule";      role = "strategy_rules_engine";   path = (Join-Path $bin "opengrep-core.exe"); kind = "exe" }
    @{ id = "semgrep";           layer = "T0_rule";      role = "strategy_rules_alt";      path = (Join-Path $py "semgrep.exe"); kind = "exe" }
    @{ id = "ast-grep";          layer = "T0_struct";    role = "structural_search";       path = (Join-Path $bin "ast-grep.exe"); kind = "exe"; alias = "sg" }
    @{ id = "conftest";          layer = "T0_policy";    role = "config_policy";           path = (Join-Path $bin "conftest.exe"); kind = "exe" }
    @{ id = "opa";               layer = "T0_policy";    role = "rego_eval";               path = (Join-Path $bin "opa.exe"); kind = "exe" }
    @{ id = "regal";             layer = "T0_policy";    role = "rego_lint";               path = (Join-Path $bin "regal.exe"); kind = "exe" }
    @{ id = "rg";                layer = "T0_discovery"; role = "fulltext_candidate";      path = (Join-Path $bin "rg.exe"); kind = "exe"; not_brain = $true }
    @{ id = "ugrep";             layer = "T0_discovery"; role = "fulltext_indexable";      path = (Join-Path $bin "ugrep.exe"); kind = "exe"; not_brain = $true }
    @{ id = "ugrep-indexer";     layer = "T0_discovery"; role = "local_index";             path = (Join-Path $bin "ugrep-indexer.exe"); kind = "exe"; not_brain = $true }
    @{ id = "fd";                layer = "T0_discovery"; role = "filename_find";           path = (Join-Path $bin "fd.exe"); kind = "exe"; not_brain = $true }
    @{ id = "Everything";        layer = "T0_discovery"; role = "windows_filename_index";  path = (Join-Path $bin "Everything\Everything.exe"); kind = "exe"; not_brain = $true }
    @{ id = "import-linter";     layer = "T1_arch";      role = "python_layer_boundary";   path = (Join-Path $py "lint-imports.exe"); kind = "exe" }
    @{ id = "tach";              layer = "T1_arch";      role = "python_module_boundary";  path = (Join-Path $py "tach.exe"); kind = "exe" }
    @{ id = "pydeps";            layer = "T1_arch";      role = "python_dep_graph";        path = (Join-Path $py "pydeps.exe"); kind = "exe" }
    @{ id = "depcruise";         layer = "T1_arch";      role = "js_dep_rules";            path = (Join-Path $npm "depcruise.cmd"); kind = "cmd" }
    @{ id = "vulture";           layer = "T1_dead";      role = "python_dead_code";        path = (Join-Path $py "vulture.exe"); kind = "exe" }
    @{ id = "knip";              layer = "T1_dead";      role = "js_unused_exports";       path = (Join-Path $npm "knip.cmd"); kind = "cmd" }
    @{ id = "check-jsonschema";  layer = "T1_contract";  role = "json_schema_validate";    path = (Join-Path $py "check-jsonschema.exe"); kind = "exe" }
    @{ id = "spectral";          layer = "T1_contract";  role = "openapi_lint";            path = (Join-Path $npm "spectral.cmd"); kind = "cmd" }
    @{ id = "ruff";              layer = "T1_hygiene";   role = "python_lint";             path = (Join-Path $py "ruff.exe"); kind = "exe" }
    @{ id = "hadolint";          layer = "T1_hygiene";   role = "dockerfile_lint";         path = (Join-Path $bin "hadolint.exe"); kind = "exe" }
    @{ id = "shellcheck";        layer = "T1_hygiene";   role = "shell_lint";              path = (Join-Path $bin "shellcheck.exe"); kind = "exe" }
    @{ id = "pre-commit";        layer = "T1_orch";      role = "multi_engine_hook";       path = (Join-Path $py "pre-commit.exe"); kind = "exe" }
    @{ id = "repomix";           layer = "T1_pack";      role = "repo_pack_for_agent";     path = (Join-Path $npm "repomix.cmd"); kind = "cmd" }
    @{ id = "gitingest";         layer = "T1_pack";      role = "repo_ingest_for_agent";   path = (Join-Path $py "python.exe"); kind = "python_mod"; module = "gitingest" }
)

$deferred = @(
    @{ id = "zoekt"; reason = "windows_native_build_fail_unix_Umask"; fallback = "ugrep-indexer+rg+Everything" }
    @{ id = "comby"; reason = "linux_only_binary_archived"; fallback = "ast-grep" }
    @{ id = "openrewrite"; reason = "no_windows_standalone_cli"; fallback = "ast-grep+semgrep rules" }
    @{ id = "livegrep"; reason = "service_heavy_deferred"; fallback = "ugrep+rg" }
)

function Get-DefaultPolicyRoots {
    $cands = @(
        "E:\XINAO_RESEARCH_WORKSPACES\S\services\agent_runtime",
        "E:\XINAO_RESEARCH_WORKSPACES\S\materials",
        "E:\XINAO_RESEARCH_WORKSPACES\S\contracts",
        "E:\XINAO_RESEARCH_WORKSPACES\S\scripts",
        "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace-grok-4.5-island\grok-admin-bridge",
        "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge",
        "D:\XINAO_RESEARCH_RUNTIME\specs",
        "C:\Users\xx363\Desktop\工具胶水宪法"
    )
    return @($cands | Where-Object { Test-Path -LiteralPath $_ })
}

function Get-EngineInventory {
    $rows = @()
    foreach ($e in $engines) {
        $ok = Test-Path -LiteralPath $e.path
        $rows += [ordered]@{
            id       = $e.id
            layer    = $e.layer
            role     = $e.role
            path     = $e.path
            kind     = $e.kind
            on_disk  = $ok
            usable   = $ok
            not_brain = [bool]$e.not_brain
            alias    = $e.alias
            claim_state = if ($ok) { "registered_and_hooked" } else { "missing" }
            now_can_invoke = if ($ok) { "Invoke-GrokScanStack.ps1 -Run -Tool $($e.id)" } else { $null }
        }
    }
    return $rows
}

function Invoke-Engine([string]$Id, [string[]]$Args) {
    Enable-ScanStackPath
    $e = $engines | Where-Object { $_.id -eq $Id -or $_.alias -eq $Id } | Select-Object -First 1
    if (-not $e) { throw "Unknown tool: $Id. Use -List." }
    if (-not (Test-Path -LiteralPath $e.path)) { throw "Tool on_disk=false: $Id path=$($e.path)" }
    if ($e.kind -eq "python_mod") {
        & $e.path -m $e.module @Args
        return $LASTEXITCODE
    }
    & $e.path @Args
    return $LASTEXITCODE
}

function Invoke-SmokeQuick {
    Enable-ScanStackPath
    $results = @()
    $probes = @{
        "opengrep" = @("--version"); "semgrep" = @("--version"); "ast-grep" = @("--version")
        "conftest" = @("--version"); "opa" = @("version"); "rg" = @("--version")
        "ugrep" = @("--version"); "fd" = @("--version"); "ruff" = @("--version")
        "vulture" = @("--version"); "hadolint" = @("--version"); "knip" = @("--version")
        "depcruise" = @("--version"); "spectral" = @("--version"); "repomix" = @("--version")
        "check-jsonschema" = @("--version"); "regal" = @("version"); "shellcheck" = @("--version")
        "tach" = @("--version"); "import-linter" = @("--version")
    }
    foreach ($k in $probes.Keys) {
        $e = $engines | Where-Object { $_.id -eq $k } | Select-Object -First 1
        if (-not $e -or -not (Test-Path -LiteralPath $e.path)) {
            $results += [ordered]@{ id = $k; ok = $false; out = "missing" }
            continue
        }
        try {
            $out = & $e.path @($probes[$k]) 2>&1 | Out-String
            $out = $out.Trim()
            if ($out.Length -gt 120) { $out = $out.Substring(0, 120) + "..." }
            $results += [ordered]@{ id = $k; ok = $true; out = $out }
        } catch {
            $results += [ordered]@{ id = $k; ok = $false; out = "$_" }
        }
    }
    return $results
}

function Invoke-PolicyScanCore {
    param([string[]]$ScanRoots)

    Enable-ScanStackPath
    $opengrepRules = Join-Path $rulesRoot "opengrep\xinao-weak-strategy.yaml"
    $conftestDir = Join-Path $rulesRoot "conftest"
    $astgrepDir = Join-Path $rulesRoot "ast-grep"
    $rgPatFile = Join-Path $rulesRoot "rg-patterns\weak_strategy_patterns.txt"
    $rawDir = Join-Path $policyStateRoot "raw"
    New-Item -ItemType Directory -Force -Path $rawDir | Out-Null

    $engineRuns = @()
    $findings = @()
    $errors = @()

    $excludeGlobs = @("node_modules", ".venv", "dist", "build", "__pycache__", ".git", "mlruns")

    # --- 1) OpenGrep (primary rule engine) ---
    $ogExe = Join-Path $bin "opengrep.exe"
    $sgExe = Join-Path $py "semgrep.exe"
    $ruleEngine = $null
    if (Test-Path $ogExe) { $ruleEngine = @{ name = "opengrep"; path = $ogExe } }
    elseif (Test-Path $sgExe) { $ruleEngine = @{ name = "semgrep"; path = $sgExe } }

    if ($ruleEngine -and (Test-Path $opengrepRules)) {
        foreach ($root in $ScanRoots) {
            $outFile = Join-Path $rawDir ("{0}_{1}.json" -f $ruleEngine.name, ($root -replace '[\\/:]', '_'))
            try {
                $args = @("scan", "--config", $opengrepRules, "--json", "--quiet", $root)
                # exclude heavy dirs via --exclude if supported; both accept multiple
                foreach ($ex in $excludeGlobs) {
                    $args = @("--exclude", $ex) + $args
                    # OpenGrep may use --exclude differently; also try path filters in rule
                }
                # simpler: put path last
                $args = @("scan", "--config", $opengrepRules, "--json", "--quiet")
                foreach ($ex in $excludeGlobs) { $args += @("--exclude", $ex) }
                $args += $root
                $jsonOut = & $ruleEngine.path @args 2>&1 | Out-String
                [System.IO.File]::WriteAllText($outFile, $jsonOut, $utf8)
                $parsed = $null
                try { $parsed = $jsonOut | ConvertFrom-Json -ErrorAction Stop } catch { $parsed = $null }
                $resultCount = 0
                if ($parsed -and $parsed.results) {
                    $resultCount = @($parsed.results).Count
                    foreach ($r in @($parsed.results | Select-Object -First 200)) {
                        $findings += [ordered]@{
                            engine   = $ruleEngine.name
                            rule_id  = $r.check_id
                            path     = $r.path
                            line     = $r.start.line
                            message  = $r.extra.message
                            severity = $r.extra.severity
                            layer    = "T0_rule"
                        }
                    }
                }
                $engineRuns += [ordered]@{
                    engine = $ruleEngine.name; root = $root; ok = $true
                    findings = $resultCount; raw = $outFile; exit = $LASTEXITCODE
                }
            } catch {
                $errors += "rule_engine $($ruleEngine.name) $root : $_"
                $engineRuns += [ordered]@{ engine = $ruleEngine.name; root = $root; ok = $false; error = "$_" }
            }
        }
    } else {
        $errors += "no opengrep/semgrep or rules missing"
    }

    # --- 2) ast-grep structural ---
    $sgBin = Join-Path $bin "ast-grep.exe"
    if (Test-Path $sgBin) {
        foreach ($root in $ScanRoots) {
            # only python-ish roots worth it
            $pyFiles = Get-ChildItem -LiteralPath $root -Recurse -Filter "*.py" -File -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -notmatch 'node_modules|\\.venv|__pycache__' } |
                Select-Object -First 1
            if (-not $pyFiles) { continue }
            try {
                $outFile = Join-Path $rawDir ("astgrep_{0}.txt" -f ($root -replace '[\\/:]', '_'))
                $txt = & $sgBin scan -r $astgrepDir $root 2>&1 | Out-String
                [System.IO.File]::WriteAllText($outFile, $txt, $utf8)
                $hitLines = @($txt -split "`n" | Where-Object { $_ -match 'time\.sleep|asyncio\.sleep|xinao-' } | Select-Object -First 80)
                foreach ($hl in $hitLines) {
                    if ([string]::IsNullOrWhiteSpace($hl)) { continue }
                    $findings += [ordered]@{
                        engine = "ast-grep"; rule_id = "ast-grep.scan"; path = $root
                        line = $null; message = $hl.Trim(); severity = "WARNING"; layer = "T0_struct"
                    }
                }
                $engineRuns += [ordered]@{
                    engine = "ast-grep"; root = $root; ok = $true
                    findings = $hitLines.Count; raw = $outFile
                }
            } catch {
                $errors += "ast-grep $root : $_"
            }
        }
    }

    # --- 3) Conftest on key config files ---
    $ctExe = Join-Path $bin "conftest.exe"
    if (Test-Path $ctExe) {
        $configFiles = @()
        foreach ($root in $ScanRoots) {
            $configFiles += Get-ChildItem -LiteralPath $root -Recurse -Include `
                "thin_glue_litellm_config.yaml","docker-compose*.yml","docker-compose*.yaml","*.v1.json" `
                -File -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -notmatch 'node_modules|\\.venv' } |
                Select-Object -First 40
        }
        $configFiles = @($configFiles | Select-Object -Unique -First 60)
        foreach ($cf in $configFiles) {
            try {
                $outFile = Join-Path $rawDir ("conftest_{0}.txt" -f ($cf.Name -replace '[^\w\.-]', '_'))
                $txt = & $ctExe test -p $conftestDir $cf.FullName 2>&1 | Out-String
                [System.IO.File]::WriteAllText($outFile, $txt, $utf8)
                $failed = $txt -match 'FAIL|deny'
                if ($failed) {
                    $findings += [ordered]@{
                        engine = "conftest"; rule_id = "xinao.conftest"
                        path = $cf.FullName; line = $null
                        message = ($txt.Trim() -replace '\s+', ' ').Substring(0, [Math]::Min(400, ($txt.Trim()).Length))
                        severity = "ERROR"; layer = "T0_policy"
                    }
                }
                $engineRuns += [ordered]@{
                    engine = "conftest"; file = $cf.FullName; ok = -not $failed; raw = $outFile
                }
            } catch {
                $errors += "conftest $($cf.FullName): $_"
            }
        }
    }

    # --- 4) rg discovery (candidates, not brain) ---
    $rgExe = Join-Path $bin "rg.exe"
    if ((Test-Path $rgExe) -and (Test-Path $rgPatFile)) {
        $patterns = Get-Content $rgPatFile -Encoding UTF8 | Where-Object { $_ -and $_ -notmatch '^\s*#' }
        foreach ($root in $ScanRoots) {
            foreach ($pat in $patterns) {
                try {
                    $hits = & $rgExe -n --max-count 15 -g '!node_modules' -g '!.venv' -g '!__pycache__' -g '!*.pyc' -e $pat $root 2>$null
                    $hitArr = @($hits | Select-Object -First 15)
                    foreach ($h in $hitArr) {
                        $hs = [string]$h
                        $fPath = $root
                        $fLine = $null
                        if ($hs -match '^(.*?):(\d+):') {
                            $fPath = $Matches[1]
                            $fLine = [int]$Matches[2]
                        }
                        $findings += [ordered]@{
                            engine = "rg"; rule_id = "rg:$pat"; path = $fPath
                            line = $fLine; message = $hs; severity = "INFO"
                            layer = "T0_discovery"; not_brain = $true
                        }
                    }
                    if ($hitArr.Count -gt 0) {
                        $engineRuns += [ordered]@{
                            engine = "rg"; root = $root; pattern = $pat; hits = $hitArr.Count; ok = $true
                        }
                    }
                } catch { }
            }
        }
    }

    # de-dupe by engine+rule+message prefix
    $dedup = @{}
    $unique = @()
    foreach ($f in $findings) {
        $msg = [string]$f.message
        $key = "{0}|{1}|{2}|{3}" -f $f.engine, $f.rule_id, $f.path, $f.line
        if ($dedup.ContainsKey($key)) { continue }
        $dedup[$key] = $true
        $unique += $f
    }

    $byEngine = @{}
    foreach ($f in $unique) {
        if (-not $byEngine.ContainsKey($f.engine)) { $byEngine[$f.engine] = 0 }
        $byEngine[$f.engine]++
    }

    return [ordered]@{
        schema_version = "xinao.weak_strategy_policy_scan.v1"
        sentinel       = "SENTINEL:WEAK_STRATEGY_POLICY_SCAN"
        generated_at   = (Get-Date).ToString("o")
        purpose_cn     = "规则引擎弱智策略扫 — 已挂 opengrep/ast-grep/conftest/rg；非安全面"
        rules_root     = $rulesRoot
        rules_mounted  = [ordered]@{
            opengrep = $opengrepRules
            conftest = $conftestDir
            ast_grep = $astgrepDir
            rg_patterns = $rgPatFile
        }
        roots          = $ScanRoots
        exclude_security = @("Trivy", "Grype", "OSV", "Gitleaks", "TruffleHog")
        counts         = [ordered]@{
            findings_total = $unique.Count
            engine_runs    = $engineRuns.Count
            errors         = $errors.Count
            roots          = $ScanRoots.Count
        }
        by_engine      = $byEngine
        engine_runs    = $engineRuns
        findings       = $unique
        errors         = $errors
        completion_claim_allowed = $false
        now_can_do_cn  = @(
            "Invoke-GrokScanStack.ps1 -PolicyScan"
            "证据: $policyLatestPath"
            "规则: $rulesRoot"
        )
    }
}

# ---------- dispatch ----------
if (-not ($Status -or $List -or $Smoke -or $Run -or $PolicyScan)) { $Status = $true }

$inv = Get-EngineInventory
$usable = @($inv | Where-Object { $_.usable })
$missing = @($inv | Where-Object { -not $_.usable })
$byLayer = @{}
foreach ($u in $usable) {
    if (-not $byLayer.ContainsKey($u.layer)) { $byLayer[$u.layer] = 0 }
    $byLayer[$u.layer]++
}

if ($List -and -not $Quiet) {
    Write-Host "=== scan-stack usable engines ($($usable.Count)/$($inv.Count)) ==="
    $usable | ForEach-Object {
        $nb = if ($_.not_brain) { " [discovery-only]" } else { "" }
        Write-Host ("  {0,-18} {1,-14} {2}{3}" -f $_.id, $_.layer, $_.role, $nb)
    }
    Write-Host "=== rules mounted ==="
    Write-Host "  $rulesRoot"
    Get-ChildItem $rulesRoot -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host ("  - {0}" -f $_.FullName.Substring($rulesRoot.Length + 1))
    }
    Write-Host "=== deferred (not native Win) ==="
    $deferred | ForEach-Object { Write-Host ("  {0,-18} {1}" -f $_.id, $_.reason) }
}

if ($Run) {
    if ([string]::IsNullOrWhiteSpace($Tool)) { throw "-Run requires -Tool <id>" }
    $code = Invoke-Engine -Id $Tool -Args $ToolArgs
    if (-not $Quiet) { Write-Host "exit=$code tool=$Tool" }
    exit $code
}

$policyResult = $null
if ($PolicyScan) {
    $scanRoots = if ($Roots.Count -gt 0) { $Roots } else { Get-DefaultPolicyRoots }
    if (-not $Quiet) {
        Write-Host "PolicyScan roots ($($scanRoots.Count)):"
        $scanRoots | ForEach-Object { Write-Host "  $_" }
    }
    $policyResult = Invoke-PolicyScanCore -ScanRoots $scanRoots
    Write-JsonFile $policyLatestPath $policyResult
    $pstamp = Join-Path $policyStateRoot ("policy_{0:yyyyMMdd_HHmmss}.json" -f (Get-Date))
    Write-JsonFile $pstamp $policyResult
    # also mirror summary into weak_strategy_scan for continuity
    $wsDir = Join-Path $runtime "state\weak_strategy_scan"
    New-Item -ItemType Directory -Force -Path $wsDir | Out-Null
    $wsMirror = [ordered]@{
        schema_version = "xinao.weak_strategy_scan.v1"
        sentinel       = "SENTINEL:WEAK_STRATEGY_SCAN"
        generated_at   = $policyResult.generated_at
        source         = "Invoke-GrokScanStack -PolicyScan"
        completion_claim_allowed = $false
        policy_scan_ref = $policyLatestPath
        gap_count      = $policyResult.counts.findings_total
        counts         = $policyResult.counts
        by_engine      = $policyResult.by_engine
        top_findings   = @($policyResult.findings | Select-Object -First 40)
        roots          = $policyResult.roots
        rules_mounted  = $policyResult.rules_mounted
    }
    Write-JsonFile (Join-Path $wsDir "latest.json") $wsMirror
    if (-not $Quiet) {
        Write-Host "PolicyScan findings=$($policyResult.counts.findings_total) engines=$($policyResult.by_engine | ConvertTo-Json -Compress)"
        Write-Host "evidence: $policyLatestPath"
    }
}

$smokeRows = $null
if ($Smoke) { $smokeRows = Invoke-SmokeQuick }

$payload = [ordered]@{
    schema_version = "xinao.grok_scan_stack_status.v1"
    sentinel       = "SENTINEL:GROK_SCAN_STACK"
    generated_at   = (Get-Date).ToString("o")
    root           = $scanRoot
    root_ok        = (Test-Path -LiteralPath $scanRoot)
    manifest_ok    = (Test-Path -LiteralPath $manifestPath)
    rules_root     = $rulesRoot
    rules_mounted  = @(
        "rules\opengrep\xinao-weak-strategy.yaml",
        "rules\conftest\xinao_compose.rego",
        "rules\conftest\xinao_policy_json.rego",
        "rules\ast-grep\no-time-sleep-poll.yml",
        "rules\rg-patterns\weak_strategy_patterns.txt"
    )
    env_ps1        = $envPs1
    invoke         = "Invoke-GrokScanStack.ps1"
    purpose_cn     = "策略/结构/合同/发现全局扫 — 非安全；规则已挂 PolicyScan"
    exclude_security = @("Trivy", "Grype", "OSV", "Gitleaks", "TruffleHog")
    counts         = [ordered]@{
        engines_defined   = $inv.Count
        usable            = $usable.Count
        missing           = $missing.Count
        deferred_not_win  = $deferred.Count
        strategy_brain_ok = @($usable | Where-Object { -not $_.not_brain }).Count
        discovery_only    = @($usable | Where-Object { $_.not_brain }).Count
        rules_files       = @(Get-ChildItem $rulesRoot -Recurse -File -EA SilentlyContinue).Count
    }
    by_layer       = $byLayer
    engines        = $inv
    deferred       = $deferred
    smoke          = $smokeRows
    last_policy_scan = if ($policyResult) { $policyLatestPath } else { $null }
    now_can_do_cn  = @(
        "Invoke-GrokScanStack.ps1 -Status | -List | -Smoke"
        "Invoke-GrokScanStack.ps1 -PolicyScan          # 规则引擎一键扫（已挂）"
        "Invoke-GrokScanStack.ps1 -Run -Tool <id>"
        ". E:\XINAO_EXTERNAL_MATURE\scan-stack\env.ps1"
    )
    claim_state    = "registered_and_hooked"
    rules_claim_state = "mounted_default_hotpath"
    completion_claim_allowed = $false
}

Write-JsonFile $latestPath $payload
$stamp = Join-Path $stateRoot ("scan_stack_{0:yyyyMMdd_HHmmss}.json" -f (Get-Date))
Write-JsonFile $stamp $payload

if (-not $Quiet) {
    Write-Host "scan-stack usable=$($usable.Count)/$($inv.Count) rules=$(($payload.counts.rules_files)) deferred=$($deferred.Count)"
    Write-Host "evidence: $latestPath"
    Write-Host "invoke: -PolicyScan | -List | -Run -Tool <id>"
}

if ($PolicyScan) {
    if ($policyResult.errors.Count -gt 0 -and $policyResult.counts.findings_total -eq 0) { exit 3 }
    exit 0
}
if ($Status -or $Smoke -or $List) {
    if ($missing.Count -gt 0) { exit 2 }
    exit 0
}
