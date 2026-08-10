from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import scripts.build_selector_release as selector_release_cli
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


def _rewrite_current_as_legacy_v1(
    runtime: Path,
    built: dict[str, object],
    *,
    marker_path: Path | None = None,
) -> dict[str, object]:
    manifest_path = Path(str(built["release_manifest_ref"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "xinao.selector_release.v1"
    manifest.pop("python_sha256")
    manifest.pop("python_size_bytes")
    if marker_path is not None:
        relative = "services/agent_runtime/routing_policy_reader.py"
        target = Path(str(built["release_root"])) / relative
        target.write_text(
            target.read_text(encoding="utf-8")
            + "\nfrom pathlib import Path as _LegacyMarkerPath\n"
            + f"_LegacyMarkerPath({str(marker_path)!r}).write_text('executed', encoding='utf-8')\n",
            encoding="utf-8",
        )
        target_raw = target.read_bytes()
        target_sha = selector_release._sha_bytes(target_raw)
        for row in manifest["files"]:
            if row["path"] == relative:
                row["sha256"] = target_sha
                row["size_bytes"] = len(target_raw)
        source_capture = manifest["source_capture"]
        for row in source_capture["files"]:
            if row["path"] == relative:
                row["sha256"] = target_sha
                row["size_bytes"] = len(target_raw)
        capture_body = dict(source_capture)
        capture_body.pop("source_capture_sha256")
        source_capture["source_capture_sha256"] = selector_release._sha_bytes(
            selector_release._canonical_bytes(capture_body)
        )
        manifest["selector_source_sha256"] = target_sha
        manifest["probe"]["selector_source_sha256"] = target_sha
    content = dict(manifest)
    content.pop("release_content_sha256")
    manifest["release_content_sha256"] = selector_release._sha_bytes(
        selector_release._canonical_bytes(content)
    )
    manifest_raw = selector_release._json_bytes(manifest)
    manifest_path.write_bytes(manifest_raw)
    pointer_path = runtime / "state" / "grok_supervisor_selector" / "current.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["release_manifest_sha256"] = selector_release._sha_bytes(manifest_raw)
    pointer_raw = selector_release._json_bytes(pointer)
    pointer_path.write_bytes(pointer_raw)
    return {
        "pointer_path": pointer_path,
        "pointer_raw": pointer_raw,
        "manifest_path": manifest_path,
        "manifest_raw": manifest_raw,
        "release_root": Path(str(built["release_root"])),
    }


def _make_legacy_v1_current(
    repo: Path,
    runtime: Path,
    release_id: str,
    *,
    marker_path: Path | None = None,
) -> dict[str, object]:
    built = _build_fast_release(repo, runtime, release_id)
    promote_selector_release(
        runtime,
        release_id=release_id,
        expected_current=selector_release_current_identity(runtime),
    )
    return _rewrite_current_as_legacy_v1(runtime, built, marker_path=marker_path)


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


def test_legacy_v1_release_is_rejected_without_explicit_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    legacy = _make_legacy_v1_current(repo, runtime, "legacy-schema")
    _build_fast_release(repo, runtime, "normal-candidate")
    pointer = Path(str(legacy["pointer_path"]))
    legacy_present = {
        "state": "PRESENT",
        "release_id": "legacy-schema",
        "pointer_sha256": selector_release._sha_bytes(pointer.read_bytes()),
    }

    with pytest.raises(SelectorReleaseError, match="schema mismatch"):
        validate_selector_release_pointer(pointer)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_selector_release.py",
            "--runtime-root",
            str(runtime),
            "--show-current",
        ],
    )
    assert selector_release_cli.main() == 20
    assert "manifest schema mismatch" in capsys.readouterr().err
    with pytest.raises(SelectorReleaseError, match="schema mismatch"):
        promote_selector_release(
            runtime,
            release_id="normal-candidate",
            expected_current=legacy_present,
        )
    with pytest.raises(SelectorReleaseError, match="schema mismatch"):
        build_selector_release(
            source_root=repo,
            runtime_root=runtime,
            release_id="normal-build-must-not-migrate",
            python_executable=Path(sys.executable),
            create_venv=False,
            promote=True,
        )
    explicit_legacy = selector_release.selector_release_legacy_v1_migration_identity(runtime)
    with pytest.raises(SelectorReleaseError, match="forbidden for normal promotion"):
        promote_selector_release(
            runtime,
            release_id="normal-candidate",
            expected_current=explicit_legacy,
        )
    assert pointer.read_bytes() == legacy["pointer_raw"]


@pytest.mark.parametrize(
    "argv",
    (
        ("--release-id", "candidate", "--migrate-current-v1"),
        ("--show-current", "--promote", "--migrate-current-v1"),
    ),
)
def test_legacy_v1_cli_flag_requires_dedicated_promote_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    argv: tuple[str, ...],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_selector_release.py",
            "--runtime-root",
            str(tmp_path / "runtime"),
            *argv,
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        selector_release_cli.main()

    assert exc_info.value.code == 2


def test_legacy_v1_cli_forwards_explicit_migration_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}

    def fake_build(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"status": "release_built_and_migrated_from_legacy_v1"}

    monkeypatch.setattr(selector_release_cli, "build_selector_release", fake_build)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_selector_release.py",
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--release-id",
            "v2-candidate",
            "--promote",
            "--migrate-current-v1",
            "--no-venv",
        ],
    )

    assert selector_release_cli.main() == 0
    assert observed["promote"] is True
    assert observed["migrate_current_v1"] is True
    assert json.loads(capsys.readouterr().out)["status"] == (
        "release_built_and_migrated_from_legacy_v1"
    )


def test_explicit_legacy_v1_migration_promotes_strict_v2_without_executing_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    marker = tmp_path / "legacy-code-executed.txt"
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    legacy = _make_legacy_v1_current(
        repo,
        runtime,
        "legacy-current",
        marker_path=marker,
    )
    _build_fast_release(repo, runtime, "v2-candidate")
    legacy_root = Path(str(legacy["release_root"]))
    legacy_tree = {
        path.relative_to(legacy_root).as_posix(): path.read_bytes()
        for path in legacy_root.rglob("*")
        if path.is_file()
    }
    expected = selector_release.selector_release_legacy_v1_migration_identity(runtime)

    result = promote_selector_release(
        runtime,
        release_id="v2-candidate",
        expected_current=expected,
        migrate_current_v1=True,
    )

    assert result["status"] == "release_migrated_from_legacy_v1"
    assert result["migration"]["from"] == expected
    assert result["migration"]["to"]["release_id"] == "v2-candidate"
    assert result["migration"]["completion_claim_allowed"] is False
    assert result["completion_claim_allowed"] is False
    current = load_current_selector_release(runtime)
    assert current["release_id"] == "v2-candidate"
    assert current["release_manifest"]["schema_version"] == "xinao.selector_release.v2"
    assert not marker.exists()
    assert legacy["manifest_path"].read_bytes() == legacy["manifest_raw"]
    assert {
        path.relative_to(legacy_root).as_posix(): path.read_bytes()
        for path in legacy_root.rglob("*")
        if path.is_file()
    } == legacy_tree


def test_build_api_performs_one_shot_legacy_v1_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    _make_legacy_v1_current(repo, runtime, "legacy-build-api")

    result = build_selector_release(
        source_root=repo,
        runtime_root=runtime,
        release_id="v2-built-and-migrated",
        python_executable=Path(sys.executable),
        create_venv=False,
        promote=True,
        migrate_current_v1=True,
    )

    assert result["status"] == "release_built_and_migrated_from_legacy_v1"
    assert result["migration"]["from"]["state"] == "LEGACY_V1_PRESENT"
    assert load_current_selector_release(runtime)["release_id"] == "v2-built-and-migrated"


@pytest.mark.parametrize(
    "damage",
    (
        "pointer_manifest_hash",
        "manifest_content_seal",
        "manifest_moved",
        "pointer_moved",
        "release_root_dotdot",
        "manifest_external",
    ),
)
def test_legacy_v1_migration_rejects_tampered_or_moved_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / damage
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    legacy = _make_legacy_v1_current(repo, runtime, f"legacy-{damage}")
    pointer_path = Path(str(legacy["pointer_path"]))
    manifest_path = Path(str(legacy["manifest_path"]))
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    if damage == "pointer_manifest_hash":
        pointer["release_manifest_sha256"] = "0" * 64
        pointer_path.write_bytes(selector_release._json_bytes(pointer))
    elif damage == "manifest_content_seal":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_root"] = str(tmp_path / "redirected-source")
        manifest_raw = selector_release._json_bytes(manifest)
        manifest_path.write_bytes(manifest_raw)
        pointer["release_manifest_sha256"] = selector_release._sha_bytes(manifest_raw)
        pointer_path.write_bytes(selector_release._json_bytes(pointer))
    elif damage == "manifest_moved":
        moved = manifest_path.with_name("moved-release-manifest.json")
        manifest_path.rename(moved)
        pointer["release_manifest_ref"] = str(moved)
        pointer_path.write_bytes(selector_release._json_bytes(pointer))
    elif damage == "pointer_moved":
        pointer_path.rename(pointer_path.with_name("moved-current.json"))
    elif damage == "release_root_dotdot":
        release_root = Path(str(legacy["release_root"]))
        pointer["release_root"] = str(
            release_root.parent / "unused-segment" / ".." / release_root.name
        )
        pointer_path.write_bytes(selector_release._json_bytes(pointer))
    else:
        external = tmp_path / "external-manifest.json"
        external.write_bytes(manifest_path.read_bytes())
        pointer["release_manifest_ref"] = str(external)
        pointer_path.write_bytes(selector_release._json_bytes(pointer))

    with pytest.raises(SelectorReleaseError):
        selector_release.selector_release_legacy_v1_migration_identity(runtime)


@pytest.mark.parametrize(
    "reparse_leaf",
    ("pointer", "manifest", "release_root", "runtime_root"),
)
def test_legacy_v1_migration_rejects_prepositioned_reparse_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reparse_leaf: str,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / reparse_leaf
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    legacy = _make_legacy_v1_current(repo, runtime, f"legacy-{reparse_leaf}")
    pointer_path = Path(str(legacy["pointer_path"]))
    manifest_path = Path(str(legacy["manifest_path"]))
    release_root = Path(str(legacy["release_root"]))
    observed_runtime = runtime
    try:
        if reparse_leaf == "pointer":
            external = tmp_path / "identical-current.json"
            external.write_bytes(pointer_path.read_bytes())
            pointer_path.unlink()
            pointer_path.symlink_to(external)
        elif reparse_leaf == "manifest":
            external = tmp_path / "identical-manifest.json"
            external.write_bytes(manifest_path.read_bytes())
            manifest_path.unlink()
            manifest_path.symlink_to(external)
        elif reparse_leaf == "release_root":
            physical = release_root.with_name(release_root.name + "-physical")
            release_root.rename(physical)
            release_root.symlink_to(physical, target_is_directory=True)
        else:
            observed_runtime = tmp_path / "runtime-alias"
            observed_runtime.symlink_to(runtime, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(SelectorReleaseError, match="reparse"):
        selector_release.selector_release_legacy_v1_migration_identity(observed_runtime)


def test_legacy_v1_migration_rejects_absent_v2_unknown_and_repeat_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    with pytest.raises(SelectorReleaseError, match="legacy v1"):
        build_selector_release(
            source_root=repo,
            runtime_root=tmp_path / "absent",
            release_id="must-not-be-created",
            python_executable=Path(sys.executable),
            create_venv=False,
            promote=True,
            migrate_current_v1=True,
        )
    assert not (
        tmp_path
        / "absent"
        / "state"
        / "grok_supervisor_selector"
        / "releases"
        / "must-not-be-created"
    ).exists()

    runtime = tmp_path / "runtime"
    legacy = _make_legacy_v1_current(repo, runtime, "legacy-once")
    _build_fast_release(repo, runtime, "v2-current")
    expected = selector_release.selector_release_legacy_v1_migration_identity(runtime)
    promote_selector_release(
        runtime,
        release_id="v2-current",
        expected_current=expected,
        migrate_current_v1=True,
    )
    pointer_path = Path(str(legacy["pointer_path"]))
    v2_pointer = pointer_path.read_bytes()
    with pytest.raises(SelectorReleaseError, match="legacy v1"):
        selector_release.selector_release_legacy_v1_migration_identity(runtime)
    with pytest.raises(SelectorReleaseError, match="legacy v1"):
        build_selector_release(
            source_root=repo,
            runtime_root=runtime,
            release_id="repeat-migration-must-not-build",
            python_executable=Path(sys.executable),
            create_venv=False,
            promote=True,
            migrate_current_v1=True,
        )
    assert pointer_path.read_bytes() == v2_pointer
    normal = promote_selector_release(
        runtime,
        release_id="v2-current",
        expected_current=selector_release_current_identity(runtime),
    )
    assert normal["status"] == "release_already_current"

    unknown_runtime = tmp_path / "unknown"
    unknown = _make_legacy_v1_current(repo, unknown_runtime, "legacy-unknown")
    unknown_manifest_path = Path(str(unknown["manifest_path"]))
    unknown_manifest = json.loads(unknown_manifest_path.read_text(encoding="utf-8"))
    unknown_manifest["schema_version"] = "xinao.selector_release.unknown"
    content = dict(unknown_manifest)
    content.pop("release_content_sha256")
    unknown_manifest["release_content_sha256"] = selector_release._sha_bytes(
        selector_release._canonical_bytes(content)
    )
    unknown_raw = selector_release._json_bytes(unknown_manifest)
    unknown_manifest_path.write_bytes(unknown_raw)
    unknown_pointer_path = Path(str(unknown["pointer_path"]))
    unknown_pointer = json.loads(unknown_pointer_path.read_text(encoding="utf-8"))
    unknown_pointer["release_manifest_sha256"] = selector_release._sha_bytes(unknown_raw)
    unknown_pointer_path.write_bytes(selector_release._json_bytes(unknown_pointer))
    with pytest.raises(SelectorReleaseError, match="legacy v1"):
        selector_release.selector_release_legacy_v1_migration_identity(unknown_runtime)


def test_legacy_v1_migration_stale_cas_rejects_concurrent_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    _make_legacy_v1_current(repo, runtime, "legacy-stale")
    _build_fast_release(repo, runtime, "winner")
    _build_fast_release(repo, runtime, "stale")
    stale_expected = selector_release.selector_release_legacy_v1_migration_identity(runtime)
    promote_selector_release(
        runtime,
        release_id="winner",
        expected_current=stale_expected,
        migrate_current_v1=True,
    )

    with pytest.raises(SelectorReleaseError, match="changed"):
        promote_selector_release(
            runtime,
            release_id="stale",
            expected_current=stale_expected,
            migrate_current_v1=True,
        )
    assert load_current_selector_release(runtime)["release_id"] == "winner"


def test_legacy_v1_migration_is_recoverable_after_replace_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(selector_release, "_probe_release", _fast_probe)
    legacy = _make_legacy_v1_current(repo, runtime, "legacy-crash")
    real_validate = selector_release.validate_selector_release_pointer
    pointer_path = Path(str(legacy["pointer_path"]))

    def crash_on_committed_readback(path: Path) -> dict[str, object]:
        if Path(path) == pointer_path and json.loads(pointer_path.read_text(encoding="utf-8"))[
            "release_id"
        ] == "v2-after-crash":
            raise RuntimeError("simulated process crash after pointer replace")
        return real_validate(path)

    monkeypatch.setattr(
        selector_release,
        "validate_selector_release_pointer",
        crash_on_committed_readback,
    )
    with pytest.raises(RuntimeError, match="simulated process crash"):
        build_selector_release(
            source_root=repo,
            runtime_root=runtime,
            release_id="v2-after-crash",
            python_executable=Path(sys.executable),
            create_venv=False,
            promote=True,
            migrate_current_v1=True,
        )
    monkeypatch.setattr(selector_release, "validate_selector_release_pointer", real_validate)

    assert load_current_selector_release(runtime)["release_id"] == "v2-after-crash"
    assert (
        runtime
        / "state"
        / "grok_supervisor_selector"
        / "releases"
        / "v2-after-crash"
    ).is_dir()
    assert Path(str(legacy["manifest_path"])).read_bytes() == legacy["manifest_raw"]


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
