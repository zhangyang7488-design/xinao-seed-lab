from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from scripts.run_foundation_v2_f4_negative_companion import (
    COMPANION_PREFIX,
    build_initial,
    patch_capacity,
    validate_report,
)


def _write(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_case(name: str) -> dict[str, object]:
    return {
        "case": name,
        "checks": {"proof": True},
        "histories": [
            {
                "workflow_id": f"{COMPANION_PREFIX}-{name.lower()}",
                "replay_ok": True,
            }
        ],
    }


def test_patch_capacity_rebinds_observation_and_frontier(tmp_path: Path) -> None:
    observation_path = tmp_path / "capacity.json"
    observation_hash = _write(
        observation_path,
        {
            "host_state": "available",
            "available_slots": 2,
            "queue_depth": 3,
            "verified_canary": True,
        },
    )
    frontier_path = tmp_path / "frontier.json"
    prior_frontier_hash = _write(
        frontier_path,
        {
            "capacity_observation_ref": str(observation_path),
            "capacity_observation_sha256": observation_hash,
        },
    )
    rebound = patch_capacity(
        {
            "frontier_ref": str(frontier_path),
            "frontier_sha256": prior_frontier_hash,
        },
        available_slots=0,
    )
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    frontier = json.loads(frontier_path.read_text(encoding="utf-8"))

    assert observation["available_slots"] == 0
    assert rebound["frontier_sha256"] != prior_frontier_hash
    assert frontier["capacity_observation_sha256"] != observation_hash


def test_build_initial_can_seed_a_real_width_two_resume_state() -> None:
    inputs = {
        "frontier_ref": r"D:\XINAO_RESEARCH_RUNTIME\fixture\frontier.json",
        "frontier_sha256": "a" * 64,
        "roll_forward_manifest_ref": (
            r"D:\XINAO_RESEARCH_RUNTIME\fixture\roll-forward.json"
        ),
        "roll_forward_manifest_sha256": "b" * 64,
    }
    initial = build_initial(
        inputs,
        operation_id="negative-companion-width-two",
        previous_width=2,
    )

    assert set(initial) == {"resume_state"}
    assert initial["resume_state"]["previous_width"] == 2
    assert initial["resume_state"]["operation_id"] == (
        "negative-companion-width-two"
    )


def test_report_contract_requires_three_replayed_zero_model_cases() -> None:
    report = {
        "execution_surface": "TEMPORAL_EPHEMERAL_TEST_SERVER",
        "model_invocations": 0,
        "canonical_v1_live_mutations": 0,
        "cases": [
            _valid_case("BACKPRESSURE"),
            _valid_case("PARTIAL"),
            _valid_case("CANCEL"),
        ],
    }
    validate_report(report)

    report["model_invocations"] = 1
    with pytest.raises(ValueError, match="zero-model"):
        validate_report(report)


def test_runner_has_no_process_or_network_transport_surface() -> None:
    source_path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "run_foundation_v2_f4_negative_companion.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    imported_from_live_helper: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)
            if node.module == "scripts.run_foundation_v2_f4_live_canary":
                imported_from_live_helper.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    assert "subprocess" not in imported_modules
    assert "temporalio.client" in imported_modules
    assert imported_from_live_helper == {
        "RUNTIME",
        "file_sha256",
        "prepare_inputs",
        "write_json",
    }
    assert not {
        "Popen",
        "create_subprocess_exec",
        "process_one_wave",
        "run_canonical_grok_transaction",
    }.intersection(called_names)
