import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = REPO_ROOT / "src" / "xinao_seedlab" / "application" / "seed_cortex.py"


def test_seed_cortex_service_has_no_duplicate_method_definitions() -> None:
    tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
    service = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SeedCortexService"
    )
    method_lines: dict[str, list[int]] = {}
    for node in service.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method_lines.setdefault(node.name, []).append(node.lineno)

    duplicates = {name: lines for name, lines in method_lines.items() if len(lines) > 1}
    assert duplicates == {}
    assert len(method_lines["default_main_loop_trigger_candidate"]) == 1
