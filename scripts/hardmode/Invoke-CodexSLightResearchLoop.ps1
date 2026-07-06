[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$Python = "",
    [ValidateSet("local_only", "external_light", "architecture_audit")]
    [string]$Mode = "local_only",
    [string]$WaveId = "",
    [string]$Objective = "",
    [string]$LocalQuery = "",
    [string[]]$LocalRoot = @(),
    [string[]]$SourceUrl = @(),
    [string[]]$SourcePackage = @(),
    [string]$ExternalNote = "",
    [int]$MaxResults = 12,
    [ValidateSet("auto", "local_only", "cloud_allowed", "skip")]
    [string]$WorkerPolicy = "auto",
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
            "light-research-loop",
            "--runtime-root",
            $RuntimeRoot,
            "--repo-root",
            $RepoRoot,
            "--mode",
            $Mode,
            "--worker-policy",
            $WorkerPolicy,
            "--max-results",
            [string]$MaxResults
        )
        if (-not [string]::IsNullOrWhiteSpace($WaveId)) {
            $argsList += @("--wave-id", $WaveId)
        }
        if (-not [string]::IsNullOrWhiteSpace($Objective)) {
            $argsList += @("--objective", $Objective)
        }
        if (-not [string]::IsNullOrWhiteSpace($LocalQuery)) {
            $argsList += @("--local-query", $LocalQuery)
        }
        foreach ($item in $LocalRoot) {
            if (-not [string]::IsNullOrWhiteSpace($item)) {
                $argsList += @("--local-root", $item)
            }
        }
        foreach ($item in $SourceUrl) {
            if (-not [string]::IsNullOrWhiteSpace($item)) {
                $argsList += @("--source-url", $item)
            }
        }
        foreach ($item in $SourcePackage) {
            if (-not [string]::IsNullOrWhiteSpace($item)) {
                $argsList += @("--source-package", $item)
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($ExternalNote)) {
            $argsList += @("--external-note", $ExternalNote)
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
