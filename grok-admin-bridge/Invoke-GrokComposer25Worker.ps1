#Requires -Version 5.1
<#
.SYNOPSIS
  Headless Grok Composer 2.5 worker (grok-composer-2.5-fast).
.DESCRIPTION
  Thin entry for Grok 4.5 main session: not a 4.5 Task subagent;
  runs CLI -m grok-composer-2.5-fast to burn SuperGrok Build quota.
.EXAMPLE
  .\Invoke-GrokComposer25Worker.ps1 -Prompt "Reply COMPOSER25_OK" -MaxTurns 1
  .\Invoke-GrokComposer25Worker.ps1 -PromptFile .\task.md -Cwd E:\repo -Background
#>
param(
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "grok-composer-2.5-fast",
    [int]$MaxTurns = 40,
    [ValidateSet("plain", "json", "streaming-json")]
    [string]$OutputFormat = "plain",
    [string]$GrokHome = "C:\Users\xx363\.grok-4.5-lane",
    [string]$GrokExe = "",
    [string]$EvidenceDir = "D:\XINAO_RESEARCH_RUNTIME\state\composer25_worker",
    [switch]$Background,
    [switch]$NoAlwaysApprove,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

if (-not $GrokExe) {
    $cand = @(
        (Get-Command grok.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        "C:\Users\xx363\.grok\bin\grok.exe",
        "C:\Users\xx363\.grok-4.5-lane\bin\grok.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $cand) { throw "GROK_CLI_NOT_FOUND: install Grok Build CLI (https://x.ai/cli)" }
    $GrokExe = $cand
}

if ($PromptFile) {
    if (-not (Test-Path -LiteralPath $PromptFile)) { throw "PromptFile missing: $PromptFile" }
    $Prompt = Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8
}
if ([string]::IsNullOrWhiteSpace($Prompt)) {
    throw "Prompt or PromptFile required"
}

if (-not $Cwd) { $Cwd = (Get-Location).Path }
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$runId = "c25_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$outLog = Join-Path $EvidenceDir ($runId + ".out.log")
$errLog = Join-Path $EvidenceDir ($runId + ".err.log")
$metaPath = Join-Path $EvidenceDir ($runId + ".json")
$latest = Join-Path $EvidenceDir "latest.json"

# Prefer --prompt-file so long prompts are not split by Start-Process on Windows.
$promptForFile = Join-Path $EvidenceDir ($runId + ".prompt.md")
if ($PromptFile -and (Test-Path -LiteralPath $PromptFile)) {
    Copy-Item -LiteralPath $PromptFile -Destination $promptForFile -Force
} else {
    $Prompt | Set-Content -LiteralPath $promptForFile -Encoding UTF8
}

$argsList = [System.Collections.Generic.List[string]]::new()
[void]$argsList.Add("-m"); [void]$argsList.Add($Model)
[void]$argsList.Add("--cwd"); [void]$argsList.Add($Cwd)
[void]$argsList.Add("--max-turns"); [void]$argsList.Add("$MaxTurns")
[void]$argsList.Add("--output-format"); [void]$argsList.Add($OutputFormat)
[void]$argsList.Add("--prompt-file"); [void]$argsList.Add($promptForFile)
if (-not $NoAlwaysApprove) {
    [void]$argsList.Add("--always-approve")
}

$env:GROK_HOME = $GrokHome

$meta = [ordered]@{
    schema_version = "xinao.grok_composer25_worker.v1"
    sentinel = "SENTINEL:GROK_COMPOSER25_WORKER"
    generated_at = (Get-Date).ToString("o")
    run_id = $runId
    model = $Model
    grok_exe = $GrokExe
    grok_home = $GrokHome
    cwd = $Cwd
    max_turns = $MaxTurns
    background = [bool]$Background
    out_log = $outLog
    err_log = $errLog
    create_no_window = $true
    completion_claim_allowed = $false
    note_cn = "Composer 2.5 headless worker; SuperGrok Build quota; CREATE_NO_WINDOW; not 4.5 Task subagent"
    hot_path_cn = "Codex->Grok headless worker (not visible TUI inject; not Docker desktop .lnk)"
}

# Mature Windows spawn: UseShellExecute=false + CreateNoWindow (not WindowStyle Hidden flash).
$argString = ($argsList | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $GrokExe
$psi.Arguments = $argString
$psi.WorkingDirectory = $Cwd
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true
if ($GrokHome) {
    $psi.EnvironmentVariables["GROK_HOME"] = $GrokHome
}

$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi
[void]$proc.Start()

if ($Background) {
    # Drain stdio to files on a background runspace so parent can return without -WindowStyle Hidden flash.
    $drain = {
        param($Process, $OutLog, $ErrLog, $MetaPath, $LatestPath, $MetaObj)
        try {
            $stdout = $Process.StandardOutput.ReadToEnd()
            $stderr = $Process.StandardError.ReadToEnd()
            $Process.WaitForExit()
            $utf8 = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText($OutLog, $stdout, $utf8)
            if ($stderr) { [System.IO.File]::WriteAllText($ErrLog, $stderr, $utf8) }
            $MetaObj.status = if ($Process.ExitCode -eq 0) { "ok_background" } else { "failed_background" }
            $MetaObj.exit_code = $Process.ExitCode
            $MetaObj.finished_at = (Get-Date).ToString("o")
            $MetaObj.stdout_excerpt = if ($stdout.Length -gt 4000) { $stdout.Substring(0, 4000) } else { $stdout }
            $json = ($MetaObj | ConvertTo-Json -Depth 6)
            [System.IO.File]::WriteAllText($MetaPath, $json, $utf8)
            Copy-Item -LiteralPath $MetaPath -Destination $LatestPath -Force
        } catch {
            try {
                $MetaObj.status = "drain_error"
                $MetaObj.error = "$_"
                $MetaObj | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $MetaPath -Encoding UTF8
            } catch { }
        }
    }
    $rs = [runspacefactory]::CreateRunspace()
    $rs.Open()
    $ps = [powershell]::Create()
    $ps.Runspace = $rs
    [void]$ps.AddScript($drain).AddArgument($proc).AddArgument($outLog).AddArgument($errLog).AddArgument($metaPath).AddArgument($latest).AddArgument($meta)
    $meta.status = "started_background"
    $meta.pid = $proc.Id
    $meta.drain = "runspace_create_no_window"
    $meta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding UTF8
    Copy-Item $metaPath $latest -Force
    [void]$ps.BeginInvoke()
    if (-not $Quiet) {
        @{ ok = $true; run_id = $runId; pid = $proc.Id; out_log = $outLog; latest = $latest; create_no_window = $true } | ConvertTo-Json
    }
    exit 0
}

$stdout = $proc.StandardOutput.ReadToEnd()
$stderr = $proc.StandardError.ReadToEnd()
$proc.WaitForExit()
$stdout | Set-Content -LiteralPath $outLog -Encoding UTF8
if ($stderr) { $stderr | Set-Content -LiteralPath $errLog -Encoding UTF8 }

$meta.status = if ($proc.ExitCode -eq 0) { "ok" } else { "failed" }
$meta.exit_code = $proc.ExitCode
$meta.pid = $proc.Id
$meta.stdout_excerpt = if ($stdout.Length -gt 4000) { $stdout.Substring(0, 4000) } else { $stdout }
$meta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding UTF8
Copy-Item $metaPath $latest -Force

if (-not $Quiet) {
    Write-Output $stdout
    if ($stderr) { Write-Error $stderr }
}
exit $proc.ExitCode
