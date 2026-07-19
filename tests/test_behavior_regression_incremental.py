from __future__ import annotations

import json
from pathlib import Path

import yaml
from scripts.select_behavior_regression_incremental import select_incremental


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _manifest(path: Path, prompt_hash: str, cases_hash: str) -> None:
    _write_json(
        path,
        {
            "files": [
                {
                    "path": "AGENTS.md",
                    "role": "working_agreement",
                    "size_bytes": 1,
                    "sha256": "a" * 64,
                },
                {
                    "path": "evals/context_intent_alignment/prompt.txt",
                    "role": "context_eval",
                    "size_bytes": 1,
                    "sha256": prompt_hash,
                },
                {
                    "path": "evals/context_intent_alignment/cases.yaml",
                    "role": "context_eval",
                    "size_bytes": 1,
                    "sha256": cases_hash,
                },
                {
                    "path": "evals/behavior_regression/catalog.json",
                    "role": "catalog",
                    "size_bytes": 1,
                    "sha256": "c" * 64,
                },
            ]
        },
    )


def _case(identifier: str, value: str) -> dict[str, object]:
    return {
        "description": f"case {identifier}",
        "metadata": {"id": identifier, "domain": "continuity", "profiles": ["core"]},
        "vars": {"case_id": identifier, "value": value},
    }


def _result_row(case: dict[str, object], *, success: bool) -> dict[str, object]:
    variables = dict(case["vars"])
    variables["sessionId"] = "dynamic"
    return {
        "id": "row",
        "success": success,
        "vars": variables,
        "testCase": {
            "description": case["description"],
            "metadata": case["metadata"],
            "vars": variables,
        },
    }


def test_incremental_reuses_only_identical_terminal_pass(tmp_path: Path) -> None:
    cases = [_case("A", "same"), _case("B", "changed"), _case("C", "failed")]
    cases_path = tmp_path / "cases.yaml"
    cases_path.write_text(yaml.safe_dump(cases), encoding="utf-8")
    current_manifest = tmp_path / "current-manifest.json"
    _manifest(current_manifest, "p" * 64, "new" * 21 + "n")

    prior = tmp_path / "prior"
    prior_manifest = prior / "source-manifest.json"
    _manifest(prior_manifest, "p" * 64, "old" * 21 + "o")
    prior_cases = [_case("A", "same"), _case("B", "old"), _case("C", "failed")]
    result_path = prior / "result.json"
    _write_json(
        result_path,
        {
            "results": {
                "results": [
                    _result_row(prior_cases[0], success=True),
                    _result_row(prior_cases[1], success=True),
                    _result_row(prior_cases[2], success=False),
                ]
            }
        },
    )
    _write_json(
        prior / "summary.json",
        {
            "source_manifest_unchanged": True,
            "source_manifest": str(prior_manifest),
            "infrastructure_error": None,
        },
    )

    receipt_path = tmp_path / "selection.json"
    select_incremental(
        cases_path,
        current_manifest,
        [result_path],
        receipt_path,
        profile="context",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["reused_case_ids"] == ["A"]
    assert receipt["fresh_case_ids"] == ["B", "C"]
    assert receipt["fresh_case_pattern"] == r"^(?:case\ B|case\ C)$"
    assert receipt["fail_error_or_drift_reused"] is False


def test_shared_runtime_drift_reuses_nothing(tmp_path: Path) -> None:
    case = _case("A", "same")
    cases_path = tmp_path / "cases.yaml"
    cases_path.write_text(yaml.safe_dump([case]), encoding="utf-8")
    current_manifest = tmp_path / "current.json"
    _manifest(current_manifest, "n" * 64, "x" * 64)
    prior = tmp_path / "prior"
    prior_manifest = prior / "source-manifest.json"
    _manifest(prior_manifest, "o" * 64, "y" * 64)
    result = prior / "result.json"
    _write_json(result, {"results": {"results": [_result_row(case, success=True)]}})
    _write_json(
        prior / "summary.json",
        {
            "source_manifest_unchanged": True,
            "source_manifest": str(prior_manifest),
            "infrastructure_error": None,
        },
    )

    receipt_path = tmp_path / "selection.json"
    select_incremental(
        cases_path,
        current_manifest,
        [result],
        receipt_path,
        profile="context",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["reused_case_ids"] == []
    assert receipt["fresh_case_ids"] == ["A"]
    assert receipt["run_checks"][0]["reason"] == "shared_runtime_drift"
