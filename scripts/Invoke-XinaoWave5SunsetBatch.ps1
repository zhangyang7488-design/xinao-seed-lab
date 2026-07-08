# Wave5 batch sunset — stub all large retired handroll modules.
$ErrorActionPreference = "Stop"
$repo = "E:\XINAO_RESEARCH_WORKSPACES\S"
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$code = @'
from pathlib import Path
from services.agent_runtime._sunset_generic import apply_wave5_stubs
rt = Path(r"E:\XINAO_RESEARCH_WORKSPACES\S\services\agent_runtime")
replaced = apply_wave5_stubs(rt, min_kb=25.0)
print("WAVE5_STUB_COUNT", len(replaced))
for name in replaced:
    print("STUBBED", name)
'@

Push-Location $repo
& $py -c $code
Pop-Location