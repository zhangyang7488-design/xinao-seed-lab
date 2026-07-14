"""Deterministic Promptfoo provider for P9 agent admission regressions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from xinao.policy import evaluate_agent_admission  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def call_api(prompt, options, context):
    del options, context
    case_id = str(prompt).strip()
    path = (FIXTURES / f"{case_id}.json").resolve()
    if path.parent != FIXTURES.resolve() or not path.is_file():
        output = {"admitted": False, "reasons": ["unknown_case"]}
    else:
        request = json.loads(path.read_text(encoding="utf-8"))
        output = evaluate_agent_admission(request)
    return {"output": json.dumps(output, sort_keys=True)}
