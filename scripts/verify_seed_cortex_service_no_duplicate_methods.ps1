param(
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = "python"
}

$servicePath = Join-Path $RepoRoot "src\xinao_seedlab\application\seed_cortex.py"
Assert-True (Test-Path -LiteralPath $servicePath -PathType Leaf) "Missing SeedCortexService source: $servicePath"

$code = @'
import ast
import json
import sys
from pathlib import Path

service_path = Path(sys.argv[1])
tree = ast.parse(service_path.read_text(encoding="utf-8"))
service = next(
    (
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SeedCortexService"
    ),
    None,
)
if service is None:
    raise SystemExit("SeedCortexService class missing")

method_lines = {}
for node in service.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        method_lines.setdefault(node.name, []).append(node.lineno)

duplicates = {
    name: lines
    for name, lines in method_lines.items()
    if len(lines) > 1
}
if duplicates:
    print(json.dumps({"duplicates": duplicates}, ensure_ascii=False, indent=2))
    raise SystemExit(1)

trigger_lines = method_lines.get("default_main_loop_trigger_candidate", [])
if len(trigger_lines) != 1:
    raise SystemExit(
        f"default_main_loop_trigger_candidate definition count must be 1, got {len(trigger_lines)}"
    )

print(
    json.dumps(
        {
            "schema_version": "xinao.seed_cortex_service_duplicate_method_detector.v1",
            "status": "seed_cortex_service_no_duplicate_methods",
            "class_name": "SeedCortexService",
            "method_count": len(method_lines),
            "default_main_loop_trigger_candidate_line": trigger_lines[0],
            "default_main_loop_trigger_candidate_definition_cn": (
                "现在默认主循环触发走唯一的 SeedCortexService.default_main_loop_trigger_candidate "
                "定义；该定义调用 services.agent_runtime.default_main_loop_trigger_candidate.build，"
                "无 provider worker pool 真相链时保持候选边界；同 wave ledger+唯一AAQ+Qwen/DP "
                "真相链通过时才允许 task-scoped runtime_enforced。"
            ),
        },
        ensure_ascii=False,
        indent=2,
    )
)
'@

$output = & $python -c $code $servicePath
$exitCode = $LASTEXITCODE
$output
Assert-True ($exitCode -eq 0) "SeedCortexService duplicate method detector failed."
Write-Output "SENTINEL:XINAO_SEED_CORTEX_SERVICE_NO_DUPLICATE_METHODS"
