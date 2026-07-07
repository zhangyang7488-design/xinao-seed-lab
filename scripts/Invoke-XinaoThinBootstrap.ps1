# XINAO thin bootstrap — minimal cheap self-boot (local sandbox default)
param(
    [string]$InputPath = "C:\Users\xx363\Desktop\新系统\thin_bootstrap_input.md",
    [switch]$PreferE2b
)

$ErrorActionPreference = "Stop"
$Repo = "E:\XINAO_RESEARCH_WORKSPACES\S"
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "venv python missing: $Py" }
if (-not (Test-Path $InputPath)) { throw "input missing: $InputPath" }

$args = @("-m", "services.agent_runtime.thin_bootstrap_runner", "--input", $InputPath)
if ($PreferE2b) { $args += "--prefer-e2b" }

Push-Location $Repo
try {
    & $Py @args
    if ($LASTEXITCODE -ne 0) { throw "thin bootstrap failed exit=$LASTEXITCODE" }
    Write-Host "OK thin bootstrap — check D:\XINAO_RESEARCH_RUNTIME\bootstrap\acceptance_pending.json"
}
finally {
    Pop-Location
}