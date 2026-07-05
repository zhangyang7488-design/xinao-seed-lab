[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$Python = "",
    [string]$WaveId = "",
    [string]$LaneId = "",
    [ValidateSet("draft", "eval", "contradiction", "audit", "extraction", "citation_verify", "search", "provider_probe")]
    [string]$Mode = "draft",
    [ValidateSet("auto", "qwen", "dp")]
    [string]$Provider = "auto",
    [string]$Objective = "",
    [string]$InputText = "",
    [string]$InputFile = "",
    [switch]$NoWrite
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if (-not $Python) {
    $repoPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $repoPython -PathType Leaf) {
        $Python = $repoPython
    } else {
        $Python = "python"
    }
}

$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$RepoRoot\src;$RepoRoot"
    Push-Location $RepoRoot
    try {
        $argsList = @(
            "-m",
            "xinao_seedlab.cli.__main__",
            "direct-worker-lane",
            "--runtime-root",
            $RuntimeRoot,
            "--repo-root",
            $RepoRoot,
            "--mode",
            $Mode,
            "--provider",
            $Provider
        )
        if (-not [string]::IsNullOrWhiteSpace($WaveId)) {
            $argsList += @("--wave-id", $WaveId)
        }
        if (-not [string]::IsNullOrWhiteSpace($LaneId)) {
            $argsList += @("--lane-id", $LaneId)
        }
        if (-not [string]::IsNullOrWhiteSpace($Objective)) {
            $argsList += @("--objective", $Objective)
        }
        if (-not [string]::IsNullOrWhiteSpace($InputFile)) {
            $argsList += @("--input-file", $InputFile)
        } else {
            $argsList += @("--input-text", $InputText)
        }
        if ($NoWrite) {
            $argsList += @("--no-write")
        }
        & $Python @argsList
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PYTHONPATH = $oldPythonPath
}
