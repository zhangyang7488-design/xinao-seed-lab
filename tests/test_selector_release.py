from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from services.agent_runtime import selector_release
from services.agent_runtime.selector_release import (
    RELEASE_FILES,
    REQUIRED_DISTRIBUTIONS,
    SelectorReleaseError,
    _locked_requirement_specs,
    _probe_release,
    build_selector_release,
    load_current_selector_release,
    promote_selector_release,
    selector_release_current_identity,
    validate_selector_release_pointer,
)


def _write_release_lock(path: Path, names: tuple[str, ...]) -> None:
    rows = ["version = 1", "revision = 3"]
    for name in names:
        rows.extend(["", "[[package]]", f'name = "{name}"', 'version = "1.2.3"'])
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _copy_release_source(source: Path, destination: Path) -> None:
    for relative_text in (*RELEASE_FILES, "uv.lock"):
        origin = source / relative_text
        target = destination / relative_text
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)


def _fast_probe(release_root: Path, python_executable: Path) -> dict[str, object]:
    selector = release_root / "services" / "agent_runtime" / "routing_policy_reader.py"
    return {
        "selector_source_sha256": selector_release._sha_file(selector),
        "python_executable": str(selector_release._absolute_executable(python_executable)),
    }


def _build_fast_release(repo: Path, runtime: Path, release_id: str) -> dict[str, object]:
    return build_selector_release(
        source_root=repo,
        runtime_root=runtime,
        release_id=release_id,
        python_executable=Path(sys.executable),
        create_venv=False,
        promote=False,
    )


def test_release_dependencies_are_exactly_derived_from_uv_lock(tmp_path: Path) -> None:
    _write_release_lock(tmp_path / "uv.lock", REQUIRED_DISTRIBUTIONS)

    assert _locked_requirement_specs(tmp_path) == tuple(
        f"{name}==1.2.3" for name in REQUIRED_DISTRIBUTIONS
    )


def test_release_dependency_bootstrap_rejects_incomplete_lock(tmp_path: Path) -> None:
    _write_release_lock(tmp_path / "uv.lock", REQUIRED_DISTRIBUTIONS[:-1])

    with pytest.raises(SelectorReleaseError, match="not uniquely pinned"):
        _locked_requirement_specs(tmp_path)


def test_build_rejects_selected_source_drift_instead_of_publishing_mixed_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    _copy_release_source(repo, source)

    def drift_after_copy(release_root: Path, python_executable: Path) -> dict[str, object]:
        del python_executable
        selected = source / "services" / "__init__.py"
        selected.write_bytes(selected.read_bytes() + b"\n# concurrent drift\n")
        selector = release_root / "services" / "agent_runtime" / "routing_policy_reader.py"
        return {
            "selector_source_sha256": selector_release._sha_file(selector),
            "python_executable": str(Path(sys.executable).absolute()),
        }

    monkeypatch.setattr(selector_release, "_probe_release", drift_after_copy)

    with pytest.raises(SelectorReleaseError, match="source.*changed|source.*drift"):
        build_selector_release(
            source_root=source,
            runtime_root=runtime,
            release_id="selector-drift",
            python_executable=Path(sys.executable),
            create_venv=False,
            promote=False,
        )
    assert not (
        runtime / "state" / "grok_supervisor_selector" / "releases" / "selector-drift"
    ).exists()


def test_promotion_absent_cas_has_one_commit_stale_reject_and_exact_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    _build_fast_release(repo, runtime, "candidate-a")
    _build_fast_release(repo, runtime, "candidate-b")
    expected_absent = selector_release_current_identity(runtime)
    assert expected_absent == {"state": "ABSENT"}
    assert not (runtime / "state" / "grok_supervisor_selector" / ".promotion.lock").exists()
    barrier = threading.Barrier(2)

    def attempt(release_id: str) -> tuple[str, str]:
        barrier.wait(timeout=5)
        try:
            result = promote_selector_release(
                runtime,
                release_id=release_id,
                expected_current=expected_absent,
            )
            return release_id, str(result["status"])
        except SelectorReleaseError as exc:
            return release_id, str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("candidate-a", "candidate-b")))

    committed = [release_id for release_id, status in results if status == "release_promoted"]
    rejected = [status for _, status in results if "current pointer changed" in status]
    assert len(committed) == 1
    assert len(rejected) == 1
    current = selector_release_current_identity(runtime)
    assert current["state"] == "PRESENT"
    assert current["release_id"] == committed[0]

    retry = promote_selector_release(
        runtime,
        release_id=committed[0],
        expected_current=expected_absent,
    )
    assert retry["status"] == "release_already_current"
    assert retry["pointer_sha256"] == current["pointer_sha256"]
    state_dir = runtime / "state" / "grok_supervisor_selector"
    assert not list(state_dir.glob("current.json.candidate.*"))


def test_pointer_reader_observes_only_complete_old_or_new_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    _build_fast_release(repo, runtime, "reader-old")
    _build_fast_release(repo, runtime, "reader-new")
    absent = selector_release_current_identity(runtime)
    promote_selector_release(
        runtime,
        release_id="reader-old",
        expected_current=absent,
    )
    expected_old = selector_release_current_identity(runtime)
    pointer = runtime / "state" / "grok_supervisor_selector" / "current.json"
    old_raw = pointer.read_bytes()
    real_replace = selector_release.os.replace
    replacement_started = threading.Event()

    def delayed_replace(source: object, destination: object) -> None:
        if Path(destination).resolve(strict=False) == pointer.resolve(strict=False):
            replacement_started.set()
            time.sleep(0.05)
        real_replace(source, destination)

    monkeypatch.setattr(selector_release.os, "replace", delayed_replace)
    observed = {old_raw}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            promote_selector_release,
            runtime,
            release_id="reader-new",
            expected_current=expected_old,
        )
        assert replacement_started.wait(timeout=5)
        while not future.done():
            try:
                observed.add(pointer.read_bytes())
            except PermissionError:
                # NTFS may briefly sharing-deny an uncoordinated raw reader at
                # the replace syscall; it must never return partial bytes.
                pass
            time.sleep(0.001)
        promoted = future.result(timeout=5)
    new_raw = pointer.read_bytes()
    observed.add(new_raw)

    assert promoted["status"] == "release_promoted"
    assert old_raw != new_raw
    assert observed <= {old_raw, new_raw}
    assert {json.loads(raw)["release_id"] for raw in observed} == {
        "reader-old",
        "reader-new",
    }


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

    promoted = promote_selector_release(
        runtime,
        release_id="selector-test-1",
        expected_current=selector_release_current_identity(runtime),
    )
    assert promoted["status"] == "release_promoted"
    current = load_current_selector_release(runtime)
    assert current["release_id"] == "selector-test-1"
    assert current["release_manifest"]["schema_version"] == "xinao.selector_release.v2"
    assert current["selector_source_sha256"] == built["selector_source_sha256"]
    assert Path(current["release_root"]) != repo
    assert current["execution_binding"]["schema_version"] == (
        "xinao.selector_release_execution_binding.v1"
    )
    assert [row["path"] for row in current["execution_binding"]["files"]] == list(
        RELEASE_FILES
    )
    assert current["execution_binding"]["python"]["sha256"] == current[
        "release_manifest"
    ]["python_sha256"]
    assert current["release_manifest"]["probe"]["dependency_distributions"]["jsonschema"]
    assert current["release_manifest"]["probe"]["dependency_distributions"]["portalocker"]
    assert current["release_manifest"]["probe"]["dispatch_route_claim_callable"] is True
    assert current["release_manifest"]["probe"]["task_local_checkpoint_preparer_callable"] is True
    assert current["release_manifest"]["probe"]["package_task_run_preparer_callable"] is True
    assert current["release_manifest"]["probe"]["contract_preparer_help"] is True
    assert Path(current["release_manifest"]["probe"]["action_resume_module"]) == (
        Path(current["release_root"]) / "services" / "agent_runtime" / "action_resume_receipt.py"
    )
    assert (
        Path(current["release_root"]) / "services" / "agent_runtime" / "work_unit_lifecycle.py"
    ).is_file()

    # A stale or unrelated task cwd is not an input to pointer resolution.
    stale_task_cwd = tmp_path / "stale-task-cwd"
    stale_task_cwd.mkdir()
    assert validate_selector_release_pointer(Path(promoted["pointer_path"]))["release_id"] == (
        "selector-test-1"
    )


def test_selector_release_probe_rejects_missing_task_local_checkpoint_preparer(
    tmp_path: Path,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    built = build_selector_release(
        source_root=repo,
        runtime_root=runtime,
        release_id="selector-test-missing-checkpoint-preparer",
        python_executable=Path(sys.executable),
        create_venv=False,
        promote=False,
    )
    action_resume = (
        Path(built["release_root"]) / "services" / "agent_runtime" / "action_resume_receipt.py"
    )
    source = action_resume.read_text(encoding="utf-8")
    assert "def prepare_task_local_checkpoint(" in source
    action_resume.write_text(
        source.replace(
            "def prepare_task_local_checkpoint(",
            "def _missing_task_local_checkpoint_preparer(",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(SelectorReleaseError, match="import probe failed"):
        _probe_release(Path(built["release_root"]), Path(sys.executable))


def test_selector_release_probe_rejects_missing_package_task_run_preparer(
    tmp_path: Path,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    built = build_selector_release(
        source_root=repo,
        runtime_root=runtime,
        release_id="selector-test-missing-package-task-run-preparer",
        python_executable=Path(sys.executable),
        create_venv=False,
        promote=False,
    )
    dispatch_economics = (
        Path(built["release_root"]) / "services" / "agent_runtime" / "dispatch_economics.py"
    )
    source = dispatch_economics.read_text(encoding="utf-8")
    assert "def prepare_worker_package_task_run(" in source
    dispatch_economics.write_text(
        source.replace(
            "def prepare_worker_package_task_run(",
            "def _missing_package_task_run_preparer(",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(SelectorReleaseError, match="import probe failed"):
        _probe_release(Path(built["release_root"]), Path(sys.executable))


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


def test_manifest_swap_after_hash_before_parse_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    built = _build_fast_release(repo, runtime, "manifest-swap")
    promote_selector_release(
        runtime,
        release_id="manifest-swap",
        expected_current=selector_release_current_identity(runtime),
    )
    manifest_path = Path(str(built["release_manifest_ref"]))
    malicious = json.loads(manifest_path.read_text(encoding="utf-8"))
    malicious["source_root"] = str(tmp_path / "redirected-source")
    content = dict(malicious)
    content.pop("release_content_sha256")
    malicious["release_content_sha256"] = selector_release._sha_bytes(
        selector_release._canonical_bytes(content)
    )
    malicious_raw = selector_release._json_bytes(malicious)
    real_decode = selector_release._decode_object
    swapped = False

    def swap_then_decode(raw: bytes, *, path: Path, label: str) -> dict[str, object]:
        nonlocal swapped
        if path == manifest_path and not swapped:
            manifest_path.write_bytes(malicious_raw)
            swapped = True
        return real_decode(raw, path=path, label=label)

    monkeypatch.setattr(selector_release, "_decode_object", swap_then_decode)

    pointer = runtime / "state" / "grok_supervisor_selector" / "current.json"
    with pytest.raises(SelectorReleaseError, match="manifest changed during validation"):
        validate_selector_release_pointer(pointer)
    assert swapped is True


def test_legacy_v1_release_manifest_requires_fresh_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    built = _build_fast_release(repo, runtime, "legacy-schema")
    promote_selector_release(
        runtime,
        release_id="legacy-schema",
        expected_current=selector_release_current_identity(runtime),
    )
    manifest_path = Path(str(built["release_manifest_ref"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "xinao.selector_release.v1"
    content = dict(manifest)
    content.pop("release_content_sha256")
    manifest["release_content_sha256"] = selector_release._sha_bytes(
        selector_release._canonical_bytes(content)
    )
    manifest_raw = selector_release._json_bytes(manifest)
    manifest_path.write_bytes(manifest_raw)
    pointer = runtime / "state" / "grok_supervisor_selector" / "current.json"
    pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
    pointer_payload["release_manifest_sha256"] = selector_release._sha_bytes(manifest_raw)
    pointer.write_bytes(selector_release._json_bytes(pointer_payload))

    with pytest.raises(SelectorReleaseError, match="schema mismatch"):
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
