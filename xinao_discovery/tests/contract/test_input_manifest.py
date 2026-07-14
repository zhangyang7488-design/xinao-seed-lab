from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "evidence" / "input_manifest.schema.json"
PROBE_PATH = PROJECT_ROOT / "scripts" / "probe" / "capability_probe.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("xinao_capability_probe", PROBE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_manifest() -> dict[str, object]:
    probe = load_probe()
    materials = []
    for index, material in enumerate(probe.MATERIALS, start=1):
        materials.append(
            {
                "material_id": material["material_id"],
                "role": material["role"],
                "path": f"D:/fixture/material-{index}",
                "size_bytes": index,
                "mtime_utc": "2026-07-14T00:00:00.000Z",
                "sha256": material["expected_sha256"],
                "expected_sha256": material["expected_sha256"],
                "exists": True,
                "stable_during_probe": True,
                "expected_sha256_matches": True,
            }
        )
    return {
        "schema_version": "xinao.input_material_manifest.v1",
        "generated_at": "2026-07-14T00:00:00.000Z",
        "correlation_id": "fixture-correlation",
        "parent_operation_id": "fixture-parent",
        "materials": materials,
        "dataset_verification": {
            "human_record_lines": 913,
            "json_record_lines": 913,
            "ok": True,
        },
        "baseline_verification": {
            "data_rows": 433,
            "play_groups": 13,
            "baseline_id_unique": True,
            "ok": True,
        },
        "result_status": "verified",
    }


def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_valid_manifest_matches_repository_contract() -> None:
    errors = list(validator().iter_errors(valid_manifest()))
    assert errors == []


def test_fixed_material_identities_and_hashes_are_unique() -> None:
    probe = load_probe()
    ids = [str(item["material_id"]) for item in probe.MATERIALS]
    assert len(ids) == len(set(ids)) == 4
    assert probe.EXPECTED_DATASET_SHA256 == (
        "57f9fc68f48416fd38610da1cf0bba3476537318514f0093fcb86af3a94ab2c6"
    )
    assert probe.EXPECTED_BASELINE_SHA256 == (
        "634c50219fb4450332d79b232275854adf648d4c5614eaabf5a961eb9f7bfbf1"
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("materials", 0, "exists"), False),
        (("materials", 1, "stable_during_probe"), False),
        (("dataset_verification", "human_record_lines"), 912),
        (("baseline_verification", "data_rows"), 432),
        (("result_status",), "partial"),
    ],
)
def test_invalid_verified_manifest_fails_closed(path: tuple[object, ...], value: object) -> None:
    instance = copy.deepcopy(valid_manifest())
    target: object = instance
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    assert list(validator().iter_errors(instance))


def test_output_boundary_rejects_repository_tree() -> None:
    probe = load_probe()
    with pytest.raises(ValueError, match="repository"):
        probe.ensure_output_boundary(PROJECT_ROOT / "evidence")


def test_only_read_only_mode_is_exposed() -> None:
    source = PROBE_PATH.read_text(encoding="utf-8")
    assert 'choices=("read-only",)' in source
    assert "subprocess.run" in source
    assert "shell=True" not in source


def test_durable_child_accepts_current_langgraph_result_shape() -> None:
    probe = load_probe()
    assert probe._langgraph_child_passed({"passed": True, "workflow_id": "child"})
    assert probe._langgraph_child_passed([{"passed": True, "workflow_id": "child"}])
    assert probe._langgraph_child_passed([{"result": {"status": "passed"}}])
    assert not probe._langgraph_child_passed({"passed": False})
