#Requires -Version 5.1
<#
.SYNOPSIS
  Run integrated LangGraphPlugin bus invoke (Temporal official integration + markitdown + docker).
.NOT_333_MAINLINE
#>
param(
    [string]$SRepo = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$Mode = "temporal",
    [string]$InputPath = ""
)

$seamDir = Join-Path $SRepo "materials\authority_glue\seams"
if (-not (Test-Path (Join-Path $seamDir "integrated_langgraph_plugin_invoke.py"))) {
    throw "missing integrated seam module under: $seamDir"
}

$python = Join-Path $SRepo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$modeArgs = @()
if ($InputPath) { $modeArgs += @("--input", $InputPath) }
switch ($Mode) {
    "local" { $modeArgs += "--local" }
    "temporal" { $modeArgs += "--temporal" }
    default { $modeArgs += "--temporal" }
}

Push-Location $seamDir
try {
    & $python -m pip install -q markitdown 2>$null | Out-Null
    & $python -m integrated_langgraph_plugin_invoke @modeArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}