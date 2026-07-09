#Requires -Version 5.1
<#
.SYNOPSIS
  Run Phase0 external-seam invoke (Temporal hello_activity pattern + markitdown + docker).
.NOT_333_MAINLINE
#>
param(
    [string]$SRepo = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$Mode = "auto",
    [string]$InputPath = ""
)

$seam = Join-Path $SRepo "materials\authority_glue\seams\phase0_external_seam_invoke.py"
if (-not (Test-Path $seam)) { throw "missing seam script: $seam" }

$python = Join-Path $SRepo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Push-Location $SRepo
try {
    & $python -m pip install -q markitdown 2>$null | Out-Null
    $args = @($seam)
    if ($InputPath) { $args += @("--input", $InputPath) }
    switch ($Mode) {
        "local" { $args += "--local" }
        "temporal" { $args += "--temporal" }
        default { }
    }
    & $python @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}