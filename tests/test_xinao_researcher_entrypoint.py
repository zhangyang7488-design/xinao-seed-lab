from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "docker" / "xinao-researcher" / "entrypoint.py"
    spec = importlib.util.spec_from_file_location("xinao_researcher_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate() -> dict[str, object]:
    return {
        "schema_version": "xinao.research_candidate.v1",
        "status": "CANDIDATE_READY",
        "research_question": "arbitrary topic outside seven families",
        "summary": "candidate only",
        "hypotheses": [],
        "methods": [],
        "evidence_needed": [],
        "current_action_projection": {
            "status": "UNSUPPORTED",
            "family": None,
            "reason": "research is retained without coercion",
        },
    }


def test_candidate_accepts_research_only_output_outside_action_domain() -> None:
    module = _module()
    assert module._valid_candidate(_candidate()) is True


def test_candidate_rejects_capability_as_science_claim() -> None:
    module = _module()
    candidate = _candidate()
    candidate["science_restored"] = True
    assert module._valid_candidate(candidate) is False


def test_candidate_rejects_hidden_account_or_settlement_field() -> None:
    module = _module()
    candidate = _candidate()
    candidate["account"] = {"opening_balance": 10000}
    assert module._valid_candidate(candidate) is False
