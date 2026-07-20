from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from services.agent_runtime.selector_release import (
    SelectorReleaseError,
    build_selector_release,
    load_current_selector_release,
    promote_selector_release,
    validate_selector_release_pointer,
)


def test_versioned_selector_release_is_not_task_cwd_dependent(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    built = build_selector_release(
        source_root=repo,
        runtime_root=runtime,
        release_id="selector-test-1",
        python_executable=Path(sys.executable),
        create_venv=False,
        promote=False,
    )
    assert built["status"] == "release_built"
    assert not (runtime / "state" / "grok_supervisor_selector" / "current.json").exists()

    promoted = promote_selector_release(runtime, release_id="selector-test-1")
    assert promoted["status"] == "release_promoted"
    current = load_current_selector_release(runtime)
    assert current["release_id"] == "selector-test-1"
    assert current["selector_source_sha256"] == built["selector_source_sha256"]
    assert Path(current["release_root"]) != repo
    assert current["release_manifest"]["probe"]["dependency_distributions"]["jsonschema"]
    assert current["release_manifest"]["probe"]["dispatch_route_claim_callable"] is True
    assert Path(current["release_manifest"]["probe"]["action_resume_module"]) == (
        Path(current["release_root"]) / "services" / "agent_runtime" / "action_resume_receipt.py"
    )

    # A stale or unrelated task cwd is not an input to pointer resolution.
    stale_task_cwd = tmp_path / "stale-task-cwd"
    stale_task_cwd.mkdir()
    assert validate_selector_release_pointer(Path(promoted["pointer_path"]))["release_id"] == (
        "selector-test-1"
    )


def test_selector_release_hash_drift_fails_closed(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    built = build_selector_release(
        source_root=repo,
        runtime_root=runtime,
        release_id="selector-test-2",
        python_executable=Path(sys.executable),
        create_venv=False,
        promote=True,
    )
    selector = (
        Path(built["release_root"]) / "services" / "agent_runtime" / "routing_policy_reader.py"
    )
    selector.write_text(selector.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    pointer = runtime / "state" / "grok_supervisor_selector" / "current.json"
    with pytest.raises(SelectorReleaseError, match="release file hash mismatch"):
        validate_selector_release_pointer(pointer)


def test_selector_pointer_never_scans_arbitrary_worktrees(tmp_path: Path) -> None:
    pointer = tmp_path / "current.json"
    pointer.write_text(
        json.dumps(
            {
                "schema_version": "xinao.selector_release_pointer.v1",
                "release_id": "missing",
                "release_root": str(tmp_path / "worktrees" / "maybe-compatible"),
                "release_manifest_ref": str(tmp_path / "missing.json"),
                "release_manifest_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SelectorReleaseError, match="release manifest missing"):
        validate_selector_release_pointer(pointer)
