"""Deterministic Promptfoo provider for typed handoff fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from xinao.contracts import HandoffMessage  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def call_api(prompt, options, context):
    del options, context
    case_id = str(prompt).strip()
    path = (FIXTURES / f"{case_id}.json").resolve()
    if path.parent != FIXTURES.resolve() or not path.is_file():
        return {"output": json.dumps({"valid": False, "error": "unknown_case"})}
    try:
        message = HandoffMessage.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        output = {"valid": False, "error": "invalid_handoff"}
    else:
        output = {"valid": True, "kind": message.payload.kind, "schema": message.schema_version}
    return {"output": json.dumps(output, sort_keys=True)}
